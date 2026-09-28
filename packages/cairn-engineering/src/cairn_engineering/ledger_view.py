"""Read a CLOSED, consistent schema-1 Cairn copy without constructing Store/Ledger.

Live host integration supplies a snapshot through its own protected adapter. This
CLI deliberately does not open a live WAL store, call recover, or create a store.
"""
from __future__ import annotations

import sqlite3
import time
from contextlib import closing
from pathlib import Path

from iceflow_harness.common import Refused, canonical, digest, no_symlinks, parse_json, read_bytes
from .contracts import integer, require, seal

MAX_DB_BYTES = 64 * 1024 * 1024
MAX_ROWS = 4096
CORE_LEDGER_BLOB = "60703b676d28f10499850371eaefe92ace844533"
STATES = {"QUEUED", "SENT", "ACKED", "STARTED", "COMPLETED", "BLOCKED", "CANCELLED", "SUPERSEDED"}
# Deliberately never SELECT credential hashes, lease tokens or raw history details.
EVENT_FIELDS = ("id", "payload", "digest", "target", "state", "worker_owner", "worker_until",
                "ack_deadline", "attempts", "needs_inspection", "eligible_at", "receipt", "result_evidence")


def read_ledger_copy(path: Path, *, offline_copy: bool, now: float | None = None) -> dict:
    require(offline_copy is True, "OFFLINE_LEDGER_COPY_REQUIRED")
    path = no_symlinks(path)
    require(not any(path.is_relative_to(Path(p)) for p in ("/opt", "/var/lib", "/var/www")), "LIVE_LEDGER_PATH_REFUSED")
    require(path.is_file(), "LEDGER_COPY_MISSING")
    for ext in ('-wal', '-shm', '-journal'):
        require(not Path(str(path) + ext).exists(), "LEDGER_SIDECAR_REFUSED")
    before = read_bytes(path, MAX_DB_BYTES)
    try:
        with closing(sqlite3.connect(path.as_uri() + '?mode=ro&immutable=1', uri=True, timeout=2)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA query_only=ON')
            db.execute('PRAGMA trusted_schema=OFF')
            # No candidate-controlled SQL, views or extension functions.
            objects = {row['name']: row['type'] for row in db.execute(
                "SELECT name,type FROM sqlite_master WHERE name IN ('config','events','checkpoints','recipients')")}
            require(objects == dict.fromkeys(('config','events','checkpoints','recipients'),'table'), "LEDGER_SCHEMA_UNSUPPORTED")
            db.execute('BEGIN')
            version = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
            require(version is not None and version[0] == '1', "LEDGER_SCHEMA_UNSUPPORTED")
            rows = db.execute('SELECT '+','.join(EVENT_FIELDS)+' FROM events ORDER BY id LIMIT ?', (MAX_ROWS+1,)).fetchall()
            require(len(rows) <= MAX_ROWS, "LEDGER_SNAPSHOT_BUDGET")
            events = []
            for row in rows:
                e = dict(row); p = parse_json(e.pop('payload'))
                require(type(p) is dict and e['state'] in STATES and p.get('target_task') == e['target'], "LEDGER_EVENT_INVALID")
                require(digest(canonical(p)) == e['digest'], "LEDGER_PAYLOAD_DIGEST_MISMATCH")
                e['payload'] = {k: p.get(k) for k in ('source_task','target_task','issue','checkpoint','base','head','scope','kind','dependency')}
                events.append(e)
            checkpoints = [dict(r) for r in db.execute('SELECT issue,scope,checkpoint,base,head,revision FROM checkpoints LIMIT ?', (MAX_ROWS+1,))]
            recipients = [dict(r) for r in db.execute('SELECT task,busy,active_event FROM recipients LIMIT ?', (MAX_ROWS+1,))]
            require(len(checkpoints)<=MAX_ROWS and len(recipients)<=MAX_ROWS,"LEDGER_SNAPSHOT_BUDGET")
            row = db.execute("SELECT value FROM config WHERE key='adapter:registry'").fetchone()
            registry = None
            if row is not None:
                raw = parse_json(row[0]);integer(raw.get('revision'))
                require(type(raw.get('entries')) is list and len(raw['entries'])<=MAX_ROWS, "REGISTRY_INVALID")
                entries=[]
                for item in raw['entries']:
                    require(type(item) is dict, "REGISTRY_INVALID")
                    entries.append({k:item.get(k) for k in ('task_id','session_id','generation','role','state','scopes')})
                registry={'revision':raw['revision'],'entries':entries}
            db.rollback()
    except sqlite3.Error as exc:
        raise Refused('LEDGER_READ_UNAVAILABLE') from exc
    require(read_bytes(path,MAX_DB_BYTES)==before, "LEDGER_COPY_CHANGED")
    return seal({'schema':'cairn-ledger-observation-v1','core_schema':1,'events':events,
                 'checkpoints':checkpoints,'recipients':recipients,'registry':registry,
                 'observed_at_unix':time.time() if now is None else now,
                 'origin':'OFFLINE_COPY_NOT_LIVE_ATTESTATION','file_sha256':digest(before),
                 'authority':'NONE','recovery_executed':False})
