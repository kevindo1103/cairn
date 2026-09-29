"""Strict bounded observation contracts. Payload fields never authenticate actors."""
from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from iceflow_harness.common import Refused, SHA40, SHA256, canonical, digest, safe_rel


def require(ok: bool, code: str) -> None:
    if not ok:
        raise Refused(code)


def exact(value: Any, keys: set[str], code: str) -> dict:
    require(type(value) is dict and set(value) == keys, code)
    return value


def word(value: Any, code: str = "IDENTIFIER_INVALID", limit: int = 128) -> str:
    require(isinstance(value, str) and 0 < len(value) <= limit and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.:/-]*", value) is not None, code)
    return value


def integer(value: Any, minimum: int = 1, code: str = "INTEGER_INVALID") -> int:
    require(type(value) is int and value >= minimum, code)
    return value


def sha40(value: Any) -> str:
    require(isinstance(value, str) and SHA40.fullmatch(value) is not None, "SOURCE_ID_INVALID")
    return value


def sha256(value: Any) -> str:
    require(isinstance(value, str) and SHA256.fullmatch(value) is not None, "DIGEST_INVALID")
    return value


def timestamp(value: Any) -> float:
    require(isinstance(value, str), "TIMESTAMP_INVALID")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise Refused("TIMESTAMP_INVALID") from exc
    require(dt.tzinfo is not None, "TIMESTAMP_INVALID")
    return dt.timestamp()


def verify_digest(value: dict, key: str) -> str:
    """Integrity only; this is not a signature or source authentication."""
    require(type(value) is dict and key in value, "ENVELOPE_DIGEST_MISSING")
    expected = sha256(value[key])
    body = {k: v for k, v in value.items() if k != key}
    require(digest(canonical(body)) == expected, "ENVELOPE_DIGEST_MISMATCH")
    return expected


def seal(value: dict, key: str = "observation_digest") -> dict:
    require(key not in value, "DIGEST_FIELD_ALREADY_PRESENT")
    return {**value, key: digest(canonical(value))}


def inert(kind: str, **fields) -> dict:
    return {"schema": kind, **fields, "authority": "NONE", "effective_permissions": [],
            "actions_executed": [], "release_ready": "NOT_EVALUATED"}


_BINDING = {"schema", "repository", "repository_id", "issue", "pr", "main_branch",
            "event_id", "task_id", "session_id", "generation", "registry_revision",
            "checkpoint_revision", "checkpoint", "scope", "base_sha", "head_sha", "tree_sha",
            "main_sha", "workflow", "workflow_digest", "step_id", "owner_role", "allowed_paths"}


def validate_binding(value: Any) -> dict:
    exact(value, _BINDING, "TASK_BINDING_SHAPE")
    require(value["schema"] == "cairn-task-binding-v1", "TASK_BINDING_VERSION")
    require(isinstance(value['repository'], str) and
            re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value['repository']) is not None
            and all(p not in {'.', '..'} for p in value['repository'].split('/')), "REPOSITORY_INVALID")
    for key in ('repository_id','issue','generation','registry_revision','checkpoint_revision'):
        integer(value[key])
    if value['pr'] is not None:
        integer(value['pr'])
    for key in ('base_sha','head_sha','tree_sha','main_sha'):
        sha40(value[key])
    sha256(value['workflow_digest'])
    for key in ('event_id','task_id','session_id','checkpoint','scope','workflow','step_id','owner_role'):
        word(value[key])
    safe_rel(value['main_branch'])
    require(type(value['allowed_paths']) is list and 0 < len(value['allowed_paths']) <= 64,
            "PATH_SCOPE_INVALID")
    for p in value['allowed_paths']:
        safe_rel(p)
    require(len(value['allowed_paths']) == len(set(value['allowed_paths'])), "PATH_SCOPE_INVALID")
    return value
