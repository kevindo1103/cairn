# Historical issue #10 proposal: separate PM succession package

Superseded for source preparation by issue #15's separately versioned core and
adapter candidates. See PM_SUCCESSION_V020.md for current implementation and
acceptance gaps. The following records the pre-implementation v0.1.0 boundary.

Current package: communication-ledger 0.1.0, communication-ledger-v0.1.0,
merge f31726234c43c2ded4716c0998a8e4475ad25c19.

The package binds config.pm_task on initialization, refuses later constructor rebinding,
and uses that immutable identity for STOP, urgent priority and stopped-worker release.
Moving that identity in the adapter would silently change the accepted core contract.
Therefore this adapter refuses logical flip/retirement when the predecessor role is PM.
It does not write config.pm_task, patch Ledger._pm, or invent a second PM truth source.

Proposed separately authorized package PR: bump to a newly reviewed version (candidate
0.2.0, subject to PM approval) and add one explicit audited CAS operation for PM identity
rotation. Bind expected old PM, target successor, generation/registry checkpoint and
accepted handoff/recovery proof in one package transaction; permanently fence old PM
commands and preserve the old identity in history. Include old-red/new-green tests for
old-PM STOP/priority/release refusal, stale approval/retry/restart and exact recovery.

This is a proposal only. No package change, new package PR, merge, migration or activation
is performed. Worker/Lead logical transition rehearsal can be reviewed independently;
full PM succession acceptance stays blocked on the separate core version decision.
