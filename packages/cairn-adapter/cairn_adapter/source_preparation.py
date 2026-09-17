"""Pre-PR local source work under the existing Cairn lifecycle, never release.

Event head/base identify the owner-approved starting source. The mutable candidate
is independently inventoried and completion binds its exact content snapshot.
"""
import copy
import hashlib
import json
import re
import subprocess
from pathlib import Path
from contextlib import contextmanager

from .adapter import Adapter
from .preparation import proposal as preparation_proposal
from .store import Rejected, digest, canonical, get_config, credential_hash, Owner, Store
from .verifier import GitHubVerifier, safe_path, in_scope

SCOPE="PRE_PR_SOURCE"
VERSION="pre-pr-source-1"
ERP1632_TARGET = "01a0a959-b752-70f0-9118-900571ba60ab"
ERP1632_PATHS = [
    ".github/workflows/pr-quality-gate.yml",
    "scripts/ci/backend_impact.py",
    "scripts/tests/test_backend_impact.py",
]


def no_send_failure_evidence(event, delivery_token):
    """Bind the PM's explicit NOT_SENT report to one event and claim token."""
    body = dict(event_id=event["id"], event_digest=event["digest"], attempt=event["attempts"],
                delivery_token_digest=hashlib.sha256(delivery_token.encode("utf-8")).hexdigest(),
                result="NOT_SENT")
    return "artifact://sha256/" + digest(body)


def check_artifacts(artifacts):
    if not isinstance(artifacts, list) or not artifacts:
        raise Rejected("Pinned test artifacts required")
    for item in artifacts:
        if not isinstance(item, dict) or set(item) != {"path", "sha256"}:
            raise Rejected("Malformed artifact binding")
        path = Path(item["path"])
        if (not path.is_absolute() or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                for p in (path, *path.parents)) or not path.is_file()
                or hashlib.sha256(path.read_bytes()).hexdigest() != item["sha256"]):
            raise Rejected("Pinned test artifact changed or unavailable")


class BoundSourceStore:
    """Reuse a caller-owned transaction; nested Owner/Adapter calls cannot commit."""
    def __init__(self, store, db, ledger):
        self.path, self.project, self.clock = store.path, store.project, store.clock
        self.db, self.ledger = db, ledger

    @contextmanager
    def transaction(self):
        yield self.db, self.ledger


def principal_identity(entries, credentials):
    by_task = {entry["task_id"]: entry for entry in entries}
    def resolve(token):
        for task, secret in credentials.items():
            if task in by_task and secret == token:
                entry = by_task[task]
                return dict(task_id=task, session_id=entry["session_id"],
                            generation=entry["generation"])
        return None
    return resolve


def successor_preconditions(db, ledger, profile, *, check_registry=True):
    registry = get_config(db, "registry")
    if check_registry and (registry["revision"] != profile["expected_registry_revision"]
                           or digest(registry) != profile["expected_registry_digest"]):
        raise Rejected("Successor registry CAS moved")
    parent = ledger._get(db, profile["parent_event_id"])
    payload = json.loads(parent["payload"])
    target, pm = profile["target_task"], profile["pm_task"]
    if (parent["state"] != "BLOCKED" or parent["target"] != target
            or payload["source_task"] != pm or payload["scope"] != SCOPE
            or ledger._pm_authority(db)["task_id"] != pm):
        raise Rejected("Parent/source/target binding mismatch")
    slot = db.execute("SELECT active_event FROM recipients WHERE task=?", (target,)).fetchone()
    if slot is None or slot[0] is not None:
        raise Rejected("Parent worker slot not released")
    attestation = get_config(db, "attest:release_stopped_worker:" + parent["id"])
    records = db.execute("SELECT seq,detail FROM history WHERE event_id=? AND action=? AND actor=?",
                        (parent["id"], "WORKER_CONFIRMED_STOPPED", pm)).fetchall()
    matching = [dict(row) for row in records
                if json.loads(row["detail"]).get("evidence") == attestation["evidence"]]
    if not matching:
        raise Rejected("Parent lacks separately attested worker-stop release")
    if db.execute("SELECT 1 FROM events WHERE dedupe_key=?", (profile["dedupe_key"],)).fetchone():
        raise Rejected("Successor dedupe exists; reconcile only")
    # A new checkpoint must not silently invalidate other live work in this scope.
    for row in db.execute("SELECT payload FROM events WHERE state IN ('QUEUED','SENT','ACKED','STARTED')"):
        if json.loads(row["payload"])["scope"] == SCOPE:
            raise Rejected("Other source work still active")
    return dict(parent_digest=parent["digest"], release_digest=digest(
        dict(attestation=attestation, history=matching)))


