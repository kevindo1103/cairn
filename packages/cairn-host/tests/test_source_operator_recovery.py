"""Recovery CLI contract using only synthetic Store/Git/credentials, never live state."""
import copy
import io
import json
from contextlib import redirect_stdout
from pathlib import Path
import time
import unittest
from unittest.mock import patch

import source_operator as cli
import test_source_operator_successor as fixture
from cairn_adapter import Store, Owner, Rejected
from cairn_adapter import source_preparation as source
from cairn_adapter.store import canonical, digest, get_config
from cairn_adapter.recovery import proof
from comms_ledger.ledger import LedgerError

PM, TARGET = fixture.PM, fixture.TARGET


class RecoveryTests(unittest.TestCase):
    reuse = False
    @classmethod
    def setUpClass(cls):
        fixture.SuccessorTests.setUpClass.__func__(cls)

    @classmethod
    def tearDownClass(cls):
        fixture.SuccessorTests.tearDownClass.__func__(cls)

    def setUp(self):
        fixture.SuccessorTests.setUp(self)
        # Advance only the synthetic canonical registry to the requested old rev4.
        initial_entries = copy.deepcopy(self.registry["entries"])
        if self.reuse:
            initial_entries[0]["grants"].append(dict(command="inspect_retry", scope=source.SCOPE, states=["QUEUED"]))
            initial_entries[0]["authority"] = sorted([*initial_entries[0]["authority"], "inspect_retry"])
        for revision in (1, 2):
            Owner(self.store).replace(self.credentials["owner"], revision, initial_entries)
        with self.store.transaction() as (db, _):
            current = get_config(db, "registry")
        self.profile.update(expected_registry_revision=3, expected_registry_digest=digest(current))
        self.profile_path.write_text(canonical(self.profile))
        self.now = [time.time()]
        self.fixture_store = lambda root, project: Store(root, project, clock=lambda: self.now[0])
        self.store = self.fixture_store(self.store_root, "synthetic/repo")
        result = self.invoke("successor-draft", self.new_root, None,
            "--prior-proposal-root", str(self.old_root), "--profile", str(self.profile_path))
        self.original_digest = result["proposal_sha256"]
        self.invoke("activate", self.new_root, self.original_digest)
        self.event = self.invoke("event", self.new_root, self.original_digest)["result"]["event_id"]
        with self.store.transaction() as (db, _):
            self.rev4 = get_config(db, "registry")
        self.assertEqual(self.rev4["revision"], 4)
        self.assertEqual("inspect_retry" in self.rev4["entries"][0]["authority"], self.reuse)
        # The fixture's transport was never called. Record the supported explicit
        # pre-send failure before testing retry inspection; expiry alone is ambiguous.
        private_delivery = cli.read_json(self.new_root / "delivery-private.json")
        host = source.SourceHost(self.store, source.principal_identity(self.rev4["entries"], self.credentials),
                                 self.verifier)
        with self.store.transaction() as (db, ledger):
            claimed_event = ledger._get(db, self.event)
        host.execute(self.credentials[PM], self.rev4["entries"][0]["generation"],
                     self.rev4["revision"], "delivery_failed",
                     {"event_id": self.event, "delivery_token": private_delivery["delivery_token"],
                      "evidence": source.no_send_failure_evidence(claimed_event, private_delivery["delivery_token"])})
        self.recovery_root = self.folder / "recovery"
        self.original_bytes = {name: (self.new_root / name).read_bytes()
            for name in ("proposal.json", "delivery-private.json", "worker-credential.json")}

    def invoke(self, command, root, reviewed, *args):
        argv = [command, "--proposal-root", str(root)]
        if reviewed is not None:
            argv += ["--reviewed-digest", reviewed]
        output = io.StringIO()
        with patch.object(cli, "Store", self.fixture_store), patch.object(source, "Store", self.fixture_store), \
             patch.object(cli, "SourceVerifier", lambda: self.verifier), \
             patch.object(cli, "SourceHost", lambda s, i: source.SourceHost(s, i, self.verifier)), \
             redirect_stdout(output):
            cli.main(argv + list(args))
        for token in self.credentials.values():
            self.assertNotIn(token, output.getvalue())
        for name in ("delivery-private.json", "delivery-attempt-2.json", "worker-lease-private.json"):
            path = root / name
            if path.exists() and path.stat().st_size:
                for key, value in cli.read_json(path).items():
                    if key.endswith("token"):
                        self.assertNotIn(value, output.getvalue())
        return json.loads(output.getvalue())

    def draft(self):
        before = proof(self.store.path)
        result = self.invoke("recovery-draft", self.recovery_root, None,
            "--prior-proposal-root", str(self.new_root), "--event-id", self.event,
            *(["--reuse-existing-grant"] if self.reuse else []))
        self.assertEqual(before, proof(self.store.path))
        self.recovery_digest = result["proposal_sha256"]
        self.package = cli.read_json(self.recovery_root / "proposal.json")
        return result

    def command(self, name, *args):
        return self.invoke(name, self.recovery_root, self.recovery_digest,
                           "--event-id", self.event, *args)

    def inspect(self):
        return self.command("inspect-retry", "--no-send-confirmed", "--evidence", "artifact://synthetic/pm-no-send")

    def ready(self):
        self.draft()
        before = proof(self.store.path)
        self.command("recover-authority")
        if self.reuse:
            self.assertEqual(proof(self.store.path), before)

    def zero_write(self, fn, error=LedgerError):
        before = proof(self.store.path)
        with self.assertRaises(error):
            fn()
        self.assertEqual(before, proof(self.store.path))

    def test_full_cli_from_rev4_without_grant_through_completion_and_replay(self):
        self.ready()
        with self.store.transaction() as (db, _):
            rev5 = get_config(db, "registry")
        expected = copy.deepcopy(self.rev4)
        if not self.reuse:
            expected["revision"] = 5
            pm = expected["entries"][0]
            pm["grants"].append(dict(command="inspect_retry", scope=source.SCOPE, states=["QUEUED"]))
            pm["authority"] = sorted([*pm["authority"], "inspect_retry"])
        self.assertEqual(rev5, expected)
        self.assertEqual(cli.read_json(self.recovery_root / "worker-credential.json"), {TARGET: self.credentials[TARGET]})
        self.inspect()
        self.zero_write(lambda: self.command("reclaim"))
        self.now[0] += 30
        self.command("reclaim")
        self.zero_write(lambda: self.command("reclaim"))
        observations = [dict(event_id=self.event, source="synthetic offline transport", accepted=True)]
        cli.save(self.folder / "synthetic-transport-receipt.json", observations[0])
        self.command("sent", "--evidence", "artifact://synthetic/transport/" + digest(observations[0]))
        # Fresh operator/worker CLI invocation; worker cannot access either operator secret file.
        for root in (self.new_root, self.recovery_root):
            (root / "operator-credentials.json").rename(root / "operator-private.saved")
        self.command("ack")
        self.command("start", "--evidence", "artifact://synthetic/worker-start")
        (self.repo / "source.txt").write_text("fixed\n")
        result = self.command("test", "--test-index", "0")["result"]
        self.assertEqual(result["exit_code"], 0)
        self.assertEqual(self.command("complete", "--test-evidence", result["evidence"])["result"]["state"], "COMPLETED")
        for root in (self.new_root, self.recovery_root):
            (root / "operator-private.saved").rename(root / "operator-credentials.json")
        self.store = self.fixture_store(self.store_root, "synthetic/repo")
        for cmd, args in (("recover-authority", ()), ("inspect-retry", ("--no-send-confirmed", "--evidence", "artifact://synthetic/duplicate")),
                ("reclaim", ()), ("sent", ("--evidence", "artifact://synthetic/duplicate")), ("ack", ()),
                ("complete", ("--test-evidence", result["evidence"])), ("event", ()), ("activate", ())):
            with self.subTest(replay=cmd):
                self.zero_write(lambda: self.command(cmd, *args))
        with self.store.transaction() as (db, ledger):
            actions = [r[0] for r in db.execute("SELECT action FROM history WHERE event_id=? ORDER BY seq", (self.event,))]
            self.assertEqual(actions.count("CLAIMED"), 2)
            for name in ("QUEUED", "SENT", "ACKED", "STARTED", "COMPLETED"):
                self.assertEqual(actions.count(name), 1)
            self.assertEqual(ledger._get(db, self.parent)["state"], "BLOCKED")
        self.assertEqual(len(observations), 1)
        for name, raw in self.original_bytes.items():
            self.assertEqual((self.new_root / name).read_bytes(), raw)
        self.assertEqual((self.recovery_root / "delivery-private.json").read_bytes(), self.original_bytes["delivery-private.json"])

    def test_missing_no_send_confirmation_missing_inspection_and_backoff(self):
        self.ready()
        for args in ((), ("--evidence", "artifact://synthetic/assertion-only"), ("--no-send-confirmed",)):
            self.zero_write(lambda: self.command("inspect-retry", *args))
        self.zero_write(lambda: self.command("reclaim"), FileNotFoundError)
        self.assertFalse((self.recovery_root / "delivery-attempt-2.json").exists())
        self.inspect()
        self.zero_write(self.inspect)
        self.zero_write(lambda: self.command("reclaim"))
        self.now[0] += 29
        self.zero_write(lambda: self.command("reclaim"))
        self.now[0] += 1
        self.command("reclaim")

    def test_stale_cas_and_exact_revision_after_admission(self):
        self.draft()
        Owner(self.store).replace(self.credentials["owner"], 4, self.rev4["entries"])
        self.zero_write(lambda: self.command("recover-authority"))

    def test_changed_binding_or_extra_authority_in_package(self):
        self.draft()
        original = self.package
        for kind in ("binding", "grant"):
            bad = copy.deepcopy(original)
            if kind == "binding":
                bad["registry"]["entries"][1]["bindings"][source.SCOPE]["source"]["allowed_paths"] = ["outside"]
            else:
                bad["registry"]["entries"][1]["authority"].append("inspect_retry")
            (self.recovery_root / "proposal.json").write_text(canonical(bad))
            self.recovery_digest = digest(bad)
            self.zero_write(lambda: self.command("recover-authority"))
        (self.recovery_root / "proposal.json").write_text(canonical(original))
        self.recovery_digest = digest(original)
        self.command("recover-authority")
        with self.store.transaction() as (db, _):
            entries = get_config(db, "registry")["entries"]
        Owner(self.store).replace(self.credentials["owner"], 5, entries)
        self.zero_write(self.inspect)  # identical entries, wrong revision

    def test_prior_sent_and_ambiguous_history_refused(self):
        # The explicit no-send path can be inspected/reclaimed; a later accepted
        # transport receipt makes the event ineligible for another recovery.
        self.ready()
        self.inspect()
        self.now[0] += 30
        self.command("reclaim")
        self.command("sent", "--evidence", "artifact://synthetic/already-sent")
        self.zero_write(lambda: self.command("recover-authority"))

    def test_expired_ambiguous_claim_cannot_enter_no_send_recovery(self):
        self.ready()
        self.inspect()
        self.now[0] += 30
        self.command("reclaim")
        self.now[0] += 61
        host = source.SourceHost(self.store, source.principal_identity(self.rev4["entries"], self.credentials),
                                 self.verifier)
        host.execute(self.credentials[PM], self.rev4["entries"][0]["generation"],
                     self.package["recovery"]["admitted_revision"], "claim", {"event_id": self.event})
        self.recovery_root = self.folder / "recovery-after-ambiguous"
        self.zero_write(self.draft, Rejected)

    def test_ambiguous_claim_without_matching_prior_receipt_refused(self):
        receipt = cli.read_json(self.new_root / "delivery-private.json")
        receipt["delivery_token"] = "wrong-token"
        (self.new_root / "delivery-private.json").write_text(canonical(receipt))
        self.zero_write(self.draft)

    def test_existing_root_original_receipt_mutation_and_stale_attempt_refused(self):
        self.draft()
        self.zero_write(self.draft, FileExistsError)
        path = self.new_root / "delivery-private.json"
        path.write_text("{}")
        self.zero_write(lambda: self.command("recover-authority"))
        path.write_bytes(self.original_bytes["delivery-private.json"])
        self.command("recover-authority")
        self.inspect()
        self.now[0] += 30
        self.command("reclaim")
        current_path = self.recovery_root / "delivery-attempt-2.json"
        correct = current_path.read_bytes()
        current = json.loads(correct)
        for field, value in (("delivery_token", cli.read_json(path)["delivery_token"]), ("attempt", 1),
                             ("event_id", self.parent), ("proposal_digest", "wrong")):
            wrong = {**current, field: value}
            current_path.write_text(canonical(wrong))
            self.zero_write(lambda: self.command("sent", "--evidence", "artifact://synthetic/stale-attempt"))
        current_path.write_bytes(correct)

    def test_reclaim_fsync_failure_preserves_guard_and_rolls_back(self):
        self.ready(); self.inspect(); self.now[0] += 30
        with patch.object(cli.os, "fsync", side_effect=OSError("synthetic disk failure")):
            self.zero_write(lambda: self.command("reclaim"), OSError)
        self.assertTrue((self.recovery_root / "delivery-attempt-2.json").exists())
        self.zero_write(lambda: self.command("reclaim"))
        self.zero_write(lambda: self.command("sent", "--evidence", "artifact://synthetic/ambiguous"))

    def test_reuse_refuses_absent_grant(self):
        self.zero_write(lambda: self.invoke("recovery-draft", self.recovery_root, None,
            "--prior-proposal-root", str(self.new_root), "--event-id", self.event, "--reuse-existing-grant"))


