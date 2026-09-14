# Cairn adapter — canonical 24-case contract

Review-only library for issue #10. Base main/package merge:
`f31726234c43c2ded4716c0998a8e4475ad25c19`; package version `0.1.0`, tag
`communication-ledger-v0.1.0`, annotated object
`065fd4c19a952f1af2f5c0a04e31e7fe462e1d7f`. The package tree remains
`d21f0346b18f01f0bab41566200db88b6ac78d3a`. Only `packages/cairn-adapter/**`
is owned by this branch. No core lifecycle/schema changes or second store.

Current contract: this README, MATRIX24.md and CONTRACT24_VALIDATION.md. Older
VALIDATION.md, RECONCILIATION.md and ACCEPTED_PACKAGE.md are historical checkpoints.

## Trust and authorization

The host must protect the interpreter, imported code/package lock, Git/GitHub
executables, canonical project root, database and credentials. Workers may receive
only a remote facade to Adapter.execute; never Store/Owner/verifier objects, host
interpreter access, database permissions or raw ledger CLI/MCP. This source package
installs no such transport. Principal enforcement remains NOT_PROVEN until the actual
host identity boundary is independently accepted. A missing/unavailable host identity
resolver refuses requests; credentials must match external host task/session/generation
and the separately owned canonical registry. The synthetic resolver in tests is not
proof of a real host identity provider.

Registry records require project/repository, task/session ID, generation, role, scopes,
authority/grants, worktree, branch, rule/config version, pending/active/quiesced/retired
state, parent, owner, expected output, stop condition, successor, quiescence and a full
handoff inventory. Owner.replace requires a distinct owner credential, exact revision
CAS and append-only audit. A principal cannot supply its actor, registry, role, scope,
generation authority or verifier through command arguments. Generation/credential
rotation is monotonic. Owner CAS cannot activate a pending successor, resurrect a
quiesced/retired predecessor or silently delete records. Bootstrap is for a new TEST
project only. Existing older adapter metadata is refused, not silently migrated.

ACL combines authenticated principal, command, literal scope, canonical event state
and generation. Role restrictions are additional ceilings: workers/QC/Docs/Infra only
mutate their own target; PM-only STOP, urgent/cross-team priority, release, flip and
retirement cannot be obtained through an overbroad worker grant. A pending successor
may process only its own HANDOFF readback/ACK/start/complete. It cannot acquire normal
work. Quiesced, retired and stale generations reject. Owner and PM are distinct powers:
PM control operations additionally require a separate host owner's exact attestation.

## Fresh source and full handoff evidence

Each request freshly resolves the owner-bound repository, worktree/branch, local and
remote exact base/head/tree, manifest/rule hashes, rule/config versions, complete path
inventory and GitHub plan decisions. Every changed/renamed path must fit the literal
path cap. Missing/unreachable/ambiguous evidence fails closed. Authority and mutation
share the same SQLite transaction with registry CAS. The package's timeout maintenance
is rolled back if it crosses the authorized scope or event-state grant. External GitHub
and filesystem changes cannot be atomically fenced by SQLite; that remains NOT_PROVEN.

Existing ledger states remain QUEUED -> SENT -> ACKED -> STARTED -> COMPLETED, with
terminal BLOCKED/CANCELLED/SUPERSEDED attempts. SENT records dispatcher receipt only.
ACK, START and COMPLETED require current durable principal reconciliation. Full HANDOFF
completion also requires complete predecessor/successor inventories, exact readback
of unfinished work/PRs/issues/blockers, matching canonical task/event/status evidence,
and no omitted unfinished ledger work. GitHub PR/issue body/state/head references are
freshly rechecked. An authenticated PM can read handoff_review; a separately authorized
host owner attests its full digest. Caller completion evidence must match that exact
attestation. Changes in identity, registry revision, checkpoint, Git/rules, work or
readback invalidate the proof. Ordinary non-HANDOFF package events retain core semantics.

## Logical transition prototype and the PM core STOP

Only synthetic tests invoke the control prototype. No external session API, task
creation, process activation, archive or production operation is called. Control methods
return actions_executed=[] and external_authority_effect=false.

The PM-only authority_flip command requires a pending mapped successor, completed
reviewed HANDOFF, quiesced predecessor, zero drain and separate host attestation. One
SQLite transaction increments both generations, activates the successor and records
old-generation provenance permanently. The predecessor stays quiesced. PM-only retire
additionally checks the active successor generation and writes retired logically; it
never archives a session. Old tokens/generations and resurrection through Owner CAS
are rejected. Source work/rules/inventory changes invalidate completed-handoff eligibility.

RETIRE_ALLOWED = HANDOFF_COMPLETED && successor ACTIVE generation && predecessor
QUIESCED && drain ZERO. Drain covers active mutations, every lease/retained slot,
undelivered handoff, unmapped unfinished work and host-observed ownership ambiguity.
Unknown values cannot count as zero. Conservatively, historical non-COMPLETED ledger
attempts keep drain nonzero even if listed in an inventory; no unreviewed work-remapping
rule is invented. PM-last assessment checks all other registry-mapped predecessors.

Completion before quiescence is permitted by the required HANDOFF-then-quiesce order;
it does not authorize flip/retirement. Case 21 verifies refusal before quiescence and
with nonzero ambiguity. Filesystem/process quiescence still needs external proof.

STOP: core v0.1.0 permanently binds pm_task. PM succession/retirement cannot be enabled
by silently rewriting that key. The prototype explicitly refuses it. See
PM_CORE_CHANGE_PROPOSAL.md for a separately reviewed, version-bumped package proposal.
That package change has NOT been implemented; full PM migration acceptance is blocked.

## Recovery and preparation

One fixed ledger.sqlite under the host-selected project root stores the existing ledger
plus adapter config metadata; requests cannot select another DB. The host must maintain
one canonical root per project. SQLite backup API copies a stable read snapshot including
WAL. Restore only writes a new offline destination after exact proof comparison; never
an existing/live DB. Proof covers schema, accepted package/PM/config binding, registry
revision/generations, checkpoints/revisions, events, high-water mark, history, receipts,
slots, terminal statuses, HANDOFF and a complete logical digest. Tests reopen the restored
DB, reconcile and finish execution. Local recovery drill PASS does not close production
RecoveryProven or stop external workers. Never replay a backup as active authority without
separate reconciliation/authorization.

snapshot_prep.py reads candidate JSON only. Missing task/session/worktree/checkpoint,
successor/ACK or runtime evidence becomes an explicit gap. All rows remain untrusted
projection candidates even when filled. No successor ID is generated, no Store is opened,
and no GitHub projection becomes registry authority. The example includes one known old
task ID and null unknowns; it is not the full ERP inventory. TEAM_STATE projection mismatch
warns and never changes ledger truth; ledger BLOCKED stays terminal even if the UI has a
resumable blocked label.

Run without installation from the Cairn checkout:

    python packages/cairn-adapter/run_tests.py
    python packages/cairn-adapter/snapshot_prep.py packages/cairn-adapter/examples/migration-candidates.json

The runner fails on skipped tests. See MATRIX24.md for the 24 named groups and additional
checks; GitHub verifier tests use explicit fixtures with real local Git. Actual host
identity, live adapter GitHub E2E and filesystem/process fencing remain NOT_PROVEN.
Automatic wake and automatic transport are NOT_IMPLEMENTED. AdapterAccepted and real
RecoveryProven remain NOT_PROVEN pending independent review. Live activation, authority
flip, successor creation, retirement, archive, merge and ERP production mutation are
NOT_AUTHORIZED. Publication is Draft PR only if environment permissions permit it.
