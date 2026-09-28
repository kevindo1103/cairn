"""Fresh bounded Git/GitHub observations. No comment-to-authority parser."""
from __future__ import annotations

import time
from pathlib import Path
from urllib.parse import quote

from iceflow_harness.common import Refused, canonical, digest, no_symlinks
from iceflow_harness.gitview import GitView
from iceflow_harness.github import ReadOnlyGitHub
from .contracts import inert, require, seal, sha40, validate_binding


def local_snapshot(repo: Path, binding: dict) -> dict:
    """Observe CURRENT HEAD, not just the old SHA mentioned by a conversation."""
    repo=no_symlinks(repo)
    first=GitView(repo,'HEAD')
    branch=first._git(['branch','--show-current']).decode().strip()
    index=digest(first._git(['diff','--cached','--no-ext-diff','--no-textconv','--binary','HEAD','--']))
    # Only names/hash, never file contents or raw diff in reports.
    changed=first._git(['diff','--no-ext-diff','--no-textconv','--name-only','-z','HEAD','--'])
    second=GitView(repo,'HEAD')
    require((first.sha,first.tree,first.dirty)==(second.sha,second.tree,second.dirty), 'LOCAL_SOURCE_MOVED')
    require(index==digest(second._git(['diff','--cached','--no-ext-diff','--no-textconv','--binary','HEAD','--'])), 'LOCAL_INDEX_MOVED')
    origin=first._git(['remote','get-url','--all','origin']).decode().strip()
    expected=binding['repository']
    require(origin in {f'https://github.com/{expected}',f'https://github.com/{expected}.git',f'git@github.com:{expected}.git'},'LOCAL_REMOTE_MISMATCH')
    return {'head_sha':first.sha,'tree_sha':first.tree,'branch':branch,'dirty':first.dirty,
            'index_sha256':index,'changed_paths_digest':digest(changed),
            'observed_at_unix':time.time(),'origin':'LOCAL_GIT_READ_ONLY'}


def task_snapshot(client: ReadOnlyGitHub, binding: dict) -> dict:
    """Two reads of task identity; no cache fallback and no hidden retry."""
    binding=validate_binding(binding)
    require(client.repository==binding['repository'] and client.repository_id==binding['repository_id'], 'CLIENT_REPOSITORY_MISMATCH')
    repository=client.get('')
    require(repository.get('id')==binding['repository_id'] and repository.get('full_name','').lower()==binding['repository'].lower(), 'REPOSITORY_ID_MISMATCH')
    def observe():
        issue=client.get(f"/issues/{binding['issue']}")
        require(issue.get('number')==binding['issue'] and issue.get('state') in {'open','closed'},'ISSUE_SHAPE_INVALID')
        task={'issue':binding['issue'],'issue_state':issue['state'],
              'issue_body_sha256':digest((issue.get('body') or '').encode()),
              'issue_updated_at':issue.get('updated_at'),'pr':None}
        if binding['pr'] is not None:
            pr=client.get(f"/pulls/{binding['pr']}")
            require(pr.get('number')==binding['pr'] and pr.get('state') in {'open','closed'} and
                    type(pr.get('merged')) is bool,'PR_SHAPE_INVALID')
            require(pr['base']['repo']['id']==binding['repository_id'],'PR_REPOSITORY_MISMATCH')
            task['pr']={'number':pr['number'],'state':pr['state'],'merged':pr['merged'],
                        'head_sha':sha40(pr['head']['sha']),'base_sha':sha40(pr['base']['sha']),
                        'head_repository_id':pr['head']['repo']['id'],
                        'merge_commit_sha':pr.get('merge_commit_sha'),
                        'body_sha256':digest((pr.get('body') or '').encode()),'updated_at':pr.get('updated_at')}
            if task['pr']['merged']:
                require(pr['state']=='closed','PR_MERGE_STATE_INVALID');sha40(task['pr']['merge_commit_sha'])
        branch=client.get('/branches/'+quote(binding['main_branch'],safe=''))
        require(branch.get('name')==binding['main_branch'],'MAIN_BRANCH_MISMATCH')
        task['main_sha']=sha40(branch['commit']['sha'])
        return task
    start=observe();end=observe()
    require(start==end,'GITHUB_TASK_CHANGED_DURING_READ')
    return seal(inert('cairn-github-task-observation-v1',repository=binding['repository'],
         repository_id=binding['repository_id'],task=start,api_reads=client.reads,
         observed_at_unix=time.time(),origin='DIRECT_GITHUB_GET',
         comments_authority='NOT_EVALUATED',cross_system_atomicity=False))
