"""Host-owned registry metadata in the existing ledger DB, never a worker API.

This module assumes the host alone can open the DB and construct Owner/Store objects.
Python object privacy and possession of the database file are NOT security boundaries.
"""

import hashlib
import hmac
import json
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path

from comms_ledger.ledger import Ledger, LedgerError, EXPECTED_SCHEMA_VERSION


class Rejected(LedgerError):
    pass


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def credential_hash(token):
    if not isinstance(token, str) or len(token) < 32:
        raise Rejected("Require a random bearer credential of at least 32 characters")
    return hashlib.sha256(token.encode()).hexdigest()


def get_config(db, key):
    row = db.execute("SELECT value FROM config WHERE key=?", ("adapter:" + key,)).fetchone()
    if row is None:
        raise Rejected("Missing canonical adapter configuration")
    return json.loads(row[0])


def put_config(db, key, value):
    db.execute("INSERT INTO config VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
               ("adapter:" + key, canonical(value)))


class TransactionLedger(Ledger):
    """Reuse package methods inside the adapter's already locked transaction.

    Do not initialize, clone or reimplement ledger schema/transitions. Each instance
    lives for just one outer transaction and cannot commit independently.
    """
    def __init__(self, db, path, clock):
        self.db, self.path, self.clock = db, str(path), clock

    @contextmanager
    def _tx(self):
        yield self.db


