"""Pure workflow projections over existing events/evidence, no workflow database.

A step being READY is a routing proposal. Its host must still admit every action
through Cairn Adapter. No report can supply an approval or expand scope.
"""
from __future__ import annotations
import importlib.resources
import math
import time

from iceflow_harness.common import Refused, canonical, digest, parse_json, safe_rel
from .contracts import exact, inert, require, seal, sha40, word
from .topology import overlaps, resolve_role, topology
from iceflow_harness.coverage import coverage_contract

KINDS={'plan','implement','check','review','integrate','docs','release_handoff'}


def load_workflow(name: str) -> dict:
    require(name in {'backend-bugfix','ui-api-feature','inventory-migration','incident-release','docs-only'},'WORKFLOW_UNKNOWN')
    p=importlib.resources.files('cairn_engineering').joinpath('data/workflows.json')
    return validate_workflow(parse_json(p.read_bytes())[name])


def validate_workflow(value: dict) -> dict:
    exact(value,{'schema','id','version','steps'},'WORKFLOW_SHAPE')
    require(value['schema']=='cairn-workflow-v1' and type(value['version']) is int and value['version'] in {1,2,3},'WORKFLOW_VERSION')
    word(value['id'])
    steps=value['steps'];require(type(steps) is list and 0<len(steps)<=32,'WORKFLOW_STEP_LIMIT')
    ids=[]
    for s in steps:
        exact(s,{'id','kind','owner_role','depends_on','paths','contracts','independent_of','acceptance'},'STEP_SHAPE')
        ids.append(word(s['id']));word(s['owner_role']);require(s['kind'] in KINDS,'STEP_KIND')
        for k in ('depends_on','paths','contracts'):
            require(type(s[k]) is list and all(isinstance(v,str) for v in s[k]) and len(s[k])==len(set(s[k])),'STEP_LIST_INVALID')
        for p in s['paths']:safe_rel(p)
        for c in s['contracts']:word(c)
        require(s['independent_of'] is None or isinstance(s['independent_of'],str),'INDEPENDENCE_INVALID')
        a=s['acceptance']
        require(type(a) is dict, 'STEP_ACCEPTANCE')
        optional={'model_coverage'} if 'model_coverage' in a else set()
        exact(a,{'mode','checks'} | optional,'STEP_ACCEPTANCE')
        if optional:
            coverage_contract(a['model_coverage'])
            require(s['kind']=='check' and a['mode']=='required_checks' and
                    {'K04','K04B','K04B_COVERAGE'} <= set(a['checks']), 'COVERAGE_PREREQUISITES_REQUIRED')
        require(a['mode'] in {'artifact','diagnostic','required_checks','independent_review'},'STEP_ACCEPTANCE_MODE')
        require(type(a['checks']) is list and all(isinstance(v,str) for v in a['checks']) and len(set(a['checks']))==len(a['checks']), 'CHECKSET_INVALID')
        require(a['mode']!='required_checks' or bool(a['checks']), 'CHECKSET_EMPTY')
        require(s['owner_role'] in topology()['roles'],'ROLE_UNKNOWN')
        require(s['kind']!='check' or a['mode'] in {'diagnostic','required_checks'},'CHECK_ACCEPTANCE_MODE')
        require(a['mode']!='independent_review' or s['independent_of'] is not None,'INDEPENDENCE_REQUIRED')
    require(len(set(ids))==len(ids),'STEP_DUPLICATE')
    byid={s['id']:s for s in steps};done=set();visiting=set()
    def visit(key):
        require(key in byid,'DEPENDENCY_UNKNOWN');require(key not in visiting,'WORKFLOW_CYCLE')
        if key in done:return
        visiting.add(key)
        for d in byid[key]['depends_on']:visit(d)
        visiting.remove(key);done.add(key)
    for key in byid:visit(key)
    for s in steps:
        if s['independent_of'] is not None:require(s['independent_of'] in byid,'INDEPENDENCE_UNKNOWN')
    return value


