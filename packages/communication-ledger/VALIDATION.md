# Implementation handoff and validation

This records the initial implementation handoff. The subsequently authorized local registration and real manual UAT are documented separately in `INTEGRATION.md`; initial NOT_RUN entries below describe the initial handoff, not the later trial.

Date: 2026-09-10 (Asia/Saigon). Scope: this standalone local repository only.

- Branch: `codex/communication-ledger`.
- Tested implementation commit: `d52d48dc1c5631547dd1a634eb0d8d9f1c95da38`.
- First concrete checkpoint: `6280023b22e266e7b389e764b63f4cb3b5723760` (23 core tests passed), reported to PM task `01a07d6f-05ae-74b1-90f3-3a9487ae4a24`.
- This validation record is a subsequent documentation-only commit; `git rev-parse HEAD` identifies the full handoff revision. Implementation/tests are unchanged from the tested commit above.
- Authoring used the configured model/effort. No model override, remote repository or global installation.

## Executed evidence

| Check | Result | Scope |
| --- | --- | --- |
| `python -m unittest tests.test_ledger -v` at first checkpoint | 23/23 PASS, 6.519 s | Core behavior and real CLI process |
| `.venv/Scripts/python -m unittest discover -v` on final implementation | **28/28 PASS, 18.225 s, zero skips** | 27 core/CLI tests + one end-to-end MCP scenario |
| `python -m examples.demo` | PASS | Synthetic event reached COMPLETED after reopening SQLite |
| `.venv/Scripts/python -m pip install --no-deps -e .` | PASS | Local editable package build/install |
| `.venv/Scripts/python -m pip check` | PASS | No broken requirements |
| Installed CLI and MCP entrypoints `--help` | PASS | Both console entrypoints runnable |
| `python -m compileall -q comms_ledger tests examples` | PASS | Python compilation |
| `git diff --check` / staged diff check | PASS | Whitespace verification |
| Repository remote listing | Empty | No remote configured |
| Local process check after tests | No `python ... comms_ledger.server` process | Test server exited; no persistent service |
| Temporary test directory check | Empty | Synthetic test/demo databases cleaned up |

Environment: Windows, Python **3.14.3**, official MCP SDK **2.2.0**, output-local `.venv`. `requirements-mcp-windows.lock` records the dependency versions actually installed before the local package. Standard-library core tests do not require MCP.

The MCP test starts a real stdio subprocess with the official SDK Client, lists all three tools, reads server instructions, records a checkpoint, enqueues/claims/prepares a manual envelope, simulates transport receipt, ACKs/starts/completes, verifies a rejected command, exits the server, starts a fresh server, and verifies persisted state and history. It performs no external delivery. The expected rejected command emits a tool-error log; the test requires the protocol error result and passes.

An initial MCP test exposed missing structured output from unparameterized dictionary return annotations. Explicit structured output plus `dict[str, Any]` fixed the interface; the full suite above passed afterward. Ordinary validation errors now return intentional MCP tool errors.

## Required scenarios covered

| Requirement | Test evidence |
| --- | --- |
| Contention / duplicate delivery claim | Four independent spawned processes compete; exactly one claims |
| Duplicate event | Repeated and four-thread enqueue return one UUID; changed payload conflicts |
| Busy recipient | Pre-claim busy retains QUEUED without consuming attempts; post-send busy rejects ACK |
| Delivery failure | Failure evidence retained; one inspected retry; second failure becomes BLOCKED |
| Restart persistence | Receipt/ownership persist across reopening; failed delivery remains inspection-gated; MCP server restart reads COMPLETED |
| Missing ACK | SENT remains separate from worker acceptance; timeout marks MISSING_ACK; late ACK rejected |
| Expired delivery lease | New claim requires inspection; old dispatcher token cannot write SENT |
| Expired worker lease | Becomes BLOCKED, holds recipient slot, rejects stale worker; PM stop attestation required to release |
| Stale approval | Checkpoint CAS rejects stale updates; old approval superseded; stale completed approval cannot satisfy new dependency |
| Successful handoff | QUEUED/SENT/ACKED/STARTED/COMPLETED with evidence; dependent work progresses without PM intervention |
| Single worker ownership | Competing ACKs yield one winner; duplicate same-worker ACK is idempotent |
| PM priority / urgent STOP | Ordinary Lead override rejected; PM STOP delivers through control lane while unrelated active work/queue remain intact |
| Lease renewal | Live owner extends lease; expired renewal rejected |
| Terminal dependency | Cancelled dependency prevents downstream claim |
| Durability / privacy of tokens | Audit/payload edits rejected; read/history outputs omit lease tokens |
| Invalid commands | Bad tokens and early completion leave state/history unchanged; CLI rejects missing event; MCP rejects private command |

## Acceptance limits and next owner

**Delivered:** runnable local ledger, standard-library CLI, official SDK MCP stdio interface, manual Codex envelope adapter, synthetic tests, setup/runbook and versioned source.

**NOT_IMPLEMENTED:** automatic Codex task wake, automatic transport, real process interruption, background dispatcher/monitor, automatic PM fallback notification, identity authentication, multi-user network service, cross-machine operation, migrations and automatic backups. The adapter is an explicit seam and never invents an external wake API.

**NOT_RUN:** registration in the user's Codex settings, real task-to-task delivery through this standalone package, real worker acceptance/UAT, independent review, ERP or production validation. No ERP code/docs/CI were changed and no ERP worker was contacted. The two authorized reports to the PM task use the host's existing message tool; they are not evidence that Python can call it.

Actor IDs are trusted local assertions. PM identifier checks are application rules, not authentication. Lease tokens fence ledger transitions, not external filesystem or production side effects. Expiry cannot prove a real worker stopped; retained slots require explicit reconciliation. Evidence URLs are references, not fetched or verified facts. Never enter secrets, personal data or raw production logs.

Next owner: PM/user reviews this standalone handoff. A later, separate approval is needed to register the MCP server in Codex, create a remote repository, or run a persistent dispatcher/service. None is needed for the delivered local CLI or synthetic demo. This work neither consumes production authority nor gates ERP deployment.
