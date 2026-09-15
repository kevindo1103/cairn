import copy
import json
import os
import unittest
from pathlib import Path
from unittest.mock import patch

from cairn_adapter import Adapter, Owner, Store
from cairn_adapter.recovery import backup, proof, restore
from cairn_adapter.store import get_config
import test_adapter as fixtures
from test_adapter import TOKENS, entry


class PMSuccession(unittest.TestCase):
    # Reuse fixture helpers without inheriting/rerunning its regression tests.
    setUp = fixtures.NegativeMatrix.setUp
    replace = fixtures.NegativeMatrix.replace
    identity = fixtures.NegativeMatrix.identity
    call = fixtures.NegativeMatrix.call
    rejected_zero_write = fixtures.NegativeMatrix.rejected_zero_write
    refresh_fixture_identity = fixtures.NegativeMatrix.refresh_fixture_identity

    def scenario(self):
        self.store = Store.initialize(self.root / 'pm-project', 'synthetic/repo', 'pm', TOKENS['owner'], clock=lambda: self.now)
        self.owner = Owner(self.store)
        self.entries = [entry('pm', role='PM'), entry('old', role='Lead'), entry('new', state='pending', role='PM')]
        self.entries[0]['successor'] = {'task_id': 'new', 'generation': 1}
        self.revision = 0
        self.replace()
        self.adapter = Adapter(self.store, self.verifier, host_identity=self.identity)
        self.call('pm', 'checkpoint')
        event = self.call('pm', 'enqueue', dedupe_key='pm', target='new', kind='HANDOFF', priority=1,
                          dependency=None, next_action='Synthetic PM readback')['id']
        self.rejected_zero_write(lambda: self.call('new', 'checkpoint'))
        self.rejected_zero_write(lambda: self.call('new', 'handoff_review', event_id=event))
        delivery = self.call('pm', 'claim', event_id=event)
        self.call('pm', 'sent', event_id=event, delivery_token=delivery['delivery_token'], receipt='synthetic://sent')
        self.call('new', 'reconcile', event_id=event)
        token = self.call('new', 'ack', event_id=event)['worker_token']
        self.call('new', 'start', event_id=event, worker_token=token, evidence='synthetic://start')
        review = self.call('pm', 'handoff_review', event_id=event)
        self.owner.attest(TOKENS['owner'], self.revision, event, 'complete', review['digest'], 'synthetic://complete')
        self.call('new', 'complete', event_id=event, worker_token=token, evidence='synthetic://complete')
        self.entries[0]['state'] = 'quiesced'
        self.entries[0]['quiescence'] = dict(evidence='synthetic://host-stopped', active_mutations=0,
                                           unmapped_work=0, ownership_ambiguity=0)
        self.replace()
        return event, token

    def approve(self, event, command='authority_flip'):
        review = self.call('new', 'handoff_review', event_id=event)
        self.owner.attest(TOKENS['owner'], self.revision, event, command, review['digest'], 'synthetic://approved')

    def test_owner_reviewed_flip_fences_old_generation_and_preserves_bootstrap(self):
        event, token = self.scenario()
        self.rejected_zero_write(lambda: self.call('new', 'authority_flip', event_id=event))
        self.approve(event)
        before_revision = self.revision
        result = self.call('new', 'authority_flip', event_id=event)
        self.assertEqual(result['successor_generation'], 2)
        self.refresh_fixture_identity()
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger.pm_authority()['task_id'], 'new')
            self.assertEqual(db.execute("SELECT value FROM config WHERE key='pm_task'").fetchone()[0], 'pm')
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS['new'], 1, self.revision, 'adapter', 'checkpoint', {}))
        self.rejected_zero_write(lambda: self.adapter.execute(TOKENS['new'], 2, before_revision, 'adapter', 'checkpoint', {}))
        self.rejected_zero_write(lambda: self.call('pm', 'checkpoint'))
        self.rejected_zero_write(lambda: self.call('new', 'start', event_id=event, worker_token=token, evidence='synthetic://stale'))
        self.call('new', 'checkpoint')
        self.approve(event, 'retire')
        self.call('new', 'retire', event_id=event)
        self.refresh_fixture_identity()
        self.assertEqual(self.entries[0]['state'], 'retired')
        self.entries[0]['state'] = 'active'
        self.rejected_zero_write(self.replace)

    def test_stale_owner_review_and_cross_role_flip_are_zero_write(self):
        event, _ = self.scenario()
        self.approve(event)
        self.replace()
        self.rejected_zero_write(lambda: self.call('new', 'authority_flip', event_id=event))
        self.rejected_zero_write(lambda: self.call('old', 'authority_flip', event_id=event))
        self.approve(event)
        self.verifier.available = False
        self.rejected_zero_write(lambda: self.call('new', 'authority_flip', event_id=event))

    def test_core_epoch_and_registry_roll_back_together(self):
        event, _ = self.scenario()
        self.approve(event)
        from cairn_adapter import governance
        original = governance.put_config
        def fail_registry(db, key, value):
            if key == 'registry':
                raise ValueError('synthetic failure after core succession')
            return original(db, key, value)
        with patch.object(governance, 'put_config', fail_registry):
            self.rejected_zero_write(lambda: self.call('new', 'authority_flip', event_id=event))
        with self.store.transaction() as (db, ledger):
            self.assertEqual(ledger.pm_authority()['task_id'], 'pm')

    def test_pm_last_rejects_other_unretired_mapping(self):
        event, _ = self.scenario()
        self.entries.append(entry('other', state='pending'))
        self.entries[1]['successor'] = {'task_id': 'other', 'generation': 1}
        self.replace()
        self.approve(event)
        self.rejected_zero_write(lambda: self.call('new', 'authority_flip', event_id=event))

    def test_restore_binds_new_pm_epoch_and_rejects_old_proof(self):
        event, _ = self.scenario()
        old = backup(self.store.path, self.root / 'before.sqlite')
        self.approve(event)
        self.call('new', 'authority_flip', event_id=event)
        self.refresh_fixture_identity()
        saved = backup(self.store.path, self.root / 'after.sqlite')
        self.assertEqual(saved['pm_authority']['task_id'], 'new')
        self.assertEqual(saved['pm_task'], 'pm')
        if os.environ.get('CAIRN_TEST_EVIDENCE_DIR'):
            output = Path(os.environ['CAIRN_TEST_EVIDENCE_DIR'])
            output.mkdir(parents=True, exist_ok=True)
            (output / 'pm-succession-recovery-proof.json').write_text(json.dumps(
                {'kind': 'SYNTHETIC_ONLY', 'before': old, 'after': saved}, indent=2) + '\n', encoding='utf-8')
        with self.assertRaises(ValueError):
            restore(self.root / 'after.sqlite', self.root / 'wrong', old, 'synthetic/repo')
        self.assertFalse((self.root / 'wrong' / 'ledger.sqlite').exists())
        restore(self.root / 'after.sqlite', self.root / 'restored', saved, 'synthetic/repo')
        self.store = Store(self.root / 'restored', 'synthetic/repo', clock=lambda: self.now)
        self.owner = Owner(self.store)
        self.adapter = Adapter(self.store, self.verifier, host_identity=self.identity)
        self.assertEqual(proof(self.store.path), saved)
        self.rejected_zero_write(lambda: self.call('pm', 'checkpoint'))
        self.call('new', 'checkpoint')


if __name__ == '__main__':
    unittest.main()
