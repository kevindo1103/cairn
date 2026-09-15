# Local Codex communication ledger

A standalone Python + SQLite MVP for durable handoffs between named tasks. It records delivery and worker acceptance separately, survives process restarts, and provides a dependency-free CLI plus an optional official MCP SDK stdio server.

Local integration update: the user-authorized `communication-ledger-local` stdio server is now registered. A real host delivery of one synthetic UAT event to this standalone task completed. The registered command is callable; tools were not yet loaded into the already-running task's native tool inventory. See `INTEGRATION.md` for exact paths, activation boundary and rollback.

**Automatic task wake: `NOT_IMPLEMENTED`.** The manual adapter prepares an envelope only. No code calls Codex task APIs, starts workers, interrupts a task, sends messages, polls a service, or accesses ERP/GitHub. This repository is independent of Bingxue ERP and grants no deployment or production authority.

## Run locally

Use Python 3.11 or newer. This delivery was tested on Windows with Python 3.14.3. Run commands from this package directory. Nothing requires a global installation.

```powershell
# Standard-library CLI and core tests need no installation.
python -m unittest tests.test_ledger -v
python -m examples.demo

# Optional MCP: install only into a local virtual environment.
python -m venv .venv
.venv/Scripts/python -m pip install -e '.[mcp]'
.venv/Scripts/python -m unittest discover -v
```

`requirements-mcp-windows.lock` captures the optional MCP verification versions; reproduce it with `.venv/Scripts/python -m pip install -r requirements-mcp-windows.lock`. It is a version snapshot, not a hash-verified or cross-platform lock. Core runtime has no third-party dependencies.

All automated tests and the demo use temporary **synthetic** databases inside `work/` and clean them up. They do not contact real tasks. `python -m unittest discover` without the optional SDK reports the MCP test as skipped; that is not MCP proof. The full delivered verification uses `.venv/Scripts/python` with no skips.

## CLI walkthrough

Create a new demo database once; use a fresh database for each complete replay. Re-enqueueing the same payload returns its original event, even after completion.

```powershell
python -m comms_ledger --db work/demo.sqlite --pm-task pm init
python -m comms_ledger --db work/demo.sqlite checkpoint --input examples/checkpoint.json
$event = python -m comms_ledger --db work/demo.sqlite enqueue --input examples/event.json | ConvertFrom-Json
$claim = '{"target":"worker-task","dispatcher":"manual-dispatcher"}' |
  python -m comms_ledger --db work/demo.sqlite claim | ConvertFrom-Json
@{event_id=$event.id; delivery_token=$claim.delivery_token} | ConvertTo-Json |
  python -m comms_ledger --db work/demo.sqlite prepare_manual
```

Preparing an envelope leaves the event `QUEUED`. For a real handoff, use an explicitly authorized host channel to deliver it to the exact existing target, retain a receipt reference, and only then call `sent`. The following continues **only the synthetic demonstration**, without delivering anything externally:

```powershell
@{event_id=$event.id; delivery_token=$claim.delivery_token; receipt='synthetic://simulated-delivery'} |
  ConvertTo-Json | python -m comms_ledger --db work/demo.sqlite sent
$ack = @{event_id=$event.id; target='worker-task'; worker='worker-1'; evidence='synthetic://simulated-ack'} |
  ConvertTo-Json | python -m comms_ledger --db work/demo.sqlite ack | ConvertFrom-Json
@{event_id=$event.id; worker_token=$ack.worker_token; evidence='synthetic://first-action'} |
  ConvertTo-Json | python -m comms_ledger --db work/demo.sqlite start
@{event_id=$event.id; worker_token=$ack.worker_token; evidence='synthetic://result'} |
  ConvertTo-Json | python -m comms_ledger --db work/demo.sqlite complete
'{}' | python -m comms_ledger --db work/demo.sqlite snapshot
```

Do these steps within the delivery lease (default 60 seconds), ACK deadline (120 seconds), and worker lease (300 seconds). Use the matching parameters for longer bounded windows, up to one day. Keep claim/worker tokens in the caller's private working state; read/history outputs omit them. Lost ACK replies can be retried with the same event, target, worker and evidence to retrieve the existing unexpired worker token.

The CLI takes JSON command arguments from stdin or `--input FILE`. It emits JSON to stdout, errors to stderr, and exits 2 for rejected input. `--db` is always explicit. `init` requires `--pm-task` for a new database; that binding cannot subsequently be replaced through this API. Other commands open an already initialized database.

