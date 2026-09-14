"""Official MCP SDK 2.2.0, local stdio only. Never registers itself with Codex."""

import argparse
import inspect
from typing import Any

from mcp.server import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from .api import COMMANDS, execute
from .ledger import FIELDS, Ledger, LedgerError


def create_server(ledger):
    server = MCPServer(
        "Local communication ledger", version="0.1.0",
        instructions="Trusted local ledger only. Automatic Codex task wake is NOT_IMPLEMENTED. "
        "Preparing manual delivery sends nothing. SENT means transport acceptance, not worker ACK or STARTED. "
        "Use evidence references; never send secrets or raw production logs. Inspect before the one allowed retry. "
        "PM owns urgent STOP and priority overrides; ordinary Lead queues require no per-message PM approval. "
        "Expired worker leases require confirmation the worker stopped before another writer is admitted.",
    )

    @server.tool(structured_output=True)
    def ledger_read(view: str = "snapshot", event_id: str | None = None, target: str | None = None) -> dict[str, Any]:
        """Read snapshot, event, or append-only history. Does not run timeout recovery."""
        if view == "snapshot":
            return ledger.snapshot(target)
        if view == "event" and event_id:
            try:
                return ledger.get(event_id)
            except LedgerError as exc:
                raise ToolError(str(exc)) from exc
        if view == "history":
            return {"history": ledger.history(event_id)}
        raise ToolError("view must be snapshot, event (with event_id), or history")

    @server.tool(structured_output=True)
    def ledger_command(command: str, arguments: dict[str, Any]) -> dict[str, Any]:
        """Apply a local ledger command; use ledger_help for exact named arguments. Never wakes a Codex task."""
        try:
            return {"result": execute(ledger, command, arguments)}
        except (LedgerError, TypeError) as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(structured_output=True)
    def ledger_help() -> dict[str, Any]:
        """Return command signatures and limits. Actor identities are trusted local assertions."""
        from .transport import prepare_manual
        signatures = {}
        for name in COMMANDS:
            function = prepare_manual if name == "prepare_manual" else getattr(ledger, name)
            signatures[name] = str(inspect.signature(function))
        signatures["prepare_manual"] = "(event_id, delivery_token)"
        return {"commands": signatures, "enqueue_payload_fields": sorted(FIELDS), "automatic_wake": "NOT_IMPLEMENTED",
                "max_delivery_attempts": 2, "retry_inspection_required": True}

    return server


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    args = parser.parse_args()
    create_server(Ledger(args.db)).run(transport="stdio")


if __name__ == "__main__":
    main()
