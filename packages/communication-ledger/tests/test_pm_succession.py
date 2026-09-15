import hashlib
import json
import sqlite3
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from comms_ledger import Ledger, LedgerError


class PMSuccessionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'ledger.sqlite'
        self.ledger = Ledger(self.path, pm_task='pm')
        self.ledger.checkpoint('pm', 'issue', 'scope', 'cp', 'base', 'head', 0, 'synthetic://cp')
        self.event = self.ledger.enqueue(dict(dedupe_key='pm-handoff', source_task='pm',
            target_task='next-pm', issue='issue', scope='scope', checkpoint='cp', base='base', head='head',
            kind='HANDOFF', priority=1, dependency=None, evidence='synthetic://plan', next_action='Read back'))['id']
        delivery = self.ledger.claim('next-pm', 'dispatcher')
        self.delivery_token = delivery['delivery_token']
        self.ledger.sent(self.event, self.delivery_token, 'synthetic://sent')
        self.worker_token = self.ledger.ack(self.event, 'next-pm', 'next-pm@1', 'synthetic://ack')['worker_token']
        self.ledger.start(self.event, self.worker_token, 'synthetic://start')
        self.ledger.complete(self.event, self.worker_token, 'synthetic://completed')

    def arguments(self, **overrides):
        args = dict(actor='pm', event_id=self.event, expected_revision=0, predecessor='pm', successor='next-pm',
                    predecessor_generation=1, successor_generation=2, checkpoint_revision=1,
                    registry_revision=3, review_digest='a'*64, evidence='synthetic://owner-reviewed')
        args.update(overrides)
        return args

    def state(self):
        with closing(sqlite3.connect(self.path)) as db:
            return hashlib.sha256('\n'.join(db.iterdump()).encode()).hexdigest()

    def test_succession_preserves_bootstrap_revokes_old_privilege_and_tokens(self):
        result = self.ledger.succeed_pm(**self.arguments())
        self.assertEqual(result['task_id'], 'next-pm')
        self.assertEqual(result['revision'], 1)
        with closing(sqlite3.connect(self.path)) as db:
            self.assertEqual(db.execute("SELECT value FROM config WHERE key='pm_task'").fetchone()[0], 'pm')
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute("UPDATE config SET value='next-pm' WHERE key='pm_task'")
            with self.assertRaises(sqlite3.IntegrityError):
                db.execute('DELETE FROM pm_authority')
        for action in (
            lambda: self.ledger.set_busy('pm', 'other', True, 'synthetic://stale-pm'),
            lambda: self.ledger.start(self.event, self.worker_token, 'synthetic://old-token'),
            lambda: self.ledger.sent(self.event, self.delivery_token, 'synthetic://old-delivery'),
        ):
            before = self.state()
            with self.assertRaises(LedgerError):
                action()
            self.assertEqual(self.state(), before)
        self.ledger.set_busy('next-pm', 'other', True, 'synthetic://new-pm')
        self.assertEqual(Ledger(self.path, pm_task='pm').pm_authority(), result)
        with self.assertRaises(LedgerError):
            Ledger(self.path, pm_task='next-pm')

    def test_stale_revision_identity_checkpoint_and_proof_are_zero_write(self):
        for overrides in ({'expected_revision': 1}, {'actor': 'other'}, {'predecessor': 'other'},
                          {'successor': 'other'}, {'predecessor_generation': True},
                          {'successor_generation': 0}, {'checkpoint_revision': 2},
                          {'review_digest': 'not-a-digest'}, {'registry_revision': -1}):
            before = self.state()
            with self.assertRaises(LedgerError):
                self.ledger.succeed_pm(**self.arguments(**overrides))
            self.assertEqual(self.state(), before)

    def test_outstanding_work_and_stale_binding_refuse_succession(self):
        p = self.ledger.get(self.event)['payload']
        p.update(dedupe_key='outstanding', target_task='other')
        blocked = self.ledger.enqueue(p)['id']
        before = self.state()
        with self.assertRaises(LedgerError):
            self.ledger.succeed_pm(**self.arguments())
        self.assertEqual(self.state(), before)
        self.ledger.terminate(blocked, 'pm', 'BLOCKED', 'synthetic://blocked')
        with self.assertRaises(LedgerError):
            self.ledger.succeed_pm(**self.arguments())
        self.ledger.checkpoint('pm', 'issue', 'scope', 'moved', 'base', 'head2', 1, 'synthetic://moved')
        with self.assertRaises(LedgerError):
            self.ledger.succeed_pm(**self.arguments())

    def test_cas_race_has_one_winner_and_one_authority_receipt(self):
        def attempt(_):
            try:
                return self.ledger.succeed_pm(**self.arguments())['revision']
            except LedgerError:
                return 'rejected'
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(attempt, range(2)))
        self.assertCountEqual(results, [1, 'rejected'])
        self.assertEqual(len([h for h in self.ledger.history() if h['action'] == 'PM_SUCCEEDED']), 1)

    def test_backup_restart_preserves_authority_and_exact_receipt(self):
        expected = self.ledger.succeed_pm(**self.arguments())
        destination = Path(self.temp.name) / 'recovery.sqlite'
        with closing(sqlite3.connect(self.path)) as src, closing(sqlite3.connect(destination)) as dst:
            src.backup(dst)
        restored = Ledger(destination, pm_task='pm')
        self.assertEqual(restored.pm_authority(), expected)
        self.assertEqual(restored.history(), self.ledger.history())
        with self.assertRaises(LedgerError):
            restored.succeed_pm(**self.arguments())
        with self.assertRaises(LedgerError):
            restored.set_busy('pm', 'other', True, 'synthetic://replayed-old-pm')


if __name__ == '__main__':
    unittest.main()