## State and recovery rules

| State | Meaning |
| --- | --- |
| `QUEUED` | Durable event, possibly reserved by a delivery lease; nothing has accepted transport yet |
| `SENT` | Caller recorded a transport receipt; no worker acceptance implied |
| `ACKED` | Exact target and one worker accepted; worker token and recipient slot reserved |
| `STARTED` | Worker recorded first-action evidence under a live lease |
| `COMPLETED` | Worker recorded result evidence; recipient slot released |
| `BLOCKED` | Retry exhausted, worker lease expired, or explicit blocker; requires reconciliation |
| `CANCELLED` | Explicit cancellation, retained as history |
| `SUPERSEDED` | Explicit replacement or checkpoint/base/head changed before completion |

SQLite uses WAL, `synchronous=FULL`, foreign keys, unique dedupe keys, and `BEGIN IMMEDIATE`. Projection changes and audit records commit together. Database triggers prevent event deletion, payload identity changes and history edits through ordinary SQL. This is durability under normal local SQLite/filesystem guarantees, not tamper resistance against a database administrator.

Each event has a generated UUID, immutable canonical payload and SHA-256 digest. Same dedupe key + same payload is idempotent; different content is rejected. Required payload fields are in `examples/event.json`; unknown fields are rejected. Timestamps are UTC Unix seconds. Priorities 0/1/2 are ordinary Lead ordering; 100 is reserved for PM. Dependency is one existing event UUID; it must be completed and still bound to its current checkpoint. Existing-only dependencies form a DAG. Blocked/cancelled/stale dependencies hold downstream work without discarding it.

Checkpoint updates use `(issue, scope)` plus an expected revision. An update invalidates all outstanding events bound to the old checkpoint/base/head. Completed events remain historical evidence but cannot satisfy a dependency after their binding becomes stale. The ledger cannot detect Git movement on its own: the owning Lead must record the current checkpoint after verification. No checkpoint record creates plan approval or expands authority. Checkpoints and ordinary enqueues need no per-message PM approval.

One normal delivery lane per recipient prevents parallel dispatch, and ACK reserves one normal execution slot. A separately reported `busy` flag preserves unrelated work outside the ledger. Busy state is caller-reported; no app-status inference is made. PM `STOP` events require priority 100, bypass the normal busy lane and carry their own event ownership. They do **not** kill a process, cancel unrelated work, or free its slot. The operator/recipient must perform the separately authorized stop, record evidence, and reconcile the old event. PM may override queue priority; ordinary priority increases do not bypass busy work.

Recovery is explicit (`recover`) and also runs before a claim/retry inspection. There is no background scheduler:

1. A claimed delivery consumes an attempt before external delivery. Delivery failure, expired claim, or missing ACK leaves an audit trail. The first failure returns it to `QUEUED` with `needs_inspection=1` and a 30-second delay.
2. The owning source Lead or PM inspects recipient/transport state, then records an evidence reference with `inspect_retry`. A second claim is eligible only after inspection and the delay. At most **two total attempts** are allowed; the second failure becomes terminal `BLOCKED` and needs manual fallback/PM attention.
3. A late receipt or ACK after its deadline is rejected. Delivery may nevertheless have happened outside the ledger; there is no exactly-once transport guarantee. Check the exact event ID before resending. No duplicate worker should be started to work around a missing ACK.
4. Expired worker leases become `BLOCKED` and revoke the old token while retaining the recipient slot. After confirming that the real worker stopped, PM calls `release_stopped_worker`. Never release the slot based only on elapsed time. A new explicitly reconciled event may then proceed.
5. Terminal events do not reopen. Record corrected work with a new dedupe key and current checkpoint/evidence. Cancellation/supersession of active work retains its slot until PM confirms the worker stopped. Successful completion releases it directly.

Worker lease tokens fence **ledger writes only**. They cannot fence filesystem edits or external side effects from a paused/disconnected worker. PM confirmation is an attestation, not a technical process-kill check. This is why expired active slots are held.

## Command reference

All names below are both CLI commands and values for the MCP `ledger_command` tool. Arguments are named JSON properties. Defaults are shown in parentheses.

