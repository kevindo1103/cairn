from __future__ import annotations

import sqlite3
from contextlib import closing
import time
from pathlib import Path

from .common import Refused, digest, finding, no_symlinks, read_bytes
from .coverage import inspect_model_scope, scope_findings


def check_database(db: Path, models: bytes, classes: list[str], expected_revision: str) -> list[dict]:
    """Only accept an explicit, standalone offline copy. No repair/stamp/DDL."""
    path = no_symlinks(db)
    if any(Path(str(path) + suffix).exists() for suffix in ["-wal", "-shm", "-journal"]):
        raise Refused("DATABASE_NOT_STANDALONE")
    before = read_bytes(path, 512 * 1024 * 1024)
    if before[:16] != b"SQLite format 3\0":
        raise Refused("DATABASE_FORMAT")
    expected, coverage = inspect_model_scope(models, classes)
    by_table = {item["table"]: item["model"] for item in coverage["resolved"]}
    output = []
    deadline = time.monotonic() + 10
    try:
        with closing(sqlite3.connect(path.as_uri() + "?mode=ro&immutable=1", uri=True, timeout=1)) as con, con:
            con.execute("PRAGMA query_only=ON")
            con.set_progress_handler(lambda: int(time.monotonic() >= deadline), 1000)
            versions = sorted(row[0] for row in con.execute("SELECT version_num FROM alembic_version"))
            revision_ok = versions == [expected_revision]
            output.append(finding("K04", "PASS" if revision_ok else "FAIL",
                                  "REVISION_MATCH" if revision_ok else "REVISION_MISMATCH",
                                  details={"expected_revision": expected_revision, "observed_revisions": versions}))
            for table, columns in expected.items():
                present = {r[1] for r in con.execute('PRAGMA table_info("' + table + '")')}
                missing = sorted(set(columns) - present)
                output.append(finding("K04B", "FAIL" if missing else "PASS",
                                      "MODEL_MIGRATION_MISMATCH" if missing else "MODEL_COLUMNS_PRESENT",
                                      details={"model": by_table[table], "table": table, "missing_columns": missing,
                                               "inspected_column_names": columns,
                                               "inspected_columns": len(columns), "types_constraints_indexes": "NOT_CHECKED",
                                               "database_sha256": digest(before),
                                               "migration_execution_provenance": "CALLER_SUPPLIED_COPY_NOT_ATTESTED"}))
    except sqlite3.Error as exc:
        raise Refused("DATABASE_INSPECTION_FAILED") from exc
    if digest(read_bytes(path, 512 * 1024 * 1024)) != digest(before):
        raise Refused("DATABASE_CHANGED")
    if any(Path(str(path) + suffix).exists() for suffix in ["-wal", "-shm", "-journal"]):
        raise Refused("DATABASE_CHANGED")
    output.extend(scope_findings(coverage))
    return output
