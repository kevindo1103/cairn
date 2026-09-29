"""H2/H3 regression controls; Windows attributes here are synthetic, not native Windows."""
import os
import sqlite3
from contextlib import closing
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

from iceflow_harness.common import Refused, no_symlinks, outside, write_new
from iceflow_harness.schema import check_database
from iceflow_harness.sourcechecks import model_columns

CONSTANT_MODEL = b'''from sqlalchemy import Column, Integer
PHYSICAL_COLUMN = "physical_id"
class Item(Base):
    __tablename__ = "items"
    logical_id = Column(PHYSICAL_COLUMN, Integer, primary_key=True)
'''


def database_with(tmp_path, column):
    db = tmp_path / 'fixture.db'
    with closing(sqlite3.connect(db)) as c, c:
        c.executescript("CREATE TABLE alembic_version(version_num TEXT); "
                        "INSERT INTO alembic_version VALUES ('m1'); "
                        f'CREATE TABLE items("{column}" INTEGER);')
    return db


def test_h3_python_attribute_is_not_physical_column(tmp_path):
    db = database_with(tmp_path, 'logical_id')
    before = db.read_bytes()
    result = check_database(db, CONSTANT_MODEL, ['Item'], 'm1')
    assert result[0]['code'] == 'REVISION_MATCH'
    assert result[1]['status'] == 'FAIL'
    assert result[1]['details']['missing_columns'] == ['physical_id']
    assert db.read_bytes() == before


def test_h3_real_physical_column_passes(tmp_path):
    db = database_with(tmp_path, 'physical_id')
    before = db.read_bytes()
    result = check_database(db, CONSTANT_MODEL, ['Item'], 'm1')
    assert all(x['status'] == 'PASS' for x in result)
    assert db.read_bytes() == before


