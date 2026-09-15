"""Windows named-pipe broker for the pinned Cairn Adapter TEST Store.

This is a bounded host integration for the elevated Codex sandbox. It never
starts Codex, creates a task, or activates a store. The owner starts it with a
fresh TEST root and an expected sandbox SID. Client-provided identity fields are
never accepted: the broker reads the named-pipe client process token.
"""
import argparse
import copy
import ctypes
from ctypes import wintypes
import json
from pathlib import Path
import secrets
import sys

from local_queue_pilot import FixtureVerifier, Pilot, PROJECT

if sys.platform != "win32":
    raise RuntimeError("windows_sandbox_broker requires Windows")

KERNEL32 = ctypes.WinDLL("kernel32", use_last_error=True)
ADVAPI32 = ctypes.WinDLL("advapi32", use_last_error=True)
INVALID_HANDLE_VALUE = wintypes.HANDLE(-1).value
PIPE_ACCESS_DUPLEX = 0x00000003
PIPE_TYPE_MESSAGE = 0x00000004
PIPE_READMODE_MESSAGE = 0x00000002
PIPE_WAIT = 0x00000000
ERROR_PIPE_CONNECTED = 535
TOKEN_QUERY = 0x0008
TOKEN_USER = 1
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
MAX_FRAME = 16 * 1024

class SECURITY_ATTRIBUTES(ctypes.Structure):
    _fields_ = [
        ("nLength", wintypes.DWORD),
        ("lpSecurityDescriptor", wintypes.LPVOID),
        ("bInheritHandle", wintypes.BOOL),
    ]

KERNEL32.CreateNamedPipeW.argtypes = (
    wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, wintypes.DWORD,
    wintypes.DWORD, wintypes.DWORD, wintypes.DWORD, wintypes.LPVOID,
)
KERNEL32.CreateNamedPipeW.restype = wintypes.HANDLE
KERNEL32.ConnectNamedPipe.argtypes = (wintypes.HANDLE, wintypes.LPVOID)
KERNEL32.ConnectNamedPipe.restype = wintypes.BOOL
KERNEL32.GetNamedPipeClientProcessId.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.ULONG))
KERNEL32.GetNamedPipeClientProcessId.restype = wintypes.BOOL
KERNEL32.OpenProcess.argtypes = (wintypes.DWORD, wintypes.BOOL, wintypes.DWORD)
KERNEL32.OpenProcess.restype = wintypes.HANDLE
KERNEL32.OpenProcessToken.argtypes = (wintypes.HANDLE, wintypes.DWORD, ctypes.POINTER(wintypes.HANDLE))
KERNEL32.OpenProcessToken.restype = wintypes.BOOL
ADVAPI32.GetTokenInformation.argtypes = (
    wintypes.HANDLE, wintypes.DWORD, wintypes.LPVOID, wintypes.DWORD,
    ctypes.POINTER(wintypes.DWORD),
)
ADVAPI32.GetTokenInformation.restype = wintypes.BOOL
ADVAPI32.ConvertSidToStringSidW.argtypes = (wintypes.LPVOID, ctypes.POINTER(wintypes.LPWSTR))
ADVAPI32.ConvertSidToStringSidW.restype = wintypes.BOOL
ADVAPI32.ConvertStringSecurityDescriptorToSecurityDescriptorW.argtypes = (
    wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(wintypes.LPVOID),
    ctypes.POINTER(wintypes.DWORD),
)
ADVAPI32.ConvertStringSecurityDescriptorToSecurityDescriptorW.restype = wintypes.BOOL
KERNEL32.LocalFree.argtypes = (wintypes.HLOCAL,)
KERNEL32.CloseHandle.argtypes = (wintypes.HANDLE,)
KERNEL32.ReadFile.argtypes = (wintypes.HANDLE, wintypes.LPVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
KERNEL32.WriteFile.argtypes = (wintypes.HANDLE, wintypes.LPCVOID, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), wintypes.LPVOID)
KERNEL32.DisconnectNamedPipe.argtypes = (wintypes.HANDLE,)


def checked(ok, label):
    if not ok:
        raise OSError(ctypes.get_last_error(), label)