def build_successor(store, prior, profile, credentials, verifier):
    """Pure proposal construction inside the existing Store transaction."""
    fields = {"pm_task", "target_task", "parent_event_id", "expected_registry_revision",
              "expected_registry_digest", "dedupe_key", "next_action", "allowed_paths",
              "test_commands", "test_artifacts"}
    if (not isinstance(profile, dict) or set(profile) != fields
            or type(profile["expected_registry_revision"]) is not int
            or not isinstance(profile["dedupe_key"], str) or not profile["dedupe_key"]
            or not isinstance(profile["next_action"], str) or not profile["next_action"]):
        raise Rejected("Malformed successor profile")
    check_artifacts(profile["test_artifacts"])
    with store.transaction() as (db, ledger):
        registry = get_config(db, "registry")
        proof = successor_preconditions(db, ledger, profile)
        old = prior["registry"]
        pm, target = profile["pm_task"], profile["target_task"]
        if (old["project"] != store.project or Path(old["store_root"]).resolve() != store.path.parent
                or old["pm_task"] != pm or set(credentials) != {"owner", pm, target}
                or credential_hash(credentials["owner"]) != get_config(db, "owner_hash")
                or old["owner_credential_hash"] != get_config(db, "owner_hash")):
            raise Rejected("Existing owner/project binding mismatch")
        entries = copy.deepcopy(registry["entries"])
        current = {e["task_id"]: e for e in entries}
        previous = {e["task_id"]: e for e in old["entries"]}
        for task in (pm, target):
            if (task not in current or task not in previous or current[task]["state"] != "active"
                    or current[task]["credential_hash"] != credential_hash(credentials[task])
                    or any(current[task][k] != previous[task][k] for k in
                           ("credential_hash", "generation", "role", "session_id", "worktree"))):
                raise Rejected("Principal credentials/identity drift")
        contexts = old["execution_contexts"]
        if (set(contexts) != {pm, target} or any(not Path(p).is_absolute() for p in contexts.values())
                or Path(contexts[target]).resolve() != Path(current[target]["worktree"]).resolve()):
            raise Rejected("Execution context drift")
        provenance = get_config(db, "event:" + profile["parent_event_id"])
        for label, task in (("source", pm), ("target", target)):
            if provenance[label] != dict(task_id=task, generation=current[task]["generation"]):
                raise Rejected("Parent principal generation changed")
        binding = copy.deepcopy(current[target]["bindings"][SCOPE])
        if current[pm]["bindings"][SCOPE] != binding:
            raise Rejected("Existing source/target bindings differ")
        roots = profile["allowed_paths"]
        if (not isinstance(roots, list) or not roots
                or any(not in_scope(safe_path(p), binding["source"]["allowed_paths"]) for p in roots)):
            raise Rejected("Successor cannot expand source scope")
        binding["source"].update(allowed_paths=roots, test_commands=profile["test_commands"],
                                 test_artifacts=profile["test_artifacts"])
        verifier.verify(binding, SCOPE)
        candidate = verifier.candidate(binding)
        for task in (pm, target):
            current[task]["bindings"][SCOPE] = copy.deepcopy(binding)
        reviewed = copy.deepcopy(old)
        reviewed.update(entries=entries, expected_revision=registry["revision"])
        event = dict(dedupe_key=profile["dedupe_key"], target=target, kind="APPROVAL",
                     priority=1, dependency=None, next_action=profile["next_action"])
        return dict(registry=reviewed, event=event, successor=dict(
            profile=copy.deepcopy(profile), prior=copy.deepcopy(prior),
            parent_proof=proof, initial_candidate=candidate))


def admit_successor(package, credentials, expected_digest, verifier=None):
    """One transaction for preconditions, authenticated Owner CAS and checkpoint."""
    if set(package) != {"registry", "event", "successor"} or digest(package) != expected_digest:
        raise Rejected("Successor package digest/schema changed")
    verifier = verifier or SourceVerifier()
    reviewed, metadata = package["registry"], package["successor"]
    store = Store(reviewed["store_root"], reviewed["project"])
    with store.transaction() as (db, ledger):
        bound = BoundSourceStore(store, db, ledger)
        rebuilt = build_successor(bound, metadata["prior"], metadata["profile"], credentials, verifier)
        if rebuilt != package:
            raise Rejected("Successor authority/candidate changed since review")
        revision = Owner(bound).replace(credentials["owner"], reviewed["expected_revision"],
                                        reviewed["entries"])["revision"]
        host = SourceHost(bound, principal_identity(reviewed["entries"], credentials), verifier)
        pm = next(e for e in reviewed["entries"] if e["task_id"] == reviewed["pm_task"])
        checkpoint = host.execute(credentials[pm["task_id"]], pm["generation"],
                                  revision, "checkpoint", {})
    return dict(registry_revision=revision, checkpoint=checkpoint)


