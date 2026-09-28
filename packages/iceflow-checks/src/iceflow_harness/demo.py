from __future__ import annotations
import json
import sqlite3
from contextlib import closing
from pathlib import Path
from .common import Refused, no_symlinks, write_new
from .junit import inspect_junit
from .report import envelope, save_report
from .schema import check_database
from .sourcechecks import workflow_check

MODEL = b'''from sqlalchemy import Column, Integer, String
class InventoryMovement(Base):
    __tablename__ = "inventory_movements"
    id = Column(Integer, primary_key=True)
    inventory_tenant_ref = Column(String(128), nullable=True)
'''


def run_demo(output: Path) -> dict:
    output = no_symlinks(output)  # Refuse aliases BEFORE any mkdir/side effect.
    if output.exists():
        raise Refused("OUTPUT_EXISTS")
    output.mkdir(parents=True)
    good_yml = b'name: CI\non: [pull_request]\njobs:\n  test:\n    runs-on: ubuntu-latest\n    steps: [{run: "echo test"}]\n'
    bad_yml = good_yml + b'  test:\n    runs-on: ubuntu-latest\n'
    write_new(output / 'good.yml', good_yml)
    write_new(output / 'bad.yml', bad_yml)
    db = output / 'synthetic.db'
    with closing(sqlite3.connect(db)) as con, con:
        con.executescript("CREATE TABLE alembic_version(version_num TEXT); INSERT INTO alembic_version VALUES ('m58'); CREATE TABLE inventory_movements(id INTEGER);")
    junit = output / 'synthetic-junit.xml'
    write_new(junit, b'<testsuite tests="1"><testcase classname="inventory" name="test_depletion"><failure message="secret-canary">secret-canary</failure></testcase></testsuite>')
    bad = workflow_check(bad_yml, '.github/workflows/ci.yml') + check_database(db, MODEL, ['InventoryMovement'], 'm58') + inspect_junit(junit, 'synthetic', 1)
    bad_report = save_report(envelope('demo-bad', bad, extra={'synthetic_only': True}), output / 'reports')
    with closing(sqlite3.connect(db)) as con, con:
        con.execute('ALTER TABLE inventory_movements ADD COLUMN inventory_tenant_ref VARCHAR(128)')
    good = workflow_check(good_yml, '.github/workflows/ci.yml') + check_database(db, MODEL, ['InventoryMovement'], 'm58')
    good_report = save_report(envelope('demo-fixed', good, extra={'synthetic_only': True}), output / 'reports')
    return {'demo': 'synthetic-only', 'bad_report': str(bad_report / 'report.html'),
            'fixed_report': str(good_report / 'report.html'), 'real_erp_or_production_test': False}
