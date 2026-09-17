import copy
import hashlib
import json
import os
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

    def operator_entry(self, stage, *, turn=None, suffix=None):
        envelope = self.public['envelope']
        readback = dict(envelope, action=uat.ACTION[stage])
        if stage == 'complete':
            readback['result'] = 42
        transport = self.root / 'evidence' / 'observed-transport.json'
        stream = self.root / 'evidence' / 'observed-stream.json'
        transport.write_text('accepted transport receipt', encoding='utf-8')
        stream.write_text('protected stream receipt', encoding='utf-8')
        receipt = dict(event_id=envelope['event_id'], dedupe=envelope['dedupe'],
                       checkpoint=envelope['checkpoint'], thread_id=self.public['recipient'],
                       turn_id=turn or ('turn-delivery' if stage == 'sent' else
                                        ('turn-ack' if stage == 'ack' else 'turn-work')),
                       action=uat.ACTION[stage], readback=readback,
                       transport_ref='artifact://sha256/' + hashlib.sha256(transport.read_bytes()).hexdigest(),
                       stream_ref='artifact://sha256/' + hashlib.sha256(stream.read_bytes()).hexdigest())
        if stage == 'complete':
            output = self.root / 'evidence' / 'observed-output.txt'
            output.write_text('Incident summary: one delivery, missing ACK, observer defect, preserved SENT.',
                              encoding='utf-8')
            digest = hashlib.sha256(output.read_bytes()).hexdigest()
            receipt.update(output_path=str(output), output_sha256=digest,
                           output_ref='artifact://sha256/' + digest)
        path = self.root / 'evidence' / ('observed-' + (suffix or stage) + '.json')
        path.write_bytes(json.dumps(receipt, separators=(',', ':')).encode('utf-8'))
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        confirmation = dict(owner='pm', confirmed=True, stage=stage,
                            event_id=envelope['event_id'], dedupe=envelope['dedupe'],
                            checkpoint=envelope['checkpoint'], receipt_sha256=digest)
        return dict(stage=stage, receipt_path=str(path), confirmation=confirmation)

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

    def test_legacy_public_envelope_uses_default_completion_contract(self):
        legacy = dict(self.public)
        legacy.pop('completion_contract')
        (self.root / 'evidence' / 'envelope.json').write_text(json.dumps(legacy))
        self.assertEqual(uat.validate_observation(self.root, 'sent', self.observation('sent'))['envelope'],
                         legacy['envelope'])

    def test_mutated_public_completion_contract_is_zero_write(self):
        public = dict(self.public, completion_contract=dict(result=99))
        (self.root / 'evidence' / 'envelope.json').write_text(json.dumps(public))
        self.no_write(lambda: self.apply('sent'))

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

    def test_pre_send_validator_rejects_live_origin_before_mock_send(self):
        message = self.observation('sent')
        message['observer'] = 'APP_SERVER_LIVE_STREAM'
        sent = False
        with patch.object(uat, 'Uat', side_effect=AssertionError('Store opened before pre-send rejection')):
            with self.assertRaisesRegex(ValueError, 'manual observation'):
                uat.validate_observation(self.root, 'sent', message)
        self.assertFalse(sent)

    def test_prospective_manual_shape_validates_without_store_write_or_send(self):
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        sent = False
        with patch.object(uat, 'Uat', side_effect=AssertionError('pre-send validation opened Store')):
            validated = uat.validate_observation(self.root, 'sent', self.observation('sent'))
        self.assertEqual(validated['origin']['turn_id'], None)
        self.assertFalse(sent)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)

    def test_import_rechecks_fresh_store_binding_after_pre_send_validation(self):
        message = self.observation('sent')
        public_path = self.root / 'evidence' / 'envelope.json'
        public = uat.read_json(public_path)
        public['envelope']['nonce'] = 'new-prospective-nonce'
        message['readback']['nonce'] = 'new-prospective-nonce'
        public_path.write_text(json.dumps(public), encoding='utf-8')
        self.assertEqual(
            uat.validate_observation(self.root, 'sent', message)['envelope']['nonce'],
            'new-prospective-nonce')
        self.no_write(lambda: self.apply('sent', message))

    def test_import_cannot_bypass_pre_send_validation(self):
        with patch.object(uat, 'validate_observation', side_effect=ValueError('pre-send rejected')):
            with patch.object(uat, 'Uat', side_effect=AssertionError('Store opened after rejected validation')):
                self.no_write(lambda: self.apply('sent'))

    def test_operator_resume_imports_existing_stage_evidence_without_dispatch(self):
        deliveries = []
        sent = self.operator_entry('sent')
        deliveries.append(sent['receipt_path'])  # Synthetic pre-existing transport evidence.
        entries = [sent, self.operator_entry('ack'), self.operator_entry('start'),
                   self.operator_entry('complete')]
        results = uat.operator_resume(self.root, entries, clock=lambda: 1)
        self.assertEqual([result['state'] for result in results],
                         ['SENT', 'ACKED', 'STARTED', 'COMPLETED'])
        self.assertEqual(len(deliveries), 1)

    def test_operator_attestation_requires_existing_bound_receipt_and_confirmation(self):
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        missing = dict(stage='sent', receipt_path=str(self.root / 'evidence' / 'missing.json'),
                       confirmation={})
        with self.assertRaises(FileNotFoundError):
            uat.operator_resume(self.root, [missing])
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        entry = self.operator_entry('sent')
        entry['confirmation']['receipt_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'owner confirmation'):
            uat.operator_resume(self.root, [entry])
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)

    def test_operator_resume_failure_and_ttl_do_not_duplicate_delivery_or_reset_clock(self):
        deliveries = []
        sent = self.operator_entry('sent')
        deliveries.append(sent['receipt_path'])
        uat.operator_resume(self.root, [sent], clock=lambda: 0)
        ack = self.operator_entry('ack')
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        ack['confirmation']['event_id'] = 'stale'
        with self.assertRaisesRegex(ValueError, 'owner confirmation'):
            uat.operator_resume(self.root, [ack], clock=lambda: 1)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        self.assertEqual(len(deliveries), 1)
        corrected = self.operator_entry('ack', suffix='ack-corrected')
        with self.assertRaisesRegex(ValueError, 'Five-minute UAT bound expired'):
            uat.operator_resume(self.root, [corrected], clock=lambda: 301)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        self.assertEqual(len(deliveries), 1)

    def test_operator_complete_requires_immutable_actual_output(self):
        entries = [self.operator_entry(stage) for stage in ('sent', 'ack', 'start')]
        uat.operator_resume(self.root, entries, clock=lambda: 1)
        complete = self.operator_entry('complete')
        output = Path(uat.read_json(complete['receipt_path'])['output_path'])
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        output.unlink()
        with self.assertRaises(FileNotFoundError):
            uat.operator_resume(self.root, [complete], clock=lambda: 1)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        complete = self.operator_entry('complete', suffix='complete-changed')
        output = Path(uat.read_json(complete['receipt_path'])['output_path'])
        output.write_text('Changed after confirmation', encoding='utf-8')
        with self.assertRaisesRegex(ValueError, 'output artifact'):
            uat.operator_resume(self.root, [complete], clock=lambda: 1)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)

    def test_operator_rejects_original_lexical_links_without_target_write(self):
        target = self.operator_entry('sent')
        target_path = Path(target['receipt_path'])
        target_bytes = target_path.read_bytes()
        linked = self.root / 'evidence' / 'linked-receipt.json'
        try:
            os.symlink(target_path, linked)
            linked_entry = dict(target, receipt_path=str(linked))
            link_check = None
        except OSError:
            linked_entry = dict(target, receipt_path=str(linked))
            link_check = patch.object(Path, 'is_symlink',
                                      lambda value: value.absolute() == linked.absolute())
        linked_entry = dict(target, receipt_path=str(linked))
        before = self.api['proof'](self.root / 'broker/ledger.sqlite')
        if link_check:
            with link_check:
                with self.assertRaisesRegex(ValueError, 'Linked evidence'):
                    uat.operator_resume(self.root, [linked_entry])
        else:
            with self.assertRaisesRegex(ValueError, 'Linked evidence'):
                uat.operator_resume(self.root, [linked_entry])
        self.assertEqual(target_path.read_bytes(), target_bytes)
        self.assertEqual(self.api['proof'](self.root / 'broker/ledger.sqlite'), before)
        linked_root = Path(self.temp.name) / 'linked-evidence-root'
        linked_root.mkdir()
        try:
            os.symlink(self.root / 'evidence', linked_root / 'evidence', target_is_directory=True)
            root_link_check = None
        except OSError:
            root_link_check = patch.object(
                Path, 'is_symlink',
                lambda value: value.absolute() == (linked_root / 'evidence').absolute())
        linked_entry = dict(target, receipt_path=str(linked_root / 'evidence' / target_path.name))
        if root_link_check:
            with root_link_check:
                with self.assertRaisesRegex(ValueError, 'Linked evidence'):
                    uat.operator_resume(linked_root, [linked_entry])
        else:
            with self.assertRaisesRegex(ValueError, 'Linked evidence'):
                uat.operator_resume(linked_root, [linked_entry])
        self.assertEqual(target_path.read_bytes(), target_bytes)

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

    def test_prepare_binds_a_host_owned_recipient_and_dedupe(self):
        root = Path(self.temp.name) / 'host-owned'
        recipient = 'host-owned-thread'
        public = uat.prepare(root, 'b' * 40, recipient=recipient, dedupe='cairn:host-owned:001')
        self.assertEqual(public['recipient'], recipient)
        self.assertEqual(public['envelope']['dedupe'], 'cairn:host-owned:001')
        def observed(stage):
            readback = dict(public['envelope'], action=uat.ACTION[stage])
            if stage == 'complete':
                readback['result'] = 42
            return dict(observer='PM_MANUAL_PLATFORM_READBACK',
                        origin=dict(thread_id=recipient,
                                    turn_id=None if stage == 'sent' else
                                    ('host-ack' if stage == 'ack' else 'host-work'),
                                    evidence_ref='artifact://fixture/' + stage),
                        readback=readback)
        for stage, state in zip(uat.ACTION, ('SENT', 'ACKED', 'STARTED', 'COMPLETED')):
            self.assertEqual(uat.import_observation(root, stage, observed(stage))['state'], state)


if __name__ == '__main__':
    unittest.main()
