"""Offline TEST-store facade. PM imports manual platform observations; no transport."""
import argparse
from contextlib import contextmanager
import hashlib
import json
from pathlib import Path
import secrets
import subprocess
import time

from local_queue_pilot import Pilot, FixtureVerifier, dependencies, exclusive_root, PROJECT, SCOPE, CORE, BASELINE

RECIPIENT = '01a0a069-8b36-70e0-b66b-7af6ff0b1913'
DEDUPE = 'cairn:uat:' + RECIPIENT + ':001'
ACTION = dict(sent='TRANSPORT_ACCEPTED', ack='ACK_REQUEST', start='START_REQUEST', complete='COMPLETION_REQUEST')
EXPECTED = dict(sent='QUEUED', ack='SENT', start='ACKED', complete='STARTED')
MAX_BYTES = 16384


def parse_json(raw):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    if len(raw) > MAX_BYTES:
        raise ValueError('Import size limit exceeded')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


def read_json(path):
    with Path(path).open('rb') as stream:
        return parse_json(stream.read(MAX_BYTES + 1))


class UatVerifier(FixtureVerifier):
    def __init__(self, head):
        self.head = head

    def verify(self, binding, scope):
        result = super().verify(binding, scope)
        result.update(head=self.head, base=BASELINE,
                      checkpoint='cairn-existing-task-uat-01@' + self.head[:12])
        return result


class Uat(Pilot):
    def __init__(self, root):
        self.root = Path(root).absolute()
        for part in (self.root, *self.root.parents):
            if '..' in self.root.parts or part.is_symlink() or part.is_junction():
                raise ValueError('Linked/traversing UAT root refused')
        self.api = dependencies()
        data = read_json(self.root / 'broker' / 'owner.json')
        if set(data) != {'tokens', 'head', 'recipient', 'core_pin'} or data['core_pin'] != CORE:
            raise ValueError('Unknown UAT owner binding')
        self.tokens = data['tokens']
        self.recipient = data['recipient']
        self.store = self.api['Store'](self.root / 'broker', PROJECT)
        self.verifier = UatVerifier(data['head'])
        from cairn_adapter.store import get_config
        with self.store.transaction() as (db, ledger):
            config = get_config(db, 'uat')
            self.envelope = config['envelope']
            self.event = self.envelope['event_id']
            self.revision = config['registry_revision']
            if config['recipient'] != self.recipient:
                raise ValueError('Wrong canonical recipient')

    def identity(self, credential):
        # Owner-fixed mapping only. This is explicitly MANUAL_ATTESTATION, not
        # independently enforced platform/OS identity or caller-selected actor.
        for actor in ('pm', self.recipient):
            if credential == self.tokens[actor]:
                return dict(task_id=actor, session_id='synthetic-session-' + actor, generation=1)
        return None


def prepare(root, head, *, recipient=RECIPIENT, dedupe=DEDUPE, completion_result=42):
    if len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('Require exact source head')
    if not isinstance(completion_result, int) or isinstance(completion_result, bool):
        raise ValueError('Require integer completion result')
    completion = dict(result=completion_result)
    api = dependencies()
    if api['verify_package']()['source_commit'] != CORE:
        raise ValueError('Core pin drift')
    root = exclusive_root(root)
    (root / 'broker').mkdir()
    (root / 'evidence').mkdir()
    tokens = {actor: secrets.token_hex(32) for actor in ('owner', 'pm', recipient)}
    # Reuse existing fixture registry shape and pinned Adapter; no new lifecycle.
    fixture = object.__new__(Uat)
    fixture.api, fixture.tokens, fixture.recipient = api, tokens, recipient
    entries = [fixture.entry('pm', 'PM'), fixture.entry(recipient, 'worker')]
    store = api['Store'].initialize(root / 'broker', PROJECT, 'pm', tokens['owner'])
    revision = api['Owner'](store).replace(tokens['owner'], 0, entries)['revision']
    verifier = UatVerifier(head)
    adapter = api['Adapter'](store, verifier, host_identity=fixture.identity)
    def call(command, args):
        return adapter.execute(tokens['pm'], 1, revision, SCOPE, command, args)
    call('checkpoint', {})
    event = call('enqueue', dict(dedupe_key=dedupe, target=recipient, kind='APPROVAL', priority=1,
                                 dependency=None, next_action='Readback and arithmetic only'))
    from cairn_adapter.store import get_config, put_config
    envelope = {key: event['payload'][key] for key in ('checkpoint', 'scope', 'head', 'base')}
    envelope.update(event_id=event['id'], dedupe=dedupe, nonce=secrets.token_hex(16))
    with store.transaction() as (db, ledger):
        put_config(db, 'uat', dict(envelope=envelope, recipient=recipient, registry_revision=revision,
                                  imports={}, sent_at=None, identity='MANUAL_ATTESTATION',
                                  completion_contract=completion))
    owner = dict(tokens=tokens, head=head, recipient=recipient, core_pin=CORE)
    (root / 'broker' / 'owner.json').write_text(json.dumps(owner) + '\n', encoding='utf-8')
    public = dict(recipient=recipient, envelope=envelope, state='QUEUED', transport='NOT_SENT',
                  principal_enforcement='NOT_PROVEN', isolation='NOT_PROVEN', activation_authorized=False)
    public['completion_contract'] = completion
    (root / 'evidence' / 'envelope.json').write_text(json.dumps(public, indent=2) + '\n', encoding='utf-8')
    return public


