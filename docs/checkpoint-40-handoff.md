# Checkpoint 40: reviewed recoverable single-file removal

Status: scoped implementation and automated verification complete. The
protected Agent serves the final build on loopback. The wider product and the
chat-first redesign remain open against the whole-application ledger and the
separate Agent experience plan.

## What changed

- The Agent workspace can move exactly one reviewed ordinary UTF-8 file to the
  Windows Recycle Bin. It cannot permanently delete a file, remove a directory,
  recurse through a subtree or use this authority from a shell command.
- `local-agent-workspace-lifecycle.v1` now includes strict file-trash
  preview/apply contracts. Authority is memory-only, metadata-only,
  session-bound, single-use, capped with the existing lifecycle previews and
  expires after at most 120 seconds. Preview binds the canonical relative path,
  exact revision, file/parent identities, byte count and mode. Apply requires
  the distinct native confirmation `apply_reviewed_workspace_file_trash`.
- Preparation accepts only one bounded regular strict-UTF-8 file on a local
  Windows drive. Root, directory, binary/NUL-bearing, hard-linked,
  link/reparse, changed-parent and changed-file cases fail closed.
- Apply pins the reviewed file and parent, rechecks identity/content/size/mode,
  then moves the exact still-open entry to a private staging name. This staging
  step creates a safe exact rollback window before Windows receives the item.
  Native `IFileOperation` is configured for undo/recycle semantics and is
  accepted as success only after the original and staging names are absent, the
  open descriptor retains the reviewed identity and bytes, and its final path
  is verified below the same drive's `$Recycle.Bin`.
- A settled native failure rolls back only the exact still-open reviewed entry
  and claims rejection only after restored identity/content/path readback. A
  failed verification or rollback becomes `unverified`, never success. The
  native Shell worker has a 15-second caller deadline; if it is still alive,
  rollback is deliberately not attempted while that worker may act late and
  the lifecycle service hard-locks later mutations in the session.
- The model tool schema exposes first-class `trash_file` whenever workspace
  writes are enabled. It uses the same preview, exact approval and apply service
  as the manual workbench. The system instruction forbids permanent deletion
  and shell emulation of lifecycle actions.
- Private/no-store HTTP preview and apply routes bind session, preview token,
  exact path/revision and native confirmation. Generated OpenAPI and strict
  frontend parsing reject mismatched or invented recovery/permanence state.
- The workbench adds **Move to Recycle Bin** with exact path, revision, bytes,
  recovery and `Permanent: No` review. It protects drafts and staged
  transactions, closes the removed file after verified success, refreshes the
  tree/discovery/change set and hard-locks on uncertainty. Coding-chat activity
  labels the same tool explicitly.
- The reviewed change set records a verified source deletion or an unverified
  lifecycle result; it never treats an assistant completion claim as evidence.

## Correctness repairs made during verification

- An initial native approach could wait without a caller deadline. The Shell
  operation now runs on a dedicated STA worker with a bounded join. A timeout is
  an explicit unverified state, and two regressions prove the join bound and
  prohibit unsafe rollback while a late worker may still run.
- The first UI success copy could be read as if Windows necessarily preserved
  the source filename. The safe rollback design actually hands Windows a
  private staging entry. Both review and success copy now disclose that the
  Recycle Bin may show an app-generated name rather than the original filename.
- The first full intercepted-HTTP browser run found one stale pre-checkpoint
  copy assertion. The application correctly rendered the expanded native-
  presence and no-permanent-delete boundary. The assertion was updated to
  require both truths, passed its corrective run, and the complete 35-case suite
  then passed from the beginning.
- The first protected instance passed readiness and asset probes, then was no
  longer listening at the final check. Its content-free native marker reports a
  terminal `runtime_stop_failed` for `automation_grant_worker`; it contains no
  exception, path, process, port or content and cannot establish whether the
  native window was closed by a person or why worker cleanup failed. That event
  is not relabelled as a clean stop or a spontaneous-crash diagnosis. A fresh
  owned instance was started afterward, preserved the failed prior outcome and
  remained at non-terminal `window_created` through 120 consecutive half-second
  readiness samples.
- A later owner-visible repeated-launch check exposed multiple independent
  native Agent windows. The launcher had no shared instance lease and every
  invocation could reserve another ephemeral backend. The instances were
  contained and the listener was stopped. Agent-00 supersedes the operational
  claim that this checkpoint's launcher should remain running.

## Verification receipts

