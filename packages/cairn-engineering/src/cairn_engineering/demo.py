"""Synthetic observations only. No real session, GitHub account or store is used."""
from __future__ import annotations
import copy
import json
import time
from pathlib import Path

from iceflow_harness.common import canonical, digest, no_symlinks, write_new
from .contracts import seal
from .resume import reconcile
from .workflow import load_workflow, project_workflow


def inputs(now: float = 2000000000.0):
    wf=load_workflow('backend-bugfix')
    b={'schema':'cairn-task-binding-v1','repository':'d2kyle113/bingxue-erp','repository_id':1222526625,
       'issue':999999,'pr':888888,'main_branch':'main','event_id':'synthetic-event',
       'task_id':'synthetic-worker','session_id':'synthetic-session','generation':1,'registry_revision':1,
       'checkpoint_revision':1,'checkpoint':'synthetic-checkpoint','scope':'synthetic-scope',
       'base_sha':'a'*40,'head_sha':'b'*40,'tree_sha':'c'*40,'main_sha':'a'*40,
       'workflow':wf['id'],'workflow_digest':digest(canonical(wf)),'step_id':'implement',
       'owner_role':'backend_dev','allowed_paths':['backend']}
    e={'id':b['event_id'],'target':b['task_id'],'state':'STARTED',
       'payload':{'source_task':'synthetic-lead','target_task':b['task_id'],'issue':str(b['issue']),
                  'scope':b['scope'],'base':b['base_sha'],'head':b['head_sha'],
                  'checkpoint':b['checkpoint'],'kind':'APPROVAL','dependency':None},
       'worker_owner':b['task_id']+'@1','worker_until':now+300,'ack_deadline':None,
       'attempts':1,'needs_inspection':0,'eligible_at':now,'result_evidence':None}
    ledger=seal({'schema':'cairn-ledger-observation-v1','core_schema':1,'events':[e],
        'checkpoints':[{'issue':str(b['issue']),'scope':b['scope'],'checkpoint':b['checkpoint'],
                         'base':b['base_sha'],'head':b['head_sha'],'revision':1}],
        'recipients':[{'task':b['task_id'],'busy':0,'active_event':b['event_id']}],
        'registry':{'revision':1,'entries':[{'task_id':b['task_id'],'session_id':b['session_id'],
            'generation':1,'role':'Dev','state':'active','scopes':[b['scope']]}]},
        'observed_at_unix':now,'origin':'SYNTHETIC_ONLY','authority':'NONE','recovery_executed':False})
    local={'head_sha':b['head_sha'],'tree_sha':b['tree_sha'],'dirty':False,'branch':'synthetic',
           'index_sha256':'e'*64,'changed_paths_digest':'f'*64,'observed_at_unix':now}
    remote=seal({'schema':'cairn-github-task-observation-v1','repository':b['repository'],
        'repository_id':b['repository_id'],'task':{'issue':b['issue'],'issue_state':'open',
         'main_sha':b['main_sha'],'pr':{'number':b['pr'],'state':'open','merged':False,
         'head_sha':b['head_sha'],'base_sha':b['base_sha'],'head_repository_id':b['repository_id'],
         'merge_commit_sha':None}},'observed_at_unix':now,'authority':'NONE','origin':'SYNTHETIC_ONLY'})
    return b,ledger,local,remote


def reseal(value):
    value=copy.deepcopy(value);value.pop('observation_digest',None);return seal(value)


def demo(output: Path):
    output=no_symlinks(output)
    from .contracts import require
    require(not output.exists(),'OUTPUT_EXISTS')
    b,ledger,local,remote=inputs()
    reports={'unchanged':reconcile(b,ledger,local,remote,now=2000000000)}
    merged=copy.deepcopy(remote);merged['task']['pr'].update(state='closed',merged=True,merge_commit_sha='d'*40)
    reports['merged_after_compaction']=reconcile(b,ledger,local,reseal(merged),now=2000000000)
    expired=copy.deepcopy(ledger);expired['events'][0]['worker_until']=1999999999
    reports['expired_lease']=reconcile(b,reseal(expired),local,remote,now=2000000000)
    reports['remote_unavailable']=reconcile(b,ledger,local,None,now=2000000000)
    moved=copy.deepcopy(remote);moved['task']['main_sha']='d'*40
    reports['main_moved']=reconcile(b,ledger,local,reseal(moved),now=2000000000)
    for name,body in reports.items():write_new(output/(name+'.json'),canonical(body))
    write_new(output/'binding.example.json',json.dumps(b,indent=2).encode())
    write_new(output/'ledger.synthetic.json',canonical(ledger))
    write_new(output/'github.synthetic.json',canonical(remote))
    return {'synthetic_only':True,'out':str(output),'cases':{k:v['disposition'] for k,v in reports.items()},
            'actions_executed':[],'authority':'NONE','live_ledger_or_task_touched':False}