def pipe_client_sid(handle):
    """Return the kernel-authenticated client SID for one connected pipe."""
    pid = wintypes.ULONG()
    checked(KERNEL32.GetNamedPipeClientProcessId(handle, ctypes.byref(pid)), "GetNamedPipeClientProcessId")
    process = KERNEL32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid.value)
    if not process:
        raise OSError(ctypes.get_last_error(), "OpenProcess")
    token = wintypes.HANDLE()
    try:
        checked(ADVAPI32.OpenProcessToken(process, TOKEN_QUERY, ctypes.byref(token)), "OpenProcessToken")
        required = wintypes.DWORD()
        ADVAPI32.GetTokenInformation(token, TOKEN_USER, None, 0, ctypes.byref(required))
        buffer = ctypes.create_string_buffer(required.value)
        checked(ADVAPI32.GetTokenInformation(token, TOKEN_USER, buffer, required.value, ctypes.byref(required)), "GetTokenInformation")
        sid = ctypes.cast(buffer, ctypes.POINTER(ctypes.c_void_p))[0]
        value = wintypes.LPWSTR()
        checked(ADVAPI32.ConvertSidToStringSidW(sid, ctypes.byref(value)), "ConvertSidToStringSidW")
        try:
            return value.value
        finally:
            KERNEL32.LocalFree(value)
    finally:
        if token:
            KERNEL32.CloseHandle(token)
        KERNEL32.CloseHandle(process)


