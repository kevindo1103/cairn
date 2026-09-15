"""SQLite-consistent copies into NEW paths only; never restore over a live DB."""

import hashlib
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from comms_ledger.ledger import EXPECTED_SCHEMA_VERSION
from .store import Rejected, canonical


def snapshot(connection):
    """Caller holds a SQLite read transaction, so all tables share one snapshot."""
    tables = connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table' ORDER BY name").fetchall()
    data = {}
    for name, sql in tables:
        quoted = '"' + name.replace('"', '""') + '"'
        columns = [r[1] for r in connection.execute("PRAGMA table_info(" + quoted + ")")]
        rows = [list(r) for r in connection.execute("SELECT * FROM " + quoted)]
        data[name] = {"schema": sql, "columns": columns, "rows": sorted(rows, key=canonical)}
    config = dict(connection.execute("SELECT key,value FROM config"))
    if config.get("schema_version") != EXPECTED_SCHEMA_VERSION:
        raise Rejected("Unsupported backup schema")
    if "adapter:project" not in config or "pm_task" not in config:
        raise Rejected("Backup missing project/PM binding")
    schema = [list(r) for r in connection.execute("SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name")]
    high = connection.execute("SELECT COALESCE(MAX(seq),0) FROM history").fetchone()[0]
    registry = json.loads(config["adapter:registry"])
    authority = connection.execute("SELECT revision,task_id,event_id,receipt FROM pm_authority ORDER BY revision DESC LIMIT 1").fetchone()
    if authority is None:
        raise Rejected("Backup missing PM authority")
    return {"digest": hashlib.sha256(canonical({"schema": schema, "data": data}).encode()).hexdigest(),
            "history_high_water": high, "schema_version": config["schema_version"],
            "project": json.loads(config["adapter:project"]), "pm_task": config["pm_task"],
            "pm_authority": dict(revision=authority[0], task_id=authority[1], event_id=authority[2], receipt=json.loads(authority[3])),
            "package": json.loads(config["adapter:package"]), "registry_revision": registry["revision"],
            "generations": {e["task_id"]: e["generation"] for e in registry["entries"]},
            "tables": {k: len(v["rows"]) for k, v in data.items()}}


def proof(path):
    path = Path(path).resolve()
    with closing(sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)) as db:
        db.execute("BEGIN")
        if db.execute("PRAGMA integrity_check").fetchone()[0] != "ok" or db.execute("PRAGMA foreign_key_check").fetchall():
            raise Rejected("SQLite integrity check failed")
        return snapshot(db)


def backup(source, destination):
    source, destination = Path(source).resolve(), Path(destination).resolve()
    if source == destination:
        raise Rejected("Backup may not overwrite source")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with destination.open("xb"):
        pass
    with closing(sqlite3.connect(source.as_uri() + "?mode=ro", uri=True)) as src:
        src.execute("BEGIN")
        expected = snapshot(src)  # establish and retain a stable read snapshot, including WAL
        with closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
    actual = proof(destination)
    if actual != expected:
        raise Rejected("Backup snapshot mismatch")
    return actual


def restore(source, new_project_root, expected_proof, project):
    """Host-only offline recovery rehearsal. Replay/activation is a separate decision."""
    if expected_proof.get("project") != project or proof(source) != expected_proof:
        raise Rejected("Restore requires exact independently retained proof and project binding")
    destination = Path(new_project_root).resolve() / "ledger.sqlite"
    result = backup(source, destination)
    if result != expected_proof:
        raise Rejected("Restored snapshot differs from accepted backup")
    return result