def build_bounded_binding_update(store, prior, profile, credentials, verifier=None):
    """Build the sole approved ERP #1632 scope and baseline/test refresh."""
    fields = {"pm_task", "target_task", "expected_registry_revision",
              "expected_registry_digest", "expected_pm_generation",
              "expected_target_generation", "allowed_paths", "expected_base",
              "expected_base_tree", "dedupe_key", "next_action"}
    if not isinstance(profile, dict) or set(profile) != fields:
        raise Rejected("Malformed bounded binding update")
    if (profile["target_task"] != ERP1632_TARGET
            or profile["allowed_paths"] != ERP1632_PATHS):
        raise Rejected("Binding update must match the exact approved target and paths")
    if any(type(profile[k]) is not int or profile[k] < 1 for k in
           ("expected_registry_revision", "expected_pm_generation", "expected_target_generation")):
        raise Rejected("Binding update requires exact positive revision and generations")
    if not isinstance(profile["expected_registry_digest"], str) or len(profile["expected_registry_digest"]) != 64:
        raise Rejected("Binding update requires exact registry digest")
    if (not isinstance(profile["expected_base"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", profile["expected_base"])
            or not isinstance(profile["expected_base_tree"], str)
            or not re.fullmatch(r"[0-9a-f]{40}", profile["expected_base_tree"])):
        raise Rejected("Binding update requires a freshly verified main base/tree")
    if (not isinstance(profile["dedupe_key"], str) or not profile["dedupe_key"]
            or not isinstance(profile["next_action"], str) or not profile["next_action"]):
        raise Rejected("Binding update requires one exact event dedupe/action")
    with store.transaction() as (db, ledger):
        live = get_config(db, "registry")
        pm, target = profile["pm_task"], profile["target_task"]
        if (live["revision"] != profile["expected_registry_revision"]
                or digest(live) != profile["expected_registry_digest"]):
            raise Rejected("Binding update registry CAS moved")
        if (prior["registry"]["project"] != store.project
                or Path(prior["registry"]["store_root"]).resolve() != store.path.parent
                or prior["registry"]["pm_task"] != pm
                or prior["registry"]["entries"] != live["entries"]
                or set(credentials) != {"owner", pm, target}
                or credential_hash(credentials["owner"]) != get_config(db, "owner_hash")
                or prior["registry"]["owner_credential_hash"] != get_config(db, "owner_hash")):
            raise Rejected("Binding update owner/project/prior registry mismatch")
        if ledger._pm_authority(db)["task_id"] != pm:
            raise Rejected("Binding update requires the current PM principal")
        if db.execute("SELECT 1 FROM events WHERE dedupe_key=?", (profile["dedupe_key"],)).fetchone():
            raise Rejected("Binding update event dedupe already exists; reconcile only")
        current = {entry["task_id"]: entry for entry in live["entries"]}
        previous = {entry["task_id"]: entry for entry in prior["registry"]["entries"]}
        if pm not in current or target not in current:
            raise Rejected("Binding update principal is absent")
        for task, generation in ((pm, profile["expected_pm_generation"]),
                                 (target, profile["expected_target_generation"])):
            entry = current[task]
            if (entry["state"] != "active" or entry["generation"] != generation
                    or task not in previous
                    or any(entry[k] != previous[task][k] for k in
                           ("credential_hash", "generation", "role", "session_id", "worktree"))):
                raise Rejected("Binding update principal generation/identity changed")
            expected_secret = credential_hash(credentials[task])
            if entry["credential_hash"] != expected_secret:
                raise Rejected("Binding update PM/worker credentials do not match current registry")
        pm_entry, worker_entry = current[pm], current[target]
        old_binding = worker_entry["bindings"].get(SCOPE)
        current_paths = old_binding["source"].get("allowed_paths") if old_binding else None
        if (not old_binding or pm_entry["bindings"].get(SCOPE) != old_binding
                or current_paths not in ([".github/workflows/pr-quality-gate.yml"], ERP1632_PATHS)):
            raise Rejected("Binding update requires the exact prior or approved three-path binding")
        slot = db.execute("SELECT active_event FROM recipients WHERE task=?", (target,)).fetchone()
        if slot is not None and slot[0] is not None:
            raise Rejected("Binding update blocked by active worker slot")
        rows = db.execute("SELECT id,state,needs_inspection,delivery_token,worker_token,receipt,payload "
                          "FROM events WHERE target=?", (target,)).fetchall()
        for row in rows:
            payload = json.loads(row["payload"])
            if payload.get("scope") != SCOPE:
                continue
            if row["state"] in {"QUEUED", "SENT", "ACKED", "STARTED"}:
                raise Rejected("Binding update blocked by active source event")
            if row["state"] == "BLOCKED" and (row["needs_inspection"] or row["delivery_token"]
                    or row["worker_token"] or row["receipt"]):
                stopped = db.execute("SELECT detail FROM history WHERE event_id=? AND actor=? "
                    "AND action='WORKER_CONFIRMED_STOPPED'", (row["id"], pm)).fetchall()
                try:
                    attestation = get_config(db, "attest:release_stopped_worker:" + row["id"])
                except Rejected:
                    attestation = None
                if (attestation is None or not any(
                        json.loads(item["detail"]).get("evidence") == attestation.get("evidence")
                        for item in stopped)):
                    raise Rejected("Ambiguous blocked delivery lacks PM stop attestation")
        entries = copy.deepcopy(live["entries"])
        repo_root = Path(old_binding["worktree"]).resolve(strict=True)
        smoke_paths = ["backend/tests/test_auth.py", "backend/tests/test_auth_branch_context.py",
                       "backend/tests/modules/kds/test_kds_ingest_http.py"]
        artifacts = []
        for relative in smoke_paths:
            artifact = repo_root / relative
            if (not artifact.is_file() or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)()
                                               for p in (artifact, *artifact.parents))):
                raise Rejected("Approved synthetic smoke artifact is unavailable or linked")
            artifacts.append(dict(path=str(artifact), sha256=hashlib.sha256(artifact.read_bytes()).hexdigest()))
        python = old_binding["source"]["test_commands"][0][0]
        if not Path(python).is_absolute() or not Path(python).is_file():
            raise Rejected("Binding update requires the already-bound Python executable")
        smoke_runner = ("import os,sys; os.chdir('backend'); os.environ['PYTHONPATH']='.'; "
            "import pytest; raise SystemExit(pytest.main(['-q','tests/test_auth.py',"
            "'tests/test_auth_branch_context.py','tests/modules/kds/test_kds_ingest_http.py']))")
        test_commands = [[python, "-m", "unittest", "scripts.tests.test_backend_impact", "-v"],
                         [python, "-c", smoke_runner]]
        for entry in entries:
            if entry["task_id"] in {pm, target}:
                binding = entry["bindings"][SCOPE]
                binding["source"]["allowed_paths"] = copy.deepcopy(ERP1632_PATHS)
                binding["source"]["base"] = profile["expected_base"]
                binding["source"]["base_tree"] = profile["expected_base_tree"]
                binding["source"]["test_commands"] = copy.deepcopy(test_commands)
                binding["source"]["test_artifacts"] = copy.deepcopy(artifacts)
        updated_target = next(e for e in entries if e["task_id"] == target)
        (verifier or SourceVerifier()).verify(updated_target["bindings"][SCOPE], SCOPE)
        reviewed = copy.deepcopy(prior["registry"])
        reviewed.update(entries=entries, expected_revision=live["revision"])
        return dict(prior_registry=copy.deepcopy(prior["registry"]), registry=reviewed,
                    profile=copy.deepcopy(profile),
                    event=dict(dedupe_key=profile["dedupe_key"], target=target,
                               kind="APPROVAL", priority=1, dependency=None,
                               next_action=profile["next_action"]),
                    authority="pilot operator confirmation authority")


