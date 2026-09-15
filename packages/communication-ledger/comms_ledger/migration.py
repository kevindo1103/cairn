"""Host-only offline copy preparation. No transport, activation or OS fencing.

Only run against detached, host-owned input/output paths. SQLite read-only mode
does not stop external writers or authenticate a host. Leftover destinations
after any failure/crash are quarantined by the host and must never be reused.
"""
import hashlib
import json
import os
import sqlite3
import stat
import time
from contextlib import closing, contextmanager
from pathlib import Path

from . import __version__
from .ledger import (Ledger, LedgerError, FIELDS, EXPECTED_SCHEMA_VERSION,
                     _initialize_pm_authority, evidence_ref, text_value)

# Exact sqlite_master fingerprint of accepted 0.1.0 DDL, frozen in the test SQL.
V1_SCHEMA_SHA256 = 'ab7b06b15fc21495b39232ffb6d1599a115f200fdbcbc27717d0df62b34650e5'
TABLES = ('config', 'checkpoints', 'events', 'recipients', 'history', 'sqlite_sequence')


def _canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False)
    except (ValueError, TypeError) as exc:
        raise LedgerError('Unrepresentable or ambiguous snapshot value') from exc


def _digest(value):
    return hashlib.sha256(_canonical(value).encode()).hexdigest()


def _is_reparse(path):
    info = path.lstat()
    return stat.S_ISLNK(info.st_mode) or bool(getattr(info, 'st_file_attributes', 0) & 0x400)


def _path(value, *, existing):
    if '..' in Path(value).parts:
        raise LedgerError('Parent traversal can hide an aliased path component')
    absolute = Path(os.path.abspath(os.fspath(value)))
    # Inspect original components before resolve follows any links/junctions.
    for component in (*reversed(absolute.parents), absolute):
        if os.path.lexists(component) and _is_reparse(component):
            raise LedgerError('Symlink/junction/reparse paths are not accepted')
    if not absolute.parent.is_dir():
        raise LedgerError('Destination/source parent must already be a host-owned directory')
    if existing:
        info = absolute.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_nlink != 1:
            raise LedgerError('Require a regular file with one unambiguous identity')
    elif os.path.lexists(absolute):
        raise LedgerError('Destination already exists; quarantine/review rather than overwrite')
    return absolute.resolve(strict=existing)


def _identity(path):
    path = _path(path, existing=True)
    info = path.stat()
    if not info.st_ino:
        raise LedgerError('Filesystem does not provide a stable file identity')
    return {'device': info.st_dev, 'inode': info.st_ino, 'links': info.st_nlink}


@contextmanager
def _read(path):
    with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=5)) as db:
        db.row_factory = sqlite3.Row
        db.execute('PRAGMA query_only=ON')
        db.execute('BEGIN')
        yield db


def _snapshot(db, tables=TABLES):
    schema = [list(row) for row in db.execute('SELECT type,name,tbl_name,sql FROM sqlite_master ORDER BY type,name')]
    data = {name: sorted([list(r) for r in db.execute('SELECT * FROM "' + name + '"')], key=_canonical)
            for name in tables}
    return {'schema': schema, 'data': data}


