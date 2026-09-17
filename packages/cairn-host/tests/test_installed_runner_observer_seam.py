"""Exercise the installed runner's exact req/until_turn AST without its top level."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import time
import types
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from appserver_stream_observer import ObservationTimeout


FIXTURES = Path(__file__).resolve().parent / "fixtures"
RUNNER = FIXTURES / "appserver-doc-correction-20260915.py"
RUNNER_SHA256 = "2279d674bd74ec218831630b2d83a55536af7172e57951015c789a1ed60e8ee8"
OBSERVER_PATH = FIXTURES / "observer-21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329.py"
OBSERVER_SHA256 = "21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329"
TASK3_RUNNER = FIXTURES / "appserver-incident-audit-20260915.py"
TASK3_RUNNER_SHA256 = "4a8d9bfd562d42c7d3883a1f3b342e32b57e67281a9dba0618c0cd399e35d0db"


class FakeInput:
    def __init__(self):
        self.data = []
        self.flushes = 0

    def write(self, value):
        self.data.append(value)

    def flush(self):
        self.flushes += 1


class FakeProcess:
    def __init__(self):
        self.stdin = FakeInput()
        self.terminated = False
        self.restarted = False
        self.imported = False

    def terminate(self):
        self.terminated = True


class ControlledObserver:
    def __init__(self, outcome):
        self.outcome = outcome
        self.received = ({"method": "item/received"},)
        self.calls = []

    def wait_for(self, predicate, *, timeout_seconds):
        self.calls.append(timeout_seconds)
        if isinstance(self.outcome, BaseException):
            raise self.outcome
        self.assert_predicate = predicate
        return self.outcome


def exact_runner_functions(process, observer):
    source = RUNNER.read_bytes()
    if hashlib.sha256(source).hexdigest() != RUNNER_SHA256:
        raise AssertionError("installed runner hash changed; fixture is not bound to reviewed source")
    module = ast.parse(source.decode("utf-8"), filename=str(RUNNER))
    nodes = [node for node in module.body if isinstance(node, ast.FunctionDef)
             and node.name in {"req", "until_turn"}]
    if [node.name for node in nodes] != ["req", "until_turn"]:
        raise AssertionError("installed runner seam functions changed")
    namespace = {"json": json, "time": time, "p": process, "observer": observer, "events": []}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(RUNNER), "exec"), namespace)
    return namespace


def exact_observer_loader(path=OBSERVER_PATH, expected_hash=OBSERVER_SHA256):
    source = RUNNER.read_bytes()
    if hashlib.sha256(source).hexdigest() != RUNNER_SHA256:
        raise AssertionError("installed runner hash changed; fixture is not bound to reviewed source")
    module = ast.parse(source.decode("utf-8"), filename=str(RUNNER))
    loader = next(node for node in module.body if isinstance(node, ast.FunctionDef)
                  and node.name == "load_observer")
    namespace = {"hashlib": hashlib, "os": os, "types": types,
                 "OBSERVER_PATH": path, "OBSERVER_SHA256": expected_hash}
    exec(compile(ast.Module(body=[loader], type_ignores=[]), str(RUNNER), "exec"),
         namespace)
    return namespace["load_observer"]()


def exact_task3_delivery(validate, send):
    source = TASK3_RUNNER.read_bytes()
    if hashlib.sha256(source).hexdigest() != TASK3_RUNNER_SHA256:
        raise AssertionError("task3 runner hash changed; fixture is not bound to reviewed source")
    module = ast.parse(source.decode("utf-8"), filename=str(TASK3_RUNNER))
    nodes = [node for node in module.body if isinstance(node, ast.FunctionDef)
             and node.name in {"prospective_sent", "start_delivery"}]
    if [node.name for node in nodes] != ["prospective_sent", "start_delivery"]:
        raise AssertionError("task3 pre-send seam changed")
    namespace = {"ROOT": Path("fixture-root"), "uat": types.SimpleNamespace(
        validate_observation=validate), "json": json, "request": send}
    exec(compile(ast.Module(body=nodes, type_ignores=[]), str(TASK3_RUNNER), "exec"),
         namespace)
    return namespace


class InstalledRunnerObserverSeamTests(unittest.TestCase):
    def test_task3_invalid_or_stale_preflight_never_calls_turn_start(self):
        for error in (ValueError("live origin"), ValueError("stale binding")):
            calls = []
            seam = exact_task3_delivery(
                lambda *_args: (_ for _ in ()).throw(error),
                lambda *args: calls.append(args))
            with self.assertRaisesRegex(ValueError, str(error)):
                seam["start_delivery"]({"event_id": "event"}, "recipient", {"ack": True})
            self.assertEqual(calls, [])

    def test_task3_valid_preflight_calls_exactly_one_mock_turn_start(self):
        validations, calls = [], []
        seam = exact_task3_delivery(
            lambda *args: validations.append(args),
            lambda *args: calls.append(args) or {"turn": {"id": "turn-1"}})
        response = seam["start_delivery"]({"event_id": "event"}, "recipient", {"ack": True})
        self.assertEqual(response["turn"]["id"], "turn-1")
        self.assertEqual(len(validations), 1)
        self.assertEqual(validations[0][1], "sent")
        self.assertEqual(validations[0][2]["origin"]["evidence_ref"],
                         "artifact://fixture/prospective-sent")
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0][1], "turn/start")

    def test_protected_observer_import_uses_exact_runner_loader(self):
        observer, journal = exact_observer_loader()
        self.assertEqual(observer.__module__, "cairn_protected_observer")
        self.assertEqual(journal.__module__, "cairn_protected_observer")

    def test_loader_refuses_missing_or_hash_mismatched_artifact(self):
        with self.assertRaises(FileNotFoundError):
            exact_observer_loader(Path(self._testMethodName), OBSERVER_SHA256)
        with self.assertRaisesRegex(RuntimeError, "hash mismatch"):
            exact_observer_loader(OBSERVER_PATH, "0" * 64)

    def test_req_completed_writes_once_and_returns_response_result(self):
        process = FakeProcess()
        observer = ControlledObserver({"id": 3, "result": {"turn": "ready"}})
        runner = exact_runner_functions(process, observer)
        self.assertEqual(runner["req"](3, "turn/start", {"threadId": "t-1"}), {"turn": "ready"})
        self.assertEqual(observer.calls, [90])
        self.assertEqual(len(process.stdin.data), 1)
        self.assertEqual(json.loads(process.stdin.data[0])["id"], 3)
        self.assertFalse(process.terminated)
        self.assertFalse(process.restarted)
        self.assertFalse(process.imported)

    def test_silent_partial_and_eof_are_preserved_without_process_control(self):
        for failure in (ObservationTimeout("silent"), ObservationTimeout("partial"), EOFError("eof")):
            process = FakeProcess()
            observer = ControlledObserver(failure)
            runner = exact_runner_functions(process, observer)
            with self.assertRaises(type(failure)):
                runner["req"](1, "initialize", {})
            self.assertEqual(len(process.stdin.data), 1)
            self.assertFalse(process.terminated)
            self.assertFalse(process.restarted)
            self.assertFalse(process.imported)

    def test_journal_failure_stops_req_before_result_or_import(self):
        process = FakeProcess()
        observer = ControlledObserver(RuntimeError("App Server stream read failed"))
        runner = exact_runner_functions(process, observer)
        with self.assertRaisesRegex(RuntimeError, "stream read failed"):
            runner["req"](1, "initialize", {})
        self.assertFalse(process.terminated)
        self.assertFalse(process.imported)

    def test_until_turn_matches_completed_turn_and_preserves_events(self):
        completed = {"method": "turn/completed", "params": {"turn": {"id": "turn-1"}}}
        process = FakeProcess()
        observer = ControlledObserver(completed)
        runner = exact_runner_functions(process, observer)
        self.assertEqual(runner["until_turn"]("turn-1"), completed)
        self.assertEqual(observer.calls, [90])
        self.assertEqual(runner["events"], list(observer.received))
        self.assertTrue(observer.assert_predicate(completed))
        self.assertFalse(observer.assert_predicate(
            {"method": "turn/completed", "params": {"turn": {"id": "other"}}}))
        self.assertFalse(process.terminated)

    def test_finally_cleanup_is_static_only_and_guarded(self):
        module = ast.parse(RUNNER.read_text(encoding="utf-8"), filename=str(RUNNER))
        finalizer = next(node for node in module.body if isinstance(node, ast.Try)).finalbody
        self.assertEqual(ast.unparse(finalizer[0].value), "observer.close()")
        self.assertEqual(ast.unparse(finalizer[1].test), "OPERATOR_CLEANUP")


if __name__ == "__main__":
    unittest.main()
