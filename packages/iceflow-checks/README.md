# Iceflow Checks 0.1.5 — Cairn package for mechanical verification

Imported from the reviewed `iceflow-harness 0.1.2` source into Cairn issue #21.
The existing wheel name and CLI stay `iceflow-harness` for compatibility. This is
NOT a second orchestrator. Cairn Engineering consumes typed reports from this tool.

## Changes from 0.1.2

F1: wildcard imports cause MODEL_COLUMN_UNRESOLVED; `mapped_column(__name_pos=...)`
is resolved or blocked rather than guessed. The constant-name fix stays intact.
SQLAlchemy synthetic regression compares against the installed real library; it
never imports ERP or uses current model create_all to bootstrap a migration test.

F2: demo validates its full output path before exists/mkdir. Refusal leaves the
destination unchanged, including directory inventory. Real Windows junction
regression is included; native results require a capable Windows runner.

F3: delivery verification checks the COMPLETE wheel installation surface,
including top-level `.pth`, modules, `.data` payloads, entrypoints and metadata.
Only reviewed source plus necessary metadata and matching LICENSE are accepted.
Correct RECORD/checksums do not bless an unexpected install member. No malicious
payload was found in the actual 0.1.2 wheel; negative fixtures are inert and not
installed.

Source reports now include configuration_sha256 and committed-tree coverage for
Cairn's evidence bridge. Existing GET-only client allows bounded issue/main-branch
reads for resume; no new HTTP write endpoint exists.

## Use

Python 3.11+ and Git, installed in a dedicated venv. For complete instructions use
`packages/cairn-engineering/README.md` and the coherent distribution installer.
All original commands (`init`, `doctor`, `scan`, `schema`, `schema-probe`, `audio`,
`junit`, `decision-lint`, `pr`, `demo`) remain. No LLM key for local checks.

`scan` is read-only source analysis and can return PARTIAL with exit 0. `schema`
checks the configured direct ORM columns in a stable offline SQLite copy; it does
not prove migration provenance, all ORM semantics or type/FK/index compatibility.
Native `schema-probe` requires opt-in isolated Docker and an approved reproducible
image; ENV and ENVIRONMENT are both test, tenant is harness-fixture. BLOCKED is
not proof of a migration bootstrap failure. No create_all/stamp fallback.

Windows link-capability failures must not be skipped or called PASS. Run
`scripts/validate_windows.py` on an environment already permitted to create links.
The coherent distribution's verifier is
`packages/cairn-engineering/scripts/verify_install.py`; the standalone legacy
`scripts/verify_delivery.py` remains regression-tested for its package format.

Source/runtime/tests are reused from v0.1.2; old validation files are not copied
as evidence for this version. New exact test and delivery receipts are at the
coherent distribution root. ERP production/CI/ledger are never changed by install.

## PR #22 review corrections (0.1.4, extended by 0.1.5)

The default Bingxue profile selects **InventoryMovement, WarehouseStock, InventoryEpoch and InventoryManifest**.
This is an explicit four-model, direct-column contract, not full-schema discovery.
The Cairn inventory workflow requires K04 revision matching and K04B for all four
models plus K04B_COVERAGE; native P01–P16 remain separate requirements. A custom
narrower local check is permitted but cannot satisfy that broader workflow.

K04B_COVERAGE reports resolved model/table/column names, unsupported selected
models and excluded top-level class declarations in the inspected source file.
It does not discover models in other files or certify type/FK/index/constraints.
Class-level conditionals/loops/try/with/match in a selected model are currently
unsupported: return BLOCKED rather than silently ignore potential declarations.
Normal method bodies are not treated as class-level declarations. Inheritance,
mixins and dynamic names retain their existing refusal behavior.

`schema-probe` now emits K04 when the sandbox DB revision matches the graph head,
alongside physical column coverage. Native migration execution remains a separate
qualification; unit tests and constructed SQLite copies are not ERP migration proof.

The S1b expansion uses coverage contract `bingxue-movement-stock-v2`, replacing
the two-model v1 requirement only through a new package/workflow version. Existing
configuration is never rewritten automatically. Narrow profiles remain valid
for diagnostic checks, but cannot satisfy the four-model Inventory workflow.
The regression fixtures are synthetic m58-shaped copies, not historical ERP
seed/upgrade executions. All other models and type/FK/index checks stay outside
this bounded contract and remain explicitly reported.
