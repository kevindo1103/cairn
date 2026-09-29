"""Probe unit/transport regressions; these are NOT native Docker/ERP tests."""
import json
import os
import sys
import types
from importlib.resources import files
from pathlib import Path
from subprocess import CompletedProcess

import pytest

from iceflow_harness import probe_protocol
from iceflow_harness.common import Refused
from iceflow_harness.config import default_config
from iceflow_harness.gitview import GitView
from iceflow_harness.probe import export_probe, run_probe


class TenantContextRefused(RuntimeError):
    pass


@pytest.fixture
def worker(monkeypatch):
    # The exported worker imports the very same stdlib-only protocol as the runner.
    monkeypatch.setitem(sys.modules, 'probe_protocol', probe_protocol)
    monkeypatch.setattr(sys, 'dont_write_bytecode', sys.dont_write_bytecode)
    for key in ('ENV', 'ENVIRONMENT', 'DEFAULT_TENANT_ID', 'BINGXUE_ALEMBIC_CALLER_CLASS',
                'TENANTS_DIR', 'PYTHONDONTWRITEBYTECODE'):
        monkeypatch.delenv(key, raising=False)
    module = types.ModuleType('synthetic_probe_worker_under_test')
    data = files('iceflow_harness.data').joinpath('probe_worker.py.txt').read_text()
    exec(compile(data, 'probe_worker.py', 'exec'), module.__dict__)
    return module


def mirrored_settings_admission(env):
    """Minimal oracle mirrored from pinned ERP config.py/env.py, NOT an ERP import."""
    if env.get('ENVIRONMENT', 'dev') != 'test':
        raise TenantContextRefused('tenant-context-refused:settings-environment')
    if env.get('DEFAULT_TENANT_ID', 'bingxue-ocp1') != 'harness-fixture':
        raise TenantContextRefused('tenant-context-refused:settings-tenant')


def test_old_env_fails_before_revision_and_new_env_binds(worker):
    old = {'ENV': 'test', 'BINGXUE_ALEMBIC_CALLER_CLASS': 'SYNTHETIC_TEST_V1',
           'TENANTS_DIR': '/work/tenants', 'PYTHONDONTWRITEBYTECODE': '1'}
    with pytest.raises(TenantContextRefused, match='settings-environment'):
        mirrored_settings_admission(old)
    with pytest.raises(TenantContextRefused, match='settings-tenant'):
        mirrored_settings_admission({**old, 'ENVIRONMENT': 'test'})
    worker.configure_environment(Path('/work/tenants'))
    mirrored_settings_admission(os.environ)
    assert os.environ['ENV'] == os.environ['ENVIRONMENT'] == 'test'
    assert os.environ['DEFAULT_TENANT_ID'] == 'harness-fixture'
    assert os.environ['BINGXUE_ALEMBIC_CALLER_CLASS'] == 'SYNTHETIC_TEST_V1'


def test_environment_override_cannot_retarget_fixture(worker, monkeypatch):
    monkeypatch.setenv('ENVIRONMENT', 'production')
    monkeypatch.setenv('DEFAULT_TENANT_ID', 'synthetic-wrong-tenant')
    worker.configure_environment(Path('/work/tenants'))
    mirrored_settings_admission(os.environ)
    assert os.environ['TENANTS_DIR'] == str(Path('/work/tenants'))


@pytest.mark.parametrize('suffix,reason', [
    ('settings-environment', 'TENANT_SETTINGS_ENVIRONMENT_MISMATCH'),
    ('settings-tenant', 'TENANT_SETTINGS_TENANT_MISMATCH'),
    ('settings-root', 'TENANT_SETTINGS_ROOT_MISMATCH'),
    ('caller', 'TENANT_CONTEXT_REFUSED')])
def test_finite_tenant_codes(suffix, reason):
    result = probe_protocol.failure(TenantContextRefused('tenant-context-refused:' + suffix), 'ALEMBIC_UPGRADE')
    assert probe_protocol.validate_result(result)['diagnostic']['reason'] == reason


