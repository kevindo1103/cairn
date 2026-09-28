"""Protected-host seam for live observations; never a second ledger or dispatcher.

The host supplies a non-mutating canonical snapshot reader. This avoids loading
raw Store/Owner/credentials into a worker or using an offline copy as live truth.
"""
from __future__ import annotations
import time

from iceflow_harness.common import canonical,digest,parse_json
from .contracts import require,validate_binding
from .resume import reconcile


def semantic_ledger_digest(snapshot):
    # Observation timestamps can change while canonical task content does not.
    return digest(canonical({k:snapshot.get(k) for k in
                             ('core_schema','events','checkpoints','recipients','registry')}))


class ResumeService:
    """Called by existing host at resume/before proposing the next action.

    Provider identity/access controls are a host responsibility. The result is
    advisory; every side effect still goes through current Adapter authorization.
    The service never calls recover, renew, complete, dispatch or filesystem edits.
    """
    def __init__(self,ledger_reader,local_reader,github_reader,*,clock=time.time):
        self.ledger_reader=ledger_reader;self.local_reader=local_reader
        self.github_reader=github_reader;self.clock=clock

    def observe(self,binding):
        b=parse_json(canonical(validate_binding(binding)))
        before=self.ledger_reader(b);local_before=self.local_reader(b)
        remote=self.github_reader(b)
        after=self.ledger_reader(b);local_after=self.local_reader(b)
        require(semantic_ledger_digest(before)==semantic_ledger_digest(after),'LEDGER_SNAPSHOT_MOVED')
        require(all(local_before.get(k)==local_after.get(k) for k in
             ('head_sha','tree_sha','dirty','index_sha256','changed_paths_digest')),'LOCAL_SOURCE_MOVED')
        return reconcile(b,after,local_after,remote,now=self.clock())
