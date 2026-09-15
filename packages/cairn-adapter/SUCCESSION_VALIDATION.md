# Issue #15 source validation

Core binding: `ec4004d59369392ebf6c49c8f6c15c733b3434ac` (0.2.0, schema 2).
Old baseline: main `5526443b0b4f2e6cdf10cbd37f6ccc87b9a69a99` (accepted v0.1.0 core/adapter).
Python 3.12.14. Tests use fresh temporary synthetic project databases only.

- Same five succession tests on the old baseline: 5 expected rejections of a
  pending PM successor at the immutable unique-PM registry guard.
- New focused suite: 5/5 passed, zero skips.
- Full adapter runner: 41/41 passed, zero skips (48.702 seconds).
- Preserved original 36 contracts, including actual temporary Git repositories
  with fixture GitHub responses; this is not live GitHub authorization evidence.
- Added owner-reviewed PM flip/retirement, pending-PM command restriction, old
  generation/revision/token refusal, stale owner approval, unavailable verifier,
  PM-last refusal, rollback of core epoch plus registry after an injected failure,
  exact PM receipt recovery and rejection of a pre-flip proof for a post-flip copy.

Read-only Codex snapshot: 26 relevant task candidates from pinned plus latest 50
unpinned tasks. Raw candidate metadata is a local review artifact. No trusted
registry is produced. Session identity, successor/ACK, canonical checkpoint/base/
head, authority generation, unfinished-work readback, runtime and host/process
evidence remain unknown. The listing is bounded and excludes archive inventory;
MigrationSnapshotComplete=false and CUTOVER_READY=false.

GitHub Draft publication/terminal CI were not obtained: the GitHub mutation tool
rejected creating the core tree with `requires approval, but approval policy is
never`; local network Git fetch also cannot connect. The PM callback tool returned
the same approval error. Existing CI runs the old adapter with the core-only PR,
so that old lock is expected to refuse core 0.2.0 until the separately reviewed
adapter is integrated. The stacked adapter target branch is outside the current
workflow branch filter. No workflow files were modified.

PackageAccepted/AdapterAccepted=PENDING. RecoveryProven is synthetic-copy evidence
only; schema-1 migration, current host fencing and production acceptance remain
NOT_PROVEN. No live activation, install, registration, quiesce, retirement, archive,
ERP or production action occurred.
