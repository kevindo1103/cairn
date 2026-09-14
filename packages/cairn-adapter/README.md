# Cairn principal adapter — issue #10

Review-only Python library on the existing communication-ledger package. No server,
MCP registration, dispatcher process, hook, installation, activation, authority flip,
task creation or retirement is performed. No ERP files or runtime data are used.

This separate PR targets main and owns only `packages/cairn-adapter/**`. Its accepted
package base is `f31726234c43c2ded4716c0998a8e4475ad25c19`, communication-ledger
version `0.1.0`, annotated tag `communication-ledger-v0.1.0` (tag object
`065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f`). PR #9 is merged. Package tree and
module hashes are identical to the prior checkpoint; the ledger lifecycle is unchanged.
The exact package Git tree and LF-normalized Python source hashes are pinned in
`cairn_adapter/package.lock.json`. Construction and every request refuse different
package content. Package binding is now accepted/versioned; independent adapter QC
remains pending. No dependency is silently upgraded. See ACCEPTED_PACKAGE.md for
the current exact base/head and zero-skip evidence.

## Trust boundary

The integrating host must own the process, interpreter/import path, executables,
canonical project root, SQLite DB, package lock and credentials. Workers may only call
the narrow `Adapter.execute` interface over a future authenticated host boundary.
They must not receive a Store, Owner, verifier object, database path/access, interpreter
access in the host, or the raw ledger CLI/MCP. Direct Python/file access bypasses this
facade; preventing that is NOT_PROVEN and is a prerequisite for any later deployment.
No host authentication transport is installed or claimed by this change.

Worker requests contain a bearer credential, exact principal generation, registry
revision, scope, command and allowlisted arguments. The credential hash resolves a
single canonical identity; an `actor`, registry, verifier or checkpoint supplied in
arguments is rejected. Generate credentials with at least 256 random bits in the host;
the fixed tokens in tests are synthetic only. Logs/read models never return credentials.

The distinct Owner interface authenticates a separate owner credential and applies
complete registry snapshots using CAS. A worker credential cannot write the registry
or overlap the owner credential. Identity rotation increments its generation exactly
once, and every registry edit increments the global revision. Credentials, task IDs
and successor assignments must be unique; stale generations, successor cycles and
silent deletion of old records fail closed. The configured PM identity is preserved.
ACTIVE/QUIESCED are owner-observed registry facts, not a new event workflow.

Both registry CAS and `principal x command x scope x state` checks share the same
`BEGIN IMMEDIATE` transaction as package mutations. The small TransactionLedger shim
only supplies that transaction to existing ledger methods; no event transition is
reimplemented. Registry/provenance/reconciliation metadata use the existing config
table; the ledger's history records their audit digests. There is one fixed
`ledger.sqlite` under the host-bound project root; requests cannot select another DB.
The host must maintain a single canonical root per project. Recovery copies are offline.

## Fresh authority and lifecycle

For every command, GitHubVerifier reads the owner-bound worktree and GitHub repository,
PR and plan issue. It checks exact local/remote base and head, tree, branch, remote URL,
clean worktree, complete changed-path inventory, manifest/rule SHA-256, rule/config
versions and plan body digest. All changed and renamed paths must lie in allowed roots.
The base must be an ancestor of the head; divergent bases conservatively fail closed.
It rechecks local/remote heads and plan at the end. Missing credentials, network,
objects, paths or malformed/ambiguous responses reject the operation. There is no cache
or caller-reported checkpoint fallback. A checkpoint is derived from the verified
binding and written only by a principal explicitly granted checkpoint authority.

GitHub reads use the host's GitHub CLI through argument arrays, an explicit github.com
hostname and bounded subprocess timeouts. Local Git does not run external diff/textconv.
Verification holds the DB writer lock; this favors safety over throughput. It proves
observations at command time, not an atomic transaction with GitHub or filesystem/process
fencing. Fork PRs, multiple origin URLs and paths outside the allowlist are rejected.

The existing lifecycle remains `QUEUED -> SENT -> ACKED -> STARTED -> COMPLETED`, with
terminal `BLOCKED`, `CANCELLED`, `SUPERSEDED` attempts. Queue selection remains the
package's priority/dependency/busy arbitration. A claim for a different event rolls back.
Package timeout maintenance that would mutate another scope or a disallowed state also
rolls back; separately trusted host recovery is then required. Source/recipient generation
and credential ownership fence ledger tokens. Quiesced topology cannot acquire delivery
or work. Existing active work is not magically stopped by a bookkeeping transition.

`sent` records the authenticated dispatcher's transport receipt, never a worker ACK.
Receipt truthfulness must be attested by the trusted transport host; arbitrary receipt
URLs do not prove external delivery. `reconcile` records a fresh recipient/event digest,
checkpoint revision, principal generation and registry revision. ACK requires that
exact durable reconciliation, so stale policy, binding or principal identity cannot
reuse it. ACK/start/complete must belong to the authenticated recipient/worker owner.

`BLOCKED` remains terminal; a dashboard's resumable `blocked` label cannot reactivate
it. Reconciliation needs a new ledger event. Expired workers keep active slots until
the separate trusted host verifies they stopped; no worker-facing release operation
is exposed. Automatic wake is NOT_IMPLEMENTED. Filesystem/process fencing is NOT_PROVEN.

## Retirement and recovery

`retirement` is a read-only assessment of completed HANDOFF, the exact ACTIVE successor
generation, QUIESCED predecessor and drain ZERO. Drain includes active mutations and
unmapped work observed by the separate host, plus all unfinished relevant events,
retained recipient slots, delivery/worker leases and undelivered handoffs in the ledger.
The predecessor's successor mapping must match. PM eligibility additionally requires
all registry-mapped non-PM predecessors to satisfy their full retirement conditions.
Ambiguous multiple old PM mappings refuse eligibility. Old BLOCKED/unmapped events
conservatively keep drain nonzero; this adapter does not invent a work-remapping authority.

Every assessment returns `actions_executed=[]` and `retirement_authorized=false`, even
when the four-part eligibility invariant is true. Host quiescence reports are separate
authority assertions; real process-stop proof is NOT_PROVEN. Production acceptance,
complete migration inventory, package acceptance and PM/user cutover authorization
remain separate prerequisites. No eligibility result flips authority or archives tasks.

`recovery.backup` uses SQLite's backup API while holding a stable read snapshot, including
uncheckpointed WAL. It compares complete logical tables, schema/indexes/triggers, config
and PM/project binding, checkpoints/revisions, event history, receipts, slots, terminal
states, credential/provenance metadata, digest and history high-water mark. Proof exposes
counts/digests, not tokens. `restore` requires the independently retained exact proof
and matching project, copies only into a new `ledger.sqlite`, and refuses an existing
destination. It never restores over a live DB or makes a backup an active project.
After real recovery, old claims and external workers still require host reconciliation;
restoring a file alone cannot safely revoke external work or prevent history rollback.

## Validation

From the Cairn checkout, with Python 3.11+ and Git available:

```text
python packages/cairn-adapter/run_tests.py
```

No install, network, MCP service, existing project DB or GitHub write is used by tests.
The runner imports the sibling pinned package and fails on any skip.
The 16 named groups are mapped in MATRIX.md; additional tests cover transaction CAS
races, cross-scope timeout effects, freeze, PM-last, dependency drift and real local Git.
GitHub responses in verifier tests are explicit fixtures, not live GitHub E2E evidence.
See ACCEPTED_PACKAGE.md for exact environment, results and pending adapter QC.
