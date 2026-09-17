import hashlib, json, os, sqlite3, subprocess, sys, time, types
from pathlib import Path

WORKTREE = Path(r"C:\Users\ddkho\Documents\Codex\2026-09-10\codex-communication-ledger\work\cairn-issue15-adapter")
HOST = WORKTREE / "packages" / "cairn-host"
sys.path.insert(0, str(HOST))
import existing_task_uat as uat

CODEX = r"C:\Users\ddkho\AppData\Local\OpenAI\Codex\bin\12219cbfbcbddde7\codex.exe"
ROOT = Path(r"C:\ProgramData\CairnBroker\issue15-test\incident-audit-20260915-01")
HEAD = "0dc7996c1281eb92f8e4ceb9e044cbcc32e25476"
DEDUPE = "cairn:limited-pilot:incident-audit:001"
OBSERVER_PATH = Path(r"C:\ProgramData\CairnBroker\issue15-test\observer-21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329.py")
OBSERVER_SHA256 = "21b4115ceb182c763d6f9f3ec7e3f2a2d10656a35e2f396330fa245a6da5f329"
ROOT.mkdir()
(ROOT / "evidence").mkdir()


def load_observer():
    if os.path.islink(OBSERVER_PATH) or (os.lstat(OBSERVER_PATH).st_file_attributes & 0x400):
        raise RuntimeError("observer artifact must not be a reparse point")
    data = OBSERVER_PATH.read_bytes()
    if hashlib.sha256(data).hexdigest() != OBSERVER_SHA256:
        raise RuntimeError("observer artifact hash mismatch")
    module = types.ModuleType("cairn_protected_observer")
    module.__file__ = str(OBSERVER_PATH)
    exec(compile(data, str(OBSERVER_PATH), "exec"), module.__dict__)
    return module.AppServerStreamObserver, module.SafeNotificationJournal


