"""Bounded operator CLI. It accepts only a host-root configuration."""
import argparse
import hashlib
import json
import time
import time
from pathlib import Path
import sys

_PACKAGES = Path(__file__).resolve().parents[1]
for _package in (_PACKAGES / "communication-ledger", _PACKAGES / "cairn-adapter"):
    if str(_package) not in sys.path:
        sys.path.insert(0, str(_package))


def host_file(root, path):
    if ".." in Path(path).parts:
        raise ValueError("Host configuration traversal refused")
    root, path = Path(root).absolute(), Path(path).absolute()
    for current in (path, *path.parents):
        if current.is_symlink() or current.is_junction():
            raise ValueError("Linked host configuration refused")
    if not path.is_relative_to(root):
        raise ValueError("Host configuration escapes approved root")
    return path


def load_config(root, config):
    path = host_file(root, config)
    value = json.loads(path.read_text(encoding="utf-8"))
    if set(value) != {"executable", "arguments", "authority_key_file", "stream_journal",
                      "command_journal", "receipt_journal", "payload_file",
                      "work_payload_file", "confirmation_wait_seconds",
                      "uat_root", "confirmation_dir"}:
        raise ValueError("Invalid fixed host configuration")
    if not isinstance(value["executable"], str) or not isinstance(value["arguments"], list):
        raise ValueError("Invalid fixed host configuration")
    value["authority_key_file"] = str(host_file(root, root / value["authority_key_file"]))
    value["stream_journal"] = str(host_file(root, root / value["stream_journal"]))
    value["command_journal"] = str(host_file(root, root / value["command_journal"]))
    value["receipt_journal"] = str(host_file(root, root / value["receipt_journal"]))
    value["payload_file"] = str(host_file(root, root / value["payload_file"]))
    value["work_payload_file"] = str(host_file(root, root / value["work_payload_file"]))
    value["uat_root"] = str(host_file(root, root / value["uat_root"]))
    value["confirmation_dir"] = str(host_file(root, root / value["confirmation_dir"]))
    value["_host_root"] = str(Path(root).absolute())
    if not isinstance(value["confirmation_wait_seconds"], int) or value["confirmation_wait_seconds"] <= 0:
        raise ValueError("Invalid confirmation wait")
    return value


def fixed_transport(config, *, popen=None):
    """Construct only the host-configured one-process stdio transport."""
    from appserver_stdio_transport import AppServerStdioTransport
    from uuid import uuid4
    kwargs = {} if popen is None else {"popen": popen}
    # Each CLI process owns a new exclusive journal; a later work phase must
    # neither overwrite the ACK stream nor fail because that stream exists.
    base = Path(config["stream_journal"])
    journal = base.with_name(base.stem + "." + uuid4().hex + base.suffix)
    return AppServerStdioTransport(config["executable"], config["arguments"],
                                   journal, **kwargs)


def _immutable_evidence(path, value):
    """Persist host-observed evidence once, returning its content digest."""
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    digest = hashlib.sha256(encoded).hexdigest()
    path.mkdir(parents=True, exist_ok=True)
    artifact = path / (digest + ".json")
    if artifact.exists() and artifact.read_bytes() != encoded:
        raise ValueError("Observed evidence artifact mutation")
    if not artifact.exists():
        artifact.write_bytes(encoded)
    return digest


def host_flat_receipt(config, command, turn_id, response, output, sequence):
    """Bind raw model readback to host-observed transport identity.

    This creates evidence only.  It cannot create an operator confirmation or
    invoke the importer, so observation remains distinct from authorization.
    """
    if not isinstance(output, dict):
        raise ValueError("Model readback must be an object")
    action = output.get("action")
    stage = {"ACK_REQUEST": "ack", "START_REQUEST": "start",
             "COMPLETION_REQUEST": "complete"}.get(action)
    if stage is None:
        raise ValueError("Unknown model readback action")
    evidence = Path(config["command_journal"]).parent / "evidence"
    stream_digest = _immutable_evidence(evidence, dict(
        observer="APP_SERVER_LIVE_STREAM", thread_id=command["thread_id"],
        turn_id=turn_id, sequence=sequence, output=output))
    transport_digest = _immutable_evidence(evidence, dict(
        method="turn/start", accepted=True, thread_id=command["thread_id"],
        turn_id=turn_id, response=response))
    receipt = dict(event_id=command["event_id"], dedupe=command["dedupe"],
                   checkpoint=command["checkpoint"], thread_id=command["thread_id"],
                   turn_id=turn_id, action=action, readback=output,
                   transport_ref="artifact://sha256/" + transport_digest,
                   stream_ref="artifact://sha256/" + stream_digest)
    if stage == "complete":
        output_digest = _immutable_evidence(Path(config["uat_root"]) / "evidence",
                                            dict(raw_model_output=output))
        output_path = Path(config["uat_root"]) / "evidence" / (output_digest + ".json")
        receipt.update(output_path=str(output_path), output_sha256=output_digest,
                       output_ref="artifact://sha256/" + output_digest)
    return receipt


