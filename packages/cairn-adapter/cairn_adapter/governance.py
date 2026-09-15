"""Host-reviewed handoff evidence and logical registry controls, never task APIs."""

import json
from .store import Rejected, digest, get_config, put_config


def inventory_body(inventory):
    return {k: inventory[k] for k in ("unfinished_work", "prs", "issues", "blockers")}


def review_snapshot(db, ledger, event, registry, fresh, checkpoint):
    payload = json.loads(event["payload"])
    entries = {e["task_id"]: e for e in registry["entries"]}
    source, target = entries[payload["source_task"]], entries[event["target"]]
    def public(entry):
        return {k: v for k, v in entry.items() if k != "credential_hash"}
    raw = {"project": get_config(db, "project"), "registry_revision": registry["revision"],
           "event_id": event["id"], "event_digest": event["digest"], "state": event["state"],
           "predecessor": public(source), "successor": public(target),
           "checkpoint": dict(checkpoint), "fresh_git": fresh,
           "readback": None, "provenance": get_config(db, "event:" + event["id"]),
           "pm_authority": ledger._pm_authority(db)}
    unfinished = []
    for item in source["inventory"]["unfinished_work"]:
        if not isinstance(item, dict) or set(item) != {"task_id", "event_id", "status", "evidence"}:
            raise Rejected("Unfinished work lacks canonical task/event/status/evidence")
        if item["task_id"] not in entries:
            raise Rejected("Unfinished work identity is unmapped")
        actual = ledger._get(db, item["event_id"])
        actual_payload = json.loads(actual["payload"])
        if (item["status"] != actual["state"] or item["task_id"] not in (actual_payload["source_task"], actual["target"])
                or item["evidence"] not in (actual_payload["evidence"], actual["result_evidence"])
                or actual_payload["scope"] != payload["scope"]):
            raise Rejected("Unfinished work does not match canonical ledger truth")
        unfinished.append(ledger._public(actual))
    raw["unfinished_ledger"] = unfinished
    key = "adapter:reconcile:" + event["id"]
    if db.execute("SELECT 1 FROM config WHERE key=?", (key,)).fetchone():
        raw["readback"] = get_config(db, "reconcile:" + event["id"])
    return {"snapshot": raw, "digest": digest(raw)}


def require_attestation(db, command, event_id, review, revision):
    record = get_config(db, "attest:" + command + ":" + event_id)
    if record["revision"] != revision or record["digest"] != review["digest"]:
        raise Rejected("Host approval does not match full current handoff snapshot")
    return record


def validate_completion(db, verifier, event, registry, fresh, cp, ledger, evidence):
    if json.loads(event["payload"])["kind"] != "HANDOFF":
        return  # ordinary package events retain their existing completion semantics
    review = review_snapshot(db, ledger, event, registry, fresh, cp)
    source, target = review["snapshot"]["predecessor"], review["snapshot"]["successor"]
    if target["state"] == "pending" and source["successor"] != {"task_id": target["task_id"], "generation": target["generation"]}:
        raise Rejected("Pending HANDOFF recipient is not the registry-bound successor")
    if not source["inventory"]["complete"] or not target["inventory"]["complete"]:
        raise Rejected("Incomplete handoff inventory")
    if target["inventory"]["readback_digest"] != digest(inventory_body(source["inventory"])):
        raise Rejected("Successor has not read back exact unfinished work/PR/issues/blockers")
    if inventory_body(source["inventory"]) != inventory_body(target["inventory"]):
        raise Rejected("Handoff inventory changed or omitted work")
    mapped = {r["id"] for r in review["snapshot"]["unfinished_ledger"]}
    for row in db.execute("SELECT * FROM events WHERE state != 'COMPLETED'"):
        if row["id"] != event["id"] and source["task_id"] in (row["target"], json.loads(row["payload"])["source_task"]) and row["id"] not in mapped:
            raise Rejected("Canonical ledger contains unmapped unfinished work")
    verifier.verify_references(source["inventory"]["prs"], source["inventory"]["issues"])
    attestation = require_attestation(db, "complete", event["id"], review, registry["revision"])
    if evidence != attestation["evidence"]:
        raise Rejected("Completion evidence is not the separately reviewed host evidence")
    put_config(db, "completed-proof:" + event["id"], review)


