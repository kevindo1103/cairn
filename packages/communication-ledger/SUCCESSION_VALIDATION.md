# Source validation for issue #15

Baseline: main `5526443b0b4f2e6cdf10cbd37f6ccc87b9a69a99` (core 0.1.0).
Python 3.12.14, temporary SQLite databases only.

- Same `test_pm_succession.py` on old baseline: 5 tests, 5 expected missing
  `Ledger.succeed_pm` errors; no unrelated failure in retained final red run.
- Candidate: 5/5 succession tests passed, zero skips.
- Existing core regression `test_ledger.py`: 29/29 passed, zero skips.
- Covered immutable bootstrap/append-only receipt, old PM privilege and token
  refusal with zero-write checks, stale epoch/identity/checkpoint/proof, outstanding
  work, two concurrent succession attempts with one winner, consistent backup and
  reopen preserving the exact authority and history.

MCP SDK test not run locally. CI results are separate. The current CI workflow
also runs the old adapter against the sibling core; that old package lock must
refuse this version. The follow-on adapter PR binds this core separately. Neither
source tests nor the synthetic restore prove live migration, host fencing or
production acceptance. All live changes remain HOLD.