def admit_bounded_binding_update(package, credentials, expected_digest, verifier=None):
    """Apply the reviewed binding-only delta using the existing Owner CAS."""
    if (not isinstance(package, dict) or set(package) !=
            {"prior_registry", "registry", "profile", "event", "authority"}
            or package["authority"] != "pilot operator confirmation authority"
            or digest(package) != expected_digest):
        raise Rejected("Binding update package is not exactly operator-reviewed")
    reviewed, profile = package["registry"], package["profile"]
    store = Store(reviewed["store_root"], reviewed["project"])
    with store.transaction() as (db, ledger):
        bound = BoundSourceStore(store, db, ledger)
        prior = dict(registry=package["prior_registry"])
        rebuilt = build_bounded_binding_update(bound, prior, profile, credentials, verifier)
        if rebuilt != package:
            raise Rejected("Binding update changed after operator review")
        revision = Owner(bound).replace(credentials["owner"],
            profile["expected_registry_revision"], reviewed["entries"])["revision"]
    return dict(registry_revision=revision, registry_digest=digest(
        dict(revision=revision, entries=reviewed["entries"])),
        target=profile["target_task"], generation=profile["expected_target_generation"],
        allowed_paths=copy.deepcopy(ERP1632_PATHS), authority=package["authority"])

