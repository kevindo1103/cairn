"""Owner-reviewed PREPARATION binding over the existing registry and Adapter.

No transport, source editing, event enqueue, lease, release or production API.
The operator supplies identity evidence; bearer mapping is not OS isolation.
"""
import copy
import json
import uuid
from pathlib import Path

from .adapter import Adapter
from .store import Owner, Store, Rejected, credential_hash, digest, get_config
from .verifier import GitHubVerifier

SCOPE = "PREPARATION"
VERSION = "preparation-1"


class PreparationVerifier:
    """Map freshly checked PR-absent preparation into a normal checkpoint."""
    def __init__(self, github=None):
        self.github = github if github is not None else GitHubVerifier()

    def verify(self, binding, scope):
        required = {"repository", "worktree", "branch", "rule_version", "config_version",
                    "base_ref", "preparation"}
        if (not isinstance(binding, dict) or set(binding) != required or scope != SCOPE
                or binding["rule_version"] != VERSION or binding["config_version"] != VERSION
                or binding["base_ref"] != "main"):
            raise Rejected("Only reviewed PREPARATION bindings are supported")
        p = binding["preparation"]
        if (not isinstance(p, dict) or p.get("repository") != binding["repository"]
                or p.get("worktree") != binding["worktree"]):
            raise Rejected("Preparation source binding differs from registry")
        # Recheck both ends of the observation to reject movement during reads.
        for _ in range(2):
            self.github.verify_preparation(p)
            cwd = Path(p["worktree"]).resolve(strict=True)
            def git(*args):
                return self.github._run([self.github.git, "-C", str(cwd), *args], cwd).decode().strip()
            if Path(git("rev-parse", "--show-toplevel")).resolve() != cwd:
                raise Rejected("Preparation worktree root mismatch")
            if git("status", "--porcelain=v1", "--untracked-files=all"):
                raise Rejected("Preparation requires clean source inventory")
            branch = git("branch", "--show-current") or "DETACHED"
            if branch != binding["branch"]:
                raise Rejected("Preparation branch drift")
            repo = binding["repository"]
            if git("remote", "get-url", "--all", "origin") not in {
                    f"https://github.com/{repo}.git", f"https://github.com/{repo}",
                    f"git@github.com:{repo}.git"}:
                raise Rejected("Preparation repository mismatch")
            try:
                remote = json.loads(self.github._run([self.github.gh, "api", "--hostname", "github.com",
                    f"repos/{repo}/commits/main"], cwd))
                if remote["sha"] != p["head"] or remote["commit"]["tree"]["sha"] != p["tree"]:
                    raise Rejected("Preparation main identity drift")
            except (KeyError, TypeError, ValueError) as exc:
                raise Rejected("Preparation main evidence unavailable") from exc
        return {"issue": str(p["issue"]), "scope": SCOPE, "base": p["head"], "head": p["head"],
                "checkpoint": digest(binding),
                "evidence": f"https://github.com/{binding['repository']}/issues/{p['issue']}"}


