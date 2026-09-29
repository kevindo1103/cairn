"""Selected-model coverage guards; only synthetic models are executed."""
import sqlite3
from contextlib import closing

import pytest
from iceflow_harness.common import Refused
from iceflow_harness.schema import check_database
from iceflow_harness.sourcechecks import model_columns

MODEL = '''from sqlalchemy import Column, Integer, String
class InventoryMovement(Base):
    __tablename__ = 'inventory_movements'
    id = Column(Integer, primary_key=True)
%s
'''


@pytest.mark.parametrize('body', [
    '    if True:\n        expected_extra = Column(String)',
    '    if FLAG:\n        expected_extra = Column(String)',
    '    if False:\n        pass\n    else:\n        expected_extra = Column(String)',
    '    for unused in [1]:\n        expected_extra = Column(String)',
    '    while FLAG:\n        expected_extra = Column(String)\n        break',
    '    try:\n        expected_extra = Column(String)\n    except Exception:\n        pass',
    '    with CONTEXT:\n        expected_extra = Column(String)',
    '    match FLAG:\n        case 1:\n            expected_extra = Column(String)',
])
def test_r3_class_control_flow_never_silently_omits_columns(body):
    with pytest.raises(Refused, match='MODEL_CONDITIONAL_DECLARATION_UNSUPPORTED'):
        model_columns((MODEL % body).encode(), ['InventoryMovement'])


def test_r3_actual_sqlalchemy_model_has_nested_column(tmp_path):
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase): pass
    model = MODEL % '    if True:\n        expected_extra = Column(String)'
    ns = {'Base': Base}; exec(model, ns)
    assert list(ns['InventoryMovement'].__table__.columns.keys()) == ['id', 'expected_extra']
    db = tmp_path/'synthetic.db'
    with closing(sqlite3.connect(db)) as c, c:
        c.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES ('m1'); CREATE TABLE inventory_movements(id INTEGER);")
    before = db.read_bytes()
    findings = check_database(db, model.encode(), ['InventoryMovement'], 'm1')
    assert any(f['check']=='K04B' and f['status']=='BLOCKED' for f in findings)
    assert not any(f['check']=='K04B' and f['status']=='PASS' for f in findings)
    coverage = next(f for f in findings if f['check']=='K04B_COVERAGE')['details']
    assert coverage['resolved']==[] and coverage['unsupported'][0]['model']=='InventoryMovement'
    assert db.read_bytes()==before


def test_r3_unselected_conditional_model_is_explicitly_excluded(tmp_path):
    model = (MODEL % '') + '''class Unselected(Base):
    __tablename__ = 'unselected'
    if True:
        id = Column(Integer, primary_key=True)
'''
    from iceflow_harness.coverage import inspect_model_scope
    expected, coverage = inspect_model_scope(model.encode(), ['InventoryMovement'])
    assert expected == {'inventory_movements': ['id']}
    assert coverage['unsupported']==[]
    assert coverage['excluded']==[dict(model='Unselected', table='unselected', reason='NOT_SELECTED')]
    assert coverage['other_source_files_and_runtime_mappers']=='NOT_DISCOVERED'


def test_r3_condition_in_normal_method_is_not_a_class_declaration():
    model = MODEL % '    def ordinary(self):\n        if True:\n            return 1'
    assert model_columns(model.encode(), ['InventoryMovement']) == {'inventory_movements':['id']}


def test_r3_existing_mixin_refusal_retained():
    model = (MODEL % '').replace('(Base):', '(Mixin, Base):')
    with pytest.raises(Refused, match='MODEL_INHERITANCE_UNSUPPORTED'):
        model_columns(model.encode(), ['InventoryMovement'])


def test_r3_class_duplicate_not_merged_into_misleading_coverage():
    model = (MODEL % '') + (MODEL % '').split('\n', 1)[1].replace("'inventory_movements'", "'different_table'")
    with pytest.raises(Refused, match='MODEL_CLASS_AMBIGUOUS'):
        model_columns(model.encode(), ['InventoryMovement'])
