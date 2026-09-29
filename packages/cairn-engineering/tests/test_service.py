import copy
import pytest
from iceflow_harness.common import Refused
from cairn_engineering.service import ResumeService
from cairn_engineering.demo import reseal


def test_host_seam_rechecks_before_return_without_mutation(data):
    b,l,s,g=data;calls=[]
    def read(_):calls.append('read');return copy.deepcopy(l)
    service=ResumeService(read,lambda _:s,lambda _:g,clock=lambda:2000000000)
    assert service.observe(b)['disposition']=='RESUME_CANDIDATE'
    assert calls==['read','read']


def test_rs3_registry_race_rejected(data):
    b,l,s,g=data;n=0
    def read(_):
        nonlocal n
        n+=1;v=copy.deepcopy(l)
        if n==2:v['registry']['revision']+=1
        return reseal(v)
    with pytest.raises(Refused,match='LEDGER_SNAPSHOT_MOVED'):
        ResumeService(read,lambda _:s,lambda _:g,clock=lambda:2000000000).observe(b)


def test_rs3_local_race_rejected(data):
    b,l,s,g=data;n=0
    def read(_):
        nonlocal n
        n+=1;v=copy.deepcopy(s)
        if n==2:v['index_sha256']='0'*64
        return v
    with pytest.raises(Refused,match='LOCAL_SOURCE_MOVED'):
        ResumeService(lambda _:l,read,lambda _:g,clock=lambda:2000000000).observe(b)
