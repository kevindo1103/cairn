"""Literal accepted package identity; reject unsupported content or version."""

import hashlib
import json
from pathlib import Path

import comms_ledger
from comms_ledger.ledger import EXPECTED_SCHEMA_VERSION
from .store import Rejected


def verify_package():
    lock = json.loads((Path(__file__).resolve().parent / "package.lock.json").read_text())
    root = Path(comms_ledger.__file__).resolve().parent
    actual = {p.name: hashlib.sha256(p.read_bytes().replace(b"\r\n", b"\n")).hexdigest()
              for p in root.glob("*.py")}
    if (actual != lock["module_lf_sha256"] or comms_ledger.__version__ != lock["version"]
            or EXPECTED_SCHEMA_VERSION != lock["schema_version"]):
        raise Rejected("Ledger package changed; bind and revalidate the accepted package version")
    return {"version": lock["version"], "source_commit": lock["source_commit"],
            "tag": lock["tag"], "tag_object": lock["tag_object"], "package_tree": lock["package_tree"]}
