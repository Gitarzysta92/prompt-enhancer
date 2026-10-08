# Agent checkpoint 09x — non-blocking workspace draft protection

Date: 2026-08-28

## Outcome

The Files & review workspace no longer uses synchronous `window.confirm` for
its internal unsaved-work transitions. The live new-file Cancel path had been
reproduced as a blocking browser dialog that could hold the in-app interaction
surface. It now uses the repository's shared modal-dialog primitive and returns
control without blocking the browser client.

This slice changes only in-memory draft navigation. It grants no file, model,
process, provider, network, approval, controller, or MCP authority. No live
workspace file was previewed, created, changed, moved, recycled, or deleted.

## Repaired transitions

- Cancel a pending new-file, new-folder, move, or Recycle Bin draft.
- Open another file, folder, or staged creation while a disposable draft is
  present.
- Remove one staged transaction member or clear the complete staged plan.
- Discard the current manual editor draft.
- Hide the workspace when its optional direct close control is present.
- Keep is the initially focused action; Escape and backdrop dismissal keep the
  draft; closing returns focus to the initiating control.
- The dialog states that confirmation changes no workspace file and clears only
  the selected in-memory draft.

Removing the currently open staged edit now copies the staged text into the
manual editor before removing the transaction member. The resulting text is a
real unsaved draft, matching the existing UI promise and avoiding silent loss
of the staged content.

## Verification

- Focused workspace suite: **50/50 tests passed**. Coverage includes the exact
  new-file Cancel reproduction, Escape/keep, focus return, explicit discard,
  absence of the native confirmation call, staged-member keep/remove, staged
  text preservation, and keep/clear-all behavior.
- Complete Agent surface: **21/21 files and 301/301 tests passed**.
- Complete frontend: **160/160 files and 2,166/2,166 tests passed** in one
  serial run.
- TypeScript and production build: **547 transformed modules**, passed.
- Repository privacy scan and scoped whitespace check: passed.

## Live and process evidence

A fresh temporary in-app tab loaded `http://127.0.0.1:8765/agent` from the
rebuilt production resources. In the retained fictional workspace, a synthetic
new-file draft opened the in-app **Discard workspace changes?** dialog. **Keep
draft** received focus; Escape preserved both fields and returned focus to
Cancel. Reopening the dialog and choosing **Discard operation draft** removed
the form while the bounded tree remained confirmed empty. The temporary tab
was closed after validation.

The runtime remained **Stopped**. The application listener remained singular
and loopback-only on `127.0.0.1:8765`; no matching Vite, Vitest, Playwright-test,
or model-worker process remained after the gates. No LLM was loaded, so GPU
cleanup was not required.

## Remaining acceptance

The overall Agent goal remains active. The parent Agent page still has a small
set of synchronous confirmations outside this internal workspace component,
including dirty review-drawer/window transitions and live-chat close. They
should move to the same non-blocking confirmation model in the next bounded
slice. Owner-only acceptance still covers real artifact Preview/Reveal/Review/
Download and stale-file refusal, followed by one actual model-backed turn and
Stop, one fictional reviewed write, unload, and process/GPU cleanup evidence.
