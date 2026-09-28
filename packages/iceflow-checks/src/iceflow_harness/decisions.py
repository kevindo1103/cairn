"""V0.3 compatibility linter. Deliberately no grant evaluator or state machine."""
from __future__ import annotations

from datetime import datetime
from importlib.resources import files

from jsonschema import Draft202012Validator, FormatChecker

from .common import Refused, canonical, digest, finding, parse_json, safe_rel


def lint_decision(value: dict) -> list[dict]:
    schema = parse_json(files("iceflow_harness.data").joinpath("decision-v03.schema.json").read_bytes())
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    if list(validator.iter_errors(value)):
        return [finding("DECISION", "FAIL", "DECISION_SHAPE_INVALID")]
    try:
        for scope in [value["scope"], *(s["scope"] for s in value["supersedes"])]:
            for path in scope["paths"]:
                safe_rel(path, glob=scope["path_match"] == "GLOB")
        policy = value["subject"].get("policy_ref")
        if policy:
            safe_rel(policy["path"])
    except Refused:
        return [finding("DECISION", "FAIL", "DECISION_PATH_INVALID")]
    kind = value["kind"]
    if kind in {"GRANT", "AMEND"} and set(value["scope"]["operations"]) & set(value["denies"]):
        return [finding("DECISION", "FAIL", "GRANT_DENY_CONFLICT")]
    if kind == "REVOKE" and value["expires_at"] is not None:
        return [finding("DECISION", "FAIL", "REVOKE_EXPIRY_AMBIGUOUS")]
    if value["expires_at"] is not None:
        issued = datetime.fromisoformat(value["issued_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(value["expires_at"].replace("Z", "+00:00"))
        if expires <= issued:
            return [finding("DECISION", "FAIL", "DECISION_INVALID_TIME_RANGE")]
    if kind == "AMEND":
        return [finding("DECISION", "BLOCKED", "AMEND_SEMANTICS_NOT_RATIFIED")]
    return [finding("DECISION", "INFO", "SHAPE_VALID_AUTHORITY_NOT_EVALUATED", details={
        "payload_sha256": digest(canonical(value)), "kind": kind, "effective_permissions": [],
        "identity_verified": False, "protocol_ratified": False})]


def lint_document(text: str) -> list[dict]:
    """Only an entire JSON value or explicit fenced decision blocks; never infer prose."""
    if text.lstrip().startswith("{"):
        return lint_decision(parse_json(text))
    import re
    blocks = re.findall(r"^```decision\s*\n(.*?)^```\s*$", text, flags=re.M | re.S)
    if not blocks:
        return [finding("DECISION", "INFO", "UNSTRUCTURED_NO_AUTHORITY_EXTRACTED")]
    if len(blocks) > 10:
        raise Refused("DECISION_BLOCK_LIMIT")
    return [item for block in blocks for item in lint_decision(parse_json(block))]
