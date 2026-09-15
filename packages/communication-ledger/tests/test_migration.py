"""Synthetic isolated copies only; no live ledger or adapter activation."""
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

from comms_ledger import Ledger, LedgerError
from comms_ledger.api import COMMANDS
from comms_ledger import migration

FIXTURE = Path(__file__).parent / 'fixtures' / 'schema1.sql'


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / 'schema1.sqlite'
        self.destination = self.root / 'prepared.sqlite'
        with closing(sqlite3.connect(self.source)) as db:
            db.executescript(FIXTURE.read_text(encoding='utf-8'))
            db.executemany('INSERT INTO config VALUES (?,?)', [
                ('schema_version', '1'), ('pm_task', 'synthetic-pm'),
                ('adapter:project', '"synthetic/project"'),
                ('adapter:package', '{"version":"0.1.0"}'),
                ('adapter:registry', '{"revision":7,"entries":[]}')])
            db.execute("INSERT INTO checkpoints VALUES ('15','scope','cp','base','head',1)")
            db.commit()

    def change(self, sql, parameters=()):
        with closing(sqlite3.connect(self.source)) as db:
            db.execute(sql, parameters)
            db.commit()

    def event(self, state='QUEUED'):
        payload = dict(dedupe_key='fixture', source_task='synthetic-pm', target_task='synthetic-worker',
                       issue='15', scope='scope', checkpoint='cp', base='base', head='head',
                       kind='HANDOFF', priority=1, dependency=None, evidence='synthetic://fixture', next_action='Read back')
        raw = json.dumps(payload, sort_keys=True, separators=(',', ':'))
        self.change('INSERT INTO recipients VALUES (?,0,NULL)', ('synthetic-worker',))
        self.change('INSERT INTO events(id,dedupe_key,payload,digest,target,state,priority,eligible_at,created_at,updated_at) VALUES (?,?,?,?,?,?,1,0,0,0)',
                    ('e', 'fixture', raw, hashlib.sha256(raw.encode()).hexdigest(), 'synthetic-worker', state))
        self.change("INSERT INTO history(event_id,at,actor,action,detail) VALUES ('e',0,'synthetic-pm','QUEUED','{}')")

    def raw(self, path=None):
        with closing(sqlite3.connect(path or self.source)) as db:
            return '\n'.join(db.iterdump())

    def migrate(self, proof=None):
        return migration.migrate_copy(self.source, self.destination,
                                      proof or migration.inspect_v1(self.source), 'synthetic://isolated-fixture')

    def test_empty_copy_preserves_bootstrap_and_is_host_only(self):
        before = self.raw()
        proof = migration.inspect_v1(self.source)
        result = self.migrate(proof)
        self.assertEqual(before, self.raw())
        self.assertEqual(result['status'], 'PREPARED_ONLY')
        self.assertFalse(result['live_readiness'])
        self.assertEqual(result['source_proof'], proof)
        self.assertEqual(Ledger(self.destination, pm_task='synthetic-pm').pm_authority()['revision'], 0)
        self.assertFalse({'migrate_copy', 'inspect_v1'} & set(COMMANDS))
        with self.assertRaises(LedgerError):
            Ledger(self.source)

    def test_queued_and_completed_copies_preserve_history_and_adapter_metadata(self):
        self.event()
        for state in ('QUEUED', 'COMPLETED'):
            self.change('UPDATE events SET state=? WHERE id=\'e\'', (state,))
            self.destination = self.root / (state + '.sqlite')
            before = self.raw()
            result = self.migrate()
            self.assertEqual(self.raw(), before)
            ledger = Ledger(self.destination)
            history = ledger.history()
            self.assertEqual([h['action'] for h in history], ['QUEUED', 'SCHEMA1_COPY_PREPARED'])
            self.assertEqual(history[0]['seq'], 1)
            self.assertEqual(ledger.get('e')['state'], state)
            with closing(sqlite3.connect(self.destination)) as db:
                self.assertEqual(db.execute("SELECT value FROM config WHERE key='adapter:package'").fetchone()[0], '{"version":"0.1.0"}')
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute("UPDATE config SET value='other' WHERE key='pm_task'")
                with self.assertRaises(sqlite3.IntegrityError):
                    db.execute('DELETE FROM pm_authority')
            saved = self.root / (state + '-restored.sqlite')
            with closing(sqlite3.connect(self.destination)) as src, closing(sqlite3.connect(saved)) as dst:
                src.backup(dst)
            self.assertEqual(Ledger(saved).history(), history)
            self.assertEqual(migration._read_output(saved)['digest'], result['output_digest'])
            if state == 'COMPLETED' and os.environ.get('CAIRN_MIGRATION_EVIDENCE_DIR'):
                output = Path(os.environ['CAIRN_MIGRATION_EVIDENCE_DIR'])
                output.mkdir(parents=True, exist_ok=True)
                (output / 'migration-success-proof.json').write_text(json.dumps(
                    dict(result, synthetic_only=True, restored_digest=migration._read_output(saved)['digest']),
                    indent=2) + '\n', encoding='utf-8')

    def test_wal_commits_are_included_in_consistent_snapshot(self):
        with closing(sqlite3.connect(self.source, isolation_level=None)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
            writer.execute('PRAGMA wal_autocheckpoint=0')
            writer.execute("INSERT INTO config VALUES ('fixture:wal','committed')")
            self.assertGreater(Path(str(self.source) + '-wal').stat().st_size, 0)
            self.migrate()
            with closing(sqlite3.connect(self.destination)) as db:
                self.assertEqual(db.execute("SELECT value FROM config WHERE key='fixture:wal'").fetchone()[0], 'committed')

    def test_stale_proof_and_source_identity_are_refused_before_creation(self):
        proof = migration.inspect_v1(self.source)
        self.change("INSERT INTO config VALUES ('fixture:moved','yes')")
        before = self.raw()
        with self.assertRaises(LedgerError):
            self.migrate(proof)
        self.assertEqual(self.raw(), before)
        self.assertFalse(self.destination.exists())
        proof = migration.inspect_v1(self.source)
        proof['source_identity']['inode'] += 1
        with self.assertRaises(LedgerError):
            self.migrate(proof)
        self.assertFalse(self.destination.exists())

    def test_unknown_schema_corruption_missing_pm_and_unknown_objects(self):
        for command in ("UPDATE config SET value='99' WHERE key='schema_version'",
                        "DELETE FROM config WHERE key='pm_task'", 'CREATE TABLE extra(x)',
                        'CREATE TRIGGER unexpected AFTER INSERT ON config BEGIN SELECT 1; END'):
            with self.subTest(command=command):
                original = self.source.read_bytes()
                self.change(command)
                before = self.raw()
                with self.assertRaises(LedgerError):
                    migration.inspect_v1(self.source)
                self.assertEqual(self.raw(), before)
                self.source.write_bytes(original)
        self.source.write_bytes(b'not a SQLite database')
        with self.assertRaises(LedgerError):
            migration.inspect_v1(self.source)

    def test_inflight_leases_slots_busy_and_ambiguous_events_are_refused(self):
        self.event()
        for sql in ("UPDATE events SET state='SENT'", "UPDATE events SET state='ACKED'",
                    "UPDATE events SET state='STARTED'", "UPDATE events SET state='UNKNOWN'",
                    "UPDATE events SET worker_token='old-capability'", 'UPDATE events SET worker_until=0',
                    'UPDATE events SET delivery_until=0', 'UPDATE events SET ack_deadline=0',
                    "UPDATE events SET delivery_token='old-delivery'", 'UPDATE recipients SET busy=1',
                    "UPDATE recipients SET active_event='e'", "UPDATE checkpoints SET head='moved'"):
            with self.subTest(sql=sql):
                original = self.source.read_bytes()
                self.change(sql)
                before = self.raw()
                with self.assertRaises(LedgerError):
                    self.migrate()
                self.assertEqual(self.raw(), before)
                self.assertFalse(self.destination.exists())
                self.source.write_bytes(original)

    def test_destination_collision_alias_and_parent_links_are_refused(self):
        proof = migration.inspect_v1(self.source)
        self.destination.write_bytes(b'keep existing')
        with self.assertRaises(LedgerError):
            self.migrate(proof)
        self.assertEqual(self.destination.read_bytes(), b'keep existing')
        with self.assertRaises(LedgerError):
            migration.migrate_copy(self.source, self.source, proof, 'synthetic://same')
        hardlink = self.root / 'alias.sqlite'
        os.link(self.source, hardlink)
        with self.assertRaises(LedgerError):
            migration.inspect_v1(hardlink)
        with self.assertRaises(LedgerError):
            migration.inspect_v1(self.source)
        hardlink.unlink()
        with self.assertRaises(LedgerError):
            migration.inspect_v1(self.root / 'hidden-link' / '..' / self.source.name)
        # Symlink creation on Windows can require OS privileges. Test the boundary
        # with a real directory link on POSIX and the reparse predicate on all hosts.
        if os.name != 'nt':
            alias = self.root / 'linked'
            alias.symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(LedgerError):
                migration.inspect_v1(alias / self.source.name)
        with patch.object(migration, '_is_reparse', return_value=True):
            with self.assertRaises(LedgerError):
                migration.inspect_v1(self.source)

    def test_external_commit_during_copy_is_detected_without_migration_source_writes(self):
        original = migration._verify_preservation
        def externally_changed(*args):
            result = original(*args)
            self.change("INSERT INTO config VALUES ('fixture:external','separate-writer')")
            return result
        with closing(sqlite3.connect(self.source)) as writer:
            writer.execute('PRAGMA journal_mode=WAL')
        with patch.object(migration, '_verify_preservation', externally_changed):
            with self.assertRaises(LedgerError):
                self.migrate()
        with closing(sqlite3.connect(self.destination)) as db:
            self.assertEqual(db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()[0], '1')
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name='pm_authority'").fetchone())

    def test_failures_after_backup_during_ddl_and_before_receipt_are_atomic(self):
        for stage in ('_initialize_pm_authority', '_verify_preservation', '_append_receipt'):
            self.destination = self.root / (stage + '.sqlite')
            original = self.raw()
            def fail(*args, **kwargs):
                if stage == '_initialize_pm_authority':
                    args[0].execute('CREATE TABLE partial(x)')
                raise RuntimeError('synthetic injected failure')
            with patch.object(migration, stage, fail):
                with self.assertRaises(LedgerError):
                    self.migrate()
            self.assertEqual(self.raw(), original)
            with closing(sqlite3.connect(self.destination)) as db:
                self.assertEqual(db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()[0], '1')
                self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('partial','pm_authority')").fetchone())
            with self.assertRaises(LedgerError):
                self.migrate()

    def test_process_crash_during_upgrade_leaves_no_prepared_receipt(self):
        script = """import os,sys
from comms_ledger import migration
def crash(db, *args):
    db.execute('CREATE TABLE partial(x)')
    os._exit(73)
migration._initialize_pm_authority = crash
migration.migrate_copy(sys.argv[1],sys.argv[2],migration.inspect_v1(sys.argv[1]),'synthetic://crash')
"""
        before = self.raw()
        result = subprocess.run([sys.executable, '-c', script, str(self.source), str(self.destination)], capture_output=True)
        self.assertEqual(result.returncode, 73, result.stderr)
        self.assertEqual(self.raw(), before)
        with closing(sqlite3.connect(self.destination)) as db:
            self.assertEqual(db.execute("SELECT value FROM config WHERE key='schema_version'").fetchone()[0], '1')
            self.assertFalse(db.execute("SELECT 1 FROM sqlite_master WHERE name IN ('partial','pm_authority')").fetchone())

    def test_concurrent_destination_claims_have_one_winner(self):
        proof = migration.inspect_v1(self.source)
        def attempt(_):
            try:
                return self.migrate(proof)['status']
            except LedgerError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, range(2)))
        self.assertCountEqual(outcomes, ['PREPARED_ONLY', 'rejected'])


if __name__ == '__main__':
    unittest.main()
