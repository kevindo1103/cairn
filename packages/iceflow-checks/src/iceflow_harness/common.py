from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

SHA40 = re.compile(r"[0-9a-f]{40}\Z")
SHA256 = re.compile(r"[0-9a-f]{64}\Z")
MAX_TEXT = 8 * 1024 * 1024


class Refused(Exception):
    """Only a finite code and non-sensitive numeric context escape the CLI."""
    def __init__(self, code: str):
        if not re.fullmatch(r"[A-Z][A-Z0-9_]{1,79}", code):
            code = "INTERNAL_ERROR"
        super().__init__(code)
        self.code = code


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True,
                      allow_nan=False).encode()


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise Refused("DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def parse_json(data: str | bytes) -> Any:
    try:
        return json.loads(data, object_pairs_hook=_pairs,
                          parse_constant=lambda _: (_ for _ in ()).throw(Refused("NONFINITE_JSON")))
    except (ValueError, UnicodeError, RecursionError) as exc:
        raise Refused("INVALID_JSON") from exc


def safe_rel(value: str, *, glob: bool = False) -> str:
    if (not isinstance(value, str) or not value or len(value) > 1024 or
        any(ord(c) < 32 or ord(c) == 127 for c in value) or "\\" in value or ":" in value or
        value.startswith("/") or any(x in {"", ".", ".."} for x in value.split("/"))):
        raise Refused("UNSAFE_PATH")
    if not glob and any(c in value for c in "*?[]"):
        raise Refused("UNSAFE_PATH")
    return PurePosixPath(value).as_posix()


def _check_path_components(path: Path) -> None:
    # lstat (rather than is_symlink) distinguishes inaccessible paths from absent
    # paths, including on Python 3.14. Walk root-first before normalizing '..' so
    # an alias cannot disappear from the spelling we inspect.
    for part in reversed((path, *path.parents)):
        try:
            info = os.lstat(part)
        except FileNotFoundError:
            continue  # New output leaves/parents are allowed.
        except (OSError, ValueError) as exc:
            raise Refused("PATH_IDENTITY_UNAVAILABLE") from exc
        if stat.S_ISLNK(info.st_mode):
            raise Refused("SYMLINK_REFUSED")
        # Python 3.11 has st_file_attributes; Path.is_junction needs 3.12.
        # Refuse ALL reparse points, not just symlinks/junctions. Cloud placeholders
        # are deliberately unsupported: copy to a normal local directory first.
        if (getattr(info, "st_file_attributes", 0) &
                getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)) or getattr(info, "st_reparse_tag", 0):
            raise Refused("REPARSE_POINT_REFUSED")


def no_symlinks(path: Path) -> Path:
    """Return the resolved path only after refusing linked/reparse ancestors.

    This is a trusted-local-user guard, NOT an OS security boundary against a
    different process racing renames, bind mounts, or directory replacement.
    """
    raw = Path(path)
    if not raw.is_absolute():
        raw = Path.cwd() / raw
    _check_path_components(raw)
    try:
        resolved = raw.resolve(strict=False)
    except (OSError, RuntimeError, ValueError) as exc:
        raise Refused("PATH_IDENTITY_UNAVAILABLE") from exc
    _check_path_components(resolved)
    return resolved


def read_bytes(path: Path, limit: int = MAX_TEXT) -> bytes:
    path = no_symlinks(path)
    try:
        with path.open("rb") as stream:
            s = os.fstat(stream.fileno())
            if not stat.S_ISREG(s.st_mode) or s.st_size > limit:
                raise Refused("FILE_LIMIT_OR_KIND")
            data = stream.read(limit + 1)
            t = os.fstat(stream.fileno())
        if len(data) > limit or (s.st_ino, s.st_size, s.st_mtime_ns) != (t.st_ino, t.st_size, t.st_mtime_ns):
            raise Refused("FILE_CHANGED_OR_LIMIT")
        return data
    except OSError as exc:
        raise Refused("FILE_UNAVAILABLE") from exc


def outside(path: Path, root: Path) -> Path:
    path = no_symlinks(path)
    root = root.resolve()
    if path == root or path.is_relative_to(root):
        raise Refused("OUTPUT_INSIDE_TARGET_REPO")
    return path


def write_new(path: Path, data: bytes) -> None:
    """Never replace a file. Reports are new snapshots, not mutable authority."""
    path = no_symlinks(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path = no_symlinks(path)  # Recheck after creating missing parent directories.
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError as exc:
        raise Refused("OUTPUT_EXISTS") from exc


def finding(check: str, status: str, code: str, *, path: str | None = None,
            line: int | None = None, details: Any = None) -> dict:
    if status not in {"PASS", "FAIL", "WARN", "NOT_RUN", "BLOCKED", "INFO"}:
        raise Refused("INVALID_STATUS")
    result = {"check": check, "status": status, "code": code}
    if path is not None:
        result["path"] = safe_rel(path)
    if line is not None:
        result["line"] = line
    if details is not None:
        result["details"] = details
    return result
