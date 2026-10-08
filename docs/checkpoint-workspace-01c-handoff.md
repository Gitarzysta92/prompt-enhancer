# Workspace checkpoint 01c handoff

## Outcome

Every Agent file-content review now uses one structured, local diff viewer. The
manual editor, new-file review, multi-file transaction, Agent proposal, pending
native write approval, reviewed change set and baseline recovery no longer
present unrelated raw `<pre>` blocks with different behavior.

The shared viewer provides old/new line numbers, semantic hunk/addition/
deletion/context treatment, exact-copy, explicit long-line wrapping and a
keyboard-scrollable bounded viewport. Recovery cards also state which recovery
review is available before it is opened: exact baseline restore, missing-file
recreation or recoverable Recycle Bin movement.

## Truthful rendering contract

- Complete unified hunks are parsed against their declared old/new ranges.
  Multiple file sections and deleted content that resembles a file header are
  handled without losing line-number authority.
- Raw model previews without hunk headers stay exact raw text and say that line
  counts are unavailable; zero is never substituted.
- Truncated or internally incomplete hunks stay exact raw text with an explicit
  warning. Partial derived counts are not presented as authoritative.
- If a complete rendered diff contradicts server-reported counts, both facts
  remain visible and the contradiction is announced.
- Reviews above 2,000 rendered lines retain the complete bounded raw diff rather
  than mounting thousands of table rows. The existing 60,000-character
  transport bound remains unchanged.
- Copy always uses the exact source diff, not reconstructed table text.

## Recovery and inspection ergonomics

- Modified paths advertise a baseline-restore review.
- Missing original paths advertise baseline recreation.
- Session-created paths advertise a Recycle Bin recovery review instead of the
  misleading generic **Restore baseline** label.
- Unavailable baselines, unsafe current paths, unsupported transports and
  already-reverted paths explain why recovery cannot be opened.
- A detailed net diff and an eligible restore review can open the exact current
  file directly. Missing files do not offer a nonexistent file action.

These controls add no publication authority. Apply still requires the existing
single-use preview, revision revalidation and native user-presence gate.

## Accessibility and responsive behavior

- The diff viewport is focusable and keyboard-scrollable.
- Old and new line-number cells expose explicit accessible labels.
- Copy and wrapping controls meet the 44-pixel target.
- The toolbar stacks at narrow width; standard and compact transaction views
  have bounded scrolling.
- Addition/deletion structure remains distinguishable in forced colors.

## Validation ledger

- Complete frontend Agent suite: **450 passed** across 27 files.
- Dedicated parser/viewer coverage includes multi-hunk and multi-file line
  accounting, header-like deleted text, raw reviews, truncated hunks,
  contradictory counts, exact copy, wrapping and the 2,000-line guard.
- Backend reviewed-change/recovery suite: **21 passed**.
- Generated OpenAPI client drift check passed; this frontend-only checkpoint
  changed no backend route or authority contract.
- Production TypeScript/Vite build passed with **563 transformed modules**. The
  existing non-fatal large-chunk warning remains.
- Repository privacy scan and whitespace check passed. Existing Windows
  LF-to-CRLF worktree warnings remain informational.

## Live protected-app smoke check

- The exact owned listener was restarted hidden; one healthy `pythonw` listener
  served `127.0.0.1:8765` and `/health` returned HTTP 200.
- A temporary reserved synthetic text file was opened in the retained synthetic
  workspace. Its non-applied manual edit rendered a live structured diff with
  +2/−1 summary, one hunk, correct old/new line numbers, exact-copy success and
  a working wrap toggle.
- Native apply remained disabled in the ordinary in-app browser, proving that
  richer review did not bypass the protected-window gate.
- The synthetic draft was cleared through a final app restart and the exact
  temporary file was removed. It is absent from the cleaned workspace.
- The cleaned Agent tab is left open on **Files & review → Changes**. It reports
  zero browser-console errors; 12 script and two stylesheet resources were
  observed after reload.
- Zero `llama-server` processes and zero visible terminal windows remained
  after both live verification and cleanup restart.

## Privacy and safety

Only a reserved synthetic path and fictional text were used. No provider
session, credential, private transcript, unrelated file, model weight or real
workspace source was read. The smoke test never applied a file edit, started a
model, ran a command or used the network. No GPU memory was allocated.

## Click later

1. Open a disposable UTF-8 file, change several nearby lines and select
   **Review diff**. Confirm old/new numbers, semantic colors, +/− summary,
   horizontal scrolling and **Wrap long lines**.
2. Choose **Copy** and paste into a disposable editor. Confirm the copied text
   is the exact unified diff, including headers and hunk markers.
3. Stage two disposable files, open the transaction review and inspect each
   collapsible diff. Confirm each file keeps its own summary and compact scroll
   boundary.
4. Let an Agent propose a disposable write in the native window. Confirm the
   pending approval uses the same viewer and that **Approve**/**Deny** remain the
   only effect controls.
5. After one reviewed publication, open **Changes**. Confirm the card names the
   correct recovery effect, the net diff can reopen the current file, and the
   restore preview still requires native confirmation.
6. Repeat at phone width and with Windows forced colors or high contrast.
   Confirm toolbar wrapping, focus visibility, line structure and 44-pixel
   controls remain usable.

## Next

The wider finish goal remains active. Workspace-01 is automated through 01c,
with its combined native owner walkthrough still pending. The next bounded
implementation checkpoint should begin Artifact-01: capability-aware media and
document inputs, versioned generated artifacts, safe previews and viewer-format
coverage. No Artifact-01 implementation is included here.
