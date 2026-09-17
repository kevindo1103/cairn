"""Fresh, fail-closed local Git plus GitHub checks, no checkpoint input from workers."""

import hashlib
import json
import os
import re
import subprocess
import uuid
from pathlib import Path

from .store import Rejected, digest


def safe_path(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value) or value.startswith("/")
            or any(p in {"", ".", ".."} for p in value.split("/"))):
        raise Rejected("Ambiguous repository path")
    return value


def in_scope(path, roots):
    safe_path(path)
    return any(path == root or path.startswith(root + "/") for root in roots)


class GitHubVerifier:
    def __init__(self, *, git="git", gh="gh", timeout=15):
        self.git, self.gh, self.timeout = git, gh, timeout

    def _run(self, argv, cwd):
        env = dict(os.environ)
        for key in list(env):
            if key.startswith("GIT_"):
                env.pop(key)
        env["GIT_NO_REPLACE_OBJECTS"] = "1"
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            result = subprocess.run(argv, cwd=cwd, env=env, capture_output=True,
                                    timeout=self.timeout, check=True)
            return result.stdout
        except (OSError, subprocess.SubprocessError) as exc:
            # Do not copy tool output, environment, credentials or HTTP headers to logs.
            raise Rejected("Fresh Git/GitHub verification unavailable") from exc

    def verify_references(self, prs, issues):
        """Freshly check full inventory decision references, supplied by the host registry."""
        try:
            for kind, references in (("pulls", prs), ("issues", issues)):
                for ref in references:
                    required = {"repository", "number", "state", "body_sha256"} | ({"head"} if kind == "pulls" else set())
                    if set(ref) != required or not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", ref["repository"]):
                        raise Rejected("Incomplete handoff decision reference")
                    if type(ref["number"]) is not int or ref["number"] < 1:
                        raise Rejected("Invalid handoff decision identity")
                    endpoint = f"repos/{ref['repository']}/{kind}/{ref['number']}"
                    response = json.loads(self._run([self.gh, "api", "--hostname", "github.com", endpoint], None))
                    if (response["number"] != ref["number"] or response["state"] != ref["state"]
                            or hashlib.sha256((response["body"] or "").encode()).hexdigest() != ref["body_sha256"]
                            or (kind == "pulls" and response["head"]["sha"] != ref["head"])):
                        raise Rejected("Handoff PR/issue decision drift")
        except Rejected:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise Rejected("Handoff decision evidence missing or ambiguous") from exc

    def verify(self, binding, scope):
        try:
            return self._verify(binding, scope)
        except Rejected:
            raise
        except (KeyError, TypeError, ValueError, OSError) as exc:
            raise Rejected("Missing or ambiguous Git/GitHub evidence") from exc

    def verify_preparation(self, binding):
        """Verify a PR-absent source-preparation record without granting PR authority."""
        fields = {"repository", "issue", "issue_state", "issue_body_sha256", "worktree",
                  "head", "tree", "target_thread", "target_worktree", "scope"}
        if not isinstance(binding, dict) or set(binding) != fields:
            raise Rejected("Incomplete pre-PR preparation binding")
        if binding["scope"] != "PREPARATION" or binding["issue_state"] != "open":
            raise Rejected("Preparation scope is not allowed")
        if type(binding["issue"]) is not int or binding["issue"] < 1:
            raise Rejected("Invalid preparation issue")
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", binding["repository"]):
            raise Rejected("Invalid preparation repository")
        if any(not isinstance(binding[k], str) or not binding[k] for k in
               ("worktree", "head", "tree", "target_thread", "target_worktree", "issue_body_sha256")):
            raise Rejected("Invalid preparation binding identity")
        if not re.fullmatch(r"[0-9a-f]{40}", binding["head"]) or not re.fullmatch(r"[0-9a-f]{40}", binding["tree"]):
            raise Rejected("Invalid preparation git identity")
        if not re.fullmatch(r"[0-9a-f]{64}", binding["issue_body_sha256"]):
            raise Rejected("Invalid preparation issue digest")
        try:
            cwd = Path(binding["worktree"]).resolve(strict=True)
            if (str(uuid.UUID(binding["target_thread"])) != binding["target_thread"]
                    or not Path(binding["target_worktree"]).is_absolute()
                    or Path(binding["target_worktree"]).resolve(strict=True) != cwd):
                raise Rejected("Preparation target identity mismatch")
            issue = json.loads(self._run([self.gh, "api", "--hostname", "github.com",
                                          f"repos/{binding['repository']}/issues/{binding['issue']}"], cwd))
            if issue["number"] != binding["issue"] or issue["state"] != "open" or hashlib.sha256((issue["body"] or "").encode()).hexdigest() != binding["issue_body_sha256"]:
                raise Rejected("Preparation issue evidence drift")
            head = self._run([self.git, "-C", str(cwd), "rev-parse", "HEAD"], cwd).decode().strip()
            tree = self._run([self.git, "-C", str(cwd), "rev-parse", "HEAD^{tree}"], cwd).decode().strip()
            if head != binding["head"] or tree != binding["tree"]:
                raise Rejected("Preparation target source drift")
        except Rejected:
            raise
        except (OSError, subprocess.SubprocessError, KeyError, ValueError, json.JSONDecodeError) as exc:
            raise Rejected("Fresh pre-PR Git/GitHub verification unavailable") from exc
        return {"status": "PREPARATION_ONLY", "authority_effect": False,
                "platform_identity": "NOT_PROVEN", "actions_executed": []}

    def _verify(self, b, scope):
        fields = {"repository", "pr", "issue", "worktree", "branch", "base", "head", "tree",
                  "manifest_path", "manifest_sha256", "rule_path", "rule_sha256",
                  "rule_version", "config_version", "plan_sha256", "paths"}
        if not isinstance(b, dict) or set(b) != fields:
            raise Rejected("Incomplete canonical source binding")
        repo = b["repository"]
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repo):
            raise Rejected("Invalid canonical repository")
        for key in ("base", "head", "tree"):
            if not re.fullmatch(r"[0-9a-f]{40}", b[key]):
                raise Rejected("Require exact Git object IDs")
        for key in ("pr", "issue"):
            if type(b[key]) is not int or b[key] < 1:
                raise Rejected("Require exact GitHub issue/PR identity")
        for key in ("manifest_sha256", "rule_sha256", "plan_sha256"):
            if not re.fullmatch(r"[0-9a-f]{64}", b[key]):
                raise Rejected("Require exact content digest")
        if not isinstance(b["paths"], list) or not b["paths"]:
            raise Rejected("Missing allowed path scope")
        roots = [safe_path(p) for p in b["paths"]]
        for key in ("manifest_path", "rule_path"):
            safe_path(b[key])
        cwd = Path(b["worktree"]).resolve(strict=True)

        def git(*args):
            return self._run([self.git, "-C", str(cwd), *args], cwd)

        def api(endpoint, paged=False):
            args = [self.gh, "api", "--hostname", "github.com", endpoint]
            if paged:
                args += ["--paginate", "--slurp"]
            return json.loads(self._run(args, cwd))

        def equal(actual, expected, label):
            if actual != expected:
                raise Rejected("Fresh verification mismatch: " + label)

        equal(Path(git("rev-parse", "--show-toplevel").decode().strip()).resolve(), cwd, "worktree")
        equal(git("status", "--porcelain=v1", "--untracked-files=all").strip(), b"", "dirty source")
        remote = git("remote", "get-url", "--all", "origin").decode().strip()
        if remote not in {f"https://github.com/{repo}.git", f"https://github.com/{repo}",
                          f"git@github.com:{repo}.git"}:
            raise Rejected("Unexpected or ambiguous Git remote")
        equal(git("branch", "--show-current").decode().strip(), b["branch"], "branch")
        equal(git("rev-parse", "HEAD").decode().strip(), b["head"], "local head")
        equal(git("rev-parse", b["head"] + "^{tree}").decode().strip(), b["tree"], "local tree")
        equal(git("merge-base", b["base"], b["head"]).decode().strip(), b["base"], "base ancestry")
        pr = api(f"repos/{repo}/pulls/{b['pr']}")
        equal(pr["number"], b["pr"], "PR identity")
        equal(pr["state"], "open", "PR state")
        equal(pr["base"]["repo"]["full_name"], repo, "base repository")
        equal(pr["head"]["repo"]["full_name"], repo, "head repository")
        equal(pr["base"]["sha"], b["base"], "remote base")
        equal(pr["head"]["sha"], b["head"], "remote head")
        equal(pr["head"]["ref"], b["branch"], "remote branch")
        commit = api(f"repos/{repo}/git/commits/{b['head']}")
        equal(commit["sha"], b["head"], "remote commit")
        equal(commit["tree"]["sha"], b["tree"], "remote tree")
        plan = api(f"repos/{repo}/issues/{b['issue']}")
        equal(plan["number"], b["issue"], "plan identity")
        equal(plan["state"], "open", "plan state")
        equal(hashlib.sha256(plan["body"].encode()).hexdigest(), b["plan_sha256"], "plan content")
        changed = git("diff", "--no-ext-diff", "--no-textconv", "--no-renames", "--name-only", "-z",
                      b["base"], b["head"], "--").decode().split("\0")
        changed = sorted(p for p in changed if p)
        pages = api(f"repos/{repo}/pulls/{b['pr']}/files?per_page=100", paged=True)
        remote_files = [f for page in pages for f in page]
        equal(len(remote_files), pr["changed_files"], "complete GitHub file inventory")
        remote_paths = set()
        for f in remote_files:
            remote_paths.add(f["filename"])
            if "previous_filename" in f:
                remote_paths.add(f["previous_filename"])
        equal(sorted(remote_paths), changed, "local/remote path inventory")
        if any(not in_scope(path, roots) for path in changed):
            raise Rejected("Changed artifact outside authorized scope")
        manifest_raw = git("show", b["head"] + ":" + b["manifest_path"])
        rule_raw = git("show", b["head"] + ":" + b["rule_path"])
        equal(hashlib.sha256(manifest_raw).hexdigest(), b["manifest_sha256"], "manifest digest")
        equal(hashlib.sha256(rule_raw).hexdigest(), b["rule_sha256"], "rule digest")
        manifest = json.loads(manifest_raw)
        equal(manifest["config_version"], b["config_version"], "config version")
        equal(manifest["rule_version"], b["rule_version"], "rule version")
        # Re-read remote/local heads at the end to detect movement during verification.
        latest = api(f"repos/{repo}/pulls/{b['pr']}")
        equal(latest["head"]["sha"], b["head"], "head moved during verification")
        equal(latest["base"]["sha"], b["base"], "base moved during verification")
        equal(latest["state"], "open", "PR closed during verification")
        latest_plan = api(f"repos/{repo}/issues/{b['issue']}")
        equal(latest_plan["state"], "open", "plan closed during verification")
        equal(hashlib.sha256(latest_plan["body"].encode()).hexdigest(), b["plan_sha256"], "plan changed")
        equal(git("rev-parse", "HEAD").decode().strip(), b["head"], "local head moved")
        equal(git("status", "--porcelain=v1", "--untracked-files=all").strip(), b"", "source changed")
        # Scope and all configured identities contribute to the derived checkpoint.
        return {"issue": str(b["issue"]), "scope": scope, "base": b["base"], "head": b["head"],
                "checkpoint": digest({"binding": b, "scope": scope}),
                "evidence": f"https://github.com/{repo}/pull/{b['pr']}"}
