"""Safe structured diagnostics; never serialize exception text, SQL or arguments."""
from __future__ import annotations

import json
import logging
import re

from .common import Refused

REASONS = frozenset({"COMMAND_FAILED", "MANIFEST_MISSING", "MANIFEST_INVALID", "ASSET_MISSING",
                     "ASSET_DIGEST_MISMATCH", "SCHEMA_MISMATCH", "MIGRATION_FAILED", "UNCLASSIFIED"})
CLASSES = frozenset({"OperationalError", "IntegrityError", "ValidationError", "ValueError", "TypeError",
                     "OSError", "FileNotFoundError", "RuntimeError", "TimeoutError"})


def safe_event(reason: str, exception: BaseException, phase: str, correlation_id: str) -> dict:
    if reason not in REASONS or phase not in {"brew", "audio", "migration", "scan", "request"}:
        raise Refused("DIAGNOSTIC_ENUM")
    if not re.fullmatch(r"[a-zA-Z0-9-]{8,64}", correlation_id):
        raise Refused("DIAGNOSTIC_CORRELATION")
    cls = type(exception).__name__
    return {"schema": "safe-diagnostic-v1", "reason": reason,
            "exception_class": cls if cls in CLASSES else "OtherException",
            "phase": phase, "correlation_id": correlation_id}


def emit_safe_event(logger: logging.Logger, *, reason: str, exception: BaseException,
                    phase: str, correlation_id: str) -> bool:
    try:
        payload = safe_event(reason, exception, phase, correlation_id)
        logger.error(json.dumps(payload, sort_keys=True), exc_info=False, stack_info=False)
        return True
    except Exception:
        # Reporter failure must not change transaction or retry semantics.
        return False
