import sqlite3
from contextlib import closing
import pytest
from iceflow_harness.common import Refused
from cairn_engineering.ledger_view import read_ledger_copy
from cairn_engineering.resume import reconcile


def test_copy_read_only_and_no_tokens(ledger_copy,data):
    before=ledger_copy.read_bytes();files=set(ledger_copy.parent.iterdir())
    result=read_ledger_copy(ledger_copy,offline_copy=True,now=2000000000)
    assert result['events'][0]['state']=='STARTED'
    assert 'worker_token' not in str(result) and 'credential_hash' not in str(result)
    assert before==ledger_copy.read_bytes() and files==set(ledger_copy.parent.iterdir())
    assert reconcile(data[0],result,data[2],data[3],now=2000000000)['disposition']=='RESUME_CANDIDATE'

@pytest.mark.parametrize('suffix',['-wal','-shm','-journal'])
def test_copy_sidecars_blocked(ledger_copy,suffix):
    from pathlib import Path
    Path(str(ledger_copy)+suffix).write_bytes(b'synthetic')
    with pytest.raises(Refused,match='SIDECAR'):read_ledger_copy(ledger_copy,offline_copy=True)

def test_requires_explicit_closed_copy(ledger_copy):
    with pytest.raises(Refused,match='OFFLINE'):read_ledger_copy(ledger_copy,offline_copy=False)

def test_missing_copy_does_not_create_database(tmp_path):
    p=tmp_path/'absent'
    with pytest.raises(Refused):read_ledger_copy(p,offline_copy=True)
    assert not p.exists()

def test_no_silent_schema2_upgrade(ledger_copy):
    with closing(sqlite3.connect(ledger_copy)) as db,db:db.execute("UPDATE config SET value='2' WHERE key='schema_version'")
    before=ledger_copy.read_bytes()
    with pytest.raises(Refused,match='SCHEMA_UNSUPPORTED'):read_ledger_copy(ledger_copy,offline_copy=True)
    assert ledger_copy.read_bytes()==before

def test_corrupt_payload_digest_refused(ledger_copy):
    with closing(sqlite3.connect(ledger_copy)) as db,db:db.execute("UPDATE events SET digest=?",('0'*64,))
    with pytest.raises(Refused,match='PAYLOAD_DIGEST'):read_ledger_copy(ledger_copy,offline_copy=True)

def test_no_schema_auto_creation(tmp_path):
    p=tmp_path/'empty.db';p.touch()
    with pytest.raises(Refused,match='SCHEMA_UNSUPPORTED'):read_ledger_copy(p,offline_copy=True)
    assert p.read_bytes()==b''
