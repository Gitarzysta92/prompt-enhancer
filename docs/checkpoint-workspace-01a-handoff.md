# Workspace checkpoint 01a handoff

## Outcome

Agent action cards now report one coherent terminal receipt instead of requiring
the user to reconstruct execution truth from raw output and separate approval
rows. New file, command and web actions expose monotonic elapsed time, exact
approval outcome and a bounded evidence classification. Missing historical
receipts remain explicitly unavailable; they are never estimated.

The checkpoint also repaired a reproducible Windows race between two sessions
publishing different changes from the same reviewed revision. Only one write
could ever succeed before this repair, but the rejected call sometimes received
a generic write-failure code. The receipt-only pre-read now shares the global
reviewed-write serialization boundary and stale authority is re-observed through
the no-follow lane, making the terminal classification stable.

## Contract

- The active Agent event contract is `local-agent.v9`. v8 is rejected as stale
  by the strict frontend parser rather than silently accepting two incompatible
  v8 shapes.
- `agent-tool-execution.v1` contains only `elapsed_ms`,
  `timing_source=server_monotonic.v1`, `approval_state` and `evidence_state`.
- Approval states: not required, not requested, approved, denied, timed out, or
  cancelled before a decision.
- Evidence states: read-only observation, verified workspace effect, unverified
  workspace effect, untracked external effect, no effect, or unknown.
- Denial, timeout, cancellation before decision and policy/validation rejection
  cannot claim an effect. Protected effects require recorded approval.
- Command and web calls are never presented as verified workspace changes.
- Raw tool output, arguments, previews, approval IDs and reusable authority are
  still removed from retained history. Old events without the optional receipt
  continue to load.

## Covered execution paths

- bounded reads, directory listing and text search;
- exact reviewed single-file writes and failure-atomic write batches;
- reviewed directory creation, file/directory moves and recoverable file trash;
- approved commands, cancellation and unconfirmed-cleanup quarantine;
- approved bounded URL fetches;
- scoped controller write, transaction and lifecycle proposals;
- durable local-history projection and strict frontend history parsing;
- live action-card rendering, legacy fallback and narrow responsive wrapping.

## Validation ledger

- Receipt model, approval/evidence invariants and unusable-clock tests: **51
  passed**.
- Focused OpenAPI, retained history, proposal, command, transaction and turn
  coverage: **95 passed**.
- Broad local Agent/workspace regression before the concurrency repair: **311
  passed**.
- Affected workspace/Agent matrix after the repair: **279 passed**.
- Repeated two-session reviewed-write race: **100/100 passed** after repair; the
  deterministic failed-start seam also passed.
- Frontend Agent action-card suite: **149 passed**; the final combined Agent
  page, layout, prompt-check and workspace-pane gate passed **208/208**.
- Frontend event, turn and retained-history contracts: **61 passed**.
- Production TypeScript/Vite build passed with **560 transformed modules**;
  generated OpenAPI client drift check passed.
- Repository privacy scan and diff whitespace check passed.
- Final standalone full backend result: **4,919 passed, 9 platform-only
  symlink skips, 0 failed** in 36m25s.
- Full frontend result: **2,397 passed** and one unrelated concurrent-load Team
  Analytics timeout; that exact test passed immediately in isolation. The Agent
  suite itself remained green.

## Live protected-app smoke check

- The owned native Agent launcher started one loopback listener at
  `127.0.0.1:8765`; `/health` and the current Agent JavaScript/CSS assets each
  returned HTTP 200.
- The existing localhost Agent tab was reloaded and left open on the reversible
  **New chat** drawer. The catalog rail, conversation region, workspace input,
  model selector and Browse control rendered with no disconnected banner,
  fatal boundary or browser-console error.
- Browse is intentionally disabled in the ordinary browser and enabled only in
  the visible native Agent window, where the narrow folder picker and protected
  approvals live. Model selection remains available in the ordinary browser.
- No model was started: zero `llama-server` processes were present. The launch
  created no visible console window; its one `uv`-owned console helper remained
  hidden while the single native Agent window stayed visible.

## Privacy and safety

All tests use fictional workspaces, identities, paths, commands, URLs and
outputs. No provider transcript, credential, private repository, model weight or
real network fetch was read. No model was loaded and no GPU memory was used.
The receipt contains no source or tool output and grants no authority.

## Click later

1. Open **Agent**, choose or create a disposable project/chat and perform one
   read-only file inspection. Confirm the result card shows **Not required** and
   **Read-only observation**, plus an elapsed value or honest unknown state.
2. Propose a disposable file edit and deny it. Confirm the terminal card shows
   **Not approved**, **Denied**, and **No effect**; verify the file is unchanged.
3. Propose and approve a disposable edit. Confirm the card shows **Approved**
   and **Verified workspace effect**, then open the diff/read-back evidence.
4. Run a harmless synthetic test command after approval. Confirm it is labelled
   **Untracked external effect**, not a verified workspace write.
5. If web access is enabled for a disposable chat, approve one public bounded
   fetch and confirm the same untracked-external classification.
6. Restart the app and reopen a local-history chat. Confirm new action facts
   survive while raw tool output and approval identifiers do not. Older chats
   should say **Execution details unavailable** rather than inventing values.

## Next

Continue Workstream C with Workspace-01b only after the live owner checklist is
recorded. The next bounded audit should reconcile richer diff/editor ergonomics,
revert/recovery discoverability and artifact handoff without weakening the
reviewed publication boundary. The wider finish goal remains active.