class ReuseTests(unittest.TestCase):
    reuse = True
    setUpClass = classmethod(RecoveryTests.setUpClass.__func__)
    tearDownClass = classmethod(RecoveryTests.tearDownClass.__func__)
    setUp = RecoveryTests.setUp
    invoke = RecoveryTests.invoke
    draft = RecoveryTests.draft
    command = RecoveryTests.command
    inspect = RecoveryTests.inspect
    ready = RecoveryTests.ready
    zero_write = RecoveryTests.zero_write
    test_full_cli_with_existing_rev4_grant_and_replay = RecoveryTests.test_full_cli_from_rev4_without_grant_through_completion_and_replay
    test_missing_confirmation_and_backoff = RecoveryTests.test_missing_no_send_confirmation_missing_inspection_and_backoff
    test_changed_registry = RecoveryTests.test_stale_cas_and_exact_revision_after_admission

    def test_changed_claim_rejected_without_cas(self):
        # A no-send failure is safely inspected/reclaimed; once the reclaimed
        # lease expires, it is ambiguous and cannot reuse the no-send package.
        self.ready()
        self.inspect()
        self.now[0] += 30
        self.command("reclaim")
        self.now[0] += 61
        host = source.SourceHost(self.store, source.principal_identity(self.rev4["entries"], self.credentials),
                                 self.verifier)
        host.execute(self.credentials[PM], self.rev4["entries"][0]["generation"],
                     self.package["recovery"]["admitted_revision"], "claim", {"event_id": self.event})
        self.zero_write(lambda: self.command("recover-authority"))
        self.zero_write(self.inspect)

    def test_reuse_refuses_different_grant(self):
        entries = copy.deepcopy(self.rev4["entries"])
        grant = next(g for g in entries[0]["grants"] if g["command"] == "inspect_retry")
        grant["states"].append("SENT")
        Owner(self.store).replace(self.credentials["owner"], 4, entries)
        prior = cli.read_json(self.new_root / "proposal.json")
        prior["registry"].update(entries=entries, expected_revision=4)
        (self.new_root / "proposal.json").write_text(canonical(prior))
        self.zero_write(self.draft)