def validate_bound_command(command_file, command, command_digest, config):
    """Re-read and authorize the immutable command immediately before a send."""
    from runnable_operator_path import CommandFileSource
    from integrated_operator import CommandAuthority, AuthorityRejected
    current, current_digest = CommandFileSource(command_file).read()
    if current != command or current_digest != command_digest:
        raise AuthorityRejected("Command changed after session binding")
    CommandAuthority(config["_host_root"], Path(config["authority_key_file"]).read_bytes()).validate(
        current, current_digest)


def dispatch_on_transport(command_file, command, command_digest, config, payload, transport, phase):
    """Reserve one durable phase and persist only its direct stream observations."""
    from runnable_operator_path import DurableCommandJournal, dispatch_once
    from observed_receipts import ReceiptJournal, receipt_from_agent_output
    from appserver_observation_parser import (ObservationTerminalError,
                                               final_agent_message, parse_completed,
                                               terminal_turn)
    # This is deliberately adjacent to reserve/send: a session may wait for a
    # separate confirmation between phases, so its initial authority check is
    # insufficient for the later external effect.
    validate_bound_command(command_file, command, command_digest, config)
    journal = DurableCommandJournal(config["command_journal"])
    phase_command = journal.phase_command(command, phase)
    response = dispatch_once(journal, phase_command, command_digest, transport.turn_start, payload)
    turn_id = response["turn"]["id"]
    terminal = next((terminal_turn(message, thread_id=command["thread_id"], turn_id=turn_id)
                     for message in reversed(transport.observer.received)
                     if terminal_turn(message, thread_id=command["thread_id"], turn_id=turn_id)),
                    None)
    if terminal is None:
        message = transport.observer.wait_for(
            lambda value: terminal_turn(value, thread_id=command["thread_id"], turn_id=turn_id)
            is not None, timeout_seconds=90)
        terminal = terminal_turn(message, thread_id=command["thread_id"], turn_id=turn_id)
    if terminal.get("status") != "completed" or terminal.get("error") is not None:
        raise ObservationTerminalError("App Server turn terminated without a completed result")
    item = final_agent_message(transport.observer.received,
                               thread_id=command["thread_id"], turn_id=turn_id)
    outputs = parse_completed(item, thread_id=command["thread_id"], turn_id=turn_id)
    receipts = [receipt_from_agent_output(
                    command, command_digest, turn_id,
                    host_flat_receipt(config, command, turn_id, response, output, index + 1),
                    sequence=index + 1)
                for index, output in enumerate(outputs)]
    store = ReceiptJournal(config["receipt_journal"])
    for receipt in receipts:
        store.persist_receipt(receipt)
    return receipts


def run_command(command_file, config, payload, *, transport_factory=fixed_transport):
    """Reserve and dispatch the ACK phase with a short-lived CLI wrapper."""
    from runnable_operator_path import CommandFileSource
    from integrated_operator import CommandAuthority
    command, command_digest = CommandFileSource(command_file).read()
    CommandAuthority(config["_host_root"], Path(config["authority_key_file"]).read_bytes()).validate(command, command_digest)
    transport = transport_factory(config)
    try:
        transport.initialize_and_resume(command["thread_id"])
        return dispatch_on_transport(command_file, command, command_digest, config, payload, transport, "ack")
    finally:
        transport.close()


def resume_command(command_file, config):
    """Import only host-root confirmations for already persisted receipts."""
    from runnable_operator_path import CommandFileSource
    from observed_receipts import ReceiptJournal
    from receipt_bridge import resume_existing_importer
    from integrated_operator import CommandAuthority
    command, command_digest = CommandFileSource(command_file).read()
    CommandAuthority(config["_host_root"], Path(config["authority_key_file"]).read_bytes()).validate(
        command, command_digest)
    journal = ReceiptJournal(config["receipt_journal"])
    results = []
    for receipt in journal.pending(command["command_id"]):
        if receipt.get("command_digest") != command_digest:
            raise ValueError("Pending receipt does not bind current command digest")
        path = Path(config["confirmation_dir"]) / (receipt["receipt_digest"] + ".json")
        if not path.is_file():
            continue
        confirmation = json.loads(path.read_text(encoding="utf-8"))
        results.extend(resume_existing_importer(config["uat_root"], receipt, receipt["payload"],
                                                confirmation, receipt["stage"],
                                                receipt_journal=journal))
    return results


