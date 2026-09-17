import sys
import json
from pathlib import Path
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver_operator_runner import CommandFileSource, ControlCommand, OneConnectionOperatorRunner, RunnerStopped


class FakeTransport:
    def __init__(self, outcomes=None):
        self.processes = 1
        self.calls = []
        self.outcomes = list(outcomes or [{"turn": {"id": "ack"}}, {"turn": {"id": "work"}}])

    def turn_start(self, recipient, payload):
        self.calls.append((recipient, payload))
        result = self.outcomes.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class OneConnectionOperatorRunnerTests(unittest.TestCase):
    def test_pm_wait_then_work_uses_one_connection_and_no_import(self):
        state = {"value": "SENT"}
        records = []
        transport = FakeTransport()
        runner = OneConnectionOperatorRunner(
            transport, event_id="event", recipient="thread",
            ledger_state=lambda: state["value"],
            record=lambda name, data: records.append((name, data)))
        runner.send_ack_once({"action": "ACK_REQUEST"})
        runner.await_pm()
        with self.assertRaises(RunnerStopped):
            runner.send_work_once(ControlCommand("work-1", "send_work_once", "event", "artifact://pm/ack"),
                                  {"action": "START_REQUEST"})
        self.assertEqual(len(transport.calls), 1)
        state["value"] = "ACKED"  # External PM import; runner never performs it.
        result = runner.send_work_once(
            ControlCommand("work-1", "send_work_once", "event", "artifact://pm/ack"),
            {"action": "START_REQUEST"})
        self.assertEqual(result["turn"]["id"], "work")
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.processes, 1)
        self.assertFalse(any(name.endswith("import") for name, _ in records))

    def test_duplicate_timeout_and_error_never_resend_or_start_second_process(self):
        records = []
        transport = FakeTransport(outcomes=[{"turn": {"id": "ack"}}, TimeoutError("stream timeout")])
        runner = OneConnectionOperatorRunner(
            transport, event_id="event", recipient="thread", ledger_state=lambda: "ACKED",
            record=lambda name, data: records.append((name, data)))
        runner.send_ack_once({"action": "ACK_REQUEST"})
        command = ControlCommand("work-1", "send_work_once", "event", "artifact://pm/ack")
        with self.assertRaises(TimeoutError):
            runner.send_work_once(command, {"action": "START_REQUEST"})
        self.assertEqual(runner.phase, "STOPPED")
        self.assertEqual(len(transport.calls), 2)
        with self.assertRaises(RunnerStopped):
            runner.send_work_once(command, {"action": "START_REQUEST"})
        self.assertEqual(len(transport.calls), 2)
        self.assertEqual(transport.processes, 1)
        self.assertIn("work_error", [name for name, _ in records])

    def test_host_owned_control_file_is_hash_recorded_and_single_use(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "pm-command.json"
            path.write_text(json.dumps({"command_id": "work-1", "action": "send_work_once",
                                        "event_id": "event", "attestation_ref": "artifact://pm/ack"}),
                            encoding="utf-8")
            records, transport = [], FakeTransport()
            runner = OneConnectionOperatorRunner(
                transport, event_id="event", recipient="thread", ledger_state=lambda: "ACKED",
                record=lambda name, data: records.append((name, data)))
            runner.send_ack_once({"action": "ACK_REQUEST"})
            runner.apply_control_file(CommandFileSource(path), {"action": "START_REQUEST"})
            with self.assertRaises(RunnerStopped):
                runner.apply_control_file(CommandFileSource(path), {"action": "START_REQUEST"})
            self.assertEqual(len(transport.calls), 2)
            self.assertIn("control_observed", [name for name, _ in records])


if __name__ == "__main__":
    unittest.main()
