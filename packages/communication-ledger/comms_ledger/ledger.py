"""SQLite projections and append-only history, committed in the same transaction.

This is a trusted local coordination store, not an identity provider or an
external-work fencing system. Every operation opens its own SQLite connection.
"""

import hashlib
import json
import math
import sqlite3
import time
import uuid
from contextlib import closing, contextmanager
from pathlib import Path


TERMINAL = {"COMPLETED", "BLOCKED", "CANCELLED", "SUPERSEDED"}
FIELDS = {"dedupe_key", "source_task", "target_task", "issue", "checkpoint",
          "base", "head", "scope", "kind", "priority", "dependency",
          "evidence", "next_action"}
EXPECTED_SCHEMA_VERSION = "2"


class LedgerError(ValueError):
    """Rejected command; its transaction is rolled back."""


def text_value(value, name, limit=500):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise LedgerError(f"{name} must be nonempty text, at most {limit} characters")
    if any(ord(c) < 32 for c in value):
        raise LedgerError(f"{name} must be a single line")
    return value


def evidence_ref(value):
    text_value(value, "evidence", 1000)
    if not value.startswith(("https://", "artifact://", "synthetic://")):
        raise LedgerError("Use an https://, artifact:// or synthetic:// evidence reference")
    return value


def duration(value):
    if isinstance(value, bool) or not isinstance(value, (float, int)):
        raise LedgerError("duration must be numeric")
    if not math.isfinite(value) or not 1 <= value <= 86400:
        raise LedgerError("duration must be between 1 and 86400 seconds")
    return value


def _initialize_pm_authority(db, pm_task=None):
    """Schema-2 DDL in the caller's transaction; never an implicit migration."""
    statements = (
        "CREATE TABLE IF NOT EXISTS pm_authority (revision INTEGER PRIMARY KEY, task_id TEXT NOT NULL UNIQUE, event_id TEXT UNIQUE REFERENCES events(id), receipt TEXT NOT NULL)",
        "CREATE TRIGGER IF NOT EXISTS pm_authority_no_update BEFORE UPDATE ON pm_authority BEGIN SELECT RAISE(ABORT, 'PM authority is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS pm_authority_no_delete BEFORE DELETE ON pm_authority BEGIN SELECT RAISE(ABORT, 'PM authority is append-only'); END",
        "CREATE TRIGGER IF NOT EXISTS bootstrap_pm_no_update BEFORE UPDATE ON config WHEN OLD.key='pm_task' OR NEW.key='pm_task' BEGIN SELECT RAISE(ABORT, 'bootstrap PM is immutable'); END",
        "CREATE TRIGGER IF NOT EXISTS bootstrap_pm_no_delete BEFORE DELETE ON config WHEN OLD.key='pm_task' BEGIN SELECT RAISE(ABORT, 'bootstrap PM is immutable'); END",
    )
    for statement in statements:
        db.execute(statement)
    if pm_task is not None:
        db.execute("INSERT INTO pm_authority VALUES (0, ?, NULL, ?)",
                   (pm_task, json.dumps({"bootstrap": True}, sort_keys=True)))


