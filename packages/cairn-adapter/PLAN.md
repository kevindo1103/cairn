# Issue #10: principal-bound adapter

Owner: existing Codex_Ledger task 01a08774-2524-7553-b951-35e9ce8de283.
PM authorized implementation in a separate Cairn branch on 2026-09-14.
Base: PR #9 c496cc5690ba4e1e2825fe07aa6b2d2f6ad2572f (provisional package 0.1.0).
Branch: codex/cairn-principal-adapter. Exclusive paths: packages/cairn-adapter/**.
Canonical contract: issue #10 and PR #9 comment 5664645871.

Implement a library for a separately trusted host, with no activation/server/hooks.
Worker bearer credentials select identities; requests cannot supply actors, registry,
bindings, or authority. A distinct owner credential controls registry snapshots with
CAS and monotonic generations. Store registry/config/reconciliation metadata in the
existing ledger config table, in the same project SQLite DB. Reuse ledger methods in
one encompassing transaction so authorization and mutation cannot race registry CAS.

Resolve Git and GitHub afresh from owner-bound configuration for every authority-bearing
command. Refuse unavailable/changed repository, base/head/tree, manifest, rule, plan,
or path scope. Derive checkpoints only from that verification. ACK requires a durable
reconciliation of the exact event, principal generation, registry revision and binding.
Ledger tokens remain subject to authenticated owner checks. Preserve terminal BLOCKED
attempts and slot retention after unconfirmed worker expiry.

Retirement is a read-only assessment: completed HANDOFF plus active successor generation,
quiesced predecessor and zero drain. No retirement/authority flip operation is exposed.
Recovery uses SQLite backup API to new destinations with logical snapshot/digest/high-water
comparison; never overwrite a live database. One fixed ledger.sqlite per project root.

Validation: 16 named negative groups plus happy path, transaction race, verifier and
backup/restore tests, all in synthetic temporary projects. Publish exact test environment,
base/head and separate draft PR. No changes to packages/communication-ledger or PR #9
docs/workflows. Final acceptance remains pending accepted package version/tag and adapter QC.
Automatic wake NOT_IMPLEMENTED; filesystem/process fencing NOT_PROVEN.
