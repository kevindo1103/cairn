"""Durable host-side command journal for the bounded operator runner."""
import hashlib
import json
from pathlib import Path
import sqlite3
import time


class CommandRejected(ValueError):
    pass


class CommandFileSource:
    """Read exactly one immutable command from a host-approved path."""
    def __init__(self, path):
        self.path = Path(path)

    def read(self):
        return read_command(self.path)


class DurableCommandJournal:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        db = sqlite3.connect(self.path)
        try:
            db.execute("""create table if not exists commands (
                command_id text primary key, digest text not null, event_id text not null,
                status text not null, turn_id text, sends integer not null default 0,
                completions integer not null default 0, updated real not null)""")
            db.commit()
        finally:
            db.close()

    def accept(self, command, digest):
        db = sqlite3.connect(self.path)
        try:
            row = db.execute("select digest,status from commands where command_id=?",
                             (command["command_id"],)).fetchone()
            if row:
                if row[0] != digest:
                    raise CommandRejected("Command id digest mismatch")
                return row[1]
            db.execute("insert into commands(command_id,digest,event_id,status,updated) values(?,?,?,?,?)",
                       (command["command_id"], digest, command["event_id"], "ACCEPTED", time.time()))
            db.commit()
            return "ACCEPTED"
        finally:
            db.close()

    def mark_sent(self, command_id, turn_id):
        db = sqlite3.connect(self.path)
        try:
            changed = db.execute("""update commands set status='SENT_AMBIGUOUS',turn_id=?,sends=sends+1,updated=?
                                  where command_id=? and status='ACCEPTED'""",
                                 (turn_id, time.time(), command_id)).rowcount
            if changed != 1:
                raise CommandRejected("Command cannot be sent again")
            db.commit()
        finally:
            db.close()

    def bind_turn(self, command_id, turn_id):
        """Record the transport turn after its request was already reserved."""
        if not isinstance(turn_id, str) or not turn_id:
            raise CommandRejected("Require a transport turn id")
        db = sqlite3.connect(self.path)
        try:
            changed = db.execute("""update commands set turn_id=?,updated=?
                                  where command_id=? and status='SENT_AMBIGUOUS'
                                  and turn_id='PENDING'""",
                                 (turn_id, time.time(), command_id)).rowcount
            if changed != 1:
                raise CommandRejected("Command turn cannot be rebound")
            db.commit()
        finally:
            db.close()

    def mark_completed(self, command_id):
        db = sqlite3.connect(self.path)
        try:
            changed = db.execute("""update commands set status='COMPLETED',completions=completions+1,updated=?
                                  where command_id=? and status='SENT_AMBIGUOUS'""",
                                 (time.time(), command_id)).rowcount
            if changed != 1:
                raise CommandRejected("Command cannot be completed")
            db.commit()
        finally:
            db.close()

    def state(self, command_id):
        db = sqlite3.connect(self.path)
        try:
            return db.execute("select status,sends,completions,turn_id from commands where command_id=?",
                              (command_id,)).fetchone()
        finally:
            db.close()

    def phase_command(self, command, phase):
        """Derive a host-only dispatch identity for a reviewed lifecycle phase."""
        if phase not in {"ack", "work"}:
            raise CommandRejected("Unknown dispatch phase")
        derived = dict(command)
        derived["command_id"] = command["command_id"] + ":" + phase
        return derived


def read_command(path):
    path = Path(path).absolute()
    for current in (path, *path.parents):
        if current.is_symlink() or getattr(current, "is_junction", lambda: False)():
            raise CommandRejected("Linked command path refused")
    raw = path.read_bytes()
    if len(raw) > 16384:
        raise CommandRejected("Command exceeds size limit")
    value = json.loads(raw)
    required = {"command_id", "event_id", "dedupe", "checkpoint", "thread_id", "action",
                "attestation_ref"}
    authority = required | {"project", "target", "scope", "principal", "generation"}
    accepted = isinstance(value, dict) and (set(value) == required or set(value) == authority)
    if not accepted or not all(
            isinstance(value[key], str) and value[key] for key in value):
        raise CommandRejected("Invalid immutable command")
    return value, hashlib.sha256(raw).hexdigest()


def dispatch_once(journal, command, digest, turn_start, payload):
    """Reserve durable non-replayability before the external transport call.

    The caller must attach a live AppServerStreamObserver before invoking this
    function. This module never manufactures an ACK, START, or COMPLETE.
    """
    status = journal.accept(command, digest)
    if status != "ACCEPTED":
        raise CommandRejected("Command was already accepted; reconcile before any resend")
    journal.mark_sent(command["command_id"], "PENDING")
    response = turn_start(command["thread_id"], payload)
    try:
        turn_id = response["turn"]["id"]
    except (KeyError, TypeError):
        raise CommandRejected("Transport response lacks a turn id") from None
    journal.bind_turn(command["command_id"], turn_id)
    return response
