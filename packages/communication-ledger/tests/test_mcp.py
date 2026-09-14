"""Real SDK stdio subprocess integration. Run with the optional MCP environment."""

import asyncio
import importlib.util
import tempfile
import unittest
from pathlib import Path
import sys

from comms_ledger import Ledger
from tests.test_ledger import ROOT, payload


@unittest.skipUnless(importlib.util.find_spec("mcp"), "Optional MCP SDK not installed")
class MCPTests(unittest.TestCase):
    def test_stdio_handoff_error_and_restart(self):
        from mcp import Client
        from mcp.client.stdio import StdioServerParameters

        async def scenario(db_path):
            params = StdioServerParameters(command=sys.executable,
                                           args=["-m", "comms_ledger.server", "--db", str(db_path)], cwd=ROOT)
            async with Client(params, read_timeout_seconds=15) as client:
                listing = await client.list_tools()
                self.assertEqual({t.name for t in listing.tools}, {"ledger_read", "ledger_command", "ledger_help"})
                self.assertIn("NOT_IMPLEMENTED", client.instructions)

                async def command(name, arguments):
                    result = await client.call_tool("ledger_command", {"command": name, "arguments": arguments})
                    self.assertFalse(result.is_error, result.content)
                    return result.structured_content["result"]

                await command("checkpoint", dict(actor="lead", issue="synthetic-issue", scope="synthetic-scope",
                              checkpoint="cp-1", base="base-1", head="head-1", expected_revision=0, evidence="synthetic://cp"))
                event = await command("enqueue", {"payload": payload()})
                event_id = event["id"]
                claim = await command("claim", {"target": "worker-task", "dispatcher": "dispatcher"})
                envelope = await command("prepare_manual", {"event_id": event_id, "delivery_token": claim["delivery_token"]})
                self.assertFalse(envelope["transport_accepted"])
                await command("sent", {"event_id": event_id, "delivery_token": claim["delivery_token"], "receipt": "synthetic://sent"})
                ack = await command("ack", dict(event_id=event_id, target="worker-task", worker="worker-1", evidence="synthetic://ack"))
                token = ack["worker_token"]
                await command("start", dict(event_id=event_id, worker_token=token, evidence="synthetic://start"))
                done = await command("complete", dict(event_id=event_id, worker_token=token, evidence="synthetic://done"))
                self.assertEqual(done["state"], "COMPLETED")
                denied = await client.call_tool("ledger_command", {"command": "_connect", "arguments": {}})
                self.assertTrue(denied.is_error)

            # A newly launched server sees the committed history after the first exits.
            async with Client(params, read_timeout_seconds=15) as restarted:
                result = await restarted.call_tool("ledger_read", {"view": "event", "event_id": event_id})
                self.assertFalse(result.is_error)
                self.assertEqual(result.structured_content["state"], "COMPLETED")
                history = await restarted.call_tool("ledger_read", {"view": "history", "event_id": event_id})
                self.assertGreaterEqual(len(history.structured_content["history"]), 7)

        (ROOT / "work").mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=ROOT / "work") as folder:
            path = Path(folder) / "mcp-synthetic.sqlite"
            Ledger(path, pm_task="pm")
            asyncio.run(asyncio.wait_for(scenario(path), timeout=50))
