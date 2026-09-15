# Companion adapter copy migration — PREPARED_ONLY

This host-only API follows the separately proved core schema-1 to schema-2 copy.
It never changes that core-proved source, mounts a worker command, or activates a
project. Candidate core pin is commit `39950de062ef085ed4e0ba5f87e3b48d6183d551`,
package tree `b207445cda7231917df89d210948a5fc19d0e923`, with exact module hashes.
The planned v0.2.0 tag object remains null and package/adapter acceptance PENDING.
This checkpoint supersedes the earlier candidate pin recorded in README and
PM_SUCCESSION_V020.md; the current package.lock.json and this migration contract
identify the dependency used for this source candidate.

## Inputs and refusals

`cairn_adapter.migration.migrate_copy(source, new_project_root, expected_core_proof,
project=..., owner_token=..., expected_registry_revision=..., evidence=...)`
requires a new isolated destination root already created/protected by the host.
Only its never-existing `ledger.sqlite` is created. Reparse/link/alias and existing
destination guards are reused from the exact pinned core.

The independently retained core receipt must be PREPARED_ONLY, bind this resolved
source/file identity/full snapshot/history high-water, and match its final core
migration audit and the pinned core module content. Schema must be 2, bootstrap
PM authority must be revision 0, and the old adapter must have the exact accepted
0.1.0 package binding and registry schema 2. No caller-provided replacement pin
or inferred project/owner/CAS is accepted. Canonical metadata, source project,
separate owner credential, exact registry revision, all entries and the legacy
unique PM identity are validated. Incompatible registry records are refused rather
than repaired. Future/ambiguous reconcile or attestation revisions are refused.

## Allowed destination delta

A readonly SQLite snapshot (including WAL) is backed up into an exclusively
created new destination. One transaction changes only the package metadata to
the pinned new package and increments registry revision exactly once. Task/session
IDs, credentials, role/state/grants, principal generations, successor mappings,
bootstrap/core authority, events, checkpoints, old history and all other config
are preserved. A final fresh source validation rejects observed concurrent changes.
An `ADAPTER_COPY_PREPARED` audit is appended atomically; failures roll back metadata
and audit together. No source repair, grant promotion, credential rotation or
logical authority flip is part of migration.

Old reconcile/attestation records remain historical evidence with their original
revisions. They cannot authorize commands at the new registry revision; the host
must obtain fresh readback/owner approval through existing controls. Existing
completed-proof content is not rewritten to simulate new acceptance.

The audit binds source core proof, old/new package, project, before/after registry
revision, unchanged entries digest and prepared content digest before the audit.
The returned receipt includes the complete post-audit recovery proof and is
PREPARED_ONLY, `live_readiness=false`, `activation_authorized=false`. Host fencing
is NOT_PROVEN. Failed/crashed copies are quarantined; never overwrite or retry
in place. A crash after commit can leave a prepared copy without a returned
receipt, which still has no live authority.

## Verification and remaining gates

Synthetic fixtures use frozen accepted v1 DDL, explicit old package/owner/registry
metadata, a real core-copy proof, and separate adapter-copy destinations. Tests
cover Store/Adapter reopen, source and history/ID/grant/generation preservation,
old revision/generation/readback/approval refusal, owner/project/CAS/package/proof
mismatch, incompatible registry/future approval, destination collision, rollback,
a real crashing subprocess, concurrent claims, WAL source drift and recovery
proof equality. A migrated PM fixture separately exercises owner-reviewed PM
succession and stale token refusal.

No adapter test result establishes OS/process isolation or actual transport/wake.
Same-OS-user unrestricted sessions remain outside the claimed fencing boundary.
The host proposal requires a separately authorized target/service identity/worker
sandbox and real identity/transport integration. Final exact-base CI, package
acceptance, complete inventory, host/process fencing, runtime and recovery evidence
remain prerequisites; no PR merge, tag, host install or live activation occurs here.
