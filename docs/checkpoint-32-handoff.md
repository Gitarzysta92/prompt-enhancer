# Checkpoint 32: truthful memory-only Agent session effects

Status: scoped implementation and automated verification complete. The whole
application remains open against the verification ledger. The single existing
privacy-artifact finding remains open.

## What changed

- Agent conversations now expose a session-level effects card derived only from
  validated retained turn summaries. It distinguishes observed action requests,
  reviewed write receipts, paths with a verified create/modify effect,
  unverified writes and command attempts with uninventoried effects.
- A verified `unchanged` write is now shown as a no-op and does not increment the
  changed-file count. Repeated receipts are grouped by path; the latest receipt
  is labelled, and repeated writes within one turn list that turn once.
- Coverage is explicit: complete retained history, current turn not summarized,
  retained summaries incomplete or partial history. Expired pages, invalid
  summaries, duplicate turn identities and duplicate turn numbers cannot be
  presented as complete.
- File rows reuse the existing safe workspace-open path. Links are disabled when
  the session is closing or disconnected. Unverified writes require inspection,
  and command attempts are called out as effects the ledger cannot inventory.
- The card explicitly states that it is not a net Git diff, excludes manual,
  external and command-created changes, and remains in server memory only.
  Durable Agent transcripts were not added: storing content remains an explicit
  owner-gated privacy-vault decision.
- The first integration placed the expanded card in the fixed-height Agent
  header. A responsive browser test reproduced a real failure at 1440 px: the
  transcript collapsed and turn-details clicks were intercepted. The card now
  expands inside the transcript scroll boundary, keeping the composer separate.

## Verification receipts

- Focused Agent component checks after the final integrity hardening:
  **95 passed / 3 files**. The new session-effects component has four direct
  regressions, including conflicting turn numbers and repeated same-turn paths.
- Full frontend: **1,760 passed / 129 files** in **140.76 s**.
- Focused Agent/backend API contract selection: **116 passed** in **50.30 s**,
  with the existing Starlette/httpx deprecation warning.
- Strict TypeScript passed for the workflow fixture/spec and loopback HTTP spec.
  Production build and generated API consistency passed.
- Full synthetic browser suite: **105 passed** in about **1.1 min**.
- Full loopback HTTP browser suite: **30 passed** in **48.8 s**. No real model or
  GPU was used by either suite.
- The in-app browser independently expanded the card at 1440x900 and 360x740.
  At 360 px the transcript remained scrollable, ended **9.6 px** above the
  composer and emitted no browser warnings/errors. The viewport was restored and
  the temporary tab was closed.
- Tracked-diff and checkpoint-new-file whitespace checks passed. The privacy
  scanner reports exactly the one unchanged old synthetic SQLite artifact under
  `test-results`; no exclusion, deletion retry or scanner weakening was used.
  The final resource check found zero `llama-server` processes and no listeners
  on the real-test or owner-app ports 4175/8765. The pre-existing synthetic
  development listener on loopback port 4173 was preserved.

## Explicit limits and next work

- This is a receipt view over retained in-memory events, not crash-durable
  history, a persisted conversation, a working-tree scan or a net Git diff.
- Direct reviewed writes are inventoried. Manual edits, external changes and
  command-created effects remain outside the ledger. A true multi-file change
  inventory and richer editing are separate work.
- Durable Agent content cannot be implemented as an implicit enhancement. The
  pending decision requires an opt-in, default-off encrypted vault, OS-protected
  keys, redacted content, delete-all controls and security review.
- Native folder-picker and protected-action confirmation still require owner
  presence for acceptance. Packaged-launcher reliability, the known native
  shutdown marker, POSIX publication acceptance and final owner visual
  preferences remain separate.
- No real provider data, credentials or owner configuration were used. No GPU
  model was loaded. The normal owner app was not restarted.
