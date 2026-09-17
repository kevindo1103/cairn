"""Synthetic-only admission/CLI tests: real SQLite, Git and child test execution."""
import copy
import hashlib
import io
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing, redirect_stdout
from unittest.mock import patch

import source_operator as cli
from cairn_adapter import Store, Owner, Rejected
from cairn_adapter.store import canonical, digest, get_config, put_config
from cairn_adapter.source_preparation import (
    SourceHost, SourceVerifier, source_proposal, principal_identity, SCOPE, VERSION)
from cairn_adapter.recovery import proof
from comms_ledger.ledger import LedgerError
import test_verifier as fixtures

PM = "11111111-1111-4111-8111-111111111111"
TARGET = "22222222-2222-4222-8222-222222222222"


class SuccessorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.temp.name)
        cls.repo = cls.root / "repo"
        cls.repo.mkdir()
        def git(*args):
            return subprocess.check_output(["git", "-C", str(cls.repo), *args],
                                           stderr=subprocess.PIPE, timeout=20).decode("utf-8").strip()
        git("init", "-b", "main")
        git("remote", "add", "origin", "https://github.com/synthetic/repo.git")
        (cls.repo / "source.txt").write_text("base\n")
        git("add", ".")
        git("-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
            "commit", "-m", "synthetic")
        cls.head, cls.tree = git("rev-parse", "HEAD"), git("rev-parse", "HEAD^{tree}")
        cls.responses = {"repos/synthetic/repo/issues/7": dict(number=7, state="open", body="approved"),
                         "repos/synthetic/repo/commits/main":
                         dict(sha=cls.head, commit=dict(tree=dict(sha=cls.tree)))}
        cls.credentials = {task: (task + "-synthetic-token-").ljust(64, "x") for task in ("owner", PM, TARGET)}
        cls.validator = cls.root / "validate.py"
        cls.validator.write_text("from pathlib import Path\nassert Path('source.txt').read_text() in ('base\\n', 'fixed\\n')\nprint('verified')\n")
        cls.initial_script = cls.validator.read_bytes()
        cls.binding = dict(repository="synthetic/repo", worktree=str(cls.repo), branch="main",
                           rule_version=VERSION, config_version=VERSION,
                           source=dict(issue=7, issue_body_sha256=hashlib.sha256(b"approved").hexdigest(),
                           base=cls.head, base_tree=cls.tree, target_thread=TARGET,
                           allowed_paths=["source.txt", "more"], evidence_root=str(cls.root / "evidence"),
                           head_semantics="APPROVED_BASELINE_NOT_CANDIDATE",
                           permissions=["local_source", "local_tests", "pr_preparation"],
                           allowed_branches=["main"], test_commands=[[sys.executable, str(cls.validator)]]))
        cls.contexts = {PM: str(cls.root / "pm-context"), TARGET: str(cls.repo)}
        cls.template = cls.root / "template"
        store = Store.initialize(cls.template, "synthetic/repo", PM, cls.credentials["owner"])
        cls.prior = dict(registry=source_proposal(cls.binding, PM, cls.credentials,
                         cls.template, cls.contexts), event={})
        entries = cls.prior["registry"]["entries"]
        pm = entries[0]
        for command in ("handoff_review", "release_stopped_worker"):
            pm["grants"].append(dict(command=command, scope=SCOPE, states=["BLOCKED"]))
            pm["authority"].append(command)
        pm["authority"].sort()
        Owner(store).replace(cls.credentials["owner"], 0, entries)
        now = [1000.]
        store.clock = lambda: now[0]
        host = SourceHost(store, principal_identity(entries, cls.credentials),
                          SourceVerifier(fixtures.FixtureGitHub(cls.responses)))
        def call(task, cmd, **args):
            return host.execute(cls.credentials[task], 1, 1, cmd, args)
        call(PM, "checkpoint")
        cls.parent = call(PM, "enqueue", dedupe_key="parent", target=TARGET, kind="APPROVAL",
                          priority=1, dependency=None, next_action="original")["id"]
        claimed = call(PM, "claim", event_id=cls.parent)
        call(PM, "sent", event_id=cls.parent, delivery_token=claimed["delivery_token"],
             receipt="artifact://synthetic/transport")
        call(TARGET, "reconcile", event_id=cls.parent)
        ack = call(TARGET, "ack", event_id=cls.parent)
        call(TARGET, "start", event_id=cls.parent, worker_token=ack["worker_token"],
             evidence="artifact://synthetic/start")
        now[0] += 301
        with store.transaction() as (_, ledger):
            ledger.recover()
        cls.unreleased = cls.root / "unreleased.sqlite"
        with closing(sqlite3.connect(store.path)) as db, closing(sqlite3.connect(cls.unreleased)) as dest:
            db.backup(dest)
        review = call(PM, "handoff_review", event_id=cls.parent)
        Owner(store).attest(cls.credentials["owner"], 1, cls.parent, "release_stopped_worker",
                           review["digest"], "artifact://synthetic/observed-stop")
        call(PM, "release_stopped_worker", event_id=cls.parent)

    @classmethod
    def tearDownClass(cls):
        cls.temp.cleanup()

    def setUp(self):
        self.case = tempfile.TemporaryDirectory(dir=self.root)
        self.addCleanup(self.case.cleanup)
        self.folder = Path(self.case.name)
        self.store_root = self.folder / "store"
        self.store_root.mkdir()
        # This copies ONLY the synthetic database created above; no live paths/secrets.
        with closing(sqlite3.connect(self.template / "ledger.sqlite")) as src, closing(sqlite3.connect(self.store_root / "ledger.sqlite")) as dst:
            src.backup(dst)
        (self.repo / "source.txt").write_text("base\n")
        self.validator.write_bytes(self.initial_script)
        self.store = Store(self.store_root, "synthetic/repo")
        self.verifier = SourceVerifier(fixtures.FixtureGitHub(copy.deepcopy(self.responses)))
        prior = copy.deepcopy(self.prior)
        prior["registry"]["store_root"] = str(self.store_root)
        self.old_root = self.folder / "prior"
        self.old_root.mkdir()
        cli.save(self.old_root / "proposal.json", prior)
        cli.save(self.old_root / "operator-credentials.json", self.credentials)
        with self.store.transaction() as (db, _):
            self.registry = get_config(db, "registry")
        self.profile = dict(pm_task=PM, target_task=TARGET, parent_event_id=self.parent,
            expected_registry_revision=1, expected_registry_digest=digest(self.registry),
            dedupe_key="next", next_action="Apply reviewed source correction, test and complete",
            allowed_paths=["source.txt"], test_commands=[[sys.executable, str(self.validator)]],
            test_artifacts=[dict(path=str(self.validator), sha256=hashlib.sha256(self.initial_script).hexdigest())])
        self.new_root = self.folder / "successor"
        self.profile_path = self.folder / "profile.json"
        cli.save(self.profile_path, self.profile)

    def run_cli(self, command, *extra):
        args = [command, "--proposal-root", str(self.new_root)]
        if command == "successor-draft":
            args += ["--prior-proposal-root", str(self.old_root), "--profile", str(self.profile_path)]
        else:
            args += ["--reviewed-digest", self.package_digest]
        output = io.StringIO()
        with patch.object(cli, "SourceVerifier", lambda: self.verifier), \
             patch.object(cli, "SourceHost", lambda s, i: SourceHost(s, i, self.verifier)), \
             redirect_stdout(output):
            cli.main(args + list(extra))
        for secret in self.credentials.values():
            self.assertNotIn(secret, output.getvalue())
        return json.loads(output.getvalue())

    def draft(self):
        result = self.run_cli("successor-draft")
        self.package = cli.read_json(self.new_root / "proposal.json")
        self.package_digest = result["proposal_sha256"]
        return result

    def zero_write(self, fn, error=LedgerError):
        before = proof(self.store.path)
        with self.assertRaises(error):
            fn()
        self.assertEqual(proof(self.store.path), before)

    def start(self):
        self.draft()
        self.run_cli("activate")
        event = self.run_cli("event")["result"]["event_id"]
        self.event = event
        self.run_cli("sent", "--event-id", event, "--evidence", "artifact://synthetic/only-delivery")
        self.run_cli("ack", "--event-id", event)
        self.run_cli("start", "--event-id", event, "--evidence", "artifact://synthetic/started")
        return event

    def test_full_cli_completion_reopen_and_replay(self):
        event = self.start()
        (self.repo / "source.txt").write_text("fixed\n")
        # Worker operations must not depend on access to Owner/PM secrets.
        (self.new_root / "operator-credentials.json").rename(self.new_root / "operator-private.saved")
        result = self.run_cli("test", "--event-id", event, "--test-index", "0")["result"]
        completed = self.run_cli("complete", "--event-id", event, "--test-evidence", result["evidence"])
        self.assertEqual(completed["result"]["state"], "COMPLETED")
        (self.new_root / "operator-private.saved").rename(self.new_root / "operator-credentials.json")
        self.store = Store(self.store_root, "synthetic/repo")
        for command, args in (("activate", []), ("event", []),
                ("sent", ["--event-id", event, "--evidence", "artifact://synthetic/duplicate"]),
                ("ack", ["--event-id", event]),
                ("complete", ["--event-id", event, "--test-evidence", result["evidence"]])):
            with self.subTest(command=command):
                self.zero_write(lambda: self.run_cli(command, *args))
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger._get(db, self.parent)["state"], "BLOCKED")
            current = get_config(db, "registry")
            for old, new in zip(self.registry["entries"], current["entries"]):
                self.assertEqual({k:v for k,v in old.items() if k != "bindings"},
                                 {k:v for k,v in new.items() if k != "bindings"})
            for action in ("CLAIMED", "SENT", "ACKED", "STARTED", "COMPLETED"):
                self.assertEqual(db.execute("SELECT count(*) FROM history WHERE event_id=? AND action=?",
                                           (event, action)).fetchone()[0], 1)

    def test_fault_after_owner_cas_rolls_back_checkpoint_and_registry(self):
        self.draft()
        original = Owner.replace
        observed = []
        def fail(owner, *args):
            result = original(owner, *args)
            observed.append(result["revision"])
            raise RuntimeError("fault after CAS")
        with patch.object(Owner, "replace", fail):
            self.zero_write(lambda: self.run_cli("activate"), RuntimeError)
        self.assertEqual(observed, [2])
        self.run_cli("activate")

    def test_checkpoint_failure_rolls_back_cas(self):
        self.draft()
        original = SourceHost.execute
        def fail(host, credential, generation, revision, command, args):
            if command == "checkpoint":
                raise RuntimeError("checkpoint unavailable")
            return original(host, credential, generation, revision, command, args)
        with patch.object(SourceHost, "execute", fail):
            self.zero_write(lambda: self.run_cli("activate"), RuntimeError)

    def test_stale_cas_and_tampered_authority(self):
        self.draft()
        bad = copy.deepcopy(self.package)
        bad["registry"]["entries"][1]["authority"].append("enqueue")
        self.zero_write(lambda: cli.admit_successor(bad, self.credentials, digest(bad), self.verifier))
        Owner(self.store).replace(self.credentials["owner"], 1, self.registry["entries"])
        self.zero_write(lambda: self.run_cli("activate"))

    def test_unreleased_parent_and_missing_stop_proof(self):
        with closing(sqlite3.connect(self.unreleased)) as src, closing(sqlite3.connect(self.store.path)) as dst:
            src.backup(dst)
        self.zero_write(self.draft)

    def test_missing_parent(self):
        self.profile["parent_event_id"] = "absent-parent"
        self.profile_path.write_text(canonical(self.profile))
        self.zero_write(self.draft)

    def test_nonblocked_parent(self):
        with self.store.transaction() as (db, _):
            db.execute("UPDATE events SET state='COMPLETED' WHERE id=?", (self.parent,))
        self.zero_write(self.draft)

    def test_wrong_parent_generation(self):
        with self.store.transaction() as (db, _):
            value = get_config(db, "event:" + self.parent)
            value["target"]["generation"] += 1
            put_config(db, "event:" + self.parent, value)
        self.zero_write(self.draft)

    def test_released_parent_without_attestation(self):
        with self.store.transaction() as (db, _):
            db.execute("DELETE FROM config WHERE key=?",
                       ("adapter:attest:release_stopped_worker:" + self.parent,))
        self.zero_write(self.draft)

    def test_dedupe_collision_and_ambiguous_private_file(self):
        self.draft()
        self.run_cli("activate")
        self.run_cli("event")
        self.zero_write(lambda: self.run_cli("event"))
        # Missing private artifact cannot re-enable a claim: durable dedupe refuses.
        (self.new_root / "delivery-private.json").unlink()
        self.zero_write(lambda: self.run_cli("event"))

    def test_crash_after_claim_preserves_ambiguous_guard_without_resend(self):
        self.draft()
        self.run_cli("activate")
        with patch.object(cli.os, "fsync", side_effect=OSError("disk failure")):
            self.zero_write(lambda: self.run_cli("event"), OSError)
        self.assertTrue((self.new_root / "delivery-private.json").exists())
        self.zero_write(lambda: self.run_cli("event"))

    def test_artifact_and_candidate_mutation_before_admission(self):
        self.draft()
        self.validator.write_text("raise SystemExit(0)\n")
        self.zero_write(lambda: self.run_cli("activate"))
        self.validator.write_bytes(self.initial_script)
        (self.repo / "source.txt").write_text("fixed\n")
        self.zero_write(lambda: self.run_cli("activate"))

    def test_fresh_github_refusal(self):
        self.draft()
        self.verifier.github.responses["repos/synthetic/repo/commits/main"]["sha"] = "a" * 40
        self.zero_write(lambda: self.run_cli("activate"))

    def test_timeout_test_failure_and_drift_do_not_complete(self):
        self.start()
        binding = self.package["registry"]["entries"][1]["bindings"][SCOPE]
        host = SourceHost(self.store, principal_identity(self.registry["entries"], self.credentials), self.verifier)
        real_run = subprocess.run
        def timeout_child(argv, **kwargs):
            if argv == binding["source"]["test_commands"][0]:
                raise subprocess.TimeoutExpired(argv, 120)
            return real_run(argv, **kwargs)
        with patch("cairn_adapter.source_preparation.subprocess.run", side_effect=timeout_child):
            self.zero_write(lambda: host.run_test(binding, 0), subprocess.TimeoutExpired)
        result = host.run_test(binding, 0)
        (self.repo / "source.txt").write_text("fixed\n")
        self.zero_write(lambda: self.run_cli("complete", "--event-id", self.event,
                                            "--test-evidence", result["evidence"]))
        self.validator.write_text("raise SystemExit(1)\n")
        self.zero_write(lambda: self.run_cli("test", "--event-id", self.event, "--test-index", "0"))
