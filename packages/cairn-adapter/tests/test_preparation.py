"""Real temporary Store/Owner/Adapter and Git; GitHub is explicitly simulated."""
import copy
import hashlib
import json
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from contextlib import redirect_stdout
import io
import sys
from pathlib import Path

from cairn_adapter import Owner, Rejected
from cairn_adapter.preparation import PreparationHost, PreparationVerifier, activate, proposal, SCOPE, VERSION
from cairn_adapter.recovery import proof
from cairn_adapter.store import digest, get_config
from test_verifier import FixtureGitHub

TARGET = "01a0a959-b752-70f0-9118-900571ba60ab"
PM = "01a07d6f-05ae-74b1-90f3-3a9487ae4a24"


class PreparationIntegration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name); self.repo = self.root / "repo"; self.repo.mkdir()
        self.git("init", "-b", "main")
        self.git("remote", "add", "origin", "https://github.com/synthetic/repo.git")
        (self.repo / "source.txt").write_text("source\n")
        self.git("add", ".")
        self.git("-c", "user.name=Test", "-c", "user.email=test@example.invalid", "commit", "-m", "fixture")
        head = self.git("rev-parse", "HEAD"); tree = self.git("rev-parse", "HEAD^{tree}")
        p = dict(repository="synthetic/repo", issue=1632, issue_state="open",
                 issue_body_sha256=hashlib.sha256(b"reviewed issue").hexdigest(),
                 worktree=str(self.repo), head=head, tree=tree, target_thread=TARGET,
                 target_worktree=str(self.repo), scope=SCOPE)
        self.binding = dict(repository="synthetic/repo", worktree=str(self.repo), branch="main",
                            rule_version=VERSION, config_version=VERSION, base_ref="main", preparation=p)
        self.responses = {"repos/synthetic/repo/issues/1632": {"number":1632,"state":"open","body":"reviewed issue"},
                          "repos/synthetic/repo/commits/main": {"sha":head,"commit":{"tree":{"sha":tree}}}}
        self.github = FixtureGitHub(self.responses); self.verifier = PreparationVerifier(self.github)
        self.credentials = {k:(k+"-fixture-").ljust(64,"x") for k in ("owner", PM, TARGET)}
        self.contexts={PM:str(self.root/"pm-workspace"),TARGET:str(self.repo)}
        self.reviewed = proposal(self.binding, PM, self.credentials, self.root/"store",self.contexts)
        self.store, self.revision = activate(self.reviewed, self.credentials, digest(self.reviewed), self.verifier)
        self.host = PreparationHost(self.store, self.identity, self.verifier)
        self.host.checkpoint(self.credentials[PM], 1, self.revision)

    def git(self, *args):
        return subprocess.run(["git","-c","core.excludesFile=","-C",str(self.repo),*args],
                              check=True,capture_output=True).stdout.decode().strip()

    def identity(self, token):
        for task in (PM,TARGET):
            if token == self.credentials[task]: return dict(task_id=task,session_id=task,generation=1)
        return None

    def zero_write(self, fn):
        before=proof(self.store.path)
        with self.assertRaises((Rejected,ValueError)): fn()
        self.assertEqual(proof(self.store.path),before)

    def report(self, **kwargs):
        return self.host.report(kwargs.get("credential",self.credentials[TARGET]),
                                kwargs.get("generation",1),kwargs.get("revision",self.revision))

    def test_real_registry_checkpoint_report_and_no_event(self):
        before=proof(self.store.path); result=self.report()
        self.assertEqual(proof(self.store.path),before)
        self.assertEqual(result["stage"],SCOPE); self.assertFalse(result["source_edit_authorized"])
        self.assertFalse(result["transport_authorized"])
        self.assertEqual(result["source_binding"]["issue"],1632)
        self.assertEqual(result["inventory"][1]["task_id"],TARGET)
        self.assertNotEqual(self.reviewed["execution_contexts"][PM],self.binding["worktree"])
        self.assertEqual(self.reviewed["execution_contexts"][TARGET],self.binding["worktree"])
        with self.store.transaction() as (db,ledger):
            registry=get_config(db,"registry")
            self.assertEqual(registry["revision"],1)
            self.assertEqual(registry["entries"][1]["task_id"],TARGET)
            self.assertEqual(registry["entries"][1]["role"],"Infra")
            self.assertEqual(db.execute("select count(*) from events").fetchone()[0],0)
            self.assertEqual(db.execute("select scope from checkpoints").fetchone()[0],SCOPE)

    def test_stale_revision_generation_and_wrong_principal_zero_write(self):
        for kwargs in ({"revision":0},{"generation":2},{"credential":"wrong"*16},{"credential":self.credentials["owner"]}):
            with self.subTest(kwargs=kwargs): self.zero_write(lambda:self.report(**kwargs))
        host=PreparationHost(self.store,lambda _:dict(task_id=PM,session_id=PM,generation=1),self.verifier)
        self.zero_write(lambda:host.report(self.credentials[TARGET],1,1))

    def test_owner_cas_duplicate_registration_and_grant_expansion_zero_write(self):
        owner=Owner(self.store)
        self.zero_write(lambda:owner.replace(self.credentials["owner"],0,self.reviewed["entries"]))
        duplicates=self.reviewed["entries"]+[copy.deepcopy(self.reviewed["entries"][1])]
        self.zero_write(lambda:owner.replace(self.credentials["owner"],1,duplicates))
        self.zero_write(lambda:owner.replace(self.credentials[TARGET],1,self.reviewed["entries"]))
        self.zero_write(lambda:activate(self.reviewed,self.credentials,digest(self.reviewed),self.verifier))
        expanded=copy.deepcopy(self.reviewed); expanded["entries"][1]["grants"].append(dict(command="enqueue",scope=SCOPE,states=["ABSENT"]))
        self.zero_write(lambda:activate(expanded,self.credentials,digest(expanded),self.verifier))

    def test_scope_and_source_lifecycle_denied_zero_write(self):
        self.zero_write(lambda:self.host.adapter.execute(self.credentials[TARGET],1,1,"SOURCE","snapshot_prep",{"candidates":[]}))
        self.zero_write(lambda:self.host.checkpoint(self.credentials[TARGET],1,1))
        for task in (PM,TARGET):
            self.zero_write(lambda:self.host.adapter.execute(self.credentials[task],1,1,SCOPE,"enqueue",
                dict(dedupe_key="forbidden",target=TARGET,kind="APPROVAL",priority=1,dependency=None,next_action="edit")))

    def test_github_unavailable_wrong_issue_and_remote_head_drift_zero_write(self):
        key="repos/synthetic/repo/issues/1632"; original=copy.deepcopy(self.responses[key])
        for bad in (Rejected("GitHub unavailable"),dict(original,number=99),dict(original,body="drift"),dict(original,state="closed")):
            self.responses[key]=bad; self.zero_write(self.report)
        self.responses[key]=original
        self.responses["repos/synthetic/repo/commits/main"]["sha"]="a"*40
        self.zero_write(self.report)

    def test_local_head_dirty_branch_and_wrong_target_binding_zero_write(self):
        self.git("checkout","-b","wrong-branch"); self.zero_write(self.report)
        self.git("checkout","main")
        (self.repo/"source.txt").write_text("changed\n"); self.zero_write(self.report)
        self.git("add","."); self.git("-c","user.name=Test","-c","user.email=test@example.invalid","commit","-m","drift")
        self.zero_write(self.report)
        for key,value in (("target_thread","client-new-thread:pending"),("target_worktree",str(self.root))):
            bad=copy.deepcopy(self.binding); bad["preparation"][key]=value
            self.zero_write(lambda:self.verifier.verify(bad,SCOPE))

    def test_wrong_scope_valid_binding_and_payload_digest_rejected(self):
        self.zero_write(lambda:self.verifier.verify(self.binding,"SOURCE"))
        self.zero_write(lambda:activate(self.reviewed,self.credentials,"0"*64,self.verifier))

    def test_preflight_rejection_creates_no_store(self):
        payload=proposal(self.binding,PM,self.credentials,self.root/"unapproved",self.contexts)
        self.responses["repos/synthetic/repo/issues/1632"]=Rejected("offline")
        with self.assertRaises(Rejected): activate(payload,self.credentials,digest(payload),self.verifier)
        self.assertFalse((self.root/"unapproved").exists())

    def test_execution_identity_is_separate_and_review_bound(self):
        changed=copy.deepcopy(self.reviewed)
        changed["execution_contexts"][PM]=str(self.repo)
        self.zero_write(lambda:activate(changed,self.credentials,digest(self.reviewed),self.verifier))
        with self.assertRaises(Rejected):
            proposal(self.binding,PM,self.credentials,self.root/"wrong",{PM:str(self.repo),TARGET:str(self.root)})

    def test_operator_validation_and_worker_report_are_not_worker_ack(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"cairn-host"))
        import preparation_operator as cli
        folder=self.root/"proposal"; folder.mkdir()
        reviewed=proposal(self.binding,PM,self.credentials,self.root/"cli-store",self.contexts)
        (folder/"proposal.json").write_text(json.dumps(reviewed))
        (folder/"operator-credentials.json").write_text(json.dumps(self.credentials))
        (folder/"worker-credential.json").write_text(json.dumps({TARGET:self.credentials[TARGET]}))
        def invoke(command):
            output=io.StringIO()
            with patch.object(sys,"argv",["preparation_operator",command,"--proposal-root",str(folder),"--reviewed-digest",digest(reviewed)]), \
                 patch.object(cli,"activate",lambda r,c,d:activate(r,c,d,self.verifier)), \
                 patch.object(cli,"PreparationHost",lambda s,i:PreparationHost(s,i,self.verifier)), redirect_stdout(output):
                cli.main()
            value=json.loads(output.getvalue())
            for secret in self.credentials.values(): self.assertNotIn(secret,output.getvalue())
            self.assertFalse(value["worker_action_observed"])
            return value
        operator=invoke("activate")
        self.assertEqual(operator["observation_kind"],"OPERATOR_VALIDATION")
        self.assertEqual(operator["validation_actor"],PM)
        # Worker reporting must not even read operator/PM/owner credentials.
        (folder/"operator-credentials.json").write_text("operator credentials unavailable")
        worker=invoke("report")
        self.assertEqual(worker["observation_kind"],"LOCAL_REPORT_INVOCATION")
        self.assertEqual(worker["validation_actor"],TARGET)
        self.assertEqual(worker["platform_caller_identity"],"NOT_PROVEN")