@pytest.mark.parametrize('exc,reason', [
    (ModuleNotFoundError('canary-password'), 'DEPENDENCY_IMPORT_FAILED'),
    (PermissionError('canary-password'), 'PROBE_PERMISSION_DENIED'),
    (FileNotFoundError('canary-password'), 'PROBE_FILE_MISSING'),
    (OSError('canary-password'), 'PROBE_OS_ERROR'),
    (TimeoutError('canary-password'), 'PROBE_TIMEOUT'),
    (SystemExit('canary-password'), 'PROBE_PROCESS_EXIT'),
    (KeyboardInterrupt('canary-password'), 'PROBE_INTERRUPTED'),
    (RuntimeError('MODEL_CREATE_ALL_FORBIDDEN_IN_PARITY_FIXTURE'), 'MODEL_CREATE_ALL_FORBIDDEN'),
    (RuntimeError('PROBE_DB_MISSING'), 'PROBE_DB_MISSING'),
    (RuntimeError('canary-password'), 'MIGRATION_SETUP_FAILED'),
])
def test_exception_classification_has_no_raw_message(exc, reason):
    result = probe_protocol.failure(exc, 'ALEMBIC_UPGRADE')
    assert probe_protocol.validate_result(result)['diagnostic']['reason'] == reason
    assert 'canary-password' not in json.dumps(result)


def test_exception_str_is_never_called():
    class BadMessage(Exception):
        def __str__(self):
            raise AssertionError('unsafe-message-renderer')
    result = probe_protocol.failure(BadMessage('postgres://user:canary-password@db'), 'COPY_SOURCE')
    assert result['diagnostic']['exception_class'] == 'OtherException'
    assert 'canary-password' not in json.dumps(result)


def test_guard_is_not_misreported_as_migration(worker, capsys):
    def denied(state):
        return probe_protocol.blocked('SANDBOX_REQUIRED', 'SANDBOX_CHECK')
    worker.work = denied
    result = worker.capture()
    assert result['diagnostic']['reason'] == 'SANDBOX_REQUIRED'
    assert capsys.readouterr().out == ''


def test_worker_captures_phase_and_hides_stdout_stderr(worker, capsys):
    def fail(state):
        state['phase'] = 'ALEMBIC_UPGRADE'
        print('stdout-canary')
        print('stderr-canary', file=sys.stderr)
        raise TenantContextRefused('tenant-context-refused:settings-environment')
    worker.work = fail
    result = worker.capture()
    assert result['diagnostic']['phase'] == 'ALEMBIC_UPGRADE'
    assert result['diagnostic']['reason'] == 'TENANT_SETTINGS_ENVIRONMENT_MISMATCH'
    captured = capsys.readouterr()
    assert 'canary' not in captured.out + captured.err + json.dumps(result)


def test_no_create_all_fallback(worker):
    with pytest.raises(RuntimeError, match='MODEL_CREATE_ALL_FORBIDDEN'):
        worker.forbid_model_ddl()


def test_export_uses_same_protocol_source(repo, tmp_path):
    destination = tmp_path / 'context'
    export_probe(GitView(repo[0]), destination)
    assert (destination / 'probe_protocol.py').read_bytes() == files('iceflow_harness').joinpath('probe_protocol.py').read_bytes()
    assert 'ENVIRONMENT=\'test\'' in (destination / 'probe_worker.py').read_text()
    assert not (destination / '.git').exists()


@pytest.mark.parametrize('corrupt', [
    {'schema': 'migration-probe-v1', 'status': 'MIGRATION_SETUP_FAILED'},
    {'schema': probe_protocol.SCHEMA, 'status': 'SOME_NEW_STATUS'},
    {'schema': probe_protocol.SCHEMA, 'status': 'BLOCKED', 'diagnostic': {}},
    {'schema': probe_protocol.SCHEMA, 'status': 'MIGRATED', 'revisions': ['m1'], 'tables': []},
    {'schema': probe_protocol.SCHEMA, 'status': 'MIGRATED', 'revisions': ['m1', 'm1'], 'tables': {'x': ['id']}},
    {'schema': probe_protocol.SCHEMA, 'status': 'MIGRATED', 'revisions': ['m1'], 'tables': {'x': ['id', 'id']}},
])
def test_bad_protocol_never_becomes_green(corrupt):
    with pytest.raises(ValueError, match='PROBE_RESULT_INVALID'):
        probe_protocol.validate_result(corrupt)


