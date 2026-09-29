"""Review 5876863593: real validator + synthetic source/DB/report contracts.

The existing registry validator is imported from the sibling Cairn source file;
no copied validator, mock authority, Store construction or real session is used.
P01-P16 records below are explicitly synthetic aggregate-contract inputs.
"""
import copy
import hashlib
import importlib.util
import sqlite3
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

import pytest
from iceflow_harness.common import Refused, canonical, digest, finding
from iceflow_harness.report import envelope
from iceflow_harness.schema import check_database
from cairn_engineering.demo import inputs, reseal
from cairn_engineering.evidence import validate_report, HostEvidenceBridge
from cairn_engineering.project import initialize, load_project
from cairn_engineering.resume import reconcile
from cairn_engineering.topology import resolve_role, topology
from cairn_engineering.workflow import load_workflow, validate_workflow

NOW = 2000000000
MODELS = b'''from sqlalchemy import Column, Integer, String
class InventoryMovement(Base):
    __tablename__ = 'inventory_movements'
    id = Column(Integer, primary_key=True)
class WarehouseStock(Base):
    __tablename__ = 'warehouse_stocks'
    id = Column(Integer, primary_key=True)
    inventory_tenant_ref = Column(String)
class InventoryEpoch(Base):
    __tablename__ = 'inventory_epochs'
    id = Column(Integer, primary_key=True)
class InventoryManifest(Base):
    __tablename__ = 'inventory_manifests'
    id = Column(Integer, primary_key=True)
class InventoryTransaction(Base):
    __tablename__ = 'inventory_transactions'
    id = Column(Integer, primary_key=True)
'''


@pytest.fixture
def existing_validator(monkeypatch):
    packages = Path(__file__).resolve().parents[2]
    # This is an explicit source integration test, not installed-core evidence.
    monkeypatch.syspath_prepend(str(packages / 'communication-ledger'))
    p = packages / 'cairn-adapter/cairn_adapter/store.py'
    assert p.is_file(), 'Actual sibling Cairn adapter source required; no mock fallback'
    raw = p.read_bytes().replace(b'\r\n', b'\n')
    assert hashlib.sha1(b'blob '+str(len(raw)).encode()+b'\0'+raw).hexdigest() == 'a0c6102909ad0e16921cafce55bea1c615edd4de'
    spec = importlib.util.spec_from_file_location('pr22_actual_registry_validator', p)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def registry_entry(b, role='worker'):
    binding = dict(repository=b['repository'], worktree='synthetic-worktree', branch='synthetic',
                   rule_version='synthetic-v1', config_version='synthetic-v1')
    return dict(task_id=b['task_id'], session_id=b['session_id'], generation=1, state='active',
                credential_hash=hashlib.sha256(b'synthetic-worker-not-a-live-token').hexdigest(),
                role=role, project=b['repository'], scopes=[b['scope']], authority=['get'],
                grants=[dict(command='get', scope=b['scope'], states=['STARTED'])],
                bindings={b['scope']: binding}, successor=None, quiescence=None,
                worktree=binding['worktree'], branch=binding['branch'], rule_version='synthetic-v1',
                config_version='synthetic-v1', parent=None, owner='synthetic-lead',
                expected_output='synthetic readback', stop_condition='no live operations',
                inventory=dict(complete=False, unfinished_work=[], prs=[], issues=[], blockers=[],
                               readback_digest=None))


@pytest.mark.parametrize('role,workflow,step', [
    ('backend_dev', 'backend-bugfix', 'implement'),
    ('frontend_dev', 'ui-api-feature', 'frontend'),
    ('qc_dev', 'backend-bugfix', 'verify')])
def test_r1_actual_canonical_worker_resolves_and_resumes(existing_validator, role, workflow, step):
    b, ledger, local, remote = inputs(NOW)
    w = load_workflow(workflow)
    b.update(workflow=workflow, workflow_digest=digest(canonical(w)), step_id=step, owner_role=role)
    entry = registry_entry(b)
    before = copy.deepcopy(entry)
    existing_validator.validate_entries([entry], [], 'a'*64)
    registry = dict(revision=1, entries=[entry])
    bindings = {role: [{k: entry[k] for k in ('task_id', 'session_id', 'generation')}]}
    assert resolve_role(role, bindings, registry=registry)['task_id'] == b['task_id']
    ledger['registry'] = registry
    result = reconcile(b, reseal(ledger), local, remote, now=NOW)
    assert result['disposition'] == 'RESUME_CANDIDATE'
    assert result['authority'] == 'NONE' and result['effective_permissions'] == []
    assert entry == before


