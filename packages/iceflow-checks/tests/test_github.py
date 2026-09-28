import copy
import pytest
from iceflow_harness.common import Refused
from iceflow_harness.github import ReadOnlyGitHub, render_pr_metadata

HEAD='1'*40
BASE='2'*40

def fixture(count=1):
    pr={'head':{'sha':HEAD},'base':{'sha':BASE,'repo':{'id':1222526625}},'changed_files':count,
        'state':'open','draft':True,'updated_at':'2026-09-28T00:00:00Z','body':'human text'}
    responses={'': {'id':1222526625,'full_name':'d2kyle113/bingxue-erp'}, '/pulls/1':pr,
               f'/commits/{HEAD}/check-runs?per_page=100&page=1':{'total_count':0,'check_runs':[]}}
    for n in range((count+99)//100):
        responses[f'/pulls/1/files?per_page=100&page={n+1}']=[{'filename':f'backend/f{i}.py','status':'modified','sha':'3'*40} for i in range(n*100,min(count,(n+1)*100))]
    def transport(path): return copy.deepcopy(responses[path])
    return responses, transport

def client(transport, max_reads=20):
    return ReadOnlyGitHub('d2kyle113/bingxue-erp',1222526625,transport=transport,max_reads=max_reads)

def test_paginated_complete_snapshot():
    _, t=fixture(101)
    s=client(t).pr_snapshot(1)
    assert len(s['files'])==101 and s['changed_files']==101
    assert s['authority']=='NONE' and s['release_ready']=='NOT_EVALUATED'
    assert HEAD in render_pr_metadata(s)

def test_head_race_refused():
    responses,t=fixture()
    calls=0
    def changing(path):
        nonlocal calls
        v=t(path)
        if path=='/pulls/1':
            calls+=1
            if calls>1:v['head']['sha']='4'*40
        return v
    with pytest.raises(Refused,match='CHANGED_DURING'): client(changing).pr_snapshot(1)

def test_body_race_refused():
    _,t=fixture(); calls=0
    def changing(path):
        nonlocal calls
        v=t(path)
        if path=='/pulls/1':
            calls+=1
            if calls>1:v['body']='changed approval'
        return v
    with pytest.raises(Refused,match='CHANGED_DURING'): client(changing).pr_snapshot(1)

def test_duplicate_files():
    r,t=fixture(2); r['/pulls/1/files?per_page=100&page=1'][1]=r['/pulls/1/files?per_page=100&page=1'][0]
    with pytest.raises(Refused,match='DUPLICATE'): client(t).pr_snapshot(1)

def test_budget_never_partial_success():
    _,t=fixture(101)
    with pytest.raises(Refused,match='BUDGET'): client(t,max_reads=3).pr_snapshot(1)

def test_wrong_repository_numeric_id():
    r,t=fixture(); r['']['id']=999
    with pytest.raises(Refused,match='REPOSITORY_ID'): client(t).pr_snapshot(1)

def test_api_truncation_refused():
    r,t=fixture();r['/pulls/1']['changed_files']=3001
    with pytest.raises(Refused,match='TRUNCATED'): client(t).pr_snapshot(1)

def test_check_subject_mismatch():
    r,t=fixture()
    r[f'/commits/{HEAD}/check-runs?per_page=100&page=1']={'total_count':1,'check_runs':[{'id':1,'head_sha':BASE}]}
    with pytest.raises(Refused,match='SUBJECT'): client(t).pr_snapshot(1)

@pytest.mark.parametrize('path',['/issues/1/comments','/actions/workflows/1/dispatches','https://evil.invalid','/../../users/me'])
def test_no_write_or_arbitrary_endpoint(path):
    _,t=fixture()
    with pytest.raises(Refused,match='ENDPOINT'): client(t).get(path)

def test_repository_dot_segments():
    with pytest.raises(Refused,match='REPOSITORY_INVALID'): ReadOnlyGitHub('../users',1)