| Command | Arguments |
| --- | --- |
| `checkpoint` | actor, issue, scope, checkpoint, base, head, expected_revision, evidence |
| `enqueue` | payload |
| `set_busy` | actor, target, busy (boolean), evidence |
| `claim` | target, dispatcher, lease_seconds (60) |
| `prepare_manual` | event_id, delivery_token |
| `sent` | event_id, delivery_token, receipt, ack_timeout (120) |
| `delivery_failed` | event_id, delivery_token, evidence |
| `inspect_retry` | event_id, actor, evidence |
| `ack` | event_id, target, worker, evidence, lease_seconds (300) |
| `start` | event_id, worker_token, evidence |
| `renew` | event_id, worker_token, lease_seconds (300) |
| `complete` | event_id, worker_token, evidence |
| `terminate` | event_id, actor, state (BLOCKED/CANCELLED/SUPERSEDED), evidence |
| `release_stopped_worker` | event_id, actor (PM), evidence |
| `override_priority` | event_id, actor (PM), priority, evidence |
| `recover` | none |
| `get` | event_id |
| `snapshot` | target (optional) |
| `history` | event_id (optional; absent includes global checkpoint/recipient changes) |

Read commands do not alter timeout state. Run `recover` to materialize expired states. Use `snapshot` for current checkpoint revisions and retained recipient slots. Snapshot/history return all matching records in this MVP; large-scale pagination, retention policy and automatic escalation are not implemented.

## MCP setup boundary

Official documentation was verified before implementation. The server uses `mcp.server.MCPServer` from the official SDK, pinned to 2.2.0, and `run(transport="stdio")`. It exposes `ledger_read`, `ledger_command`, and `ledger_help` with structured JSON results. `ledger_help` supplies signatures and required enqueue fields. A test client launches, exercises and exits a real stdio server; no persistent process remains.

The separately authorized registration now uses the absolute executable path to `.venv/Scripts/python.exe` and arguments `-m comms_ledger.server --db <absolute-local-db-path>`. The local editable install makes it independent of the caller's working directory; the registered invocation was verified from a different directory. The private database was initialized via CLI first. Exact configuration and backup are documented in `INTEGRATION.md`. Running the module directly waits for an MCP client on stdin; it is not an interactive CLI.

The available host messaging tool in the authoring task is not assumed to be an API accessible to a standalone Python process. No supported external wake interface for existing desktop tasks was proven for this adapter. Accordingly, automatic wake stays `NOT_IMPLEMENTED`. MCP accessibility and automatic delivery are separate capabilities; connecting this server does not wake recipients.

## Trust and data boundaries

This MVP is for one trusted local operator/host. Actor, source task, target task and worker names are assertions supplied by that operator; the PM check enforces the configured identifier but is **not authentication**. Any client with unrestricted local access can impersonate an actor or edit the database. There is no multi-user authorization, network service, secret store, or production integration. Apply OS filesystem access controls before sharing the host; do not expose this server over HTTP.

Store only concise coordination metadata and evidence references (`https://`, `artifact://`, `synthetic://`). There are no fields for attachments or raw logs, and strings are bounded to a single line. Validation does not detect every secret or personal identifier: never submit credentials, sensitive query-string links, personal data, or raw production logs in any field. Evidence content is not fetched or verified by this ledger.

Keep the database on a local disk outside OneDrive/network shares. No automatic backup/restore or schema migration system is included (schema version 2; schema 1 requires separately reviewed offline migration). Stop clients before making a filesystem backup and preserve all SQLite files together; use SQLite's backup API for a live backup. Clock jumps can affect timeout timing; timeout never proves a worker stopped. No live Codex/ERP/UAT acceptance is claimed by synthetic tests.

## Design provenance

Read-only input: [ERP PR #1571](https://github.com/kevindo1103/bingxue-erp/pull/1571), pinned to `ea5cecbda37583632b8373e17e04e271f5a819d2`: `AGENTS.md` communication ledger section and `docs/SESSION_COMMS.md` durable queue handoff section. These supplied design requirements, not permission to alter ERP, contact its workers, or gate its deployment.

Official references checked 2026-09-10:

- [Official MCP Python SDK](https://py.sdk.modelcontextprotocol.io/) — SDK class and tool registration.
- [SDK server transports](https://py.sdk.modelcontextprotocol.io/run/) — local stdio subprocess lifecycle.
- [SDK client](https://py.sdk.modelcontextprotocol.io/client/) — integration client and structured results.
- [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli) — supported local stdio configuration. This documents connecting tools, not this adapter's automatic wake.

See `VALIDATION.md` for executed evidence and limitations. Source, tests, examples and docs are local Git deliverables on `codex/communication-ledger`; no remote repository was created.