def test_r1_all_advertised_roles_admitted_by_actual_validator(existing_validator):
    b = inputs(NOW)[0]
    for definition in topology()['roles'].values():
        for role in definition['registry_roles']:
            existing_validator.validate_entries([registry_entry(b, role)], [], 'a'*64)


@pytest.mark.parametrize('alias', ['Dev', 'Worker', 'Designer'])
def test_r1_invented_alias_is_not_a_registry_migration(existing_validator, alias):
    b = inputs(NOW)[0]
    with pytest.raises(existing_validator.Rejected, match='canonical role'):
        existing_validator.validate_entries([registry_entry(b, alias)], [], 'a'*64)


def db_copy(tmp_path, *, complete=True):
    db = tmp_path / 'synthetic.db'
    suffix = ', inventory_tenant_ref TEXT' if complete else ''
    with closing(sqlite3.connect(db)) as c, c:
        c.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES ('m1'); "
                        "CREATE TABLE inventory_movements(id INTEGER); CREATE TABLE inventory_epochs(id INTEGER); "
                        "CREATE TABLE inventory_manifests(id INTEGER); CREATE TABLE warehouse_stocks(id INTEGER"+suffix+");")
    return db


def schema_findings(tmp_path, *, expected='m1', complete=True, classes=None):
    return check_database(db_copy(tmp_path, complete=complete), MODELS,
                          classes or ['InventoryMovement', 'WarehouseStock', 'InventoryEpoch', 'InventoryManifest'], expected)


def report_case(findings):
    b = inputs(NOW)[0]
    w = load_workflow('inventory-migration')
    b.update(workflow=w['id'], workflow_digest=digest(canonical(w)), step_id='verify', owner_role='qc_dev')
    # These P records deliberately exercise the aggregate parser. No native P
    # test ran, and the resulting receipt grants no permission.
    p = [finding(f'P{i:02d}', 'PASS', 'SYNTHETIC_NOT_EXECUTED') for i in range(1, 17)]
    r = envelope('schema', findings + p,
                 dict(commit_sha=b['head_sha'], tree_sha=b['tree_sha'], working_tree_dirty=False),
                 dict(configuration_sha256='f'*64, candidate_coverage='COMMITTED_TREE_ONLY'))
    r['created_at'] = datetime.fromtimestamp(NOW, timezone.utc).isoformat()
    r.pop('report_digest_sha256'); r['report_digest_sha256'] = digest(canonical(r))
    return b, w, r


def evaluate(case):
    b, w, r = case; raw = canonical(r)
    return validate_report(raw, file_sha256=digest(raw), binding=b, workflow=w,
                           config_sha256='f'*64, now=NOW)


@pytest.mark.parametrize('complete,verdict', [(False, 'REJECTED'), (True, 'ACCEPTED')])
def test_r2_init_default_covers_non_movement_missing_column(repo, tmp_path, complete, verdict):
    output = tmp_path / 'config'
    initialize(repo, output)
    _, cfg = load_project(output/'project.json')
    assert 'WarehouseStock' in cfg['model_classes']
    findings = schema_findings(tmp_path, complete=complete, classes=cfg['model_classes'])
    result = evaluate(report_case(findings))
    assert result['step_result'] == verdict
    if not complete:
        row = next(f for f in findings if f.get('details', {}).get('table') == 'warehouse_stocks')
        assert row['status'] == 'FAIL' and row['details']['missing_columns'] == ['inventory_tenant_ref']


def test_r2_narrow_report_cannot_satisfy_inventory_workflow(tmp_path):
    findings = schema_findings(tmp_path, classes=['InventoryMovement'])
    assert all(f['status'] == 'PASS' for f in findings)
    assert evaluate(report_case(findings))['step_result'] == 'REJECTED'


def test_r2_absent_coverage_is_rejected_even_all_check_ids_pass(tmp_path):
    findings = schema_findings(tmp_path)
    findings = [f for f in findings if f['check'] != 'K04B_COVERAGE']
    findings.append(finding('K04B_COVERAGE', 'PASS', 'SYNTHETIC_NO_COVERAGE'))
    assert evaluate(report_case(findings))['step_result'] == 'REJECTED'


@pytest.mark.parametrize('mutation', ['missing_table', 'wrong_table', 'wrong_model', 'columns', 'unsupported', 'duplicate'])
def test_r2_coverage_and_rows_must_match(tmp_path, mutation):
    findings = schema_findings(tmp_path)
    coverage = next(f for f in findings if f['check'] == 'K04B_COVERAGE')['details']
    rows = [f for f in findings if f['check'] == 'K04B']
    if mutation == 'missing_table': findings.remove(rows[-1])
    elif mutation == 'wrong_table': rows[-1]['details']['table'] = 'different_table'
    elif mutation == 'wrong_model': rows[-1]['details']['model'] = 'Unknown'
    elif mutation == 'columns': rows[-1]['details']['inspected_column_names'] = ['id']
    elif mutation == 'unsupported': coverage['unsupported'] = [dict(model='WarehouseStock', reason='UNRESOLVED')]
    else: findings.append(copy.deepcopy(rows[-1]))
    assert evaluate(report_case(findings))['step_result'] == 'REJECTED'


