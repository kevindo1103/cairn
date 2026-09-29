"""Bingxue configuration: routing references, not a second policy/authority store."""
from __future__ import annotations
import json
from pathlib import Path
import yaml

from iceflow_harness.common import Refused, no_symlinks, outside, parse_json, read_bytes, write_new
from iceflow_harness.config import default_config, load_config
from iceflow_harness.gitview import GitView
from .contracts import exact, require


def initialize(repo: Path, output: Path) -> dict:
    repo=no_symlinks(repo);view=GitView(repo,'HEAD');output=outside(output,repo)
    require(not output.exists(),'OUTPUT_EXISTS')
    # Check path BEFORE mkdir. No hook, .env, daemon or ledger is installed.
    cfg=default_config(repo,output/'reports')
    write_new(output/'iceflow.yml',yaml.safe_dump(cfg,sort_keys=False).encode())
    project={'schema':'cairn-engineering-project-v1','checks_config':'iceflow.yml',
             'mode':'observe','main_branch':'main'}
    write_new(output/'project.json',json.dumps(project,indent=2).encode())
    return {'created':str(output/'project.json'),'head_sha':view.sha,'authority':'NONE'}


def load_project(path: Path) -> tuple[dict,dict]:
    path=no_symlinks(path);data=parse_json(read_bytes(path))
    exact(data,{'schema','checks_config','mode','main_branch'},'PROJECT_SHAPE')
    require(data['schema']=='cairn-engineering-project-v1' and data['mode']=='observe','PROJECT_MODE_UNSUPPORTED')
    # Deliberately one sibling config; no path traversal or config auto-discovery.
    require(data['checks_config']=='iceflow.yml','PROJECT_CONFIG_PATH')
    require(data['main_branch']=='main','PROJECT_MAIN_BRANCH_UNSUPPORTED')
    cfg=load_config(path.parent/'iceflow.yml')
    no_symlinks(Path(cfg['repo_path']));outside(Path(cfg['output_dir']),Path(cfg['repo_path']))
    return data,cfg