def build_recovery_authority(store, proposal, credentials, event_id, receipt,
                             prior_root, receipt_sha256, verifier, *, reuse_existing_grant=False):
    """Reconstruct the sole allowed grant delta from the current admitted registry."""
    with store.transaction() as (db, ledger):
        registry = get_config(db, "registry")
        old = proposal["registry"]
        pm_task, target = old["pm_task"], proposal["event"]["target"]
        if (registry["entries"] != old["entries"]
                or registry["revision"] != old["expected_revision"] + 1
                or Path(old["store_root"]).resolve() != store.path.parent
                or old["project"] != store.project
                or set(credentials) != {"owner", pm_task, target}
                or credential_hash(credentials["owner"]) != get_config(db, "owner_hash")
                or old["owner_credential_hash"] != get_config(db, "owner_hash")
                or ledger._pm_authority(db)["task_id"] != pm_task):
            raise Rejected("Recovery prior registry/owner binding changed")
        by_task = {e["task_id"]: e for e in registry["entries"]}
        for task in (pm_task, target):
            if (by_task[task]["state"] != "active"
                    or by_task[task]["credential_hash"] != credential_hash(credentials[task])):
                raise Rejected("Recovery principal credential/state mismatch")
        binding = by_task[target]["bindings"][SCOPE]
        if by_task[pm_task]["bindings"][SCOPE] != binding or by_task[pm_task]["role"] != "PM":
            raise Rejected("Recovery PM binding mismatch")
        event = ledger._get(db, event_id)
        payload = json.loads(event["payload"])
        if (payload["scope"] != SCOPE or payload["source_task"] != pm_task
                or event["dedupe_key"] != proposal["event"]["dedupe_key"] or event["target"] != target):
            raise Rejected("Recovery event binding mismatch")
        require_proven_no_send(db, store, event, pm_task, by_task[pm_task]["generation"], receipt)
        provenance = get_config(db, "event:" + event_id)
        if any(provenance[label] != dict(task_id=task, generation=by_task[task]["generation"])
               for label, task in (("source", pm_task), ("target", target))):
            raise Rejected("Recovery event generation changed")
        fresh = verifier.verify(binding, SCOPE)
        cp = db.execute("SELECT * FROM checkpoints WHERE issue=? AND scope=?",
                        (fresh["issue"], SCOPE)).fetchone()
        if (any(payload[k] != fresh[k] for k in ("issue", "scope", "base", "head", "checkpoint"))
                or not cp or any(cp[k] != fresh[k] for k in ("base", "head", "checkpoint"))):
            raise Rejected("Recovery checkpoint drift")
        entries = copy.deepcopy(registry["entries"])
        pm = next(e for e in entries if e["task_id"] == pm_task)
        grant = dict(command="inspect_retry", scope=SCOPE, states=["QUEUED"])
        existing = [g for g in pm["grants"] if g["command"] == "inspect_retry"]
        if reuse_existing_grant:
            if existing != [grant] or pm["authority"].count("inspect_retry") != 1:
                raise Rejected("Reuse requires exactly the already-admitted narrow PM grant")
        else:
            if "inspect_retry" in pm["authority"] or existing:
                raise Rejected("Recovery grant already exists; no repeated admission")
            pm["grants"].append(grant)
            pm["authority"] = sorted([*pm["authority"], "inspect_retry"])
        admitted_revision = registry["revision"] + (0 if reuse_existing_grant else 1)
        reviewed = copy.deepcopy(old)
        reviewed.update(entries=entries, expected_revision=registry["revision"])
        return dict(registry=reviewed, event=copy.deepcopy(proposal["event"]),
                    recovery=dict(expected_revision=registry["revision"], expected_digest=digest(registry),
                                  authority_mode="reuse" if reuse_existing_grant else "add",
                                  admitted_revision=admitted_revision,
                                  admitted_digest=digest(dict(revision=admitted_revision, entries=entries)),
                                  event_id=event_id, event_digest=event["digest"], claim_digest=digest(dict(event)),
                                  prior_root=str(prior_root), prior_proposal_digest=digest(proposal),
                                  receipt_sha256=receipt_sha256, initial_candidate=verifier.candidate(binding)))


def require_proven_no_send(db, store, event, pm_task, generation, receipt):
    """Accept only the ledger's explicit pre-send failure path, never an expired claim."""
    if (set(receipt) != {"event_id", "delivery_token"} or receipt["event_id"] != event["id"]
            or not isinstance(receipt["delivery_token"], str) or not receipt["delivery_token"]
            or event["state"] != "QUEUED" or event["attempts"] != 1 or not event["needs_inspection"]
            or event["delivery_token"] is not None or event["delivery_until"] is not None
            or event["receipt"] is not None or event["delivery_owner"] != f"{pm_task}@{generation}"):
        raise Rejected("Require a supported recorded no-send failure; ambiguous attempts are reconcile-only")
    rows = db.execute("SELECT actor,action,detail FROM history WHERE event_id=? ORDER BY seq",
                      (event["id"],)).fetchall()
    actions = [row["action"] for row in rows]
    owner = f"{pm_task}@{generation}"
    if actions != ["QUEUED", "CLAIMED", "DELIVERY_FAILURE", "DELIVERY_FAILED"]:
        raise Rejected("Prior delivery/recovery history is ambiguous; reconcile only")
    failure = json.loads(rows[2]["detail"])
    retry = json.loads(rows[3]["detail"])
    if (rows[1]["actor"] != owner or rows[2]["actor"] != owner or rows[3]["actor"] != "ledger"
            or failure != {"evidence": no_send_failure_evidence(event, receipt["delivery_token"])}
            or retry.get("state") != "QUEUED" or retry.get("needs_inspection") != 1
            or retry.get("reason") != "DELIVERY_FAILED"):
        raise Rejected("No-send recovery is not bound to a supported PM delivery-failure record")


def admit_recovery_authority(package, credentials, expected_digest, prior, receipt, verifier):
    if set(package) != {"registry", "event", "recovery"} or digest(package) != expected_digest:
        raise Rejected("Recovery package digest/schema changed")
    r = package["recovery"]; store = Store(package["registry"]["store_root"], package["registry"]["project"])
    with store.transaction() as (db, ledger):
        live = get_config(db, "registry")
        if live["revision"] != r["expected_revision"] or digest(live) != r["expected_digest"]:
            raise Rejected("Recovery registry CAS moved")
        bound = BoundSourceStore(store, db, ledger)
        rebuilt = build_recovery_authority(bound, prior, credentials, r["event_id"], receipt,
                                            r["prior_root"], r["receipt_sha256"], verifier,
                                            reuse_existing_grant=r["authority_mode"] == "reuse")
        if rebuilt != package:
            raise Rejected("Recovery package differs from exact one-grant delta or candidate")
        revision = live["revision"]
        if r["authority_mode"] == "add":
            revision = Owner(bound).replace(credentials["owner"], live["revision"], package["registry"]["entries"])["revision"]
    return dict(registry_revision=revision, event_id=r["event_id"], recovery="AUTHORITY_ONLY",
                authority_mode=r["authority_mode"], registry_mutated=r["authority_mode"] == "add")


