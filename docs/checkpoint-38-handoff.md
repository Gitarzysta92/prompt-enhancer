# Checkpoint 38: reviewed workspace topology

Status: scoped implementation complete; automated gates and protected-app
restart are recorded below. The wider product remains open against the
whole-application verification ledger and owner-gated decisions.

## What changed

- The Agent workbench can create exactly one ordinary workspace directory under
  one already-existing parent. It never creates missing parents recursively,
  replaces an existing path, deletes anything or moves a directory.
- `local-agent-workspace-lifecycle.v1` now includes directory preview/apply
  contracts. Authority is memory-only, metadata-only, session-bound,
  single-use, capped with the existing lifecycle previews and valid for at most
  120 seconds. Apply requires the distinct native confirmation
  `apply_reviewed_workspace_directory_create`.
- Preview binds the canonical relative path and parent identity. Apply reopens
  the parent through the no-follow workspace boundary, verifies its identity,
  performs one native create-if-absent operation, reopens the result, and
  compares its path/handle identity before reporting success. POSIX also flushes
  the pinned parent before success.
- A verified result refreshes the current tree/discovery/change views. If
  creation may have occurred but verification is not exact, the result is
  `unverified` and later lifecycle mutations in that session are locked. The app
  does not attempt path-based cleanup because a raced replacement directory
  could belong to another process; no deletion authority is inferred from
  permission to create.
- Windows mutation-parent handles now omit delete sharing. This closes a
  reproduced race in which the final reviewed parent could be renamed and
  replaced while an absolute-path publication was in progress. The same pin
  protects reviewed file creation, directory creation and file moves.
- The model tool schema now exposes `create_directory` and `move_file` whenever
  workspace writes are enabled. Both use the same reviewed lifecycle service as
  the manual workbench, wait for human approval, revoke denied/cancelled
  capability and are explicitly preferred over shell emulation in the system
  prompt.
- The coding-chat UI labels directory creation and file moves as first-class
  activity. The workspace adds a keyboard-labelled **New folder** card with
  canonical path review, missing-parent guidance, native-presence unavailable
  state, draft protection, exact confirmation binding and responsive layout.
- Fixed workspace failure codes for parent drift, unsafe paths and directory
  uncertainty are allowlisted without forwarding internal server messages, so
  the UI gives operation-specific recovery instead of a generic editor error.

## Defects reproduced and repaired

- The interrupted component edit had directory state and transport methods but
  no rendered card or review/apply functions. The new component regression
  failed before those controls existed and passes with the complete flow.
- Directory apply error codes were not in the transport's fixed safe-code set,
  so useful recovery reasons were discarded. Fixed-code projection tests now
  retain only the code and continue to suppress arbitrary server detail.
- The local-real HTTP fixture had create/move routes but no directory lifecycle
  route or correct nested-tree model. It now exercises folder create, nested
  file create, verified readback, move and second readback at narrow and desktop
  widths.
- A real Windows diagnostic proved that a reviewed mutation parent could be
  renamed while its handle was held. The regression now attempts that exact
  rename during directory publication and proves it is blocked while the
  reviewed destination succeeds.
- The initial verification-failure design attempted to remove an empty directory
  by path. Review showed that an external swap between identity check and
  removal could delete somebody else's directory. The cleanup was removed;
  uncertainty now stays explicit and hard-locks the session.
- One focused frontend invocation was accidentally launched from the repository
  root and therefore used the wrong Vitest environment. It failed with
  `document is not defined`; the same component file passed from the declared
  frontend project. This was a command-context error, not relabelled product
  evidence.

## Verification receipts

- Dedicated lifecycle gate: **23 passed**, including exact/single-use authority,
  target collision, unverified hard lock, no speculative cleanup and the real
  Windows parent-swap regression.
- Affected workspace/Agent/OpenAPI gate: **287 passed** before the two final
  denial cases; the final current-tree full-backend receipt below includes both.
