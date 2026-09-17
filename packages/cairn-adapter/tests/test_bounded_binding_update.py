"""Exact PM/operator CAS scope for ERP #1632; never a worker command."""
import copy
import hashlib
import io
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

from cairn_adapter import Owner, Rejected, Store
from cairn_adapter.source_preparation import (
    ERP1632_PATHS, ERP1632_TARGET, SCOPE, VERSION, build_bounded_binding_update,
    admit_bounded_binding_update, source_proposal,
)
from cairn_adapter.store import digest, get_config

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "cairn-host"))
import source_operator as source_cli

PM = "11111111-1111-4111-8111-111111111111"
CREDS = {"owner": "owner-token-".ljust(64, "o"),
         PM: "pm-token-".ljust(64, "p"),
         ERP1632_TARGET: "worker-token-".ljust(64, "w")}


class BindingVerifier:
    def __init__(self, base="c" * 40, tree="d" * 40):
        self.base, self.tree = base, tree

    def verify(self, binding, scope):
        source = binding["source"]
        if (scope != SCOPE or source["base"] != self.base or source["base_tree"] != self.tree
                or source["allowed_paths"] != ERP1632_PATHS
                or len(source["test_commands"]) != 2 or len(source["test_artifacts"]) != 3):
            raise Rejected("fresh source contract did not match approved profile")


class BoundedBindingUpdateTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.root = root
        self.store_root = root / "store"
        self.store = Store.initialize(self.store_root, "synthetic/repo", PM, CREDS["owner"])
        repo = root / "worktree"
        repo.mkdir()
        for rel in ("backend/tests/test_auth.py", "backend/tests/test_auth_branch_context.py",
                    "backend/tests/modules/kds/test_kds_ingest_http.py"):
            path = repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("# synthetic pinned smoke fixture\n")
        binding = dict(repository="synthetic/repo", worktree=str(repo), branch="main",
            rule_version=VERSION, config_version=VERSION,
            source=dict(issue=1632, issue_body_sha256=hashlib.sha256(b"approved").hexdigest(),
                base="a" * 40, base_tree="b" * 40, target_thread=ERP1632_TARGET,
                allowed_paths=[".github/workflows/pr-quality-gate.yml"],
                evidence_root=str(root / "evidence"), head_semantics="APPROVED_BASELINE_NOT_CANDIDATE",
                permissions=["local_source", "local_tests", "pr_preparation"],
                allowed_branches=["main"], test_commands=[[sys.executable, "-c", "print('ok')"]]))
        contexts = {PM: str(root / "pm"), ERP1632_TARGET: str(repo)}
        self.prior = dict(registry=source_proposal(binding, PM, CREDS, self.store_root, contexts))
        self.revision = Owner(self.store).replace(CREDS["owner"], 0,
            self.prior["registry"]["entries"])["revision"]
        with self.store.transaction() as (db, _):
            self.live = get_config(db, "registry")
        self.profile = dict(pm_task=PM, target_task=ERP1632_TARGET,
            expected_registry_revision=self.live["revision"],
            expected_registry_digest=digest(self.live), expected_pm_generation=1,
            expected_target_generation=1, allowed_paths=copy.deepcopy(ERP1632_PATHS),
            expected_base="c" * 40, expected_base_tree="d" * 40,
            dedupe_key="cairn:bingxue-erp:1632:infra60ab:step-b-001",
            next_action="Implement the approved Step B slice; keep the existing full gate unchanged")

    def build(self, profile=None, credentials=None):
        return build_bounded_binding_update(self.store, self.prior,
            profile or self.profile, credentials or CREDS, BindingVerifier())

    def add_unrelated_principal(self):
        entries = copy.deepcopy(self.live["entries"])
        unrelated = copy.deepcopy(next(e for e in entries if e["task_id"] == ERP1632_TARGET))
        unrelated.update(task_id="33333333-3333-4333-8333-333333333333",
            credential_hash=hashlib.sha256(b"unrelated-worker-credential").hexdigest(),
            session_id="synthetic-unrelated-worker-session")
        Owner(self.store).replace(CREDS["owner"], self.live["revision"], entries)
        with self.store.transaction() as (db, _): self.live = get_config(db, "registry")
        self.prior["registry"]["entries"] = copy.deepcopy(self.live["entries"])
        self.profile["expected_registry_revision"] = self.live["revision"]
        self.profile["expected_registry_digest"] = digest(self.live)

    def test_operator_reviewed_update_changes_only_exact_binding_and_uses_owner_cas(self):
        self.add_unrelated_principal()
        package = self.build()
        before = copy.deepcopy(self.live["entries"])
        result = admit_bounded_binding_update(package, CREDS, digest(package), BindingVerifier())
        self.assertEqual(result["registry_revision"], 3)
        self.assertEqual(result["allowed_paths"], ERP1632_PATHS)
        with self.store.transaction() as (db, _):
            current = get_config(db, "registry")
        old = {e["task_id"]: e for e in before}
        new = {e["task_id"]: e for e in current["entries"]}
        for task in old:
            a, b = copy.deepcopy(old[task]), copy.deepcopy(new[task])
            if task in {PM, ERP1632_TARGET}:
                for field in ("allowed_paths", "base", "base_tree", "test_commands", "test_artifacts"):
                    a["bindings"][SCOPE]["source"][field] = b["bindings"][SCOPE]["source"][field]
            self.assertEqual(a, b)
        with self.assertRaises(Rejected):
            admit_bounded_binding_update(package, CREDS, digest(package), BindingVerifier())

    def test_stale_registry_cas_is_zero_write(self):
        package = self.build()
        Owner(self.store).replace(CREDS["owner"], 1, self.live["entries"])
        with self.store.transaction() as (db, _): before = digest(get_config(db, "registry"))
        with self.assertRaisesRegex(Rejected, "CAS moved"):
            admit_bounded_binding_update(package, CREDS, digest(package))
        with self.store.transaction() as (db, _): self.assertEqual(digest(get_config(db, "registry")), before)

    def test_worker_cannot_self_expand_or_use_operator_transition(self):
        with self.assertRaises(Rejected):
            self.build(credentials={ERP1632_TARGET: CREDS[ERP1632_TARGET]})
        package = self.build()
        with self.assertRaises(Rejected):
            admit_bounded_binding_update(package,
                {"owner": CREDS[ERP1632_TARGET], PM: CREDS[PM],
                 ERP1632_TARGET: CREDS[ERP1632_TARGET]}, digest(package), BindingVerifier())

    def test_active_source_event_blocks_update(self):
        from comms_ledger.ledger import Ledger
        Ledger(self.store.path).checkpoint(PM, "1632", SCOPE, "step-b",
            "a" * 40, "a" * 40, 0, "artifact://synthetic/checkpoint")
        payload = dict(dedupe_key="active-event", issue="1632", scope=SCOPE,
            checkpoint="step-b", base="a" * 40, head="a" * 40, kind="APPROVAL",
            source_task=PM, target_task=ERP1632_TARGET, priority=1, dependency=None,
            evidence="artifact://synthetic/active", next_action="active")
        Ledger(self.store.path).enqueue(payload)
        with self.store.transaction() as (db, _): before = digest(get_config(db, "registry"))
        with self.assertRaisesRegex(Rejected, "active source event"):
            self.build()
        with self.store.transaction() as (db, _): self.assertEqual(digest(get_config(db, "registry")), before)

    def test_ambiguous_blocked_delivery_without_stop_attestation_blocks_update(self):
        from comms_ledger.ledger import Ledger
        Ledger(self.store.path).checkpoint(PM, "1632", SCOPE, "step-b",
            "a" * 40, "a" * 40, 0, "artifact://synthetic/checkpoint")
        payload = dict(dedupe_key="ambiguous-event", issue="1632", scope=SCOPE,
            checkpoint="step-b", base="a" * 40, head="a" * 40, kind="APPROVAL",
            source_task=PM, target_task=ERP1632_TARGET, priority=1, dependency=None,
            evidence="artifact://synthetic/active", next_action="active")
        event = Ledger(self.store.path).enqueue(payload)
        with self.store.transaction() as (db, _):
            db.execute("UPDATE events SET state='BLOCKED',needs_inspection=1,receipt=? WHERE id=?",
                ("artifact://synthetic/uncertain", event["id"]))
            before = digest(get_config(db, "registry"))
        with self.assertRaisesRegex(Rejected, "PM stop attestation"):
            self.build()
        with self.store.transaction() as (db, _): self.assertEqual(digest(get_config(db, "registry")), before)

    def test_existing_event_dedupe_blocks_binding_update(self):
        from comms_ledger.ledger import Ledger
        Ledger(self.store.path).checkpoint(PM, "1632", SCOPE, "step-b",
            "a" * 40, "a" * 40, 0, "artifact://synthetic/checkpoint")
        payload = dict(dedupe_key=self.profile["dedupe_key"], issue="1632", scope=SCOPE,
            checkpoint="step-b", base="a" * 40, head="a" * 40, kind="APPROVAL",
            source_task=PM, target_task=ERP1632_TARGET, priority=1, dependency=None,
            evidence="artifact://synthetic/active", next_action="active")
        Ledger(self.store.path).enqueue(payload)
        before = digest(self.live)
        with self.assertRaisesRegex(Rejected, "dedupe already exists"):
            self.build()
        with self.store.transaction() as (db, _): self.assertEqual(digest(get_config(db, "registry")), before)

    def test_caller_cannot_choose_additional_or_different_paths(self):
        for paths in (ERP1632_PATHS[:-1], ERP1632_PATHS + ["secrets.env"],
                      ["scripts/ci/backend_impact.py", *ERP1632_PATHS[:1], ERP1632_PATHS[2]]):
            profile = copy.deepcopy(self.profile)
            profile["allowed_paths"] = paths
            with self.subTest(paths=paths), self.assertRaisesRegex(Rejected, "exact approved"):
                self.build(profile)

    def test_metadata_refresh_is_fixed_and_bound_to_fresh_base_and_two_test_commands(self):
        package = self.build()
        binding = next(e for e in package["registry"]["entries"]
            if e["task_id"] == ERP1632_TARGET)["bindings"][SCOPE]
        source = binding["source"]
        self.assertEqual((source["base"], source["base_tree"]), ("c" * 40, "d" * 40))
        self.assertEqual(source["test_commands"][0],
            [sys.executable, "-m", "unittest", "scripts.tests.test_backend_impact", "-v"])
        self.assertIn("tests/modules/kds/test_kds_ingest_http.py", source["test_commands"][1][2])
        self.assertEqual([Path(x["path"]).relative_to(self.root).as_posix()
            for x in source["test_artifacts"]], [
                "worktree/backend/tests/test_auth.py",
                "worktree/backend/tests/test_auth_branch_context.py",
                "worktree/backend/tests/modules/kds/test_kds_ingest_http.py"])

    def test_stale_or_nonreviewed_baseline_is_zero_write(self):
        profile = copy.deepcopy(self.profile)
        profile["expected_base_tree"] = "e" * 40
        before = digest(self.live)
        with self.assertRaisesRegex(Rejected, "fresh source contract"):
            self.build(profile)
        with self.store.transaction() as (db, _): self.assertEqual(digest(get_config(db, "registry")), before)

    def test_followup_metadata_refresh_keeps_the_exact_three_path_scope(self):
        first = self.build()
        admit_bounded_binding_update(first, CREDS, digest(first), BindingVerifier())
        with self.store.transaction() as (db, _): live = get_config(db, "registry")
        prior = copy.deepcopy(self.prior)
        prior["registry"]["entries"] = copy.deepcopy(live["entries"])
        profile = copy.deepcopy(self.profile)
        profile.update(expected_registry_revision=live["revision"],
                       expected_registry_digest=digest(live), expected_base="e" * 40,
                       expected_base_tree="f" * 40)
        second = build_bounded_binding_update(self.store, prior, profile, CREDS,
                                               BindingVerifier("e" * 40, "f" * 40))
        self.assertEqual(next(e for e in second["registry"]["entries"]
            if e["task_id"] == ERP1632_TARGET)["bindings"][SCOPE]["source"]["allowed_paths"],
            ERP1632_PATHS)
        result = admit_bounded_binding_update(second, CREDS, digest(second),
                                               BindingVerifier("e" * 40, "f" * 40))
        self.assertEqual(result["registry_revision"], 3)

    def test_operator_cli_draft_and_cas_update_is_separate_from_event_delivery(self):
        prior_root = Path(self.temp.name) / "prior"
        proposal_root = Path(self.temp.name) / "binding-update"
        prior_root.mkdir()
        source_cli.save(prior_root / "proposal.json", self.prior)
        source_cli.save(prior_root / "operator-credentials.json", CREDS)
        profile_path = Path(self.temp.name) / "profile.json"
        source_cli.save(profile_path, self.profile)
        with patch("cairn_adapter.source_preparation.SourceVerifier", BindingVerifier), redirect_stdout(io.StringIO()):
            source_cli.main(["binding-update-draft", "--proposal-root", str(proposal_root),
                "--prior-proposal-root", str(prior_root), "--profile", str(profile_path)])
        package = source_cli.read_json(proposal_root / "proposal.json")
        reviewed = digest(package)
        with patch("cairn_adapter.source_preparation.SourceVerifier", BindingVerifier), redirect_stdout(io.StringIO()):
            source_cli.main(["binding-update", "--proposal-root", str(proposal_root),
                "--reviewed-digest", reviewed])
        with self.store.transaction() as (db, _):
            self.assertEqual(get_config(db, "registry")["revision"], 2)
            self.assertEqual(db.execute("SELECT COUNT(*) FROM events").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
