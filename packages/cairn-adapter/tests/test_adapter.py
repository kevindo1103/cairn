"""16 negative groups exercise real package transitions against temporary TEST DBs."""

import copy
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event
from unittest.mock import patch

from cairn_adapter import Adapter, Owner, Store, Rejected, credential_hash
from cairn_adapter.recovery import backup, proof, restore
from cairn_adapter.store import COMMANDS, STATES, digest, get_config


TOKENS = {k: (k + "-test-credential-").ljust(64, "x") for k in ("owner", "pm", "old", "new", "other")}
BINDING = {"fixture": "synthetic-authority-v1"}


class TestVerifier:
    """Trusted test-only dependency. Workers cannot inject this through execute()."""
    __test__ = False
    def __init__(self):
        self.available, self.head, self.calls = True, "head-1", 0

    def verify(self, binding, scope):
        self.calls += 1
        if not self.available or binding != BINDING:
            raise Rejected("Synthetic unavailable authority")
        return {"issue": "10", "scope": scope, "base": "base-1", "head": self.head,
                "checkpoint": "cp-" + self.head, "evidence": "synthetic://canonical-plan"}


def entry(task, commands=None, state="ACTIVE", role="worker"):
    return {"task_id": task, "credential_hash": credential_hash(TOKENS[task]), "generation": 1,
            "state": state, "role": role, "bindings": {"adapter": copy.deepcopy(BINDING)},
            "grants": [{"command": c, "scope": "adapter", "states": sorted(STATES)}
                       for c in (commands if commands is not None else COMMANDS)],
            "successor": None, "quiescence": None}