def logical_control(db, ledger, command, event, registry, fresh, cp, principal, assess):
    review = review_snapshot(db, ledger, event, registry, fresh, cp)
    approved = require_attestation(db, command, event["id"], review, registry["revision"])
    payload = json.loads(event["payload"])
    entries = {e["task_id"]: e for e in registry["entries"]}
    old, new = entries[payload["source_task"]], entries[event["target"]]
    if command == "release_stopped_worker":
        return ledger.release_stopped_worker(event["id"], principal["task_id"], approved["evidence"])
    if old["role"] == "PM":
        if new["role"] != "PM":
            raise Rejected("PM succession requires a registry-bound PM successor")
        if any(e["successor"] and e["task_id"] != old["task_id"] and e["state"] != "retired"
               for e in entries.values()):
            raise Rejected("PM-last requires every other mapped predecessor already retired")
    if command == "authority_flip":
        if db.execute("SELECT 1 FROM config WHERE key=?", ("adapter:flip:" + event["id"],)).fetchone():
            raise Rejected("Authority already flipped")
        status = assess(db, ledger, event, entries, allow_pending=True)
        if new["state"] != "pending" or not status["RETIRE_ALLOWED"]:
            raise Rejected("Flip requires pending successor, completed handoff, quiescence and zero drain")
        previous = {"source": {"task_id": old["task_id"], "generation": old["generation"]},
                    "target": {"task_id": new["task_id"], "generation": new["generation"]}}
        if old["role"] == "PM":
            authority = review["snapshot"]["pm_authority"]
            ledger.succeed_pm(actor=old["task_id"], event_id=event["id"],
                expected_revision=authority["revision"], predecessor=old["task_id"], successor=new["task_id"],
                predecessor_generation=old["generation"], successor_generation=new["generation"] + 1,
                checkpoint_revision=cp["revision"], registry_revision=registry["revision"],
                review_digest=review["digest"], evidence=approved["evidence"])
        old["generation"] += 1
        new["generation"] += 1
        new["state"] = "active"
        old["successor"] = {"task_id": new["task_id"], "generation": new["generation"]}
        put_config(db, "flip:" + event["id"], {"previous": previous,
                   "source_generation": old["generation"], "target_generation": new["generation"],
                   "review_digest": review["digest"]})
    elif command == "retire":
        if old["role"] == "PM" and ledger._pm_authority(db)["task_id"] != new["task_id"]:
            raise Rejected("PM retirement requires the committed core succession first")
        if not assess(db, ledger, event, entries)["RETIRE_ALLOWED"]:
            raise Rejected("Retirement invariant is incomplete")
        old["state"] = "retired"
    else:
        raise Rejected("Unknown logical control")
    registry["revision"] += 1
    put_config(db, "registry", registry)
    ledger._audit(db, event["id"], principal["task_id"], command.upper(),
                  {"revision": registry["revision"], "review_digest": review["digest"],
                   "predecessor_generation": old["generation"], "successor_generation": new["generation"]})
    return {"registry_revision": registry["revision"], "predecessor_generation": old["generation"],
            "successor_generation": new["generation"], "actions_executed": [],
            "external_authority_effect": False, "live_authorization": "NOT_AUTHORIZED"}


def preparation_snapshot(candidates):
    """Projection inputs only: never manufacture trusted registry or successor IDs."""
    required = {"issue", "task_id", "session_id", "role", "owner", "worktree", "branch", "pr",
                "base", "head", "checkpoint", "unfinished_work", "blocker", "evidence"}
    rows = []
    for candidate in candidates:
        if not isinstance(candidate, dict):
            raise Rejected("Snapshot candidate must be an object")
        gaps = sorted(k for k in required if k not in candidate or candidate[k] is None or candidate[k] == "")
        if any(candidate.get(k) in (None, "", "TBD") for k in ("successor", "successor_ack", "runtime_evidence")):
            gaps += ["successor/ACK/runtime evidence unverified"]
        if any(candidate.get(k) in (None, "", "TBD") for k in ("host_identity_evidence", "process_fencing_evidence")):
            gaps += ["host identity/process fencing evidence unverified"]
        rows.append({"candidate": candidate, "gaps": gaps, "trusted_identity": False})
    return {"rows": rows, "status": "PREPARATION_ONLY", "authority_effect": False,
            "actions_executed": [], "AdapterAccepted": "NOT_PROVEN", "RecoveryProven": "NOT_PROVEN"}


def project_event(event, label):
    expected = {"QUEUED": "queued", "SENT": "sent", "ACKED": "acked", "STARTED": "started",
                "COMPLETED": "completed", "BLOCKED": "blocked", "CANCELLED": "cancelled",
                "SUPERSEDED": "superseded"}[event["state"]]
    return {"ledger_state": event["state"], "projection": expected,
            "warning": "PROJECTION_MISMATCH" if label != expected else None,
            "terminal_attempt": event["state"] in {"COMPLETED", "BLOCKED", "CANCELLED", "SUPERSEDED"},
            "projection_can_resume_ledger": False}
