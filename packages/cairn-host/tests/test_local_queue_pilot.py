import json
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


if __name__ == '__main__':
    unittest.main()
