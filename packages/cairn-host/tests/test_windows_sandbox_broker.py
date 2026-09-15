import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(HERE))

from windows_sandbox_broker import Broker


class WindowsSandboxBrokerTests(unittest.TestCase):
    SID = "S-1-5-21-2199549977-3302132792-1898431476-1005"

    def request(self, broker, command, **arguments):
        return {
            "command": command,
            "event_id": broker.pilot.event,
            "arguments": arguments,
        }

    def test_bound_sid_can_recover_then_complete_and_is_revoked(self):
        with tempfile.TemporaryDirectory() as temp:
            broker = Broker(Path(temp) / "run", self.SID)
            self.assertTrue(broker.dispatch(self.SID, self.request(broker, "reconcile"))["ok"])
            ack = broker.dispatch(self.SID, self.request(broker, "ack"))
            self.assertTrue(ack["recovery"]["backup_restore_equal"])
            token = ack["worker_token"]
            self.assertTrue(broker.dispatch(
                self.SID, self.request(broker, "start", worker_token=token,
                                       evidence="synthetic://bound-start"))["ok"])
            self.assertTrue(broker.dispatch(
                self.SID, self.request(broker, "renew", worker_token=token))["ok"])
            completed = broker.dispatch(
                self.SID, self.request(broker, "complete", worker_token=token,
                                       evidence="synthetic://bound-complete"))
            self.assertTrue(completed["revoked"])
            with self.assertRaises((ValueError, RuntimeError)):
                broker.dispatch(self.SID, self.request(broker, "complete", worker_token=token,
                                                       evidence="synthetic://replay"))

    def test_wrong_sid_is_denied_before_adapter_mutation(self):
        with tempfile.TemporaryDirectory() as temp:
            broker = Broker(Path(temp) / "run", self.SID)
            before = broker.pilot.api["proof"](broker.pilot.store.path)
            with self.assertRaises(PermissionError):
                broker.dispatch("S-1-5-21-0-0-0-999", self.request(broker, "reconcile"))
            self.assertEqual(before, broker.pilot.api["proof"](broker.pilot.store.path))


if __name__ == "__main__":
    unittest.main()
