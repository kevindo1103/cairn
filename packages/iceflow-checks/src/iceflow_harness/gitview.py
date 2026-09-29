from __future__ import annotations

import hashlib
import os
import subprocess
from pathlib import Path

from .common import Refused, SHA40, safe_rel


class GitView:
    """Read immutable Git blobs, never checkout/import/execute the target application."""
    def __init__(self, root: Path, ref: str = "HEAD"):
        self.root = root.resolve()
        self.cache: dict[str, bytes] = {}
        top = self._git(["rev-parse", "--show-toplevel"]).decode().strip()
        if Path(top).resolve() != self.root:
            raise Refused("REPO_ROOT_REQUIRED")
        self.sha = self._git(["rev-parse", "--verify", "--end-of-options", ref + "^{commit}"]).decode().strip()
        if not SHA40.fullmatch(self.sha):
            raise Refused("GIT_SHA_UNSUPPORTED")
        self.tree = self._git(["rev-parse", self.sha + "^{tree}"]).decode().strip()
        self.entries = {}
        for row in self._git(["ls-tree", "-r", "-l", "-z", self.sha]).split(b"\0"):
            if not row:
                continue
            meta, raw_name = row.split(b"\t", 1)
            mode, kind, blob, size = meta.decode().split()
            try:
                name = safe_rel(raw_name.decode("utf-8", "strict"))
            except UnicodeError as exc:
                raise Refused("NON_UTF8_GIT_PATH") from exc
            self.entries[name] = (mode, kind, blob, int(size) if size != "-" else 0)
        self.dirty = bool(self._git(["status", "--porcelain=v1", "--untracked-files=normal"]))

    def _git(self, args: list[str], data: bytes | None = None) -> bytes:
        env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_") and
               k not in {"GH_TOKEN", "GITHUB_TOKEN"}}
        env.update(GIT_TERMINAL_PROMPT="0", GIT_OPTIONAL_LOCKS="0", GIT_NO_REPLACE_OBJECTS="1")
        try:
            result = subprocess.run(
                ["git", "-c", "core.fsmonitor=false", "-c", "core.hooksPath=/dev/null",
                 "-C", str(self.root), *args], input=data, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=40, env=env, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise Refused("GIT_UNAVAILABLE_OR_TIMEOUT") from exc
        if result.returncode != 0:
            raise Refused("GIT_READ_FAILED")
        if len(result.stdout) > 64 * 1024 * 1024:
            raise Refused("GIT_OUTPUT_LIMIT")
        return result.stdout

    def preload(self, paths: list[str]) -> None:
        paths = list(dict.fromkeys(p for p in paths if p not in self.cache))
        requests = []
        expected_size = 0
        for path in paths:
            mode, kind, blob, size = self.entries[path]
            if mode not in {"100644", "100755"} or kind != "blob":
                raise Refused("SOURCE_LINK_OR_SUBMODULE")
            expected_size += size
            if size > 8 * 1024 * 1024:
                raise Refused("SOURCE_BLOB_LIMIT")
            requests.append(blob)
        if len(paths) > 5000 or expected_size + sum(map(len, self.cache.values())) > 48 * 1024 * 1024:
            raise Refused("SOURCE_BUDGET")
        if not paths:
            return
        raw = self._git(["cat-file", "--batch"], ("\n".join(requests) + "\n").encode())
        pos = 0
        for path, blob in zip(paths, requests):
            end = raw.find(b"\n", pos)
            fields = raw[pos:end].decode().split()
            if len(fields) != 3 or fields[0] != blob or fields[1] != "blob":
                raise Refused("SOURCE_BLOB_MISMATCH")
            size = int(fields[2])
            content = raw[end + 1:end + 1 + size]
            if len(content) != size or hashlib.sha1(f"blob {size}\0".encode() + content).hexdigest() != blob:
                raise Refused("SOURCE_BLOB_MISMATCH")
            self.cache[path] = content
            pos = end + size + 2
        if pos != len(raw):
            raise Refused("SOURCE_BLOB_TRAILING")

    def read(self, path: str) -> bytes:
        if path not in self.entries:
            raise Refused("SOURCE_FILE_MISSING")
        self.preload([path])
        return self.cache[path]

    def source(self) -> dict:
        return {"kind": "LOCAL_GIT_COMMITTED_TREE", "commit_sha": self.sha, "tree_sha": self.tree,
                "working_tree_dirty": self.dirty, "uncommitted_changes_included": False,
                "blobs_read": {p: self.entries[p][2] for p in sorted(self.cache)}}
