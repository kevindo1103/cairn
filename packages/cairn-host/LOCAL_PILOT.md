# Local synthetic queue pilot

This rehearsal starts one Python fixture child over private stdio pipes. The
parent uses the existing core and Adapter; it creates a new synthetic project,
registry and one ordinary APPROVAL event. It exercises receipt, reconciliation,
ACK, start, renew and completion. It does not exercise HANDOFF or succession.
The parent fixes the channel mapping and retains random fixture owner/principal
credentials. The child receives only the event ID and its later worker lease.
No credential is written to the result JSON or child command line.

Baseline is adapter ee86e13ea44d1e3ac181e08418f624ea8f8b3d29 with core
39950de062ef085ed4e0ba5f87e3b48d6183d551. Core module hashes are checked by the
existing package verifier. The baseline field records provenance, not a runtime
attestation of the adapter or new host script; review their exact commit separately.

## Run without installation

From the checkout root, use an available Python 3.12+ interpreter:

```text
python -m unittest discover -s packages/cairn-host/tests -v
python packages/cairn-host/local_queue_pilot.py --run-root ABSOLUTE_NEW_RUN_DIRECTORY
```

The parent of the new run directory must already exist. For this local assignment,
use unique children of
`C:/Users/ddkho/Documents/Codex/2026-09-10/codex-communication-ledger/work/issue15-readiness/local-pilot/runs/`.
Never point at a live store. Existing roots, traversal and linked ancestors are
refused. Partial outputs are retained for inspection and must not be reused.
The CLI accepts only the exact inert example config; no account, model, listener,
runtime install, service, scheduled task or Codex settings are involved.

Use `--scenario` with happy, receipt_only, crash_after_ack, duplicate,
wrong_mapping or impersonate. The last five are explicit fault fixtures.
The loop is bounded to 15 seconds, 12 requests and 64 KiB per frame. Cleanup
may take up to seven additional seconds to reap only this fixture child.
There is no automatic retry, lease release, queue replay or takeover.
The CLI exits nonzero if the observed child exit/state/request counts do not match
the selected scenario; merely producing an evidence file does not count as success.

## Evidence and recovery

`evidence/result.json` records parent/child PIDs, child exit, request outcomes,
event state, completion count, retained slots and a complete recovery proof.
The backup uses the existing SQLite consistent backup API, including WAL if
present, and restore creates a new root. The restored Store must reopen and its
proof must equal the source/backup proof. It is never activated or dispatched.
All rejection records assert the entire logical proof stayed unchanged.

Expected outcomes: happy completes once; receipt_only remains SENT; mapping and
actor spoofing stay SENT; duplicates leave one completion; exit 74 after ACK
leaves ACKED with a retained slot. A new parent refuses that old root before
opening its DB. Death of this child does not grant authority to release a lease.

These are real processes and real SQLite transitions with synthetic identities
and authority evidence. Same-user processes are not security isolation. The
worker can potentially access other same-user files; omitting secrets from its
envelope does not prove host fencing. This is a fixture harness, not an exposed
production broker. Every result stays PREPARED_ONLY and live_readiness=false.

## Remaining integration

No Codex task is created, resumed, messaged or automatically woken. Real transport
needs an authorized App Server integration, independently established identity,
restricted filesystem/process access, stop/revoke tests and recovery acceptance.
Official docs describe stdio JSONL and thread/resume plus turn/start:
https://learn.chatgpt.com/docs/app-server . A transport response or model completion
does not replace an explicit ledger ACK or completion. WebSocket is labelled
experimental/unsupported in the documentation inspected for this plan.

The local capability check found WSL/Hyper-V services running but could not
enumerate guests because platform permissions denied access. Guest availability
and usable isolation remain unknown. No permission bypass, OS install, broad ACL
change, live ledger operation, authority flip, retirement or ERP action is included.
