import copy
import json
import sqlite3
import subprocess
from contextlib import closing
from pathlib import Path

import pytest
from iceflow_harness.common import canonical,digest
from cairn_engineering.demo import inputs,reseal

@pytest.fixture
def data():return inputs()

@pytest.fixture
def ledger_copy(tmp_path,data):
    """Frozen core schema-1-shaped fixture, NOT a claim to execute core code."""
    b,s,_,_=data;p=tmp_path/'synthetic-ledger.sqlite'
    fields={'id':'TEXT PRIMARY KEY','payload':'TEXT','digest':'TEXT','target':'TEXT','state':'TEXT',
            'worker_owner':'TEXT','worker_until':'REAL','ack_deadline':'REAL','attempts':'INTEGER',
            'needs_inspection':'INTEGER','eligible_at':'REAL','receipt':'TEXT','result_evidence':'TEXT'}
    with closing(sqlite3.connect(p)) as db,db:
        db.execute('CREATE TABLE config(key TEXT PRIMARY KEY,value TEXT NOT NULL)')
        db.execute("INSERT INTO config VALUES ('schema_version','1')")
        db.execute("INSERT INTO config VALUES ('adapter:registry',?)",(canonical(s['registry']).decode(),))
        db.execute('CREATE TABLE events('+','.join(k+' '+v for k,v in fields.items())+')')
        db.execute('CREATE TABLE checkpoints(issue TEXT,scope TEXT,checkpoint TEXT,base TEXT,head TEXT,revision INTEGER)')
        db.execute('CREATE TABLE recipients(task TEXT,busy INTEGER,active_event TEXT)')
        for e in s['events']:
            row=dict(e,payload=canonical(e['payload']).decode(),digest=digest(canonical(e['payload'])))
            db.execute('INSERT INTO events VALUES ('+','.join('?' for _ in fields)+')',tuple(row.get(k) for k in fields))
        for cp in s['checkpoints']:db.execute('INSERT INTO checkpoints VALUES (?,?,?,?,?,?)',tuple(cp[k] for k in ('issue','scope','checkpoint','base','head','revision')))
        for r in s['recipients']:db.execute('INSERT INTO recipients VALUES (?,?,?)',tuple(r[k] for k in ('task','busy','active_event')))
    return p

@pytest.fixture
def repo(tmp_path):
    path=tmp_path/'erp';path.mkdir()
    def git(*args):return subprocess.check_output(['git','-C',str(path),*args],stderr=subprocess.DEVNULL).decode().strip()
    git('init','-b','main');git('config','user.email','synthetic@example.invalid');git('config','user.name','Synthetic')
    git('config','core.autocrlf','false');git('remote','add','origin','https://github.com/d2kyle113/bingxue-erp.git')
    (path/'.github/workflows').mkdir(parents=True)
    (path/'.github/workflows/test.yml').write_bytes(b'on: [pull_request]\njobs:\n  tests:\n    runs-on: ubuntu-latest\n    steps: [{run: "echo synthetic"}]\n')
    (path/'backend/alembic/versions').mkdir(parents=True)
    (path/'backend/alembic/versions/m1.py').write_bytes(b"revision='m1'\ndown_revision=None\n")
    (path/'backend/models.py').write_bytes(b"from sqlalchemy import Column,Integer\nclass InventoryMovement(Base):\n    __tablename__='inventory_movements'\n    id=Column(Integer,primary_key=True)\n")
    (path/'AGENTS.md').write_bytes(b'Read this router.\n');(path/'CLAUDE.md').write_bytes(b'See AGENTS.md\n')
    (path/'backend/tests').mkdir();(path/'backend/tests/test_example.py').write_bytes(b'def test_synthetic():\n    assert True\n')
    git('add','.');git('commit','-m','synthetic fixture')
    return path
