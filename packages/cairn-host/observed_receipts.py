"""Host observations and pilot operator confirmations are separate artifacts."""
import hashlib
import hmac
import json
import time
import sqlite3


class ReceiptRejected(ValueError):
    pass

class ReceiptJournal:
    """Host-owned durable receipt/confirmation consumption journal."""
    def __init__(self, path):
        self.path = str(path)
        db=sqlite3.connect(self.path)
        try:
            db.execute("create table if not exists receipts(digest text primary key, body text not null, confirmation text, imported integer not null default 0)")
            db.commit()
        finally: db.close()
    def persist_receipt(self, receipt):
        body=canonical(receipt).decode(); key=receipt["receipt_digest"]; db=sqlite3.connect(self.path)
        try:
            row=db.execute("select body from receipts where digest=?",(key,)).fetchone()
            if row and row[0] != body: raise ReceiptRejected("Persisted receipt mutation")
            if not row: db.execute("insert into receipts(digest,body) values(?,?)",(key,body)); db.commit()
        finally: db.close()
    def consume(self, receipt, confirmation):
        key=receipt["receipt_digest"]; encoded=canonical(confirmation).decode(); db=sqlite3.connect(self.path)
        try:
            row=db.execute("select body,confirmation,imported from receipts where digest=?",(key,)).fetchone()
            if not row or row[0] != canonical(receipt).decode(): raise ReceiptRejected("Receipt unavailable or mutated")
            if row[2]: raise ReceiptRejected("Receipt already imported")
            if row[1] and row[1] != encoded: raise ReceiptRejected("Confirmation mutation")
            db.execute("update receipts set confirmation=?,imported=1 where digest=?",(encoded,key)); db.commit()
        finally: db.close()
    def assert_unconsumed(self, receipt):
        db=sqlite3.connect(self.path)
        try:
            row=db.execute("select body,imported from receipts where digest=?",(receipt["receipt_digest"],)).fetchone()
            if not row or row[0] != canonical(receipt).decode() or row[1]:
                raise ReceiptRejected("Receipt unavailable, mutated, or already imported")
        finally: db.close()
    def pending(self, command_id):
        db=sqlite3.connect(self.path)
        try:
            rows=db.execute("select body from receipts where imported=0").fetchall()
            return [json.loads(row[0]) for row in rows
                    if json.loads(row[0]).get("command_id") == command_id]
        finally: db.close()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")


def digest(value):
    return hashlib.sha256(canonical(value)).hexdigest()


def observed_receipt(command, command_digest, stage, turn_id, payload, *, sequence, clock=time.time):
    """Create host observation only; this function has no ledger access."""
    if stage not in {"ack", "start", "complete"} or not isinstance(turn_id, str) or not turn_id:
        raise ReceiptRejected("Invalid observed stage or turn")
    receipt = dict(command_id=command["command_id"], command_digest=command_digest,
                   event_id=command["event_id"], thread_id=command["thread_id"],
                   turn_id=turn_id, stage=stage, payload=payload,
                   observer="APP_SERVER_LIVE_STREAM", sequence=sequence, observed_at=clock())
    receipt["receipt_digest"] = digest(receipt)
    return receipt


def receipt_from_agent_output(command, command_digest, turn_id, output, *, sequence, clock=time.time):
    """Convert one pinned parsed agent output object into an observation only."""
    if not isinstance(output, dict):
        raise ReceiptRejected("Agent output must be an object")
    action_to_stage = {"ACK_REQUEST": "ack", "START_REQUEST": "start",
                       "COMPLETION_REQUEST": "complete"}
    stage = action_to_stage.get(output.get("action"))
    if stage is None:
        raise ReceiptRejected("Unknown agent action")
    return observed_receipt(command, command_digest, stage, turn_id, output,
                            sequence=sequence, clock=clock)


def operator_confirmation(receipt, operator, key, *, clock=time.time):
    """A distinct pilot-operator authorization over one immutable receipt."""
    body = dict(receipt_digest=receipt["receipt_digest"], command_id=receipt["command_id"],
                event_id=receipt["event_id"], stage=receipt["stage"], operator=operator,
                confirmed_at=clock())
    body["signature"] = hmac.new(key, canonical(body), hashlib.sha256).hexdigest()
    return body


def validate_pair(receipt, confirmation, command, command_digest, key, expected_stage,
                  expected_thread, expected_turn=None):
    base = dict(receipt)
    received = base.pop("receipt_digest", None)
    if received != digest(base):
        raise ReceiptRejected("Receipt digest mismatch")
    if (receipt["command_id"] != command["command_id"] or receipt["command_digest"] != command_digest
            or receipt["event_id"] != command["event_id"] or receipt["thread_id"] != expected_thread
            or receipt["stage"] != expected_stage or receipt["observer"] != "APP_SERVER_LIVE_STREAM"):
        raise ReceiptRejected("Receipt binding mismatch")
    if expected_turn is not None and receipt["turn_id"] != expected_turn:
        raise ReceiptRejected("Receipt turn mismatch")
    signed = dict(confirmation)
    signature = signed.pop("signature", None)
    if (not isinstance(signature, str) or not hmac.compare_digest(
            signature, hmac.new(key, canonical(signed), hashlib.sha256).hexdigest())
            or signed.get("receipt_digest") != received or signed.get("command_id") != command["command_id"]
            or signed.get("event_id") != command["event_id"] or signed.get("stage") != expected_stage):
        raise ReceiptRejected("Confirmation binding mismatch")
    return receipt["payload"]