@pytest.mark.parametrize('key,value', [('stderr', 'secret-canary'), ('phase', 'secret-canary'),
                                      ('exception_class', 'secret-canary'), ('reason', 'secret-canary')])
def test_diagnostics_allowlist_rejects_unknown_fields(key, value):
    result = probe_protocol.blocked('MIGRATION_SETUP_FAILED', 'ALEMBIC_UPGRADE', 'RuntimeError')
    result['diagnostic'][key] = value
    with pytest.raises(ValueError):
        probe_protocol.validate_result(result)


def fake_transport(monkeypatch, payload):
    def transport(command, **kwargs):
        assert kwargs['check'] is False
        assert 'GH_TOKEN' not in kwargs['env'] and 'GITHUB_TOKEN' not in kwargs['env']
        if command[:2] == ['docker', 'run']:
            assert '--network=none' in command and '--read-only' in command
            return CompletedProcess(command, 0, json.dumps(payload).encode(), b'')
        assert command[:3] == ['docker', 'rm', '-f']
        return CompletedProcess(command, 0, b'', b'')
    monkeypatch.setattr('iceflow_harness.probe.subprocess.run', transport)


def test_runner_preserves_structured_failure(repo, tmp_path, monkeypatch):
    view = GitView(repo[0])  # construct before mocking subprocess for Docker
    cfg = default_config(repo[0], tmp_path / 'reports')
    view.preload(list(view.entries))
    payload = probe_protocol.blocked('TENANT_SETTINGS_ENVIRONMENT_MISMATCH', 'ALEMBIC_UPGRADE', 'TenantContextRefused')
    fake_transport(monkeypatch, payload)
    result = run_probe(view, cfg, 'sha256:' + 'a' * 64)
    assert len(result) == 1 and result[0]['status'] == 'BLOCKED'
    detail = result[0]['details']
    assert detail['diagnostic'] == payload['diagnostic']
    assert detail['parity_evaluated'] is False and detail['auto_ddl_fallback'] is False
    assert detail['source_sha'] == view.sha


@pytest.mark.parametrize('columns,status', [(['id'], 'FAIL'), (['id', 'inventory_tenant_ref'], 'PASS')])
def test_runner_still_computes_column_parity(repo, tmp_path, monkeypatch, columns, status):
    view = GitView(repo[0])
    cfg = default_config(repo[0], tmp_path / 'reports')
    view.preload(list(view.entries))
    fake_transport(monkeypatch, {'schema': probe_protocol.SCHEMA, 'status': 'MIGRATED',
                                'revisions': ['m1'], 'tables': {'inventory_movements': columns, 'warehouse_stocks': ['id'], 'inventory_epochs': ['id'], 'inventory_manifests': ['id']}})
    result = run_probe(view, cfg, 'sha256:' + 'a' * 64)
    assert result[0]['check'] == 'K04' and result[0]['status'] == 'PASS'
    row = next(f for f in result if f['check'] == 'K04B' and f['details']['table'] == 'inventory_movements')
    assert row['status'] == status
    assert row['details']['adversarial_source_attestation'] == 'NOT_PROVEN'


def test_runner_unknown_state_is_invalid_not_migration_failure(repo, tmp_path, monkeypatch):
    view = GitView(repo[0]); view.preload(list(view.entries))
    fake_transport(monkeypatch, {'schema': probe_protocol.SCHEMA, 'status': 'READY'})
    with pytest.raises(Refused, match='DOCKER_PROBE_RESULT_INVALID'):
        run_probe(view, default_config(repo[0], tmp_path / 'reports'), 'sha256:' + 'a' * 64)
