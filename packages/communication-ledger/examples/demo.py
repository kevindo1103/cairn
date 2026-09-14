"""Synthetic handoff in a temporary database; no external communication."""

import json
import tempfile
from pathlib import Path

from comms_ledger import Ledger
from comms_ledger.transport import prepare_manual


def main():
    root = Path(__file__).resolve().parents[1]
    (root / "work").mkdir(exist_ok=True)
    with tempfile.TemporaryDirectory(dir=root / "work") as folder:
        ledger = Ledger(Path(folder) / "synthetic.sqlite", pm_task="pm")
        checkpoint = json.loads((root / "examples/checkpoint.json").read_text())
        ledger.checkpoint(**checkpoint)
        event = ledger.enqueue(json.loads((root / "examples/event.json").read_text())["payload"])
        event_id = event["id"]
        delivery = ledger.claim("worker-task", "manual-dispatcher")
        envelope = prepare_manual(ledger, event_id, delivery["delivery_token"])
        # Simulation only: this receipt does not claim delivery to a real Codex task.
        ledger.sent(event_id, delivery["delivery_token"], "synthetic://simulated-transport-receipt")
        acceptance = ledger.ack(event_id, "worker-task", "synthetic-worker", "synthetic://simulated-ack")
        token = acceptance["worker_token"]
        ledger.start(event_id, token, "synthetic://first-action")
        ledger.complete(event_id, token, "synthetic://result")
        restarted = Ledger(Path(folder) / "synthetic.sqlite")
        print(json.dumps({"synthetic_only": True, "automatic_wake": envelope["automatic_wake"],
                          "event_id": event_id, "state_after_reopen": restarted.get(event_id)["state"],
                          "history": [r["action"] for r in restarted.history(event_id)]}, indent=2))


if __name__ == "__main__":
    main()