AppServerStreamObserver, SafeNotificationJournal = load_observer()
events = []
process = subprocess.Popen([CODEX, "app-server", "--listen", "stdio://"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, encoding="utf-8", bufsize=1)
observer = AppServerStreamObserver(
    process.stdout, journal=SafeNotificationJournal(ROOT / "evidence" / "stream-safe.jsonl"))
completed_terminal = False
started_at = time.monotonic()
PM_ATTESTED = False


def artifact(name, content):
    path = ROOT / "evidence" / name
    path.write_text(json.dumps(content, indent=2) + "\n", encoding="utf-8")
    return "artifact://sha256/" + hashlib.sha256(path.read_bytes()).hexdigest()


def request(request_id, method, params):
    process.stdin.write(json.dumps({"jsonrpc": "2.0", "id": request_id,
                                    "method": method, "params": params}) + "\n")
    process.stdin.flush()
    reply = observer.wait_for(lambda message: message.get("id") == request_id,
                              timeout_seconds=90)
    events[:] = observer.received
    if "error" in reply:
        raise RuntimeError(reply["error"])
    return reply["result"]


def until_turn(turn_id):
    completed = observer.wait_for(
        lambda message: message.get("method") == "turn/completed"
        and message["params"]["turn"]["id"] == turn_id, timeout_seconds=90)
    events[:] = observer.received
    return completed


def prospective_sent(envelope, recipient):
    # Fixture only: this is never persisted as a transport receipt or PM attestation.
    return {"observer": "PM_MANUAL_PLATFORM_READBACK",
            "origin": {"thread_id": recipient, "turn_id": None,
                       "evidence_ref": "artifact://fixture/prospective-sent"},
            "readback": dict(envelope, action="TRANSPORT_ACCEPTED")}


def start_delivery(envelope, recipient, ack_payload):
    # Must reject static contract mismatch before the first delivery-bearing turn/start.
    uat.validate_observation(ROOT / "uat", "sent", prospective_sent(envelope, recipient))
    return request(3, "turn/start", {"threadId": recipient, "input": [{"type": "text", "text":
        "No tools. Return exactly this JSON object: " +
        json.dumps(ack_payload, separators=(",", ":"))}]})


def final_json(completed):
    messages = [item["text"] for item in completed["params"]["turn"]["items"]
                if item.get("type") == "agentMessage"]
    if len(messages) != 1:
        raise ValueError("Expected exactly one agent message")
    return json.loads(messages[0])


def observed(envelope, action, turn_id, ref, result=None):
    if not PM_ATTESTED:
        raise RuntimeError("actual PM attestation required before ledger import")
    readback = dict(envelope, action=action)
    if result is not None:
        readback["result"] = result
    return {"observer": "PM_MANUAL_PLATFORM_READBACK",
            "origin": {"thread_id": recipient, "turn_id": turn_id, "evidence_ref": ref},
            "readback": readback}


try:
    request(1, "initialize", {"clientInfo": {"name": "cairn-incident-audit", "version": "0.1"},
                              "capabilities": {"experimentalApi": True}})
    thread = request(2, "thread/start", {"ephemeral": True, "environments": [],
                                          "sandbox": "read-only", "historyMode": "paginated"})
    recipient = thread["thread"]["id"]
    public = uat.prepare(ROOT / "uat", HEAD, recipient=recipient, dedupe=DEDUPE)
    envelope = public["envelope"]
    ack_payload = dict(envelope, action="ACK_REQUEST", acknowledgement=True)
    ack_turn = start_delivery(envelope, recipient, ack_payload)["turn"]["id"]
    receipt = artifact("transport.json", {"thread_id": recipient, "turn_id": ack_turn,
                                           "method": "turn/start", "accepted": True})
    uat.import_observation(ROOT / "uat", "sent",
                           observed(envelope, "TRANSPORT_ACCEPTED", None, receipt))
    if final_json(until_turn(ack_turn)) != ack_payload:
        raise ValueError("ACK payload mismatch")
    ack_ref = artifact("ack.json", {"payload": ack_payload, "events": events})
    ack_result = uat.import_observation(ROOT / "uat", "ack",
                                        observed(envelope, "ACK_REQUEST", ack_turn, ack_ref))
    start_payload = dict(envelope, action="START_REQUEST")
    complete_base = dict(envelope, action="COMPLETION_REQUEST", result=42)
    prompt = (
        "No tools and do not edit files. Return exactly a JSON array with two objects. "
        "First: " + json.dumps(start_payload, separators=(",", ":")) + ". Second: every field in " +
        json.dumps(complete_base, separators=(",", ":")) +
        " plus incident_summary with exactly these nonempty string keys: successful_delivery, missing_ack, "
        "observer_defect, preserved_sent, zero_duplicates. Audit this incident only: event "
        "0825d53e-cc80-4387-91db-7a10a1cdacdd had one accepted transport delivery, no observed explicit ACK, "
        "a readback observer defect, remains SENT, and has zero duplicate delivery/completion. "
        "Do not claim recipient failure and do not propose resend or recovery.")
    work_turn = request(4, "turn/start", {"threadId": recipient,
        "input": [{"type": "text", "text": prompt}]})["turn"]["id"]
    payload = final_json(until_turn(work_turn))
    if not isinstance(payload, list) or len(payload) != 2 or payload[0] != start_payload:
        raise ValueError("START payload mismatch")
    completion = payload[1]
    if any(completion.get(key) != value for key, value in complete_base.items()):
        raise ValueError("COMPLETE payload mismatch")
    summary = completion.get("incident_summary")
    required = {"successful_delivery", "missing_ack", "observer_defect", "preserved_sent", "zero_duplicates"}
    if set(summary or {}) != required or not all(isinstance(summary[key], str) and summary[key] for key in required):
        raise ValueError("incident summary payload mismatch")
    work_ref = artifact("work.json", {"payload": payload, "events": events})
    start_result = uat.import_observation(ROOT / "uat", "start",
        observed(envelope, "START_REQUEST", work_turn, work_ref))
    complete_result = uat.import_observation(ROOT / "uat", "complete",
        observed(envelope, "COMPLETION_REQUEST", work_turn, work_ref, 42))
    store = uat.Uat(ROOT / "uat").store
    api = uat.dependencies()
    proof = api["proof"](store.path)
    backup = api["backup"](store.path, ROOT / "evidence" / "backup.sqlite")
    restored = api["restore"](ROOT / "evidence" / "backup.sqlite", ROOT / "restored", backup, uat.PROJECT)
    reopened = api["Store"](ROOT / "restored", uat.PROJECT)
    if proof != backup or restored != backup or api["proof"](reopened.path) != backup:
        raise RuntimeError("backup/restore mismatch")
    with sqlite3.connect("file:" + str(store.path) + "?mode=ro", uri=True) as conn:
        counts = dict(conn.execute("SELECT action,COUNT(*) FROM history WHERE event_id=? GROUP BY action",
                                   (envelope["event_id"],)).fetchall())
    result = {"recipient_thread_id": recipient, "event_id": envelope["event_id"], "dedupe": DEDUPE,
              "turns": {"ack": ack_turn, "work": work_turn}, "receipt": receipt, "ack": ack_result,
              "start": start_result, "complete": complete_result, "incident_summary": summary,
              "counts": counts, "backup_restore_equal": True, "final_state": complete_result["state"],
              "latency_seconds": round(time.monotonic() - started_at, 3), "interventions": 0,
              "token_usage": "UNAVAILABLE"}
    artifact("result.json", result)
    completed_terminal = True
    print(json.dumps(result, indent=2))
except Exception as error:
    artifact("stop.json", {"status": "STOPPED", "error_type": type(error).__name__,
                           "error": str(error), "received_count": len(observer.received),
                           "latency_seconds": round(time.monotonic() - started_at, 3),
                           "interventions": 0, "token_usage": "UNAVAILABLE"})
    raise
finally:
    observer.close()
    if completed_terminal:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()
