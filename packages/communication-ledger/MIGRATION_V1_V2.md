# Offline copy preparation: schema 1 to schema 2

Issue #15. This host-only library prepares a new isolated copy; it does not
upgrade or activate a live database. The raw CLI/MCP/worker allowlists do not expose
these operations. `Ledger(existing_schema1)` continues to refuse implicit migration.
Core candidate version remains 0.2.0; no accepted 0.1.0 tag is changed.

## Contract

1. `comms_ledger.migration.inspect_v1(source)` opens SQLite `mode=ro`, sets
   `query_only`, and holds one read transaction. It returns the resolved path,
   stable file identity, exact known v1 schema fingerprint, logical snapshot digest,
   bootstrap PM, history high-water and opaque extension-config digest. It does
   not attest host isolation. Preserve this proof independently before copying.
   Read-only SQLite can still use locking/shared-memory sidecars to read WAL;
   preservation checks concern database schema/data, not absence of filesystem locks.
2. `migrate_copy(source, new_destination, expected_proof, evidence)` requires the
   exact proof and a host evidence reference. Parents must already exist in a
   host-controlled isolated directory. The destination must never have existed;
   links, junctions/reparse paths, multiple hardlinks, unknown file identity and
   existing destinations are refused. Inputs and output directories must be
   inaccessible to untrusted processes; path inspection is not OS fencing.
3. Source schema must match frozen core 0.1.0 DDL from main
   `5526443b0b4f2e6cdf10cbd37f6ccc87b9a69a99` (fixture `tests/fixtures/schema1.sql`).
   Fingerprint: `ab7b06b15fc21495b39232ffb6d1599a115f200fdbcbc27717d0df62b34650e5`.
   Unknown objects, corrupt/inconsistent data, missing PM, malformed payloads,
   stale queued checkpoints, SENT/ACKED/STARTED, capability/deadline residue,
   busy recipients and retained worker slots are refused. Resolve these under
   separate authority; migration does not clear or repair them.
4. SQLite backup copies the retained snapshot, including WAL, to the exclusively
   created destination. A single destination transaction adds the shared schema-2
   PM table/triggers, inserts revision 0 for the unchanged bootstrap PM, updates
   only `schema_version`, and appends one `SCHEMA1_COPY_PREPARED` audit row. Existing
   schema objects and all original data/config/history/sequence values are checked
   for preservation before adding that new row. Original history rows/sequence
   identities are never rewritten; the history sequence advances for the new audit.
5. A separate fresh source snapshot and path-identity check before receipt/commit
   reject observed concurrent changes. Read-only access cannot stop a later external
   writer; the check is not an ongoing quiescence or host-fencing guarantee.
6. The returned receipt is **PREPARED_ONLY**, `live_readiness=false`,
   `adapter_rebound=false`. It binds source proof, target version/schema/module
   digest, destination identity, output history high-water and full output digest.
   The audit row binds the prepared content digest *before its own insertion*;
   the returned full output digest includes the audit row. This avoids a circular
   self-hash. Both digest definitions include all relevant schema and table data.

## Failure and recovery

Failures before output creation write no destination. After creation, errors or
crashes leave that exact output path quarantined for host inspection; it is never
overwritten, automatically retried or promoted. DDL/data/audit changes roll back
together on an interrupted transaction. A crash after commit can leave a valid
PREPARED_ONLY copy without a returned receipt; this still grants no live authority.
No receipt claims COMPLETE or live readiness. Retain the independent source proof
and use a new isolated destination for another separately reviewed attempt.

A synthetic backup/reopen of schema 2 validates data/receipt persistence only.
Real host restore, rollback protection and prevention of stale authority activation
remain separate mandatory readiness gates.

## Adapter and operational boundary

Opaque adapter config is copied byte-for-byte, including old package binding,
owner/grants and registry generations. It is not interpreted as new authority.
The old pin must fail closed against the new core modules. A separately accepted
adapter migration/rebind must validate the full old/new package and registry
contract before the copy can be used by adapter 0.2.0. Updating a hash alone is not
adapter migration acceptance.

This change provides no transport, automatic wake, identity provider, restricted
worker process, live successor, quiesce, retirement/archive, installation or ERP
operation. Same-user unrestricted sessions are not fenced by registry tokens.

## Focused verification

The baseline contract suite fails to import the absent migration module. New
synthetic tests cover empty/queued/completed copies, WAL, preserved history and
adapter metadata, schema2 reopen and backup copy, exact-proof mismatch, file
identity/aliases, malformed schema/corruption, in-flight/retained work, destination
collision, external source commit, injected failures, a real crashing subprocess,
and concurrent claims of one destination. Windows reparse rejection is tested at
the predicate boundary; a real POSIX symlink is additionally tested on POSIX. This
does not claim a privileged Windows sandbox or real-host fencing test.
