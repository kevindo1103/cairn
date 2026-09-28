"""Typed bridge from checker report to a single existing Cairn workflow step.

Validating bytes is not attestation. The injected protected host alone may submit
result_ref through its existing Adapter; this module never opens/writes a ledger.
"""
from __future__ import annotations
import time
from collections import Counter
from pathlib import Path

from iceflow_harness.common import Refused, canonical, digest, parse_json, read_bytes, write_new
from .contracts import exact, inert, require, seal, sha256, verify_digest, timestamp, validate_binding
from .workflow import validate_workflow

_ALLOWED_STATUS={'PASS','FAIL','WARN','NOT_RUN','BLOCKED','INFO'}


def validate_report(raw: bytes, *, file_sha256: str, binding: dict, workflow: dict,
                    config_sha256: str, now: float | None = None, max_age: int = 3600) -> dict:
    binding=validate_binding(binding);workflow=validate_workflow(workflow)
    sha256(file_sha256);sha256(config_sha256)
    require(type(max_age) is int and 1<=max_age<=86400,'EVIDENCE_AGE_POLICY_INVALID')
    require(digest(raw)==file_sha256,'EVIDENCE_FILE_DIGEST_MISMATCH')
    require(len(raw)<=8*1024*1024,'EVIDENCE_LIMIT')
    report=parse_json(raw);require(type(report) is dict,'REPORT_SHAPE')
    require(report.get('schema')=='iceflow-harness-report-v1' and report.get('version')=='0.1.3','CHECKER_VERSION_UNQUALIFIED')
    verify_digest(report,'report_digest_sha256')
    require(report.get('authority')=='NONE' and report.get('effective_permissions')==[] and
            report.get('release_ready')=='NOT_EVALUATED' and report.get('mode')=='observe','REPORT_AUTHORITY_INVALID')
    source=report.get('source');require(type(source) is dict,'CANDIDATE_NOT_COVERED')
    require(source.get('commit_sha')==binding['head_sha'] and source.get('tree_sha')==binding['tree_sha'], 'CANDIDATE_NOT_COVERED')
    require(source.get('working_tree_dirty') is False,'DIRTY_CANDIDATE_NOT_COVERED')
    extra=report.get('extra');require(type(extra) is dict and extra.get('configuration_sha256')==config_sha256,
                                     'CHECKER_CONFIG_MISMATCH')
    require(extra.get('candidate_coverage')=='COMMITTED_TREE_ONLY','CANDIDATE_COVERAGE_UNKNOWN')
    when=timestamp(report.get('created_at'));now=time.time() if now is None else now
    require(when<=now+5 and now-when<=max_age,'EVIDENCE_EXPIRED_OR_FUTURE')
    require(digest(canonical(workflow))==binding['workflow_digest'] and workflow['id']==binding['workflow'],'WORKFLOW_BINDING_MISMATCH')
    steps=[s for s in workflow['steps'] if s['id']==binding['step_id']]
    require(len(steps)==1 and steps[0]['owner_role']==binding['owner_role'],'STEP_BINDING_MISMATCH')
    step=steps[0];require(step['kind']=='check','CHECK_EVIDENCE_WRONG_STEP')
    findings=report.get('findings');require(type(findings) is list and 0<len(findings)<=10000,'FINDING_SET_INVALID')
    require(all(type(f) is dict and isinstance(f.get('check'),str) and f.get('status') in _ALLOWED_STATUS for f in findings),'FINDING_SHAPE_INVALID')
    counts=dict(Counter(f['status'] for f in findings))
    require(type(report.get('counts')) is dict and all(type(v) is int and v>0 for v in report['counts'].values()) and report['counts']==counts,'REPORT_COUNTS_MISMATCH')
    outcome=('FAIL' if counts.get('FAIL') else 'BLOCKED' if counts.get('BLOCKED') else
             'PARTIAL' if counts.get('WARN') or counts.get('NOT_RUN') else 'CHECKED_SCOPE_ONLY')
    require(report.get('outcome')==outcome,'REPORT_OUTCOME_MISMATCH')
    selected={k:[f for f in findings if f['check']==k] for k in step['acceptance']['checks']}
    accepted=bool(selected) and all(rows and all(f['status']=='PASS' for f in rows) for rows in selected.values())
    # Collecting diagnostics may finish with findings; it must not advance a pass gate.
    result='COLLECTED' if step['acceptance']['mode']=='diagnostic' else 'ACCEPTED' if accepted else 'REJECTED'
    return seal(inert('cairn-check-evidence-v1',event_id=binding['event_id'],task_id=binding['task_id'],
        session_id=binding['session_id'],generation=binding['generation'],
        checkpoint_revision=binding['checkpoint_revision'],checkpoint=binding['checkpoint'],
        step_id=binding['step_id'],workflow_digest=binding['workflow_digest'],candidate_sha=binding['head_sha'],
        tree_sha=binding['tree_sha'],checker_version=report['version'],config_sha256=config_sha256,
        report_file_sha256=file_sha256,report_internal_sha256=report['report_digest_sha256'],
        step_result=result,check_outcome=outcome,required_checks=list(selected),
        report_ref='artifact://sha256/'+file_sha256,
        report_created_at=report['created_at'],provenance='REPORT_BYTES_NOT_HOST_IDENTITY'))


def bind_report(path: Path, **kwargs) -> dict:
    return validate_report(read_bytes(path),**kwargs)


def read_step_evidence(path: Path) -> dict:
    raw=read_bytes(path);value=parse_json(raw)
    verify_digest(value,'observation_digest')
    require(value.get('schema') in {'cairn-check-evidence-v1','cairn-host-step-receipt-v1'},'STEP_EVIDENCE_VERSION')
    return dict(value, evidence_ref='artifact://sha256/'+digest(raw))


class HostEvidenceBridge:
    """Host-owned integration API; not a worker CLI and not an identity provider.

    The protected executor must already bind credential/generation/registry/scope
    to Adapter.execute and freshly verify authority. Host pins task/workflow/check
    policy here; a worker supplies only report bytes and its existing lease token.
    No Store/Owner handle or mutable registry is exposed.
    """
    def __init__(self, adapter_executor, artifact_writer, *, binding, workflow,
                 config_sha256, clock=time.time):
        # Deep detach, so an untrusted caller cannot mutate policy after binding.
        self._binding=parse_json(canonical(validate_binding(binding)))
        self._workflow=parse_json(canonical(validate_workflow(workflow)))
        self._config=sha256(config_sha256)
        self._execute=adapter_executor; self._write=artifact_writer; self._clock=clock

    def complete_check(self, *, report: bytes, report_sha256: str, worker_token: str) -> dict:
        evidence=validate_report(report,file_sha256=report_sha256,binding=self._binding,
             workflow=self._workflow,config_sha256=self._config,now=self._clock())
        require(evidence['step_result'] in {'ACCEPTED','COLLECTED'},'CHECK_NOT_ACCEPTED')
        # Persist raw report first. Completion is never retried here. A failed
        # adapter call can leave an immutable artifact, not a re-opened event.
        require(self._write(report)=='artifact://sha256/'+digest(report),'ARTIFACT_PUBLISH_BINDING')
        raw=canonical(evidence);ref=self._write(raw)
        require(ref=='artifact://sha256/'+digest(raw),'ARTIFACT_PUBLISH_BINDING')
        return self._execute('complete',{'event_id':self._binding['event_id'],
                             'worker_token':worker_token,'evidence':ref})
