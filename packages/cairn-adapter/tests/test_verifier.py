"""Real local Git repository; deterministic GitHub API fixtures, explicitly not live E2E."""

import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from cairn_adapter import GitHubVerifier, Rejected


class FixtureGitHub(GitHubVerifier):
    def __init__(self, responses):
        super().__init__()
        self.responses, self.api_calls = responses, []

    def _run(self, argv, cwd):
        if argv[0] == self.gh:
            self.api_calls.append(argv[4])
            response = self.responses[argv[4]]
            if isinstance(response, Exception):
                raise response
            return json.dumps(response).encode()
        return super()._run(argv, cwd)


class VerifierTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.git("init", "-b", "adapter-work")
        self.git("remote", "add", "origin", "https://github.com/synthetic/repo.git")
        (self.root / "src").mkdir()
        self.manifest = b'{"rule_version":"rule-1","config_version":"config-1"}\n'
        self.rule = b"canonical synthetic rule\n"
        (self.root / "manifest.json").write_bytes(self.manifest)
        (self.root / "RULE.md").write_bytes(self.rule)
        (self.root / "src/work.py").write_text("value = 1\n")
        self.commit("base")
        base = self.git("rev-parse", "HEAD")
        (self.root / "src/work.py").write_text("value = 2\n")
        self.commit("head")
        head, tree = self.git("rev-parse", "HEAD"), self.git("rev-parse", "HEAD^{tree}")
        plan = "Synthetic plan authorized by owner fixture"
        self.binding = dict(repository="synthetic/repo", pr=1, issue=2, worktree=str(self.root),
                            branch="adapter-work", base=base, head=head, tree=tree,
                            manifest_path="manifest.json", manifest_sha256=hashlib.sha256(self.manifest).hexdigest(),
                            rule_path="RULE.md", rule_sha256=hashlib.sha256(self.rule).hexdigest(),
                            rule_version="rule-1", config_version="config-1", plan_sha256=hashlib.sha256(plan.encode()).hexdigest(),
                            paths=["src"])
        self.pr_path = "repos/synthetic/repo/pulls/1"
        self.responses = {
            self.pr_path: {"number": 1, "state": "open", "changed_files": 1,
                           "base": {"repo": {"full_name": "synthetic/repo"}, "sha": base},
                           "head": {"repo": {"full_name": "synthetic/repo"}, "sha": head, "ref": "adapter-work"}},
            f"repos/synthetic/repo/git/commits/{head}": {"sha": head, "tree": {"sha": tree}},
            "repos/synthetic/repo/issues/2": {"number": 2, "state": "open", "body": plan},
            self.pr_path + "/files?per_page=100": [[{"filename": "src/work.py"}]],
        }

    def git(self, *args):
        return subprocess.run(["git", "-c", "core.excludesFile=", "-c", "core.autocrlf=false",
                               "-C", str(self.root), *args], check=True,
                              capture_output=True).stdout.decode().strip()

    def commit(self, message):
        self.git("add", ".")
        self.git("-c", "user.name=Synthetic Test", "-c", "user.email=test@example.invalid", "commit", "-m", message)

    def test_real_git_positive_and_every_call_rechecks_github(self):
        verifier = FixtureGitHub(self.responses)
        first = verifier.verify(self.binding, "adapter")
        second = verifier.verify(self.binding, "adapter")
        self.assertEqual(first, second)
        self.assertEqual(verifier.api_calls.count(self.pr_path), 4)
        self.assertEqual(first["head"], self.binding["head"])

    def test_remote_identity_base_head_tree_plan_changes_fail_closed(self):
        changes = [(self.pr_path, ("head", "sha"), "a" * 40),
                   (self.pr_path, ("base", "sha"), "a" * 40),
                   (self.pr_path, ("head", "repo", "full_name"), "wrong/repository"),
                   (self.pr_path, ("state",), "closed"),
                   (f"repos/synthetic/repo/git/commits/{self.binding['head']}", ("tree", "sha"), "a" * 40),
                   ("repos/synthetic/repo/issues/2", ("body",), "changed decision"),
                   (self.pr_path, ("changed_files",), 2)]
        for path, keys, value in changes:
            with self.subTest(keys=keys, value=value):
                responses = copy.deepcopy(self.responses)
                target = responses[path]
                for key in keys[:-1]:
                    target = target[key]
                target[keys[-1]] = value
                with self.assertRaises(Rejected):
                    FixtureGitHub(responses).verify(self.binding, "adapter")

    def test_manifest_rule_versions_and_path_scope_mismatches(self):
        for key, value in [("manifest_sha256", "0" * 64), ("rule_sha256", "0" * 64),
                           ("rule_version", "other"), ("config_version", "other"),
                           ("paths", ["other"]), ("manifest_path", "../outside"),
                           ("head", "--help"), ("pr", True)]:
            with self.subTest(key=key):
                binding = dict(self.binding, **{key: value})
                with self.assertRaises(Rejected):
                    FixtureGitHub(self.responses).verify(binding, "adapter")

    def test_dirty_source_wrong_remote_and_branch(self):
        (self.root / "unexpected.txt").write_text("uncommitted")
        with self.assertRaises(Rejected):
            FixtureGitHub(self.responses).verify(self.binding, "adapter")
        (self.root / "unexpected.txt").unlink()
        self.git("remote", "set-url", "origin", "https://github.com/other/repo.git")
        with self.assertRaises(Rejected):
            FixtureGitHub(self.responses).verify(self.binding, "adapter")

    def test_unavailable_tool_and_malformed_api_are_rejections(self):
        with self.assertRaises(Rejected):
            GitHubVerifier(git="missing-cairn-test-binary").verify(self.binding, "adapter")
        for response in (None, {}, Rejected("unavailable API")):
            responses = dict(self.responses, **{self.pr_path: response})
            with self.assertRaises(Rejected):
                FixtureGitHub(responses).verify(self.binding, "adapter")

    def test_remote_moves_during_verification(self):
        class Moving(FixtureGitHub):
            def _run(inner, argv, cwd):
                if argv[0] == inner.gh and argv[4] == self.pr_path and self.pr_path in inner.api_calls:
                    changed = copy.deepcopy(inner.responses[self.pr_path])
                    changed["head"]["sha"] = "f" * 40
                    return json.dumps(changed).encode()
                return super()._run(argv, cwd)
        with self.assertRaises(Rejected):
            Moving(self.responses).verify(self.binding, "adapter")

    def test_handoff_reference_body_head_and_unreachable_evidence(self):
        self.responses[self.pr_path]["body"] = "reviewed PR"
        pr = {"repository": "synthetic/repo", "number": 1, "state": "open",
              "head": self.binding["head"], "body_sha256": hashlib.sha256(b"reviewed PR").hexdigest()}
        issue = {"repository": "synthetic/repo", "number": 2, "state": "open", "body_sha256": self.binding["plan_sha256"]}
        verifier = FixtureGitHub(self.responses)
        verifier.verify_references([pr], [issue])
        self.responses[self.pr_path]["head"]["sha"] = "f" * 40
        with self.assertRaises(Rejected):
            verifier.verify_references([pr], [issue])
        self.responses[self.pr_path] = Rejected("GitHub unavailable")
        with self.assertRaises(Rejected):
            verifier.verify_references([pr], [issue])


if __name__ == "__main__":
    unittest.main()
