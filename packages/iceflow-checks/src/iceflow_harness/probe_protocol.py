"""Small, stdlib-only protocol shared by the host runner and exported worker.

Diagnostics are finite codes, never exception messages, SQL, locals or stderr.
This validates shape, not the trustworthiness of code running in the sandbox.
"""
from __future__ import annotations

import re

SCHEMA = "migration-probe-v2"
PHASES = frozenset({"SANDBOX_CHECK", "COPY_SOURCE", "SETUP_ENVIRONMENT",
                    "IMPORT_DEPENDENCIES", "CONFIGURE_ALEMBIC", "ALEMBIC_UPGRADE",
                    "INSPECT_DATABASE", "COMPLETE"})
CLASSES = frozenset({"None", "OtherException", "TenantContextRefused", "RuntimeError",
                     "TimeoutError", "ImportError", "ModuleNotFoundError", "OSError",
                     "FileNotFoundError", "PermissionError", "OperationalError",
                     "DatabaseError", "IntegrityError", "ProgrammingError", "ValueError",
                     "TypeError", "SystemExit", "KeyboardInterrupt"})
REFUSALS = {
    "tenant-context-refused:settings-environment": "TENANT_SETTINGS_ENVIRONMENT_MISMATCH",
    "tenant-context-refused:settings-tenant": "TENANT_SETTINGS_TENANT_MISMATCH",
    "tenant-context-refused:settings-root": "TENANT_SETTINGS_ROOT_MISMATCH",
}
REASONS = frozenset({"SANDBOX_REQUIRED", "PROBE_DB_MISSING", "MODEL_CREATE_ALL_FORBIDDEN",
                     "TENANT_CONTEXT_REFUSED", "PROBE_TIMEOUT", "PROBE_INTERRUPTED",
                     "PROBE_PROCESS_EXIT", "DEPENDENCY_IMPORT_FAILED", "PROBE_FILE_MISSING",
                     "PROBE_PERMISSION_DENIED", "PROBE_OS_ERROR", "DATABASE_OPERATION_FAILED",
                     "MIGRATION_SETUP_FAILED"}) | frozenset(REFUSALS.values())


def blocked(reason: str, phase: str, exception_class: str = "None") -> dict:
    if reason not in REASONS or phase not in PHASES or exception_class not in CLASSES:
        raise ValueError("PROBE_DIAGNOSTIC_INVALID")
    return {"schema": SCHEMA, "status": "BLOCKED", "diagnostic": {
        "phase": phase, "reason": reason, "exception_class": exception_class}}


def failure(exc: BaseException, phase: str) -> dict:
    """Only recognize exact finite messages; never call str(exc) or format a traceback."""
    cls = type(exc).__name__
    cls = cls if cls in CLASSES else "OtherException"
    args = exc.args
    token = args[0] if len(args) == 1 and type(args[0]) is str else None
    reason = "MIGRATION_SETUP_FAILED"
    if cls == "TenantContextRefused":
        reason = REFUSALS.get(token, "TENANT_CONTEXT_REFUSED")
    elif cls == "RuntimeError" and token == "MODEL_CREATE_ALL_FORBIDDEN_IN_PARITY_FIXTURE":
        reason = "MODEL_CREATE_ALL_FORBIDDEN"
    elif cls == "RuntimeError" and token == "PROBE_DB_MISSING":
        reason = "PROBE_DB_MISSING"
    elif isinstance(exc, TimeoutError):
        reason = "PROBE_TIMEOUT"
    elif isinstance(exc, KeyboardInterrupt):
        reason = "PROBE_INTERRUPTED"
    elif isinstance(exc, SystemExit):
        reason = "PROBE_PROCESS_EXIT"
    elif isinstance(exc, ImportError):
        reason = "DEPENDENCY_IMPORT_FAILED"
    elif isinstance(exc, FileNotFoundError):
        reason = "PROBE_FILE_MISSING"
    elif isinstance(exc, PermissionError):
        reason = "PROBE_PERMISSION_DENIED"
    elif isinstance(exc, OSError):
        reason = "PROBE_OS_ERROR"
    elif cls in {"OperationalError", "DatabaseError", "IntegrityError", "ProgrammingError"}:
        reason = "DATABASE_OPERATION_FAILED"
    return blocked(reason, phase, cls)


def validate_result(value: object) -> dict:
    """Reject unknown states/extra diagnostics instead of printing untrusted payloads."""
    def require(condition: bool) -> None:
        if not condition:
            raise ValueError("PROBE_RESULT_INVALID")

    require(type(value) is dict)
    require(value.get("schema") == SCHEMA)
    if value.get("status") == "BLOCKED":
        require(set(value) == {"schema", "status", "diagnostic"})
        diag = value["diagnostic"]
        require(type(diag) is dict and set(diag) == {"phase", "reason", "exception_class"})
        for key, allowed in (("phase", PHASES - {"COMPLETE"}), ("reason", REASONS),
                             ("exception_class", CLASSES)):
            require(type(diag[key]) is str and diag[key] in allowed)
        require((diag["reason"] == "SANDBOX_REQUIRED") == (diag["phase"] == "SANDBOX_CHECK"))
        return value
    require(value.get("status") == "MIGRATED")
    require(set(value) == {"schema", "status", "revisions", "tables"})
    revisions = value["revisions"]
    require(type(revisions) is list and 1 <= len(revisions) <= 16)
    require(all(type(x) is str and re.fullmatch(r"[A-Za-z0-9_][A-Za-z0-9_.-]{0,127}", x)
                for x in revisions))
    require(revisions == sorted(set(revisions)))
    tables = value["tables"]
    require(type(tables) is dict and 1 <= len(tables) <= 4096)
    for table, columns in tables.items():
        require(type(table) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", table))
        require(type(columns) is list and 1 <= len(columns) <= 2048)
        require(all(type(x) is str and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]{0,127}", x)
                    for x in columns))
        require(columns == sorted(set(columns)))
    return value
