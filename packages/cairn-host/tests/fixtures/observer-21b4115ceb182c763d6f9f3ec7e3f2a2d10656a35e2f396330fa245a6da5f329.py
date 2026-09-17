"""Bounded JSON-RPC stream observation for the Cairn host.

The observer never starts, terminates, restarts, or otherwise controls an App
Server process. Its caller owns process lifecycle. Complete notifications are
persisted before matching so an observation timeout cannot erase received
evidence.
"""
import json
import os
from pathlib import Path
from queue import Empty, Full, Queue
import threading
import time


class ObservationTimeout(TimeoutError):
    """No matching notification arrived before the observer deadline."""


class SafeNotificationJournal:
    """Append-only owner-controlled journal that excludes raw item content."""
    def __init__(self, path, *, max_bytes=65536):
        self.path = Path(path)
        self.max_bytes = max_bytes
        self._bytes = 0
        self._stream = self.path.open("x", encoding="utf-8")

    def append(self, notification):
        encoded = (json.dumps(notification, separators=(",", ":")) + "\n").encode("utf-8")
        if self._bytes + len(encoded) > self.max_bytes:
            raise OSError("Safe notification journal limit exceeded")
        self._stream.write(encoded.decode("utf-8"))
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._bytes += len(encoded)

    def close(self):
        self._stream.close()


def safe_notification(message):
    """Keep response/notification lifecycle metadata; never journal payloads."""
    if not isinstance(message, dict):
        raise ValueError("App Server stream message is invalid")
    if isinstance(message.get("id"), (str, int)) and (
            "result" in message or "error" in message):
        return dict(kind="response", request_id=message["id"],
                    has_error="error" in message)
    if not isinstance(message.get("method"), str):
        raise ValueError("App Server stream message is invalid")
    params = message.get("params") if isinstance(message.get("params"), dict) else {}
    turn = params.get("turn") if isinstance(params.get("turn"), dict) else {}
    return dict(kind="notification", method=message["method"],
                thread_id=params.get("threadId") if isinstance(params.get("threadId"), str) else None,
                turn_id=params.get("turnId") if isinstance(params.get("turnId"), str) else turn.get("id"),
                turn_status=turn.get("status") if isinstance(turn.get("status"), str) else None)


class AppServerStreamObserver:
    def __init__(self, stream, *, journal, clock=time.monotonic, max_messages=256):
        if max_messages <= 0:
            raise ValueError("max_messages must be positive")
        self._stream = stream
        self._journal = journal
        self._clock = clock
        self._received = []
        self._queue = Queue(maxsize=max_messages)
        self._started = False
        self._closed = False
        self._failure = None

    @property
    def received(self):
        return tuple(self._received)

    def _run(self):
        try:
            for line in self._stream:
                if not line:
                    break
                message = json.loads(line)
                self._journal.append(safe_notification(message))
                self._queue.put_nowait(("message", message))
                self._received.append(message)
        except Full as error:
            self._failure = OSError("App Server notification queue limit exceeded")
        except (OSError, ValueError, json.JSONDecodeError) as error:
            self._failure = error
        finally:
            try:
                self._queue.put_nowait(("error", self._failure) if self._failure else ("eof", None))
            except Full:
                pass

    def _start(self):
        if self._started:
            return
        self._started = True
        self._reader = threading.Thread(target=self._run, daemon=True)
        self._reader.start()

    def wait_for(self, predicate, *, timeout_seconds):
        """Return the first persisted message matching predicate within deadline."""
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        if self._closed:
            raise RuntimeError("Observer is closed")
        self._start()
        deadline = self._clock() + timeout_seconds
        while True:
            if self._failure:
                raise RuntimeError("App Server stream read failed") from self._failure
            remaining = deadline - self._clock()
            if remaining <= 0:
                raise ObservationTimeout("No matching App Server notification before deadline")
            try:
                kind, value = self._queue.get(timeout=remaining)
            except Empty as error:
                raise ObservationTimeout(
                    "No matching App Server notification before deadline") from error
            if kind == "message" and predicate(value):
                return value
            if kind == "error":
                raise RuntimeError("App Server stream read failed") from value
            if kind == "eof":
                raise EOFError("App Server stream ended before matching notification")

    def close(self):
        """Make observation terminal without controlling caller-owned stream/process."""
        if self._closed:
            return
        self._closed = True
        self._journal.close()
