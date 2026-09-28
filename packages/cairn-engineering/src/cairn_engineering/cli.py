"""Cairn workflows/resume companion. All public commands are non-authorizing."""
from __future__ import annotations
import argparse
import json
import sys
import time
from pathlib import Path

from iceflow_harness.common import Refused, canonical, digest, outside, parse_json, read_bytes, write_new
from iceflow_harness.gitview import GitView
from iceflow_harness.github import ReadOnlyGitHub
from . import __version__
from .checks import run_scan
from .contracts import exact, inert, require, seal, validate_binding
from .evidence import bind_report, read_step_evidence
from .ledger_view import read_ledger_copy
from .observations import local_snapshot, task_snapshot
from .project import initialize, load_project
from .resume import reconcile
from .topology import topology
from .workflow import load_workflow, project_workflow


def parser():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--version',action='version',version=__version__)
    sub=p.add_subparsers(dest='command',required=True)
    q=sub.add_parser('init');q.add_argument('--repo',type=Path,required=True);q.add_argument('--out',type=Path,required=True)
    q=sub.add_parser('topology')
    q=sub.add_parser('workflow-template');q.add_argument('--name',required=True);q.add_argument('--out',type=Path,required=True)
    q=sub.add_parser('demo');q.add_argument('--out',type=Path,required=True)
    for name in ['doctor','scan','resume','bridge','workflow-next']:
        q=sub.add_parser(name);q.add_argument('--config',type=Path,required=True)
        if name=='scan':q.add_argument('--ref')
        if name in {'resume','bridge'}:q.add_argument('--binding',type=Path,required=True)
        if name=='resume':
            q.add_argument('--ledger-copy',type=Path,required=True)
            q.add_argument('--offline-copy',action='store_true',required=True)
            q.add_argument('--github-observation',type=Path,help='Imported observation for offline review, NEVER authority')
        if name=='bridge':
            q.add_argument('--report',type=Path,required=True);q.add_argument('--report-sha256',required=True)
        if name=='workflow-next':
            q.add_argument('--instance',type=Path,required=True);q.add_argument('--ledger-copy',type=Path,required=True)
            q.add_argument('--offline-copy',action='store_true',required=True)
    return p


def emit(value, output=None, repo=None):
    if output is not None:
        if repo is not None:output=outside(output,repo)
        raw=canonical(value);path=output/(digest(raw)+'.json')
        if path.exists():require(read_bytes(path)==raw,'IMMUTABLE_ARTIFACT_CONFLICT')
        else:write_new(path,raw)
        print(json.dumps({'result':value,'artifact':str(path),'file_sha256':digest(raw)},ensure_ascii=True))
    else:print(json.dumps(value,indent=2,ensure_ascii=True))


