# Canonical 24-case extension plan

Base main f31726234c43c2ded4716c0998a8e4475ad25c19; literal package version 0.1.0,
tag communication-ledger-v0.1.0. Owner Codex_Ledger; only packages/cairn-adapter/**.

Extend the existing adapter registry, ACL and evidence gates; do not change any core
ledger method/schema/transition. Registry facts include pending/active/quiesced/retired,
full host-owned identity/work binding and inventory. Add a required host identity
resolver; unavailable identity refuses mutation and remains NOT_PROVEN. Keep separately
authenticated owner CAS/audit. Add host-attested complete-handoff review plus durable
readback; start and complete must reconcile against current authority.

Implement PM-only logical control operations for synthetic review drills: separately
owner-approved flip changes registry generations and state atomically in the existing
DB. It creates no task, starts no service and archives nothing. Retirement is a logical
registry transition only, gated by the full invariant. Real use remains NOT_AUTHORIZED.

Interpret 'completed before quiesce' as retirement/flip rejection: the specified order
explicitly has handoff complete before predecessor quiesce. Ordinary ledger completion
does not itself quiesce the predecessor. Record this distinction in the 24-case matrix.

Core-change STOP: the package permanently binds pm_task at initialization. Moving the
configured PM identity would alter that core contract. Refuse PM succession/retirement
in this adapter and propose a separately reviewed version-bumped package change; do not
rewrite pm_task or pretend a registry role update changes core PM authority.

Validate 24 named negative groups, restored-DB execution, projections and read-only
snapshot preparation; publish Draft PR if the environment permits. Preserve explicit
NOT_PROVEN identity/process enforcement and NOT_IMPLEMENTED wake/transport labels.