class SourceVerifier:
    def __init__(self, github=None): self.github=github or GitHubVerifier()

    def candidate(self, binding):
        b=binding
        fields={"repository","worktree","branch","rule_version","config_version","source"}
        contract={"issue","issue_body_sha256","base","base_tree","target_thread","allowed_paths",
                  "evidence_root","head_semantics","permissions","test_commands","allowed_branches"}
        if (not isinstance(b,dict) or set(b)!=fields or b["rule_version"]!=VERSION
                or b["config_version"]!=VERSION or not isinstance(b["source"],dict)
                or set(b["source"]) not in (contract, contract | {"test_artifacts"})):
            raise Rejected("Incomplete source contract")
        s=b["source"]
        if "test_artifacts" in s:
            check_artifacts(s["test_artifacts"])
        if (s["head_semantics"]!="APPROVED_BASELINE_NOT_CANDIDATE"
                or s["permissions"]!=["local_source","local_tests","pr_preparation"]
                or not isinstance(s["allowed_paths"],list) or not s["allowed_paths"]):
            raise Rejected("Invalid source-only authorization")
        roots=[safe_path(p) for p in s["allowed_paths"]]
        if (not isinstance(s["allowed_branches"],list) or not s["allowed_branches"]
                or b["branch"] not in s["allowed_branches"]
                or any(not isinstance(x,str) or not x for x in s["allowed_branches"])):
            raise Rejected("Require exact owner-reviewed candidate branches")
        if any(p==".git" or p.startswith(".git/") for p in roots): raise Rejected("Git metadata cannot be source scope")
        cwd=Path(b["worktree"]).resolve(strict=True)
        if (not Path(s["evidence_root"]).is_absolute()
                or Path(s["evidence_root"]).resolve().is_relative_to(cwd)
                or not isinstance(s["test_commands"],list) or not s["test_commands"]
                or any(not isinstance(c,list) or not c or any(not isinstance(a,str) or not a for a in c)
                       for c in s["test_commands"])):
            raise Rejected("Require external evidence root and owner-fixed test commands")
        def git(*args): return self.github._run([self.github.git,"-C",str(cwd),*args],cwd)
        def api(endpoint): return json.loads(self.github._run([self.github.gh,"api","--hostname","github.com",endpoint],cwd))
        try:
            import uuid,re
            if (type(s["issue"]) is not int or s["issue"]<1
                    or str(uuid.UUID(s["target_thread"]))!=s["target_thread"]
                    or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+",b["repository"])
                    or any(not re.fullmatch(r"[0-9a-f]{40}",s[k]) for k in ("base","base_tree"))
                    or not re.fullmatch(r"[0-9a-f]{64}",s["issue_body_sha256"])):
                raise Rejected("Invalid source identity")
            if Path(git("rev-parse","--show-toplevel").decode().strip()).resolve()!=cwd:
                raise Rejected("Source worktree mismatch")
            branch=git("branch","--show-current").decode().strip() or "DETACHED"
            if branch not in s["allowed_branches"]: raise Rejected("Source branch differs from owner binding")
            repo=b["repository"]
            if git("remote","get-url","--all","origin").decode().strip() not in {
                    f"https://github.com/{repo}.git",f"https://github.com/{repo}",f"git@github.com:{repo}.git"}:
                raise Rejected("Source repository mismatch")
            issue=api(f"repos/{repo}/issues/{s['issue']}")
            if (issue["number"]!=s["issue"] or issue["state"]!="open"
                    or hashlib.sha256((issue["body"] or "").encode()).hexdigest()!=s["issue_body_sha256"]):
                raise Rejected("Reviewed source plan drift")
            remote=api(f"repos/{repo}/commits/main")
            if remote["sha"]!=s["base"] or remote["commit"]["tree"]["sha"]!=s["base_tree"]:
                raise Rejected("Reviewed source base drift")
            head=git("rev-parse","HEAD").decode().strip()
            tree=git("rev-parse","HEAD^{tree}").decode().strip()
            if git("merge-base",s["base"],head).decode().strip()!=s["base"]:
                raise Rejected("Source candidate is not descended from approved base")
            def paths(*args): return {p for p in git(*args).decode().split("\0") if p}
            changed=paths("diff","--no-ext-diff","--no-textconv","--no-renames","--name-only","-z",s["base"],"HEAD","--")
            changed|=paths("diff","--no-ext-diff","--no-textconv","--no-renames","--name-only","-z","HEAD","--")
            changed|=paths("diff","--cached","--no-ext-diff","--no-textconv","--no-renames","--name-only","-z","--")
            changed|=paths("ls-files","--others","--exclude-standard","-z")
            inventory=[]
            for name in sorted(changed):
                if not in_scope(name,roots): raise Rejected("Candidate path outside reviewed source scope")
                path=cwd/name
                if (any(p.lower() in {".git","secrets","runtime","node_modules",".venv"} or p.lower().startswith(".env") for p in Path(name).parts)
                        or path.suffix.lower() in {".db",".sqlite",".pem",".key"}):
                    raise Rejected("Secret/runtime artifact cannot be source scope")
                if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path,*path.parents)):
                    raise Rejected("Linked candidate path refused")
                if path.exists() and not path.is_file(): raise Rejected("Candidate path is not a regular file")
                inventory.append(dict(path=name,sha256=hashlib.sha256(path.read_bytes()).hexdigest() if path.exists() else None))
            # Bind index content too; a staged version must not be hidden by a
            # different working copy of the same file at report time.
            index=git("diff","--cached","--no-ext-diff","--no-textconv","--binary",s["base"],"--")
            return dict(head=head,tree=tree,branch=branch,files=inventory,
                        index_sha256=hashlib.sha256(index).hexdigest())
        except Rejected: raise
        except (KeyError,TypeError,ValueError,OSError) as exc:
            raise Rejected("Source evidence unavailable or malformed") from exc

    def verify(self,binding,scope):
        if scope!=SCOPE: raise Rejected("Source scope mismatch")
        first=self.candidate(binding)
        if self.candidate(binding)!=first: raise Rejected("Candidate moved during source verification")
        s=binding["source"]
        return dict(issue=str(s["issue"]),scope=SCOPE,base=s["base"],head=s["base"],
                    checkpoint=digest(binding),evidence=f"https://github.com/{binding['repository']}/issues/{s['issue']}")

    def validate_source_completion(self,binding,event,evidence):
        root=Path(binding["source"]["evidence_root"]).absolute()
        prefix="artifact://sha256/"
        if not isinstance(evidence,str) or not evidence.startswith(prefix): raise Rejected("Require immutable source report")
        import re
        content_hash=evidence[len(prefix):]
        if not re.fullmatch(r"[0-9a-f]{64}",content_hash): raise Rejected("Invalid report digest")
        path=root/(content_hash+".json")
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (path,*path.parents)): raise Rejected("Linked source evidence refused")
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=content_hash: raise Rejected("Source report changed")
        report=json.loads(raw)
        required={"event_id","task_id","contract_digest","candidate","test_evidence","result"}
        if (set(report)!=required or report["event_id"]!=event["id"]
                or report["task_id"]!=event["target"] or report["task_id"]!=binding["source"]["target_thread"]
                or report["contract_digest"]!=digest(binding)
                or report["candidate"]!=self.candidate(binding)
                or report["result"]!="SOURCE_READY_FOR_REVIEW"
                or not isinstance(report["test_evidence"],list) or not report["test_evidence"]):
            raise Rejected("Source completion report binding mismatch")
        verified_commands=set()
        for ref in report["test_evidence"]:
            if not isinstance(ref,str) or not re.fullmatch(r"artifact://sha256/[0-9a-f]{64}",ref):
                raise Rejected("Test evidence must resolve to a local immutable artifact")
            test_path=root/(ref[len(prefix):]+".json")
            if test_path.is_symlink() or getattr(test_path, "is_junction", lambda: False)(): raise Rejected("Linked test evidence refused")
            test_raw=test_path.read_bytes(); test=json.loads(test_raw)
            if (hashlib.sha256(test_raw).hexdigest()!=ref[len(prefix):]
                    or set(test)!={"candidate_digest","command","exit_code","log_sha256"}
                    or test["candidate_digest"]!=digest(report["candidate"])
                    or test["command"] not in binding["source"]["test_commands"]
                    or type(test["exit_code"]) is not int or test["exit_code"]!=0
                    or not re.fullmatch(r"[0-9a-f]{64}",test["log_sha256"])):
                raise Rejected("Test evidence is failed, stale or unreviewed")
            log=root/(test["log_sha256"]+".log")
            if log.is_symlink() or getattr(log, "is_junction", lambda: False)() or hashlib.sha256(log.read_bytes()).hexdigest()!=test["log_sha256"]:
                raise Rejected("Test output artifact is missing or changed")
            verified_commands.add(canonical(test["command"]))
        if verified_commands!={canonical(command) for command in binding["source"]["test_commands"]}:
            raise Rejected("Required source test evidence is incomplete")


