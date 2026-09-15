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
MODES = ('happy', 'receipt_only', 'crash_after_ack', 'duplicate', 'wrong_mapping', 'impersonate')
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


class Pilot:
    def __init__(self, root):
        self.api = dependencies()
        if self.api['verify_package']()['source_commit'] != CORE:
            raise ValueError('Unexpected core pin')
        self.root = exclusive_root(root)
        for name in ('broker', 'worker', 'evidence'):
            (self.root / name).mkdir()
        self.tokens = {name: secrets.token_hex(32) for name in ('owner', 'pm', 'worker')}
        self.mapping = dict(task_id='worker', session_id='synthetic-session-worker', generation=1)
        self.store = self.api['Store'].initialize(self.root / 'broker', PROJECT, 'pm', self.tokens['owner'])
        entries = [self.entry('pm', 'PM'), self.entry('worker', 'worker')]
        self.revision = self.api['Owner'](self.store).replace(self.tokens['owner'], 0, entries)['revision']
        self.adapter = self.api['Adapter'](self.store, FixtureVerifier(), host_identity=self.identity)
        self.call('pm', 'checkpoint')
        self.event = self.call('pm', 'enqueue', dedupe_key='synthetic-single-event', target='worker',
                               kind='APPROVAL', priority=1, dependency=None,
                               next_action='Return synthetic IPC lifecycle evidence')['id']
        self.delivery = self.call('pm', 'claim', event_id=self.event)['delivery_token']
        self.records = []

    def entry(self, task, role):
        grants = ({'checkpoint': ['ABSENT'], 'enqueue': ['ABSENT'], 'claim': ['QUEUED'],
                   'sent': ['QUEUED'], 'get': ['QUEUED', 'SENT', 'ACKED', 'STARTED', 'COMPLETED']}
                  if task == 'pm' else
                  {'reconcile': ['SENT'], 'ack': ['SENT'], 'start': ['ACKED'],
                   'renew': ['STARTED'], 'complete': ['STARTED']})
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
        if token == self.tokens['pm']:
            return dict(task_id='pm', session_id='synthetic-session-pm', generation=1)
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
                           'wrong_mapping': 'SENT', 'impersonate': 'SENT'}
        expected_requests = {'happy': 6, 'duplicate': 8, 'crash_after_ack': 3,
                             'receipt_only': 1, 'wrong_mapping': 2, 'impersonate': 2}
        expected_rejects = 2 if mode == 'duplicate' else int(mode in {'wrong_mapping', 'impersonate'})
        scenario_passed = (stop_reason == 'CHILD_EXIT' and child_pid != os.getpid()
                           and exit_code == (74 if mode == 'crash_after_ack' else 0)
                           and self.state() == expected_states[mode]
                           and completions == int(mode in {'happy', 'duplicate'})
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
        (self.root / 'evidence' / 'result.json').write_text(json.dumps(evidence, indent=2) + '\n', encoding='utf-8')
        return evidence


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
    pilot = Pilot(root)
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
