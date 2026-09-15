"""Host-only adapter preparation on a new copy, never on the core-proved source.

Uses private copy/read helpers of the exact pinned core. No worker command, live
activation, OS isolation or automatic credential/registry repair is provided.
"""
import hmac
import json
import sqlite3
import time
from contextlib import closing
from pathlib import Path

from comms_ledger import migration as core
from comms_ledger.ledger import Ledger, evidence_ref
from .package import verify_package
from .recovery import proof as recovery_proof
from .store import (Rejected, canonical, credential_hash, digest, put_config,
                    validate_entries, validate_pm_entries)

_LEGACY_PACKAGE = dict(version='0.1.0', source_commit='f31726234c43c2ded4716c0998a8e4475ad25c19',
    tag='communication-ledger-v0.1.0', tag_object='065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f',
    package_tree='d21f0346b18f01f0bab41566200db88b6ac78d3a')
_OUTPUT_FIELDS = {'output_path', 'output_identity', 'output_digest', 'output_history_high_water'}
_TABLES = core.TABLES + ('pm_authority',)


def _config(db, key):
    row = db.execute('SELECT value FROM config WHERE key=?', ('adapter:' + key,)).fetchone()
    if not row:
        raise Rejected('Missing source adapter metadata: ' + key)
    value = json.loads(row[0])
    if canonical(value) != row[0]:
        raise Rejected('Ambiguous/noncanonical source metadata: ' + key)
    return value


def _validate_source(db, source, expected, project, owner_token, revision):
    if type(revision) is not int or revision < 0:
        raise Rejected('Require exact nonnegative registry CAS')
    if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or db.execute('PRAGMA foreign_key_check').fetchall():
        raise Rejected('Source integrity/FK check failed')
    snapshot = core._snapshot(db, _TABLES)
    high = db.execute('SELECT COALESCE(MAX(seq),0) FROM history').fetchone()[0]
    if (expected.get('status') != 'PREPARED_ONLY' or expected.get('live_readiness') is not False
            or expected.get('adapter_rebound') is not False or expected.get('target_schema') != '2'
            or expected.get('target_version') != '0.2.0'
            or expected.get('output_path') != str(source)
            or expected.get('output_identity') != core._identity(source)
            or expected.get('output_digest') != core._digest(snapshot)
            or type(expected.get('output_history_high_water')) is not int
            or expected['output_history_high_water'] != high):
        raise Rejected('Core PREPARED_ONLY proof does not bind this exact source')
    receipt = db.execute('SELECT action,detail FROM history WHERE seq=?', (high,)).fetchone()
    if (not receipt or receipt['action'] != 'SCHEMA1_COPY_PREPARED' or
            canonical(json.loads(receipt['detail'])) != canonical({k: v for k, v in expected.items() if k not in _OUTPUT_FIELDS})):
        raise Rejected('Missing or mismatched core migration receipt')
    lock = json.loads(Path(__file__).with_name('package.lock.json').read_text(encoding='utf-8'))
    if expected.get('target_modules_sha256') != digest(lock['module_lf_sha256']):
        raise Rejected('Core preparation came from different module content')
    schema = db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()
    registry_schema = _config(db, 'registry_schema')
    if (schema is None or schema[0] != '2' or _config(db, 'package') != _LEGACY_PACKAGE
            or type(registry_schema) is not int or registry_schema != 2):
        raise Rejected('Unsupported old package binding or registry schema')
    if _config(db, 'project') != project:
        raise Rejected('Project differs from the proof-bound source')
    owner_hash = _config(db, 'owner_hash')
    if not isinstance(owner_hash, str) or not hmac.compare_digest(credential_hash(owner_token), owner_hash):
        raise Rejected('Separate source owner credential is required')
    registry = _config(db, 'registry')
    if (not isinstance(registry, dict) or set(registry) != {'revision', 'entries'}
            or type(registry['revision']) is not int or registry['revision'] != revision):
        raise Rejected('Source registry CAS moved or is malformed')
    entries = registry['entries']
    # Validate a preserved snapshot, not a newly bootstrapped generation-one roster.
    validate_entries(entries, entries, owner_hash)
    if any(e['project'] != project for e in entries):
        raise Rejected('Registry entry project mismatch')
    authority = Ledger._pm_authority(db)
    if (authority != {'revision': 0, 'task_id': expected['source_proof']['bootstrap_pm'],
                      'event_id': None, 'receipt': {'bootstrap': True}} or
            [e['task_id'] for e in entries if e['role'] == 'PM'] != [authority['task_id']]):
        raise Rejected('Source must preserve the legacy unique bootstrap PM')
    validate_pm_entries(db, Ledger, entries)
    for row in db.execute("SELECT key,value FROM config WHERE key LIKE 'adapter:attest:%' OR key LIKE 'adapter:reconcile:%'"):
        record = json.loads(row['value'])
        field = 'revision' if row['key'].startswith('adapter:attest:') else 'registry_revision'
        if (not isinstance(record, dict) or canonical(record) != row['value']
                or type(record.get(field)) is not int or not 0 <= record[field] <= revision):
            raise Rejected('Ambiguous/future reconcile or attestation revision')
    return snapshot, registry


