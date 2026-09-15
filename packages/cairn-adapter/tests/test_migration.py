"""Isolated legacy adapter -> core copy -> adapter copy contract."""
import copy
import hashlib
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path
from unittest.mock import patch

from comms_ledger import migration as core_migration
from cairn_adapter import Adapter, Owner, Store, Rejected, credential_hash
from cairn_adapter import migration
from cairn_adapter.governance import require_attestation
from cairn_adapter.package import verify_package
from cairn_adapter.recovery import backup, proof, restore
from cairn_adapter.store import canonical, digest, get_config, COMMANDS
from test_adapter import TOKENS, entry, TestVerifier, BINDING

LEGACY_PACKAGE = dict(version='0.1.0', source_commit='f31726234c43c2ded4716c0998a8e4475ad25c19',
    tag='communication-ledger-v0.1.0', tag_object='065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f',
    package_tree='d21f0346b18f01f0bab41566200db88b6ac78d3a')


def prepare_fixture(root, changes=None):
    """Frozen accepted v1 DDL and explicit synthetic old metadata, no old install."""
    root = Path(root)
    legacy = root / 'legacy'
    legacy.mkdir()
    source = legacy / 'ledger.sqlite'
    entries = [entry('pm', role='PM'), entry('old', role='Lead'), entry('new')]
    entries[1]['generation'] = 2
    fresh = TestVerifier().verify(BINDING, 'adapter')
    payload = dict(fresh, source_task='old', target_task='new', dedupe_key='legacy', kind='HANDOFF',
                   priority=1, dependency=None, next_action='Synthetic handoff')
    raw = canonical(payload)
    event_digest = hashlib.sha256(raw.encode()).hexdigest()
    config = {'schema_version': '1', 'pm_task': 'pm', 'adapter:project': canonical('synthetic/repo'),
        'adapter:owner_hash': canonical(credential_hash(TOKENS['owner'])),
        'adapter:package': canonical(LEGACY_PACKAGE), 'adapter:registry_schema': '2',
        'adapter:registry': canonical(dict(revision=7, entries=entries)),
        'adapter:event:legacy': canonical(dict(source=dict(task_id='old', generation=2), target=dict(task_id='new', generation=1))),
        'adapter:attest:retire:legacy': canonical(dict(revision=7, digest='a'*64, evidence='synthetic://old-approval')),
        'adapter:reconcile:legacy': canonical(dict(event_digest=event_digest, generation=1, registry_revision=7,
            checkpoint_revision=1, binding=digest(fresh), owner='new@1'))}
    config.update(changes or {})
    ddl = Path(__file__).resolve().parents[2] / 'communication-ledger/tests/fixtures/schema1.sql'
    with closing(sqlite3.connect(source)) as db:
        db.executescript(ddl.read_text(encoding='utf-8'))
        db.executemany('INSERT INTO config VALUES (?,?)', config.items())
        db.execute("INSERT INTO checkpoints VALUES ('10','adapter','cp-head-1','base-1','head-1',1)")
        db.execute("INSERT INTO recipients VALUES ('new',0,NULL)")
        db.execute("INSERT INTO events(id,dedupe_key,payload,digest,target,state,priority,eligible_at,created_at,updated_at,worker_owner) VALUES ('legacy','legacy',?,?,'new','COMPLETED',1,0,0,0,'new@1')", (raw, event_digest))
        db.execute("INSERT INTO history(event_id,at,actor,action,detail) VALUES ('legacy',0,'new','COMPLETED','{}')")
        db.commit()
    core_root = root / 'core-prepared'
    core_root.mkdir()
    core_path = core_root / 'ledger.sqlite'
    core_proof = core_migration.migrate_copy(source, core_path, core_migration.inspect_v1(source), 'synthetic://isolated-core-copy')
    return core_path, core_proof, entries


class AdapterMigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source, self.core_proof, self.entries = prepare_fixture(self.root)
        self.destination = self.root / 'adapter-prepared'
        self.destination.mkdir()

    def migrate(self, **changes):
        args = dict(project='synthetic/repo', owner_token=TOKENS['owner'], expected_registry_revision=7,
                    evidence='synthetic://owner-reviewed-isolated-adapter-copy')
        args.update(changes)
        return migration.migrate_copy(self.source, self.destination, self.core_proof, **args)

    def reject_no_write(self, call):
        before = proof(self.source)
        with self.assertRaises((Rejected, ValueError)):
            call()
        self.assertEqual(proof(self.source), before)
        self.assertFalse((self.destination / 'ledger.sqlite').exists())

    def identity(self, credential):
        for e in self.entries:
            if credential_hash(credential) == e['credential_hash']:
                return dict(task_id=e['task_id'], session_id=e['session_id'], generation=e['generation'])
        return None

    def test_copy_reopens_and_preserves_entries_history_and_source(self):
        before = proof(self.source)
        with self.assertRaises(Rejected):
            Store(self.source.parent, 'synthetic/repo')
        result = self.migrate()
        self.assertEqual(proof(self.source), before)
        self.assertEqual(result['status'], 'PREPARED_ONLY')
        self.assertFalse(result['live_readiness'])
        store = Store(self.destination, 'synthetic/repo')
        with store.transaction() as (db, ledger):
            registry = get_config(db, 'registry')
            self.assertEqual(registry, dict(revision=8, entries=self.entries))
            self.assertEqual(ledger.pm_authority()['task_id'], 'pm')
            self.assertEqual(get_config(db, 'package'), verify_package())
            self.assertEqual([r['action'] for r in ledger.history()], ['COMPLETED', 'SCHEMA1_COPY_PREPARED', 'ADAPTER_COPY_PREPARED'])
        adapter = Adapter(store, TestVerifier(), host_identity=self.identity)
        self.assertEqual(adapter.execute(TOKENS['new'], 1, 8, 'adapter', 'get', {'event_id': 'legacy'})['state'], 'COMPLETED')
        self.assertFalse({'migrate_copy', 'inspect_v1'} & COMMANDS)
        saved = self.root / 'adapter-backup.sqlite'
        retained = backup(store.path, saved)
        self.assertEqual(retained, result['output_proof'])
        restore(saved, self.root / 'restored', retained, 'synthetic/repo')
        restored = Store(self.root / 'restored', 'synthetic/repo')
        self.assertEqual(proof(restored.path), retained)
        if os.environ.get('CAIRN_TEST_EVIDENCE_DIR'):
            output = Path(os.environ['CAIRN_TEST_EVIDENCE_DIR'])
            output.mkdir(parents=True, exist_ok=True)
            (output / 'adapter-migration-proof.json').write_text(json.dumps(dict(result, synthetic_only=True), indent=2)+'\n', encoding='utf-8')

    def test_wrong_owner_project_revision_and_core_proof_are_zero_write(self):
        for args in ({'owner_token': TOKENS['old']}, {'project': 'wrong/project'},
                     {'expected_registry_revision': 6}, {'expected_registry_revision': True}):
            self.reject_no_write(lambda: self.migrate(**args))
        original = copy.deepcopy(self.core_proof)
        for key, bad in (('output_digest', '0'*64), ('output_path', str(self.root / 'other.sqlite')),
                         ('status', 'COMPLETE'), ('target_modules_sha256', '0'*64),
                         ('output_identity', dict(original['output_identity'], links=True))):
            self.core_proof = dict(original, **{key: bad})
            self.reject_no_write(self.migrate)
        self.core_proof = original

    def test_old_binding_unknown_registry_and_future_approvals_are_refused(self):
        cases = [{'adapter:package': canonical(dict(LEGACY_PACKAGE, version='9'))},
                 {'adapter:registry_schema': '99'},
                 {'adapter:registry': canonical(dict(revision=7, entries=[self.entries[0],self.entries[0]]))},
                 {'adapter:attest:retire:legacy': canonical(dict(revision=8, digest='a'*64, evidence='synthetic://future'))}]
        for i, changes in enumerate(cases):
            place = self.root / ('case-'+str(i))
            place.mkdir()
            self.source, self.core_proof, _ = prepare_fixture(place, changes)
            self.reject_no_write(self.migrate)

    def test_old_generation_reconcile_and_attestation_stay_invalid(self):
        self.migrate()
        store = Store(self.destination, 'synthetic/repo')
        adapter = Adapter(store, TestVerifier(), host_identity=self.identity)
        before = proof(store.path)
        for generation, revision in ((1,7), (2,8)):
            with self.assertRaises(Rejected):
                adapter.execute(TOKENS['new'], generation, revision, 'adapter', 'get', {'event_id': 'legacy'})
        with store.transaction() as (db, ledger):
            self.assertEqual(get_config(db,'reconcile:legacy')['registry_revision'], 7)
            with self.assertRaises(Rejected):
                require_attestation(db,'retire','legacy',{'digest':'a'*64},8)
        with self.assertRaisesRegex(Rejected, 'current principal reconciliation'):
            adapter.execute(TOKENS['new'], 1, 8, 'adapter', 'complete',
                            dict(event_id='legacy', worker_token='old-token', evidence='synthetic://old'))
        self.assertEqual(proof(store.path), before)

    def test_destination_collision_and_source_drift_are_refused(self):
        target = self.destination / 'ledger.sqlite'
        target.write_bytes(b'keep')
        with self.assertRaises(Rejected):
            self.migrate()
        self.assertEqual(target.read_bytes(), b'keep')
        target.unlink()
        with closing(sqlite3.connect(self.source)) as db:
            db.execute("INSERT INTO config VALUES ('extra','changed')")
            db.commit()
        self.reject_no_write(self.migrate)

    def test_failure_after_metadata_change_rolls_back_and_source_is_preserved(self):
        before = proof(self.source)
        with patch.object(migration, '_append_audit', side_effect=RuntimeError('synthetic failure')):
            with self.assertRaises(Rejected):
                self.migrate()
        self.assertEqual(proof(self.source), before)
        partial = self.destination / 'ledger.sqlite'
        self.assertEqual(proof(partial), before)
        with self.assertRaises(Rejected):
            Store(self.destination, 'synthetic/repo')

    def test_wal_external_commit_during_copy_rolls_back_destination(self):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute('PRAGMA journal_mode=WAL')
        before = proof(self.source)
        original = migration._verify_preservation
        def external_commit(*args):
            result = original(*args)
            with closing(sqlite3.connect(self.source)) as db:
                db.execute("INSERT INTO config VALUES ('external','separate-writer')")
                db.commit()
            return result
        with patch.object(migration, '_verify_preservation', external_commit):
            with self.assertRaises(Rejected):
                self.migrate()
        self.assertEqual(proof(self.destination / 'ledger.sqlite'), before)
        self.assertEqual(proof(self.source)['package'], LEGACY_PACKAGE)

    def test_real_crash_leaves_old_metadata_and_no_adapter_receipt(self):
        proof_file = self.root / 'core-proof.json'
        proof_file.write_text(json.dumps(self.core_proof), encoding='utf-8')
        script = """import os,sys,json
from pathlib import Path
from cairn_adapter import migration
def crash(*args): os._exit(74)
migration._append_audit=crash
migration.migrate_copy(sys.argv[1],sys.argv[2],json.loads(Path(sys.argv[3]).read_text()),project='synthetic/repo',owner_token=sys.argv[4],expected_registry_revision=7,evidence='synthetic://crash')
"""
        before = proof(self.source)
        child_env = dict(os.environ)
        child_env['PYTHONPATH'] = os.pathsep.join((str(Path(__file__).resolve().parents[1]),
                                                 str(Path(core_migration.__file__).resolve().parents[1])))
        result = subprocess.run([sys.executable,'-c',script,str(self.source),str(self.destination),str(proof_file),TOKENS['owner']],
                                capture_output=True, env=child_env)
        self.assertEqual(result.returncode,74,result.stderr)
        self.assertEqual(proof(self.source),before)
        self.assertEqual(proof(self.destination / 'ledger.sqlite'),before)

    def test_concurrent_copies_have_one_destination_winner(self):
        def attempt(_):
            try: return self.migrate()['status']
            except Rejected: return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(attempt,range(2)))
        self.assertCountEqual(results,['PREPARED_ONLY','rejected'])


if __name__ == '__main__':
    unittest.main()
