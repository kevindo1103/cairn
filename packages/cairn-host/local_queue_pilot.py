"""Synthetic same-user IPC rehearsal. NOT a production broker or sandbox."""
import argparse
import copy
import json
import os
from pathlib import Path
import queue
import secrets
import subprocess
import sys
import threading
import time

HERE = Path(__file__).resolve().parent
BASELINE = 'ee86e13ea44d1e3ac181e08418f624ea8f8b3d29'
CORE = '39950de062ef085ed4e0ba5f87e3b48d6183d551'
PROJECT = 'synthetic/local-cairn-pilot'
SCOPE = 'local-pilot'
MODES = ('happy', 'receipt_only', 'crash_after_ack', 'duplicate', 'wrong_mapping', 'impersonate', 'handoff')
CONFIG = dict(synthetic_only=True, activation_authorized=False, project=PROJECT,
              adapter_baseline=BASELINE, core_pin=CORE, timeout_seconds=15, max_messages=12)
BINDING = dict(fixture='local-pilot-only', repository=PROJECT, worktree='synthetic-worktree',
               branch='synthetic-branch', rule_version='fixture-1', config_version='fixture-1')


def dependencies():
    # Only the parent loads the ledger. The child is a stdlib fixture, not Codex.
    for package in ('communication-ledger', 'cairn-adapter'):
        sys.path.insert(0, str(HERE.parent / package))
    from cairn_adapter import Adapter, Owner, Store, Rejected, credential_hash
    from cairn_adapter.recovery import backup, proof, restore
    from cairn_adapter.store import digest
    from cairn_adapter.package import verify_package
    return locals()


def exclusive_root(path):
    path = Path(path).absolute()
    if '..' in path.parts:
        raise ValueError('Parent traversal refused')
    for part in (path, *path.parents):
        if part.is_symlink() or part.is_junction():
            raise ValueError('Linked run path refused')
    # Never resume/rebind a previous run, including an incomplete crashed run.
    path.mkdir(parents=False, exist_ok=False)
    return path


class FixtureVerifier:
    """Fixed synthetic evidence; performs no GitHub/host identity verification."""
    def verify(self, binding, scope):
        if binding != BINDING or scope != SCOPE:
            raise ValueError('Synthetic binding mismatch')
        return dict(issue='15', scope=SCOPE, base=CORE, head=BASELINE,
                    checkpoint='synthetic-local-pilot-1', evidence='synthetic://approved-fixture')

    def verify_references(self, prs, issues):
        if prs or issues:
            raise ValueError('Only empty synthetic reference inventories accepted')


