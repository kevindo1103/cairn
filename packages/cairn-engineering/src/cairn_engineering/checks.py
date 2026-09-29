"""Trusted local check invocation, reusing Iceflow; never executes ERP Python."""
from __future__ import annotations
from pathlib import Path

from iceflow_harness.common import canonical, digest, outside
from iceflow_harness.gitview import GitView
from iceflow_harness.sourcechecks import scan
from iceflow_harness.report import envelope, save_report
from .contracts import require


def run_scan(config: dict, ref: str | None = None) -> tuple[dict,Path]:
    root=Path(config['repo_path']);output=outside(Path(config['output_dir']),root)
    view=GitView(root,ref or config['ref']);findings=scan(view,config)
    source=view.source()
    value=envelope('scan',findings,source,{
        'configuration_sha256':digest(canonical(config)),
        'candidate_coverage':'COMMITTED_TREE_ONLY','test_execution':'STATIC_ONLY'})
    # Source blobs are immutable even if working tree moves, but record that
    # coverage honestly and never bind as an unchanged editable candidate.
    final=GitView(root,'HEAD')
    if final.sha!=view.sha or final.dirty:
        value['source']['working_tree_dirty']=True
        value.pop('report_digest_sha256')
        value['report_digest_sha256']=digest(canonical(value))
    path=save_report(value,output,root)
    return value,path
