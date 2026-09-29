"""Four-model S1b scope regressions, NOT a replay of ERP seed/migration history.

These disposable SQLite fixtures model only column presence. The 8/5/1 added
column names come from the source-pinned m60 migration below. No ERP module,
seed_local.py, production data, network or migration is executed here.
"""
import json
import sqlite3
from contextlib import closing
from importlib.resources import files
from pathlib import Path

import pytest
import yaml

from iceflow_harness.cli import main
from iceflow_harness.common import Refused
from iceflow_harness.config import load_config, load_yaml
from iceflow_harness.coverage import INVENTORY_COVERAGE_ID, coverage_contract, coverage_satisfied

PROVENANCE = {
    'kind': 'S1B_SHAPED_SYNTHETIC_NOT_ERP_SEED',
    'repository': 'd2kyle113/bingxue-erp',
    'source_sha': 'd211a6ecc417cf34fa30bac8539068f7fe71f1f5',
    'path': 'backend/alembic/versions/m60_inventory_g1_orm_surface_repair.py',
    'blob_sha': '78fe02fd0e5bc61a184f5aec6636941bde10403e',
}
EXPECTED_MODELS = {
    'InventoryMovement': 'inventory_movements',
    'WarehouseStock': 'warehouse_stocks',
    'InventoryEpoch': 'inventory_epochs',
    'InventoryManifest': 'inventory_manifests',
}
# Independent oracle: do not derive expected coverage from the implementation.
MISSING_AT_M58 = {
    'warehouse_stocks': ['inventory_tenant_ref', 'inventory_branch_id',
                         'inventory_scope_identity', 'inventory_epoch_ref',
                         'inventory_epoch_version', 'inventory_mapping_version',
                         'catalog_ref', 'canonical_uom'],
    'inventory_epochs': ['effective_at', 'business_timezone', 'branch_scope_identity',
                         'catalog_uom_snapshot', 'catalog_uom_digest'],
    'inventory_manifests': ['catalog_uom_snapshot_digest'],
}


def synthetic_model_source():
    text = 'from sqlalchemy import Column, Integer, String\n'
    for model, table in EXPECTED_MODELS.items():
        text += f'class {model}(Base):\n    __tablename__ = {table!r}\n    id = Column(Integer, primary_key=True)\n'
        for column in MISSING_AT_M58.get(table, []):
            text += f'    {column} = Column(String)\n'
    text += "class UnrelatedEmployee(Base):\n    __tablename__ = 'employees'\n    id = Column(Integer)\n"
    return text.encode()


def seed_shape(path, revision, missing_tables):
    """Construct a minimal synthetic shape, not ERP seed_local.py output."""
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('CREATE TABLE alembic_version (version_num TEXT)')
        db.execute('INSERT INTO alembic_version VALUES (?)', (revision,))
        for table in EXPECTED_MODELS.values():
            columns = ['id INTEGER']
            if table not in missing_tables:
                columns += ['"' + c + '" TEXT' for c in MISSING_AT_M58.get(table, [])]
            db.execute('CREATE TABLE "' + table + '" (' + ','.join(columns) + ')')


@pytest.mark.parametrize('missing_tables', [
    tuple(MISSING_AT_M58), ('warehouse_stocks',), ('inventory_epochs',),
    ('inventory_manifests',), (),
], ids=['m58-three-tables-8-5-1', 'stock-only', 'epoch-only', 'manifest-only', 'four-models-complete'])
def test_init_to_offline_schema_detects_each_s1b_boundary(repo, tmp_path, capsys, missing_tables):
    root, git = repo
    (root/'backend/models.py').write_bytes(synthetic_model_source())
    revision = 'm58_inventory_movement_scope' if missing_tables else 'm60_inventory_g1_orm_surface_repair'
    (root/'backend/alembic/versions/m1.py').write_text(f'revision={revision!r}\ndown_revision=None\n')
    git('add', '.'); git('commit', '-m', 'Synthetic S1b column-presence contract fixture')
    source_sha = git('rev-parse', 'HEAD')
    config = tmp_path/'new-default.yml'
    assert main(['init', '--repo', str(root), '--out', str(config)]) == 0
    capsys.readouterr()
    cfg = load_config(config)
    assert cfg['model_classes'] == list(EXPECTED_MODELS)
    config_before = config.read_bytes()
    db = tmp_path/'synthetic-offline.sqlite'
    seed_shape(db, revision, missing_tables)
    before = db.read_bytes()
    code = main(['schema', '--config', str(config), '--ref', source_sha,
                 '--db', str(db), '--offline-copy'])
    result = json.loads(capsys.readouterr().out)
    report = json.loads(Path(result['json']).read_bytes())
    rows = {f['details']['table']: f for f in report['findings'] if f['check'] == 'K04B'}
    assert set(rows) == set(EXPECTED_MODELS.values())
    assert next(f for f in report['findings'] if f['check'] == 'K04')['status'] == 'PASS'
    failed = {table: row['details']['missing_columns'] for table, row in rows.items() if row['status'] == 'FAIL'}
    assert failed == {table: sorted(MISSING_AT_M58[table]) for table in missing_tables}
    assert code == (1 if missing_tables else 0)
    assert report['outcome'] == ('FAIL' if missing_tables else 'CHECKED_SCOPE_ONLY')
    assert coverage_satisfied(report['findings'], INVENTORY_COVERAGE_ID) is (not missing_tables)
    scope = next(f for f in report['findings'] if f['check'] == 'K04B_COVERAGE')['details']
    assert scope['unsupported'] == []
    assert scope['excluded'] == [{'model': 'UnrelatedEmployee', 'table': 'employees', 'reason': 'NOT_SELECTED'}]
    assert scope['types_constraints_indexes'] == 'NOT_CHECKED'
    assert all(row['details']['types_constraints_indexes'] == 'NOT_CHECKED' for row in rows.values())
    assert report['source']['commit_sha'] == source_sha
    assert report['authority'] == 'NONE' and report['effective_permissions'] == []
    assert db.read_bytes() == before and config.read_bytes() == config_before
    assert git('status', '--porcelain') == ''


def test_four_model_contract_version_and_defaults_agree():
    assert INVENTORY_COVERAGE_ID == 'bingxue-movement-stock-v2'
    assert coverage_contract(INVENTORY_COVERAGE_ID) == EXPECTED_MODELS
    resource = files('iceflow_harness.data').joinpath('bingxue.yml').read_bytes()
    example = Path(__file__).resolve().parents[1]/'examples/bingxue.yml'
    assert load_yaml(resource)['model_classes'] == list(EXPECTED_MODELS)
    assert load_yaml(example.read_bytes()) == load_yaml(resource)
    with pytest.raises(Refused, match='MODEL_COVERAGE_CONTRACT_UNKNOWN'):
        coverage_contract('bingxue-movement-stock-v1')


def test_existing_two_model_config_is_not_silently_rewritten(repo, tmp_path, capsys):
    root, _ = repo
    cfg_path = tmp_path/'existing.yml'
    assert main(['init', '--repo', str(root), '--out', str(cfg_path)]) == 0
    capsys.readouterr()
    cfg = load_config(cfg_path)
    cfg['model_classes'] = ['InventoryMovement', 'WarehouseStock']
    cfg_path.write_text(yaml.safe_dump(cfg))
    before = cfg_path.read_bytes()
    assert load_config(cfg_path)['model_classes'] == ['InventoryMovement', 'WarehouseStock']
    assert main(['init', '--repo', str(root), '--out', str(cfg_path)]) == 2
    assert cfg_path.read_bytes() == before
