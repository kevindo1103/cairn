# PM succession source candidate 0.2.0

Issue #15. The bootstrap `config.pm_task` remains immutable. Schema 2 adds
append-only `pm_authority` rows in the same project SQLite database. The latest
revision selects the PM for existing privileged core commands. A former PM task
identity cannot become PM again.

`Ledger.succeed_pm` is a trusted host library operation, deliberately absent from
the generic CLI/MCP command allowlist. It requires a current-PM/epoch CAS,
completed fresh HANDOFF with exact predecessor and successor, checkpoint revision,
positive registry generation bindings, registry revision, reviewed proof digest,
evidence, and zero outstanding events, leases and worker slots involving either
PM. The authority row and history receipt commit atomically. An enclosing adapter
transaction can commit its owner-approved registry generation flip with that row.

The core epoch revision and registry principal generations are distinct. The core
records registry proof bindings; the adapter must authenticate the host principal,
validate those generations, perform owner approval and enforce PM-last ordering.
The trusted core library does not establish OS identity or stop external writers.

Schema 1 and unknown existing schemas are refused before schema/journal changes.
No automatic upgrade is provided. A future offline migration must take a verified
SQLite-consistent backup into a new path, bind old/new package and schema hashes,
preserve bootstrap identity/history, explicitly migrate adapter metadata, and
rehearse restore before separately authorized activation. Existing live database
migration and rollback acceptance remain **NOT_PROVEN**. New schema-2 fixture
backup/reopen checks are source evidence only.

Release tag `communication-ledger-v0.2.0` is planned, not created or accepted here.
No install, registration, task creation, live succession, retirement or ERP action
is part of this source PR.
