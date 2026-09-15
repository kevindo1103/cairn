# Owner-reviewed PM succession source candidate

Issue #15. Adapter version 0.2.0 depends on core 0.2.0, schema 2. The package lock
binds exact candidate commit `ec4004d59369392ebf6c49c8f6c15c733b3434ac`, package tree
`75665794d2f19d0e924c08e9c97a03beb27c859f`, and LF-normalized module hashes.
`communication-ledger-v0.2.0` is a planned tag; its object is null. Package and
adapter acceptance remain PENDING. The version bump is not a release acceptance.

## Transition contract

The registry retains the immutable bootstrap PM and all historical PM records.
There is one current PM selected by the core authority epoch. Only its mapped
pending successor can hold another future PM role. Historical PM records must
remain quiesced or retired; owner CAS cannot make them active or change their role.
Registry updates and each adapter transaction check this relationship.

The current PM sends a HANDOFF to its pending PM successor. Existing reconcile,
ACK, START and separately owner-reviewed COMPLETE requirements still apply. The
host then quiesces the predecessor with zero-drain evidence. At this point the
pending successor may only review and request `authority_flip` for its own completed
PM HANDOFF, subject to the same host identity, registry generation/revision, ACL,
scope, state and fresh Git/GitHub checks. It gains no general PM authority while
pending. A separate owner attestation must match the full current review, including
the current core PM epoch.

The flip requires every other registry-mapped predecessor already retired. It
calls the core's CAS with the exact source/target, generations, checkpoint revision,
registry revision, review digest and evidence, then advances both registry principal
generations and activates the successor, all within one SQLite transaction. A
failure after the core write rolls back the core epoch, registry and audit together.
Actual PM retirement requires the committed core succession and another separately
reviewed owner attestation. These are library operations demonstrated only on new
temporary fixture databases; no real task or external process is changed.

## Recovery and migration boundary

SQLite-consistent recovery proofs include the latest PM authority epoch/receipt,
immutable bootstrap PM, package binding, registry revision/generations and complete
logical data/schema digest. A restore requires the exact retained proof and project;
an old pre-succession proof cannot accept a post-succession backup. Exact snapshots
can be copied and reopened at new paths only. Reopening an old valid backup does not
establish that it is the latest live authority; external rollback/activation fencing
remains NOT_PROVEN and must be checked before any activation.

There is no schema-1 or prior-adapter in-place migration. A future offline copy
migration must reconcile old core/adapter package bindings, owner registry and PM
epoch, validate the current task inventory and rehearse restore. The read-only
Codex inventory is a local review artifact, not a trusted registry or public source
fixture. Missing successor IDs/ACKs, session identities, checkpoints, runtime and
host/process evidence remain explicit gaps. MigrationSnapshotComplete is false.

No live install, registration, successor creation, authority flip, quiesce,
retire/archive, ERP change or production action is authorized by this PR.