def _source_snapshot(db, path):
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise LedgerError('Source SQLite integrity/FK check failed')
    snapshot = _snapshot(db)
    if _digest(snapshot['schema']) != V1_SCHEMA_SHA256:
        raise LedgerError('Unknown schema-1 objects or schema fingerprint')
    config = dict(snapshot['data']['config'])
    if config.get('schema_version') != '1':
        raise LedgerError('Require exact source schema_version 1')
    text_value(config.get('pm_task'), 'immutable bootstrap PM')
    if any(not isinstance(k, str) or not isinstance(v, str) for k, v in config.items()):
        raise LedgerError('Ambiguous config types')
    for row in db.execute('SELECT * FROM events'):
        if row['state'] not in {'QUEUED', 'COMPLETED', 'BLOCKED', 'CANCELLED', 'SUPERSEDED'} or any(
                row[k] is not None for k in ('delivery_token', 'worker_token', 'delivery_until', 'worker_until', 'ack_deadline')):
            raise LedgerError('In-flight/unknown event, capability or deadline requires separate resolution')
        try:
            payload = json.loads(row['payload'])
        except (TypeError, ValueError) as exc:
            raise LedgerError('Malformed event payload') from exc
        if (not isinstance(payload, dict) or set(payload) != FIELDS or
                hashlib.sha256(row['payload'].encode()).hexdigest() != row['digest'] or
                any(payload[k] != row[c] for k, c in (('target_task', 'target'), ('dedupe_key', 'dedupe_key'), ('dependency', 'dependency')))):
            raise LedgerError('Ambiguous event identity or payload digest')
        for key in FIELDS - {'priority', 'dependency', 'evidence'}:
            text_value(payload[key], key)
        evidence_ref(payload['evidence'])
        if (payload['kind'] not in {'HANDOFF', 'APPROVAL', 'STOP', 'CHECKPOINT'} or
                type(payload['priority']) is not int or payload['priority'] not in (0, 1, 2, 100) or
                type(row['priority']) is not int or row['priority'] not in (0, 1, 2, 100)):
            raise LedgerError('Invalid event kind or priority')
        if payload['dependency'] is not None:
            text_value(payload['dependency'], 'dependency')
        if payload['kind'] == 'STOP' and (payload['priority'] != 100 or payload['dependency'] is not None or row['priority'] != 100):
            raise LedgerError('Ambiguous STOP payload')
        if row['state'] == 'QUEUED':
            cp = db.execute('SELECT * FROM checkpoints WHERE issue=? AND scope=?', (payload['issue'], payload['scope'])).fetchone()
            if cp is None or any(cp[k] != payload[k] for k in ('checkpoint', 'base', 'head')):
                raise LedgerError('Queued event has stale checkpoint binding')
    if db.execute('SELECT 1 FROM recipients WHERE busy != 0 OR active_event IS NOT NULL').fetchone():
        raise LedgerError('Busy recipient or retained worker slot requires separate resolution')
    history_high = db.execute('SELECT COALESCE(MAX(seq),0) FROM history').fetchone()[0]
    proof = {'format': 'cairn-schema1-copy-proof-v1', 'source_path': str(path),
             'source_identity': _identity(path), 'source_schema': '1', 'schema_sha256': V1_SCHEMA_SHA256,
             'bootstrap_pm': config['pm_task'], 'snapshot_sha256': _digest(snapshot),
             'history_high_water': history_high,
             'extension_config_sha256': _digest({k: v for k, v in config.items() if k not in {'pm_task', 'schema_version'}}),
             'host_isolation': 'NOT_PROVEN_BY_SQLITE'}
    return snapshot, proof


def inspect_v1(source):
    """Read a stable proof, including WAL. This does not grant migration authority."""
    try:
        path = _path(source, existing=True)
        identity = _identity(path)
        with _read(path) as db:
            _, proof = _source_snapshot(db, path)
        if proof['source_identity'] != identity or _identity(path) != identity:
            raise LedgerError('Source identity changed during inspection')
        return proof
    except (OSError, sqlite3.Error) as exc:
        raise LedgerError('Cannot inspect an unambiguous schema-1 source: ' + str(exc)) from exc


def _verify_preservation(db, before, pm_task):
    expected = json.loads(_canonical(before['data']))
    expected['config'] = sorted([[k, '2' if k == 'schema_version' else v] for k, v in expected['config']], key=_canonical)
    actual = _snapshot(db)
    if actual['data'] != expected:
        raise LedgerError('Migration changed preserved source data')
    original_objects = {(r[0], r[1]): r for r in before['schema']}
    current_objects = {(r[0], r[1]): r for r in actual['schema']}
    if any(current_objects.get(key) != value for key, value in original_objects.items()):
        raise LedgerError('Migration changed existing schema objects')
    if Ledger._pm_authority(db) != {'revision': 0, 'task_id': pm_task, 'event_id': None, 'receipt': {'bootstrap': True}}:
        raise LedgerError('Migration changed bootstrap PM authority')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise LedgerError('Prepared output failed integrity/FK verification')
    return _digest(_snapshot(db, TABLES + ('pm_authority',)))


