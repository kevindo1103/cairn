# Canonical 24-case matrix

Each numbered group is a real test against the unchanged v0.1.0 ledger in a temporary
SQLite project. `rejected_zero_write` compares the complete logical DB proof before and
after refusal, including history/config. Host identity and GitHub network responses are
explicit synthetic fixtures, so their deployment enforcement remains NOT_PROVEN.

| Case | Test / refusal proved |
|---|---|
| 01 | Impersonation, actor injection, worker registry write, owner/principal credential separation |
| 02 | Stale registry CAS/revision/generation, credential rotation and old event provenance |
| 03 | Wrong command, literal scope, canonical event state |
| 04 | Stale approval base/head, caller checkpoint fallback, superseded approval |
| 05 | Git/GitHub unavailable: fail closed with zero writes |
| 06 | Changed rule/manifest/scope authority binding |
| 07 | Duplicate event and concurrent duplicate claim: one lease |
| 08 | Duplicate/stale successor and successor cycle |
| 09 | Busy target retained with no consumed attempt |
| 10 | Expired worker not confirmed stopped retains slot; Lead/unauthorized release denied; PM plus separate host approval required |
| 11 | Wrong target/owner and stolen/completed lease tokens |
| 12 | ACK without current reconciliation or with stale revision |
| 13 | Restart persistence; uninspected retry denied; bounded retry exhaustion |
| 14 | SENT without ACK times out; terminal BLOCKED cannot resume from projection |
| 15 | Retirement requires all four terms; quiesced mutation and inactive successor denied |
| 16 | SQLite-consistent nonempty-WAL backup; exact restore; wrong project/overwrite/changed backup denied |
| 17 | Forged PM/Lead rights, worker claim, forged STOP, absent/mismatched trusted host identity |
| 18 | Pending successor cannot acquire ordinary work; separate approval required for atomic flip; old predecessor/generation and actual old token rejected; duplicate flip/resurrection denied |
| 19 | ACK without START cannot complete; START without current reconciliation denied |
| 20 | COMPLETED without host-reviewed full inventory/readback evidence; inventory/blocker change denied |
| 21 | HANDOFF complete before quiesce does not authorize flip; nonzero ownership ambiguity/drain denied |
| 22 | Projection mismatch warns without canonical mutation; missing snapshot identity/checkpoint/ACK/runtime remains gaps |
| 23 | Unsupported core schema, adapter metadata schema, bound package identity or changed package source fails closed |
| 24 | Reopen restored DB, compare all durable truth, reconcile, execute and complete; high-water advances only with new work |

Case 21 follows the directive's explicit order HANDOFF complete -> predecessor quiesce
-> flip. Completion is not retirement permission. Core PM succession remains a separate
version-bumped package proposal; this adapter must not rewrite the immutable pm_task.

Five supplemental adapter tests cover package pin drift, cross-scope timeout rollback,
PM-last drain, quiesced source, and CAS/claim serialization. Seven verifier tests use
real temporary Git repositories and mocked GitHub API responses for head/base/tree,
path cap, rule/manifest/config, issue/PR body/head evidence, dirty worktree and API failure.

Totals: 24 numbered groups + 5 supplemental adapter + 7 verifier = 36 test methods.
Terminal results and exact source identity are in CONTRACT24_VALIDATION.md.
