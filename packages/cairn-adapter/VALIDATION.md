# Issue #10 validation — 2026-09-14

This is the initial checkpoint record. Current base/reconciliation and terminal test
evidence are recorded in ACCEPTED_PACKAGE.md; the original counts below remain historical.

- Owner task: `01a08774-2524-7553-b951-35e9ce8de283` (Codex_Ledger).
- Branch: `codex/cairn-principal-adapter`.
- Exact provisional base: `c496cc5690ba4e1e2825fe07aa6b2d2f6ad2572f` (PR #9).
- Tested implementation commit: `51aad0418e6fb05a344bf8e587979b65bbdbfe14`.
- Effective paths: only `packages/cairn-adapter/**`.
- Dependency version: communication-ledger `0.1.0`, package Git tree
  `d21f0346b18f01f0bab41566200db88b6ac78d3a`; module content hashes in package.lock.json.

## Observed checks

Windows sandbox, bundled Python 3.12.14, system Git. No installation or activation.

| Check | Result |
|---|---|
| `python packages/cairn-adapter/run_tests.py` | 27 run, 27 passed, 0 skipped; 20.808 seconds |
| 16 negative matrix groups | All passed using real package transitions and temporary SQLite DBs |
| 5 supplemental adapter checks | CAS/claim race, scope reaping rollback, source freeze, PM-last drain, changed-package refusal passed |
| 6 verifier checks | Real local Git and deterministic GitHub API fixtures passed |
| Sibling package `python -m unittest discover -s tests -v` | 30 run, 29 passed, 1 MCP skip; 4.476 seconds |
| SQLite backup/restore | Stable logical proof equal, nonempty WAL included, receipts/slots/history/terminal states preserved |
| Scope and whitespace | `git diff --check` passed; no changes to package-owned source, docs or workflow files |
| Existing registered standalone package | Unchanged at `37cf66fd25cc703465bbd4524fc49ee5cbf80dbf`, clean |

The MCP skip is `Optional MCP SDK not installed`; it is not an MCP pass. Package
source here already contains schema-version refusal and version-contract tests,
so older counts in PR #9's description are not the current local suite count.

The source fixture verifier is injected only by the trusted test host. Worker commands
cannot supply it. The separate real-Git tests execute Git in temporary repositories;
GitHub HTTP responses are explicit fixtures. Live GitHub authority verification through
the adapter is NOT_PROVEN: this shell cannot read its GitHub CLI credentials/config.
Fresh PR #9 and issue #10 metadata were independently read through the GitHub connector.

## Acceptance still pending

1. PR #9 accepted/versioned package, rebase/rebind to that exact immutable version and
   repeat affected adapter checks. The pin is explicitly provisional, not acceptance.
2. Independent adapter QC and confirmation of the documented 16-group mapping: the
   canonical PR comment names scenarios but supplies no numbered 16-row table.
3. Zero-skip MCP package CI/evidence in the package owner's lane.
4. A separately reviewed host identity transport with protected process, DB, executable,
   credential and canonical-root ownership before any future activation.

Automatic wake: **NOT_IMPLEMENTED**. Filesystem/process fencing: **NOT_PROVEN**.
No merge, install, hook/MCP restart, topology migration, authority flip, session
retirement, live ledger write or ERP/production mutation was performed.

GitHub source publication (`create_tree`) and the Docs and PM callback tools were
rejected by automatic approval review with
`MCP tool call requires approval, but approval policy is never`. This is an environment
delivery blocker: no remote branch/PR was created and neither recipient received the
attempted callback. A local patch, source ZIP, PR body and manifest provide the complete
reviewable handoff. They do not count as remote publication or PM acceptance.

Final read-only GitHub check: PR #9 remained Draft/open at the same provisional base
`c496cc5690ba4e1e2825fe07aa6b2d2f6ad2572f`. No accepted package tag/version was observed.
