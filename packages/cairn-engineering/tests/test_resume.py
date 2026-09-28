import copy
import pytest
from iceflow_harness.common import canonical
from cairn_engineering.demo import inputs,reseal
from cairn_engineering.resume import reconcile

NOW=2000000000

def run(data):return reconcile(*data,now=NOW)

def test_rs10_repeat_same_snapshot_identical_no_permission(data):
    before=copy.deepcopy(data);a=run(data);b=run(data)
    assert a==b and data==before
    assert a['disposition']=='RESUME_CANDIDATE'
    assert a['effective_permissions']==[] and a['actions_executed']==[]

@pytest.mark.parametrize('case,code',[
 ('merged','PR_ALREADY_MERGED'),('closed','PR_CLOSED_UNMERGED'),('issue_closed','ISSUE_CLOSED'),
 ('checkpoint','STALE_CHECKPOINT'),('registry','STALE_REGISTRY'),('generation','STALE_GENERATION'),
 ('retired','STALE_GENERATION'),('lease','LEASE_EXPIRED'),('remote','REMOTE_UNAVAILABLE'),
 ('main','MAIN_MOVED_REVIEW_IMPACT'),('local','STALE_SOURCE'),('dirty','DIRTY_CANDIDATE'),
 ('terminal','TERMINAL_EVENT'),('busy','RECIPIENT_BUSY'),('stale_remote','REMOTE_SNAPSHOT_STALE'),
 ('role','PRINCIPAL_SCOPE_MISMATCH'),('owner','TASK_OWNER_CHANGED'),('pr_head','PR_SOURCE_DRIFT'),
 ('fork','FORK_SOURCE_REQUIRES_REVIEW'),('slot','SLOT_BINDING_UNKNOWN'),('dep','WAIT_DEPENDENCY'),
 ('workflow','WORKFLOW_REVISION_CHANGED'),('no_registry','REGISTRY_UNAVAILABLE'),('stale_ledger','LEDGER_SNAPSHOT_STALE')])
def test_resume_negative_cases(data,case,code):
    b,l,s,g=copy.deepcopy(data)
    if case=='merged':g['task']['pr'].update(state='closed',merged=True,merge_commit_sha='d'*40)
    elif case=='closed':g['task']['pr']['state']='closed'
    elif case=='issue_closed':g['task']['issue_state']='closed'
    elif case=='checkpoint':l['checkpoints'][0]['revision']=2
    elif case=='registry':l['registry']['revision']=2
    elif case=='generation':l['registry']['entries'][0]['generation']=2
    elif case=='retired':l['registry']['entries'][0]['state']='retired'
    elif case=='lease':l['events'][0]['worker_until']=NOW-1
    elif case=='remote':g=None
    elif case=='main':g['task']['main_sha']='f'*40
    elif case=='local':s['head_sha']='f'*40
    elif case=='dirty':s['dirty']=True
    elif case=='terminal':l['events'][0]['state']='COMPLETED'
    elif case=='busy':l['recipients'][0]['busy']=1
    elif case=='stale_remote':g['observed_at_unix']=NOW-301
    elif case=='role':l['registry']['entries'][0]['role']='PM'
    elif case=='owner':l['events'][0]['target']='other'
    elif case=='pr_head':g['task']['pr']['head_sha']='e'*40
    elif case=='fork':g['task']['pr']['head_repository_id']=1
    elif case=='slot':l['recipients'][0]['active_event']=None
    elif case=='dep':l['events'][0]['payload']['dependency']='missing'
    elif case=='workflow':b['workflow_digest']='0'*64
    elif case=='no_registry':l['registry']=None
    elif case=='stale_ledger':l['observed_at_unix']=NOW-301
    l=reseal(l);g=reseal(g) if g else None
    before=canonical([b,l,s,g]);v=reconcile(b,l,s,g,now=NOW)
    assert v['disposition']==code
    assert v['actions_executed']==[] and v['effective_permissions']==[]
    assert before==canonical([b,l,s,g])
    assert v['next_action']['action'] not in {'push','merge','deploy','reopen','reset','rebase','requeue','recover'}

@pytest.mark.parametrize('state,code', [('QUEUED','AWAITING_DELIVERY'),('SENT','AWAITING_ACK')])
def test_pending_delivery_never_manufactures_ack(data,state,code):
    b,l,s,g=copy.deepcopy(data);l['events'][0]['state']=state
    l['recipients'][0]['active_event']=None
    assert reconcile(b,reseal(l),s,g,now=NOW)['disposition']==code

def test_missing_self_digest_refused(data):
    from iceflow_harness.common import Refused
    data[1].pop('observation_digest')
    with pytest.raises(Refused,match='DIGEST_MISSING'):run(data)

def test_no_summary_argument_in_resume_api():
    import inspect
    assert 'summary' not in inspect.signature(reconcile).parameters


def test_escalation_does_not_relabel_worker_as_pm(data):
    b,l,g,r=data
    r['task']['pr']['merged']=True;r['task']['pr']['state']='closed'
    from cairn_engineering.demo import reseal
    v=reconcile(b,l,g,reseal(r),now=2000000000)
    assert v['next_action']['owner_role']=='pm_assistant'
    assert v['next_action']['task_id'] is None
    assert v['next_action']['routing']=='OWNER_MAPPING_REQUIRED'


def test_unknown_event_not_resume_candidate(data):
    b,l,g,r=data;l['events'][0]['state']='UNKNOWN'
    from cairn_engineering.demo import reseal
    assert reconcile(b,reseal(l),g,r,now=2000000000)['disposition']=='EVENT_STATE_UNKNOWN'


def test_unknown_remote_state_not_resume_candidate(data):
    b,l,g,r=data;r['task']['pr']['state']='UNKNOWN'
    from cairn_engineering.demo import reseal
    assert reconcile(b,l,g,reseal(r),now=2000000000)['disposition']=='REMOTE_STATE_UNKNOWN'
