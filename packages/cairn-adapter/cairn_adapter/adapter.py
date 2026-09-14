"""Principal-bound facade over the package's existing ledger lifecycle."""

import hmac
import json

from .store import (COMMANDS, Rejected, credential_hash, digest, get_config, put_config)


ARGUMENTS = {
    "checkpoint": set(),
    "enqueue": {"dedupe_key", "target", "kind", "priority", "dependency", "next_action"},
    "claim": {"event_id"}, "sent": {"event_id", "delivery_token", "receipt"},
    "delivery_failed": {"event_id", "delivery_token", "evidence"},
    "reconcile": {"event_id"}, "ack": {"event_id"},
    "start": {"event_id", "worker_token", "evidence"},
    "renew": {"event_id", "worker_token"},
    "complete": {"event_id", "worker_token", "evidence"},
    "terminate": {"event_id", "state", "evidence"},
    "inspect_retry": {"event_id", "evidence"},
    "override_priority": {"event_id", "priority", "evidence"},
    "set_busy": {"busy", "evidence"},
    "get": {"event_id"}, "retirement": {"event_id"},
}


class Adapter:
    def __init__(self, store, verifier):
        # Host dependency injection only, never request fields or a worker factory.
        from .package import verify_package
        self.package_binding = verify_package()
        self._store, self._verifier = store, verifier

    @staticmethod
    def capabilities():
        return {"automatic_wake": "NOT_IMPLEMENTED", "filesystem_process_fencing": "NOT_PROVEN",
                "activation": "NOT_AUTHORIZED", "retirement_actions": "NOT_IMPLEMENTED",
                "identity_boundary": "host-held bearer credentials; host alone owns database",
                "mode": "review-only library"}

    def execute(self, credential, generation, registry_revision, scope, command, arguments):
        from .package import verify_package
        verify_package()
        if command not in COMMANDS or not isinstance(arguments, dict) or set(arguments) != ARGUMENTS[command]:
            raise Rejected("Unknown command/fields; caller identity or checkpoint overrides are forbidden")
        if type(generation) is not int or type(registry_revision) is not int:
            raise Rejected("Require exact principal generation and registry revision")
        # Detach mutable caller containers before validation or network calls.
        args = json.loads(json.dumps(arguments, allow_nan=False))
        token_hash = credential_hash(credential)
        with self._store.transaction() as (db, ledger):
            registry = get_config(db, "registry")
            if registry["revision"] != registry_revision:
                raise Rejected("Stale registry revision")
            entries = registry["entries"]
            matching = [e for e in entries if hmac.compare_digest(e["credential_hash"], token_hash)]
            if len(matching) != 1:
                raise Rejected("Unknown principal")
            principal = matching[0]
            if principal["generation"] != generation or principal["state"] != "ACTIVE":
                raise Rejected("Stale generation or quiesced principal")
            event = ledger._get(db, args["event_id"]) if "event_id" in args else None
            state = event["state"] if event else "ABSENT"
            grants = [g for g in principal["grants"] if g["command"] == command and g["scope"] == scope]
            if not any(state in g["states"] for g in grants):
                raise Rejected("Principal x command x scope x state denied")
            if scope not in principal["bindings"]:
                raise Rejected("No canonical scope binding")
            p = json.loads(event["payload"]) if event else None
            if p and p["scope"] != scope:
                raise Rejected("Event scope differs from authorized request")
            # Verification happens while registry CAS and ledger mutation are serialized.
            # A network failure rolls back the entire operation. No caller fallback.
            fresh = self._verifier.verify(principal["bindings"][scope], scope)
            if set(fresh) != {"issue", "scope", "base", "head", "checkpoint", "evidence"} or fresh["scope"] != scope:
                raise Rejected("Verifier returned incomplete binding")
            if p and any(p[k] != fresh[k] for k in ("issue", "scope", "base", "head", "checkpoint")):
                raise Rejected("Event no longer matches fresh authority")
            cp = db.execute("SELECT * FROM checkpoints WHERE issue=? AND scope=?",
                            (fresh["issue"], scope)).fetchone()
            if command != "checkpoint" and (not cp or any(cp[k] != fresh[k]
                    for k in ("base", "head", "checkpoint"))):
                raise Rejected("Canonical checkpoint must be freshly reconciled by its authorized owner")
            task, owner = principal["task_id"], f"{principal['task_id']}@{generation}"
            by_task = {e["task_id"]: e for e in entries}
            if event:
                provenance = get_config(db, "event:" + event["id"])
                for key in ("source", "target"):
                    identity = provenance[key]
                    live = by_task.get(identity["task_id"])
                    if not live or live["generation"] != identity["generation"]:
                        raise Rejected("Event principal generation was revoked")
                    if command in {"claim", "sent", "reconcile", "ack", "start", "renew"} and live["state"] != "ACTIVE":
                        raise Rejected("Frozen topology cannot acquire new delivery or work")
                if command in {"reconcile", "ack", "start", "renew", "complete"} and event["target"] != task:
                    raise Rejected("Only the bound recipient may acknowledge or execute")
                if command in {"sent", "delivery_failed"} and event["delivery_owner"] != owner:
                    raise Rejected("Delivery token belongs to a different principal")
                if command in {"start", "renew", "complete"} and event["worker_owner"] != owner:
                    raise Rejected("Worker token belongs to a different principal")
            # Package claim reaps timeouts globally. Reject and roll back any incidental
            # mutation outside this scope; never silently bypass scope ACL through reaping.
            before = {r["id"]: dict(r) for r in db.execute("SELECT * FROM events")}
            result = self._invoke(db, ledger, command, args, principal, registry, fresh, cp,
                                  event, by_task, owner)
            for row in db.execute("SELECT * FROM events"):
                prior = before.get(row["id"])
                if prior != dict(row):
                    if json.loads(row["payload"])["scope"] != scope:
                        raise Rejected("Package maintenance crossed requested scope; host recovery required")
                    if prior is not None and row["id"] != args.get("event_id") and not any(
                            prior["state"] in g["states"] for g in grants):
                        raise Rejected("Package maintenance crossed permitted states; host recovery required")
            return result

    def _invoke(self, db, ledger, cmd, a, principal, registry, fresh, cp, event, entries, owner):
        task, scope = principal["task_id"], fresh["scope"]
        if cmd == "checkpoint":
            return ledger.checkpoint(actor=task, expected_revision=cp["revision"] if cp else 0, **fresh)
        if cmd == "enqueue":
            target = entries.get(a["target"])
            if not target or target["state"] != "ACTIVE" or scope not in target["bindings"]:
                raise Rejected("Target absent, quiesced or outside scope")
            # No change of artifact authority at delivery to another principal.
            if target["bindings"][scope] != principal["bindings"][scope]:
                raise Rejected("Source and target canonical bindings disagree")
            if a["dependency"] is not None:
                dependency = ledger._get(db, a["dependency"])
                if json.loads(dependency["payload"])["scope"] != scope:
                    raise Rejected("Cross-scope dependency requires separately reconciled handoff")
            payload = dict(fresh, source_task=task, target_task=a["target"],
                           **{k: v for k, v in a.items() if k != "target"})
            result = ledger.enqueue(payload)
            provenance = {"source": {"task_id": task, "generation": principal["generation"]},
                          "target": {"task_id": target["task_id"], "generation": target["generation"]}}
            key = "event:" + result["id"]
            exists = db.execute("SELECT 1 FROM config WHERE key=?", ("adapter:" + key,)).fetchone()
            if exists and get_config(db, key) != provenance:
                raise Rejected("Duplicate event cannot acquire new principal generations")
            put_config(db, key, provenance)
            return result
        if cmd == "set_busy":
            return ledger.set_busy(actor=task, target=task, **a)
        if cmd == "get":
            return ledger._public(event)
        if cmd == "retirement":
            return self._retirement(db, ledger, event, entries)
        event_id = event["id"]
        if cmd == "claim":
            target = entries.get(event["target"])
            if not target or target["state"] != "ACTIVE":
                raise Rejected("Recipient quiesced")
            result = ledger.claim(target=event["target"], dispatcher=owner)
            if result is None or result["event"]["id"] != event_id:
                raise Rejected("No claim for expected event; busy, duplicate or priority moved")
            return result
        if cmd == "reconcile":
            if event["state"] != "SENT":
                raise Rejected("Reconciliation requires delivered event")
            record = {"event_digest": event["digest"], "generation": principal["generation"],
                      "registry_revision": registry["revision"], "checkpoint_revision": cp["revision"],
                      "binding": digest(fresh), "owner": owner}
            put_config(db, "reconcile:" + event_id, record)
            ledger._audit(db, event_id, task, "PRINCIPAL_RECONCILED", record)
            return {"reconciled": event_id, "registry_revision": registry["revision"]}
        if cmd == "ack":
            expected = {"event_digest": event["digest"], "generation": principal["generation"],
                        "registry_revision": registry["revision"], "checkpoint_revision": cp["revision"],
                        "binding": digest(fresh), "owner": owner}
            if get_config(db, "reconcile:" + event_id) != expected:
                raise Rejected("ACK requires current principal reconciliation")
            return ledger.ack(event_id, task, owner, "artifact://reconciled/" + digest(expected))
        if cmd in {"sent", "delivery_failed", "start", "renew", "complete"}:
            return getattr(ledger, cmd)(**a)
        if cmd in {"terminate", "inspect_retry", "override_priority"}:
            return getattr(ledger, cmd)(actor=task, **a)
        raise Rejected("Command not implemented")

    @staticmethod
    def _retirement(db, ledger, event, entries):
        p = json.loads(event["payload"])
        predecessor = entries[p["source_task"]]
        successor = entries[event["target"]]
        mapping = predecessor["successor"]
        q = predecessor["quiescence"]
        completed = p["kind"] == "HANDOFF" and event["state"] == "COMPLETED"
        provenance = get_config(db, "event:" + event["id"])
        completed = completed and provenance == {
            "source": {"task_id": predecessor["task_id"], "generation": predecessor["generation"]},
            "target": {"task_id": successor["task_id"], "generation": successor["generation"]}}
        active = (successor["state"] == "ACTIVE" and mapping is not None
                  and mapping == {"task_id": successor["task_id"], "generation": successor["generation"]})
        quiesced = predecessor["state"] == "QUIESCED" and q is not None
        relevant = [dict(r) for r in db.execute("SELECT * FROM events")
                    if predecessor["task_id"] in (r["target"], json.loads(r["payload"])["source_task"])]
        unfinished = [r for r in relevant if r["state"] != "COMPLETED"]
        # Includes retained slots and residual leases even on terminal bookkeeping.
        relevant_ids = {r["id"] for r in relevant}
        slots = [r for r in db.execute("SELECT * FROM recipients WHERE active_event IS NOT NULL")
                 if r["task"] == predecessor["task_id"] or r["active_event"] in relevant_ids]
        leases = [r for r in relevant if r["delivery_token"] or r["worker_token"]
                  or r["delivery_until"] is not None or r["worker_until"] is not None]
        drain = bool(q is not None and q["active_mutations"] == 0 and q["unmapped_work"] == 0
                     and not unfinished and not slots and not leases)
        # PM waits for every registry-mapped predecessor's full eligibility, not just
        # its quiesced label. Cycles were rejected by owner CAS validation.
        pm_last = True
        if predecessor["role"] == "PM":
            for other in entries.values():
                if other["task_id"] == predecessor["task_id"] or not other["successor"]:
                    continue
                candidates = [dict(r) for r in db.execute("SELECT * FROM events WHERE state='COMPLETED'")
                              if json.loads(r["payload"])["source_task"] == other["task_id"]
                              and r["target"] == other["successor"]["task_id"]]
                # Multiple PM predecessors are ambiguous and refused rather than recursed.
                if other["role"] == "PM" or not any(Adapter._retirement(db, ledger, c, entries)["RETIRE_ALLOWED"]
                                                    for c in candidates):
                    pm_last = False
        return {"HANDOFF_COMPLETED": completed, "successor_ACTIVE_generation": active,
                "predecessor_QUIESCED": quiesced, "drain_ZERO": drain, "PM_last": pm_last,
                "RETIRE_ALLOWED": bool(completed and active and quiesced and drain and pm_last),
                "actions_executed": [], "retirement_authorized": False,
                "filesystem_process_fencing": "NOT_PROVEN"}
