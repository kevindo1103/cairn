import copy
import pytest
from iceflow_harness.common import Refused,canonical,digest
from cairn_engineering.workflow import load_workflow,validate_workflow,project_workflow
from cairn_engineering.topology import topology,resolve_role,overlaps


def roles():
    return {r:[{'task_id':r+'-task','session_id':r+'-session','generation':1}] for r in topology()['roles']}


def accepted_step(w,key,bindings,candidate='b'*40):
    step=next(s for s in w['steps'] if s['id']==key);p=bindings[step['owner_role']][0]
    event={'id':key+'-event','target':p['task_id'],'state':'COMPLETED','result_evidence':'artifact://sha256/'+'a'*64,
           'payload':{'issue':'123','scope':key,'base':'a'*40,'head':candidate,'checkpoint':'cp-'+key}}
    cp={'issue':'123','scope':key,'base':'a'*40,'head':candidate,'checkpoint':'cp-'+key,'revision':1}
    proof=dict(p,event_id=event['id'],step_id=key,workflow_digest=digest(canonical(w)),candidate_sha=candidate,
       checkpoint_revision=1,checkpoint=cp['checkpoint'],step_result='ACCEPTED',required_checks=step['acceptance']['checks'],evidence_ref=event['result_evidence'])
    return event,cp,proof


def project(w,accepted=(),modify=None):
    b=roles();ledger={'events':[],'checkpoints':[]};ids={};evidence={}
    for key in accepted:
        e,cp,p=accepted_step(w,key,b);ledger['events'].append(e);ledger['checkpoints'].append(cp);ids[key]=e['id'];evidence[key]=p
    if modify:modify(b,ledger,ids,evidence)
    return project_workflow(w,bindings=b,ledger=ledger,step_events=ids,evidence=evidence,candidate_sha='b'*40)

@pytest.mark.parametrize('name',['backend-bugfix','ui-api-feature','inventory-migration','incident-release','docs-only'])
def test_all_templates_valid_and_no_new_authority(name):
    w=load_workflow(name);v=project(w)
    assert len(v['ready_steps'])==1 and v['effective_permissions']==[]
    assert v['next_action']['action']=='request_existing_adapter_assignment'


def test_wf1_parallel_nonoverlapping_domains_then_join():
    w=load_workflow('ui-api-feature')
    v=project(w,['contract']);assert v['ready_steps']==['backend','frontend']
    v=project(w,['contract','backend']);assert 'verify' not in v['ready_steps']
    v=project(w,['contract','backend','frontend']);assert v['ready_steps']==['verify']


def test_wf2_same_contract_blocks_second_writer_even_different_paths():
    w=load_workflow('ui-api-feature');w['steps'][2]['contracts']=['api-contract']
    v=project(w,['contract']);assert v['ready_steps']==['backend']
    assert next(x for x in v['steps'] if x['step']=='frontend')['reason']=='WRITER_SCOPE_OVERLAP'


def test_wf2_same_path_different_worktrees_does_not_bypass():
    assert overlaps(['backend'],['backend/models.py'])
    assert not overlaps(['backend'],['backend2'])
    w=load_workflow('ui-api-feature');w['steps'][2]['paths']=['backend/models.py']
    assert project(w,['contract'])['ready_steps']==['backend']


def test_wf3_completed_parent_stale_proof_blocks_join():
    w=load_workflow('ui-api-feature')
    def modify(b,l,i,e):e['backend']['candidate_sha']='d'*40
    v=project(w,['contract','backend','frontend'],modify)
    assert 'verify' not in v['ready_steps']
    assert next(x for x in v['steps'] if x['step']=='backend')['status']=='BLOCKED'


def test_wf4_same_session_reviewer_rejected():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):b['qc_lead'][0]['session_id']=b['backend_dev'][0]['session_id']
    v=project(w,['plan','implement','scan','verify'],modify)
    assert next(x for x in v['steps'] if x['step']=='review')['reason']=='INDEPENDENT_REVIEWER_REQUIRED'


def test_rs8_completed_with_fail_is_not_accepted():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):e['verify']['step_result']='REJECTED'
    v=project(w,['plan','implement','scan','verify'],modify)
    assert 'review' not in v['ready_steps']


def test_completed_without_evidence_waits():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):e.clear()
    v=project(w,['plan'],modify)
    assert v['ready_steps']==[] and v['steps'][0]['status']=='WAITING_EVIDENCE'


def test_workflow_cycle_is_not_scheduled():
    w=load_workflow('backend-bugfix');w['steps'][0]['depends_on']=['handoff']
    with pytest.raises(Refused,match='CYCLE'):validate_workflow(w)


def test_missing_role_does_not_spawn():
    with pytest.raises(Refused,match='MISSING_OR_AMBIGUOUS'):resolve_role('backend_dev',{})


def test_duplicate_role_does_not_pick_convenient():
    b=roles();b['backend_dev']*=2
    with pytest.raises(Refused,match='MISSING_OR_AMBIGUOUS'):resolve_role('backend_dev',b)


def test_main_core_single_event_cannot_be_two_steps():
    w=load_workflow('backend-bugfix')
    with pytest.raises(Refused,match='EVENT_STEP_MAPPING_INVALID'):
        project_workflow(w,bindings=roles(),ledger={'events':[],'checkpoints':[]},step_events={'plan':'x','implement':'x'},evidence={},candidate_sha='b'*40)


def test_unknown_event_state_never_becomes_new_assignment():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):l['events'][0]['state']='MYSTERY'
    v=project(w,['plan'],modify)
    assert v['ready_steps']==[] and v['steps'][0]['reason']=='EVENT_STATE_UNKNOWN'


def test_expired_worker_is_not_a_new_writer():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):
        l['events'][1].update(state='STARTED',worker_until=0,worker_owner='backend_dev-task@1')
    v=project(w,['plan','implement'],modify)
    assert v['ready_steps']==[]
    assert v['steps'][1]['reason']=='LEASE_EXPIRED_RETAIN_SLOT'


def test_recipient_busy_outside_workflow_does_not_receive_another_task():
    w=load_workflow('backend-bugfix')
    def modify(b,l,i,e):l['recipients']=[{'task':'backend_dev-task','busy':1,'active_event':None}]
    v=project(w,['plan'],modify)
    assert v['ready_steps']==[] and v['steps'][1]['reason']=='RECIPIENT_HAS_EXISTING_WORK'


def test_bool_workflow_version_not_an_integer_version():
    w=load_workflow('backend-bugfix');w['version']=True
    with pytest.raises(Refused,match='WORKFLOW_VERSION'):validate_workflow(w)