def run(args):
    if args.command=='init':emit(initialize(args.repo,args.out));return 0
    if args.command=='topology':emit(topology());return 0
    if args.command=='workflow-template':
        w=load_workflow(args.name);write_new(args.out,json.dumps(w,indent=2).encode())
        emit({'workflow':w['id'],'digest':digest(canonical(w)),'created':str(args.out),'authority':'NONE'});return 0
    if args.command=='demo':
        from .demo import demo
        emit(demo(args.out));return 0
    _,cfg=load_project(args.config);repo=Path(cfg['repo_path']);out=Path(cfg['output_dir'])
    if args.command=='doctor':
        v=GitView(repo,cfg['ref'])
        emit(inert('cairn-doctor-v1',version=__version__,source=v.source(),
             implemented=['topology-planner','resume-observer','typed-check-bridge','iceflow-scan'],
             not_activated=['live-ledger','runtime-dispatch','compaction-hook','merge','deploy']),out,repo);return 0
    if args.command=='scan':
        value,directory=run_scan(cfg,args.ref)
        emit({'outcome':value['outcome'],'report':str(directory/'report.html'),'json':str(directory/'report.json'),'authority':'NONE'})
        return 1 if value['outcome']=='FAIL' else 2 if value['outcome']=='BLOCKED' else 0
    if args.command=='bridge':
        binding=validate_binding(parse_json(read_bytes(args.binding)));w=load_workflow(binding['workflow'])
        require(binding['repository']==cfg['repository'] and binding['repository_id']==cfg['repository_id'],'PROJECT_BINDING_MISMATCH')
        # Check local source now. A report of old HEAD does not cover dirty work.
        local=local_snapshot(repo,binding)
        require(not local['dirty'] and local['head_sha']==binding['head_sha'] and local['tree_sha']==binding['tree_sha'],'CANDIDATE_NOT_COVERED')
        value=bind_report(args.report,file_sha256=args.report_sha256,binding=binding,workflow=w,
                          config_sha256=digest(canonical(cfg)))
        emit(value,out,repo);return 0 if value['step_result'] in {'ACCEPTED','COLLECTED'} else 1
    ledger=read_ledger_copy(args.ledger_copy,offline_copy=args.offline_copy)
    if args.command=='workflow-next':
        instance=parse_json(read_bytes(args.instance))
        exact(instance,{'schema','workflow','workflow_digest','candidate_sha','step_events','roles','evidence_paths'},'INSTANCE_SHAPE')
        require(instance['schema']=='cairn-workflow-instance-v1','INSTANCE_VERSION')
        w=load_workflow(instance['workflow']);require(digest(canonical(w))==instance['workflow_digest'],'WORKFLOW_REVISION_CHANGED')
        require(type(instance['evidence_paths']) is dict and len(instance['evidence_paths'])<=32,'EVIDENCE_MAP_INVALID')
        evidence={k:read_step_evidence(Path(p)) for k,p in instance['evidence_paths'].items()}
        value=project_workflow(w,bindings=instance['roles'],ledger=ledger,step_events=instance['step_events'],
                               evidence=evidence,candidate_sha=instance['candidate_sha'],registry=ledger['registry'])
    else:
        b=validate_binding(parse_json(read_bytes(args.binding)))
        require(b['repository']==cfg['repository'] and b['repository_id']==cfg['repository_id'],'PROJECT_BINDING_MISMATCH')
        local=local_snapshot(repo,b)
        remote=None;remote_error=None
        if args.github_observation:
            remote=parse_json(read_bytes(args.github_observation))
        else:
            try:remote=task_snapshot(ReadOnlyGitHub(cfg['repository'],cfg['repository_id'],max_reads=cfg['max_api_reads'],deadline_seconds=cfg['api_deadline_seconds']),b)
            except Refused as exc:remote_error=exc.code
        after=read_ledger_copy(args.ledger_copy,offline_copy=True)
        require(after['file_sha256']==ledger['file_sha256'],'LEDGER_SNAPSHOT_MOVED')
        final=local_snapshot(repo,b)
        require(all(final[k]==local[k] for k in ('head_sha','tree_sha','dirty','index_sha256','changed_paths_digest')),'LOCAL_SOURCE_MOVED')
        value=reconcile(b,after,final,remote)
        value.pop('observation_digest')
        value['remote_read_error']=remote_error
        value['github_input']='IMPORTED_UNTRUSTED_OBSERVATION' if args.github_observation else 'DIRECT_READ_OR_UNAVAILABLE'
        value=seal(value)
    emit(value,out,repo)
    return 0  # Inert observation complete; not a check pass or write permission.


def main(argv=None):
    try:return run(parser().parse_args(argv))
    except Refused as exc:
        emit(inert('cairn-cli-error-v1',outcome='BLOCKED',reason=exc.code));return 2
    except KeyboardInterrupt:
        emit(inert('cairn-cli-error-v1',outcome='BLOCKED',reason='INTERRUPTED'));return 130
    except Exception:
        # Deliberately no arbitrary exception text, SQL or credential-bearing argv.
        emit(inert('cairn-cli-error-v1',outcome='BLOCKED',reason='INPUT_OR_ENVIRONMENT_ERROR'));return 2


if __name__=='__main__':raise SystemExit(main())
