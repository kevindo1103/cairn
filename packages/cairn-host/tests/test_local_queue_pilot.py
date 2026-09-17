import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import local_queue_pilot as pilot


class LocalPilotTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'new-run'

    def check_run(self, mode):
        result = pilot.run(self.root, mode)
        self.assertNotEqual(result['parent_pid'], result['child_pid'])
        self.assertTrue(result['backup_restore_equal'])
        self.assertFalse(result['activation_authorized'])
        self.assertEqual(result['host_isolation'], 'NOT_PROVEN')
        self.assertEqual(result['stop_reason'], 'CHILD_EXIT')
        self.assertTrue(result['scenario_passed'])
        return result

    def test_real_child_lifecycle_and_consistent_restored_store(self):
        result = self.check_run('happy')
        self.assertEqual(result['child_exit_code'], 0)
        self.assertEqual([r['state'] for r in result['requests']],
                         ['SENT', 'SENT', 'ACKED', 'STARTED', 'STARTED', 'COMPLETED'])
        self.assertEqual(result['completion_count'], 1)
        self.assertEqual(result['retained_slots'], 0)

    def test_receipt_is_not_ack_or_start(self):
        result = self.check_run('receipt_only')
        self.assertEqual(result['final_state'], 'SENT')
        self.assertEqual(result['completion_count'], 0)
        self.assertEqual(len(result['requests']), 1)

    def test_unexpected_real_child_crash_does_not_pass_happy_scenario(self):
        original = subprocess.Popen
        def crash_child(command, **kwargs):
            return original([*command[:-1], 'crash_after_ack'], **kwargs)
        with patch.object(pilot.subprocess, 'Popen', crash_child):
            result = pilot.run(self.root, 'happy')
        self.assertEqual(result['child_exit_code'], 74)
        self.assertFalse(result['scenario_passed'])
        self.assertEqual(result['retained_slots'], 1)

    def test_wrong_channel_identity_cannot_reconcile_or_ack(self):
        result = self.check_run('wrong_mapping')
        self.assertEqual(result['final_state'], 'SENT')
        self.assertFalse(result['requests'][-1]['accepted'])
        self.assertTrue(result['requests'][-1]['zero_write'])
        self.assertEqual(result['completion_count'], 0)

    def test_payload_cannot_supply_actor(self):
        result = self.check_run('impersonate')
        self.assertEqual(result['final_state'], 'SENT')
        self.assertTrue(result['requests'][-1]['zero_write'])

    def test_duplicate_delivery_and_completion_are_zero_write(self):
        result = self.check_run('duplicate')
        self.assertEqual(result['final_state'], 'COMPLETED')
        self.assertEqual(result['completion_count'], 1)
        self.assertEqual(len(result['requests']), 8)
        self.assertTrue(all(not r['accepted'] and r['zero_write'] for r in result['requests'][-2:]))

    def test_crash_retains_lease_and_new_parent_refuses_existing_run(self):
        result = self.check_run('crash_after_ack')
        self.assertEqual(result['child_exit_code'], 74)
        self.assertEqual(result['final_state'], 'ACKED')
        self.assertEqual(result['retained_slots'], 1)
        before = pilot.dependencies()['proof'](self.root / 'broker' / 'ledger.sqlite')
        retry = subprocess.run([sys.executable, '-I', str(pilot.HERE / 'local_queue_pilot.py'),
                                '--run-root', str(self.root)], capture_output=True, text=True, timeout=15)
        self.assertNotEqual(retry.returncode, 0)
        self.assertIn('FileExistsError', retry.stderr)
        self.assertEqual(pilot.dependencies()['proof'](self.root / 'broker' / 'ledger.sqlite'), before)

    def test_wrong_restore_proof_and_existing_destination_refused(self):
        result = self.check_run('happy')
        api = pilot.dependencies()
        saved = self.root / 'evidence' / 'backup.sqlite'
        wrong = dict(result['recovery_proof'], digest='0' * 64)
        with self.assertRaises(ValueError):
            api['restore'](saved, self.root / 'bad-restore', wrong, pilot.PROJECT)
        self.assertFalse((self.root / 'bad-restore').exists())
        with self.assertRaises(FileExistsError):
            api['restore'](saved, self.root / 'restored', result['recovery_proof'], pilot.PROJECT)

    def test_config_activation_and_path_traversal_refused(self):
        config = dict(pilot.CONFIG, activation_authorized=True)
        config_path = Path(self.temp.name) / 'invalid.json'
        config_path.write_text(json.dumps(config), encoding='utf-8')
        result = subprocess.run([sys.executable, '-I', str(pilot.HERE / 'local_queue_pilot.py'),
                                 '--config', str(config_path), '--run-root', str(self.root)],
                                capture_output=True, text=True, timeout=15)
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse(self.root.exists())
        with self.assertRaises(ValueError):
            pilot.exclusive_root(Path(self.temp.name) / '..' / 'escaped')

    def test_real_windows_junction_ancestor_refused_target_untouched(self):
        self.assertEqual(os.name, 'nt', 'This host coverage requires a real Windows runner')
        target = Path(self.temp.name) / 'junction-target'
        target.mkdir()
        sentinel = target / 'keep.bin'
        sentinel.write_bytes(b'untouched junction target\x00\xff')
        link = Path(self.temp.name) / 'junction-link'
        created = subprocess.run(['cmd.exe', '/d', '/c', 'mklink', '/J', str(link), str(target)],
                                 capture_output=True, text=True, timeout=10)
        self.assertEqual(created.returncode, 0,
                         'Junction creation denied; no fallback or skip: ' + created.stderr)
        try:
            self.assertTrue(getattr(link, "is_junction", lambda: False)())
            before = {p.name: p.read_bytes() for p in target.iterdir()}
            with self.assertRaisesRegex(ValueError, 'Linked run path refused'):
                pilot.Pilot(link / 'new-run')
            self.assertEqual({p.name: p.read_bytes() for p in target.iterdir()}, before)
            self.assertFalse((target / 'new-run').exists())
        finally:
            link.rmdir()  # Remove only the link, never recursively delete its target.
        self.assertEqual(sentinel.read_bytes(), b'untouched junction target\x00\xff')


class HandoffTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temp.cleanup)
        cls.result = pilot.run(Path(cls.temp.name) / 'handoff', 'handoff')
        if not cls.result['scenario_passed']:
            raise AssertionError('HANDOFF process rehearsal failed')

    def test_ack_only_cannot_retire(self):
        check = self.result['handoff_checks']['ack_only']
        self.assertFalse(check['eligibility']['HANDOFF_COMPLETED'])
        self.assertFalse(check['eligibility']['RETIRE_ALLOWED'])
        self.assertTrue(check['retire_rejected_zero_write'])

    def test_completed_with_active_predecessor_cannot_retire(self):
        check = self.result['handoff_checks']['completed_predecessor_active']
        self.assertTrue(check['eligibility']['HANDOFF_COMPLETED'])
        self.assertFalse(check['eligibility']['predecessor_QUIESCED'])
        self.assertTrue(check['retire_rejected_zero_write'])

    def test_quiesced_with_real_retained_lease_cannot_retire(self):
        check = self.result['handoff_checks']['quiesced_retained_lease']
        self.assertTrue(check['eligibility']['HANDOFF_COMPLETED'])
        self.assertTrue(check['eligibility']['predecessor_QUIESCED'])
        self.assertFalse(check['eligibility']['drain_ZERO'])
        self.assertTrue(check['retained_worker_lease'])
        self.assertTrue(check['retained_slot'])
        self.assertEqual(check['retained_worker_state'], 'STARTED')
        self.assertTrue(check['retire_rejected_zero_write'])

    def test_full_conjunction_is_eligibility_only_and_survives_restore(self):
        check = self.result['handoff_checks']['full_conjunction']
        self.assertTrue(check['eligibility']['RETIRE_ALLOWED'])
        self.assertTrue(check['eligibility']['successor_ACTIVE_generation'])
        self.assertFalse(check['eligibility']['retirement_authorized'])
        self.assertEqual(check['eligibility']['actions_executed'], [])
        self.assertIsNone(check['retire_rejected_zero_write'])
        self.assertEqual(check['eligibility'], self.result['restored_retirement_readback'])
        self.assertTrue(self.result['backup_restore_equal'])

    def test_ack_still_requires_current_reconciliation(self):
        local = pilot.HandoffPilot(Path(self.temp.name) / 'no-reconcile')
        self.assertTrue(local.handle(dict(command='receipt', event_id=local.event, arguments={}))['ok'])
        before = local.api['proof'](local.store.path)
        self.assertFalse(local.handle(dict(command='ack', event_id=local.event, arguments={}))['ok'])
        self.assertEqual(local.api['proof'](local.store.path), before)
        self.assertEqual(local.state(), 'SENT')

    def test_bad_completion_token_does_not_write_owner_attestation(self):
        local = pilot.HandoffPilot(Path(self.temp.name) / 'bad-complete')
        def send(command, **arguments):
            return local.handle(dict(command=command, event_id=local.event, arguments=arguments))
        for command in ('receipt', 'reconcile'):
            self.assertTrue(send(command)['ok'])
        token = send('ack')['worker_token']
        self.assertTrue(send('start', worker_token=token, evidence='synthetic://start')['ok'])
        self.assertTrue(send('renew', worker_token=token)['ok'])
        before = local.api['proof'](local.store.path)
        self.assertFalse(send('complete', worker_token='wrong', evidence='synthetic://child-complete')['ok'])
        self.assertEqual(local.api['proof'](local.store.path), before)
        self.assertEqual(local.state(), 'STARTED')

    def test_completed_quiesced_drained_requires_active_successor(self):
        local = pilot.HandoffPilot(Path(self.temp.name) / 'successor-not-active')
        with patch.object(pilot, 'HandoffPilot', return_value=local):
            result = pilot.run(local.root, 'handoff')
        self.assertTrue(result['scenario_passed'])
        successor = next(e for e in local.entries if e['task_id'] == 'worker')
        successor['state'] = 'quiesced'
        successor['quiescence'] = dict(evidence='synthetic://successor-quiesced', active_mutations=0,
                                       unmapped_work=0, ownership_ambiguity=0)
        local.revision = local.api['Owner'](local.store).replace(
            local.tokens['owner'], local.revision, local.entries)['revision']
        check = local.assess('successor_not_active', False, attempt_retire=True)
        eligibility = check['eligibility']
        for field in ('HANDOFF_COMPLETED', 'predecessor_QUIESCED', 'drain_ZERO'):
            self.assertTrue(eligibility[field], field)
        self.assertFalse(eligibility['successor_ACTIVE_generation'])
        self.assertTrue(check['retire_rejected_zero_write'])


if __name__ == '__main__':
    unittest.main()
