# Canonical 24-case implementation checkpoint

Owner: Codex_Ledger, issue #10. Branch `codex/cairn-principal-adapter`; target main.
Exact base: `f31726234c43c2ded4716c0998a8e4475ad25c19`.
Package pin: version `0.1.0`, tag `communication-ledger-v0.1.0`, tag object
`065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f`, targets that exact merge.
Package tree remains `d21f0346b18f01f0bab41566200db88b6ac78d3a`.
Tested source head: `3ada36b006a74591dbfb4c8d3691f923707e836e`.

## Implemented contract

- Host-owned full registry; separate owner credential, CAS/revision and audit;
  pending/active/quiesced/retired facts with monotonic generation and no resurrection.
- Required external host identity resolver plus principal/command/scope/state/generation
  ACL and PM-only control ceilings. Missing host identity fails closed.
- Fresh Git/GitHub base/head/tree/manifest/path/rule/config/decision verification;
  full canonical work inventory and durable readback before HANDOFF completion.
- Same ledger lifecycle and same project SQLite DB. Start/complete cannot bypass current
  reconciliation. Separately host-approved logical flip/retire prototypes are exercised
  only on synthetic projects; no external session operations are implemented or performed.
- Full retirement/drain guard including ownership ambiguity and old-generation refusal.
- Read-only snapshot gap reporting; projection mismatch warns, never overrides truth.

## Terminal evidence

Python 3.12.14 on Windows, `python packages/cairn-adapter/run_tests.py`:
**36 total, 36 passed, 0 skipped, exit 0, 18.712 seconds**.
24 numbered groups + five additional adapter tests + seven verifier tests.
Raw log: `evidence/contract24-adapter-tests.txt`.

SQLite backup/restore then execution: PASS. The copied and restored logical proof
is identical; digest `abaa38b122abd04f6e2f8a43c8998861f92b3e5ed50310978a6c44bdbf78c874`.
Schema/package/PM config, registry revision/generations, checkpoint revisions,
events/history, receipts, active slots, statuses, HANDOFF and high-water are covered.
After reopening the restored DB and reconciling, the same event reaches COMPLETED;
history high-water advances from 9 to 12. `evidence/contract24-recovery-proof.json`
contains the before/after proofs without credentials or lease tokens.

Read-only snapshot example: PREPARATION_ONLY. Missing session ID, worktree, head,
checkpoint, PR and successor/ACK/runtime evidence are explicit gaps. No successor ID
is generated. `evidence/contract24-snapshot-preparation.json` is a candidate projection,
not a trusted registry or a complete ERP migration inventory.

Exact-base diff/whitespace checks pass. Only `packages/cairn-adapter/**` changes;
`packages/communication-ledger`, canonical docs and workflows are untouched.

## Remaining gates and core STOP

PackageAccepted is CLOSED. AdapterAccepted and real migration RecoveryProven remain
NOT_PROVEN pending independent QC/acceptance. The local recovery drill does not infer
runtime, production or external worker-stop evidence.

Core v0.1.0 fixes pm_task. PM succession cannot be implemented without changing that
contract, so the adapter refuses it and provides PM_CORE_CHANGE_PROPOSAL.md for a
separately authorized version-bumped package PR. No core change has been made.
The required completed-before-quiesce negative case rejects flip/retirement before
quiescence; HANDOFF completion itself follows the directive's stated pre-quiesce order.

Principal enforcement, filesystem/process fencing and live adapter GitHub E2E remain
NOT_PROVEN. Tests use a synthetic host identity provider and explicit GitHub fixtures.
Automatic wake and transport are NOT_IMPLEMENTED. Live activation, topology cutover,
authority flip, successor creation, retirement/archive, installation, merge and ERP
production mutation are NOT_AUTHORIZED and were not performed.

Next gate: publish the separate Draft PR, obtain independent adapter QC, and resolve
the PM package-version proposal before any complete-topology migration acceptance.