def completion_contract(root):
    public = read_json(Path(root) / 'evidence' / 'envelope.json')
    contract = public.get('completion_contract', dict(result=42))
    if not isinstance(contract, dict) or set(contract) != {'result'} or not isinstance(contract['result'], int):
        raise ValueError('Invalid completion contract')
    return contract


def validate_observation(root, stage, observation):
    """Validate a prospective/manual observation without opening the Store."""
    if stage not in ACTION:
        raise ValueError('Unknown import stage')
    if (not isinstance(observation, dict) or set(observation) != {'observer', 'origin', 'readback'}
            or observation['observer'] != 'PM_MANUAL_PLATFORM_READBACK'):
        raise ValueError('Require PM manual observation envelope')
    origin, readback = observation['origin'], observation['readback']
    if (not isinstance(origin, dict) or set(origin) != {'thread_id', 'turn_id', 'evidence_ref'}
            or (stage != 'sent' and (not isinstance(origin['turn_id'], str) or not origin['turn_id'].strip()))
            or (stage == 'sent' and origin['turn_id'] is not None)):
        raise ValueError('Wrong/missing platform-resolved origin')
    dependencies()
    from comms_ledger.ledger import evidence_ref
    # Use the pinned core contract before opening the UAT Store. In particular,
    # codex:// is a platform locator, not a supported ledger evidence reference.
    evidence_ref(origin['evidence_ref'])
    public = read_json(Path(root) / 'evidence' / 'envelope.json')
    base_keys = {'recipient', 'envelope', 'state', 'transport', 'principal_enforcement', 'isolation',
                 'activation_authorized'}
    if (not isinstance(public, dict) or frozenset(public) not in {frozenset(base_keys),
                                                             frozenset(base_keys | {'completion_contract'})}
            or not isinstance(public['envelope'], dict)):
        raise ValueError('Unknown prospective UAT binding')
    if origin['thread_id'] != public['recipient']:
        raise ValueError('Wrong canonical recipient')
    expected = dict(public['envelope'], action=ACTION[stage])
    if stage == 'complete':
        expected.update(completion_contract(root))
    # Canonical comparison rejects true/42.0 substitution, extra identity fields,
    # stale checkpoint/nonce/dedupe and child text masquerading as platform origin.
    from cairn_adapter.store import canonical, get_config, put_config
    if canonical(readback) != canonical(expected):
        raise ValueError('Readback differs from frozen event/checkpoint/nonce')
    return dict(origin=origin, readback=readback, envelope=public['envelope'])


def protected_evidence_bytes(root, path):
    """Read one evidence file only after rejecting its original lexical link chain."""
    root = Path(root).absolute()
    evidence = root / 'evidence'
    path = Path(path).absolute()
    for current in (path, *path.parents, evidence, root, *root.parents):
        if current.is_symlink() or current.is_junction():
            raise ValueError('Linked evidence path refused')
    if not path.is_relative_to(evidence):
        raise ValueError('Evidence must be under the protected evidence root')
    resolved_evidence = evidence.resolve(strict=True)
    resolved_path = path.resolve(strict=True)
    if not resolved_path.is_relative_to(resolved_evidence):
        raise ValueError('Resolved evidence escapes the protected root')
    return path.read_bytes()


