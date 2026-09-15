"""Offline TEST-store facade. PM imports manual platform observations; no transport."""
import argparse
from contextlib import contextmanager
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


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError('Duplicate JSON field')
            result[key] = value
        return result
    with Path(path).open('rb') as stream:
        raw = stream.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError('Import size limit exceeded')
    return json.loads(raw, object_pairs_hook=unique, parse_constant=lambda _: (_ for _ in ()).throw(ValueError('Non-finite JSON')))


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


def prepare(root, head, *, recipient=RECIPIENT, dedupe=DEDUPE):
    if len(head) != 40 or any(c not in '0123456789abcdef' for c in head):
        raise ValueError('Require exact source head')
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
                                  imports={}, sent_at=None, identity='MANUAL_ATTESTATION'))
    owner = dict(tokens=tokens, head=head, recipient=recipient, core_pin=CORE)
    (root / 'broker' / 'owner.json').write_text(json.dumps(owner) + '\n', encoding='utf-8')
    public = dict(recipient=recipient, envelope=envelope, state='QUEUED', transport='NOT_SENT',
                  principal_enforcement='NOT_PROVEN', isolation='NOT_PROVEN', activation_authorized=False)
    (root / 'evidence' / 'envelope.json').write_text(json.dumps(public, indent=2) + '\n', encoding='utf-8')
    return public


def import_observation(root, stage, observation, *, clock=time.time):
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
    owner = read_json(Path(root) / 'broker' / 'owner.json')
    if origin['thread_id'] != owner.get('recipient'):
        raise ValueError('Wrong canonical recipient')
    uat = Uat(root)
    expected = dict(uat.envelope, action=ACTION[stage])
    if stage == 'complete':
        expected['result'] = 42
    # Canonical comparison rejects true/42.0 substitution, extra identity fields,
    # stale checkpoint/nonce/dedupe and child text masquerading as platform origin.
    from cairn_adapter.store import canonical, get_config, put_config
    if canonical(readback) != canonical(expected):
        raise ValueError('Readback differs from frozen event/checkpoint/nonce')
    with uat.store.transaction() as (db, ledger):
        config = get_config(db, 'uat')
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
