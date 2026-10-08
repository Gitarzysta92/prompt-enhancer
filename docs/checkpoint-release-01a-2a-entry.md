# Checkpoint Release-01a.2a entry

Status: automated complete; optional owner continuity review queued
Entered: 2026-09-01
Completed: 2026-09-01
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Prerequisite: [Release-01a.1 handoff](checkpoint-release-01a-1-handoff.md)
Handoff: [Release-01a.2a handoff](checkpoint-release-01a-2a-handoff.md)

## User-visible outcome

Every auxiliary SQLite store shipped with Prompt Enhancer either opens at one
exact, provenance-checked schema or remains unchanged with a fixed local
failure. A restart must not silently adopt a gapped ledger, altered migration,
conflicting SQLite head or unknown legacy table shape.

## Inventory evidence and gap

- `metrics.sqlite3` already binds a contiguous SHA-256 migration ledger to
  `PRAGMA user_version` through schema 61.
- `agent-catalog.sqlite3` gained the same fail-closed boundary at schema 30 in
  Release-01a.1.
- `shared-folders.sqlite3` and `central-annotations.sqlite3` are constructed on
  every application bootstrap, but currently create or alter tables ad hoc and
  have no schema ledger, checksum or SQLite schema head.
- The social store records versions 1 and 2 but trusts only `MAX(version)` and
  does not set `user_version` or retain migration checksums.
- The optional paid-product store records version 1 and verifies its current
  structure, but likewise trusts only `MAX(version)` and has no checksum or
  SQLite schema head.
- The maintenance path inventory omits the two bootstrap-mounted auxiliary
  databases and their WAL/SHM sidecars.

## Frozen implementation boundary

1. Give the shared-folder and central-annotation stores append-only migration
   registries, exact contiguous ledgers, SHA-256 checksums and `user_version`.
2. Adopt only the exact known unversioned legacy shapes in one transaction;
   refuse missing, extra or conflicting legacy structure without mutation.
3. Append checksum migrations to the social and paid-product stores without
   rewriting their historical schema statements.
4. Require ledger head, checksum head and `user_version` to agree after the new
   head exists. Preserve the exact historical `user_version=0` compatibility
   state only long enough to perform the first checksummed upgrade.
5. Force a late migration failure in each store family and prove schema,
   provenance ledger and SQLite head roll back together.
6. Preserve representative synthetic records across legacy adoption and normal
   upgrade, then reopen each store and run integrity/foreign-key checks.
7. Add the two bootstrap-mounted databases and sidecars to the maintenance
   inventory as secret local state excluded from export and portable backup.

## Privacy and safety boundary

- Tests use disposable files, fictional identifiers, example paths and
  synthetic redacted windows only.
- No live social identity, shared-folder token, annotation window, provider
  session, credential, model, command or MCP process is read or started.
- Migration checksums cover canonical SQL statements only, never stored rows.
- Failures expose fixed codes or messages without table contents or paths.
- This packet does not change sharing, annotation, social or paid authority.

## Exit gate

- New, exact legacy and every supported version for all four stores reach the
  current checksummed head with data preserved.
- Gaps, checksum drift, head disagreement and unknown unversioned shapes fail
  before any committed change.
- Forced interruption leaves the prior durable head intact.
- Focused store tests, application bootstrap tests, maintenance inventory,
  complete backend regression, privacy scan and one hidden live reload pass.

## Explicitly deferred

Release-01a.2b will reconcile interrupted downloads, artifacts, MCP work and
controller ownership across restart. Release-01a.3 remains the combined
listener/model/command/MCP/helper process-composition checkpoint.
