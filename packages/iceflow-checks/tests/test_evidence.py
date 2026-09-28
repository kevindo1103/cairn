import hashlib
import json
import sqlite3
from contextlib import closing
import pytest
from iceflow_harness.common import Refused
from iceflow_harness.schema import check_database
from iceflow_harness.junit import inspect_junit
from iceflow_harness.demo import MODEL

@pytest.fixture
def database(tmp_path):
    path = tmp_path / 'synthetic.db'
    with closing(sqlite3.connect(path)) as c, c:
        c.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES ('m58'); CREATE TABLE inventory_movements(id INTEGER);")
    return path

def test_stamp_only_not_parity(database):
    result = check_database(database, MODEL, ['InventoryMovement'], 'm58')
    assert result[0]['status'] == 'PASS'
    assert result[1]['code'] == 'MODEL_MIGRATION_MISMATCH'
    assert result[1]['details']['missing_columns'] == ['inventory_tenant_ref']

def test_wrong_revision(database):
    assert check_database(database, MODEL, ['InventoryMovement'], 'm59')[0]['status'] == 'FAIL'

def test_parity_positive_no_db_change(database):
    with closing(sqlite3.connect(database)) as c, c: c.execute('ALTER TABLE inventory_movements ADD COLUMN inventory_tenant_ref TEXT')
    before = database.read_bytes()
    result = check_database(database, MODEL, ['InventoryMovement'], 'm58')
    assert all(f['status'] == 'PASS' for f in result)
    assert database.read_bytes() == before
    assert result[1]['details']['migration_execution_provenance'] == 'CALLER_SUPPLIED_COPY_NOT_ATTESTED'

@pytest.mark.parametrize('sidecar', ['-wal','-shm','-journal'])
def test_unsettled_db_refused(database, sidecar):
    database.with_name(database.name+sidecar).touch()
    with pytest.raises(Refused, match='NOT_STANDALONE'): check_database(database, MODEL, ['InventoryMovement'], 'm58')

def test_no_alembic_version(database):
    with closing(sqlite3.connect(database)) as c, c: c.execute('DROP TABLE alembic_version')
    with pytest.raises(Refused, match='INSPECTION_FAILED'): check_database(database, MODEL, ['InventoryMovement'], 'm58')

def test_non_database(tmp_path):
    p=tmp_path/'x.db'; p.write_text('not database')
    with pytest.raises(Refused, match='DATABASE_FORMAT'): check_database(p, MODEL, ['InventoryMovement'], 'm58')

def write_xml(tmp_path, text):
    p=tmp_path/'result.xml'; p.write_text(text); return p

def test_junit_failed_name_no_secret(tmp_path):
    p=write_xml(tmp_path, '<testsuite><testcase classname="stock" name="test_use"><failure message="token-canary">secret-sql</failure></testcase></testsuite>')
    f=inspect_junit(p, 'selected', 1)[0]
    assert f['status']=='FAIL'
    assert f['details']['failed_tests'][0]['test_ref']=='stock::test_use'
    assert 'token-canary' not in json.dumps(f) and 'secret-sql' not in json.dumps(f)

def test_junit_skips_not_green(tmp_path):
    p=write_xml(tmp_path, '<testsuite><testcase name="test_a"><skipped/></testcase></testsuite>')
    assert inspect_junit(p,'full',0)[0]['code']=='SKIPS_NOT_ALL_PASS'

def test_junit_failure_exit_preserved(tmp_path):
    p=write_xml(tmp_path,'<testsuite><testcase name="test_a"/></testsuite>')
    assert inspect_junit(p,'full',2)[0]['status']=='FAIL'

def test_junit_empty_not_green(tmp_path):
    p=write_xml(tmp_path,'<testsuite tests="20"/>')
    assert inspect_junit(p,'empty',0)[0]['status']=='FAIL'

def test_junit_positive(tmp_path):
    p=write_xml(tmp_path,'<testsuite><testcase name="test_a"/></testsuite>')
    assert inspect_junit(p,'selected',0)[0]['status']=='PASS'

def test_junit_xxe(tmp_path):
    p=write_xml(tmp_path, '<!DOCTYPE testsuite [<!ENTITY x SYSTEM "file:///etc/passwd">]><testsuite>&x;</testsuite>')
    with pytest.raises(Refused): inspect_junit(p,'x',0)

def test_junit_duplicate_ids(tmp_path):
    p=write_xml(tmp_path,'<testsuite><testcase name="a"/><testcase name="a"/></testsuite>')
    with pytest.raises(Refused,match='DUPLICATE'): inspect_junit(p,'x',0)

def test_junit_valid_xml_but_truncated_count(tmp_path):
    p=write_xml(tmp_path,'<testsuite tests="3"><testcase name="a"/></testsuite>')
    with pytest.raises(Refused,match='COUNTS_INCONSISTENT'): inspect_junit(p,'x',0)

def test_junit_contradictory_case(tmp_path):
    p=write_xml(tmp_path,'<testsuite><testcase name="a"><skipped/><failure/></testcase></testsuite>')
    with pytest.raises(Refused,match='CONTRADICTORY'): inspect_junit(p,'x',0)
