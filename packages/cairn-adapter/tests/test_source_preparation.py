"""Source lifecycle uses real Store, CAS, lease transitions and executable tests."""
import copy
import json
import sys
import unittest
import io
from contextlib import redirect_stdout
from unittest.mock import patch
from pathlib import Path

from cairn_adapter import Owner,Rejected
from cairn_adapter.source_preparation import SourceVerifier,SourceHost,source_proposal,activate_source,SCOPE,VERSION
from cairn_adapter.store import digest
from cairn_adapter.recovery import proof
import test_preparation as prep
from test_preparation import PM,TARGET


class SourceIntegration(unittest.TestCase):
    git=prep.PreparationIntegration.git
    identity=prep.PreparationIntegration.identity
    zero_write=prep.PreparationIntegration.zero_write

    def setUp(self):
        prep.PreparationIntegration.setUp(self)
        p=self.binding["preparation"]
        self.binding=dict(repository=p["repository"],worktree=str(self.repo),branch="main",rule_version=VERSION,config_version=VERSION,
            source=dict(issue=1632,issue_body_sha256=p["issue_body_sha256"],base=p["head"],base_tree=p["tree"],
                target_thread=TARGET,allowed_paths=["source.txt","tests"],evidence_root=str(self.root/"evidence"),
                head_semantics="APPROVED_BASELINE_NOT_CANDIDATE",permissions=["local_source","local_tests","pr_preparation"],
                allowed_branches=["main"],
                test_commands=[[sys.executable,"-c","print('passed')"],[sys.executable,"-c","from pathlib import Path; raise SystemExit(1 if Path('tests/fail').exists() else 0)"]]))
        self.verifier=SourceVerifier(self.github)
        self.reviewed=source_proposal(self.binding,PM,self.credentials,self.root/"source-store",self.contexts)
        # Exercise the existing owner CAS transition from PREPARATION, not a new registry.
        self.revision=Owner(self.store).replace(self.credentials["owner"],self.revision,self.reviewed["entries"])["revision"]
        self.host=SourceHost(self.store,self.identity,self.verifier)
        self.call(PM,"checkpoint")
        self.event=self.call(PM,"enqueue",dedupe_key="source-1632",target=TARGET,kind="APPROVAL",priority=1,dependency=None,next_action="Source/tests only")['id']

    def call(self,task,command,**args): return self.host.execute(self.credentials[task],1,self.revision,command,args)

    def start(self):
        claim=self.call(PM,"claim",event_id=self.event)
        self.call(PM,"sent",event_id=self.event,delivery_token=claim["delivery_token"],receipt="artifact://fixture/operator-observed-delivery")
        self.call(TARGET,"reconcile",event_id=self.event)
        self.token=self.call(TARGET,"ack",event_id=self.event)["worker_token"]
        self.call(TARGET,"start",event_id=self.event,worker_token=self.token,evidence="artifact://fixture/worker-start")

    def test_happy_mutable_candidate_renew_test_report_complete_once(self):
        self.start(); (self.repo/"source.txt").write_text("modified source\n")
        self.call(TARGET,"renew",event_id=self.event,worker_token=self.token)
        self.git("add","source.txt"); self.git("-c","user.name=Test","-c","user.email=test@example.invalid","commit","-m","source work")
        result=self.host.run_test(self.binding,0); self.assertEqual(result["exit_code"],0)
        second=self.host.run_test(self.binding,1)
        report=self.host.completion_report(self.binding,self.event,[result["evidence"],second["evidence"]])
        completed=self.call(TARGET,"complete",event_id=self.event,worker_token=self.token,evidence=report)
        self.assertEqual(completed["state"],"COMPLETED")
        self.zero_write(lambda:self.call(TARGET,"complete",event_id=self.event,worker_token=self.token,evidence=report))
        with self.store.transaction() as (db,ledger):
            self.assertEqual(db.execute("select count(*) from history where action='COMPLETED'").fetchone()[0],1)
            payload=json.loads(db.execute("select payload from events where id=?",(self.event,)).fetchone()[0])
            self.assertEqual(payload["head"],self.binding["source"]["base"])
            self.assertNotEqual(self.verifier.candidate(self.binding)["head"],payload["head"])

    def test_wrong_scope_principal_stale_cas_and_no_release_grants(self):
        self.zero_write(lambda:self.host.execute(self.credentials[TARGET],1,self.revision,"checkpoint",{}))
        self.zero_write(lambda:self.host.execute(self.credentials[TARGET],2,self.revision,"get",{"event_id":self.event}))
        self.zero_write(lambda:self.host.execute(self.credentials[TARGET],1,0,"get",{"event_id":self.event}))
        self.zero_write(lambda:self.host.adapter.execute(self.credentials[TARGET],1,self.revision,"release","get",{"event_id":self.event}))
        self.zero_write(lambda:self.call(TARGET,"authority_flip",event_id=self.event))
        self.zero_write(lambda:self.call(PM,"retire",event_id=self.event))

    def test_dirty_untracked_deleted_renamed_and_secret_paths_are_checked(self):
        for name in ("outside.py","tests/.env","tests/key.pem"):
            path=self.repo/name; path.parent.mkdir(exist_ok=True); path.write_text("forbidden")
            self.zero_write(lambda:self.call(TARGET,"get",event_id=self.event)); path.unlink()
        (self.repo/"source.txt").unlink()
        self.assertIsNone(self.verifier.candidate(self.binding)["files"][0]["sha256"])
        (self.repo/"outside.txt").write_text("renamed content")
        self.zero_write(lambda:self.call(TARGET,"get",event_id=self.event))

    def test_candidate_changes_after_tests_and_failed_tests_zero_write(self):
        self.start(); passed=self.host.run_test(self.binding,0)
        (self.repo/"source.txt").write_text("new untested content")
        report=self.host.completion_report(self.binding,self.event,[passed["evidence"]])
        self.zero_write(lambda:self.call(TARGET,"complete",event_id=self.event,worker_token=self.token,evidence=report))
        (self.repo/"tests").mkdir(exist_ok=True); (self.repo/"tests/fail").write_text("fail")
        failed=self.host.run_test(self.binding,1); self.assertEqual(failed["exit_code"],1)
        report=self.host.completion_report(self.binding,self.event,[failed["evidence"]])
        self.zero_write(lambda:self.call(TARGET,"complete",event_id=self.event,worker_token=self.token,evidence=report))

    def test_unresolved_or_wrong_event_report_rejected(self):
        self.start(); passed=self.host.run_test(self.binding,0)
        for event,refs in (("other-event",[passed["evidence"]]),(self.event,["https://example.invalid/asserted-pass"]),(self.event,[passed["evidence"]])):
            report=self.host.completion_report(self.binding,event,refs)
            self.zero_write(lambda:self.call(TARGET,"complete",event_id=self.event,worker_token=self.token,evidence=report))

    def test_duplicate_event_has_no_second_delivery_and_expired_lease_zero_write(self):
        duplicate=self.call(PM,"enqueue",dedupe_key="source-1632",target=TARGET,kind="APPROVAL",priority=1,dependency=None,next_action="Source/tests only")
        self.assertEqual(duplicate["id"],self.event)
        self.start(); self.zero_write(lambda:self.call(PM,"claim",event_id=self.event))
        # Store clock dependency simulates expiry without editing ledger data.
        self.store.clock=lambda:10**12
        self.zero_write(lambda:self.call(TARGET,"renew",event_id=self.event,worker_token=self.token))

    def test_github_issue_base_or_local_branch_drift_zero_write(self):
        key="repos/synthetic/repo/issues/1632"; original=self.responses[key]
        self.responses[key]=Rejected("GitHub unavailable")
        self.zero_write(lambda:self.call(TARGET,"get",event_id=self.event))
        self.responses[key]=original
        self.responses["repos/synthetic/repo/commits/main"]["sha"]="a"*40
        self.zero_write(lambda:self.call(TARGET,"get",event_id=self.event))

    def test_new_source_store_exact_payload_bootstrap_and_duplicate_rejection(self):
        store,revision=activate_source(self.reviewed,self.credentials,digest(self.reviewed),self.verifier)
        self.assertEqual(revision,1)
        before=proof(store.path)
        with self.assertRaises(Rejected): activate_source(self.reviewed,self.credentials,digest(self.reviewed),self.verifier)
        self.assertEqual(proof(store.path),before)

    def test_supported_cli_full_lifecycle_no_secret_output(self):
        sys.path.insert(0,str(Path(__file__).resolve().parents[2]/"cairn-host"))
        import source_operator as cli
        folder=self.root/"source-operator";folder.mkdir()
        event=dict(dedupe_key="cli-source",target=TARGET,kind="APPROVAL",priority=1,dependency=None,next_action="Source/tests only")
        package=dict(registry=self.reviewed,event=event)
        (folder/"proposal.json").write_text(json.dumps(package))
        (folder/"operator-credentials.json").write_text(json.dumps(self.credentials))
        (folder/"worker-credential.json").write_text(json.dumps({TARGET:self.credentials[TARGET]}))
        def run(command,*args):
            output=io.StringIO()
            argv=["source_operator",command,"--proposal-root",str(folder),"--reviewed-digest",digest(package),*args]
            with patch.object(sys,"argv",argv),patch.object(cli,"activate_source",lambda r,c,d:activate_source(r,c,d,self.verifier)), \
                 patch.object(cli,"SourceHost",lambda s,i:SourceHost(s,i,self.verifier)),redirect_stdout(output):cli.main()
            for secret in self.credentials.values():self.assertNotIn(secret,output.getvalue())
            for name,key in (("delivery-private.json","delivery_token"),("worker-lease-private.json","worker_token")):
                path=folder/name
                if path.exists():self.assertNotIn(json.loads(path.read_text())[key],output.getvalue())
            return json.loads(output.getvalue())["result"]
        run("activate");event_id=run("event")["event_id"]
        run("sent","--event-id",event_id,"--evidence","artifact://fixture/operator-observed")
        # Worker CLI cannot depend on owner/PM secret material.
        (folder/"operator-credentials.json").write_text("unavailable")
        run("ack","--event-id",event_id)
        run("start","--event-id",event_id,"--evidence","artifact://fixture/worker-start")
        tested=run("test","--event-id",event_id,"--test-index","0")
        second=run("test","--event-id",event_id,"--test-index","1")
        completed=run("complete","--event-id",event_id,"--test-evidence",tested["evidence"],"--test-evidence",second["evidence"])
        self.assertEqual(completed["state"],"COMPLETED")