def source_proposal(binding,pm_task,credentials,store_root,execution_contexts):
    """Exact source-stage registry payload; activation remains operator-only."""
    s=binding["source"]
    prep=dict(repository=binding["repository"],worktree=binding["worktree"],branch=binding["branch"],
              rule_version=VERSION,config_version=VERSION,
              preparation=dict(target_thread=s["target_thread"],issue=s["issue"]))
    result=preparation_proposal(prep,pm_task,credentials,store_root,execution_contexts)
    for entry in result["entries"]:
        grants=({"checkpoint":["ABSENT"],"enqueue":["ABSENT"],"claim":["QUEUED"],"sent":["QUEUED"],
                 "delivery_failed":["QUEUED"],
                 "get":["QUEUED","SENT","ACKED","STARTED","COMPLETED"]} if entry["role"]=="PM" else
                {"get":["QUEUED","SENT","ACKED","STARTED","COMPLETED"],"reconcile":["SENT","ACKED","STARTED"],
                 "ack":["SENT"],"start":["ACKED"],"renew":["STARTED"],"complete":["STARTED"]})
        entry.update(bindings={SCOPE:copy.deepcopy(binding)},scopes=[SCOPE],authority=sorted(grants),
                     grants=[dict(command=c,scope=SCOPE,states=states) for c,states in grants.items()],
                     rule_version=VERSION,config_version=VERSION,
                     expected_output="Exact candidate source and test evidence ready for independent review",
                     stop_condition="Stop on source policy/identity drift, lease expiry, or unauthorized operation")
        entry["inventory"]["unfinished_work"]=[]
        body={k:entry["inventory"][k] for k in ("unfinished_work","prs","issues","blockers")}
        entry["inventory"]["readback_digest"]=digest(body)
    result.update(stage=SCOPE,source_edit_authorized=True,transport_authorized=False,
                  completion_semantics="SOURCE_READY_FOR_REVIEW_NOT_REVIEW_MERGE_DEPLOY_ACCEPTANCE")
    return result