def operator_attest(root, stage, receipt_path, confirmation):
    """Build one manual observation from an already-recorded protected receipt."""
    root = Path(root).absolute()
    receipt_path = Path(receipt_path).absolute()
    raw = protected_evidence_bytes(root, receipt_path)
    receipt = parse_json(raw)
    public = read_json(root / 'evidence' / 'envelope.json')
    envelope = public['envelope']
    expected = dict(envelope, action=ACTION.get(stage))
    if stage == 'complete':
        expected.update(completion_contract(root))
    required = {'event_id', 'dedupe', 'checkpoint', 'thread_id', 'turn_id', 'action', 'readback',
                'transport_ref', 'stream_ref'}
    if stage == 'complete':
        required |= {'output_path', 'output_sha256', 'output_ref'}
    if (stage not in ACTION or not isinstance(receipt, dict) or set(receipt) != required
            or any(receipt[key] != envelope[key] for key in ('event_id', 'dedupe', 'checkpoint'))
            or receipt['thread_id'] != public['recipient'] or receipt['action'] != ACTION[stage]):
        raise ValueError('Receipt does not bind the exact event/stage')
    from comms_ledger.ledger import evidence_ref
    evidence_ref(receipt['transport_ref'])
    evidence_ref(receipt['stream_ref'])
    if stage == 'sent':
        if not isinstance(receipt['turn_id'], str) or not receipt['turn_id'].strip():
            raise ValueError('Receipt is not an observed delivery')
        origin_turn = None
    elif not isinstance(receipt['turn_id'], str) or not receipt['turn_id'].strip():
        raise ValueError('Receipt is missing observed turn')
    else:
        origin_turn = receipt['turn_id']
    from cairn_adapter.store import canonical
    if canonical(receipt['readback']) != canonical(expected):
        raise ValueError('Receipt readback differs from exact stage binding')
    if stage == 'complete':
        output = protected_evidence_bytes(root, receipt['output_path'])
        output_hash = hashlib.sha256(output).hexdigest()
        if (not output.strip() or receipt['output_sha256'] != output_hash
                or receipt['output_ref'] != 'artifact://sha256/' + output_hash):
            raise ValueError('Completion output artifact is missing or changed')
    receipt_hash = hashlib.sha256(raw).hexdigest()
    if (not isinstance(confirmation, dict)
            or confirmation != dict(owner='pm', confirmed=True, stage=stage,
                                    event_id=envelope['event_id'], dedupe=envelope['dedupe'],
                                    checkpoint=envelope['checkpoint'], receipt_sha256=receipt_hash)):
        raise ValueError('Explicit owner confirmation does not bind observed receipt')
    observation = dict(observer='PM_MANUAL_PLATFORM_READBACK',
                       origin=dict(thread_id=public['recipient'], turn_id=origin_turn,
                                   evidence_ref='artifact://sha256/' + receipt_hash),
                       readback=receipt['readback'])
    validate_observation(root, stage, observation)
    return observation


def operator_resume(root, attestations, *, clock=time.time):
    """Import already-observed, owner-confirmed stages only; never dispatch."""
    results = []
    for entry in attestations:
        if not isinstance(entry, dict) or set(entry) != {'stage', 'receipt_path', 'confirmation'}:
            raise ValueError('Require stage-specific operator attestation')
        observation = operator_attest(root, entry['stage'], entry['receipt_path'], entry['confirmation'])
        results.append(import_observation(root, entry['stage'], observation, clock=clock))
    return results


