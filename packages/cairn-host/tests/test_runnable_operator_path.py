import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from runnable_operator_path import CommandRejected, DurableCommandJournal, dispatch_once, read_command


class DurableCommandJournalTests(unittest.TestCase):
    def test_restart_replay_and_ambiguous_send_never_resends(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "command.json"
            command = dict(command_id="cmd-1", event_id="event", dedupe="dedupe",
                           checkpoint="checkpoint", thread_id="thread", action="send_work_once",
                           attestation_ref="artifact://sha256/evidence")
            path.write_text(json.dumps(command), encoding="utf-8")
            command, digest = read_command(path)
            journal = DurableCommandJournal(Path(temp) / "broker" / "commands.sqlite")
            self.assertEqual(journal.accept(command, digest), "ACCEPTED")
            journal.mark_sent("cmd-1", "turn-1")
            restarted = DurableCommandJournal(Path(temp) / "broker" / "commands.sqlite")
            self.assertEqual(restarted.accept(command, digest), "SENT_AMBIGUOUS")
            with self.assertRaises(CommandRejected):
                restarted.mark_sent("cmd-1", "turn-2")
            restarted.mark_completed("cmd-1")
            self.assertEqual(restarted.state("cmd-1"), ("COMPLETED", 1, 1, "turn-1"))

    def test_replay_with_changed_command_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = DurableCommandJournal(Path(temp) / "commands.sqlite")
            command = dict(command_id="cmd-1", event_id="event")
            journal.accept(command, "a")
            with self.assertRaises(CommandRejected):
                journal.accept(command, "b")

    def test_linked_command_file_is_refused(self):
        with tempfile.TemporaryDirectory() as temp:
            target = Path(temp) / "command.json"
            target.write_text("{}", encoding="utf-8")
            link = Path(temp) / "command-link.json"
            junction = None
            try:
                link.symlink_to(target)
                candidate = link
            except OSError:
                self.assertEqual(os.name, "nt", "No link-capable test path is available")
                target_dir = Path(temp) / "command-target"
                target_dir.mkdir()
                nested = target_dir / "command.json"
                nested.write_text("{}", encoding="utf-8")
                junction = Path(temp) / "command-junction"
                created = subprocess.run(
                    ["cmd.exe", "/d", "/c", "mklink", "/J", str(junction), str(target_dir)],
                    capture_output=True, text=True, timeout=10)
                self.assertEqual(created.returncode, 0,
                                 "Junction creation denied; no fallback or skip: " + created.stderr)
                candidate = junction / "command.json"
            with self.assertRaises(CommandRejected):
                read_command(candidate)
            if junction is not None:
                junction.rmdir()

    def test_reserves_before_transport_and_stops_on_crash_or_replay(self):
        with tempfile.TemporaryDirectory() as temp:
            journal = DurableCommandJournal(Path(temp) / "commands.sqlite")
            command = dict(command_id="cmd-1", event_id="event", dedupe="dedupe",
                           checkpoint="checkpoint", thread_id="thread", action="send_work_once",
                           attestation_ref="artifact://sha256/evidence")
            calls = []
            response = dispatch_once(
                journal, command, "digest",
                lambda thread, payload: calls.append((thread, payload)) or {"turn": {"id": "turn-1"}},
                {"request": "work"})
            self.assertEqual(response["turn"]["id"], "turn-1")
            self.assertEqual(calls, [("thread", {"request": "work"})])
            self.assertEqual(journal.state("cmd-1"), ("SENT_AMBIGUOUS", 1, 0, "turn-1"))
            with self.assertRaises(CommandRejected):
                dispatch_once(journal, command, "digest", lambda *_: self.fail("must not resend"), {})
    def test_ack_and_work_have_separate_durable_phase_identity(self):
        with tempfile.TemporaryDirectory() as temp:
            journal=DurableCommandJournal(Path(temp)/"j.sqlite")
            command={"command_id":"c","event_id":"e"}
            self.assertEqual(journal.phase_command(command,"ack")["command_id"],"c:ack")
            self.assertEqual(journal.phase_command(command,"work")["command_id"],"c:work")


if __name__ == "__main__":
    unittest.main()
