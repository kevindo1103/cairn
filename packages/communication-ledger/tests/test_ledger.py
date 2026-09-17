import json
import multiprocessing
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier

from comms_ledger import Ledger, LedgerError, __version__
from comms_ledger.transport import prepare_manual


ROOT = Path(__file__).resolve().parents[1]


def payload(key="handoff-1", **changes):
    p = dict(dedupe_key=key, source_task="lead", target_task="worker-task", issue="synthetic-issue",
             checkpoint="cp-1", base="base-1", head="head-1", scope="synthetic-scope", kind="HANDOFF",
             priority=1, dependency=None, evidence="synthetic://plan", next_action="Run synthetic check")
    p.update(changes)
    return p


def process_claim(path, barrier, results):
    ledger = Ledger(path)
    barrier.wait(timeout=20)
    result = ledger.claim("worker-task", "process-dispatcher")
    results.put(result)


class LedgerTests(unittest.TestCase):
    def test_package_version_contract(self):
        self.assertEqual(__version__, "0.2.0")

    def setUp(self):
        (ROOT / "work").mkdir(exist_ok=True)
        self.temp = tempfile.TemporaryDirectory(dir=ROOT / "work")
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "synthetic.sqlite"
        self.now = 1000.0
        self.ledger = Ledger(self.path, pm_task="pm", clock=lambda: self.now)
        self.ledger.checkpoint("lead", "synthetic-issue", "synthetic-scope", "cp-1", "base-1", "head-1", 0, "synthetic://cp")

    def enqueue(self, key="handoff-1", **changes):
        return self.ledger.enqueue(payload(key, **changes))["id"]

    def deliver(self, event_id):
        claim = self.ledger.claim("worker-task", "dispatcher")
        self.assertEqual(claim["event"]["id"], event_id)
        return self.ledger.sent(event_id, claim["delivery_token"], "synthetic://delivery")

    def accept(self, event_id):
        self.deliver(event_id)
        return self.ledger.ack(event_id, "worker-task", "worker-1", "synthetic://ack")["worker_token"]

    def test_successful_handoff_and_dependency_progress_without_pm(self):
        first = self.enqueue()
        second = self.enqueue("next", dependency=first)
        token = self.accept(first)
        self.assertIsNone(self.ledger.claim("worker-task", "other"))
        self.ledger.start(first, token, "synthetic://first-command")
        self.ledger.complete(first, token, "synthetic://result")
        self.assertEqual(self.ledger.claim("worker-task", "dispatcher")["event"]["id"], second)
        states = [h["action"] for h in self.ledger.history(first)]
        self.assertEqual([s for s in states if s in {"QUEUED", "SENT", "ACKED", "STARTED", "COMPLETED"}],
                         ["QUEUED", "SENT", "ACKED", "STARTED", "COMPLETED"])

    def test_duplicates_and_conflicting_duplicate(self):
        first = self.enqueue()
        self.assertEqual(self.enqueue(), first)
        with self.assertRaises(LedgerError):
            self.enqueue(next_action="Different content")
        self.assertEqual(len(self.ledger.snapshot()["events"]), 1)
        self.assertEqual(len(self.ledger.history(first)), 1)

    def test_concurrent_duplicate_enqueue(self):
        barrier = Barrier(4)
        def put(_):
            barrier.wait()
            return Ledger(self.path, clock=lambda: self.now).enqueue(payload())["id"]
        with ThreadPoolExecutor(4) as pool:
            ids = list(pool.map(put, range(4)))
        self.assertEqual(len(set(ids)), 1)

    def test_contention_duplicate_claim_separate_processes(self):
        event_id = self.enqueue()
        ctx = multiprocessing.get_context("spawn")
        barrier, results = ctx.Barrier(4), ctx.Queue()
        procs = [ctx.Process(target=process_claim, args=(str(self.path), barrier, results)) for _ in range(4)]
        for proc in procs:
            proc.start()
        for proc in procs:
            proc.join(30)
            if proc.is_alive():
                proc.terminate()
                proc.join()
                self.fail("Claim process exceeded 30 seconds")
            self.assertEqual(proc.exitcode, 0)
        values = [results.get(timeout=2) for _ in procs]
        results.close()
        results.join_thread()
        winners = [v for v in values if v is not None]
        self.assertEqual(len(winners), 1)
        self.assertEqual(winners[0]["event"]["id"], event_id)

    def test_busy_recipient_retains_unrelated_work(self):
        event_id = self.enqueue()
        self.ledger.set_busy("worker-task", "worker-task", True, "synthetic://busy")
        self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))
        self.assertEqual(self.ledger.get(event_id)["attempts"], 0)
        self.ledger.set_busy("worker-task", "worker-task", False, "synthetic://idle")
        self.assertIsNotNone(self.ledger.claim("worker-task", "dispatcher"))

    def test_busy_after_send_refuses_ack_and_retains(self):
        event_id = self.enqueue()
        self.deliver(event_id)
        self.ledger.set_busy("worker-task", "worker-task", True, "synthetic://busy")
        with self.assertRaises(LedgerError):
            self.ledger.ack(event_id, "worker-task", "worker", "synthetic://ack")
        self.assertEqual(self.ledger.get(event_id)["state"], "SENT")

    def test_manual_adapter_never_marks_sent_or_wakes(self):
        event_id = self.enqueue()
        claim = self.ledger.claim("worker-task", "dispatcher")
        envelope = prepare_manual(self.ledger, event_id, claim["delivery_token"])
        self.assertFalse(envelope["transport_accepted"])
        self.assertEqual(envelope["automatic_wake"], "NOT_IMPLEMENTED")
        self.assertEqual(self.ledger.get(event_id)["state"], "QUEUED")
        self.assertNotIn(claim["delivery_token"], json.dumps(envelope))

    def test_delivery_failure_one_inspected_retry_then_blocked(self):
        event_id = self.enqueue()
        for attempt in (1, 2):
            claim = self.ledger.claim("worker-task", "dispatcher")
            self.ledger.delivery_failed(event_id, claim["delivery_token"], "synthetic://failed")
            self.now += 31
            self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))
            if attempt == 1:
                self.ledger.inspect_retry(event_id, "lead", "synthetic://status-inspected")
        self.assertEqual(self.ledger.get(event_id)["state"], "BLOCKED")
        self.assertEqual(self.ledger.get(event_id)["attempts"], 2)
        self.assertEqual(sum(h["action"] == "DELIVERY_FAILURE" for h in self.ledger.history(event_id)), 2)

    def test_missing_ack_not_acceptance(self):
        event_id = self.enqueue()
        self.deliver(event_id)
        self.assertIsNone(self.ledger.get(event_id)["worker_owner"])
        self.now += 121
        self.ledger.recover()
        self.assertEqual(self.ledger.get(event_id)["reason"], "MISSING_ACK")
        with self.assertRaises(LedgerError):
            self.ledger.ack(event_id, "worker-task", "late", "synthetic://late")
        self.now += 31
        self.ledger.inspect_retry(event_id, "lead", "synthetic://status-inspected")
        self.assertEqual(self.ledger.claim("worker-task", "dispatcher")["event"]["id"], event_id)

    def test_expired_delivery_lease_is_ambiguous_and_never_retries_blindly(self):
        event_id = self.enqueue()
        old = self.ledger.claim("worker-task", "old", lease_seconds=10)
        self.now += 11
        self.ledger.recover()
        self.assertEqual(self.ledger.get(event_id)["state"], "SENT_AMBIGUOUS")
        with self.assertRaises(LedgerError):
            self.ledger.inspect_retry(event_id, "lead", "synthetic://inspected")
        self.now += 31
        self.assertIsNone(self.ledger.claim("worker-task", "new"))
        with self.assertRaises(LedgerError):
            self.ledger.sent(event_id, old["delivery_token"], "synthetic://late-receipt")
        self.assertEqual(self.ledger.get(event_id)["state"], "SENT_AMBIGUOUS")

    def test_restart_persists_state_receipts_and_worker_ownership(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        self.ledger = Ledger(self.path, clock=lambda: self.now)
        self.assertEqual(self.ledger.get(event_id)["receipt"], "synthetic://delivery")
        self.ledger.start(event_id, token, "synthetic://resumed")
        self.ledger.complete(event_id, token, "synthetic://result")
        self.assertEqual(Ledger(self.path).get(event_id)["state"], "COMPLETED")

    def test_idempotent_ack_and_single_worker(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        for _ in range(2):
            self.assertEqual(self.ledger.ack(event_id, "worker-task", "worker-1", "synthetic://ack")["worker_token"], token)
        with self.assertRaises(LedgerError):
            self.ledger.ack(event_id, "worker-task", "worker-2", "synthetic://ack")
        self.assertEqual(sum(h["action"] == "ACKED" for h in self.ledger.history(event_id)), 1)

    def test_worker_lease_expiry_retains_slot_until_pm_confirms_stop(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        self.ledger.start(event_id, token, "synthetic://started")
        next_id = self.enqueue("next")
        self.now += 301
        self.ledger.recover()
        self.assertEqual(self.ledger.get(event_id)["state"], "BLOCKED")
        self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))
        with self.assertRaises(LedgerError):
            self.ledger.complete(event_id, token, "synthetic://old-worker")
        with self.assertRaises(LedgerError):
            self.ledger.release_stopped_worker(event_id, "lead", "synthetic://stopped")
        self.ledger.release_stopped_worker(event_id, "pm", "synthetic://stopped")
        self.assertEqual(self.ledger.claim("worker-task", "dispatcher")["event"]["id"], next_id)

    def test_stale_approval_invalidates_and_cannot_ack(self):
        event_id = self.enqueue(kind="APPROVAL")
        self.deliver(event_id)
        self.ledger.checkpoint("lead", "synthetic-issue", "synthetic-scope", "cp-2", "base-1", "head-2", 1, "synthetic://new-cp")
        self.assertEqual(self.ledger.get(event_id)["state"], "SUPERSEDED")
        with self.assertRaises(LedgerError):
            self.ledger.ack(event_id, "worker-task", "worker", "synthetic://stale-ack")
        with self.assertRaises(LedgerError):
            self.enqueue("new-old-approval", kind="APPROVAL")

    def test_checkpoint_compare_and_swap_rejects_stale_update(self):
        with self.assertRaises(LedgerError):
            self.ledger.checkpoint("lead", "synthetic-issue", "synthetic-scope", "cp-2", "base-1", "head-2", 0, "synthetic://cp")
        self.assertEqual(self.ledger.snapshot()["checkpoints"][0]["head"], "head-1")

    def test_stale_active_worker_cannot_complete_or_free_slot(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        self.ledger.start(event_id, token, "synthetic://started")
        self.ledger.checkpoint("lead", "synthetic-issue", "synthetic-scope", "cp-2", "base-1", "head-2", 1, "synthetic://new-cp")
        with self.assertRaises(LedgerError):
            self.ledger.complete(event_id, token, "synthetic://stale-result")
        self.assertEqual(self.ledger.snapshot()["recipients"][0]["active_event"], event_id)

    def test_pm_urgent_stop_bypasses_busy_preserves_active_work(self):
        original = self.enqueue()
        token = self.accept(original)
        self.ledger.start(original, token, "synthetic://started")
        unrelated = self.enqueue("unrelated")
        stop_id = self.enqueue("stop", kind="STOP", priority=100, source_task="pm")
        stop_token = self.accept(stop_id)
        self.ledger.start(stop_id, stop_token, "synthetic://stop-requested")
        self.ledger.complete(stop_id, stop_token, "synthetic://stop-recorded")
        self.assertEqual(self.ledger.get(original)["state"], "STARTED")
        self.assertEqual(self.ledger.get(unrelated)["state"], "QUEUED")
        self.assertEqual(self.ledger.snapshot()["recipients"][0]["active_event"], original)
        self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))

    def test_priority_override_and_stop_require_pm(self):
        event_id = self.enqueue()
        with self.assertRaises(LedgerError):
            self.enqueue("stop", kind="STOP", priority=100)
        with self.assertRaises(LedgerError):
            self.ledger.override_priority(event_id, "lead", 100, "synthetic://override")
        self.ledger.override_priority(event_id, "pm", 100, "synthetic://override")
        self.assertEqual(self.ledger.get(event_id)["priority"], 100)
        self.assertEqual(self.ledger.get(event_id)["payload"]["priority"], 1)

    def test_invalid_tokens_and_early_completion_leave_state_unchanged(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        before = self.ledger.history(event_id)
        with self.assertRaises(LedgerError):
            self.ledger.start(event_id, "wrong-token", "synthetic://start")
        with self.assertRaises(LedgerError):
            self.ledger.complete(event_id, token, "synthetic://too-early")
        self.assertEqual(before, self.ledger.history(event_id))

    def test_cancelled_dependency_does_not_progress(self):
        first = self.enqueue()
        second = self.enqueue("dependent", dependency=first)
        self.ledger.terminate(first, "lead", "CANCELLED", "synthetic://cancelled")
        self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))
        self.assertEqual(self.ledger.get(second)["state"], "QUEUED")

    def test_history_immutable_and_tokens_not_exposed_in_reads(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        self.assertNotIn(token, json.dumps(self.ledger.snapshot()))
        self.assertNotIn(token, json.dumps(self.ledger.history()))
        db = sqlite3.connect(self.path)
        try:
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("DELETE FROM history")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE events SET payload='{}'")
        finally:
            db.close()

    def test_pm_binding_cannot_change(self):
        with self.assertRaises(LedgerError):
            Ledger(self.path, pm_task="different")

    def test_competing_workers_only_one_ack(self):
        event_id = self.enqueue()
        self.deliver(event_id)
        barrier = Barrier(2)
        def accept(worker):
            barrier.wait()
            try:
                return Ledger(self.path, clock=lambda: self.now).ack(event_id, "worker-task", worker, "synthetic://ack")
            except LedgerError:
                return None
        with ThreadPoolExecutor(2) as pool:
            results = list(pool.map(accept, ["worker-a", "worker-b"]))
        self.assertEqual(sum(r is not None for r in results), 1)

    def test_renew_lease_and_reject_expired_renewal(self):
        event_id = self.enqueue()
        token = self.accept(event_id)
        self.now += 200
        self.ledger.renew(event_id, token, lease_seconds=300)
        self.now += 200
        self.ledger.start(event_id, token, "synthetic://still-owned")
        self.now += 101
        with self.assertRaises(LedgerError):
            self.ledger.renew(event_id, token)

    def test_old_completed_approval_is_not_a_fresh_dependency(self):
        approval = self.enqueue(kind="APPROVAL")
        token = self.accept(approval)
        self.ledger.start(approval, token, "synthetic://approval-check")
        self.ledger.complete(approval, token, "synthetic://approved")
        self.ledger.checkpoint("lead", "synthetic-issue", "synthetic-scope", "cp-2", "base-1", "head-2", 1, "synthetic://changed")
        dependent = self.enqueue("new-binding", checkpoint="cp-2", head="head-2", dependency=approval)
        self.assertIsNone(self.ledger.claim("worker-task", "dispatcher"))
        self.assertEqual(self.ledger.get(dependent)["state"], "QUEUED")
        self.assertEqual(self.ledger.get(approval)["state"], "COMPLETED")

    def test_failed_delivery_survives_restart_and_requires_inspection(self):
        event_id = self.enqueue()
        claim = self.ledger.claim("worker-task", "dispatcher")
        self.ledger.delivery_failed(event_id, claim["delivery_token"], "synthetic://failed")
        self.now += 31
        self.ledger = Ledger(self.path, clock=lambda: self.now)
        self.assertIsNone(self.ledger.claim("worker-task", "new-dispatcher"))
        self.ledger.inspect_retry(event_id, "lead", "synthetic://inspected")
        self.assertEqual(self.ledger.claim("worker-task", "new-dispatcher")["event"]["attempts"], 2)

    def test_cli_real_process_read_and_rejection(self):
        event_id = self.enqueue()
        result = subprocess.run([sys.executable, "-m", "comms_ledger", "--db", str(self.path), "get"],
                                cwd=ROOT, input=json.dumps({"event_id": event_id}), text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout)["id"], event_id)
        bad = subprocess.run([sys.executable, "-m", "comms_ledger", "--db", str(self.path), "get"],
                             cwd=ROOT, input='{"event_id":"unknown"}', text=True, capture_output=True, timeout=20)
        self.assertEqual(bad.returncode, 2)
        self.assertEqual(bad.stdout, "")

    def test_schema_version_mismatch_fails_closed(self):
        self.ledger = None
        db = sqlite3.connect(self.path)
        try:
            db.execute("UPDATE config SET value='0' WHERE key='schema_version'")
            db.commit()
        finally:
            db.close()
        with self.assertRaises(LedgerError):
            Ledger(self.path)


if __name__ == "__main__":
    unittest.main()
