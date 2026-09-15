# Adapter bound to accepted communication-ledger v0.1.0

- Owner: Codex_Ledger, Cairn issue #10.
- Branch: `codex/cairn-principal-adapter`; PR target: `main`.
- Exact main/package base: `f31726234c43c2ded4716c0998a8e4475ad25c19` (merged PR #9).
- Annotated tag: `communication-ledger-v0.1.0`.
- Tag object: `065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f`, targets the exact base above.
- Tested adapter head: `da5cc6bab170d40625afc917b1d1e27fb40fabe3`.
- Package tree: `d21f0346b18f01f0bab41566200db88b6ac78d3a`, unchanged.

The GitHub tag reference, annotated tag object, merged PR #9 and current main ref were
independently read. Missing Git objects were imported via read-only GitHub API and
verified against their exact Git object hashes before rebasing the adapter branch.
The sole upstream tree change relative to the previous base is the PR quality workflow.
No package semantic drift or adapter file overlap exists. All module source hashes and
the package lifecycle are unchanged. No duplicate database or state machine was added.

The adapter package lock now records the accepted version, tag object and merge commit.
Package acceptance is complete; independent adapter QC remains pending. Earlier
VALIDATION.md and RECONCILIATION.md are historical checkpoints, not current package status.

## Terminal zero-skip evidence

Bundled Python **3.12.14**, Windows, command:
`python packages/cairn-adapter/run_tests.py`.

**27 run, 27 passed, 0 skipped, exit 0, 22.710 seconds** at the tested head above.
The runner fails on any skipped test. The raw output is in `evidence/v010-adapter-tests.txt`.
Coverage includes 16 negative groups, five additional adapter invariants and six
real-local-Git/fixture-GitHub verifier checks. No live project database is used.

Exact-base path check and `git diff --check` passed. Only `packages/cairn-adapter/**`
differs from main. Ledger package source, canonical docs and workflows have zero edits.
The test result is adapter evidence; it does not recast historical MCP skips as passes.
Package CI acceptance was supplied by PM with the canonical merge/version decision.

Automatic wake remains **NOT_IMPLEMENTED**. Filesystem/process fencing and live adapter
GitHub E2E remain **NOT_PROVEN**. No live activation, authority flip, successor creation,
retirement, archive, merge, or ERP/production mutation is authorized or performed here.
