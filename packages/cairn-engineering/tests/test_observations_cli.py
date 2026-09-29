import copy
import json
import os
import subprocess
import sys
from pathlib import Path
import pytest

from iceflow_harness.common import Refused,canonical,digest,read_bytes
from iceflow_harness.github import ReadOnlyGitHub
from cairn_engineering.cli import main
from cairn_engineering.observations import local_snapshot,task_snapshot
from cairn_engineering.project import initialize,load_project
from cairn_engineering.checks import run_scan
from cairn_engineering.demo import demo


def fake(data):
    b=data[0]
    def transport(path):
        if path=='':return {'id':b['repository_id'],'full_name':b['repository']}
        if path.startswith('/issues/'):return {'number':b['issue'],'state':'open','body':'not authority','updated_at':'2026-09-28'}
        if path.startswith('/branches/'):return {'name':'main','commit':{'sha':b['main_sha']}}
        if path.startswith('/pulls/'):return {'number':b['pr'],'state':'open','merged':False,'body':'','updated_at':'t',
            'head':{'sha':b['head_sha'],'repo':{'id':b['repository_id']}},'base':{'sha':b['base_sha'],'repo':{'id':b['repository_id']}}}
        raise AssertionError(path)
    return transport


def test_github_observations_read_bounded_and_non_authorizing(data):
    b=data[0];v=task_snapshot(ReadOnlyGitHub(b['repository'],b['repository_id'],transport=fake(data)),b)
    assert v['api_reads']==7 and v['task']['pr']['state']=='open'
    assert v['effective_permissions']==[]


def test_github_head_movement_refused(data):
    b=data[0];n=0;t=fake(data)
    def transport(path):
        nonlocal n
        value=t(path)
        if path.startswith('/pulls/'):
            n+=1
            if n==2:value['head']['sha']='f'*40
        return value
    with pytest.raises(Refused,match='CHANGED_DURING_READ'):
        task_snapshot(ReadOnlyGitHub(b['repository'],b['repository_id'],transport=transport),b)


def test_github_budget_no_retry(data):
    b=data[0];client=ReadOnlyGitHub(b['repository'],b['repository_id'],max_reads=2,transport=fake(data))
    with pytest.raises(Refused,match='BUDGET'):task_snapshot(client,b)
    assert client.reads==2

@pytest.mark.parametrize('path',['/issues/1/comments','/git/refs','/branches/../main','/hooks','/pulls/1/merge'])
def test_new_task_reads_do_not_open_generic_endpoints(path):
    with pytest.raises(Refused,match='ENDPOINT'):ReadOnlyGitHub('a/b',1,transport=lambda _:{}).get(path)


def test_installed_cli_init_doctor_scan_no_target_write(tmp_path,repo,capsys):
    before=subprocess.check_output(['git','-C',str(repo),'status','--porcelain'])
    config=tmp_path/'config'
    assert main(['init','--repo',str(repo),'--out',str(config)])==0
    capsys.readouterr()
    assert main(['doctor','--config',str(config/'project.json')])==0
    capsys.readouterr()
    assert main(['scan','--config',str(config/'project.json')]) in (0,2)
    text=json.loads(capsys.readouterr().out)
    report=json.loads(Path(text['json']).read_bytes())
    assert report['extra']['configuration_sha256']
    assert subprocess.check_output(['git','-C',str(repo),'status','--porcelain'])==before


def test_init_refuses_inside_repo_before_mkdir(repo):
    with pytest.raises(Refused,match='INSIDE'):initialize(repo,repo/'wrong')
    assert not (repo/'wrong').exists()


def test_demo_has_no_store_and_merged_reconciles(tmp_path):
    v=demo(tmp_path/'demo');assert v['cases']['merged_after_compaction']=='PR_ALREADY_MERGED'
    assert not list((tmp_path/'demo').rglob('*.sqlite')) and v['live_ledger_or_task_touched'] is False


def test_actual_git_head_not_old_binding_is_observed(repo,data):
    old=local_snapshot(repo,data[0])
    (repo/'new.py').write_bytes(b'# synthetic')
    assert local_snapshot(repo,data[0])['dirty'] is True
    assert old['dirty'] is False


def test_resume_cli_uses_real_copy_and_git_but_not_remote_fake_as_auth(tmp_path,repo,ledger_copy,data,capsys):
    from cairn_engineering.demo import reseal
    from cairn_engineering.observations import local_snapshot
    b,l,local,g=copy.deepcopy(data)
    from iceflow_harness.gitview import GitView
    view=GitView(repo);b.update(head_sha=view.sha,tree_sha=view.tree)
    # Deliberately stale ledger: resume must not manufacture current checkpoint.
    g['observed_at_unix']=__import__('time').time();g['task']['pr']['head_sha']=view.sha
    (tmp_path/'remote.json').write_bytes(canonical(reseal(g)))
    (tmp_path/'task.json').write_bytes(canonical(b))
    config=tmp_path/'config';initialize(repo,config)
    assert main(['resume','--config',str(config/'project.json'),'--binding',str(tmp_path/'task.json'),
        '--ledger-copy',str(ledger_copy),'--offline-copy','--github-observation',str(tmp_path/'remote.json')])==0
    v=json.loads(capsys.readouterr().out)['result']
    assert v['disposition']=='STALE_CHECKPOINT' and v['effective_permissions']==[]
