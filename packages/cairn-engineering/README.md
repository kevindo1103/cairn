# Cairn Engineering 0.1.2 — implementation for issue #21

Cairn remains the only coordination framework. This package adds **topology-aware
workflow projections, a resume/reconcile observer, and a typed Iceflow evidence
bridge**. Iceflow Checks 0.1.5 retains the F1/F2/F3 fixes and adds the four
source/contract corrections from PR #22 review 5876863593.
There is no second task queue, policy database, principal registry or agent model.

**Code implemented, live activation NOT performed.** This is not an autonomous
coding fleet, an authenticated GitHub decision service or a production release
gate. Templates/projections are not grants. Existing Cairn core/adapter/host and
ERP source/CI are untouched. #16/#17/#19/#20 remain separate unmerged work; no
cherry-picking of the schema-2 draft host into the schema-1 main stack.

## Install the coherent distribution

Use Python 3.11+, Git, and a directory outside the ERP checkout. Verify the complete
ZIP first with `python packages/cairn-engineering/scripts/verify_install.py --root .`.
Create a dedicated venv, then install the two wheels in the distribution's `dist/`
directory together. Dependencies may need an index on first installation.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install .\dist\iceflow_harness-0.1.5-py3-none-any.whl .\dist\cairn_engineering-0.1.2-py3-none-any.whl
.\.venv\Scripts\python.exe -m pip check
.\.venv\Scripts\cairn-engineering.exe demo --out .\demo-run
.\.venv\Scripts\cairn-engineering.exe init --repo C:\Projects\bingxue-erp --out .\bingxue-config
.\.venv\Scripts\cairn-engineering.exe doctor --config .\bingxue-config\project.json
.\.venv\Scripts\cairn-engineering.exe scan --config .\bingxue-config\project.json
```

From a Cairn checkout, install `packages/iceflow-checks` and
`packages/cairn-engineering` with pip into the same dedicated venv. Linux/WSL uses
`.venv/bin/` instead of `.venv\Scripts\`. No global install, daemon, hook, MCP
registration, registry edit or production access is needed for these commands.
The executable remains `iceflow-harness` for backward compatibility; its role is
**checks**, not competing orchestration.

## What runs now

| Command/API | Implemented behavior | Boundary |
|---|---|---|
| `init`, `doctor`, `scan` | Configure a Git clone; run existing checks; export report | No ERP writes; exit 0 can still mean PARTIAL |
| `topology` | Role definitions and assignment relationships | No session IDs fabricated or runtime grants |
| `workflow-template --name backend-bugfix --out workflow.json` | Five named templates with dependencies, scopes, reviewer separation and required evidence | Not a new approval round or replacement ERP test policy |
| `workflow-next` | Deterministic ready/active/waiting/rework proposals from existing event/evidence observations | No dispatch or independent workflow database |
| `resume` | Recheck task/session/generation/checkpoint, Git, PR merged/closed/head, dependency, slot and lease | Advisory observer; no mandatory compaction hook installed |
| `bridge` | Verify exact report/config/source/step/checkset, digest and freshness; create typed immutable evidence | No direct ledger write; digest is not authentication |
| `ResumeService` | Double-read host-supplied canonical snapshots before returning a proposal | Host must establish real identity and supply read-only access |
| `HostEvidenceBridge` | Validate report then call an injected protected Adapter completion capability once | Host-only integration seam, not a worker CLI or fake identity provider |

All public commands return `authority=NONE` and no effective permissions. A
`RESUME_CANDIDATE` disposition is not an edit permit. `main` movement does not
trigger reset/rebase; an already merged PR does not trigger reopen/push. An expired
lease does not free a slot or spawn a replacement. Unstructured comments are never
parsed for authority. A lost transport receipt must be reconciled by existing
Cairn transport logic; this package sends no messages.

## Resume with an existing task

The task binding is a host/owner-provided *reference* to existing authority, not a
new grant. `demo-run/binding.example.json` documents the full shape using synthetic
IDs. Replace it using actual event/session/checkpoint/registry data; do NOT use
synthetic IDs on a real store. Required fields include event, task, session,
generation, registry/checkpoint revision, issue/PR, base/head/tree/main SHA,
workflow digest, step, owner role and bounded paths.

The standalone CLI only reads a **closed consistent schema-1 offline ledger copy**
prepared by the owner through the already authorized backup procedure. Do not
`cp` a live WAL DB; do not point this CLI at the active ledger. WAL/SHM/journal
sidecars, unknown schema, aliases, missing/corrupt copies are rejected. No
`Ledger()`/`Store()` constructor or `recover()` is invoked by this reader.

```text
cairn-engineering resume --config bingxue-config/project.json --binding task.json --ledger-copy /approved/offline-ledger.sqlite --offline-copy
```

With a repository-scoped read-only `GH_TOKEN`/`GITHUB_TOKEN`, GitHub task state is
read twice (max 20 reads, no retry). Tokens are never put in files or argv. No token
means REMOTE_UNAVAILABLE, not continuation from cached authority. A fixture can be
provided with `--github-observation`, but the output explicitly labels it imported
and untrusted. Copy age is NOT certified by read time: the copy's origin remains
`OFFLINE_COPY_NOT_LIVE_ATTESTATION`. Offline observations cannot authorize writes.

For a real live resume boundary, wire `ResumeService` to the already protected
Cairn host snapshot provider; continue to invoke Adapter before every side effect.
A shell/Git tool that bypasses Adapter is not fenced by this package.

## Workflow progress without another database

`workflow-next --config ... --instance instance.json --ledger-copy ... --offline-copy`
consumes `{schema,workflow,workflow_digest,candidate_sha,step_events,roles,evidence_paths}`.
`schema=cairn-workflow-instance-v1`; `step_events` maps step ID to existing event ID;
`roles` maps role to a one-element list of `{task_id,session_id,generation}` from the
existing registry; `evidence_paths` maps step ID to immutable host/check receipts.
No statuses are written to the instance file. Unknown/multiple role mappings block
that route. Dependencies are a projection over core events, not an array secretly
passed into the core's single-dependency API.

Typed host receipts use `cairn-host-step-receipt-v1` with subject fields matching
check receipts (task/session/generation/event/checkpoint/step/workflow/candidate),
`step_result`, and a canonical `observation_digest`. They are supplied by the
existing authorized host/owner review path. Import integrity is not proof of
human approval. The projection may describe an observed ACCEPTED step, but it
never supplies runtime authority. Check steps also require the exact configured
check set; diagnostic COLLECTED must not satisfy a required-check step.

Registry role names are the existing Adapter taxonomy, not display labels. Dev
routes require canonical lowercase `worker`; the QC dev route accepts `QC` or
`worker`. The single-owner Designer route uses canonical `Lead`, without adding
an authority role. Unknown aliases such as `Dev`, `Worker` and `Designer` are not
migrated or inferred. Regression tests invoke the actual sibling Adapter
`validate_entries()` before resolving/resuming a synthetic worker. This pure
source compatibility test constructs no Store and proves no host identity.

Inventory workflow definition **version 3** binds the deliberately bounded
`bingxue-movement-stock-v2` direct-column presence contract:
`InventoryMovement → inventory_movements`, `WarehouseStock → warehouse_stocks`,
`InventoryEpoch → inventory_epochs`, and `InventoryManifest → inventory_manifests`.
K04 (revision), K04B (columns for all four models), and K04B_COVERAGE (checked,
excluded and unsupported selection) must pass, alongside native P01–P16. A
Movement-only or former two-model report cannot satisfy this contract even if all its reported
checks pass. Other inventory models/tables and source files, type/FK/index and
constraints are NOT covered; this is not full ERP schema acceptance. Unknown
class-level conditional/loop/try declarations block the selected model instead
of dropping columns. Top-level excluded declarations are reported as NOT_SELECTED,
not silently certified or automatically executed.

Changing the definition or checker/config digest invalidates older bindings;
there is no automatic live checkpoint/grant/registry update. The bridge qualifies
0.1.5 reports, not stale 0.1.4/0.1.3 artifacts. Unrelated diagnostics do not become a
global veto for every workflow; only that step's explicit prerequisites apply.

The Inventory template keeps native P01–P16 as required evidence; a source `scan`
cannot manufacture them. Release workflows stop at `release_handoff`; no code
here dispatches deployment. Change templates only through review; their digest
invalidates stale bindings. Pilot task roles/paths must be reconciled with current
ERP ownership, not blindly copied from a template.

## Checks → evidence → existing Cairn

`bridge --binding task.json --report report.json --report-sha256 <FILE_SHA256>`
checks actual current local HEAD/tree/dirty state, report version 0.1.5,
configuration hash, step/workflow identity, self-digest, physical file digest,
freshness, counts, required check statuses and committed-tree coverage. It emits
an immutable receipt; it does not complete an event.

A host can initialize `HostEvidenceBridge` with its already admitted Adapter
executor, immutable artifact writer and owner-pinned binding/workflow/config. The
worker may supply report bytes and its existing lease token, not redefine policy.
The bridge validates again, persists report + typed receipt, and calls only the
existing `complete` operation. A host refusal propagates; no retry/requeue follows.
Candidate/identity/lease freshness is rechecked by that protected executor. These
interfaces do not themselves provide OS identity or prove a report was produced
by a trusted worker. No fake resolver is offered as a production option.

**Task COMPLETED != checks PASS != review accepted != merge/deploy authorized.**

## Validation and remaining work

See the distribution `evidence/VALIDATION.json`, raw JUnit and command receipts.
Do not mix Linux synthetic tests with the user's historical Windows results.
Native Windows symlink tests, native Docker/ERP migration, live GitHub client,
real host Adapter integration and compaction action fencing remain separate
qualification boundaries. We do not claim them from a mock or a file hash.

Run each package's tests separately to avoid pytest module-name collisions:

```text
python -m pip install "./packages/iceflow-checks[test]" "./packages/cairn-engineering[test]"
python -m pytest packages/iceflow-checks/tests -q
python -m pytest packages/cairn-engineering/tests -q
```

On a Windows environment already permitted to create links, run
`packages/iceflow-checks/scripts/validate_windows.py`. It does not enable Developer
Mode or elevate permissions; capability refusal remains BLOCKED, not SKIP/PASS.

This source addition addresses W1 and the W2/W3 observer/contract slice. It does
not silently activate W6 or claim the complete autonomous fleet is done. Core
schema migration/PM succession stay in #15/#16/#17; host/broker work stays in #20.
ERP bugfix/G1 and existing P01–P16 grants do not depend on this package.

Review response and focused acceptance limits: `REVIEW_5876863593.md`.

## Conditional re-review at `8d2ba60`

The user's re-review is retained as reviewer-reported evidence, not new execution
by the package author. The four-model S1b expansion is `bingxue-movement-stock-v2`
in workflow definition 3, instead of mutating the meaning of the two-model v1.
No code updates an existing config, checkpoint, grant or registry. Create a new
config or explicitly review its four-model selection, then reconcile the changed
checker/config/workflow digests. Old reduced-scope reports cannot satisfy v2.

Focused tests reproduce the S1b missing-column sets on **synthetic SQLite copies**
(8 stock, 5 epoch, 1 manifest), plus isolated epoch/manifest failures. Column names
are pinned to the m60 migration source. This is not a new execution of ERP
`seed_local.py`, a historical upgrade, native P01-P16, or a host-resume UAT.