def import_observation(root, stage, observation, *, clock=time.time):
    validated = validate_observation(root, stage, observation)
    origin, readback = validated['origin'], validated['readback']
    uat = Uat(root)
    from cairn_adapter.store import canonical, get_config, put_config
    if canonical(uat.envelope) != canonical(validated['envelope']):
        raise ValueError('Prospective binding differs from Store binding')
    with uat.store.transaction() as (db, ledger):
        config = get_config(db, 'uat')
        if canonical(config.get('completion_contract', dict(result=42))) != canonical(completion_contract(root)):
            raise ValueError('Completion contract differs from Store binding')
        row = ledger._get(db, uat.event)
        if row['state'] != EXPECTED[stage] or stage in config['imports']:
            raise ValueError('Out of order or duplicate import')
        if stage != 'sent' and (config['sent_at'] is None or clock() > config['sent_at'] + 300):
            raise ValueError('Five-minute UAT bound expired')
        if stage == 'start' and origin['turn_id'] == config['imports']['ack']['origin']['turn_id']:
            raise ValueError('START requires second recipient turn')
        if stage == 'complete' and origin['turn_id'] != config['imports']['start']['origin']['turn_id']:
            raise ValueError('Completion differs from START turn')

        class BoundStore:
            @contextmanager
            def transaction(self):
                yield db, ledger

        # Reconciliation, ACK and audit share the OUTER transaction, so a later
        # rejection cannot leave partial reconciliation or import receipts behind.
        adapter = uat.api['Adapter'](BoundStore(), uat.verifier, host_identity=uat.identity)
        def call(actor, command, **args):
            return adapter.execute(uat.tokens[actor], 1, uat.revision, SCOPE, command, args)
        if stage == 'sent':
            token = call('pm', 'claim', event_id=uat.event)['delivery_token']
            call('pm', 'sent', event_id=uat.event, delivery_token=token, receipt=origin['evidence_ref'])
            config['sent_at'] = clock()
        elif stage == 'ack':
            call(uat.recipient, 'reconcile', event_id=uat.event)
            call(uat.recipient, 'ack', event_id=uat.event)
        else:
            call(uat.recipient, stage, event_id=uat.event, worker_token=row['worker_token'], evidence=origin['evidence_ref'])
        config['imports'][stage] = dict(origin=origin, observation_digest=uat.api['digest'](observation))
        put_config(db, 'uat', config)
        ledger._audit(db, uat.event, 'pm-manual-observer', 'UAT_' + stage.upper(), config['imports'][stage])
        return dict(event_id=uat.event, state=ledger._get(db, uat.event)['state'], stage=stage,
                    origin=origin, identity='MANUAL_ATTESTATION', principal_enforcement='NOT_PROVEN',
                    isolation='NOT_PROVEN', automatic_wake='NOT_IMPLEMENTED', activation_authorized=False)


def backup_restore_uat(root):
    """Consistently backup and reopen this UAT Store without dispatching."""
    uat = Uat(root)
    backup_path = Path(root) / 'evidence' / 'uat-store-backup.sqlite'
    restored_root = Path(root) / 'restored-store'
    if restored_root.exists():
        raise ValueError('Existing restore destination refused')
    saved = uat.api['backup'](uat.store.path, backup_path)
    restored = uat.api['restore'](backup_path, restored_root, saved, PROJECT)
    reopened = uat.api['Store'](restored_root, PROJECT)
    if saved != restored or uat.api['proof'](reopened.path) != saved:
        raise ValueError('UAT backup/restore proof mismatch')
    from cairn_adapter.store import get_config
    with reopened.transaction() as (db, ledger):
        config = get_config(db, 'uat')
        state = ledger._get(db, config['envelope']['event_id'])['state']
    return dict(proof=saved, state=state, envelope=config['envelope'], imports=config['imports'])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', *ACTION))
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--observation', type=Path)
    parser.add_argument('--recipient')
    parser.add_argument('--dedupe')
    args = parser.parse_args()
    if args.command == 'prepare':
        if args.observation:
            parser.error('prepare accepts no observation')
        repo = Path(__file__).resolve().parents[2]
        head = subprocess.check_output(['git', '-c', 'core.excludesFile=',
                                        '-c', 'safe.directory=' + str(repo).replace('\\', '/'),
                                        '-C', str(repo),
                                        'rev-parse', 'HEAD'], text=True).strip()
        result = prepare(args.root, head, recipient=args.recipient or RECIPIENT,
                         dedupe=args.dedupe or DEDUPE)
    else:
        if args.observation is None:
            parser.error('--observation required')
        result = import_observation(args.root, args.command, read_json(args.observation))
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
