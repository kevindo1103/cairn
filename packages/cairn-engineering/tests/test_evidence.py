import copy
from datetime import datetime,timezone
import pytest
from iceflow_harness.common import Refused,canonical,digest,finding
from iceflow_harness.report import envelope
from cairn_engineering.evidence import validate_report,HostEvidenceBridge
from cairn_engineering.demo import reseal
from cairn_engineering.workflow import load_workflow

NOW=2000000000

@pytest.fixture
def report_case(data):
    b=copy.deepcopy(data[0]);b.update(step_id='verify',owner_role='qc_dev')
    source={'commit_sha':b['head_sha'],'tree_sha':b['tree_sha'],'working_tree_dirty':False,
            'uncommitted_changes_included':False,'kind':'LOCAL_GIT_COMMITTED_TREE','blobs_read':{}}
    report=envelope('scan',[finding('ERP_NATIVE_TESTS','PASS','SYNTHETIC_TESTS')],source,
        {'configuration_sha256':'f'*64,'candidate_coverage':'COMMITTED_TREE_ONLY'})
    report['created_at']=datetime.fromtimestamp(NOW,timezone.utc).isoformat()
    report.pop('report_digest_sha256');report['report_digest_sha256']=digest(canonical(report))
    return b,load_workflow('backend-bugfix'),report


def check(case):
    b,w,r=case;raw=canonical(r)
    return validate_report(raw,file_sha256=digest(raw),binding=b,workflow=w,config_sha256='f'*64,now=NOW)


def resign(r):
    r.pop('report_digest_sha256',None);r['report_digest_sha256']=digest(canonical(r))


def test_br_valid_checks_are_not_permission(report_case):
    result=check(report_case)
    assert result['step_result']=='ACCEPTED' and result['effective_permissions']==[]
    assert result['authority']=='NONE'

@pytest.mark.parametrize('mutation,code',[
 ('sha','CANDIDATE_NOT_COVERED'),('tree','CANDIDATE_NOT_COVERED'),('dirty','DIRTY_CANDIDATE_NOT_COVERED'),
 ('version','CHECKER_VERSION_UNQUALIFIED'),('counts','REPORT_COUNTS_MISMATCH'),('bool_count','REPORT_COUNTS_MISMATCH'),
 ('outcome','REPORT_OUTCOME_MISMATCH'),('authority','REPORT_AUTHORITY_INVALID'),
 ('config','CHECKER_CONFIG_MISMATCH'),('time','EVIDENCE_EXPIRED_OR_FUTURE')])
def test_br_bad_reports_fail_closed(report_case,mutation,code):
    b,w,r=copy.deepcopy(report_case)
    if mutation=='sha':r['source']['commit_sha']='e'*40
    elif mutation=='tree':r['source']['tree_sha']='e'*40
    elif mutation=='dirty':r['source']['working_tree_dirty']=True
    elif mutation=='version':r['version']='0.1.2'
    elif mutation=='counts':r['counts']={'PASS':2}
    elif mutation=='bool_count':r['counts']={'PASS':True}
    elif mutation=='outcome':r['outcome']='PARTIAL'
    elif mutation=='authority':r['authority']='APPROVED'
    elif mutation=='config':r['extra']['configuration_sha256']='e'*64
    elif mutation=='time':r['created_at']='2020-01-01T00:00:00Z'
    resign(r)
    with pytest.raises(Refused,match=code):check((b,w,r))

@pytest.mark.parametrize('status',['FAIL','NOT_RUN','WARN','BLOCKED'])
def test_br_required_status_not_promoted(report_case,status):
    b,w,r=copy.deepcopy(report_case)
    r['findings'][0]['status']=status;r['counts']={status:1}
    r['outcome']='FAIL' if status=='FAIL' else 'BLOCKED' if status=='BLOCKED' else 'PARTIAL'
    resign(r);assert check((b,w,r))['step_result']=='REJECTED'


def test_diagnostic_completed_with_findings_is_not_pass(report_case):
    b,w,r=copy.deepcopy(report_case);b['step_id']='scan'
    r['findings'][0]['status']='FAIL';r['counts']={'FAIL':1};r['outcome']='FAIL';resign(r)
    result=check((b,w,r));assert result['step_result']=='COLLECTED' and result['check_outcome']=='FAIL'


def test_missing_required_check_is_rejected(report_case):
    b,w,r=copy.deepcopy(report_case);r['findings'][0]['check']='K01';resign(r)
    assert check((b,w,r))['step_result']=='REJECTED'


def test_file_digest_and_internal_digest_distinct(report_case):
    b,w,r=report_case;raw=canonical(r)
    with pytest.raises(Refused,match='FILE_DIGEST'):
        validate_report(raw,file_sha256=r['report_digest_sha256'],binding=b,workflow=w,config_sha256='f'*64,now=NOW)


def test_mutated_report_internal_digest_rejected(report_case):
    report_case[2]['notices'].append('tampered')
    with pytest.raises(Refused,match='ENVELOPE_DIGEST_MISMATCH'):check(report_case)


def test_host_bridge_does_not_bypass_existing_executor(report_case):
    b,w,r=report_case;calls=[];artifacts={}
    def execute(cmd,args):
        calls.append((cmd,args));raise Refused('HOST_IDENTITY_UNAVAILABLE')
    def write(raw):ref='artifact://sha256/'+digest(raw);artifacts[ref]=raw;return ref
    bridge=HostEvidenceBridge(execute,write,binding=b,workflow=w,config_sha256='f'*64,clock=lambda:NOW)
    with pytest.raises(Refused,match='HOST_IDENTITY'):bridge.complete_check(report=canonical(r),report_sha256=digest(canonical(r)),worker_token='synthetic')
    assert len(calls)==1 and calls[0][0]=='complete' and len(artifacts)==2
    # No retry/enqueue/authority change on completion failure.
    assert set(calls[0][1])=={'event_id','worker_token','evidence'}


def test_host_bridge_rejected_check_never_calls_adapter(report_case):
    b,w,r=report_case;calls=[]
    r['findings'][0]['status']='FAIL';r['counts']={'FAIL':1};r['outcome']='FAIL';resign(r)
    bridge=HostEvidenceBridge(lambda *a:calls.append(a),lambda _:None,binding=b,workflow=w,config_sha256='f'*64,clock=lambda:NOW)
    with pytest.raises(Refused,match='CHECK_NOT_ACCEPTED'):bridge.complete_check(report=canonical(r),report_sha256=digest(canonical(r)),worker_token='synthetic')
    assert calls==[]
