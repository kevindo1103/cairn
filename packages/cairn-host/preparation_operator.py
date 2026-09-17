"""Operator-reviewed PREPARATION proposals. No transport or source execution.

Task identities are reviewed data, never framework constants. Local bearer
access is operator attestation, not platform identity enforcement.
"""
import argparse
import hashlib
import json
from pathlib import Path
import secrets
import sys

for directory in ("cairn-adapter", "communication-ledger"):
    sys.path.insert(0,str(Path(__file__).resolve().parents[1]/directory))
from cairn_adapter import GitHubVerifier, Rejected, Store
from cairn_adapter.preparation import PreparationVerifier, PreparationHost, proposal, activate, VERSION
from cairn_adapter.store import canonical, digest, get_config


def draft(root, profile):
    required={"repository","issue","pm_task","target_task","resource_worktree","store_root","execution_contexts"}
    if not isinstance(profile,dict) or set(profile)!=required:
        raise Rejected("Incomplete operator profile")
    github=GitHubVerifier(); cwd=Path(profile["resource_worktree"]).resolve(strict=True)
    repo=profile["repository"]; number=profile["issue"]
    def git(*args): return github._run([github.git,"-C",str(cwd),*args],cwd).decode().strip()
    issue=json.loads(github._run([github.gh,"api","--hostname","github.com",f"repos/{repo}/issues/{number}"],cwd))
    p=dict(repository=repo,issue=number,issue_state="open",
           issue_body_sha256=hashlib.sha256((issue["body"] or "").encode()).hexdigest(),
           worktree=str(cwd),head=git("rev-parse","HEAD"),tree=git("rev-parse","HEAD^{tree}"),
           target_thread=profile["target_task"],target_worktree=str(cwd),scope="PREPARATION")
    binding=dict(repository=repo,worktree=str(cwd),branch=git("branch","--show-current") or "DETACHED",
                 rule_version=VERSION,config_version=VERSION,base_ref="main",preparation=p)
    verified=PreparationVerifier(github).verify(binding,"PREPARATION")
    if Path(profile["store_root"]).exists(): raise Rejected("Proposed Store exists; inspect owner/config first")
    credentials={task:secrets.token_hex(32) for task in ("owner",profile["pm_task"],profile["target_task"])}
    reviewed=proposal(binding,profile["pm_task"],credentials,profile["store_root"],profile["execution_contexts"])
    root.mkdir(parents=True,exist_ok=False)
    (root/"proposal.json").write_text(canonical(reviewed),encoding="utf-8")
    (root/"operator-credentials.json").write_text(canonical(credentials),encoding="utf-8")
    (root/"worker-credential.json").write_text(canonical({profile["target_task"]:credentials[profile["target_task"]]}),encoding="utf-8")
    result=dict(status="AWAITING_EXACT_PAYLOAD_REVIEW",proposal_path=str(root/"proposal.json"),
                proposal_sha256=digest(reviewed),checkpoint=verified,store_created=False,
                source_edit_authorized=False,transport_authorized=False)
    (root/"readiness.json").write_text(json.dumps(result,indent=2),encoding="utf-8")
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("draft","activate","report"))
    parser.add_argument("--proposal-root",type=Path,required=True)
    parser.add_argument("--profile",type=Path)
    parser.add_argument("--reviewed-digest")
    args=parser.parse_args(); root=args.proposal_root.absolute()
    if any(p.is_symlink() or getattr(p, "is_junction", lambda: False)() for p in (root,*root.parents)):
        raise Rejected("Linked proposal root refused")
    if args.command=="draft":
        if args.reviewed_digest or not args.profile: parser.error("draft requires profile and no approval digest")
        result=draft(root,json.loads(args.profile.read_text(encoding="utf-8")))
    else:
        if not args.reviewed_digest or args.profile: parser.error("requires exact reviewed digest and no profile override")
        reviewed=json.loads((root/"proposal.json").read_text(encoding="utf-8"))
        if digest(reviewed)!=args.reviewed_digest: raise Rejected("Reviewed proposal changed")
        pm=reviewed["pm_task"]; target=reviewed["entries"][1]["task_id"]
        credential_file="operator-credentials.json" if args.command=="activate" else "worker-credential.json"
        credentials=json.loads((root/credential_file).read_text(encoding="utf-8"))
        def identity(token):
            for task in (pm,target):
                if credentials.get(task)==token: return dict(task_id=task,session_id=task,generation=1)
            return None
        if args.command=="activate":
            store,revision=activate(reviewed,credentials,args.reviewed_digest)
            host=PreparationHost(store,identity)
            host.checkpoint(credentials[pm],1,revision)
            # Operator validates using PM authority; this is not a worker ACK.
            result=host.report(credentials[pm],1,revision)
            result.update(validation_actor=pm,observation_kind="OPERATOR_VALIDATION",worker_action_observed=False)
        else:
            store=Store(reviewed["store_root"],reviewed["project"])
            with store.transaction() as (db,ledger):
                registry=get_config(db,"registry")
                if registry["entries"]!=reviewed["entries"]: raise Rejected("Registry differs from reviewed proposal")
                revision=registry["revision"]
            result=PreparationHost(store,identity).report(credentials[target],1,revision)
            result.update(validation_actor=target,observation_kind="LOCAL_REPORT_INVOCATION",
                          platform_caller_identity="NOT_PROVEN",worker_action_observed=False)
        result.update(store_path=str(store.path),proposal_sha256=args.reviewed_digest,
                      execution_contexts=reviewed["execution_contexts"])
        if args.command=="activate":
            with (root/"activation-result.json").open("x",encoding="utf-8") as stream: json.dump(result,stream,indent=2)
    print(json.dumps(result))


if __name__=="__main__": main()
