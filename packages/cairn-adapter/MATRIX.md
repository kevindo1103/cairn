# Issue #10 negative matrix

Canonical requirements: issue #10 and PR #9 comment 5664645871. The current published
checkpoint names the required cases but does not contain a numbered 16-row table.
The following explicit 16 groups map those requirements for review; PM/QC must confirm
this mapping against any separately held matrix. They are tests `test_01` through
`test_16` in `tests/test_adapter.py`, using the actual vendored ledger and TEST DBs.
Denied adapter requests compare complete logical SQLite proofs for zero writes.

| # | Rejected condition / proof |
|---|---|
| 01 | Recipient impersonation, actor injection, worker registry write, owner used as worker |
| 02 | Stale registry CAS/revision, stale generation, rotated credential/event provenance |
| 03 | Missing command, wrong scope and wrong canonical event state despite same principal |
| 04 | Stale head; caller checkpoint fallback rejected; fresh owner checkpoint supersedes old event |
| 05 | Unavailable Git/GitHub authority rejects reads and transitions without fallback |
| 06 | Changed manifest/rule/scope binding denied (also real-Git verifier mismatch tests) |
| 07 | Conflicting duplicate event and duplicate claim; two competing dispatchers produce one lease |
| 08 | Duplicate/stale successor assignment and successor cycle |
| 09 | Busy recipient retains queue and attempt count; clearing busy permits claim |
| 10 | Expired unconfirmed worker stays BLOCKED and retains slot; OS write still succeeds |
| 11 | Stolen delivery/worker token and token reused after completion |
| 12 | ACK without reconciliation and ACK after registry revision changes |
| 13 | Failure persisted through reopen; no uninspected retry; second failure is terminal BLOCKED |
| 14 | Missing ACK times out; exhausted attempt cannot be resumed from UI-style state |
| 15 | Retirement denied without all four conditions; quiesced predecessor cannot acquire work |
| 16 | Exact backup/restore including nonempty WAL; wrong project, overwrite and altered snapshot refused |

Additional tests prove registry CAS serializes with verification/claim, cross-scope
reaping rolls back, quiesced source cannot obtain delivery, PM-last requires other
predecessor drain, and changed package bytes reject before mutation. Real Git tests
check dirty/untracked work, remote repository, local/remote head/base/tree, plan,
manifest/rule digests and versions, scope, malformed/unavailable API and mid-read movement.