def read_frame(handle):
    size = wintypes.DWORD()
    buffer = ctypes.create_string_buffer(MAX_FRAME + 1)
    checked(KERNEL32.ReadFile(handle, buffer, MAX_FRAME, ctypes.byref(size), None), "ReadFile")
    if not 0 < size.value <= MAX_FRAME:
        raise ValueError("Invalid pipe frame size")
    value = json.loads(buffer.raw[:size.value].decode("utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Pipe frame must be an object")
    return value


def write_frame(handle, value):
    encoded = (json.dumps(value, separators=(",", ":"), allow_nan=False) + "\n").encode("utf-8")
    if len(encoded) > MAX_FRAME:
        raise ValueError("Pipe response too large")
    written = wintypes.DWORD()
    checked(KERNEL32.WriteFile(handle, encoded, len(encoded), ctypes.byref(written), None), "WriteFile")
    if written.value != len(encoded):
        raise OSError("Partial pipe write")


def pipe_security_attributes(sid):
    """Allow only the exact sandbox SID to connect to this local pipe."""
    if not sid.upper().startswith("S-1-"):
        raise ValueError("Expected worker SID is not a SID")
    descriptor = wintypes.LPVOID()
    revision = wintypes.DWORD()
    checked(ADVAPI32.ConvertStringSecurityDescriptorToSecurityDescriptorW(
        "D:(A;;GRGW;;;" + sid + ")", 1, ctypes.byref(descriptor), ctypes.byref(revision)),
        "ConvertStringSecurityDescriptorToSecurityDescriptor")
    return SECURITY_ATTRIBUTES(ctypes.sizeof(SECURITY_ATTRIBUTES), descriptor, False), descriptor


class Broker:
    """Host-owned facade; the client never receives a Store, Owner or credential."""

    def __init__(self, root, expected_sid):
        self.pilot = Pilot(Path(root))
        self.expected_sid = expected_sid.upper()
        self.pilot.call("pm", "sent", event_id=self.pilot.event,
                        delivery_token=self.pilot.delivery,
                        receipt="synthetic://windows-elevated-pipe")
        self.worker_token = None
        self.recovery = None
        self.revoked = False

    def identity(self, sid):
        if sid.upper() != self.expected_sid:
            raise PermissionError("Named-pipe SID is not the bound worker")
        return self.pilot.mapping.copy()

    def dispatch(self, sid, request):
        self.identity(sid)
        if set(request) != {"command", "event_id", "arguments"} or request["event_id"] != self.pilot.event:
            raise ValueError("Unexpected request envelope")
        command, arguments = request["command"], request["arguments"]
        if command not in {"reconcile", "ack", "start", "renew", "complete"} or not isinstance(arguments, dict):
            raise ValueError("Command outside worker facade")
        result = self.pilot.call("worker", command, event_id=self.pilot.event, **arguments)
        if command == "ack":
            self.worker_token = result["worker_token"]
            self.recover_after_ack()
            return {"ok": True, "worker_token": self.worker_token, "recovery": self.recovery}
        if command == "complete":
            self.revoke_worker()
        return {"ok": True, "state": self.pilot.state(), "revoked": self.revoked}

    def recover_after_ack(self):
        """Continue only from a verified SQLite backup in this fresh TEST root."""
        saved_path = self.pilot.root / "evidence" / "backup.sqlite"
        before = self.pilot.api["proof"](self.pilot.store.path)
        saved = self.pilot.api["backup"](self.pilot.store.path, saved_path)
        restored = self.pilot.api["restore"](saved_path, self.pilot.root / "restored", saved, PROJECT)
        reopened = self.pilot.api["Store"](self.pilot.root / "restored", PROJECT)
        if before != saved or restored != saved or self.pilot.api["proof"](reopened.path) != saved:
            raise RuntimeError("SQLite backup/restore proof mismatch")
        self.pilot.store = reopened
        self.pilot.adapter = self.pilot.api["Adapter"](
            reopened, FixtureVerifier(), host_identity=self.pilot.identity)
        self.recovery = {"backup_restore_equal": True, "proof": saved}

    def revoke_worker(self):
        """Quiesce the TEST worker after completion; later worker calls must fail."""
        entries = copy.deepcopy(self.pilot.entries)
        worker = next(entry for entry in entries if entry["task_id"] == "worker")
        worker["state"] = "quiesced"
        worker["quiescence"] = {
            "evidence": "synthetic://windows-elevated-revoke",
            "active_mutations": 0,
            "unmapped_work": 0,
            "ownership_ambiguity": 0,
        }
        self.pilot.entries = entries
        self.pilot.revision = self.pilot.api["Owner"](self.pilot.store).replace(
            self.pilot.tokens["owner"], self.pilot.revision, entries)["revision"]
        self.revoked = True


def serve_once(root, expected_sid, pipe_name=None):
    """Serve one bound client session; caller must use a fresh protected TEST root."""
    pipe_name = pipe_name or "cairn-issue15-" + secrets.token_hex(12)
    if not pipe_name.replace("-", "").isalnum():
        raise ValueError("Pipe name must be alphanumeric or hyphen")
    broker = Broker(root, expected_sid)
    security, descriptor = pipe_security_attributes(expected_sid)
    try:
        handle = KERNEL32.CreateNamedPipeW(r"\\.\pipe" + "\\" + pipe_name, PIPE_ACCESS_DUPLEX,
            PIPE_TYPE_MESSAGE | PIPE_READMODE_MESSAGE | PIPE_WAIT, 1, MAX_FRAME, MAX_FRAME, 0,
            ctypes.byref(security))
    finally:
        KERNEL32.LocalFree(descriptor)
    if handle == INVALID_HANDLE_VALUE:
        raise OSError(ctypes.get_last_error(), "CreateNamedPipeW")
    try:
        connected = KERNEL32.ConnectNamedPipe(handle, None)
        if not connected and ctypes.get_last_error() != ERROR_PIPE_CONNECTED:
            raise OSError(ctypes.get_last_error(), "ConnectNamedPipe")
        sid = pipe_client_sid(handle)
        try:
            request = read_frame(handle)
            if request == {"command": "hello"}:
                write_frame(handle, {"ok": True, "event_id": broker.pilot.event})
                request = read_frame(handle)
            denied_after_revoke = False
            for _ in range(8):
                try:
                    response = broker.dispatch(sid, request)
                except (PermissionError, ValueError, RuntimeError, KeyError, TypeError) as exc:
                    response = {"ok": False, "error": type(exc).__name__}
                    denied_after_revoke = denied_after_revoke or broker.revoked
                write_frame(handle, response)
                if response.get("ok") is False:
                    break
                request = read_frame(handle)
            else:
                raise ValueError("Request budget exhausted")
        except (PermissionError, ValueError, RuntimeError, KeyError, TypeError) as exc:
            write_frame(handle, {"ok": False, "error": type(exc).__name__})
            denied_after_revoke = False
        result = {"status": "PREPARED_ONLY", "pipe_name": pipe_name, "client_sid": sid,
                  "event_id": broker.pilot.event, "state": broker.pilot.state(),
                  "backup_restore_equal": bool(broker.recovery and broker.recovery["backup_restore_equal"]),
                  "worker_revoked": broker.revoked, "activation_authorized": False}
        (broker.pilot.root / "evidence" / "windows-sandbox-broker.json").write_text(
            json.dumps(dict(result, denied_after_revoke=denied_after_revoke), indent=2) + "\n",
            encoding="utf-8")
        return result
    finally:
        KERNEL32.DisconnectNamedPipe(handle)
        KERNEL32.CloseHandle(handle)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", required=True, type=Path)
    parser.add_argument("--expected-sid", required=True)
    parser.add_argument("--pipe-name")
    args = parser.parse_args()
    print(json.dumps(serve_once(args.run_root, args.expected_sid, args.pipe_name), indent=2))


if __name__ == "__main__":
    main()
