"""Explicit transport seam. No external wake API is assumed or called."""

from typing import Protocol

from .ledger import LedgerError


class DeliveryAdapter(Protocol):
    def prepare(self, event: dict) -> dict: ...


class ManualCodexAdapter:
    def prepare(self, event: dict) -> dict:
        p = event["payload"]
        return {
            "adapter": "codex-manual",
            "automatic_wake": "NOT_IMPLEMENTED",
            "transport_accepted": False,
            "target_task": p["target_task"],
            "event_id": event["id"],
            "message": (
                f"Ledger event {event['id']} ({p['kind']}); dedupe {p['dedupe_key']}. "
                f"From {p['source_task']} to {p['target_task']}. Issue {p['issue']}; "
                f"checkpoint {p['checkpoint']}; base {p['base']}; head {p['head']}; scope {p['scope']}. "
                f"Next action: {p['next_action']}. Evidence: {p['evidence']}. "
                "Revalidate the current ledger binding before ACK. Transport receipt is not worker acceptance."
            ),
            "next_step": "Deliver through an explicitly authorized host channel, then record sent with its receipt. "
                         "The recipient separately records ack and start. Preparing this message sends nothing.",
        }


def prepare_manual(ledger, event_id, delivery_token):
    with ledger._tx() as db:
        row = ledger._delivery(db, event_id, delivery_token)
        if not ledger._available(db, row):
            raise LedgerError("Recipient became busy; do not deliver unrelated work")
        return ManualCodexAdapter().prepare(ledger._public(row))
