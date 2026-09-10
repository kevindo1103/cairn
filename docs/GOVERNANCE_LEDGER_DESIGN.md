# Cairn Governance Ledger — Design Handoff

> Status: design/proposal only (2026-09-10). No runtime enforcement or automatic wake is installed.

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

After restart or compaction, resume from the latest canonical checkpoint and reconcile stale HOLD.
Migration from ERP preserves old task ID → role → worktree/branch/PR → unfinished checkpoint → new
owner. Nothing unfinished is marked done. Archive only after successor ACK and PM handoff; PM is
archived last. GitHub remains technical decision truth; the ledger tracks delivery/execution state.

## Enforcement inventory

| Capability | Status |
|---|---|
| Durable ledger schema/dispatcher | PROPOSED / NOT_PROVEN |
| Automatic wake | NOT_IMPLEMENTED |
| Lease/no-duplicate writer | PROPOSED / NOT_PROVEN |
| Negative tests (busy, failure/restart, duplicate, stale approval, missing ACK, blocked, handoff) | PROPOSED / NOT_RUN |
| ERP ledger/MCP reference | EXISTING PACKAGE — link/inspect, do not copy blindly |

Implementation handoff: the Cairn platform owner should choose durable storage and one dispatcher,
define adapters/permissions, then run the negative-test matrix. This document adds no deploy gate.
