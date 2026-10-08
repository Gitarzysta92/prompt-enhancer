# Checkpoint Release-01a.1 handoff

Status: automated complete; owner click-later review queued
Completed: 2026-09-01
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Entry contract: [Release-01a.1 entry](checkpoint-release-01a-1-entry.md)

## Outcome

The dedicated Agent project/chat catalog now has a fail-closed, checksummed
migration history at schema 30. Every supported historical schema upgrades
transactionally, and a damaged ledger, changed migration, conflicting SQLite
head or unledgered application table is refused without being silently repaired.
The live Agent health card accepts the current backend schema dynamically and
reports one fixed, content-free diagnostic when migration integrity is invalid.

## What changed

- Added append-only Agent catalog migration 30 and a strict checksum sidecar.
- Replaced maximum-version migration trust with an exact contiguous registry for
  versions 1 through 30.
- Bound `PRAGMA user_version`, the migration ledger and the checksum ledger to
  the same exact head before and after migration.
- Made incomplete history, checksum drift, schema-head mismatch and unledgered
  application tables fail closed with fixed reason codes.
- Added a forced-DDL-failure proof that schema, ledger and checksum changes roll
  back together.
- Replaced the frontend's obsolete literal schema expectation with a strict
  positive-safe-integer contract and added the migration-invalid recovery copy.
- Regenerated the checked-in OpenAPI contract and strict TypeScript projection.

Historical migrations 1 through 29 were not rewritten. Checksums cover frozen
migration statements only; no user records or content enter the checksum ledger.

## Correctness evidence

- Every-source-version migration matrix: schemas 1 through 29 upgrade to 30 with
  synthetic project/chat data preserved, then pass SQLite integrity and foreign
  key checks.
- Corruption matrix: gapped ledger, changed checksum, `user_version` mismatch and
  unledgered tables are rejected with no committed mutation.
- Interruption matrix: a forced schema-30 trigger failure restores the complete
  schema-29 state.
- Focused migration/hardening backend selection: 66 passed, 210 deselected.
- Complete affected backend files: 276 passed.
- Complete Agent/frontend regression: 568 passed across 33 files.
- Complete frontend regression: 2,723 passed across 184 files.
- Complete backend regression: 5,160 passed, 9 skipped, 0 failed. All skips are
  the repository's documented Windows unavailable-symlink cases.
- Focused rendered Agent health journeys: 2 passed at 360 px and 1440 px.
- Production build: 572 modules built; only the existing chunk-size advisory was
  reported.
- Generated OpenAPI check, Python compilation, offline lock check, privacy scan
  and diff check passed.

## Live reload evidence

- The prior exact loopback listener was stopped and its wrapper exited.
- The documented workspace Python entry point started one replacement listener
  on `127.0.0.1:8765` with hidden parent and child windows.
- `/health` returned `ok`, `offline_only` and `metadata`.
- Recognized local-model process count remained zero.
- The real Agent page's on-demand health card reported
  `Catalog: ready · schema 30 · 0 projection issues`.
- The rendered page had one `main`, one `h1`, no horizontal overflow, no
  unlabeled buttons and no browser errors or warnings at the live viewport.

The live check read only fixed, content-free status values. It did not inspect
project names, chat titles, prompts, messages, paths, credentials or artifacts.

## Owner click-later check

1. Open **Agent**.
2. Open **Agent settings → Connections**.
3. Select **Check again** under **Projects & chats health**.
4. Confirm the card says `Catalog: ready · schema 30 · 0 projection issues` and
   that existing projects and chats remain browsable.

## Still pending

This packet proves the Agent catalog migration boundary only. It does not yet
close whole-application durable-store recovery, interrupted download/artifact/
MCP/controller reconciliation, repeated crash/start/stop process composition or
the packaged Windows acceptance journey.

## Exact next checkpoint

**Release-01a.2 — whole-store migration and restart reconciliation.** Inventory
every remaining durable store and version ledger, prove every supported upgrade
and restart boundary with synthetic fixtures, and verify that interrupted
downloads, artifact projections, MCP operations and controller ownership resume,
roll back or fail closed without being presented as completed. No real model,
provider transcript, credential or external MCP server is required for this
packet.
