# Local integration trial — 2026-09-10

User authorized one local stdio registration and a synthetic UAT delivery to this standalone task. Registration and manual UAT succeeded. This is **not a full rollout** and does not migrate any ERP team.

## Exact registration

- Server name: `communication-ledger-local`.
- Config: `C:\Users\ddkho\.codex\config.toml`.
- Added section: `[mcp_servers.communication-ledger-local]` only.
- Executable: `C:\Users\ddkho\Documents\Codex\2026-09-10\codex-communication-ledger\outputs\.venv\Scripts\python.exe`.
- Arguments: `-m comms_ledger.server --db C:\Users\ddkho\AppData\Local\CodexCommunicationLedger\ledger.sqlite`.
- No environment variables, credentials, custom working directory or model settings were added.
- Supported CLI reported this entry enabled with stdio transport, no disabled reason.

The command used was the documented `codex mcp add communication-ledger-local -- <absolute-python> -m comms_ledger.server --db <absolute-db>`. It uses the existing output-local virtual environment and editable package; no global installation was performed. The exact configured invocation was tested from a different working directory, proving that it does not rely on the task's current directory.

Private data root: `C:\Users\ddkho\AppData\Local\CodexCommunicationLedger`. New root ACL inheritance was disabled and grants FullControl only to the current Windows user and SYSTEM; backup/database children inherit that private ACL. It is outside OneDrive. The packaged app may resolve this path through its LocalCache view; the registered path above is the stable logical path used by Codex. No database containing ERP/production data was read or changed.

## Configuration preservation

The original config was copied before registration to:

`C:\Users\ddkho\AppData\Local\CodexCommunicationLedger\backups\config-before-ledger-20260909T185922Z.toml`

The backup stays private and is excluded from this Git repository. Its settings/secrets were never printed. `registration.json` in the private data root records paths and before/after hashes without copying other settings.

The supported CLI unexpectedly removed the pre-existing empty `mcp_servers.node_repl.args = []` field. The preservation comparison rejected that delta. A narrow `apply_patch` restored that exact empty field. Full parsed comparison then confirmed **all pre-existing settings/values equal the backup**, with only the new ledger entry added. Existing model, effort, plugins and other MCP configurations were preserved.

## Actual callable status

| Boundary | Observed status |
| --- | --- |
| Config registered and enabled | PASS — supported CLI `mcp get` reads our exact entry |
| Exact registered command starts | PASS — transient subprocess, no dependency on working directory |
| Official MCP SDK client lists tools and calls them | PASS — `ledger_read`, `ledger_command`, `ledger_help`; structured results; protocol 2026-07-28 |
| Ledger tools in this already-running task's native inventory | **NOT_LOADED at inspection** |
| Desktop activation after user refresh/restart | **NOT_VERIFIED; app was not restarted** |
| Automatic wake/transport from Python | **NOT_IMPLEMENTED** |
| Persistent dispatcher/service | Not started |

Registration alone is not proof that this running task acquired new tools. The official desktop instructions use **Settings → MCP servers → Restart**, then `/mcp` to inspect connected servers. The user can refresh the server connection there and verify the ledger tools in the target task; if its inventory remains unchanged, refresh/reopen the task or app at a convenient boundary. No automatic app restart was performed. The successful trial below used the official SDK Client as an explicit local bridge to the registered stdio command; it did not claim native task-tool loading.

## Real manual-delivery UAT

- Event: `200bc81e-b87d-4fad-95c7-c777a7474c4d`.
- Dedupe: `local-uat-20260910-1`.
- Source PM task: `01a07d6f-05ae-74b1-90f3-3a9487ae4a24`.
- Only target: this standalone task, `01a08774-2524-7553-b951-35e9ce8de283`.
- Binding: issue `LOCAL-UAT-20260910`, checkpoint `uat-1`, scope `standalone-ledger-trial-only`, base/head `f3127d5b4b9085f79201bb2ffa99aaebef76b8dd`.
- Payload explicitly grants **UAT ledger acknowledgement and readback only; no work, ERP, deployment or production authority**.

The registered server created and claimed the event, then prepared an envelope while keeping `QUEUED`. PM delivered the exact envelope using the host's real `send_message_to_thread` tool to this task. This task actually received it, verified the live lease and checkpoint, and recorded a receipt referencing the observed inbound message. It then independently ACKed, started the permitted ledger readback, verified its target-filtered snapshot and completed. PM's subsequent receipt explicitly attested `isError=false` and the exact returned target task ID; this corroboration is preserved in the report without inventing a server receipt ID or replaying the assignment.

Result: **QUEUED → SENT → ACKED → STARTED → COMPLETED**, one delivery attempt. The event data is synthetic; the PM-to-target host delivery and target acknowledgement were real. `SENT` was not inferred from envelope preparation. Lease tokens are omitted from the report and remain only in private local trial state. The final event/history and PM-attested receipt are in `INTEGRATION_TRIAL.json`.

Evidence references under `artifact://local-uat/200bc81e-b87d-4fad-95c7-c777a7474c4d/` refer to the observed inbound/ACK/readback stages recorded in that report and this task's conversation. They are local evidence labels, not remotely resolvable URLs. No real ERP worker, external team or production system participated.

## Verification

Before integration: `.venv/Scripts/python -m unittest discover -v` on clean `f3127d5b4b9085f79201bb2ffa99aaebef76b8dd` passed **28/28**, zero skips, 18.970 seconds. No implementation/test source changes were made for this trial. The trial verified the actual registered invocation and durable local database separately. Expected rejected-command test logs are not failures.

No long-lived server remains from the trial; each SDK client exited its subprocess. The app may start a normal host-managed stdio subprocess after the user activates the registration, which is distinct from an independent background dispatcher. The private trial database and config backup are intentionally retained.

## Rollback

Rollback removes registration only; preserve the private database/report for evidence. The supported removal command is `codex mcp remove communication-ledger-local`, but this CLI version normalized an unrelated empty field during add, so compare settings and restore that field if it is removed again.

For an exact restore when **no config change has occurred since registration**, the following guarded PowerShell sequence restores the private original backup. It refuses to overwrite newer user settings:

```powershell
$ledgerRecord = Get-Content -Raw 'C:\Users\ddkho\AppData\Local\CodexCommunicationLedger\registration.json' | ConvertFrom-Json
$ledgerCurrentHash = (Get-FileHash -LiteralPath $ledgerRecord.config_path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ledgerCurrentHash -ne $ledgerRecord.registered_config_sha256) {
  throw 'Config changed after registration. Remove only the communication-ledger-local section; preserve later edits.'
}
$ledgerBackupHash = (Get-FileHash -LiteralPath $ledgerRecord.backup_path -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ledgerBackupHash -ne $ledgerRecord.backup_sha256) { throw 'Backup hash mismatch; stop.' }
Copy-Item -LiteralPath $ledgerRecord.backup_path -Destination $ledgerRecord.config_path
```

After removing registration, refresh MCP connections at a user-chosen boundary. Do not restore an older whole config over subsequent edits; use a narrow deletion of only the ledger section when the guard fails. Rollback instructions were provided, **not executed**.

Official setup/activation reference checked before registration: [Codex MCP documentation](https://learn.chatgpt.com/docs/extend/mcp?surface=cli). The first implementation's provenance and test coverage remain in `VALIDATION.md`.