def _append_receipt(db, receipt):
    db.execute('INSERT INTO history(event_id,at,actor,action,detail) VALUES (NULL,?,?,?,?)',
               (time.time(), 'offline-migration-host', 'SCHEMA1_COPY_PREPARED', _canonical(receipt)))


def _read_output(path):
    with _read(path) as db:
        schema = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
        if schema is None or schema[0] != EXPECTED_SCHEMA_VERSION:
            raise LedgerError('Prepared output is not schema 2')
        return {'digest': _digest(_snapshot(db, TABLES + ('pm_authority',))),
                'pm_authority': Ledger._pm_authority(db),
                'history_high_water': db.execute('SELECT COALESCE(MAX(seq),0) FROM history').fetchone()[0]}


def migrate_copy(source, new_destination, expected_proof, evidence):
    """Copy to a never-existing isolated destination; return PREPARED_ONLY proof.

    `evidence` references the host's isolation/review evidence; this library cannot
    verify OS fencing. It preserves opaque adapter config, without rebinding it.
    No incomplete/quarantined output may be activated or retried in place.
    """
    evidence_ref(evidence)
    if not isinstance(expected_proof, dict):
        raise LedgerError('Require independently retained exact source proof')
    expected = _canonical(expected_proof)  # detach mutable caller containers
    created = False
    try:
        src_path = _path(source, existing=True)
        dst_path = _path(new_destination, existing=False)
        identity = _identity(src_path)
        with _read(src_path) as src:
            before, observed = _source_snapshot(src, src_path)
            if _canonical(observed) != expected or observed['source_identity'] != identity:
                raise LedgerError('Stale/ambiguous source proof; reread before preparing')
            with dst_path.open('xb'):
                created = True
            destination_identity = _identity(dst_path)
            with closing(sqlite3.connect(dst_path.as_uri() + '?mode=rw', uri=True, isolation_level=None)) as dst:
                dst.row_factory = sqlite3.Row
                dst.execute('PRAGMA foreign_keys=ON')
                dst.execute('PRAGMA synchronous=FULL')
                src.backup(dst)
                if _snapshot(dst) != before:
                    raise LedgerError('SQLite backup differs from the retained read snapshot')
                dst.execute('BEGIN IMMEDIATE')
                try:
                    _initialize_pm_authority(dst, observed['bootstrap_pm'])
                    dst.execute("UPDATE config SET value='2' WHERE key='schema_version'")
                    content_digest = _verify_preservation(dst, before, observed['bootstrap_pm'])
                    # New connection after backup: detect observed external commits.
                    # This cannot prevent a writer from modifying the source later.
                    if _canonical(inspect_v1(src_path)) != expected or _identity(dst_path) != destination_identity:
                        raise LedgerError('Source or destination moved during copy')
                    modules = {p.name: hashlib.sha256(p.read_bytes().replace(b'\r\n', b'\n')).hexdigest()
                               for p in Path(__file__).resolve().parent.glob('*.py')}
                    audit_receipt = {'status': 'PREPARED_ONLY', 'source_proof': observed,
                                     'prepared_content_sha256': content_digest,
                                     'target_version': __version__, 'target_schema': EXPECTED_SCHEMA_VERSION,
                                     'target_modules_sha256': _digest(modules), 'evidence': evidence,
                                     'live_readiness': False, 'adapter_rebound': False,
                                     'host_fencing': 'NOT_PROVEN_BY_SQLITE'}
                    _append_receipt(dst, audit_receipt)
                    dst.commit()
                except BaseException:
                    dst.rollback()
                    raise
        if _identity(dst_path) != destination_identity:
            raise LedgerError('Destination identity changed after commit')
        output = _read_output(dst_path)
        return dict(audit_receipt, output_path=str(dst_path), output_identity=destination_identity,
                    output_digest=output['digest'], output_history_high_water=output['history_high_water'])
    except Exception as exc:
        suffix = '; output quarantined, never reuse/activate this destination' if created else '; no destination accepted'
        raise LedgerError('Copy preparation refused: ' + str(exc) + suffix) from exc