- Model lifecycle flow plus denial cleanup: the approved directory/move sequence
  and both denied-tool variants pass. Denial leaves the source untouched, creates
  no path and retains no lifecycle capability.
- Strict lifecycle parser, HTTP transport, workspace component and Agent
  activity gate: **278 passed**. TypeScript project compilation and generated
  API parity pass.
- Intercepted HTTP/browser lifecycle flow: **2 passed**, one each at 390 px and
  1,440 px, including exact native confirmation headers and no horizontal
  overflow.
- Frozen complete frontend gate: **1,858 passed across 135 files**. The final
  run includes the folder-success, missing-parent, uncertainty-lock and model
  activity regressions; the focused totals above are not added to it.
- Frozen complete browser gates: **105 synthetic workflows** and **35
  intercepted loopback/HTTP workflows**. The latter includes create folder,
  create nested file, verified readback, no-overwrite move and second readback
  at both 390 px and 1,440 px.
- The cache-free backend inventory contained **279 unique test files** and
  **4,293 collected cases**. Four disjoint sorted shards covered that inventory
  exactly once and reported **4,284 passed, nine expected Windows
  symlink-capability skips and zero failures**. Their exact receipts were
  1,080 passed / one skipped, 772 passed, 1,132 passed / six skipped and 1,300
  passed / two skipped. Each shard emitted the same known Starlette test-client
  dependency deprecation warning.
- Production build, TypeScript project compilation, generated API parity,
  Python source compilation and `git diff --check` pass.
- The unchanged repository privacy scanner and its focused tests pass (**7/7**)
  after the historical generated artifact was resolved as described below.
- The exact prior loopback listener and its launcher were stopped, the new
  protected Agent launcher was started hidden, and the new build serves only on
  `127.0.0.1:8765`. Health returns 200 in offline/metadata mode, Agent HTML and
  its current hashed assets return 200, JSON negotiation remains 404, and the
  served Agent chunk contains the new folder and model-lifecycle controls.
- No real model was loaded for this checkpoint. At final cleanup no owned test
  process, model-runtime process or NVIDIA compute context remained.

## Privacy resolution

The previously rejected generated file
`test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3` was
resolved before this slice. Its exact target was validated as one ordinary file
inside the generated test-results directory and moved to the Windows Recycle
Bin. The move is recoverable. No broad directory deletion, exclusion or scanner
weakening was used, and the unchanged privacy scanner passes. No provider
session, credential, owner configuration, screenshot or private workspace
content was read.

## Owner review checklist

1. Reload the protected Agent page and open an existing workspace session.
2. Choose **New folder**, enter a relative path whose parent already exists and
   confirm that the review shows the canonical exact path and no recursive or
   overwrite authority.
3. Apply through the native confirmation. Confirm the folder appears and the
   success receipt names the exact path.
4. Try a missing parent and an existing destination. The first must explain that
   the parent is required; the second must preserve the existing path.
5. In a model-enabled session, ask for one new folder and one file move. Confirm
   the conversation shows **Create directory** and **Move file** approval cards,
   then deny one action and verify no corresponding path mutation occurs.

## Explicit limits and next work

- No recursive parent creation, file/directory deletion, directory move,
  overwrite, case-only Windows rename or lifecycle membership in the existing
  multi-file content transaction is added.
- Stable-workspace verification does not claim power-loss atomicity or control
  over every uncooperative local writer. Detected uncertainty remains unknown
  and blocks later lifecycle operations instead of becoming success or failure.
- Empty directories are not represented in Git history or in the reviewed-file
  change set. Their verified tool/event receipt and refreshed workspace tree are
  the in-memory evidence for this slice.
- Conversations, lifecycle authority and reviewed baselines remain memory-only.
  Durable Agent content is still an owner-gated privacy-vault decision.
- Automated native-bridge fixtures do not replace owner click-through or visual
  preference review. No real model is required by this checkpoint.
- No commit or push is included in this checkpoint.