def project_workflow(workflow: dict, *, bindings: dict, ledger: dict, step_events: dict,
                     evidence: dict, candidate_sha: str, registry: dict | None = None, now: float | None = None) -> dict:
    """Caller supplies evidence already validated by the bridge/host boundary.

    This is an inert planning API, NOT a way to authenticate imported JSON.
    Even ACCEPTED here means 'accepted in this observation', never permission.
    """
    workflow=validate_workflow(workflow)
    sha40(candidate_sha)
    now=time.time() if now is None else now
    require(type(step_events) is dict and type(evidence) is dict and type(bindings) is dict,'WORKFLOW_INPUT_INVALID')
    byid={s['id']:s for s in workflow['steps']}
    require(set(step_events)<=set(byid) and len(set(step_events.values()))==len(step_events),'EVENT_STEP_MAPPING_INVALID')
    events={e['id']:e for e in ledger['events']}
    require(len(events)==len(ledger['events']),'EVENT_DUPLICATE')
    cp={(c['issue'],c['scope']):c for c in ledger['checkpoints']}
    require(len(cp)==len(ledger['checkpoints']),'CHECKPOINT_DUPLICATE')
    result={};targets={};proofs={}
    for step in workflow['steps']:
        key=step['id'];entry={'step':key,'owner_role':step['owner_role'],'status':'WAITING'}
        try:
            targets[key]=resolve_role(step['owner_role'],bindings,registry=registry)
            entry['task_id']=targets[key]['task_id']
        except Refused as exc:
            entry.update(status='BLOCKED',reason=exc.code)
        event=events.get(step_events.get(key))
        if event is not None:
            p=event['payload'];checkpoint=cp.get((p['issue'],p['scope']))
            fresh=checkpoint is not None and all(checkpoint[k]==p[k] for k in ('base','head','checkpoint'))
            if entry['status']!='BLOCKED':
                if event['target']!=targets[key]['task_id']:
                    entry.update(status='BLOCKED',reason='EVENT_OWNER_MISMATCH')
                elif not fresh:
                    entry.update(status='BLOCKED',reason='STALE_STEP_CHECKPOINT')
                elif event['state'] in {'ACKED','STARTED'}:
                    until=event.get('worker_until')
                    if type(until) not in (int,float) or not math.isfinite(until) or until<=now:
                        entry.update(status='BLOCKED',reason='LEASE_EXPIRED_RETAIN_SLOT')
                    elif event.get('worker_owner')!=targets[key]['task_id']+'@'+str(targets[key]['generation']):
                        entry.update(status='BLOCKED',reason='LEASE_OWNER_MISMATCH')
                    else:
                        entry.update(status='ACTIVE',reason='EXISTING_WORKER_NO_REDISPATCH')
                elif event['state'] in {'QUEUED','SENT'}:
                    entry.update(status='IN_FLIGHT',reason='EXISTING_DELIVERY_NO_REDISPATCH')
                elif event['state'] in {'BLOCKED','CANCELLED','SUPERSEDED'}:
                    entry.update(status='BLOCKED',reason='TERMINAL_EVENT_RECONCILIATION_REQUIRED')
                elif event['state']=='COMPLETED':
                    proof=evidence.get(key)
                    if not proof:
                        entry.update(status='WAITING_EVIDENCE',reason='COMPLETION_IS_NOT_ACCEPTANCE')
                    elif (proof.get('event_id')!=event['id'] or proof.get('candidate_sha')!=candidate_sha
                          or proof.get('evidence_ref')!=event.get('result_evidence')
                          or proof.get('workflow_digest')!=digest(canonical(workflow))
                          or proof.get('step_id')!=key or proof.get('task_id')!=event['target']
                          or proof.get('generation')!=targets[key]['generation']
                          or proof.get('session_id')!=targets[key]['session_id']
                          or proof.get('checkpoint_revision')!=checkpoint['revision']
                          or proof.get('checkpoint')!=checkpoint['checkpoint']):
                        entry.update(status='BLOCKED',reason='STALE_OR_MISBOUND_STEP_EVIDENCE')
                    elif step['kind']=='check' and proof.get('required_checks')!=step['acceptance']['checks']:
                        entry.update(status='BLOCKED',reason='CHECKSET_MISMATCH')
                    elif step['acceptance'].get('model_coverage') and (
                            proof.get('required_model_coverage') != step['acceptance']['model_coverage'] or
                            proof.get('coverage_result') != 'SATISFIED'):
                        entry.update(status='BLOCKED',reason='MODEL_COVERAGE_MISMATCH')
                    elif proof.get('step_result') not in {'ACCEPTED','COLLECTED'}:
                        entry.update(status='NEEDS_REWORK',reason='EVIDENCE_NOT_ACCEPTED')
                    elif step['acceptance']['mode']!='diagnostic' and proof['step_result']!='ACCEPTED':
                        entry.update(status='NEEDS_REWORK',reason='DIAGNOSTIC_IS_NOT_CHECK_PASS')
                    else:
                        entry.update(status='ACCEPTED',reason='OBSERVED_STEP_EVIDENCE')
                        proofs[key]=proof
                else:
                    entry.update(status='BLOCKED',reason='EVENT_STATE_UNKNOWN')
        elif key in step_events and entry['status']!='BLOCKED':
            entry.update(status='BLOCKED',reason='MAPPED_EVENT_MISSING')
        result[key]=entry
    for step in workflow['steps']:
        key=step['id'];other=step['independent_of']
        if other and key in targets and other in targets:
            a,b=targets[key],targets[other]
            if a['task_id']==b['task_id'] or a['session_id']==b['session_id']:
                result[key].update(status='BLOCKED',reason='INDEPENDENT_REVIEWER_REQUIRED')
    # Fixed-point dependency closure: an accepted child cannot hide a stale parent.
    for _ in workflow['steps']:
        for step in workflow['steps']:
            entry=result[step['id']]
            waiting=[d for d in step['depends_on'] if result[d]['status']!='ACCEPTED']
            if waiting:
                if entry['status'] in {'ACCEPTED','ACTIVE','IN_FLIGHT'}:
                    entry.update(status='BLOCKED',reason='DEPENDENCY_EVIDENCE_INVALID',waiting_for=waiting)
                elif entry['status']=='WAITING':entry['waiting_for']=waiting
            elif entry['status']=='WAITING':entry.update(status='READY_PROPOSAL')
    # Deterministic declaration order; active writers win; overlapping new writers wait.
    # Keep reservations even when dependency evidence/leases became invalid.
    # A blocked observation does not prove the previous writer stopped.
    reserved=[s for s in workflow['steps'] if s['id'] in step_events and
              events.get(step_events[s['id']],{}).get('state') in {'ACKED','STARTED','QUEUED','SENT'}
              and s['kind'] in {'implement','integrate','docs'}]
    ready=[]
    for step in workflow['steps']:
        entry=result[step['id']]
        if entry['status']!='READY_PROPOSAL':continue
        target=targets[step['id']]['task_id']
        slots=[r for r in ledger.get('recipients',[]) if r['task']==target]
        if any(r.get('busy') or r.get('active_event') for r in slots) or any(
                e['target']==target and e['state'] in {'QUEUED','SENT','ACKED','STARTED'} for e in ledger['events']):
            entry.update(status='WAITING',reason='RECIPIENT_HAS_EXISTING_WORK')
            continue
        writer=step['kind'] in {'implement','integrate','docs'}
        conflict=next((s for s in reserved if writer and
                       (overlaps(s['paths'],step['paths']) or set(s['contracts'])&set(step['contracts']))),None)
        if conflict:
            entry.update(status='WAITING',reason='WRITER_SCOPE_OVERLAP',waiting_for=[conflict['id']])
        else:
            ready.append(step['id'])
            if writer:reserved.append(step)
    done=all(x['status']=='ACCEPTED' for x in result.values())
    next_action={'action':'wait_for_assignment' if done else 'inspect_blocker','owner_role':'pm_assistant'}
    if ready:
        key=ready[0];target_role=result[key]['owner_role']
        source_role=topology()['roles'][target_role]['assigned_by']
        try:
            sender=resolve_role(source_role,bindings,registry=registry) if source_role else targets[key]
            next_action={'action':'request_existing_adapter_assignment','step':key,
                         'owner_role':source_role or target_role,'task_id':sender['task_id'],
                         'target_role':target_role,'target_task_id':result[key]['task_id']}
        except Refused:
            next_action={'action':'resolve_assignment_owner','owner_role':source_role or target_role}

    return seal(inert('cairn-workflow-observation-v1',workflow=workflow['id'],
                     workflow_digest=digest(canonical(workflow)),steps=list(result.values()),
                     ready_steps=ready,next_action=next_action,completed_observed=done,
                     authority_note='Input observations/role bindings are not authenticated grants'))