- A real Windows probe used one fictional temporary UTF-8 file. Native recycle
  publication returned `verified`; the workspace source was absent and the
  still-open reviewed descriptor resolved inside Windows Recycle Bin. The
  fictional probe entry remains recoverable there.
- Final targeted workbench regression: **39 passed / one file**.
- Frozen complete frontend gate: **1,882 passed across 135 files**.
- Frozen complete browser gates: **105 synthetic workflows** and **35
  intercepted loopback/HTTP workflows**. The latter includes create folder,
  create nested file, move folder, no-overwrite file move, recycle review/apply,
  verified source disappearance and narrow-layout truth at 390 px and 1,440 px.
- The cache-free backend inventory contained **279 unique test files**. Four
  disjoint sorted shards covered it exactly once and reported **4,308 passed,
  nine expected Windows symlink-capability skips and zero failures**. Exact
  shard receipts were 1,080 passed / one skipped, 772 passed, 1,132 passed / six
  skipped and 1,324 passed / two skipped. Each emitted the known Starlette
  test-client dependency deprecation warning.
- Production build, generated API parity, frozen dependency lock, TypeScript
  project compilation and Python source/test compilation pass.
- The unchanged repository privacy scanner passes, as do **19 focused privacy
  tests**. No exclusion or scanner weakening was added.
- At this checkpoint's original handoff, a fresh protected launcher owned the
  sole listener on `127.0.0.1:8765` and passed the recorded HTTP and 60-second
  readiness checks. It was later stopped during the repeated-window incident;
  this historical receipt is not a current-running claim. Agent-00 adds the
  missing single-instance gate and a clean hidden native close probe.
- No model was loaded. No known `llama-server` process or checkpoint-owned 4175
  listener remains. The pre-existing development listener on 4173 was left
  untouched. NVIDIA reports zero compute contexts and 0 MiB numeric compute
  allocation.

## Privacy boundary

All tests and the native probe use fictional content and generated workspace
names. File-trash authority stores only relative path, filesystem identities,
revision, byte count, mode and expiry metadata. No provider session,
credential, owner configuration, screenshot, private workspace or remote model
was read. No network service received transcript or derived content.

Four checkpoint-owned Playwright output directories remain because recursive
directory removal was rejected by the execution policy even after exact
path/type validation. Playwright's normal output reset removed the one failure
context; each directory now contains only its content-free `.last-run.json`
status file. They are ignored, disposable runner state, not application data.

## Owner review checklist

1. Reload the protected Agent page and open an existing clean UTF-8 file.
2. Choose **Move to Recycle Bin**. Confirm the review shows the exact path,
   revision, bytes, `Windows Recycle Bin`, `Permanent: No`, and the possible
   generated recovery name.
3. Approve the native confirmation. Confirm the source disappears and inspect
   Windows Recycle Bin before attempting recovery.
4. Restore or move the entry manually if desired. Do not expect Windows to
   restore it automatically to the original workspace path or filename.
5. Deny one attempt and confirm the file remains unchanged.
6. Confirm no equivalent action appears for a directory and no permanent-delete
   control exists.
7. In a model-enabled session, request one recoverable file removal. Confirm the
   chat shows a **Move file to Recycle Bin** approval card and deny one attempt.

## Explicit limits and next work

- Recovery guarantees the exact reviewed bytes are verified in Windows Recycle
  Bin. Because the app uses a private staging name, it does not guarantee the
  Recycle Bin entry keeps the source filename or that Windows can automatically
  restore it to the original workspace path. Recovery is owner-inspected and
  manual.
- Directory removal, permanent deletion, POSIX trash integration, removable or
  network-drive behavior, lifecycle operations inside multi-file content
  transactions and crash/power-loss atomicity remain out of scope.
- The native implementation is accepted on this Windows host. Symlink-only
  branches remain represented by the nine explicit platform skips and require a
  symlink-capable host.
- Conversations, lifecycle authority and reviewed baselines remain memory-only.
  Durable Agent content requires the privacy/retention architecture in the
  [Agent chat experience plan](agent-chat-experience-plan-2026-08-27.md).
- Agent-00 subsequently produced a clean, disposable full-composition native
  close with listener release after preventing duplicate runtimes. The earlier
  `automation_grant_worker` failure remains historical evidence of the
  unguarded multi-instance composition; one owner-visible open/focus/close check
  remains part of the Agent-00 checklist.
- Automated native-bridge fixtures do not replace owner click-through or visual
  preference review. No commit or push is included in this checkpoint.
