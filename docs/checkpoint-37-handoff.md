# Checkpoint 37: reviewed file creation and no-overwrite moves

Status: scoped implementation and automated verification complete. The wider
application remains open against the verification ledger. At this checkpoint's
freeze the generated privacy artifact below was still open; the checkpoint 38
continuation subsequently resolved it without weakening the scanner.

## What changed

- The Agent workspace now creates a new UTF-8 text file in an existing folder
  and renames or moves one clean, opened UTF-8 text file into another existing
  folder. Both operations expose their complete authority before apply.
- `local-agent-workspace-lifecycle.v1` binds session, operation, relative paths,
  exact revision, byte size and line-ending semantics. Apply resubmits the
  complete create content or exact move authority and requires a separate native
  user-presence confirmation.
- Lifecycle capabilities are memory-only, metadata-only, session-bound,
  single-use and valid for at most 120 seconds. A session retains at most eight;
  closing the session removes them. The exact deadline is expired, not live.
- Create uses the existing reviewed write primitive in create-if-absent mode.
  The destination parent must already exist and remain the reviewed directory.
  A destination that appears before or during publication is preserved.
- Move binds the source identity, content hash, mode, byte size and both parent
  identities. The target must remain absent. Linux uses `renameat2` with
  `RENAME_NOREPLACE`, macOS uses `renameatx_np` with `RENAME_EXCL`, and Windows
  renames the already-open source handle with replacement disabled while both
  directory chains remain pinned.
- Publication is followed by exact handle and path verification. A failed
  verification is rolled back only when the restored identity, content, size,
  mode and target absence are read back exactly. Otherwise the result is
  `unverified`, all later lifecycle changes for that session are locked, and the
  UI directs the owner to inspect both paths and start a new session.
- Verified create/move results update the memory-only reviewed change set:
  create contributes one reviewed write; move records the old path deletion and
  new path creation separately. Discovery and the current folder refresh after
  apply.
- The workbench adds responsive, keyboard-labelled **New file** and
  **Rename or move** cards, full create diff review, exact source/destination
  move review, byte/line-ending disclosure, native-presence unavailable state,
  preserved drafts, verified readback and narrow/forced-colors styling.

## Defects reproduced and repaired

- No application path previously exposed reviewed create or move authority;
  the older workspace intentionally handled existing-file content edits only.
- The first Windows handle-rename buffer was allocated from `FileName`'s field
  offset rather than the native structure size. Repetition showed that Windows
  could report success while neither name was visible. The buffer now retains
  the structure's trailing alignment and a zeroed wide terminator. A deterministic
  layout regression plus 1,000 native and 500 complete repeated moves passed.
- A target created after the initial Windows create check was initially
  classified as unknown even when the native create-if-absent call returned an
  exact collision. That outcome is now a safe revision rejection; the external
  target is preserved and the session is not needlessly hard-locked.
- Move verification initially relied on one immediate directory observation.
  Bounded retries now repeat the same strict predicates without relaxing
  authority. Windows rollback closes the publication handle, reopens and
  revalidates the moved identity, then performs and verifies one fresh
  handle-bound rename.
- Rollback initially verified only restored metadata after publication. It now
  performs exact post-restore content readback and refuses to claim rollback
  when that readback is unavailable or contradictory.
- Lifecycle expiry initially treated the exact deadline as live. Pruning and
  apply now expire at `deadline <= now`, with a boundary regression.
- The full frontend gate exposed an asynchronous focus assertion that checked
  before the workspace focus effect completed under parallel load. The
  regression now waits for the required focus; the production focus behavior is
  unchanged.
- The complete intercepted browser gate retained old manual-edit-only copy.
  Its assertion now covers manual edits, new files and no-overwrite moves.
- The first frozen backend pass correctly rejected a stale committed OpenAPI
  artifact after line-ending coherence was added. The OpenAPI document and
  generated TypeScript client were regenerated and byte-parity rechecked.

## Verification receipts

- Final dedicated lifecycle suite: **19 passed**. It covers metadata-only
  authority, exact content and line endings, session binding, single use,
  exact-deadline expiry, bounded eviction/session cleanup, create and move
  target races, native no-overwrite publication, source drift, Windows native
  buffer sizing, verified rollback, false-rollback prevention, unverified hard
  lock, reviewed change-set integration and path refusal.
