# Checkpoint Release-01a.2a handoff

Status: automated complete; optional owner continuity review queued
Completed: 2026-09-01
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Entry contract: [Release-01a.2a entry](checkpoint-release-01a-2a-entry.md)

## Outcome

Every auxiliary SQLite store now opens only through one append-only migration
registry with an exact contiguous ledger, canonical SHA-256 statement
checksums and a matching `PRAGMA user_version` head. Exact known legacy shapes
upgrade atomically; unknown shapes, ledger gaps, checksum drift, head
disagreement and extra current tables fail closed without a committed repair.

This packet closes the migration-provenance half of Release-01a.2. Interrupted
download, artifact, MCP-operation and controller reconciliation remains the
separate Release-01a.2b checkpoint.

## Store heads

| Store | Current head | Result |
| --- | ---: | --- |
| `shared-folders.sqlite3` | 2 | Exact unversioned legacy adoption plus checksummed head |
| `central-annotations.sqlite3` | 3 | Exact legacy heads 1 and 2 plus checksummed head |
| `social.sqlite3` | 3 | Existing heads 1 and 2 preserved; checksum migration appended |
| `paid-product.sqlite3` | 2 | Existing head 1 preserved; checksum migration appended |

The primary metrics database at schema 61 and Agent catalog at schema 30 were
already checksummed prerequisites and were not rewritten.

## What changed

- Added one shared migration-integrity primitive for auxiliary stores. It
  validates identifiers and registries, binds exact contiguous versions to the
  SQLite head, stores canonical statement checksums and applies pending work
  inside the caller's transaction.
- Replaced ad-hoc shared-folder and central-annotation table creation with
  versioned transactional initialization, exact legacy SQL/column admission,
  integrity and foreign-key checks, private file permissions and symlink-path
  refusal.
- Appended checksum migrations to the social and paid-product stores without
  changing their historical schema statements.
- Added exact current table/trigger checks for the social store and preserved
  the paid-product store's existing structural checks.
- Added shared-folder and central-annotation databases plus WAL/SHM sidecars to
  the maintenance inventory as secret local state. They are excluded from
  export and portable backup; their sidecars are erased with the parent choice.
- Bound bootstrap filenames to the store-owned constants so construction and
  maintenance policy cannot silently drift.

## Correctness evidence

- New adversarial migration matrix: **33 passed**. It covers every supported
  historical head; representative synthetic data survival; clean reopen;
  integrity and foreign keys; unknown and altered legacy shapes; gapped
  history; checksum drift; SQLite-head mismatch; unregistered current tables;
  and a forced failure after all pending migration statements.
- Final complete affected-store/configuration selection: **153 passed,
  2 skipped**. The skips are unavailable Windows file/directory symlink
  capabilities. This final run includes the exact normalized table, trigger and
  index SQL checks added during the last source review.
- Bootstrap/configuration/distribution selection: **71 passed, 1 skipped**.
- Complete backend regression on the coherent migration implementation:
  **5,193 passed, 9 skipped, 0 failed** in 42 minutes 15 seconds. All nine skips
  are the repository's documented unavailable Windows symlink cases. The final
  structural-validator tightening then passed the complete 153-test affected
  selection above; a second identical whole-suite run was not represented as
  having occurred.
- Frozen Python compilation, offline lock check, repository privacy scan and
  whitespace validation passed.

All fixtures use fictional identifiers, reserved example paths, fixed future
timestamps and synthetic redacted windows. No provider session, prompt,
credential, real shared token, model, GPU process, MCP host or network service
was read or started.

## Live reload evidence

- The exact prior listener and its workspace launcher were revalidated, stopped
  and confirmed absent before replacement.
- One replacement was started from the repository virtual environment with a
  hidden window. Its owned tree contains two Python processes and one console
  host, with **zero visible windows**.
- Exactly one listener is bound to `127.0.0.1:8765`; `/health` returns HTTP 200
  with `ok`, `offline_only` and `metadata`.
- Recognized local-model process count is zero.
- The existing in-app Agent tab was reloaded and left open for the owner. It
  reports one `main`, one `h1`, 33 labelled buttons, no horizontal overflow and
  zero browser warnings or errors.

Successful application construction exercises both bootstrap-mounted stores.
The live proof intentionally did not inspect project names, chat titles,
workspace paths, shared credentials, annotation rows, prompts or artifacts.

## Scope truth

- This packet proves migration provenance and restart opening, not recovery of
  an operation interrupted while it was running.
- Existing peer-link credential persistence is unchanged. Classifying the
  shared-folder database as secret reduces export/backup exposure but is not an
  encryption or operating-system-vault claim.
- Social and paid-product databases remain optional development surfaces; this
  checkpoint hardens their schema boundary without promoting product readiness.
- No frontend or public API schema changed in this packet.

## Optional owner continuity review

The live Agent page is already open. At a convenient time, confirm that the app
still opens normally and that any previously created shared-folder or central
annotation state remains available through its existing UI flow. This review is
not required before the next automated reconciliation slice proceeds.

## Exact next checkpoint

**Release-01a.2b — interrupted-operation restart reconciliation.** Prove that
downloads, artifact projections, MCP operations and controller ownership that
were interrupted at each durable phase resume, roll back or become explicitly
failed/unknown, and never reappear as completed. Release-01a.3 then exercises
combined listener/model/command/MCP/helper ownership under repeated start,
stop, crash, timeout and listener collision.