def proposal(binding, pm_task, credentials, store_root, execution_contexts):
    """Build the exact owner CAS payload; do not initialize or mutate a Store."""
    target = binding["preparation"]["target_thread"]
    if pm_task == target or any(str(uuid.UUID(t)) != t for t in (pm_task, target)):
        raise Rejected("Require distinct canonical PM and target task IDs")
    if set(credentials) != {"owner", pm_task, target}:
        raise Rejected("Require separate owner, PM and target credentials")
    hashes = {name: credential_hash(token) for name, token in credentials.items()}
    if len(set(hashes.values())) != 3:
        raise Rejected("Owner and principals require distinct credentials")
    if (set(execution_contexts) != {pm_task, target}
            or any(not isinstance(cwd, str) or not Path(cwd).is_absolute()
                   for cwd in execution_contexts.values())
            or Path(execution_contexts[target]).resolve() != Path(binding["worktree"]).resolve()):
        raise Rejected("Require principal execution contexts and exact target resource mapping")
    entries = []
    for task, role in ((pm_task, "PM"), (target, "Infra")):
        commands = ["checkpoint", "snapshot_prep"] if role == "PM" else ["snapshot_prep"]
        inventory = {"unfinished_work": [f"issue:{binding['preparation']['issue']}:PREPARATION"],
                     "prs": [], "issues": [], "blockers": []}
        entries.append(dict(task_id=task, credential_hash=hashes[task], generation=1,
            state="active", role=role, bindings={SCOPE: copy.deepcopy(binding)},
            grants=[dict(command=c, scope=SCOPE, states=["ABSENT"]) for c in commands],
            successor=None, quiescence=None, project=binding["repository"], session_id=task,
            scopes=[SCOPE], authority=sorted(commands), worktree=binding["worktree"],
            branch=binding["branch"], rule_version=VERSION, config_version=VERSION,
            parent=None if role == "PM" else pm_task, owner=pm_task,
            expected_output="Read-only source inventory and preparation report; no source authorization",
            stop_condition="Stop on binding, registry, identity or source drift",
            inventory=dict(inventory, complete=True, readback_digest=digest(inventory))))
    return dict(store_root=str(Path(store_root).absolute()), project=binding["repository"],
        pm_task=pm_task, expected_revision=0, entries=entries, owner_credential_hash=hashes["owner"],
        identity_mode="OPERATOR_ATTESTED_TASK_MAPPING", isolation="NOT_PROVEN",
        execution_contexts=copy.deepcopy(execution_contexts),
        registry_worktree_semantics="AUTHORIZED_RESOURCE_WORKTREE_NOT_PRINCIPAL_EXECUTION_CWD",
        stage=SCOPE, source_edit_authorized=False, transport_authorized=False)


def activate(reviewed, credentials, expected_digest, verifier=None):
    """Operator-only NEW TEST Store bootstrap after exact-payload review.

    Never called by a worker or implicitly by report/read operations.
    """
    if digest(reviewed) != expected_digest:
        raise Rejected("Reviewed activation payload changed")
    verifier = verifier if verifier is not None else PreparationVerifier()
    entries = reviewed["entries"]
    if len(entries) != 2:
        raise Rejected("Preparation bootstrap requires exactly PM and target")
    binding = entries[0]["bindings"][SCOPE]
    rebuilt = proposal(binding, reviewed["pm_task"], credentials, reviewed["store_root"],
                       reviewed["execution_contexts"])
    if reviewed != rebuilt:
        raise Rejected("Activation differs from narrow canonical proposal")
    verifier.verify(binding, SCOPE)
    root = Path(reviewed["store_root"])
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (root, *root.parents)):
        raise Rejected("Linked preparation Store root refused")
    if root.exists():
        raise Rejected("Preparation bootstrap refuses existing Store root")
    from .store import validate_entries
    validate_entries(entries, [], reviewed["owner_credential_hash"])
    store = Store.initialize(root, reviewed["project"], reviewed["pm_task"], credentials["owner"])
    revision = Owner(store).replace(credentials["owner"], reviewed["expected_revision"], entries)["revision"]
    return store, revision


class PreparationHost:
    """Narrow operator-host facade; all principal actions use existing ACLs."""
    def __init__(self, store, identity, verifier=None):
        self.store = store
        self.adapter = Adapter(store, verifier or PreparationVerifier(), host_identity=identity)

    def checkpoint(self, credential, generation, revision):
        return self.adapter.execute(credential, generation, revision, SCOPE, "checkpoint", {})

    def report(self, credential, generation, revision):
        # Empty candidate projection cannot manufacture a trusted new principal.
        result = self.adapter.execute(credential, generation, revision, SCOPE,
                                      "snapshot_prep", {"candidates": []})
        with self.store.transaction() as (db, ledger):
            registry = get_config(db, "registry")
            if registry["revision"] != revision:
                raise Rejected("Registry moved during preparation report")
            result.update(registry_revision=revision, stage=SCOPE,
                          source_edit_authorized=False, transport_authorized=False,
                          principal_enforcement="NOT_PROVEN", isolation="NOT_PROVEN",
                          inventory=[{key: entry[key] for key in
                              ("task_id", "role", "generation", "state", "worktree", "branch", "scopes", "authority")}
                              for entry in registry["entries"]],
                          source_binding=registry["entries"][0]["bindings"][SCOPE]["preparation"])
        return result