class Store:
    def __init__(self, project_root, project, *, clock=time.time):
        self.path = Path(project_root).resolve() / "ledger.sqlite"
        self.project, self.clock = project, clock
        # Opening a worker interface may not create or initialize a database.
        with self.transaction():
            pass

    @contextmanager
    def transaction(self):
        db = sqlite3.connect(self.path.as_uri() + "?mode=rw", uri=True,
                             timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        try:
            db.execute("PRAGMA foreign_keys=ON")
            db.execute("PRAGMA synchronous=FULL")
            db.execute("BEGIN IMMEDIATE")
            schema = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
            if schema is None or schema[0] != EXPECTED_SCHEMA_VERSION:
                raise Rejected("Unsupported ledger schema")
            if get_config(db, "project") != self.project:
                raise Rejected("Project/database binding mismatch")
            from .package import verify_package
            if get_config(db, "package") != verify_package() or get_config(db, "registry_schema") != 2:
                raise Rejected("Unsupported package or adapter registry schema; no implicit migration")
            ledger = TransactionLedger(db, self.path, self.clock)
            registry = get_config(db, "registry")
            if registry["entries"]:
                validate_pm_entries(db, ledger, registry["entries"])
            yield db, ledger
            registry = get_config(db, "registry")
            if registry["entries"]:
                validate_pm_entries(db, ledger, registry["entries"])
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    @classmethod
    def initialize(cls, project_root, project, pm_task, owner_token, *, clock=time.time):
        """Trusted host bootstrap for a NEW TEST project. Never exposed to principals."""
        from .package import verify_package
        package = verify_package()
        path = Path(project_root).resolve() / "ledger.sqlite"
        path.parent.mkdir(parents=True, exist_ok=True)
        # O_EXCL prevents concurrent/repeated bootstrap from rebinding existing data.
        with path.open("xb"):
            pass
        ledger = Ledger(path, pm_task=pm_task, clock=clock)
        with ledger._tx() as db:
            put_config(db, "project", project)
            put_config(db, "owner_hash", credential_hash(owner_token))
            put_config(db, "registry", {"revision": 0, "entries": []})
            put_config(db, "registry_schema", 2)
            put_config(db, "package", package)
        return cls(project_root, project, clock=clock)


COMMANDS = {"checkpoint", "enqueue", "claim", "sent", "late_sent", "delivery_failed", "reconcile",
            "ack", "start", "renew", "complete", "terminate", "inspect_retry",
            "override_priority", "set_busy", "get", "retirement", "handoff_review",
            "authority_flip", "retire", "release_stopped_worker", "snapshot_prep", "projection"}
STATES = {"ABSENT", "QUEUED", "SENT", "SENT_AMBIGUOUS", "ACKED", "STARTED", "COMPLETED", "BLOCKED",
          "CANCELLED", "SUPERSEDED"}


def validate_entries(entries, previous, owner_hash):
    if not isinstance(entries, list) or not entries:
        raise Rejected("Registry must be a nonempty host snapshot")
    tasks, credentials, successors = set(), set(), set()
    old = {e["task_id"]: e for e in previous}
    fields = {"task_id", "credential_hash", "generation", "state", "grants", "bindings",
              "successor", "quiescence", "role", "project", "session_id", "scopes", "authority",
              "worktree", "branch", "rule_version", "config_version", "parent", "owner",
              "expected_output", "stop_condition", "inventory"}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != fields:
            raise Rejected("Unexpected registry fields")
        task, credential, generation = entry["task_id"], entry["credential_hash"], entry["generation"]
        if not isinstance(task, str) or not task or task in tasks:
            raise Rejected("Duplicate or empty principal")
        if (not isinstance(credential, str) or len(credential) != 64
                or any(c not in "0123456789abcdef" for c in credential)
                or credential in credentials or hmac.compare_digest(credential, owner_hash)):
            raise Rejected("Duplicate credential or owner/principal authority overlap")
        if type(generation) is not int or generation < 1:
            raise Rejected("Invalid principal generation")
        if entry["state"] not in {"pending", "active", "quiesced", "retired"}:
            raise Rejected("Unknown registry state")
        if entry["role"] not in {"PM", "Lead", "worker", "QC", "Docs", "Infra"}:
            raise Rejected("Unknown canonical role")
        for key in ("project", "session_id", "worktree", "branch", "rule_version", "config_version",
                    "owner", "expected_output", "stop_condition"):
            if not isinstance(entry[key], str) or not entry[key].strip():
                raise Rejected("Incomplete registry trust root: " + key)
        if entry["parent"] is not None and not isinstance(entry["parent"], str):
            raise Rejected("Invalid registry parent")
        if task in old:
            prior = old[task]
            rotated = credential != prior["credential_hash"]
            if generation != prior["generation"] + int(rotated):
                raise Rejected("Credential rotation must increment principal generation exactly once")
            allowed = {"pending": {"pending"}, "active": {"active", "quiesced"},
                       "quiesced": {"quiesced"}, "retired": {"retired"}}
            if entry["state"] not in allowed[prior["state"]] or (
                    prior["state"] == "retired" and entry != prior):
                raise Rejected("Owner CAS cannot bypass flip/retirement or resurrect a predecessor")
        elif generation != 1:
            raise Rejected("New principal starts at generation one")
        elif previous and entry["state"] != "pending":
            raise Rejected("New successors must enter pending")
        if not isinstance(entry["bindings"], dict) or not isinstance(entry["grants"], list):
            raise Rejected("Invalid bindings/grants")
        if sorted(entry["scopes"]) != sorted(entry["bindings"]) or sorted(entry["authority"]) != sorted(
                {g["command"] for g in entry["grants"]}):
            raise Rejected("Scope/authority projections disagree with canonical grants")
        for binding in entry["bindings"].values():
            if any(binding.get(k) != entry[k] for k in ("worktree", "branch", "rule_version", "config_version")):
                raise Rejected("Registry and source binding disagree")
            if binding.get("repository") != entry["project"]:
                raise Rejected("Repository identity differs from project")
        inventory = entry["inventory"]
        if not isinstance(inventory, dict) or set(inventory) != {"complete", "unfinished_work", "prs", "issues", "blockers", "readback_digest"}:
            raise Rejected("Missing canonical handoff inventory")
        if type(inventory["complete"]) is not bool or any(not isinstance(inventory[k], list)
                for k in ("unfinished_work", "prs", "issues", "blockers")):
            raise Rejected("Invalid canonical handoff inventory")
        for grant in entry["grants"]:
            if (set(grant) != {"command", "scope", "states"} or grant["command"] not in COMMANDS
                    or grant["scope"] not in entry["bindings"] or not grant["states"]
                    or not set(grant["states"]) <= STATES):
                raise Rejected("Invalid principal x command x scope x state grant")
        successor = entry["successor"]
        if successor is not None:
            if (set(successor) != {"task_id", "generation"} or successor["task_id"] == task
                    or successor["task_id"] in successors or type(successor["generation"]) is not int):
                raise Rejected("Duplicate or invalid successor")
            successors.add(successor["task_id"])
        q = entry["quiescence"]
        if q is not None and (set(q) != {"evidence", "active_mutations", "unmapped_work", "ownership_ambiguity"}
                             or not isinstance(q["evidence"], str) or not q["evidence"]
                             or any(type(q[k]) is not int or q[k] < 0
                                    for k in ("active_mutations", "unmapped_work", "ownership_ambiguity"))):
            raise Rejected("Invalid trusted-host quiescence observation")
        tasks.add(task)
        credentials.add(credential)
    # A full snapshot may not silently drop a principal and later reuse its generation.
    if not set(old) <= tasks:
        raise Rejected("Keep quiesced predecessor records; deletion is not retirement")
    by_task = {e["task_id"]: e for e in entries}
    if len({e["session_id"] for e in entries}) != len(entries):
        raise Rejected("Duplicate session identity")
    for entry in entries:
        if entry["parent"] is not None and (entry["parent"] not in by_task or entry["parent"] == entry["task_id"]):
            raise Rejected("Missing or self-referencing parent")
        s = entry["successor"]
        if s and (s["task_id"] not in by_task or by_task[s["task_id"]]["generation"] != s["generation"]):
            raise Rejected("Unknown or stale successor generation")
        visited, node = set(), entry
        while node["successor"]:
            if node["task_id"] in visited:
                raise Rejected("Successor cycle")
            visited.add(node["task_id"])
            node = by_task[node["successor"]["task_id"]]


def validate_pm_entries(db, ledger, entries):
    """One current PM; historical PM tombstones and one pending successor allowed."""
    current = ledger._pm_authority(db)["task_id"]
    by_task = {e["task_id"]: e for e in entries}
    pm = by_task.get(current)
    if not pm or pm["role"] != "PM" or pm["state"] not in {"active", "quiesced"}:
        raise Rejected("Registry must preserve the core's current PM authority")
    historical = {r[0] for r in db.execute("SELECT task_id FROM pm_authority")} - {current}
    for task in historical:
        prior = by_task.get(task)
        if not prior or prior["role"] != "PM" or prior["state"] not in {"quiesced", "retired"}:
            raise Rejected("Historical PM identities remain fenced tombstones")
    for candidate in entries:
        if candidate["role"] != "PM" or candidate["task_id"] in historical | {current}:
            continue
        if candidate["state"] != "pending" or pm["successor"] != {
                "task_id": candidate["task_id"], "generation": candidate["generation"]}:
            raise Rejected("Only the mapped pending PM successor may hold a future PM role")


class Owner:
    """Separate control-plane interface; never mounted as a worker command."""
    def __init__(self, store):
        self.store = store

    def replace(self, token, expected_revision, entries):
        entries = json.loads(canonical(entries))
        with self.store.transaction() as (db, ledger):
            owner_hash = get_config(db, "owner_hash")
            if not hmac.compare_digest(credential_hash(token), owner_hash):
                raise Rejected("Only separate registry owner authority may write registry")
            registry = get_config(db, "registry")
            if type(expected_revision) is not int or registry["revision"] != expected_revision:
                raise Rejected("Registry CAS moved")
            validate_entries(entries, registry["entries"], owner_hash)
            if any(e["project"] != self.store.project for e in entries):
                raise Rejected("Registry project differs from canonical database")
            validate_pm_entries(db, ledger, entries)
            result = {"revision": expected_revision + 1, "entries": entries}
            put_config(db, "registry", result)
            ledger._audit(db, None, "registry-owner", "REGISTRY_CAS",
                          {"revision": result["revision"], "digest": digest(result)})
            return {"revision": result["revision"]}

    def attest(self, token, expected_revision, event_id, command, review_digest, evidence):
        """Separate host approval of a reviewed snapshot; never callable by a worker."""
        from comms_ledger.ledger import evidence_ref
        if command not in {"complete", "authority_flip", "retire", "release_stopped_worker"}:
            raise Rejected("Unknown host attestation")
        evidence_ref(evidence)
        if not isinstance(review_digest, str) or len(review_digest) != 64:
            raise Rejected("Require full reviewed-snapshot digest")
        with self.store.transaction() as (db, ledger):
            if not hmac.compare_digest(credential_hash(token), get_config(db, "owner_hash")):
                raise Rejected("Separate host owner approval required")
            if type(expected_revision) is not int or get_config(db, "registry")["revision"] != expected_revision:
                raise Rejected("Stale attestation revision")
            ledger._get(db, event_id)
            record = {"revision": expected_revision, "digest": review_digest, "evidence": evidence}
            put_config(db, "attest:" + command + ":" + event_id, record)
            ledger._audit(db, event_id, "registry-owner", "HOST_ATTESTED", {"command": command, **record})
            return record
