# Existing-task manual transport UAT facade

An offline TEST-store preparation/import script only. PM performs any approved
manual transport through its supported platform route. This script never sends,
creates/resumes a task, starts App Server, reads the live ledger or changes OS
permissions. Fixed recipient: Tìm cách tải video,
01a0a069-8b36-70e0-b66b-7af6ff0b1913. PM rechecks it is not active before sending.
No new recipient or task may be selected by caller input.

Prepare once under a new disposable directory; its parent must already exist:

    python packages/cairn-host/existing_task_uat.py prepare --root NEW_TEST_ROOT

The existing Store/Adapter freeze one ordinary APPROVAL event, source head,
checkpoint, scope, dedupe and random nonce. evidence/envelope.json is the only
payload intended for delivery: no credentials or filesystem paths. broker/ holds
the synthetic DB and random test credentials; it is never sent to the recipient.
An existing run root cannot be prepared again. This is not live migration.

PM imports each stage separately, after observing actual platform evidence:

    python packages/cairn-host/existing_task_uat.py sent --root TEST_ROOT --observation SENT_JSON
    python packages/cairn-host/existing_task_uat.py ack --root TEST_ROOT --observation ACK_JSON
    python packages/cairn-host/existing_task_uat.py start --root TEST_ROOT --observation START_JSON
    python packages/cairn-host/existing_task_uat.py complete --root TEST_ROOT --observation COMPLETE_JSON

Each JSON has exactly observer=PM_MANUAL_PLATFORM_READBACK, origin and readback.
origin contains the tool-resolved thread_id, turn_id and evidence_ref. SENT uses
turn_id=null because a transport receipt is not recipient execution. ACK needs a
nonempty platform-resolved turn; START uses the second recipient turn; COMPLETE
must match START's turn. Never extract origin from echoed task IDs in response text.
PM, not this parser, establishes the provenance of the file it supplies.
Evidence reference validation reuses the pinned core contract before opening the
Store: https://, artifact:// or synthetic://, at most1000 characters. codex://
is not a ledger evidence scheme. Preserve a real platform receipt (including any
codex locator) in an owner-reviewed artifact, then reference that artifact with
artifact://sha256/DIGEST; never relabel an unobserved delivery as evidence.
An import failure does not undo an external message. Preserve delivered/import-
failed state and obtain a recovery decision before importing again or sending.

readback contains every frozen envelope field plus action: TRANSPORT_ACCEPTED,
ACK_REQUEST, START_REQUEST or COMPLETION_REQUEST respectively. Completion also
requires integer result42 for17+25. Wrong origin/nonce/checkpoint/dedupe/turn,
extra fields, out-of-order, duplicate and expired imports are refused. Max input
16KiB; duplicate JSON keys/non-finite numbers rejected. Five minutes starts with
the imported SENT receipt; existing core ACK/lease deadlines can be stricter.
Two recipient messages maximum, no retry: readback/ACK request, then arithmetic
with explicit START_REQUEST and COMPLETION_REQUEST. No download or ERP activity.

Import validates canonical state and registry revision, then performs transitions
and appends observation digest/origin to existing config/history within ONE SQLite
transaction. Reconciliation still precedes ACK. A failed ACK rolls both back.
Worker token stays in the broker; receipt is never auto-promoted to ACK. Exact
result receipts are printed without credentials and remain auditable in the DB.

The owner-fixed registry is CAS/revisioned. Import files and same-user storage
are MANUAL_ATTESTATION, not enforced OS/platform identity. The parser cannot prove
the PM actually obtained an observation from the platform. Keep principal
enforcement and isolation NOT_PROVEN, automatic wake NOT_IMPLEMENTED, activation
unauthorized even if all imported lifecycle stages complete. No stronger label
is available through this script. Its fixture source verifier is not live GitHub
authority. No secret copying, permission bypass, listener or generic daemon.

If a platform tool denies access, PM reports that limitation and stops; this
facade must never be used as an alternate route around the denied operation.
On timeout/DECLINE, preserve the test event/lease state without release/requeue.
Final transport evidence requires real PM receipts and explicit recipient requests;
unit tests or manually invented fixtures cannot establish real UAT success.
