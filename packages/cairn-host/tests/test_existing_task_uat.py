import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import existing_task_uat as uat


class ExistingTaskUatTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'uat'
        self.public = uat.prepare(self.root, 'a' * 40)
        self.api = uat.dependencies()

    def observation(self, stage):
        readback = dict(self.public['envelope'], action=uat.ACTION[stage])
        if stage == 'complete':
            readback['result'] = 42
        turn = None if stage == 'sent' else ('turn-ack' if stage == 'ack' else 'turn-work')
        return dict(observer='PM_MANUAL_PLATFORM_READBACK',
                    origin=dict(thread_id=uat.RECIPIENT, turn_id=turn, evidence_ref='artifact://fixture/' + stage),
                    readback=readback)

    def apply(self, stage, observation=None, **kwargs):
        return uat.import_observation(self.root, stage, observation or self.observation(stage), **kwargs)

    def no_write(self, call):
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        with self.assertRaises(ValueError):
            call()
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)

    def test_durable_stages_do_not_conflate_receipt_ack_or_identity(self):
        for stage, state in zip(uat.ACTION, ('SENT', 'ACKED', 'STARTED', 'COMPLETED')):
            result = self.apply(stage)
            self.assertEqual(result['state'], state)
            self.assertEqual(result['principal_enforcement'], 'NOT_PROVEN')
            self.assertFalse(result['activation_authorized'])
        raw = json.dumps(self.public)
        for token in uat.Uat(self.root).tokens.values():
            self.assertNotIn(token, raw)
        self.assertNotIn(str(self.root), raw)
        self.assertEqual(uat.Uat(self.root).event, self.public['envelope']['event_id'])

    def test_wrong_origin_nonce_dedupe_checkpoint_are_zero_write(self):
        self.apply('sent')
        for area, key, value in (('origin', 'thread_id', 'forged-pm'), ('origin', 'turn_id', ''),
                                 ('readback', 'nonce', 'wrong'), ('readback', 'dedupe', 'wrong'),
                                 ('readback', 'checkpoint', 'wrong')):
            message = self.observation('ack')
            message[area][key] = value
            self.no_write(lambda: self.apply('ack', message))

    def test_out_of_order_and_duplicate_are_zero_write(self):
        for stage in ('ack', 'start', 'complete'):
            self.no_write(lambda: self.apply(stage))
        for stage in uat.ACTION:
            self.apply(stage)
            self.no_write(lambda: self.apply(stage))

    def test_wrong_turn_result_extra_actor_and_expiry_are_zero_write(self):
        self.apply('sent')
        self.apply('ack')
        same = self.observation('start')
        same['origin']['turn_id'] = 'turn-ack'
        self.no_write(lambda: self.apply('start', same))
        self.apply('start')
        for area, key, value in (('origin', 'turn_id', 'another-turn'), ('readback', 'result', 41),
                                 ('readback', 'result', 42.0), ('readback', 'actor', 'pm')):
            message = self.observation('complete')
            message[area][key] = value
            self.no_write(lambda: self.apply('complete', message))
        self.no_write(lambda: self.apply('complete', clock=lambda: time.time() + 301))

    def test_ack_failure_rolls_back_reconciliation_and_import_record(self):
        self.apply('sent')
        from cairn_adapter.store import TransactionLedger
        with patch.object(TransactionLedger, 'ack', side_effect=ValueError('after reconcile')):
            self.no_write(lambda: self.apply('ack'))
        self.assertEqual(self.apply('ack')['state'], 'ACKED')

    def test_existing_root_duplicate_json_and_oversized_import_refused(self):
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        with self.assertRaises(FileExistsError):
            uat.prepare(self.root, 'a' * 40)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        path = Path(self.temp.name) / 'import.json'
        for raw in ('{"observer":1,"observer":2}', 'x' * (uat.MAX_BYTES + 1)):
            path.write_text(raw, encoding='utf-8')
            with self.assertRaises(ValueError):
                uat.read_json(path)

    def test_core_evidence_contract_rejected_before_store_open_zero_write(self):
        for reference in ('codex://threads/' + uat.RECIPIENT, 'https://' + 'x' * 1000, '', None):
            message = self.observation('sent')
            message['origin']['evidence_ref'] = reference
            with patch.object(uat, 'Uat', side_effect=AssertionError('Store opened before evidence validation')):
                self.no_write(lambda: self.apply('sent', message))

    def test_saved_platform_receipt_can_use_supported_artifact_reference(self):
        receipt = self.root / 'evidence' / 'fixture-platform-receipt.json'
        receipt.write_text(json.dumps(dict(synthetic_only=True,
            platform_locator='codex://threads/' + uat.RECIPIENT)), encoding='utf-8')
        reference = 'artifact://sha256/' + hashlib.sha256(receipt.read_bytes()).hexdigest()
        message = self.observation('sent')
        message['origin']['evidence_ref'] = reference
        result = self.apply('sent', message)
        self.assertEqual(result['state'], 'SENT')
        self.assertEqual(result['origin']['evidence_ref'], reference)
        self.assertEqual(result['principal_enforcement'], 'NOT_PROVEN')


if __name__ == '__main__':
    unittest.main()
