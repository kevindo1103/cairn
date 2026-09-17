"""The bounded offline/live operator path; transport and observer are injected.

The same run() path is used with an App Server stdio transport in a future
approved UAT and with deterministic fakes in regression tests.
"""
import hashlib
import hmac
import json
from pathlib import Path

from runnable_operator_path import CommandRejected, CommandFileSource, dispatch_once
from observed_receipts import ReceiptJournal, validate_pair


class AuthorityRejected(CommandRejected):
    pass


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


class CommandAuthority:
    """Host-owned immutable allow-list; it is never supplied by the client."""
    required = {"command_id", "event_id", "dedupe", "checkpoint", "thread_id", "action",
                "project", "target", "scope", "principal", "generation", "attestation_ref"}

    def __init__(self, approved_root, key):
        self.root = Path(approved_root).absolute()
        self.key = bytes(key)

    def validate(self, command, digest):
        if set(command) != self.required:
            raise AuthorityRejected("Unexpected command authority field")
        binding = self.root / "authority" / (command["command_id"] + ".json")
        if not binding.is_file() or binding.is_symlink() or binding.is_junction():
            raise AuthorityRejected("Host authority binding unavailable")
        record = json.loads(binding.read_text(encoding="utf-8"))
        signature = record.pop("signature", None)
        if not isinstance(signature, str) or not hmac.compare_digest(
                signature, hmac.new(self.key, _canonical(record), hashlib.sha256).hexdigest()):
            raise AuthorityRejected("Authority signature mismatch")
        if record != {"digest": digest, "command": command}:
            raise AuthorityRejected("Command does not match host authority")


class EvidenceAuthority:
    """Checks host-issued artifact binding; it does not attest platform provenance."""
    def __init__(self, key):
        self.key = bytes(key)

    def validate(self, evidence, command, stage, previous_turn):
        required = {"command_id", "digest", "event_id", "thread_id", "turn_id",
                    "stage", "observer", "observation", "signature"}
        if not isinstance(evidence, dict) or set(evidence) != required:
            raise AuthorityRejected("Malformed evidence")
        signature = evidence.pop("signature")
        try:
            valid = hmac.compare_digest(signature, hmac.new(
                self.key, _canonical(evidence), hashlib.sha256).hexdigest())
        finally:
            evidence["signature"] = signature
        if not valid:
            raise AuthorityRejected("Evidence signature mismatch")
        if (evidence["command_id"] != command["command_id"]
                or evidence["digest"] != hashlib.sha256(_canonical(command)).hexdigest()
                or evidence["event_id"] != command["event_id"]
                or evidence["thread_id"] != command["thread_id"]
                or evidence["stage"] != stage
                or evidence["observer"] != "APP_SERVER_LIVE_STREAM"
                or not isinstance(evidence["turn_id"], str) or not evidence["turn_id"]):
            raise AuthorityRejected("Evidence binding mismatch")
        if stage == "start" and evidence["turn_id"] == previous_turn:
            raise AuthorityRejected("START must be a distinct turn")
        if stage == "complete" and evidence["turn_id"] != previous_turn:
            raise AuthorityRejected("COMPLETE must bind START turn")
        return evidence["observation"]


class IntegratedOperator:
    """One command, one reserved external send, sequential adapter-backed imports."""
    stages = ("ack", "start", "complete")

    def __init__(self, journal, command_authority, evidence_authority, transport, observer, importer):
        self.journal, self.command_authority = journal, command_authority
        self.evidence_authority, self.transport = evidence_authority, transport
        self.observer, self.importer = observer, importer

    def run(self, command_file, payload):
        command, file_digest = CommandFileSource(command_file).read()
        self.command_authority.validate(command, file_digest)
        response = dispatch_once(self.journal, command, file_digest, self.transport.turn_start, payload)
        prior_turn = None
        for stage in self.stages:
            evidence = self.observer.next_evidence(stage, response["turn"]["id"])
            observation = self.evidence_authority.validate(evidence, command, stage, prior_turn)
            self.importer(stage, observation)  # Must call the existing adapter/store importer.
            prior_turn = evidence["turn_id"]
        self.journal.mark_completed(command["command_id"])
        return {"command_id": command["command_id"], "state": "COMPLETED",
                "turn_id": response["turn"]["id"]}


class StagedOperator:
    """Receipt persistence is separate from operator-confirmed import."""
    stages = ("ack", "start", "complete")
    def __init__(self, receipts, confirmation_key, importer):
        self.receipts, self.key, self.importer = receipts, confirmation_key, importer
    def observe(self, receipt):
        self.receipts.persist_receipt(receipt)
        return receipt["receipt_digest"]
    def confirm(self, receipt, confirmation, command, command_digest, expected_stage, previous_turn=None):
        payload = validate_pair(receipt, confirmation, command, command_digest, self.key,
                                expected_stage, command["thread_id"], previous_turn)
        self.receipts.consume(receipt, confirmation)
        return self.importer(expected_stage, payload)