- Complete workspace/Agent corrective gate after the final boundary review:
  **180 passed** across lifecycle, read/write boundaries, transactions,
  inspection, discovery, service/HTTP and change-set behavior.
- Strict lifecycle parser, HTTP transport and workbench component gate:
  **181 passed**. Apply requests require exact native-presence body binding;
  forged paths, sessions, revisions, fields and results are rejected.
- Full frontend: **1,844 tests across 135 files passed**. The first run exposed
  the focus-timing regression; the clean complete rerun passed.
- Synthetic browser suite: **105 workflows passed**.
- Intercepted loopback/HTTP browser suite: the first complete run passed 34 and
  exposed one stale copy assertion. Its focused regression passed, and the clean
  complete rerun passed **35 workflows**. Create, readback, move and second
  readback pass at 390px and 1,440px without horizontal overflow.
- Production frontend build and generated API parity pass after regeneration.
  The OpenAPI/lifecycle corrective gate passed **24 tests** and the committed
  OpenAPI artifact is byte-exact to the current schema.
- The protected launcher was restarted from the repository `.venv` after the
  global Python executable correctly failed closed because the package is not
  installed there. The replacement binds only `127.0.0.1:8765`; `/health` and
  the Agent HTML route return 200, the same route under JSON negotiation returns
  404, and all ten versioned assets in the packaged dashboard return 200.
- The post-restart residue audit found **zero model-runtime processes, zero
  workspace test workers and zero GPU contexts owned by the local Python
  server**. The native window's embedded browser retains one ordinary rendering
  context; it is not a model runtime and reports no model-memory allocation.
- The frozen backend inventory covered all **279** `test_*.py` files in four
  disjoint, cache-free shards. Before the generated-schema correction it
  reported **4,274 passed, nine skipped and two failed**: exact shard receipts
  were 1,078 passed / one skipped / two failed; 772 passed; 1,132 passed / six
  skipped; and 1,292 passed / two skipped. One failure was the stale generated
  OpenAPI artifact and passed its exact corrective rerun. The other is the
  unchanged prohibited SQLite artifact described below. The nine skips are
  unavailable Windows symlink capabilities. A second overlapping whole-suite
  total is intentionally not invented.

## Existing privacy finding

At this checkpoint's freeze, the repository privacy scanner still rejected the historical generated artifact
`test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`.
This checkpoint did not delete it, exclude it, weaken the scanner or relabel the
failure as a pass. All new fixtures are fictional and no provider sessions,
credentials, owner configuration, screenshots or private workspace content were
read.

Checkpoint 38 later validated the exact resolved target as one ordinary file
inside the generated test-results directory, moved only that file to the Windows
Recycle Bin, and reran the unchanged scanner successfully. The move is
recoverable; the historical failure above remains recorded as the checkpoint 37
receipt rather than being rewritten as an earlier pass.

## Owner review checklist

1. Reload the protected Agent page and open an existing session/workspace.
2. Choose **New file**, enter a path whose parent already exists, add content,
   and confirm that the review starts at `/dev/null` and shows the full new path.
3. Apply through the native confirmation. Confirm the file opens with the exact
   reviewed content and appears in the current folder/change-set views.
4. With that clean file open, choose **Rename or move**, select another existing
   parent, review both paths, apply, and confirm the moved file rereads exactly.
5. Try an already-existing destination. It must be preserved and the operation
   must report that nothing was overwritten.

## Explicit limits and next work

- This slice does not create directories, delete files, move directories,
  overwrite a destination, perform a case-only Windows rename or create missing
  parents. Deletion remains separate until a recoverable design is approved.
- Checkpoint 38 subsequently adds reviewed creation of exactly one directory
  under an existing parent. Deletion, recursive parent creation and directory
  moves remain excluded.
- Create/move are separate reviewed operations, not members of the existing
  two-to-eight-file content transaction. Cross-file and power-loss atomicity are
  not claimed.
- Stable-workspace verification cannot prevent every uncooperative external
  writer. Exact detected uncertainty is surfaced and hard-locked rather than
  converted into success.
- Capabilities, conversations, reviewed baselines and change tracking remain
  memory-only. Durable content retention remains an owner-gated privacy-vault
  decision.
- Native confirmation tests use a fictional browser bridge. Owner click-through
  and visual preference remain manual acceptance items.
- No model or GPU runtime was loaded for this checkpoint. No commit or push was
  performed.
