# Agent checkpoint 09y — non-blocking page transition protection

Date: 2026-08-28

## Outcome

The Agent page no longer uses synchronous `window.confirm` for its remaining
dirty-workspace and live-chat transitions. Every caller now uses the shared
modal-dialog primitive, so confirmation cannot block the in-app browser or
leave a native JavaScript prompt hidden behind another surface.

This slice changes only navigation and in-memory draft handling. It grants no
file, model, process, provider, network, approval, controller, or MCP authority.
It does not delete an Agent project or durable catalog entry.

## Repaired transitions

- Close the Files & review drawer while a manual workspace draft is dirty.
- Switch from the active live chat to another live chat.
- Open a retained or metadata-only catalog chat.
- Accept a dedicated-window chat handoff; acknowledgement is withheld until
  the dirty-workspace decision is accepted.
- Start a replacement chat while the current workspace draft is dirty.
- Close a live chat with truthful retained-history or metadata-only copy.
- Combine live-chat close and active dirty-workspace consequences in one
  confirmation instead of presenting two prompts.
- Keep is initially focused; Escape, backdrop dismissal, and Keep preserve the
  current state; focus returns to the initiating control.
- Clean transitions remain synchronous, preserving existing selection and
  model-control timing.
- Transport replacement or unmount resolves any pending decision as rejected,
  so an old confirmation cannot mutate a newer Agent context.

## Verification

- Complete Agent page: **114/114 tests passed**. New coverage exercises drawer
  close, focus return, Escape/keep, explicit discard, live-chat switching,
  combined close/discard consequences, absence of native confirmation, and
  dedicated-window acknowledgement ordering.
- Complete Agent surface: **21/21 files and 304/304 tests passed**.
- Complete frontend: **160/160 files and 2,169/2,169 tests passed** in the final
  application-wide run.
- TypeScript and production build: **547 transformed modules**, passed.
- Repository privacy scan: passed.

The large Agent page integration file now gives asynchronous catalogue/session
reads enough time on a loaded Windows worker, and two pre-existing assertions
wait for React's committed model-rebind and New chat drawer state. Assertions
and product behavior are unchanged; these fixes remove measured full-suite
timing races rather than masking failures.

## Live and process evidence

A fresh temporary in-app tab loaded `http://127.0.0.1:8765/agent` from the
rebuilt production resources. In the retained fictional empty workspace, a
synthetic new-file draft opened the page-level **Discard workspace changes?**
dialog from the drawer's actual Close control. **Keep current state** received
initial focus. Escape preserved both fields and restored focus to Close; the
explicit Keep action also preserved both fields and left review enabled. The
temporary tab was then closed. No preview, approval, or workspace write ran.

The runtime remained **Stopped**. The application listener remained singular
and loopback-only on `127.0.0.1:8765`; zero matching model workers and zero
Vite, Vitest, or Playwright-test workers remained after validation. No LLM was
loaded, so GPU cleanup was not required.

## Remaining acceptance

The overall Agent goal remains active. The next bounded slice is the real
artifact walkthrough already reserved for the owner: create fictional
text/image/PDF/Office output, validate Preview, Reveal, Review changes, and
Download, then stale one file and prove fail-closed refusal. After that, the
guarded owner run still needs one actual model-backed turn and Stop, one
fictional reviewed write, unload, and process/GPU cleanup evidence. No
automated step may start a real model or grant reusable mutation authority.