def run_session(command_file, config, ack_payload, work_payload, *, transport_factory=fixed_transport):
    """One transport process, with each later action gated by separate confirmation."""
    from runnable_operator_path import CommandFileSource
    from integrated_operator import CommandAuthority
    command, digest = CommandFileSource(command_file).read()
    CommandAuthority(config["_host_root"], Path(config["authority_key_file"]).read_bytes()).validate(command, digest)
    transport = transport_factory(config)
    deadline = time.monotonic() + config["confirmation_wait_seconds"]
    def wait_for(state):
        while time.monotonic() < deadline:
            results = resume_command(command_file, config)
            if any(item.get("state") == state for item in results):
                return
            time.sleep(0.05)
        raise TimeoutError("Separate operator confirmation not received")
    try:
        transport.initialize_and_resume(command["thread_id"])
        ack = dispatch_on_transport(command_file, command, digest, config, ack_payload, transport, "ack")
        wait_for("ACKED")
        work = dispatch_on_transport(command_file, command, digest, config, work_payload, transport, "work")
        wait_for("COMPLETED")
        return {"ack_receipts": ack, "work_receipts": work}
    finally:
        transport.close()


def resume_work(command_file, config, payload, *, transport_factory=fixed_transport):
    """Explicit post-ACK CLI phase; it never dispatches ACK again."""
    from runnable_operator_path import CommandFileSource
    from integrated_operator import CommandAuthority
    import existing_task_uat
    import sqlite3
    command, digest = CommandFileSource(command_file).read()
    CommandAuthority(config["_host_root"], Path(config["authority_key_file"]).read_bytes()).validate(command, digest)
    uat = existing_task_uat.Uat(config["uat_root"])
    with uat.store.transaction() as (db, ledger):
        if (command["event_id"] != uat.event or command["dedupe"] != uat.envelope["dedupe"]
                or command["checkpoint"] != uat.envelope["checkpoint"]
                or command["thread_id"] != uat.recipient or command["target"] != uat.recipient
                or command["scope"] != "local-pilot"
                or ledger._get(db, uat.event)["state"] != "ACKED"):
            raise ValueError("Work phase requires the exact ACKED UAT event")
        from cairn_adapter.store import get_config
        sent_at = get_config(db, "uat").get("sent_at")
        if not isinstance(sent_at, (int, float)) or time.time() > sent_at + 300:
            raise ValueError("Work phase UAT receipt has expired; reconcile only")
    with sqlite3.connect(config["receipt_journal"]) as db:
        ack = db.execute("select imported from receipts where json_extract(body,'$.command_id')=? and json_extract(body,'$.stage')='ack'",
                         (command["command_id"],)).fetchone()
    if ack != (1,):
        raise ValueError("Work phase requires consumed ACK receipt and confirmation")
    transport = transport_factory(config)
    try:
        transport.initialize_and_resume(command["thread_id"])
        return dispatch_on_transport(command_file, command, digest, config, payload, transport, "work")
    finally:
        transport.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run-command")
    run.add_argument("--host-root", required=True, type=Path)
    run.add_argument("--host-config", required=True, type=Path)
    run.add_argument("--command-file", required=True, type=Path)
    resume = sub.add_parser("resume-command")
    resume.add_argument("--host-root", required=True, type=Path)
    resume.add_argument("--host-config", required=True, type=Path)
    resume.add_argument("--command-file", required=True, type=Path)
    session = sub.add_parser("run-session")
    session.add_argument("--host-root", required=True, type=Path)
    session.add_argument("--host-config", required=True, type=Path)
    session.add_argument("--command-file", required=True, type=Path)
    work = sub.add_parser("resume-work")
    work.add_argument("--host-root", required=True, type=Path)
    work.add_argument("--host-config", required=True, type=Path)
    work.add_argument("--command-file", required=True, type=Path)
    args = parser.parse_args()
    config = load_config(args.host_root, args.host_config)
    # Deliberately do not expose the authority key or Store/Owner credentials.
    # Live receipt conversion and PM confirmation must be explicitly wired by
    # the approved operator harness before a future UAT can invoke transport.
    if args.command == "run-command":
        payload = json.loads(Path(config["payload_file"]).read_text(encoding="utf-8"))
        receipts = run_command(args.command_file, config, payload)
        print(json.dumps({"command": "run-command", "receipt_digests":
                          [receipt["receipt_digest"] for receipt in receipts]}))
    elif args.command == "resume-command":
        # Confirmation artifacts are read only from the host-owned root. The
        # CLI deliberately cannot accept a confirmation path from its caller.
        print(json.dumps({"command": "resume-command",
                          "results": resume_command(args.command_file, config)}))
    elif args.command == "run-session":
        ack = json.loads(Path(config["payload_file"]).read_text(encoding="utf-8"))
        work = json.loads(Path(config["work_payload_file"]).read_text(encoding="utf-8"))
        result = run_session(args.command_file, config, ack, work)
        print(json.dumps({"command": "run-session", "result": result}))
    else:
        payload = json.loads(Path(config["work_payload_file"]).read_text(encoding="utf-8"))
        receipts = resume_work(args.command_file, config, payload)
        print(json.dumps({"command": "resume-work", "receipt_digests":
                          [receipt["receipt_digest"] for receipt in receipts]}))


if __name__ == "__main__":
    main()
