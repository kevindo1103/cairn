"""Deterministic advisory resume barrier. Never grant write authority from cache.

Summary/compaction text is deliberately NOT an input. Call this at resume, but
actual side-effect prevention requires the protected host/Adapter on every write.
"""
from __future__ import annotations
import math
import time

from iceflow_harness.common import Refused, canonical, digest
from .contracts import inert, require, seal, validate_binding, verify_digest
from .topology import topology
from .workflow import load_workflow


def reconcile(binding: dict, ledger: dict, local: dict | None, github: dict | None,
              *, now: float | None = None, max_age: int = 300) -> dict:
    b=validate_binding(binding);now=time.time() if now is None else now
    require(type(max_age) is int and 1<=max_age<=3600,'FRESHNESS_POLICY_INVALID')
    def answer(code, action, *, owner=None, detail=None):
        return seal(inert('cairn-resume-observation-v1',disposition=code,event_id=b['event_id'],
            task_id=b['task_id'],scope=b['scope'],checkpoint_revision=b['checkpoint_revision'],
            observed_head=local.get('head_sha') if local else None,
            next_action={'action':action,'owner_role':owner or b['owner_role'],
                         'task_id':b['task_id'] if owner in (None,b['owner_role']) else None,
                         'routing':'BOUND_RECIPIENT' if owner in (None,b['owner_role']) else 'OWNER_MAPPING_REQUIRED'},
            detail=detail or {},live_identity='NOT_ATTESTED',
            write_permission='MUST_RECHECK_THROUGH_EXISTING_ADAPTER',
            observation_only=True))
    def fresh(record):
        value=record.get('observed_at_unix')
        return type(value) in (int,float) and math.isfinite(value) and -5<=now-value<=max_age
    wf=load_workflow(b['workflow'])
    if digest(canonical(wf))!=b['workflow_digest']:
        return answer('WORKFLOW_REVISION_CHANGED','review_workflow_binding',owner='pm_assistant')
    step=next((s for s in wf['steps'] if s['id']==b['step_id']),None)
    if step is None or step['owner_role']!=b['owner_role']:
        return answer('STEP_OWNER_MISMATCH','reconcile_owner',owner='pm_assistant')
    if not isinstance(ledger,dict):return answer('LEDGER_UNAVAILABLE','obtain_current_checkpoint')
    verify_digest(ledger,'observation_digest')
    if ledger.get('schema')!='cairn-ledger-observation-v1' or ledger.get('core_schema')!=1:
        return answer('LEDGER_SCHEMA_UNSUPPORTED','review_core_binding',owner='pm_assistant')
    if not fresh(ledger):return answer('LEDGER_SNAPSHOT_STALE','obtain_current_checkpoint')
    matches=[e for e in ledger['events'] if e['id']==b['event_id']]
    if len(matches)!=1:return answer('TASK_EVENT_MISSING_OR_AMBIGUOUS','reconcile_task_assignment')
    event=matches[0];payload=event['payload']
    if event.get('state') not in {'QUEUED','SENT','ACKED','STARTED','COMPLETED','BLOCKED','CANCELLED','SUPERSEDED'}:
        return answer('EVENT_STATE_UNKNOWN','obtain_current_checkpoint')
    if event['target']!=b['task_id'] or payload.get('target_task')!=b['task_id']:
        return answer('TASK_OWNER_CHANGED','reconcile_owner',owner='pm_assistant')
    if payload.get('issue')!=str(b['issue']) or payload.get('scope')!=b['scope']:
        return answer('TASK_SCOPE_CHANGED','reconcile_scope',owner='pm_assistant')
    # Read actual PR lifecycle before proposing source work. Merged != all work
    # complete; route to owner for remaining docs/integration/assignment.
    if github is None:return answer('REMOTE_UNAVAILABLE','obtain_fresh_github_observation')
    verify_digest(github,'observation_digest')
    if (github.get('schema')!='cairn-github-task-observation-v1' or
            github.get('repository_id')!=b['repository_id'] or github.get('repository')!=b['repository']):
        return answer('REMOTE_SUBJECT_MISMATCH','obtain_fresh_github_observation')
    if not fresh(github):return answer('REMOTE_SNAPSHOT_STALE','obtain_fresh_github_observation')
    remote=github['task'];pr=remote.get('pr')
    if remote.get('issue')!=b['issue'] or (b['pr'] is None and pr is not None) or (b['pr'] is not None and (not pr or pr.get('number')!=b['pr'])):
        return answer('REMOTE_TASK_MISMATCH','obtain_fresh_github_observation')
    if remote.get('issue_state') not in {'open','closed'} or (pr and (pr.get('state') not in {'open','closed'} or type(pr.get('merged')) is not bool)):
        return answer('REMOTE_STATE_UNKNOWN','obtain_fresh_github_observation')
    if pr and pr.get('merged') is True:
        return answer('PR_ALREADY_MERGED','review_remaining_work_or_wait',owner='pm_assistant',detail={'no_reopen_no_edit':True})
    if pr and pr.get('state')=='closed':return answer('PR_CLOSED_UNMERGED','review_closed_work',owner='pm_assistant')
    if remote.get('issue_state')=='closed':return answer('ISSUE_CLOSED','review_remaining_work_or_wait',owner='pm_assistant')
    if local is None or not fresh(local):return answer('LOCAL_SOURCE_UNAVAILABLE','obtain_fresh_local_observation')
    if local.get('dirty') is not False:return answer('DIRTY_CANDIDATE','inspect_existing_work_no_reset')
    if local.get('head_sha')!=b['head_sha'] or local.get('tree_sha')!=b['tree_sha']:
        return answer('STALE_SOURCE','reconcile_candidate_without_reset')
    if pr and (pr.get('head_sha')!=b['head_sha'] or pr.get('base_sha')!=b['base_sha']):
        return answer('PR_SOURCE_DRIFT','reconcile_candidate_without_reset')
    if pr and pr.get('head_repository_id')!=b['repository_id']:
        return answer('FORK_SOURCE_REQUIRES_REVIEW','review_repository_binding')
    checkpoints=[c for c in ledger['checkpoints'] if c['issue']==str(b['issue']) and c['scope']==b['scope']]
    if len(checkpoints)!=1:return answer('CHECKPOINT_MISSING_OR_AMBIGUOUS','obtain_current_checkpoint')
    cp=checkpoints[0]
    if (cp['revision']!=b['checkpoint_revision'] or cp['checkpoint']!=b['checkpoint'] or
        cp['head']!=b['head_sha'] or cp['base']!=b['base_sha'] or
        any(payload.get(k)!=cp[k] for k in ('checkpoint','base','head'))):
        return answer('STALE_CHECKPOINT','reconcile_current_checkpoint')
    registry=ledger.get('registry')
    if not registry:return answer('REGISTRY_UNAVAILABLE','obtain_host_registry_binding',owner='pm_assistant')
    if registry.get('revision')!=b['registry_revision']:
        return answer('STALE_REGISTRY','reconcile_current_registry',owner='pm_assistant')
    principals=[p for p in registry['entries'] if p['task_id']==b['task_id']]
    if len(principals)!=1:return answer('PRINCIPAL_AMBIGUOUS','obtain_host_registry_binding',owner='pm_assistant')
    principal=principals[0]
    if (principal.get('session_id')!=b['session_id'] or principal.get('generation')!=b['generation'] or
        principal.get('state')!='active'):
        return answer('STALE_GENERATION','reconcile_owner_no_rotation',owner='pm_assistant')
    role=topology()['roles'].get(b['owner_role'])
    if not role or principal.get('role') not in role['registry_roles'] or b['scope'] not in principal.get('scopes',[]):
        return answer('PRINCIPAL_SCOPE_MISMATCH','reconcile_owner',owner='pm_assistant')
    if event['state'] in {'COMPLETED','BLOCKED','CANCELLED','SUPERSEDED'}:
        return answer('TERMINAL_EVENT','review_remaining_work_or_wait',owner='pm_assistant')
    slot=[r for r in ledger['recipients'] if r['task']==b['task_id']]
    if len(slot)!=1:return answer('RECIPIENT_SLOT_UNKNOWN','inspect_existing_worker')
    if slot[0].get('active_event') not in (None,b['event_id']) or slot[0].get('busy'):
        return answer('RECIPIENT_BUSY','wait_for_existing_worker')
    dependency=payload.get('dependency')
    if dependency:
        dependencies=[e for e in ledger['events'] if e['id']==dependency]
        if len(dependencies)!=1 or dependencies[0]['state']!='COMPLETED':
            return answer('WAIT_DEPENDENCY','wait_for_dependency_owner')
        dp=dependencies[0]['payload']
        current=[c for c in ledger['checkpoints'] if c['issue']==dp['issue'] and c['scope']==dp['scope']]
        if len(current)!=1 or any(current[0][k]!=dp[k] for k in ('checkpoint','base','head')):
            return answer('STALE_DEPENDENCY','reconcile_dependency_evidence')
    if event['state'] in {'ACKED','STARTED'}:
        until=event.get('worker_until')
        if type(until) not in (int,float) or not math.isfinite(until) or until<=now:
            return answer('LEASE_EXPIRED','confirm_worker_state_no_redispatch')
        if slot[0].get('active_event')!=b['event_id']:
            return answer('SLOT_BINDING_UNKNOWN','inspect_existing_worker')
        if event.get('worker_owner')!=b['task_id']+'@'+str(b['generation']):
            return answer('LEASE_OWNER_MISMATCH','inspect_existing_worker')
    if remote.get('main_sha')!=b['main_sha']:
        return answer('MAIN_MOVED_REVIEW_IMPACT','review_impacted_proofs_no_reset')
    if event['state']=='QUEUED':
        return answer('AWAITING_DELIVERY','inspect_existing_delivery_no_resend')
    if event['state']=='SENT':
        return answer('AWAITING_ACK','request_existing_adapter_reconcile')
    return answer('RESUME_CANDIDATE','request_existing_adapter_reconcile',detail={'not_a_write_permit':True})