def _verify_preservation(db, before, new_registry, package):
    expected = json.loads(canonical(before))
    changed = {'adapter:registry': canonical(new_registry), 'adapter:package': canonical(package)}
    expected['data']['config'] = sorted([[k, changed.get(k, v)] for k, v in expected['data']['config']], key=core._canonical)
    if core._snapshot(db, _TABLES) != expected:
        raise Rejected('Adapter preparation altered data beyond package metadata and registry CAS')
    return core._digest(expected)


def _append_audit(db, receipt):
    db.execute('INSERT INTO history(event_id,at,actor,action,detail) VALUES (NULL,?,?,?,?)',
               (time.time(), 'offline-adapter-owner', 'ADAPTER_COPY_PREPARED', canonical(receipt)))


def migrate_copy(source, new_project_root, expected_core_proof, *, project, owner_token,
                 expected_registry_revision, evidence):
    """Validate owner/project/CAS and rebind only a NEW isolated ledger.sqlite.

    The host must independently retain the core proof and protect both directories.
    Read-only snapshots detect observed drift, not future writes or OS identities.
    All failed/crashed destination copies are quarantined and never retried in place.
    """
    evidence_ref(evidence)
    if not isinstance(expected_core_proof, dict):
        raise Rejected('Require the exact independently retained core proof')
    expected = json.loads(canonical(expected_core_proof))
    created = False
    try:
        package = verify_package()
        src_path = core._path(source, existing=True)
        dst_path = core._path(Path(new_project_root) / 'ledger.sqlite', existing=False)
        with core._read(src_path) as src:
            before, registry = _validate_source(src, src_path, expected, project, owner_token, expected_registry_revision)
            with dst_path.open('xb'):
                created = True
            destination_identity = core._identity(dst_path)
            with closing(sqlite3.connect(dst_path.as_uri()+'?mode=rw', uri=True, isolation_level=None)) as dst:
                dst.row_factory = sqlite3.Row
                dst.execute('PRAGMA foreign_keys=ON')
                dst.execute('PRAGMA synchronous=FULL')
                src.backup(dst)
                if core._snapshot(dst, _TABLES) != before:
                    raise Rejected('Backup differs from the retained source snapshot')
                dst.execute('BEGIN IMMEDIATE')
                try:
                    new_registry = dict(revision=expected_registry_revision + 1, entries=registry['entries'])
                    put_config(dst, 'package', package)
                    put_config(dst, 'registry', new_registry)
                    content_digest = _verify_preservation(dst, before, new_registry, package)
                    # Fresh source read before accepting the copy; no claim of fencing.
                    with core._read(src_path) as fresh:
                        _validate_source(fresh, src_path, expected, project, owner_token, expected_registry_revision)
                    if core._identity(dst_path) != destination_identity or verify_package() != package:
                        raise Rejected('Destination identity or target package changed')
                    receipt = {'status': 'PREPARED_ONLY', 'live_readiness': False,
                               'source_core_proof_sha256': digest(expected), 'source_project': project,
                               'source_package': _LEGACY_PACKAGE, 'target_package': package,
                               'registry_revision_before': expected_registry_revision,
                               'registry_revision_after': new_registry['revision'],
                               'preserved_entries_sha256': digest(registry['entries']),
                               'prepared_content_sha256': content_digest, 'evidence': evidence,
                               'host_fencing': 'NOT_PROVEN', 'activation_authorized': False}
                    _append_audit(dst, receipt)
                    dst.commit()
                except BaseException:
                    dst.rollback()
                    raise
        if core._identity(dst_path) != destination_identity:
            raise Rejected('Destination changed after commit')
        return dict(receipt, output_path=str(dst_path), output_identity=destination_identity,
                    output_proof=recovery_proof(dst_path))
    except Exception as exc:
        suffix = '; destination quarantined, never reuse/activate it' if created else '; no destination accepted'
        raise Rejected('Adapter copy refused: ' + str(exc) + suffix) from exc
