# Agent checkpoint 09v — session-scoped composer drafts

Date: 2026-08-28

## Outcome

Unsent text and staged media now belong to one exact live Agent chat. Switching
projects or chats cannot carry private composer content into another
conversation, and returning to the owning chat restores its in-window draft.

Drafts remain memory-only for the mounted Agent window. This slice creates no
browser-storage or database copy of unsent content and grants no project, file,
approval, runtime, process, provider, or network authority.

## Draft ownership contract

- Each live session has an independent text-and-attachment draft keyed by its
  exact session identity.
- The project/chat rail shows only the content-free label **draft in this
  window**. It never renders draft text, attachment names, or attachment bytes.
- A successful send clears only the exact text and ordered attachment identity
  snapshot that was admitted. A next draft typed while that request is in
  flight survives its late completion.
- Late attachment refresh or staging results from chat A are discarded after a
  switch to chat B. They cannot populate B's composer.
- Closing a live chat preserves its in-window draft because the durable chat
  may be resumed. Permanently deleting the catalog chat purges its draft only
  after deletion succeeds; failed deletion retains it for retry.
- Page reload or window close discards every unsent draft. No `localStorage`,
  `sessionStorage`, retained-history event, telemetry, or log receives it.

## Verification

- Focused cross-chat draft, media, delayed completion, and delete-boundary
  coverage passed **14 tests**.
- The complete Agent page, project/chat rail, and attachment-composer suite
  passed **124/124 tests**.
- Two unrelated asynchronous expectations passed in isolation and received
  bounded five-second test budgets so full-suite load cannot create false
  negatives; production behavior was unchanged.
- The complete frontend suite passed **160/160 files and 2,160/2,160 tests** in
  one serial run.
- TypeScript compilation and the production build passed with **547 transformed
  modules**. The repository privacy scan passed.

## Live and process evidence

The in-app browser reloaded `http://127.0.0.1:8765/agent` and loaded the rebuilt
`AgentPage-CVcDphTJ.js` asset. The existing synthetic retained chat, project
rail, runtime controls, conversation, Files & review entry point, and disabled
model-stopped composer remained present.

The app remained bound only to `127.0.0.1:8765`. Final process classification
found no Vitest/Vite worker and no local model runtime. No LLM was loaded and no
GPU memory cleanup was required.

## Remaining acceptance

This closes an autonomous cross-chat privacy and usability defect; it does not
replace the owner-only native acceptance. The next owner gate remains artifact
Preview/Reveal/Review/Download plus stale-file refusal, followed by one actual
model turn and Stop, one fictional reviewed write, model unload, and process/GPU
cleanup evidence. Other autonomous legacy-surface audits can continue without
starting a model or changing provider configuration.
