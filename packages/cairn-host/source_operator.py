"""Host/operator CLI for source work. No command performs platform transport."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import secrets
import sys
for directory in ("cairn-adapter", "communication-ledger"):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / directory))
from cairn_adapter import GitHubVerifier, Store, Rejected
from cairn_adapter.source_preparation import (
    SourceVerifier, SourceHost, source_proposal, activate_source, SCOPE, VERSION,
    BoundSourceStore, build_successor, admit_successor, principal_identity,
    successor_preconditions, build_bounded_binding_update,
    admit_bounded_binding_update)
from cairn_adapter.source_preparation import build_recovery_authority, admit_recovery_authority, require_proven_no_send
from cairn_adapter.store import canonical, digest, get_config
from comms_ledger.ledger import evidence_ref


def read_json(path):
    return json.loads(read_bytes(path).decode("utf-8"))


def read_bytes(path):
    if any(p.is_symlink() or p.is_junction() for p in (path, *path.parents)):
        raise Rejected("Linked operator artifact")
    return path.read_bytes()


def write_private(path, raw):
    # Create-only, including on partial failure: an ambiguous artifact blocks replay.
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())


def recovery_material(root, package):
    recovery = package["recovery"]
    prior_root = Path(recovery["prior_root"])
    prior = read_json(prior_root / "proposal.json")
    original = read_bytes(prior_root / "delivery-private.json")
    retained = read_bytes(root / "delivery-private.json")
    if (digest(prior) != recovery["prior_proposal_digest"] or original != retained
            or hashlib.sha256(retained).hexdigest() != recovery["receipt_sha256"]):
        raise Rejected("Original proposal/receipt provenance changed")
    return prior, json.loads(retained)


def recovery_inspection(root, package, db, event, actor, generation, revision):
    value = read_json(root / "recovery-inspection.json")
    expected = dict(event_id=event["id"], event_digest=event["digest"],
                    proposal_digest=digest(package), receipt_sha256=package["recovery"]["receipt_sha256"],
                    operator=actor, generation=generation, registry_revision=revision,
                    no_send_confirmed=True, authority="pilot operator confirmation authority")
    if set(value) != set(expected) | {"evidence"} or any(value[k] != v for k, v in expected.items()):
        raise Rejected("Inspection artifact binding mismatch")
    evidence_ref(value["evidence"])
    evidence = "artifact://sha256/" + digest(value)
    records = db.execute("SELECT actor,detail FROM history WHERE event_id=? AND action='INSPECTION_EVIDENCE'",
                         (event["id"],)).fetchall()
    if len(records) != 1 or records[0]["actor"] != actor or json.loads(records[0]["detail"]) != {"evidence": evidence}:
        raise Rejected("Inspection is missing, ambiguous or not durably committed")
    return value


def successor_draft(root, prior_root, profile, verifier=None):
    """Create a compatible proposal and reuse credentials; never mutate the Store."""
    prior = read_json(prior_root / "proposal.json")
    credentials = read_json(prior_root / "operator-credentials.json")
    reviewed = prior["registry"]
    store = Store(reviewed["store_root"], reviewed["project"])
    package = build_successor(store, prior, profile, credentials, verifier or SourceVerifier())
    root.mkdir(parents=True, exist_ok=False)
    save(root / "proposal.json", package)
    save(root / "operator-credentials.json", credentials)
    save(root / "worker-credential.json", {profile["target_task"]: credentials[profile["target_task"]]})
    result = dict(proposal_path=str(root / "proposal.json"), proposal_sha256=digest(package),
                  expected_registry_revision=profile["expected_registry_revision"],
                  state="AWAITING_EXACT_REVIEW", live_store_created=False, transport_authorized=False)
    save(root / "readiness.json", result)
    return result


def save(path,value):
    with path.open("x",encoding="utf-8") as stream: stream.write(canonical(value))


def draft(root,profile):
    fields={"repository","issue","pm_task","target_task","resource_worktree","store_root","execution_contexts",
            "allowed_paths","work_branch","test_commands","evidence_root","dedupe"}
    if set(profile)!=fields: raise Rejected("Incomplete source profile")
    gh=GitHubVerifier(); cwd=Path(profile["resource_worktree"]).resolve(strict=True)
    def git(*a):return gh._run([gh.git,"-C",str(cwd),*a],cwd).decode().strip()
    repo=profile["repository"]; issue=profile["issue"]
    body=json.loads(gh._run([gh.gh,"api","--hostname","github.com",f"repos/{repo}/issues/{issue}"],cwd))
    source=dict(issue=issue,issue_body_sha256=hashlib.sha256((body["body"] or "").encode()).hexdigest(),
                base=git("rev-parse","HEAD"),base_tree=git("rev-parse","HEAD^{tree}"),
                target_thread=profile["target_task"],allowed_paths=profile["allowed_paths"],
                evidence_root=profile["evidence_root"],head_semantics="APPROVED_BASELINE_NOT_CANDIDATE",
                permissions=["local_source","local_tests","pr_preparation"],test_commands=profile["test_commands"],
                allowed_branches=sorted(set([git("branch","--show-current") or "DETACHED",profile["work_branch"]])))
    binding=dict(repository=repo,worktree=str(cwd),branch=profile["work_branch"],
                 rule_version=VERSION,config_version=VERSION,source=source)
    SourceVerifier(gh).verify(binding,SCOPE)
    credentials={key:secrets.token_hex(32) for key in ("owner",profile["pm_task"],profile["target_task"])}
    reviewed=source_proposal(binding,profile["pm_task"],credentials,profile["store_root"],profile["execution_contexts"])
    # The event contract is independently reviewed and uses the same immutable source binding.
    event=dict(dedupe_key=profile["dedupe"],target=profile["target_task"],kind="APPROVAL",priority=1,dependency=None,
               next_action="Implement only reviewed local source/tests; return exact candidate and test artifacts for review")
    package=dict(registry=reviewed,event=event)
    if Path(reviewed["store_root"]).exists(): raise Rejected("Existing Store requires separately reviewed CAS transition")
    root.mkdir(parents=True,exist_ok=False)
    save(root/"proposal.json",package);save(root/"operator-credentials.json",credentials)
    save(root/"worker-credential.json",{profile["target_task"]:credentials[profile["target_task"]]})
    result=dict(proposal_path=str(root/"proposal.json"),proposal_sha256=digest(package),registry_sha256=digest(reviewed),
                state="AWAITING_EXACT_REVIEW",live_store_created=False,transport_authorized=False)
    save(root/"readiness.json",result)
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("draft", "successor-draft", "binding-update-draft",
                                           "binding-update", "activate", "event",
                                           "inspect-retry", "reclaim", "recover-authority", "recovery-draft", "sent", "ack", "start", "renew", "test", "complete", "status"))
    parser.add_argument("--proposal-root", type=Path, required=True)
    parser.add_argument("--prior-proposal-root", type=Path)
    parser.add_argument("--profile", type=Path)
    parser.add_argument("--reviewed-digest")
    parser.add_argument("--event-id")
    parser.add_argument("--evidence")
    parser.add_argument("--no-send-confirmed", action="store_true")
    parser.add_argument("--reuse-existing-grant", action="store_true")
    parser.add_argument("--test-index", type=int)
    parser.add_argument("--test-evidence", action="append")
    args = parser.parse_args(argv)
    root = args.proposal_root.absolute()
    if any(p.is_symlink() or p.is_junction() for p in (root, *root.parents)):
        raise Rejected("Linked operator root")
    if args.command in {"draft", "successor-draft", "recovery-draft", "binding-update-draft"}:
        if (args.command != "recovery-draft" and not args.profile) or args.reviewed_digest:
            parser.error("draft requires profile, no approval digest")
        profile = read_json(args.profile.absolute()) if args.profile else None
        if args.command == "successor-draft":
            if not args.prior_proposal_root:
                parser.error("successor-draft requires prior proposal root")
            result = successor_draft(root, args.prior_proposal_root.absolute(), profile)
        elif args.command == "binding-update-draft":
            if not args.prior_proposal_root:
                parser.error("binding-update-draft requires prior proposal root")
            prior_root = args.prior_proposal_root.absolute()
            prior = read_json(prior_root / "proposal.json")
            credentials = read_json(prior_root / "operator-credentials.json")
            reviewed = prior["registry"]
            store = Store(reviewed["store_root"], reviewed["project"])
            package = build_bounded_binding_update(store, prior, profile, credentials)
            root.mkdir(parents=True, exist_ok=False)
            save(root / "proposal.json", package)
            save(root / "operator-credentials.json", credentials)
            save(root / "worker-credential.json",
                 {profile["target_task"]: credentials[profile["target_task"]]})
            result = dict(proposal_path=str(root / "proposal.json"),
                proposal_sha256=digest(package), expected_registry_revision=profile["expected_registry_revision"],
                authority="pilot operator confirmation authority", state="AWAITING_EXACT_REVIEW",
                registry_mutated=False, event_created=False)
        elif args.command == "recovery-draft":
            if not args.prior_proposal_root or not args.event_id:
                parser.error("recovery-draft requires prior proposal root and event id")
            prior_root = args.prior_proposal_root.absolute()
            prior = read_json(prior_root / "proposal.json")
            credentials = read_json(prior_root / "operator-credentials.json")
            receipt_raw = read_bytes(prior_root / "delivery-private.json")
            receipt = json.loads(receipt_raw)
            store = Store(prior["registry"]["store_root"], prior["registry"]["project"])
            package = build_recovery_authority(store, prior, credentials, args.event_id, receipt,
                prior_root, hashlib.sha256(receipt_raw).hexdigest(), SourceVerifier(),
                reuse_existing_grant=args.reuse_existing_grant)
            root.mkdir(parents=True, exist_ok=False); save(root / "proposal.json", package)
            write_private(root / "operator-credentials.json", canonical(credentials).encode())
            write_private(root / "worker-credential.json", canonical(
                {package["event"]["target"]: credentials[package["event"]["target"]]}).encode())
            write_private(root / "delivery-private.json", receipt_raw)
            result = dict(proposal_path=str(root / "proposal.json"), proposal_sha256=digest(package),
                          expected_registry_revision=package["recovery"]["expected_revision"],
                          admitted_registry_revision=package["recovery"]["admitted_revision"],
                          authority_mode=package["recovery"]["authority_mode"],
                          state="AWAITING_EXACT_REVIEW", transport_executed=False)
        else:
            result = draft(root, profile)
        print(json.dumps(result))
        return
    package = read_json(root / "proposal.json")
    if digest(package) != args.reviewed_digest:
        raise Rejected("Source operator payload not exactly reviewed")
    if args.command == "recover-authority":
        credentials = read_json(root / "operator-credentials.json")
        prior, receipt = recovery_material(root, package)
        print(json.dumps(dict(result=admit_recovery_authority(package, credentials, args.reviewed_digest,
                              prior, receipt, SourceVerifier()),
                              transport_executed=False, platform_identity="NOT_PROVEN")))
        return
    if args.command == "binding-update":
        credentials = read_json(root / "operator-credentials.json")
        result = admit_bounded_binding_update(package, credentials, args.reviewed_digest)
        print(json.dumps(dict(result=result, event_created=False, transport_executed=False,
                              platform_identity="NOT_PROVEN")))
        return
    if args.command in {"inspect-retry", "reclaim"} and "recovery" not in package:
        raise Rejected("Require exact reviewed recovery package")
    if "recovery" in package and (args.command in {"activate", "event"}
            or args.event_id != package["recovery"]["event_id"]):
        raise Rejected("Recovery package is limited to its existing event; no activation/enqueue")
    reviewed = package["registry"]
    pm, target = reviewed["pm_task"], package["event"]["target"]
    entries = {e["task_id"]: e for e in reviewed["entries"]}
    binding = entries[target]["bindings"][SCOPE]
    operator = args.command in {"activate", "event", "inspect-retry", "reclaim", "sent"}
    credentials = read_json(root / ("operator-credentials.json" if operator else "worker-credential.json"))
    actor = pm if operator else target
    identity = principal_identity(reviewed["entries"], credentials)
    generation = entries[actor]["generation"]
    if args.command == "activate":
        if "successor" in package:
            result = admit_successor(package, credentials, args.reviewed_digest, SourceVerifier())
        else:
            store, revision = activate_source(reviewed, credentials, digest(reviewed))
            result = SourceHost(store, identity).execute(credentials[pm], generation, revision, "checkpoint", {})
        print(json.dumps(dict(result=result, transport_executed=False, platform_identity="NOT_PROVEN")))
        return
    store = Store(reviewed["store_root"], reviewed["project"])
    with store.transaction() as (db, ledger):
        registry = get_config(db, "registry")
        revision = registry["revision"]
        if (registry["entries"] != reviewed["entries"] or ("successor" in package
                and revision != reviewed["expected_revision"] + 1)):
            raise Rejected("Registry differs from admitted proposal")
        if "recovery" in package and (revision != package["recovery"]["admitted_revision"]
                or digest(registry) != package["recovery"]["admitted_digest"]):
            raise Rejected("Recovery requires exact admitted registry revision/digest")
        if args.event_id:
            event = ledger._get(db, args.event_id)
            payload = json.loads(event["payload"])
            if (event["target"] != target or event["dedupe_key"] != package["event"]["dedupe_key"]
                    or payload["source_task"] != pm or payload["scope"] != SCOPE):
                raise Rejected("Event differs from reviewed assignment")
            if "recovery" in package and event["digest"] != package["recovery"]["event_digest"]:
                raise Rejected("Recovery event digest changed")
    host = SourceHost(store, identity)
    def call(command, **kwargs):
        return host.execute(credentials[actor], generation, revision, command, kwargs)

    if args.command == "inspect-retry":
        if not args.evidence or not args.no_send_confirmed:
            raise Rejected("Require explicit PM no-send confirmation and evidence; absence of SENT is not proof")
        evidence_ref(args.evidence)
        _, old = recovery_material(root, package)
        path = root / "recovery-inspection.json"
        if path.exists():
            raise Rejected("Existing inspection artifact; reconcile only")
        with store.transaction() as (db, ledger):
            row = ledger._get(db, args.event_id)
            require_proven_no_send(db, store, row, pm, generation, old)
            if digest(dict(row)) != package["recovery"]["claim_digest"]:
                raise Rejected("Claim changed since recovery review")
            inspection = dict(event_id=row["id"], event_digest=row["digest"], proposal_digest=digest(package),
                receipt_sha256=package["recovery"]["receipt_sha256"], operator=pm, generation=generation,
                registry_revision=revision, no_send_confirmed=True, evidence=args.evidence,
                authority="pilot operator confirmation authority")
            result = SourceHost(BoundSourceStore(store, db, ledger), identity).execute(
                credentials[pm], generation, revision, "inspect_retry",
                {"event_id": args.event_id, "evidence": "artifact://sha256/" + digest(inspection)})
            write_private(path, canonical(inspection).encode())
        print(json.dumps(dict(result=result, recovery="INSPECTED_ONLY", transport_executed=False,
                              platform_identity="NOT_PROVEN")))
        return
    if args.command == "reclaim":
        recovery_material(root, package)
        path = root / "delivery-attempt-2.json"
        if path.exists():
            raise Rejected("Current reclaim attempt already exists; reconcile only")
        with store.transaction() as (db, ledger):
            row = ledger._get(db, args.event_id)
            recovery_inspection(root, package, db, row, pm, generation, revision)
            if (row["state"] != "QUEUED" or row["needs_inspection"] or row["attempts"] != 1
                    or row["delivery_token"] is not None or row["receipt"] is not None
                    or row["eligible_at"] > store.clock()):
                raise Rejected("Reclaim requires inspected QUEUED event after backoff")
            claimed = SourceHost(BoundSourceStore(store, db, ledger), identity).execute(
                credentials[pm], generation, revision, "claim", {"event_id": args.event_id})
            if not claimed:
                raise Rejected("Reclaim backoff or delivery lane not ready")
            private = dict(event_id=args.event_id, delivery_token=claimed["delivery_token"], attempt=2,
                proposal_digest=digest(package), prior_receipt_sha256=package["recovery"]["receipt_sha256"])
            write_private(path, canonical(private).encode())
            result = dict(event_id=args.event_id, state="QUEUED", recovery="RECLAIMED", attempt=2,
                          delivery_until=claimed["event"]["delivery_until"])
        print(json.dumps(dict(result=result, old_receipt=str(root / "delivery-private.json"),
                              new_receipt=str(path), transport_executed=False,
                              platform_identity="NOT_PROVEN")))
        return
    if args.command in {"event", "ack"}:
        path = root / ("delivery-private.json" if args.command == "event" else "worker-lease-private.json")
        # Reserve exclusively BEFORE any mutation. An empty/partial artifact after
        # interruption is ambiguous and requires operator reconciliation, never retry.
        if path.exists():
            raise Rejected("Existing private receipt; reconcile only, never blind replay")
        with store.transaction() as (db, ledger):
            bound = BoundSourceStore(store, db, ledger)
            local = SourceHost(bound, identity)
            def invoke(command, **kwargs):
                return local.execute(credentials[actor], generation, revision, command, kwargs)
            if args.command == "event":
                if "successor" in package:
                    proof = successor_preconditions(db, ledger, package["successor"]["profile"],
                                                    check_registry=False)
                    if proof != package["successor"]["parent_proof"]:
                        raise Rejected("Parent release evidence changed")
                if db.execute("SELECT 1 FROM events WHERE dedupe_key=?",
                              (package["event"]["dedupe_key"],)).fetchone():
                    raise Rejected("Existing delivery assignment; reconcile only")
            else:
                row = ledger._get(db, args.event_id)
                if row["state"] != "SENT":
                    raise Rejected("ACK requires fresh SENT event")
            with path.open("x", encoding="utf-8") as stream:
                if args.command == "event":
                    event = invoke("enqueue", **package["event"])
                    claimed = invoke("claim", event_id=event["id"])
                    private = dict(event_id=event["id"], delivery_token=claimed["delivery_token"])
                    result = dict(event_id=event["id"], state="QUEUED", transport="NOT_SENT")
                else:
                    invoke("reconcile", event_id=args.event_id)
                    value = invoke("ack", event_id=args.event_id)
                    private = dict(event_id=args.event_id, worker_token=value["worker_token"])
                    result = dict(event_id=args.event_id, state="ACKED")
                stream.write(canonical(private))
                stream.flush()
                os.fsync(stream.fileno())
    elif args.command == "sent":
        if not args.evidence:
            raise Rejected("PM-observed actual delivery evidence required")
        if "recovery" in package:
            recovery_material(root, package)
            delivery = read_json(root / "delivery-attempt-2.json")
            with store.transaction() as (db, ledger):
                row = ledger._get(db, args.event_id)
                recovery_inspection(root, package, db, row, pm, generation, revision)
                expected = dict(event_id=args.event_id, attempt=2, proposal_digest=digest(package),
                    prior_receipt_sha256=package["recovery"]["receipt_sha256"], delivery_token=row["delivery_token"])
                if (delivery != expected or row["state"] != "QUEUED" or row["attempts"] != 2
                        or row["receipt"] is not None or row["needs_inspection"] or not row["delivery_token"]):
                    raise Rejected("Current attempt receipt does not match durable delivery claim")
                result = SourceHost(BoundSourceStore(store, db, ledger), identity).execute(
                    credentials[pm], generation, revision, "sent",
                    dict(event_id=args.event_id, delivery_token=delivery["delivery_token"], receipt=args.evidence))
        else:
            delivery = read_json(root / "delivery-private.json")
            if args.event_id != delivery["event_id"]:
                raise Rejected("Delivery event mismatch")
            result = call("sent", event_id=args.event_id, delivery_token=delivery["delivery_token"], receipt=args.evidence)
    elif args.command == "status":
        result = call("get", event_id=args.event_id)
    else:
        lease = read_json(root / "worker-lease-private.json")
        if args.event_id != lease["event_id"]:
            raise Rejected("Worker event mismatch")
        if args.command == "test":
            if call("get", event_id=args.event_id)["state"] != "STARTED":
                raise Rejected("Tests require STARTED")
            call("renew", event_id=args.event_id, worker_token=lease["worker_token"])
            result = host.run_test(binding, args.test_index)
        else:
            kwargs = dict(event_id=args.event_id, worker_token=lease["worker_token"])
            if args.command == "complete":
                if call("get", event_id=args.event_id)["state"] != "STARTED":
                    raise Rejected("Completion requires STARTED; duplicate refused")
                kwargs["evidence"] = host.completion_report(binding, args.event_id, args.test_evidence or [])
            elif args.command == "start":
                if not args.evidence:
                    raise Rejected("Worker start evidence required")
                kwargs["evidence"] = args.evidence
            result = call(args.command, **kwargs)
    if isinstance(result, dict):
        result = {k: v for k, v in result.items() if "token" not in k}
    print(json.dumps(dict(result=result, stage=SCOPE, actor=actor,
                         platform_identity="NOT_PROVEN", merge_authorized=False,
                         deploy_authorized=False, transport_executed=False)))


if __name__ == "__main__":
    main()
