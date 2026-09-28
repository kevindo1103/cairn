from __future__ import annotations

import math
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from .common import Refused, SHA40, canonical, digest, parse_json, safe_rel, utc_now


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise Refused("GITHUB_REDIRECT_REFUSED")


class ReadOnlyGitHub:
    """Allowlisted GET only. No generic request/write endpoint exposed."""
    def __init__(self, repository: str, repository_id: int, *, max_reads=20, deadline_seconds=60, transport=None):
        if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", repository):
            raise Refused("GITHUB_REPOSITORY_INVALID")
        if any(x in {".", ".."} for x in repository.split("/")):
            raise Refused("GITHUB_REPOSITORY_INVALID")
        self.repository, self.repository_id = repository, repository_id
        self.max_reads, self.reads = min(max_reads, 20), 0
        self.deadline = time.monotonic() + min(deadline_seconds, 120)
        self.transport = transport or self._http

    def _http(self, suffix: str):
        token = os.environ.get("GH_TOKEN") or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise Refused("GITHUB_TOKEN_MISSING")
        request = urllib.request.Request("https://api.github.com/repos/" + self.repository + suffix,
            headers={"Accept": "application/vnd.github+json", "Authorization": "Bearer " + token,
                     "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "iceflow-harness/0.1"}, method="GET")
        try:
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=max(0.1, min(15, self.deadline - time.monotonic()))) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
                if len(raw) > 8 * 1024 * 1024:
                    raise Refused("GITHUB_RESPONSE_LIMIT")
                return parse_json(raw)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise Refused("GITHUB_READ_FAILED") from exc

    def get(self, suffix: str):
        # Internal suffix grammar prevents SSRF, arbitrary endpoints and query injection.
        pattern = r"(?:|/issues/[1-9][0-9]*|/branches/[A-Za-z0-9_.-]+(?:%2F[A-Za-z0-9_.-]+)*|/pulls/[1-9][0-9]*|/pulls/[1-9][0-9]*/files\?per_page=100&page=[1-9][0-9]*|/commits/[0-9a-f]{40}/check-runs\?per_page=100&page=[1-9][0-9]*)"
        if not re.fullmatch(pattern, suffix):
            raise Refused("GITHUB_ENDPOINT_REFUSED")
        if self.reads >= self.max_reads or time.monotonic() >= self.deadline:
            raise Refused("GITHUB_BUDGET_EXHAUSTED")
        self.reads += 1
        return self.transport(suffix)

    def pr_snapshot(self, number: int) -> dict:
        if type(number) is not int or number <= 0:
            raise Refused("PR_NUMBER_INVALID")
        repository = self.get("")
        if repository.get("id") != self.repository_id or repository.get("full_name", "").lower() != self.repository.lower():
            raise Refused("REPOSITORY_ID_MISMATCH")
        start = self.get(f"/pulls/{number}")
        def identity(pr):
            try:
                head, base = pr["head"]["sha"], pr["base"]["sha"]
                count = pr["changed_files"]
                if (not SHA40.fullmatch(head) or not SHA40.fullmatch(base) or type(count) is not int or
                    count < 0 or pr["base"]["repo"]["id"] != self.repository_id):
                    raise Refused("PR_SHAPE_INVALID")
                return (head, base, count, pr.get("state"), pr.get("draft"), pr.get("updated_at"),
                        digest((pr.get("body") or "").encode()))
            except (KeyError, TypeError) as exc:
                raise Refused("PR_SHAPE_INVALID") from exc
        initial = identity(start)
        if initial[2] > 3000:
            raise Refused("PR_FILE_LIST_TRUNCATED")
        files = []
        for page in range(1, max(1, math.ceil(initial[2] / 100)) + 1):
            rows = self.get(f"/pulls/{number}/files?per_page=100&page={page}")
            if not isinstance(rows, list):
                raise Refused("PR_FILES_INVALID")
            for row in rows:
                file = {"path": safe_rel(row["filename"]), "status": row["status"], "blob_sha": row.get("sha")}
                if row.get("previous_filename"):
                    file["previous_path"] = safe_rel(row["previous_filename"])
                files.append(file)
        if len(files) != initial[2] or len({f["path"] for f in files}) != len(files):
            raise Refused("PR_FILES_INCOMPLETE_OR_DUPLICATE")
        # Head check-runs only, all pages. These are not all workflow runs or merge-commit checks.
        checks = []
        first = self.get(f"/commits/{initial[0]}/check-runs?per_page=100&page=1")
        total = first.get("total_count")
        if type(total) is not int or total < 0:
            raise Refused("CHECKS_INVALID")
        for page in range(1, max(1, math.ceil(total / 100)) + 1):
            data = first if page == 1 else self.get(f"/commits/{initial[0]}/check-runs?per_page=100&page={page}")
            if data.get("total_count") != total:
                raise Refused("CHECKS_CHANGED")
            for row in data.get("check_runs", []):
                if row.get("head_sha") != initial[0]:
                    raise Refused("CHECK_SUBJECT_MISMATCH")
                checks.append({k: row.get(k) for k in ["id", "name", "status", "conclusion", "head_sha", "details_url"]})
        if len(checks) != total or len({c["id"] for c in checks}) != total:
            raise Refused("CHECKS_INCOMPLETE")
        end = self.get(f"/pulls/{number}")
        if initial != identity(end):
            raise Refused("PR_CHANGED_DURING_SNAPSHOT")
        result = {"schema": "github-pr-observation-v1", "repository": self.repository, "repository_id": self.repository_id,
                  "pr": number, "head_sha": initial[0], "base_sha": initial[1], "changed_files": len(files),
                  "files": sorted(files, key=lambda f: f["path"]), "checks": checks,
                  "observed_at": utc_now(), "api_reads": self.reads, "authority": "NONE",
                  "permissions_of_token": "NOT_ATTESTED", "comments_authority": "NOT_EVALUATED",
                  "merge_commit_checks": "NOT_COLLECTED", "check_runs_atomic_snapshot": False,
                  "release_ready": "NOT_EVALUATED", "body_sha256": initial[6]}
        result["snapshot_digest"] = digest(canonical(result))
        return result


def render_pr_metadata(snapshot: dict) -> str:
    lines = ["<!-- iceflow-harness:metadata:start -->", "### Source metadata (generated, not approval)",
             f"PR: #{snapshot['pr']}", f"Head: `{snapshot['head_sha']}`", f"Base: `{snapshot['base_sha']}`",
             f"Changed files: {snapshot['changed_files']}", f"Observed: {snapshot['observed_at']}", "", "```json",
             canonical(snapshot["files"]).decode(), "```", "",
             "Head check-runs only; no CI/all-pass/release claim. Human body outside this block is untouched.",
             "<!-- iceflow-harness:metadata:end -->", ""]
    return "\n".join(lines)