@pytest.mark.parametrize('expected,verdict', [('m2', 'REJECTED'), ('m1', 'ACCEPTED')])
def test_r4_actual_revision_check_is_a_prerequisite(tmp_path, expected, verdict):
    findings = schema_findings(tmp_path, expected=expected)
    assert next(f for f in findings if f['check']=='K04')['status'] == ('FAIL' if expected=='m2' else 'PASS')
    assert all(f['status']=='PASS' for f in findings if f['check']=='K04B')
    assert evaluate(report_case(findings))['step_result'] == verdict


def test_r4_known_revision_failure_never_completes_adapter(tmp_path):
    b, w, r = report_case(schema_findings(tmp_path, expected='m2'))
    calls = []
    bridge = HostEvidenceBridge(lambda *a: calls.append(a), lambda raw: calls.append(raw),
                                binding=b, workflow=w, config_sha256='f'*64, clock=lambda:NOW)
    with pytest.raises(Refused, match='CHECK_NOT_ACCEPTED'):
        bridge.complete_check(report=canonical(r), report_sha256=digest(canonical(r)), worker_token='synthetic')
    assert calls == []


def test_r4_unrelated_diagnostic_failure_not_global_veto(tmp_path):
    findings = schema_findings(tmp_path)
    findings.append(finding('UNRELATED_DIAGNOSTIC', 'FAIL', 'SYNTHETIC'))
    result = evaluate(report_case(findings))
    assert result['step_result']=='ACCEPTED' and result['check_outcome']=='FAIL'


def test_r4_missing_native_p_proofs_are_still_rejected(tmp_path):
    case = report_case(schema_findings(tmp_path))
    r = case[2]
    r['findings'] = [f for f in r['findings'] if f['check'] != 'P16']
    r['counts']['PASS'] -= 1
    r.pop('report_digest_sha256'); r['report_digest_sha256'] = digest(canonical(r))
    assert evaluate(case)['step_result']=='REJECTED'


def test_r4_coverage_contract_cannot_drop_revision_prerequisite():
    w = load_workflow('inventory-migration')
    w['steps'][2]['acceptance']['checks'].remove('K04')
    with pytest.raises(Refused, match='COVERAGE_PREREQUISITES_REQUIRED'): validate_workflow(w)


def test_s1b_former_two_model_report_cannot_satisfy_four_model_step(tmp_path):
    findings = schema_findings(tmp_path, classes=['InventoryMovement', 'WarehouseStock'])
    assert all(f['status'] == 'PASS' for f in findings)
    assert evaluate(report_case(findings))['step_result'] == 'REJECTED'


@pytest.mark.parametrize('missing_model', ['InventoryEpoch', 'InventoryManifest'])
def test_s1b_omitted_epoch_or_manifest_never_completes_adapter(tmp_path, missing_model):
    names = ['InventoryMovement', 'WarehouseStock', 'InventoryEpoch', 'InventoryManifest']
    names.remove(missing_model)
    b, w, r = report_case(schema_findings(tmp_path, classes=names))
    assert r['outcome'] == 'CHECKED_SCOPE_ONLY'
    calls = []
    bridge = HostEvidenceBridge(lambda *a: calls.append(a), lambda raw: calls.append(raw),
                                binding=b, workflow=w, config_sha256='f'*64, clock=lambda:NOW)
    with pytest.raises(Refused, match='CHECK_NOT_ACCEPTED'):
        bridge.complete_check(report=canonical(r), report_sha256=digest(canonical(r)), worker_token='synthetic')
    assert calls == []


def test_s1b_inventory_template_binds_four_model_revision_explicitly():
    w = load_workflow('inventory-migration')
    assert w['version'] == 3
    verify = next(s for s in w['steps'] if s['id'] == 'verify')['acceptance']
    assert verify['model_coverage'] == 'bingxue-movement-stock-v2'
    assert set(verify['checks']) == {'K04', 'K04B', 'K04B_COVERAGE', *(f'P{i:02d}' for i in range(1,17))}
    verify['model_coverage'] = 'bingxue-movement-stock-v1'
    with pytest.raises(Refused, match='MODEL_COVERAGE_CONTRACT_UNKNOWN'):
        validate_workflow(w)