class NegativeMatrix(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.now = 1000.0
        self.store = Store.initialize(self.root / "project", "synthetic/repo", "pm", TOKENS["owner"],
                                      clock=lambda: self.now)
        self.owner, self.verifier = Owner(self.store), TestVerifier()
        self.adapter = Adapter(self.store, self.verifier)
        self.entries = [entry("pm", role="PM"), entry("old"), entry("new"), entry("other")]
        self.revision = 0
        self.replace()
        self.call("pm", "checkpoint")

    def replace(self):
        self.revision = self.owner.replace(TOKENS["owner"], self.revision, self.entries)["revision"]

    def call(self, principal, command, **args):
        generation = next(e["generation"] for e in self.entries if e["task_id"] == principal)
        return self.adapter.execute(TOKENS[principal], generation, self.revision, "adapter", command, args)

    def rejected_zero_write(self, call):
        before = proof(self.store.path)
        with self.assertRaises((Rejected, ValueError, KeyError)):
            call()
        self.assertEqual(proof(self.store.path), before)

    def enqueue(self, key="one", **updates):
        args = dict(dedupe_key=key, target="new", kind="HANDOFF", priority=1,
                    dependency=None, next_action="Synthetic test action")
        args.update(updates)
        return self.call("old", "enqueue", **args)["id"]

    def deliver(self, event):
        claimed = self.call("pm", "claim", event_id=event)
        self.call("pm", "sent", event_id=event, delivery_token=claimed["delivery_token"],
                  receipt="synthetic://transport-accepted")
        return claimed["delivery_token"]

    def accept(self, event):
        self.deliver(event)
        self.call("new", "reconcile", event_id=event)
        return self.call("new", "ack", event_id=event)["worker_token"]

    def complete(self, event):
        token = self.accept(event)
        self.call("new", "start", event_id=event, worker_token=token, evidence="synthetic://start")
        self.call("new", "complete", event_id=event, worker_token=token, evidence="synthetic://complete")

    def test_01_impersonation_and_owner_separation(self):
        event = self.enqueue()
        self.rejected_zero_write(lambda: self.call("other", "ack", event_id=event))
        self.rejected_zero_write(lambda: self.call("old", "checkpoint", actor="pm"))
        self.rejected_zero_write(lambda: self.owner.replace(TOKENS["old"], self.revision, self.entries))
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS["owner"], 1, self.revision,
                                                               "adapter", "checkpoint", {}))
        self.entries[1]["credential_hash"] = credential_hash(TOKENS["owner"])
        self.rejected_zero_write(self.replace)

    def test_02_registry_cas_and_stale_generation(self):
        event = self.enqueue()
        self.rejected_zero_write(lambda: self.owner.replace(TOKENS["owner"], 0, self.entries))
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS["new"], 2, self.revision,
                                                               "adapter", "get", {"event_id": event}))
        old_revision = self.revision
        self.replace()
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS["new"], 1, old_revision,
                                                               "adapter", "get", {"event_id": event}))
        self.entries[2]["credential_hash"] = credential_hash("rotated".ljust(64, "z"))
        self.entries[2]["generation"] = 2
        self.replace()
        self.rejected_zero_write(lambda: self.call("new", "get", event_id=event))
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))

    def test_03_acl_command_scope_and_state(self):
        event = self.enqueue()
        self.entries[2]["grants"] = [{"command": "get", "scope": "adapter", "states": ["SENT"]}]
        self.replace()
        self.rejected_zero_write(lambda: self.call("new", "checkpoint"))
        self.rejected_zero_write(lambda: self.call("new", "get", event_id=event))
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS["pm"], 1, self.revision,
                                                               "outside", "get", {"event_id": event}))

    def test_04_stale_head_and_no_checkpoint_fallback(self):
        event = self.enqueue()
        self.verifier.head = "head-2"
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))
        self.rejected_zero_write(lambda: self.call("pm", "checkpoint", head="head-1"))
        self.call("pm", "checkpoint")
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger.get(event)["state"], "SUPERSEDED")

    def test_05_unavailable_git_github_fails_closed(self):
        event = self.enqueue()
        self.verifier.available = False
        for cmd in ("claim", "get", "reconcile", "ack"):
            with self.subTest(cmd=cmd):
                self.rejected_zero_write(lambda: self.call("pm", cmd, event_id=event))
        self.rejected_zero_write(lambda: self.call("pm", "checkpoint"))

    def test_06_changed_manifest_rule_scope_authority(self):
        event = self.enqueue()
        for field in ("manifest", "rule", "scope"):
            with self.subTest(field=field):
                self.entries[0]["bindings"]["adapter"] = {"fixture": field + "-changed"}
                self.replace()
                self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))

    def test_07_duplicate_event_claim_and_competing_dispatchers(self):
        event = self.enqueue()
        self.assertEqual(self.enqueue(), event)
        self.rejected_zero_write(lambda: self.enqueue(next_action="conflicting data"))
        barrier = Barrier(2)
        def claim(principal):
            barrier.wait(timeout=10)
            try:
                return self.call(principal, "claim", event_id=event)
            except Rejected:
                return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(claim, ("pm", "old")))
        self.assertEqual(sum(r is not None for r in results), 1)
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger.get(event)["attempts"], 1)

    def test_08_duplicate_successor_and_cycles(self):
        self.entries[1]["successor"] = {"task_id": "new", "generation": 1}
        self.entries[3]["successor"] = {"task_id": "new", "generation": 1}
        self.rejected_zero_write(self.replace)
        self.entries[3]["successor"] = None
        self.entries[2]["successor"] = {"task_id": "old", "generation": 1}
        self.rejected_zero_write(self.replace)
        self.entries[2]["successor"] = None
        self.entries[1]["successor"]["generation"] = 2
        self.rejected_zero_write(self.replace)

    def test_09_busy_recipient_retains_queue(self):
        event = self.enqueue()
        self.call("new", "set_busy", busy=True, evidence="synthetic://busy")
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))
        self.call("new", "set_busy", busy=False, evidence="synthetic://available")
        self.assertEqual(self.call("pm", "claim", event_id=event)["event"]["id"], event)

    def test_10_expired_worker_unconfirmed_retains_slot(self):
        first = self.enqueue()
        token = self.accept(first)
        second = self.enqueue("second")
        self.now += 301
        with self.store.transaction() as (db, ledger):
            ledger.recover()  # trusted host timeout maintenance, never a worker command
            self.assertEqual(ledger.get(first)["state"], "BLOCKED")
        self.rejected_zero_write(lambda: self.call("new", "start", event_id=first,
                                                  worker_token=token, evidence="synthetic://late"))
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=second))
        marker = self.root / "external-worker-still-can-write.txt"
        marker.write_text("Lease expiry does not stop an OS process")
        self.assertTrue(marker.exists())

    def test_11_stolen_expired_and_completed_tokens(self):
        event = self.enqueue()
        claim = self.call("pm", "claim", event_id=event)
        self.rejected_zero_write(lambda: self.call("old", "sent", event_id=event,
                                                  delivery_token=claim["delivery_token"], receipt="synthetic://stolen"))
        self.call("pm", "sent", event_id=event, delivery_token=claim["delivery_token"], receipt="synthetic://sent")
        self.call("new", "reconcile", event_id=event)
        token = self.call("new", "ack", event_id=event)["worker_token"]
        self.rejected_zero_write(lambda: self.call("other", "start", event_id=event,
                                                  worker_token=token, evidence="synthetic://stolen"))
        self.call("new", "start", event_id=event, worker_token=token, evidence="synthetic://start")
        self.call("new", "complete", event_id=event, worker_token=token, evidence="synthetic://done")
        self.rejected_zero_write(lambda: self.call("new", "renew", event_id=event, worker_token=token))

    def test_12_ack_without_or_after_stale_reconciliation(self):
        event = self.enqueue()
        self.deliver(event)
        self.rejected_zero_write(lambda: self.call("new", "ack", event_id=event))
        self.call("new", "reconcile", event_id=event)
        self.replace()
        self.rejected_zero_write(lambda: self.call("new", "ack", event_id=event))
        self.call("new", "reconcile", event_id=event)
        self.assertEqual(self.call("new", "ack", event_id=event)["event"]["state"], "ACKED")

    def test_13_delivery_failure_restart_and_retry_exhaustion(self):
        event = self.enqueue()
        for attempt in (1, 2):
            claim = self.call("pm", "claim", event_id=event)
            self.assertEqual(claim["event"]["attempts"], attempt)
            self.call("pm", "delivery_failed", event_id=event,
                      delivery_token=claim["delivery_token"], evidence="synthetic://failed")
            self.adapter = Adapter(Store(self.root / "project", "synthetic/repo", clock=lambda: self.now), self.verifier)
            if attempt == 1:
                self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))
                self.call("old", "inspect_retry", event_id=event, evidence="synthetic://inspection")
                self.now += 31
        self.assertEqual(self.call("old", "get", event_id=event)["state"], "BLOCKED")
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))

    def test_14_missing_ack_and_terminal_projection(self):
        event = self.enqueue()
        self.deliver(event)
        self.now += 121
        self.rejected_zero_write(lambda: self.call("new", "ack", event_id=event))
        with self.store.transaction() as (db, ledger):
            ledger.recover()
        self.call("old", "inspect_retry", event_id=event, evidence="synthetic://inspection")
        self.now += 31
        self.deliver(event)
        self.now += 121
        with self.store.transaction() as (db, ledger):
            ledger.recover()
            self.assertEqual(ledger.get(event)["state"], "BLOCKED")
        self.rejected_zero_write(lambda: self.call("new", "reconcile", event_id=event))
        self.rejected_zero_write(lambda: self.call("old", "terminate", event_id=event,
                                                  state="QUEUED", evidence="synthetic://ui-resume"))

    def test_15_retirement_requires_all_invariants(self):
        event = self.enqueue()
        self.entries[1]["successor"] = {"task_id": "new", "generation": 1}
        self.replace()
        self.assertFalse(self.call("pm", "retirement", event_id=event)["RETIRE_ALLOWED"])
        self.complete(event)
        self.assertFalse(self.call("pm", "retirement", event_id=event)["RETIRE_ALLOWED"])
        self.entries[1]["state"] = "QUIESCED"
        self.entries[1]["quiescence"] = {"evidence": "synthetic://host-observed", "active_mutations": 1, "unmapped_work": 0}
        self.replace()
        self.assertFalse(self.call("pm", "retirement", event_id=event)["RETIRE_ALLOWED"])
        self.entries[1]["quiescence"]["active_mutations"] = 0
        self.replace()
        result = self.call("pm", "retirement", event_id=event)
        self.assertTrue(result["RETIRE_ALLOWED"])
        self.assertFalse(result["retirement_authorized"])
        self.assertEqual(result["actions_executed"], [])
        self.rejected_zero_write(lambda: self.call("old", "enqueue", dedupe_key="after-freeze", target="new",
                                                  kind="HANDOFF", priority=1, dependency=None, next_action="denied"))
        self.entries[2]["state"] = "QUIESCED"
        self.replace()
        self.assertFalse(self.call("pm", "retirement", event_id=event)["RETIRE_ALLOWED"])

    def test_16_exact_sqlite_backup_restore_and_project_isolation(self):
        keeper = sqlite3.connect(self.store.path)
        self.addCleanup(keeper.close)
        keeper.execute("SELECT COUNT(*) FROM config").fetchone()
        completed = self.enqueue()
        self.complete(completed)
        active = self.enqueue("active")
        self.accept(active)
        queued = self.enqueue("queued")
        before = proof(self.store.path)
        self.assertGreater(Path(str(self.store.path) + "-wal").stat().st_size, 0)
        checkpoint = self.root / "backup.sqlite"
        saved = backup(self.store.path, checkpoint)
        self.assertEqual(saved, before)
        self.assertEqual(restore(checkpoint, self.root / "restored", saved, "synthetic/repo"), saved)
        restored = Store(self.root / "restored", "synthetic/repo")
        with restored.transaction() as (db, ledger):
            self.assertEqual(ledger.get(completed)["state"], "COMPLETED")
            self.assertEqual(ledger.get(active)["state"], "ACKED")
            self.assertEqual(ledger.get(queued)["state"], "QUEUED")
            self.assertEqual(ledger.snapshot()["recipients"][0]["active_event"], active)
        with self.assertRaises(FileExistsError):
            restore(checkpoint, self.root / "project", saved, "synthetic/repo")
        with self.assertRaises(Rejected):
            Store(self.root / "project", "another/repository")
        self.call("new", "terminate", event_id=active, state="BLOCKED", evidence="synthetic://blocked")
        changed = self.root / "changed.sqlite"
        backup(self.store.path, changed)
        with self.assertRaises(Rejected):
            restore(changed, self.root / "bad-restore", saved, "synthetic/repo")
        self.assertEqual(proof(checkpoint), saved)

    def test_registry_cas_serializes_with_verification_and_claim(self):
        event = self.enqueue()
        reached, release = Event(), Event()
        ordinary = self.verifier.verify
        def paused(binding, scope):
            reached.set()
            if not release.wait(timeout=10):
                raise Rejected("Synthetic test barrier timeout")
            return ordinary(binding, scope)
        self.verifier.verify = paused
        with ThreadPoolExecutor(2) as pool:
            claim = pool.submit(self.call, "pm", "claim", event_id=event)
            self.assertTrue(reached.wait(timeout=10))
            replacement = pool.submit(self.owner.replace, TOKENS["owner"], self.revision, self.entries)
            release.set()
            self.assertEqual(claim.result(timeout=15)["event"]["id"], event)
            self.assertEqual(replacement.result(timeout=15)["revision"], self.revision + 1)
        self.rejected_zero_write(lambda: self.call("pm", "get", event_id=event))

    def test_cross_scope_timeout_reap_is_rolled_back(self):
        event = self.enqueue()
        with self.store.transaction() as (db, ledger):
            ledger.checkpoint("pm", "other", "outside", "cp", "base", "head", 0, "synthetic://outside")
            foreign = ledger.enqueue(dict(dedupe_key="foreign", source_task="old", target_task="other",
                                          issue="other", scope="outside", checkpoint="cp", base="base", head="head",
                                          kind="HANDOFF", priority=1, dependency=None, evidence="synthetic://outside",
                                          next_action="Synthetic outside event"))
            ledger.claim("other", "trusted-host", lease_seconds=1)
        self.now += 2
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger.get(foreign["id"])["attempts"], 1)
            self.assertEqual(ledger.get(event)["attempts"], 0)

    def test_quiesced_source_cannot_acquire_delivery(self):
        event = self.enqueue()
        self.entries[1]["state"] = "QUIESCED"
        self.replace()
        self.rejected_zero_write(lambda: self.call("pm", "claim", event_id=event))

    def test_changed_package_refused_before_any_ledger_write(self):
        original = Path.read_bytes
        def changed(path):
            data = original(path)
            return data + b"\n# changed dependency\n" if path.name == "ledger.py" else data
        with patch.object(Path, "read_bytes", changed):
            self.rejected_zero_write(lambda: self.call("pm", "checkpoint"))

    def test_pm_last_requires_other_predecessor_drain(self):
        old_handoff = self.enqueue()
        self.complete(old_handoff)
        self.entries[1]["successor"] = {"task_id": "new", "generation": 1}
        self.entries[1]["state"] = "QUIESCED"
        self.entries[1]["quiescence"] = {"evidence": "synthetic://quiesced", "active_mutations": 0, "unmapped_work": 1}
        self.entries[0]["successor"] = {"task_id": "other", "generation": 1}
        self.replace()
        pm_handoff = self.call("pm", "enqueue", dedupe_key="pm-handoff", target="other", kind="HANDOFF",
                               priority=1, dependency=None, next_action="Synthetic PM handoff")["id"]
        claim = self.call("pm", "claim", event_id=pm_handoff)
        self.call("pm", "sent", event_id=pm_handoff, delivery_token=claim["delivery_token"], receipt="synthetic://sent")
        self.call("other", "reconcile", event_id=pm_handoff)
        token = self.call("other", "ack", event_id=pm_handoff)["worker_token"]
        self.call("other", "start", event_id=pm_handoff, worker_token=token, evidence="synthetic://started")
        self.call("other", "complete", event_id=pm_handoff, worker_token=token, evidence="synthetic://completed")
        self.entries[0]["state"] = "QUIESCED"
        self.entries[0]["quiescence"] = {"evidence": "synthetic://quiesced", "active_mutations": 0, "unmapped_work": 0}
        self.replace()
        result = self.call("other", "retirement", event_id=pm_handoff)
        self.assertTrue(result["drain_ZERO"])
        self.assertFalse(result["PM_last"])
        self.entries[1]["quiescence"]["unmapped_work"] = 0
        self.replace()
        self.assertTrue(self.call("other", "retirement", event_id=pm_handoff)["RETIRE_ALLOWED"])


if __name__ == "__main__":
    unittest.main()
