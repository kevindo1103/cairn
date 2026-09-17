import io
import json
import os
from pathlib import Path
import sys
import threading
import time
import unittest
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver_stream_observer import AppServerStreamObserver, ObservationTimeout, SafeNotificationJournal


class FailingJournal:
    def append(self, _notification):
        raise OSError("journal write failed")

    def close(self):
        pass


class AppServerStreamObserverTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.journal_index = 0

    def observer(self, stream):
        self.journal_index += 1
        return AppServerStreamObserver(
            stream, journal=SafeNotificationJournal(
                Path(self.temp.name) / (str(self.journal_index) + ".jsonl")))

    def pipe(self):
        read_fd, write_fd = os.pipe()
        return (os.fdopen(read_fd, "r", encoding="utf-8"),
                os.fdopen(write_fd, "w", encoding="utf-8"))

    def test_silent_open_stream_hits_deadline(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        started = time.monotonic()
        with self.assertRaises(ObservationTimeout):
            observer.wait_for(lambda _: True, timeout_seconds=0.05)
        self.assertLess(time.monotonic() - started, 0.5)
        self.assertEqual(observer.received, ())

    def test_old_direct_readline_is_not_deadline_aware(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        returned = threading.Event()
        thread = threading.Thread(target=lambda: (reader.readline(), returned.set()), daemon=True)
        thread.start()
        self.assertFalse(returned.wait(0.05))

    def test_partial_line_hits_deadline_without_persisting_message(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        writer.write('{"method":"turn/completed"')
        writer.flush()
        with self.assertRaises(ObservationTimeout):
            observer.wait_for(lambda _: True, timeout_seconds=0.05)
        self.assertEqual(observer.received, ())

    def test_eof_is_distinct_from_timeout(self):
        observer = self.observer(io.StringIO(""))
        self.addCleanup(observer.close)
        with self.assertRaises(EOFError):
            observer.wait_for(lambda _: True, timeout_seconds=0.5)

    def test_completed_notification_is_returned_and_persisted(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        completed = {"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}}
        writer.write(json.dumps(completed) + "\n")
        writer.flush()
        self.assertEqual(observer.wait_for(
            lambda message: message.get("method") == "turn/completed",
            timeout_seconds=0.5), completed)
        self.assertEqual(observer.received, (completed,))

    def test_received_notification_survives_later_interruption(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        started = {"method": "turn/started", "params": {"turn": {"id": "turn-1"}}}
        writer.write(json.dumps(started) + "\n")
        writer.flush()
        with self.assertRaises(ObservationTimeout):
            observer.wait_for(
                lambda message: message.get("method") == "turn/completed",
                timeout_seconds=0.05)
        self.assertEqual(observer.received, (started,))

    def test_journal_persists_safe_metadata_before_match(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        message = {"method": "turn/completed", "params": {"threadId": "thread-1",
            "turn": {"id": "turn-1", "status": "completed",
                     "items": [{"text": "must-not-journal"}]}}}
        writer.write(json.dumps(message) + "\n")
        writer.flush()
        observer.wait_for(lambda _: True, timeout_seconds=0.5)
        journal = Path(self.temp.name) / "1.jsonl"
        content = journal.read_text(encoding="utf-8")
        self.assertIn('"turn_id":"turn-1"', content)
        self.assertNotIn("must-not-journal", content)

    def test_journal_accepts_response_without_persisting_result(self):
        reader, writer = self.pipe()
        self.addCleanup(reader.close)
        self.addCleanup(writer.close)
        observer = self.observer(reader)
        self.addCleanup(observer.close)
        response = {"jsonrpc": "2.0", "id": 7, "result": {"secret": "must-not-journal"}}
        writer.write(json.dumps(response) + "\n")
        writer.flush()
        self.assertEqual(observer.wait_for(lambda value: value.get("id") == 7,
                                           timeout_seconds=0.5), response)
        observer.close()
        content = (Path(self.temp.name) / "1.jsonl").read_text(encoding="utf-8")
        self.assertIn('"request_id":7', content)
        self.assertNotIn("must-not-journal", content)

    def test_journal_write_failure_blocks_matching_notification(self):
        message = {"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}}
        observer = AppServerStreamObserver(
            io.StringIO(json.dumps(message) + "\n"), journal=FailingJournal())
        self.addCleanup(observer.close)
        with self.assertRaises(RuntimeError) as raised:
            observer.wait_for(lambda _: True, timeout_seconds=0.5)
        self.assertIsInstance(raised.exception.__cause__, OSError)
        self.assertEqual(observer.received, ())

    def test_bounded_queue_stops_before_unbounded_received_growth(self):
        stream = io.StringIO(
            json.dumps({"method": "turn/started", "params": {"turn": {"id": "one"}}}) + "\n" +
            json.dumps({"method": "turn/completed", "params": {"turn": {"id": "two"}}}) + "\n")
        observer = AppServerStreamObserver(
            stream, journal=SafeNotificationJournal(Path(self.temp.name) / "bounded.jsonl"),
            max_messages=1)
        self.addCleanup(observer.close)
        observer._start()
        time.sleep(0.05)
        with self.assertRaises(RuntimeError):
            observer.wait_for(lambda _: False, timeout_seconds=0.5)
        self.assertLessEqual(len(observer.received), 1)

    def test_closed_observer_cannot_reactivate(self):
        observer = self.observer(io.StringIO(""))
        observer.close()
        with self.assertRaises(RuntimeError):
            observer.wait_for(lambda _: True, timeout_seconds=0.5)


if __name__ == "__main__":
    unittest.main()