def activate_source(reviewed,credentials,expected_digest,verifier=None):
    """Exact-reviewed NEW Store bootstrap; never silently modify an existing one."""
    from .store import Store,Owner,validate_entries
    if digest(reviewed)!=expected_digest: raise Rejected("Source activation payload changed")
    binding=reviewed["entries"][0]["bindings"][SCOPE]
    if reviewed!=source_proposal(binding,reviewed["pm_task"],credentials,reviewed["store_root"],reviewed["execution_contexts"]):
        raise Rejected("Source proposal differs from narrow canonical grants")
    (verifier or SourceVerifier()).verify(binding,SCOPE)
    root=Path(reviewed["store_root"])
    if root.exists() or any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (root,*root.parents)):
        raise Rejected("Source bootstrap requires a new unlinked Store root")
    validate_entries(reviewed["entries"],[],reviewed["owner_credential_hash"])
    store=Store.initialize(root,reviewed["project"],reviewed["pm_task"],credentials["owner"])
    revision=Owner(store).replace(credentials["owner"],0,reviewed["entries"])["revision"]
    return store,revision


class SourceHost:
    def __init__(self,store,identity,verifier=None):
        self.verifier=verifier or SourceVerifier()
        self.adapter=Adapter(store,self.verifier,host_identity=identity)

    def execute(self,credential,generation,revision,command,arguments):
        return self.adapter.execute(credential,generation,revision,SCOPE,command,arguments)

    def completion_report(self,binding,event_id,test_evidence):
        report=dict(event_id=event_id,task_id=binding["source"]["target_thread"],contract_digest=digest(binding),
                    candidate=self.verifier.candidate(binding),test_evidence=test_evidence,result="SOURCE_READY_FOR_REVIEW")
        raw=canonical(report).encode(); h=hashlib.sha256(raw).hexdigest()
        root=Path(binding["source"]["evidence_root"]); root.mkdir(parents=True,exist_ok=True)
        path=root/(h+".json")
        if path.exists():
            if path.read_bytes()!=raw: raise Rejected("Immutable source report conflict")
        else:
            with path.open("xb") as stream: stream.write(raw)
        return "artifact://sha256/"+h

    def run_test(self,binding,index):
        """Run only an owner-reviewed local argv; bind real output to candidate."""
        if type(index) is not int or index<0 or index>=len(binding["source"]["test_commands"]):
            raise Rejected("Unknown reviewed test command")
        before=self.verifier.candidate(binding)
        command=binding["source"]["test_commands"][index]
        run=subprocess.run(command,cwd=binding["worktree"],capture_output=True,timeout=120,shell=False)
        if self.verifier.candidate(binding)!=before: raise Rejected("Candidate changed while tests ran")
        root=Path(binding["source"]["evidence_root"])
        if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (root,*root.parents)): raise Rejected("Linked evidence root refused")
        root.mkdir(parents=True,exist_ok=True)
        log=run.stdout+b"\nSTDERR\n"+run.stderr; log_hash=hashlib.sha256(log).hexdigest()
        record=dict(candidate_digest=digest(before),command=command,exit_code=run.returncode,log_sha256=log_hash)
        raw=canonical(record).encode(); h=hashlib.sha256(raw).hexdigest()
        for path,data in ((root/(log_hash+".log"),log),(root/(h+".json"),raw)):
            if path.exists():
                if path.read_bytes()!=data: raise Rejected("Immutable test artifact conflict")
            else:
                with path.open("xb") as stream: stream.write(data)
        return dict(evidence="artifact://sha256/"+h,exit_code=run.returncode,candidate_digest=digest(before))
