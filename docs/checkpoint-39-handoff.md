# Checkpoint 39: reviewed no-overwrite directory moves

Status: scoped implementation complete. The automated gates and protected-app
restart below verify the current tree within the stated stable-workspace
boundary. The wider product remains open against the whole-application ledger
and owner-gated decisions.

## What changed

- The Agent workspace can rename or move exactly one ordinary directory entry
  to an absent workspace-relative destination whose parent already exists. The
  directory subtree moves with that entry, but preview and result contracts
  explicitly report `contents_reviewed: false`; no child is enumerated or
  admitted by the path review.
- `local-agent-workspace-lifecycle.v1` now includes strict directory-move
  preview/apply contracts. Authority is memory-only, metadata-only,
  session-bound, single-use, capped with the existing lifecycle previews and
  valid for at most 120 seconds. Apply requires the distinct native
  confirmation `apply_reviewed_workspace_directory_move`.
- Preview rejects the workspace root, same or case-only Windows paths, a target
  inside the source, traversal, links/reparse points, a missing or non-directory
  source, a missing parent and an existing target. It binds the canonical source
  and target plus the source and both parent identities.
- Apply reopens and pins both parent chains and the reviewed source directory,
  rechecks every identity, performs one native no-replace rename, and verifies
  the exact opened entry at the destination. Windows uses the source handle and
  pinned ancestry; Linux/macOS use their native no-replace rename primitives.
  A failed post-publication check rolls back only the exact still-open entry and
  claims restoration only after exact readback. Any unresolved publication or
  rollback hard-locks later lifecycle mutations in the session.
- The model tool schema now exposes first-class `move_directory` whenever
  workspace writes are enabled. It uses the same lifecycle service and approval
  boundary as the manual workspace, is preferred over shell emulation, and
  discards denied or cancelled preview authority.
- Private/no-store HTTP preview and apply routes bind the session, preview token,
  exact paths and native confirmation. Strict frontend parsers reject invented
  recursive/content authority, changed paths and extra fields.
- The workbench adds a keyboard-labelled **Move folder** flow inside non-root
  folders. It shows both exact paths, states that contents were not reviewed,
  rejects self-descendant destinations before transport, protects other drafts,
  handles native-confirmation unavailability, refreshes the tree/discovery/change
  views after success and locks writes after an unverified result. Coding-chat
  activity labels the same operation as **Move directory**.
- Fixed reason projection now preserves only the safe fixed recovery codes for
  missing, unavailable or non-directory sources and directory-move failures;
  arbitrary server detail remains suppressed.

## Defects reproduced and repaired

- The initial dedicated regression failed because directory-move preparation did
  not exist. The implementation was added only after that observable failure.
- The source could previously be described through a generic parent/item error.
  Missing, unavailable and non-directory source states now remain distinct from
  a missing destination parent in both transport and UI recovery copy.
- A reviewed source replaced before apply now has a dedicated identity-race
  regression. The replacement and displaced reviewed tree are both preserved,
  the destination remains absent and apply reports revision change.
- Native target collision, Windows source/parent swap, verification failure,
  exact rollback and unresolved rollback each have separate regressions. An
  external target is never overwritten, and uncertainty is never relabelled as
  success or clean failure.
- The responsive intercepted-HTTP fixture now carries a real nested directory
  model: create folder, create nested file, move folder, reopen the nested file,
  then move that file. Exact native confirmations and no-overwrite semantics are
  exercised at 390 px and 1,440 px.

## Verification receipts

- Focused backend lifecycle/Agent/OpenAPI gate: **78 passed** with one known
  dependency deprecation warning.
- Focused parser/transport/workspace/activity gate: **293 passed across four
  files**. TypeScript project compilation passes.
- Focused intercepted HTTP/browser directory workflow: **2 passed**, one each at
  390 px and 1,440 px.
- Frozen complete frontend gate: **1,872 passed across 135 files**.
- Frozen complete browser gates: **105 synthetic workflows** and **35
  intercepted loopback/HTTP workflows**.
- The cache-free backend inventory contained **279 unique test files** with no
  duplication. Four disjoint sorted shards covered it exactly once and reported
  **4,299 passed, nine expected Windows symlink-capability skips and zero
  failures**. Exact shard receipts were 1,080 passed / one skipped, 772 passed,
  1,132 passed / six skipped and 1,315 passed / two skipped. Each emitted the
  known Starlette test-client dependency deprecation warning.
- Production build, generated API parity, TypeScript and Python compilation,
  and `git diff --check` pass.
- The unchanged repository privacy scanner and its focused tests pass (**7/7**).
- The protected launcher was started hidden and owns the sole listener on
  `127.0.0.1:8765`. Health returns 200 with `offline_only` / `metadata`, Agent
  HTML returns 200 only for browser-style HTML negotiation, generic and JSON
  negotiation remain 404, and the current Agent JS/CSS assets return 200. The
  served Agent chunk contains both new folder-move controls.
- No real model was loaded. Every exact test PID observed during this checkpoint
  has exited, no checkpoint-owned test listener remains, no known local-model
  runtime is present and NVIDIA reports no numeric compute-memory allocation.
  One loopback development listener on the synthetic frontend port predates this
  checkpoint and was deliberately left untouched.

## Privacy boundary

All tests use fictional workspace paths and content. Directory-move authority
stores only relative paths, filesystem identities and expiry metadata. Neither
preview nor result contains child names or content. No provider session,
credential, owner configuration, private workspace, screenshot or remote model
was read. No network service received transcript or derived content.

## Owner review checklist

1. Reload the protected Agent page and open an existing workspace session.
2. Enter a non-root folder and choose **Move folder**. Confirm the card shows the
   exact source/destination and says the subtree was not enumerated or reviewed.
3. Choose an absent path under an existing parent, review it and approve the
   native confirmation. Confirm the workspace navigates into the moved folder
   and its prior files remain available.
4. Try the same path, a descendant of the source, an existing destination and a
   missing parent. None may mutate either tree.
5. In a model-enabled session, request one folder move. Confirm the chat shows a
   **Move directory** approval card; deny one attempt and verify no move occurs.

## Explicit limits and next work

- This adds no deletion, trash/recycle-bin integration, overwrite, recursive
  parent creation, directory copy, merge, case-only Windows rename or lifecycle
  membership in the multi-file content transaction. Recoverable deletion stays
  a separate design checkpoint because it grants materially different authority.
- A directory move is path-topology review, not content review. Empty directories
  and subtree membership are not represented as reviewed-file changes or Git
  history by this operation.
- Stable-workspace verification cannot exclude every uncooperative local writer
  or claim crash/power-loss atomicity. Detected uncertainty remains explicit and
  locks later lifecycle work.
- Linux/macOS branches are implemented and covered by platform-independent
  contract logic, but native POSIX acceptance remains open on this Windows host.
- Conversations, lifecycle authority and reviewed baselines remain memory-only.
  Durable Agent content remains an owner-gated privacy-vault decision.
- Automated native-bridge fixtures do not replace owner click-through or visual
  preference review. No commit or push is included in this checkpoint.
