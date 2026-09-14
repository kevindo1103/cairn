# Cairn Governance Ledger — Design Handoff

> Status: design/proposal only (2026-09-10). No runtime enforcement or automatic wake is installed.
> Reusable ledger package: `packages/communication-ledger/` (vendored from the reviewed local MVP source, version 0.1.0); source/tests are callable locally, end-to-end task wake is NOT_IMPLEMENTED.

## Topology

Long-lived sidebar records are PM, leads, QC and Docs. Leads own bounded subagents. A registry entry
must contain real task IDs, role, scope, worktree, branch, authority and expected output. Parent and
child checkpoints preserve status and evidence; one owner/lease prevents duplicate writers.

## Durable delivery ledger

Each event records an ID/dedupe key, source/target task IDs, issue/checkpoint/base/head/scope,
type/priority, dependency/eligibility, timestamps, receipt and result evidence. Lifecycle is
`QUEUED → SENT → ACKED → STARTED → COMPLETED`; terminal states are `BLOCKED`, `CANCELLED` and
`SUPERSEDED`. Delivery failure is durable; approval tied to an old SHA is invalid. Delivery and work
execution are separate. Acceptance is idempotent with bounded retry after inspection; exactly-once
transport is not claimed. Busy queues retain work, PM owns cross-team priority/preemption, and Leads
own ordinary queues. Urgent safety STOP/checkpoint may interrupt normal work.

## Resume and migration

Reusable topology/session templates remain in `docs/spawn/`, `docs/TEAM_STATE_SCHEMA.md` and
`docs/SESSION_COMMS.md`; ERP-specific transition requirements are tracked in ERP issue #1558.

After restart or compaction, resume from the latest canonical checkpoint and reconcile stale HOLD.
Migration from ERP preserves old task ID → role → worktree/branch/PR → unfinished checkpoint → new
owner. Nothing unfinished is marked done. Archive only after successor ACK and PM handoff; PM is
archived last. GitHub remains technical decision truth; the ledger tracks delivery/execution state.

## Enforcement inventory

| Capability | Status |
|---|---|
| SQLite ledger commands (`enqueue`, `claim`, `lease`, `ack`, `start`, `renew`, `complete`, `priority`, `recover`) | IMPLEMENTED in `packages/communication-ledger`; local tests/validation available |
| Automatic wake / Codex task APIs | NOT_IMPLEMENTED |
| Lease/no-duplicate writer | IMPLEMENTED for ledger writes only; filesystem/process fencing NOT_PROVEN |
| Negative tests (busy, failure/restart, duplicate, stale approval, missing ACK, blocked, handoff) | Package tests/validation exist; Cairn adapter acceptance NOT_RUN |
| Cairn integration adapter/permissions | PROPOSED / NOT_PROVEN |

## Resource policy and registry template

Select the smallest adequate model/effort by risk, not title; escalate only after a measured failure
or concrete ambiguity. Use compact summaries, targeted reads, checkpoint references, no unchanged
polling and no duplicate full suites. Verify model availability when used; do not invent token
budgets. Every registry/handoff records: rule version, parent/child task IDs, role, scope, owner,
worktree/branch, base/head, authority, model/effort, expected output, stop condition, checkpoint,
evidence and resume-after-compaction readback.

Implementation handoff: the Cairn platform owner should bind this existing SQLite package through a
single adapter/dispatcher and explicit permissions, then run the negative-test matrix. This document
adds no deploy gate and does not claim the adapter exists.

## Readiness and cutover checklist

- [ ] Ledger owner links the reviewed standalone package/adapter PR and exact source/test head.
- [ ] Negative tests pass for busy retention, send failure/restart, duplicate event, stale approval,
  missing ACK, blocked recipient, successful handoff and duplicate-writer prevention.
- [ ] Automatic wake status and permissions are recorded honestly; no wake guarantee is inferred.
- [ ] Every unfinished ERP task has an old→new handoff with successor ACK; no invented replacement ID.
- [ ] PM confirms cutover readiness only after package review/test and successor ACK; PM archives last.
- [ ] Production remains independent and is not blocked by this Cairn preparation.

### Old → new handoff template

`old_task_id | old_role | old_worktree/branch/PR | unfinished_checkpoint | successor_task_id (TBD until created) | successor_owner | rule/model/effort | authority | evidence | successor_ACK | archive_status`

An empty successor field means `TBD`, not complete. Preserve blocked/unverified work and all linked
history until the successor has acknowledged the checkpoint.