@pytest.mark.parametrize('expression', ['PHYSICAL_COLUMN', 'name_from_config()', 'other.NAME'])
def test_h3_unknown_positional_name_is_blocked(expression):
    src = ('from sqlalchemy import Column, Integer\nclass Item(Base):\n'
           ' __tablename__="items"\n logical_id=Column(' + expression + ', Integer)\n').encode()
    with pytest.raises(Refused, match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(src, ['Item'])


@pytest.mark.parametrize('arg', [
    'Integer', 'Integer()', 'sa.Integer', 'sa.Integer()', 'I', 'I()',
    'String(24)', 'LargeBinary', 'ForeignKey("other.id")',
])
def test_h3_proven_sqlalchemy_non_name_argument(arg):
    src = ('import sqlalchemy as sa\nfrom sqlalchemy import Column, Integer, String, LargeBinary, ForeignKey\n'
           'from sqlalchemy import Integer as I\nclass Item(Base):\n'
           ' __tablename__="items"\n logical_id=Column(' + arg + ')\n').encode()
    assert model_columns(src, ['Item']) == {'items': ['logical_id']}


@pytest.mark.parametrize('definition,expression', [
    ('PHYSICAL_COLUMN: str = "physical_id"', 'Column(PHYSICAL_COLUMN, Integer)'),
    ('PHYSICAL_COLUMN = "physical_id"', 'Column(Integer, name=PHYSICAL_COLUMN)'),
    ('PHYSICAL_COLUMN = "physical_id"', 'mapped_column(PHYSICAL_COLUMN, Integer)'),
    ('Integer = "physical_id"', 'Column(Integer)'),
])
def test_h3_unambiguous_literal_bindings(definition, expression):
    src = ('from sqlalchemy import Column, Integer\nfrom sqlalchemy.orm import mapped_column\n' + definition + '\n'
           'class Item(Base):\n __tablename__="items"\n logical_id=' + expression + '\n').encode()
    # A type symbol rebound to a string must never be treated as an implicit column name.
    if definition.startswith('Integer ='):
        with pytest.raises(Refused, match='MODEL_COLUMN_UNRESOLVED'):
            model_columns(src, ['Item'])
    else:
        assert model_columns(src, ['Item']) == {'items': ['physical_id']}


@pytest.mark.parametrize('prefix,suffix', [
    ('PHYSICAL_COLUMN = get_name()', ''),
    ('PHYSICAL_COLUMN = "first"\nPHYSICAL_COLUMN = "physical_id"', ''),
    ('PHYSICAL_COLUMN = "physical_id"', '\nPHYSICAL_COLUMN = "other"'),
    ('PHYSICAL_COLUMN = "physical_id"\nif flag:\n PHYSICAL_COLUMN = "other"', ''),
    ('', '\nPHYSICAL_COLUMN = "physical_id"'),
    ('PHYSICAL_COLUMN = "physical_id"\ndef mutate():\n global PHYSICAL_COLUMN\n PHYSICAL_COLUMN = "other"', ''),
])
def test_h3_ambiguous_literal_binding_not_guessed(prefix, suffix):
    src = ('from sqlalchemy import Column, Integer\n' + prefix + '\nclass Item(Base):\n'
           ' __tablename__="items"\n logical_id=Column(PHYSICAL_COLUMN, Integer)' + suffix).encode()
    with pytest.raises(Refused, match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(src, ['Item'])


def test_h3_class_literal_used_in_order():
    src = b'''from sqlalchemy import Column, Integer
class Item(Base):
 __tablename__="items"
 PHYSICAL_COLUMN="physical_id"
 logical_id=Column(PHYSICAL_COLUMN, Integer)
'''
    assert model_columns(src, ['Item']) == {'items': ['physical_id']}


@pytest.mark.parametrize('call', ['Column(*args)', 'Column(Integer, **kwargs)',
                                  'Column(custom_type)', 'Column(make_type())',
                                  'Column("physical_id", Integer, name="other")'])
def test_h3_ambiguous_column_forms_refused(call):
    src = ('from sqlalchemy import Column, Integer\nclass Item(Base):\n __tablename__="items"\n logical_id=' + call).encode()
    with pytest.raises(Refused, match='MODEL_COLUMN_UNRESOLVED'):
        model_columns(src, ['Item'])


@pytest.mark.parametrize('tag', [0xA0000003, 0xA000000C, 0x9000001A])
def test_h2_reparse_attributes_rejected_not_only_symlink(tmp_path, monkeypatch, tag):
    root = tmp_path / 'target'; root.mkdir()
    alias = tmp_path / 'outside-link'; alias.mkdir()
    original = os.lstat
    def fake(path, *args, **kwargs):
        if Path(path) == alias:
            return SimpleNamespace(st_mode=stat.S_IFDIR | 0o755,
                                   st_file_attributes=0x400, st_reparse_tag=tag)
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, 'lstat', fake)
    with pytest.raises(Refused, match='REPARSE_POINT_REFUSED'):
        outside(alias / 'new' / 'report.json', root)


def test_h2_failed_lstat_is_not_no_link(tmp_path, monkeypatch):
    alias = tmp_path / 'unreadable'
    original = os.lstat
    def fake(path, *args, **kwargs):
        if Path(path) == alias:
            raise PermissionError('synthetic-secret-path')
        return original(path, *args, **kwargs)
    monkeypatch.setattr(os, 'lstat', fake)
    with pytest.raises(Refused, match='PATH_IDENTITY_UNAVAILABLE'):
        no_symlinks(alias / 'report.json')


def test_h2_parent_link_cannot_be_normalized_away(tmp_path):
    target = tmp_path / 'target'; target.mkdir()
    alias = tmp_path / 'outside-link'
    try:
        alias.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.fail('LINK_CAPABILITY_REQUIRED: native path assertion NOT_RUN, not PASS')
    with pytest.raises(Refused, match='SYMLINK_REFUSED'):
        no_symlinks(alias / '..' / 'report.json')


def test_h2_containment_uses_resolved_path(tmp_path, monkeypatch):
    root = (tmp_path / 'target'); root.mkdir()
    # Simulate a platform realpath alias (e.g. a short-name path), not a real junction.
    alias = tmp_path / 'alias' / 'report.json'
    real = root / 'report.json'
    resolve = Path.resolve
    def fake(self, *args, **kwargs):
        return real if self == alias else resolve(self, *args, **kwargs)
    monkeypatch.setattr(Path, 'resolve', fake)
    with pytest.raises(Refused, match='OUTPUT_INSIDE_TARGET_REPO'):
        outside(alias, root)


def test_h2_normal_sibling_output_and_no_overwrite(tmp_path):
    root = tmp_path / 'target'; root.mkdir()
    path = outside(tmp_path / 'reports' / 'new' / 'report.json', root)
    write_new(path, b'{}')
    assert path.read_bytes() == b'{}'
    with pytest.raises(Refused, match='OUTPUT_EXISTS'):
        write_new(path, b'overwritten')
    assert not list(root.iterdir())
