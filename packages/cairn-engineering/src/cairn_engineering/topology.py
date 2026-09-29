"""Roles are routing labels, never credentials or automatic session creation."""
from __future__ import annotations
import importlib.resources

from iceflow_harness.common import Refused, canonical, digest, parse_json, safe_rel
from .contracts import exact, integer, require, word


def topology() -> dict:
    return parse_json(importlib.resources.files('cairn_engineering').joinpath('data/topology.json').read_bytes())


def resolve_role(role: str, bindings: dict, *, registry: dict | None = None) -> dict:
    definition=topology()['roles'].get(role)
    require(definition is not None, 'ROLE_UNKNOWN')
    matches=bindings.get(role)
    require(type(matches) is list and len(matches)==1,'ROLE_MAPPING_MISSING_OR_AMBIGUOUS')
    p=matches[0]
    exact(p, {'task_id','session_id','generation'},'ROLE_BINDING_SHAPE')
    word(p['task_id']);word(p['session_id']);integer(p['generation'])
    if registry is not None:
        matches=[x for x in registry['entries'] if x['task_id']==p['task_id']]
        require(len(matches)==1,'REGISTRY_PRINCIPAL_AMBIGUOUS')
        actual=matches[0]
        require(all(actual[k]==p[k] for k in p) and actual['state']=='active','ROLE_GENERATION_STALE')
        require(actual['role'] in definition['registry_roles'],'ROLE_CLASS_MISMATCH')
    return dict(p,role=role)


def overlaps(paths_a: list[str], paths_b: list[str]) -> bool:
    for p in paths_a+paths_b:safe_rel(p)
    return any(a==b or a.startswith(b+'/') or b.startswith(a+'/') for a in paths_a for b in paths_b)


def route_finding(check: str, roles: dict) -> dict:
    role=topology()['findings'].get(check,'domain_lead')
    target=resolve_role(role,roles)
    return {'owner_role':role,'task_id':target['task_id'],'action':'review_finding',
            'authority':'NONE','dispatch_executed':False}