class Pilot:
    def __init__(self, root, *, handoff=False):
        self.api = dependencies()
        if self.api['verify_package']()['source_commit'] != CORE:
            raise ValueError('Unexpected core pin')
        self.root = exclusive_root(root)
        for name in ('broker', 'worker', 'evidence'):
            (self.root / name).mkdir()
        self.tokens = {name: secrets.token_hex(32) for name in
                       (('owner', 'pm', 'worker', 'old') if handoff else ('owner', 'pm', 'worker'))}
        self.mapping = dict(task_id='worker', session_id='synthetic-session-worker', generation=1)
        self.store = self.api['Store'].initialize(self.root / 'broker', PROJECT, 'pm', self.tokens['owner'])
        self.entries = [self.entry('pm', 'PM'), self.entry('worker', 'worker')]
        if handoff:
            self.entries.append(self.entry('old', 'Lead'))
            self.entries[-1]['successor'] = dict(task_id='worker', generation=1)
        self.revision = self.api['Owner'](self.store).replace(self.tokens['owner'], 0, self.entries)['revision']
        self.adapter = self.api['Adapter'](self.store, FixtureVerifier(), host_identity=self.identity)
        self.call('pm', 'checkpoint')
        self.event = self.call('old' if handoff else 'pm', 'enqueue', dedupe_key='synthetic-single-event', target='worker',
                               kind='HANDOFF' if handoff else 'APPROVAL', priority=1, dependency=None,
                               next_action='Return synthetic IPC lifecycle evidence')['id']
        self.delivery = self.call('pm', 'claim', event_id=self.event)['delivery_token']
        self.records = []

    def entry(self, task, role):
        grants = ({'checkpoint': ['ABSENT'], 'enqueue': ['ABSENT'], 'claim': ['QUEUED'],
                   'sent': ['QUEUED'], 'get': ['QUEUED', 'SENT', 'ACKED', 'STARTED', 'COMPLETED']}
                  if task == 'pm' else
                  {'reconcile': ['SENT'], 'ack': ['SENT'], 'start': ['ACKED'],
                   'renew': ['STARTED'], 'complete': ['STARTED']})
        if 'old' in self.tokens and task == 'pm':
            for command in ('retirement', 'handoff_review', 'retire'):
                grants[command] = ['ACKED', 'COMPLETED']
            grants['handoff_review'].append('STARTED')
        if task == 'old':
            grants['enqueue'] = ['ABSENT']
            grants['get'] = ['SENT', 'ACKED', 'STARTED', 'COMPLETED']
        inventory = dict(unfinished_work=[], prs=[], issues=[], blockers=[])
        return dict(task_id=task, credential_hash=self.api['credential_hash'](self.tokens[task]),
                    generation=1, state='active', role=role, bindings={SCOPE: copy.deepcopy(BINDING)},
                    grants=[dict(command=k, scope=SCOPE, states=v) for k, v in grants.items()],
                    successor=None, quiescence=None, project=PROJECT,
                    session_id='synthetic-session-' + task, scopes=[SCOPE], authority=sorted(grants),
                    worktree=BINDING['worktree'], branch=BINDING['branch'], rule_version='fixture-1',
                    config_version='fixture-1', parent=None, owner='synthetic-owner',
                    expected_output='Synthetic receipt and lifecycle', stop_condition='Stop on any rejection',
                    inventory=dict(inventory, complete=True, readback_digest=self.api['digest'](inventory)))

    def identity(self, token):
        if token == self.tokens['worker']:
            return self.mapping.copy()
        for task in ('pm', 'old'):
            if task in self.tokens and token == self.tokens[task]:
                return dict(task_id=task, session_id='synthetic-session-' + task, generation=1)
        return None

    def call(self, actor, command, **arguments):
        return self.adapter.execute(self.tokens[actor], 1, self.revision, SCOPE, command, arguments)

    def state(self):
        return self.call('pm', 'get', event_id=self.event)['state']

    def handle(self, message):
        before = self.api['proof'](self.store.path)
        command = message.get('command') if isinstance(message, dict) else None
        try:
            if (not isinstance(message, dict) or set(message) != {'command', 'event_id', 'arguments'}
                    or message['event_id'] != self.event or not isinstance(message['arguments'], dict)):
                raise ValueError('Envelope identity/shape refused')
            arguments = message['arguments']
            if command == 'receipt':
                if arguments != {}:
                    raise ValueError('Receipt payload refused')
                self.call('pm', 'sent', event_id=self.event, delivery_token=self.delivery,
                          receipt='synthetic://child-pipe-received')
                result = {}
            elif command in {'reconcile', 'ack', 'start', 'renew', 'complete'}:
                result = self.call('worker', command, event_id=self.event, **arguments)
            else:
                raise ValueError('Command outside synthetic child facade')
            response = dict(ok=True)
            if command == 'ack':
                response['worker_token'] = result['worker_token']
            self.records.append(dict(command=command, accepted=True, state=self.state()))
            return response
        except (ValueError, RuntimeError, KeyError, TypeError) as error:
            after = self.api['proof'](self.store.path)
            if after != before:
                raise AssertionError('Rejected request mutated the ledger') from error
            self.records.append(dict(command=command, accepted=False, state=self.state(), zero_write=True))
            return dict(ok=False, error=type(error).__name__)

    def finish(self, child_pid, exit_code, stop_reason, mode):
        saved_path = self.root / 'evidence' / 'backup.sqlite'
        before = self.api['proof'](self.store.path)
        saved = self.api['backup'](self.store.path, saved_path)
        restored = self.api['restore'](saved_path, self.root / 'restored', saved, PROJECT)
        reopened = self.api['Store'](self.root / 'restored', PROJECT)
        if before != saved or restored != saved or self.api['proof'](reopened.path) != saved:
            raise AssertionError('Consistent restore mismatch')
        with self.store.transaction() as (db, ledger):
            completions = db.execute("SELECT COUNT(*) FROM history WHERE action='COMPLETED'").fetchone()[0]
            retained = db.execute("SELECT COUNT(*) FROM recipients WHERE active_event IS NOT NULL").fetchone()[0]
        expected_states = {'happy': 'COMPLETED', 'duplicate': 'COMPLETED',
                           'crash_after_ack': 'ACKED', 'receipt_only': 'SENT',
                           'wrong_mapping': 'SENT', 'impersonate': 'SENT', 'handoff': 'COMPLETED'}
        expected_requests = {'happy': 6, 'duplicate': 8, 'crash_after_ack': 3,
                             'receipt_only': 1, 'wrong_mapping': 2, 'impersonate': 2, 'handoff': 6}
        expected_rejects = 2 if mode == 'duplicate' else int(mode in {'wrong_mapping', 'impersonate'})
        scenario_passed = (stop_reason == 'CHILD_EXIT' and child_pid != os.getpid()
                           and exit_code == (74 if mode == 'crash_after_ack' else 0)
                           and self.state() == expected_states[mode]
                           and completions == int(mode in {'happy', 'duplicate', 'handoff'})
                           and retained == int(mode == 'crash_after_ack')
                           and len(self.records) == expected_requests[mode]
                           and sum(not r['accepted'] for r in self.records) == expected_rejects)
        evidence = dict(synthetic_only=True, scenario=mode, scenario_passed=scenario_passed,
                        adapter_baseline=BASELINE, core_pin=CORE,
                        status='PREPARED_ONLY', live_readiness=False, activation_authorized=False,
                        host_isolation='NOT_PROVEN', codex_wake='NOT_IMPLEMENTED',
                        parent_pid=os.getpid(), child_pid=child_pid, child_exit_code=exit_code,
                        stop_reason=stop_reason, event_id=self.event, final_state=self.state(),
                        completion_count=completions, retained_slots=retained,
                        requests=self.records, backup_restore_equal=True, recovery_proof=saved)
        if mode == 'handoff':
            evidence['handoff_checks'] = self.handoff_checks
            recovered = copy.copy(self)
            recovered.store = reopened
            recovered.adapter = self.api['Adapter'](reopened, FixtureVerifier(), host_identity=recovered.identity)
            recovered_status = recovered.call('pm', 'retirement', event_id=self.event)
            evidence['restored_retirement_readback'] = recovered_status
            evidence['scenario_passed'] = bool(scenario_passed and len(self.handoff_checks) == 4
                and all(check['passed'] for check in self.handoff_checks.values())
                and recovered_status == self.handoff_checks['full_conjunction']['eligibility'])
        (self.root / 'evidence' / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        return evidence


class HandoffPilot(Pilot):
    """Exercise existing HANDOFF governance; never execute flip or retirement."""
    def __init__(self, root):
        super().__init__(root, handoff=True)
        self.handoff_checks = {}

    def assess(self, label, expected, *, attempt_retire=False):
        eligibility = self.call('pm', 'retirement', event_id=self.event)
        if eligibility['RETIRE_ALLOWED'] != expected or eligibility['retirement_authorized']:
            raise AssertionError('Unexpected synthetic retirement eligibility')
        denied = None
        if attempt_retire:
            review = self.call('pm', 'handoff_review', event_id=self.event)
            self.api['Owner'](self.store).attest(self.tokens['owner'], self.revision, self.event,
                                              'retire', review['digest'], 'synthetic://deny-retire')
            before = self.api['proof'](self.store.path)
            try:
                self.call('pm', 'retire', event_id=self.event)
            except ValueError as error:
                if str(error) != 'Retirement invariant is incomplete':
                    raise AssertionError('Retire denied at wrong gate') from error
                denied = self.api['proof'](self.store.path) == before
            else:
                raise AssertionError('Retirement mutated the fixture')
            if not denied:
                raise AssertionError('Rejected retirement was not zero-write')
        check = dict(passed=True, eligibility=eligibility, retire_rejected_zero_write=denied)
        self.handoff_checks[label] = check
        return check

    def quiesce_fixture_old(self):
        self.entries = copy.deepcopy(self.entries)
        old = next(e for e in self.entries if e['task_id'] == 'old')
        old['state'] = 'quiesced'
        old['quiescence'] = dict(evidence='synthetic://fixture-quiescence', active_mutations=0,
                                 unmapped_work=0, ownership_ambiguity=0)
        self.revision = self.api['Owner'](self.store).replace(
            self.tokens['owner'], self.revision, self.entries)['revision']

    def handle(self, message):
        result = super().handle(message)
        # Approval follows successful renewal, separately from a future completion
        # request. A rejected completion must not itself write an owner attestation.
        if result['ok'] and message['command'] == 'renew':
            review = self.call('pm', 'handoff_review', event_id=self.event)
            self.api['Owner'](self.store).attest(self.tokens['owner'], self.revision, self.event,
                                              'complete', review['digest'], 'synthetic://child-complete')
        if result['ok'] and message['command'] == 'ack':
            self.assess('ack_only', False, attempt_retire=True)
        if result['ok'] and message['command'] == 'complete':
            self.assess('completed_predecessor_active', False, attempt_retire=True)
        return result

    def finish(self, child_pid, exit_code, stop_reason, mode):
        if self.state() == 'COMPLETED':
            # Fork before quiescence. Keep the retained-lease branch intact; no raw
            # SQL cleanup, time-travel, lease release or synthetic takeover.
            saved = self.api['backup'](self.store.path, self.root / 'evidence' / 'before-quiesce.sqlite')
            self.api['restore'](self.root / 'evidence' / 'before-quiesce.sqlite',
                                self.root / 'retained-branch', saved, PROJECT)
            branch = copy.copy(self)
            branch.handoff_checks = {}
            branch.store = self.api['Store'](self.root / 'retained-branch', PROJECT)
            branch.adapter = self.api['Adapter'](branch.store, FixtureVerifier(), host_identity=branch.identity)
            busy = branch.call('old', 'enqueue', dedupe_key='retained-lease', target='old', kind='APPROVAL',
                               priority=1, dependency=None, next_action='Synthetic retained worker')['id']
            token = branch.call('pm', 'claim', event_id=busy)['delivery_token']
            branch.call('pm', 'sent', event_id=busy, delivery_token=token, receipt='synthetic://retained')
            branch.call('old', 'reconcile', event_id=busy)
            worker = branch.call('old', 'ack', event_id=busy)['worker_token']
            branch.call('old', 'start', event_id=busy, worker_token=worker, evidence='synthetic://retained-start')
            branch.quiesce_fixture_old()
            check = branch.assess('quiesced_retained_lease', False, attempt_retire=True)
            with branch.store.transaction() as (db, ledger):
                retained = ledger._get(db, busy)
                check['retained_worker_state'] = retained['state']
                check['retained_worker_lease'] = retained['worker_token'] is not None
                check['retained_slot'] = bool(db.execute(
                    'SELECT 1 FROM recipients WHERE active_event=?', (busy,)).fetchone())
            if not check['retained_worker_lease'] or not check['retained_slot']:
                raise AssertionError('Retained lease fixture missing')
            self.handoff_checks['quiesced_retained_lease'] = check
            (self.root / 'evidence' / 'handoff-retained.json').write_text(json.dumps(
                dict(check=check, proof=self.api['proof'](branch.store.path)), indent=2) + '\n', encoding='utf-8')
            self.quiesce_fixture_old()
            self.assess('full_conjunction', True)  # Eligibility read only, no retire call.
        return super().finish(child_pid, exit_code, stop_reason, mode)


def child(mode):
    envelope = json.loads(sys.stdin.readline())
    def request(command, **arguments):
        msg = dict(command=command, event_id=envelope['event_id'], arguments=arguments)
        if mode == 'impersonate' and command == 'reconcile':
            msg['actor'] = 'pm'
        print(json.dumps(msg), flush=True)
        return json.loads(sys.stdin.readline())
    if not request('receipt')['ok'] or mode == 'receipt_only':
        return
    if not request('reconcile')['ok']:
        return
    response = request('ack')
    if not response['ok']:
        return
    if mode == 'crash_after_ack':
        os._exit(74)
    token = response['worker_token']
    if not request('start', worker_token=token, evidence='synthetic://child-start')['ok']:
        return
    if not request('renew', worker_token=token)['ok']:
        return
    if not request('complete', worker_token=token, evidence='synthetic://child-complete')['ok']:
        return
    if mode == 'duplicate':
        # Replay the delivered envelope, then an already-consumed completion token.
        request('receipt')
        request('complete', worker_token=token, evidence='synthetic://duplicate-complete')


def run(root, mode='happy'):
    if mode not in MODES:
        raise ValueError('Unknown synthetic scenario')
    pilot = HandoffPilot(root) if mode == 'handoff' else Pilot(root)
    if mode == 'wrong_mapping':
        pilot.mapping['task_id'] = 'pm'
    lines = queue.Queue(maxsize=16)
    with (pilot.root / 'evidence' / 'child-stderr.txt').open('x', encoding='utf-8') as stderr:
        # Explicit stdio pipes; no shell, socket, service, daemon or desktop task.
        process = subprocess.Popen([sys.executable, '-I', str(Path(__file__).resolve()), '--child', mode],
                                   stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=stderr,
                                   text=True, encoding='utf-8', cwd=pilot.root / 'worker',
                                   env={k: os.environ[k] for k in ('SYSTEMROOT', 'WINDIR', 'TEMP', 'TMP') if k in os.environ})
        def read_lines():
            try:
                for _ in range(CONFIG['max_messages'] + 1):
                    line = process.stdout.readline(65537)
                    lines.put(line)
                    if not line or len(line) > 65536:
                        return
            except (ValueError, OSError):
                lines.put('')
        reader = threading.Thread(target=read_lines, daemon=True)
        reader.start()
        stop_reason = 'CHILD_EXIT'
        deadline = time.monotonic() + CONFIG['timeout_seconds']
        try:
            process.stdin.write(json.dumps(dict(event_id=pilot.event, synthetic_only=True)) + '\n')
            process.stdin.flush()
            for _ in range(CONFIG['max_messages']):
                line = lines.get(timeout=max(0.001, deadline - time.monotonic()))
                if not line:
                    break
                if len(line) > 65536 or not line.endswith('\n'):
                    raise ValueError('Oversized or incomplete protocol frame')
                reply = pilot.handle(json.loads(line))
                process.stdin.write(json.dumps(reply) + '\n')
                process.stdin.flush()
            else:
                raise ValueError('Message budget exhausted')
            process.wait(timeout=max(0.001, deadline - time.monotonic()))
        except (queue.Empty, subprocess.TimeoutExpired, ValueError, BrokenPipeError) as error:
            stop_reason = type(error).__name__
        finally:
            if process.poll() is None:
                process.kill()  # Only this fixture child; no external process control.
            process.wait(timeout=5)
            reader.join(timeout=2)
            process.stdin.close()
            process.stdout.close()
    return pilot.finish(process.pid, process.returncode, stop_reason, mode)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--child', choices=MODES, help=argparse.SUPPRESS)
    parser.add_argument('--run-root', type=Path)
    parser.add_argument('--config', type=Path, default=HERE / 'local_queue_pilot.example.json')
    parser.add_argument('--scenario', choices=MODES, default='happy')
    args = parser.parse_args()
    if args.child:
        child(args.child)
        return
    config = json.loads(args.config.read_text(encoding='utf-8'))
    if json.dumps(config, sort_keys=True) != json.dumps(CONFIG, sort_keys=True):
        raise ValueError('Only the exact inert synthetic configuration is accepted')
    if args.run_root is None:
        parser.error('--run-root must name a NEW disposable directory below an existing parent')
    result = run(args.run_root, args.scenario)
    print(json.dumps(result, indent=2))
    if not result['scenario_passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
