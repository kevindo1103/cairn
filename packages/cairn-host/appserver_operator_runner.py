"""One-connection, PM-controlled App Server pilot runner.

The runner deliberately separates transport from ledger import.  Its caller
keeps the one App Server connection alive while an operator performs the
stage-specific import.  No control command can resend an already-dispatched
turn.
"""
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


class RunnerStopped(RuntimeError):
    pass


@dataclass(frozen=True)
class ControlCommand:
    command_id: str
    action: str
    event_id: str
    attestation_ref: str


class CommandFileSource:
    """Read one host-owned command file without deleting or rewriting it."""
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        if self.path.is_symlink() or self.path.is_junction():
            raise RunnerStopped("Linked control file refused")
        raw = self.path.read_bytes()
        if len(raw) > 16384:
            raise RunnerStopped("Control file exceeds size limit")
        value = json.loads(raw)
        if not isinstance(value, dict) or set(value) != {
                "command_id", "action", "event_id", "attestation_ref"}:
            raise RunnerStopped("Invalid stage-control command")
        if not all(isinstance(value[key], str) and value[key] for key in value):
            raise RunnerStopped("Invalid stage-control command")
        command = ControlCommand(**value)
        return command, hashlib.sha256(raw).hexdigest()


class OneConnectionOperatorRunner:
    def __init__(self, transport, *, event_id, recipient, ledger_state, record):
        self.transport = transport
        self.event_id = event_id
        self.recipient = recipient
        self.ledger_state = ledger_state
        self.record = record
        self.phase = "NEW"
        self._commands = set()
        self._work_turn = None

    def send_ack_once(self, payload):
        if self.phase != "NEW":
            raise RunnerStopped("ACK delivery was already attempted")
        try:
            response = self.transport.turn_start(self.recipient, payload)
        except Exception as error:
            self.phase = "STOPPED"
            self.record("ack_error", {"error": type(error).__name__})
            raise
        self.phase = "AWAITING_PM_ACK"
        self.record("ack_delivery", {"turn_id": response["turn"]["id"]})
        return response

    def await_pm(self):
        if self.phase not in {"AWAITING_PM_ACK", "AWAITING_PM_WORK"}:
            raise RunnerStopped("Runner is not awaiting PM")
        self.record("await_pm", {"phase": self.phase})

    def send_work_once(self, command, payload):
        if not isinstance(command, ControlCommand) or command.action != "send_work_once":
            raise RunnerStopped("Require a stage-specific send_work_once command")
        if command.event_id != self.event_id or not command.attestation_ref:
            raise RunnerStopped("Command is not bound to the current event attestation")
        if self.phase != "AWAITING_PM_ACK" or self.ledger_state() != "ACKED":
            raise RunnerStopped("Ledger is not PM-confirmed ACKED")
        if command.command_id in self._commands or self._work_turn is not None:
            raise RunnerStopped("Duplicate work command refused")
        self._commands.add(command.command_id)
        self.record("work_command", {"command_id": command.command_id,
                                     "attestation_ref": command.attestation_ref})
        try:
            response = self.transport.turn_start(self.recipient, payload)
        except Exception as error:
            self.phase = "STOPPED"
            self.record("work_error", {"command_id": command.command_id,
                                       "error": type(error).__name__})
            raise
        self._work_turn = response["turn"]["id"]
        self.phase = "AWAITING_PM_WORK"
        self.record("work_delivery", {"turn_id": self._work_turn})
        return response

    def apply_control_file(self, source, payload):
        """Apply one PM-created command after recording its immutable digest."""
        if not isinstance(source, CommandFileSource):
            raise RunnerStopped("Require host-owned command source")
        command, digest = source.read()
        self.record("control_observed", {"command_id": command.command_id, "digest": digest})
        return self.send_work_once(command, payload)
