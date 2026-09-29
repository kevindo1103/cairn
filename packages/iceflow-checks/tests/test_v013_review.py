"""F1/F2/F3 negatives; source snippets are synthetic and never import ERP."""
import base64
import csv
import hashlib
import io
import json
import os
import sys
import types
import zipfile
from pathlib import Path

import pytest
from iceflow_harness.common import Refused
from iceflow_harness.demo import run_demo
from iceflow_harness.schema import check_database
from iceflow_harness.sourcechecks import model_columns
from test_delivery import delivery, rehash, verifier  # function fixture, no TestCase class

MODEL = '''from sqlalchemy import Column, Integer
from sqlalchemy.orm import mapped_column
class Movement(Base):
    __tablename__ = 'movements'
    logical_id = mapped_column(__name_pos='physical_id', type_=Integer, primary_key=True)
'''


def db_at(tmp_path, column):
    import sqlite3
    from contextlib import closing
    p = tmp_path/'fake.db'
    with closing(sqlite3.connect(p)) as c, c:
        c.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES ('m57'); CREATE TABLE movements("+column+" INTEGER);")
    return p


@pytest.mark.parametrize('where', ['before', 'after', 'conditional'])
def test_f1_wildcard_blocks_binding_even_type_alias(where):
    statement = 'from synthetic_column_names import *\n'
    model = MODEL
    if where == 'before': model = statement + model
    elif where == 'after': model += statement
    else: model = 'if True:\n    '+statement + model
    with pytest.raises(Refused, match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(model.encode(), ['Movement'])


@pytest.mark.parametrize('col,verdict', [('logical_id','FAIL'),('physical_id','PASS')])
def test_f1_name_pos_compares_physical_column(tmp_path, col, verdict):
    f=check_database(db_at(tmp_path,col), MODEL.encode(), ['Movement'], 'm57')
    assert next(x for x in f if x['check']=='K04B')['status']==verdict


def test_f1_name_pos_matches_real_sqlalchemy():
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase): pass
    namespace={'Base':Base}
    exec(MODEL,namespace)
    actual=sorted(namespace['Movement'].__table__.columns.keys())
    assert actual==['physical_id']==model_columns(MODEL.encode(), ['Movement'])['movements']


def test_f1_wildcard_actual_sqlalchemy_is_not_guessed(monkeypatch):
    from sqlalchemy.orm import DeclarativeBase
    class Base(DeclarativeBase): pass
    module=types.ModuleType('synthetic_column_names');module.Integer='physical_id'
    monkeypatch.setitem(sys.modules,'synthetic_column_names',module)
    source="""from sqlalchemy import Column, Integer as SQLInteger
from synthetic_column_names import *
class Movement(Base):
    __tablename__='movements'
    logical_id=Column(Integer, SQLInteger, primary_key=True)
"""
    namespace={'Base':Base};exec(source,namespace)
    assert list(namespace['Movement'].__table__.columns.keys())==['physical_id']
    with pytest.raises(Refused,match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(source.encode(),['Movement'])


@pytest.mark.parametrize('name', ['__name_pos=get_name()', "__name_pos='a', name='b'", "__name_pos=UNKNOWN"])
def test_f1_unresolved_or_conflicting_name_pos(name):
    model=MODEL.replace("__name_pos='physical_id'",name)
    with pytest.raises(Refused,match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(model.encode(), ['Movement'])


def test_f2_demo_refuses_before_mkdir(tmp_path,monkeypatch):
    import iceflow_harness.demo as demo
    output=tmp_path/'not-created'/'nested'
    def reject(path):raise Refused('REPARSE_POINT_REFUSED')
    monkeypatch.setattr(demo,'no_symlinks',reject,raising=False)
    with pytest.raises(Refused,match='REPARSE_POINT_REFUSED'):demo.run_demo(output)
    assert list(tmp_path.iterdir())==[]


def test_f2_demo_real_link_leaves_target_unchanged(tmp_path):
    target=tmp_path/'protected';target.mkdir()
    link=tmp_path/'alias';link.symlink_to(target,target_is_directory=True)
    with pytest.raises(Refused):run_demo(link/'new-demo-output')
    assert list(target.iterdir())==[]


def rewrite_wheel(root,additions):
    release=json.loads((root/'RELEASE.json').read_bytes());p=root/release['artifacts']['wheel']['path']
    with zipfile.ZipFile(p) as z:data={n:z.read(n) for n in z.namelist()}
    data.update(additions)
    name=next(n for n in data if n.endswith('.dist-info/RECORD'))
    output=io.StringIO();writer=csv.writer(output)
    for n,b in data.items():
        if n!=name:writer.writerow([n,'sha256='+base64.urlsafe_b64encode(hashlib.sha256(b).digest()).rstrip(b'=').decode(),len(b)])
    writer.writerow([name,'','']);data[name]=output.getvalue().encode()
    with zipfile.ZipFile(p,'w') as z:
        for n,b in data.items():z.writestr(n,b)
    release['artifacts']['wheel']['sha256']=hashlib.sha256(p.read_bytes()).hexdigest()
    (root/'RELEASE.json').write_text(json.dumps(release));rehash(root)


@pytest.mark.parametrize('name', ['review.pth','outside.py','iceflow_harness-0.1.2.data/purelib/plugin.py',
 'iceflow_harness-0.1.2.data/scripts/start', 'other-1.0.dist-info/METADATA','iceflow_harness-0.1.2.dist-info/unknown'])
def test_f3_wheel_extra_member_consistent_hashes_rejected(delivery,name):
    rewrite_wheel(delivery,{name:b'# synthetic only; never installed\n'})
    with pytest.raises(verifier.InvalidDelivery,match='WHEEL_UNEXPECTED_INSTALL_MEMBER'):
        verifier.verify(delivery)


def test_f3_changed_entrypoint_rejected(delivery):
    rewrite_wheel(delivery,{'iceflow_harness-0.1.2.dist-info/entry_points.txt':b'[console_scripts]\nextra = outside:run\n'})
    with pytest.raises(verifier.InvalidDelivery,match='WHEEL_ENTRYPOINTS_MISMATCH'):verifier.verify(delivery)