class Ledger:
    def __init__(self, path, *, pm_task=None, clock=time.time):
        self.path = str(Path(path).resolve())
        self.clock = clock
        if pm_task is not None:
            text_value(pm_task, "pm_task")
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect()) as db:
            # Refuse old/unknown stores before DDL or journal-mode changes. No
            # constructor migration; only newly initialized schema 2 is supported.
            if db.execute("SELECT 1 FROM sqlite_master WHERE name='config'").fetchone():
                schema = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
                if schema is None or schema[0] != EXPECTED_SCHEMA_VERSION:
                    raise LedgerError("unsupported schema_version; offline migration is required")
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript("""
                CREATE TABLE IF NOT EXISTS config (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS checkpoints (
                    issue TEXT NOT NULL, scope TEXT NOT NULL, checkpoint TEXT NOT NULL,
                    base TEXT NOT NULL, head TEXT NOT NULL, revision INTEGER NOT NULL,
                    PRIMARY KEY(issue, scope));
                CREATE TABLE IF NOT EXISTS recipients (
                    task TEXT PRIMARY KEY, busy INTEGER NOT NULL DEFAULT 0,
                    active_event TEXT);
                CREATE TABLE IF NOT EXISTS events (
                    id TEXT PRIMARY KEY, dedupe_key TEXT NOT NULL UNIQUE,
                    payload TEXT NOT NULL, digest TEXT NOT NULL,
                    target TEXT NOT NULL, state TEXT NOT NULL,
                    priority INTEGER NOT NULL, dependency TEXT REFERENCES events(id),
                    attempts INTEGER NOT NULL DEFAULT 0,
                    needs_inspection INTEGER NOT NULL DEFAULT 0,
                    eligible_at REAL NOT NULL, created_at REAL NOT NULL, updated_at REAL NOT NULL,
                    delivery_token TEXT, delivery_owner TEXT, delivery_until REAL,
                    ack_deadline REAL, worker_token TEXT, worker_owner TEXT, worker_until REAL,
                    receipt TEXT, ack_evidence TEXT, result_evidence TEXT, reason TEXT);
                CREATE INDEX IF NOT EXISTS queue ON events(target, state, priority, created_at);
                CREATE TABLE IF NOT EXISTS history (
                    seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT REFERENCES events(id),
                    at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, detail TEXT NOT NULL);
                CREATE TRIGGER IF NOT EXISTS history_no_update BEFORE UPDATE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS history_no_delete BEFORE DELETE ON history
                    BEGIN SELECT RAISE(ABORT, 'history is append-only'); END;
                CREATE TRIGGER IF NOT EXISTS payload_immutable
                    BEFORE UPDATE OF id, dedupe_key, payload, digest, target, dependency ON events
                    BEGIN SELECT RAISE(ABORT, 'event identity is immutable'); END;
                CREATE TRIGGER IF NOT EXISTS event_no_delete BEFORE DELETE ON events
                    BEGIN SELECT RAISE(ABORT, 'events are durable'); END;
            """)
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT value FROM config WHERE key='pm_task'").fetchone()
            if row is None:
                if pm_task is None:
                    raise LedgerError("Initialize this database with pm_task first")
                db.execute("INSERT INTO config VALUES ('pm_task', ?)", (pm_task,))
                db.execute("INSERT INTO config VALUES ('schema_version', ?)", (EXPECTED_SCHEMA_VERSION,))
            elif pm_task is not None and row[0] != pm_task:
                raise LedgerError("pm_task is already bound to this database")
            schema = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
            if schema is None or schema[0] != EXPECTED_SCHEMA_VERSION:
                raise LedgerError("unsupported schema_version; migration is required")
            _initialize_pm_authority(db, pm_task if row is None else None)
            db.commit()

    def _connect(self):
        db = sqlite3.connect(self.path, timeout=10, isolation_level=None)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA synchronous=FULL")
        return db

    @contextmanager
    def _tx(self):
        db = self._connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            yield db
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            db.close()

    def _pm(self, db, actor):
        if actor != self._pm_authority(db)["task_id"]:
            raise LedgerError("Only the current PM task may perform this operation")

    @staticmethod
    def _pm_authority(db):
        row = db.execute("SELECT * FROM pm_authority ORDER BY revision DESC LIMIT 1").fetchone()
        if row is None:
            raise LedgerError("Missing PM authority; offline recovery is required")
        return {"revision": row["revision"], "task_id": row["task_id"],
                "event_id": row["event_id"], "receipt": json.loads(row["receipt"])}

    def pm_authority(self):
        with self._tx() as db:
            return self._pm_authority(db)

    def succeed_pm(self, *, actor, event_id, expected_revision, predecessor, successor,
                   predecessor_generation, successor_generation, checkpoint_revision,
                   registry_revision, review_digest, evidence):
        """Trusted-host CAS, called inside the adapter's owner-reviewed transaction.

        Registry generations/review digest are external proof bindings, not host
        authentication. Authority revision is a separate monotonic core epoch.
        No process, installation, transport or task retirement occurs here.
        """
        for name, value in (("actor", actor), ("predecessor", predecessor), ("successor", successor)):
            text_value(value, name)
        for name, value, minimum in (("expected_revision", expected_revision, 0),
                ("registry_revision", registry_revision, 0), ("checkpoint_revision", checkpoint_revision, 1),
                ("predecessor_generation", predecessor_generation, 1), ("successor_generation", successor_generation, 1)):
            if type(value) is not int or value < minimum:
                raise LedgerError("Invalid " + name)
        if not isinstance(review_digest, str) or len(review_digest) != 64 or any(c not in "0123456789abcdef" for c in review_digest):
            raise LedgerError("Require exact reviewed proof digest")
        evidence_ref(evidence)
        with self._tx() as db:
            current = self._pm_authority(db)
            if current["revision"] != expected_revision or current["task_id"] != predecessor or actor != predecessor:
                raise LedgerError("PM authority CAS moved or predecessor differs")
            if db.execute("SELECT 1 FROM pm_authority WHERE task_id=?", (successor,)).fetchone():
                raise LedgerError("PM identities cannot be reused")
            event = self._get(db, event_id)
            p = json.loads(event["payload"])
            if (p["kind"] != "HANDOFF" or event["state"] != "COMPLETED" or
                    p["source_task"] != predecessor or event["target"] != successor or not self._fresh(db, event)):
                raise LedgerError("Require completed fresh predecessor-to-successor HANDOFF")
            cp = db.execute("SELECT revision FROM checkpoints WHERE issue=? AND scope=?", (p["issue"], p["scope"])).fetchone()
            if cp[0] != checkpoint_revision:
                raise LedgerError("Checkpoint revision moved")
            for row in db.execute("SELECT * FROM events"):
                related = {json.loads(row["payload"])["source_task"], row["target"]}
                if predecessor in related or successor in related:
                    if row["state"] != "COMPLETED" or any(row[k] is not None for k in
                            ("delivery_token", "delivery_until", "worker_token", "worker_until")):
                        raise LedgerError("PM handoff requires zero outstanding work and leases")
            if db.execute("SELECT 1 FROM recipients WHERE task IN (?,?) AND active_event IS NOT NULL",
                          (predecessor, successor)).fetchone():
                raise LedgerError("PM handoff still holds a worker slot")
            receipt = dict(predecessor=predecessor, predecessor_generation=predecessor_generation,
                           successor_generation=successor_generation, checkpoint_revision=checkpoint_revision,
                           registry_revision=registry_revision, review_digest=review_digest, evidence=evidence,
                           event_digest=event["digest"], checkpoint={k: p[k] for k in ("issue", "scope", "checkpoint", "base", "head")})
            db.execute("INSERT INTO pm_authority VALUES (?,?,?,?)",
                       (expected_revision + 1, successor, event_id, json.dumps(receipt, sort_keys=True)))
            self._audit(db, event_id, actor, "PM_SUCCEEDED", dict(revision=expected_revision + 1, successor=successor, **receipt))
            return self._pm_authority(db)

    def _audit(self, db, event_id, actor, action, detail):
        text_value(actor, "actor")
        db.execute("INSERT INTO history(event_id,at,actor,action,detail) VALUES (?,?,?,?,?)",
                   (event_id, self.clock(), actor, action, json.dumps(detail, sort_keys=True)))

    def _get(self, db, event_id):
        row = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if row is None:
            raise LedgerError("Unknown event")
        return dict(row)

    def _change(self, db, event_id, actor, action, **updates):
        updates["updated_at"] = self.clock()
        db.execute("UPDATE events SET " + ",".join(f"{k}=?" for k in updates) + " WHERE id=?",
                   (*updates.values(), event_id))
        # Tokens are capabilities; do not copy them into history.
        self._audit(db, event_id, actor, action,
                    {k: v for k, v in updates.items() if "token" not in k})

    def _fresh(self, db, event):
        p = json.loads(event["payload"])
        cp = db.execute("SELECT * FROM checkpoints WHERE issue=? AND scope=?",
                        (p["issue"], p["scope"])).fetchone()
        return cp is not None and all(cp[k] == p[k] for k in ("checkpoint", "base", "head"))

    def checkpoint(self, actor, issue, scope, checkpoint, base, head, expected_revision, evidence):
        """Compare-and-swap current binding; invalidate all outstanding old bindings."""
        for name, value in locals().copy().items():
            if name in {"actor", "issue", "scope", "checkpoint", "base", "head"}:
                text_value(value, name)
        evidence_ref(evidence)
        if type(expected_revision) is not int or expected_revision < 0:
            raise LedgerError("expected_revision must be a nonnegative integer")
        with self._tx() as db:
            row = db.execute("SELECT * FROM checkpoints WHERE issue=? AND scope=?", (issue, scope)).fetchone()
            revision = row["revision"] if row else 0
            if revision != expected_revision:
                raise LedgerError("Checkpoint revision moved; reread before updating")
            if row and all(row[k] == v for k, v in {"checkpoint": checkpoint, "base": base, "head": head}.items()):
                return dict(row)
            ambiguous = next((r for r in db.execute(
                "SELECT id,payload FROM events WHERE state='SENT_AMBIGUOUS'")
                if (lambda p: p["issue"] == issue and p["scope"] == scope)(json.loads(r["payload"]))), None)
            if ambiguous:
                raise LedgerError("Ambiguous delivery must be reconciled before checkpoint movement")
            db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?) ON CONFLICT(issue,scope) DO UPDATE SET "
                       "checkpoint=excluded.checkpoint,base=excluded.base,head=excluded.head,revision=excluded.revision",
                       (issue, scope, checkpoint, base, head, revision + 1))
            self._audit(db, None, actor, "CHECKPOINT", dict(issue=issue, scope=scope, checkpoint=checkpoint,
                        base=base, head=head, revision=revision + 1, evidence=evidence))
            for row in db.execute("SELECT * FROM events WHERE state NOT IN ('COMPLETED','BLOCKED','CANCELLED','SUPERSEDED')").fetchall():
                p = json.loads(row["payload"])
                if p["issue"] == issue and p["scope"] == scope and not self._fresh(db, row):
                    self._change(db, row["id"], actor, "STALE_CHECKPOINT", state="SUPERSEDED",
                                 reason="STALE_CHECKPOINT", delivery_token=None, worker_token=None)
            return dict(issue=issue, scope=scope, checkpoint=checkpoint, base=base, head=head, revision=revision + 1)

    def enqueue(self, payload):
        """Dedupe is immutable: same key + different content is a conflict."""
        if not isinstance(payload, dict) or set(payload) != FIELDS:
            raise LedgerError("Payload must contain exactly: " + ", ".join(sorted(FIELDS)))
        p = dict(payload)
        for k in FIELDS - {"priority", "dependency", "evidence"}:
            text_value(p[k], k)
        evidence_ref(p["evidence"])
        if p["kind"] not in {"HANDOFF", "APPROVAL", "STOP", "CHECKPOINT"}:
            raise LedgerError("Unknown event kind")
        if type(p["priority"]) is not int or p["priority"] not in (0, 1, 2, 100):
            raise LedgerError("priority must be 0, 1, 2, or PM urgent 100")
        if p["dependency"] is not None:
            text_value(p["dependency"], "dependency")
        raw = json.dumps(p, sort_keys=True, separators=(",", ":"))
        digest = hashlib.sha256(raw.encode()).hexdigest()
        with self._tx() as db:
            existing = db.execute("SELECT * FROM events WHERE dedupe_key=?", (p["dedupe_key"],)).fetchone()
            if existing:
                if existing["digest"] != digest:
                    raise LedgerError("Dedupe conflict: key already binds different content")
                return self._public(dict(existing))
            ambiguous = db.execute("SELECT id FROM events WHERE target=? AND state='SENT_AMBIGUOUS' LIMIT 1",
                                   (p["target_task"],)).fetchone()
            if ambiguous:
                raise LedgerError("Ambiguous delivery blocks new assignments to this target")
            if p["kind"] == "STOP" or p["priority"] == 100:
                self._pm(db, p["source_task"])
            if p["kind"] == "STOP" and (p["priority"] != 100 or p["dependency"]):
                raise LedgerError("STOP requires priority 100 and no dependency")
            if p["dependency"]:
                self._get(db, p["dependency"])
            if not self._fresh(db, {"payload": raw}):
                raise LedgerError("Event binding is not the current checkpoint/base/head")
            event_id, now = str(uuid.uuid4()), self.clock()
            db.execute("INSERT OR IGNORE INTO recipients(task) VALUES (?)", (p["target_task"],))
            db.execute("INSERT INTO events(id,dedupe_key,payload,digest,target,state,priority,dependency,eligible_at,created_at,updated_at) "
                       "VALUES (?,?,?,?,?,'QUEUED',?,?,?,?,?)",
                       (event_id, p["dedupe_key"], raw, digest, p["target_task"], p["priority"], p["dependency"], now, now, now))
            self._audit(db, event_id, p["source_task"], "QUEUED", {"digest": digest})
            return self._public(self._get(db, event_id))

    def set_busy(self, actor, target, busy, evidence):
        evidence_ref(evidence)
        text_value(target, "target")
        if type(busy) is not bool:
            raise LedgerError("busy must be boolean")
        with self._tx() as db:
            if actor != target:
                self._pm(db, actor)
            db.execute("INSERT INTO recipients(task,busy) VALUES (?,?) ON CONFLICT(task) DO UPDATE SET busy=excluded.busy",
                       (target, int(busy)))
            self._audit(db, None, actor, "BUSY", dict(target=target, busy=busy, evidence=evidence))
            return dict(target=target, busy=busy)

    def _available(self, db, row):
        if json.loads(row["payload"])["kind"] == "STOP":
            return True
        target = db.execute("SELECT * FROM recipients WHERE task=?", (row["target"],)).fetchone()
        return not target["busy"] and target["active_event"] in (None, row["id"])

    def _dependency_ready(self, db, row):
        if row["dependency"] is None:
            return True
        dependency = self._get(db, row["dependency"])
        return dependency["state"] == "COMPLETED" and self._fresh(db, dependency)

    def _retry(self, db, row, reason):
        self._change(db, row["id"], "ledger", reason,
                     state="QUEUED" if row["attempts"] < 2 else "BLOCKED",
                     needs_inspection=1, eligible_at=self.clock() + 30,
                     delivery_token=None, delivery_until=None, ack_deadline=None,
                     reason=reason if row["attempts"] < 2 else "RETRY_EXHAUSTED:" + reason)

    def _reap(self, db):
        now = self.clock()
        for row in db.execute("SELECT * FROM events WHERE state NOT IN ('COMPLETED','BLOCKED','CANCELLED','SUPERSEDED')").fetchall():
            if row["state"] in ("ACKED", "STARTED") and row["worker_until"] <= now:
                self._change(db, row["id"], "ledger", "WORKER_LEASE_EXPIRED", state="BLOCKED",
                             reason="WORKER_LEASE_EXPIRED:confirm_worker_stopped", worker_token=None)
            elif row["state"] == "SENT" and row["ack_deadline"] <= now:
                self._retry(db, row, "MISSING_ACK")
            elif row["state"] == "QUEUED" and row["delivery_token"] and row["delivery_until"] <= now:
                # The external call may have crossed its send boundary before expiry.
                # Preserve the attempt token for exact late-receipt correlation; never retry blindly.
                self._change(db, row["id"], "ledger", "DELIVERY_AMBIGUOUS",
                             state="SENT_AMBIGUOUS", reason="DELIVERY_LEASE_EXPIRED")

    def recover(self):
        """Run timeout recovery once. Never loops or launches a worker."""
        with self._tx() as db:
            self._reap(db)
            return {"recovered_at": self.clock()}

    def inspect_retry(self, event_id, actor, evidence):
        evidence_ref(evidence)
        with self._tx() as db:
            self._reap(db)
            row = self._get(db, event_id)
            p = json.loads(row["payload"])
            if actor != p["source_task"]:
                self._pm(db, actor)
            if row["state"] != "QUEUED" or not row["needs_inspection"] or row["attempts"] >= 2:
                raise LedgerError("No bounded retry awaiting inspection")
            self._change(db, event_id, actor, "RETRY_INSPECTED", needs_inspection=0, reason=None)
            self._audit(db, event_id, actor, "INSPECTION_EVIDENCE", {"evidence": evidence})
            return self._public(self._get(db, event_id))

    def claim(self, target, dispatcher, lease_seconds=60):
        duration(lease_seconds)
        text_value(dispatcher, "dispatcher")
        with self._tx() as db:
            self._reap(db)
            rows = db.execute("SELECT * FROM events WHERE target=? AND state='QUEUED' "
                              "AND delivery_token IS NULL AND needs_inspection=0 AND attempts<2 AND eligible_at<=? "
                              "ORDER BY priority DESC,created_at,id", (target, self.clock())).fetchall()
            for row in rows:
                if not self._available(db, row) or not self._dependency_ready(db, row) or not self._fresh(db, row):
                    continue
                # Reserve one delivery lane per recipient; STOP is a separate control lane.
                is_stop = json.loads(row["payload"])["kind"] == "STOP"
                pending = db.execute("SELECT payload FROM events WHERE target=? AND "
                                     "(delivery_token IS NOT NULL OR state IN ('SENT','SENT_AMBIGUOUS'))",
                                     (target,)).fetchall()
                if any((json.loads(r["payload"])["kind"] == "STOP") == is_stop for r in pending):
                    continue
                token = str(uuid.uuid4())
                self._change(db, row["id"], dispatcher, "CLAIMED", delivery_token=token,
                             delivery_owner=dispatcher, delivery_until=self.clock() + lease_seconds,
                             attempts=row["attempts"] + 1)
                return {"event": self._public(self._get(db, row["id"])), "delivery_token": token}
            return None

    def _delivery(self, db, event_id, token):
        row = self._get(db, event_id)
        if row["state"] != "QUEUED" or not token or row["delivery_token"] != token or row["delivery_until"] <= self.clock():
            raise LedgerError("Delivery lease is absent, expired, or owned by another dispatcher")
        if not self._fresh(db, row):
            raise LedgerError("Stale event")
        return row

    def sent(self, event_id, delivery_token, receipt, ack_timeout=120):
        """Record transport acceptance only, after actual manual delivery."""
        evidence_ref(receipt)
        duration(ack_timeout)
        with self._tx() as db:
            row = self._delivery(db, event_id, delivery_token)
            self._change(db, event_id, row["delivery_owner"], "SENT", state="SENT", receipt=receipt,
                         delivery_token=None, delivery_until=None, ack_deadline=self.clock() + ack_timeout)
            return self._public(self._get(db, event_id))

    def late_sent(self, event_id, delivery_token, receipt_ref, receipt_digest,
                  confirmation_digest, ack_timeout=120):
        """Import a separately operator-confirmed late receipt; never retry or infer worker stages."""
        evidence_ref(receipt_ref)
        text_value(receipt_digest, "receipt_digest", 64)
        text_value(confirmation_digest, "confirmation_digest", 64)
        duration(ack_timeout)
        with self._tx() as db:
            row = self._get(db, event_id)
            if row["state"] == "SENT":
                proof = db.execute("SELECT detail FROM history WHERE event_id=? AND action='LATE_DELIVERY_PROOF' "
                                   "ORDER BY seq DESC LIMIT 1", (event_id,)).fetchone()
                expected = {"receipt_digest": receipt_digest, "confirmation_digest": confirmation_digest}
                if row["receipt"] == receipt_ref and proof and json.loads(proof["detail"]) == expected:
                    return self._public(row)
                raise LedgerError("Conflicting late-delivery replay")
            if (row["state"] != "SENT_AMBIGUOUS" or not delivery_token
                    or row["delivery_token"] != delivery_token or row["delivery_until"] is None
                    or row["delivery_until"] > self.clock()):
                raise LedgerError("Late receipt requires its expired ambiguous delivery attempt")
            self._change(db, event_id, row["delivery_owner"], "LATE_SENT_RECONCILED",
                         state="SENT", receipt=receipt_ref, delivery_token=None,
                         delivery_until=None, ack_deadline=self.clock() + ack_timeout, reason=None)
            self._audit(db, event_id, row["delivery_owner"], "LATE_DELIVERY_PROOF",
                        {"receipt_digest": receipt_digest, "confirmation_digest": confirmation_digest})
            return self._public(self._get(db, event_id))

    def delivery_failed(self, event_id, delivery_token, evidence):
        evidence_ref(evidence)
        with self._tx() as db:
            row = self._delivery(db, event_id, delivery_token)
            self._audit(db, event_id, row["delivery_owner"], "DELIVERY_FAILURE", {"evidence": evidence})
            self._retry(db, row, "DELIVERY_FAILED")
            return self._public(self._get(db, event_id))

    def ack(self, event_id, target, worker, evidence, lease_seconds=300):
        evidence_ref(evidence)
        text_value(worker, "worker")
        duration(lease_seconds)
        with self._tx() as db:
            row = self._get(db, event_id)
            if row["target"] != target or not self._fresh(db, row):
                raise LedgerError("Wrong target or stale checkpoint")
            if row["state"] in ("ACKED", "STARTED", "COMPLETED"):
                if row["worker_owner"] != worker or row["ack_evidence"] != evidence:
                    raise LedgerError("Conflicting acknowledgement")
                if row["state"] != "COMPLETED" and row["worker_until"] <= self.clock():
                    raise LedgerError("Worker lease expired; recover and reconcile")
                return {"event": self._public(row), "worker_token": row["worker_token"] if row["state"] != "COMPLETED" else None}
            if row["state"] != "SENT" or row["ack_deadline"] <= self.clock():
                raise LedgerError("ACK requires SENT before its deadline")
            if not self._available(db, row) or not self._dependency_ready(db, row):
                raise LedgerError("Recipient busy or dependency incomplete; message retained")
            token = str(uuid.uuid4())
            if json.loads(row["payload"])["kind"] != "STOP":
                db.execute("UPDATE recipients SET active_event=? WHERE task=?", (event_id, target))
            self._change(db, event_id, target, "ACKED", state="ACKED", worker_owner=worker,
                         worker_token=token, worker_until=self.clock() + lease_seconds, ack_evidence=evidence,
                         ack_deadline=None)
            return {"event": self._public(self._get(db, event_id)), "worker_token": token}

    def _worker(self, db, event_id, token):
        row = self._get(db, event_id)
        if row["state"] not in ("ACKED", "STARTED") or not token or row["worker_token"] != token or row["worker_until"] <= self.clock():
            raise LedgerError("Worker lease is absent, expired, or owned by another worker")
        if not self._fresh(db, row):
            raise LedgerError("Stale checkpoint")
        return row

    def start(self, event_id, worker_token, evidence):
        evidence_ref(evidence)
        with self._tx() as db:
            row = self._worker(db, event_id, worker_token)
            if row["state"] == "ACKED":
                self._change(db, event_id, row["worker_owner"], "STARTED", state="STARTED")
                self._audit(db, event_id, row["worker_owner"], "START_EVIDENCE", {"evidence": evidence})
            return self._public(self._get(db, event_id))

    def renew(self, event_id, worker_token, lease_seconds=300):
        duration(lease_seconds)
        with self._tx() as db:
            row = self._worker(db, event_id, worker_token)
            self._change(db, event_id, row["worker_owner"], "RENEWED", worker_until=self.clock() + lease_seconds)
            return self._public(self._get(db, event_id))

    def complete(self, event_id, worker_token, evidence):
        evidence_ref(evidence)
        with self._tx() as db:
            row = self._worker(db, event_id, worker_token)
            if row["state"] != "STARTED":
                raise LedgerError("Completion requires STARTED")
            self._change(db, event_id, row["worker_owner"], "COMPLETED", state="COMPLETED", result_evidence=evidence,
                         worker_token=None, worker_until=None)
            db.execute("UPDATE recipients SET active_event=NULL WHERE active_event=?", (event_id,))
            return self._public(self._get(db, event_id))

    def terminate(self, event_id, actor, state, evidence):
        if state not in {"BLOCKED", "CANCELLED", "SUPERSEDED"}:
            raise LedgerError("Invalid terminal state")
        evidence_ref(evidence)
        with self._tx() as db:
            row = self._get(db, event_id)
            p = json.loads(row["payload"])
            if actor not in {p["source_task"], row["target"]}:
                self._pm(db, actor)
            if row["state"] in TERMINAL:
                if row["state"] != state:
                    raise LedgerError("Terminal event cannot change state")
                return self._public(row)
            self._change(db, event_id, actor, state, state=state, reason=evidence,
                         worker_token=None, delivery_token=None)
            # Keep the active slot: terminal bookkeeping does not stop a real writer.
            return self._public(self._get(db, event_id))

    def release_stopped_worker(self, event_id, actor, evidence):
        """PM attests the old worker has actually stopped before freeing its slot."""
        evidence_ref(evidence)
        with self._tx() as db:
            self._pm(db, actor)
            row = self._get(db, event_id)
            if row["state"] not in TERMINAL - {"COMPLETED"}:
                raise LedgerError("Only a terminal blocked/cancelled/superseded worker can be released")
            db.execute("UPDATE recipients SET active_event=NULL WHERE active_event=?", (event_id,))
            self._audit(db, event_id, actor, "WORKER_CONFIRMED_STOPPED", {"evidence": evidence})
            return {"released_event": event_id}

    def override_priority(self, event_id, actor, priority, evidence):
        evidence_ref(evidence)
        if type(priority) is not int or priority not in (0, 1, 2, 100):
            raise LedgerError("Invalid priority")
        with self._tx() as db:
            self._pm(db, actor)
            row = self._get(db, event_id)
            if row["state"] != "QUEUED" or row["delivery_token"]:
                raise LedgerError("Priority override requires an unclaimed queued event")
            if json.loads(row["payload"])["kind"] == "STOP" and priority != 100:
                raise LedgerError("STOP must remain urgent")
            self._change(db, event_id, actor, "PRIORITY_OVERRIDE", priority=priority)
            self._audit(db, event_id, actor, "OVERRIDE_EVIDENCE", {"evidence": evidence})
            return self._public(self._get(db, event_id))

    @staticmethod
    def _public(row):
        result = {k: v for k, v in row.items() if k not in ("delivery_token", "worker_token")}
        result["payload"] = json.loads(result["payload"])
        return result

    def get(self, event_id):
        with self._tx() as db:
            return self._public(self._get(db, event_id))

    def snapshot(self, target=None):
        with self._tx() as db:
            rows = db.execute("SELECT * FROM events WHERE (? IS NULL OR target=?) ORDER BY created_at,id", (target, target)).fetchall()
            return {"events": [self._public(dict(r)) for r in rows],
                    "recipients": [dict(r) for r in db.execute("SELECT * FROM recipients WHERE (? IS NULL OR task=?)", (target, target))],
                    "checkpoints": [dict(r) for r in db.execute("SELECT * FROM checkpoints")],
                    "automatic_wake": "NOT_IMPLEMENTED"}

    def history(self, event_id=None):
        with self._tx() as db:
            return [dict(r) for r in db.execute("SELECT * FROM history WHERE (? IS NULL OR event_id=?) ORDER BY seq", (event_id, event_id))]
