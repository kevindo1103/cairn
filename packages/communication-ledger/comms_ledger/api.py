"""Explicit command allowlist shared by CLI and MCP."""

from .ledger import LedgerError
from .transport import prepare_manual


COMMANDS = (
    "checkpoint", "enqueue", "set_busy", "claim", "sent", "delivery_failed",
    "ack", "start", "renew", "complete", "terminate", "release_stopped_worker",
    "override_priority", "inspect_retry", "recover", "get", "snapshot", "history",
    "prepare_manual",
)


def execute(ledger, command, arguments):
    if command not in COMMANDS or not isinstance(arguments, dict):
        raise LedgerError("Unknown command or arguments are not an object")
    if command == "prepare_manual":
        return prepare_manual(ledger, **arguments)
    return getattr(ledger, command)(**arguments)
