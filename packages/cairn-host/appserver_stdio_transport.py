"""Fixed one-process JSON-RPC stdio transport for the bounded host runner."""
import json
from pathlib import Path
import subprocess

from appserver_stream_observer import AppServerStreamObserver, SafeNotificationJournal


class AppServerStdioTransport:
    """Starts one configured executable; never shells, kills, or restarts it."""
    def __init__(self, executable, arguments, journal_path, *, popen=subprocess.Popen):
        if not isinstance(executable, str) or not executable or not isinstance(arguments, list):
            raise ValueError("Require configured executable and argument list")
        if not all(isinstance(item, str) for item in arguments):
            raise ValueError("Invalid App Server arguments")
        self.process = popen([executable, *arguments], stdin=subprocess.PIPE,
                             stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                             text=True, encoding="utf-8", bufsize=1, shell=False)
        if self.process.stdin is None or self.process.stdout is None:
            raise RuntimeError("App Server stdio unavailable")
        self.journal = SafeNotificationJournal(Path(journal_path))
        self.observer = AppServerStreamObserver(self.process.stdout, journal=self.journal)
        self.request_id = 0
        self.thread_id = None

    def request(self, method, params):
        self.request_id += 1
        request_id = self.request_id
        self.process.stdin.write(json.dumps({"id": request_id, "method": method,
                                             "params": params}, separators=(",", ":")) + "\n")
        self.process.stdin.flush()
        response = self.observer.wait_for(
            lambda item: item.get("id") == request_id and ("result" in item or "error" in item),
            timeout_seconds=90)
        if "error" in response:
            raise RuntimeError("App Server rejected request")
        return response["result"]

    def notify(self, method, params=None):
        """Emit a JSON-RPC notification required by the initialized session."""
        body = {"method": method}
        if params:
            body["params"] = params
        self.process.stdin.write(json.dumps(body, separators=(",", ":")) + "\n")
        self.process.stdin.flush()

    def turn_start(self, thread_id, payload):
        if self.thread_id != thread_id:
            raise RuntimeError("App Server thread was not initialized and resumed")
        return self.request("turn/start", {"threadId": thread_id, "input": payload})

    def initialize_and_resume(self, thread_id):
        if not isinstance(thread_id, str) or not thread_id:
            raise ValueError("Require target thread id")
        self.request("initialize", {"clientInfo": {"name": "cairn-host", "version": "1"}})
        # The installed protocol declares this as a client notification after
        # initialize; do not begin thread work until it has been emitted.
        self.notify("initialized")
        result = self.request("thread/resume", {"threadId": thread_id})
        bound = result.get("thread", {}).get("id") if isinstance(result, dict) else None
        if bound != thread_id:
            raise RuntimeError("App Server did not bind the requested thread")
        self.thread_id = thread_id

    def close(self):
        self.observer.close()
        if self.process.stdin and hasattr(self.process.stdin, "close"):
            self.process.stdin.close()
        if self.process.stdout and hasattr(self.process.stdout, "close"):
            self.process.stdout.close()
        try:
            if hasattr(self.process, "wait"):
                self.process.wait(timeout=1)
        except subprocess.TimeoutExpired:
            # Preserve an unknown live process for operator reconciliation.
            pass
