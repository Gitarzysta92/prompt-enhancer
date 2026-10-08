# Agent checkpoint 12a handoff

## Outcome

Completed and failed Agent turns now have safe message-level revision controls.
**Edit in branch**, **Regenerate in branch**, and **Retry in branch** preserve
the original chat instead of rewriting its journal or appending a duplicate
request after a failed response.

Every revision resolves the exact current catalog record, reads the complete
bounded retained journal, verifies that its head still matches the catalog,
and creates a durable branch immediately before the selected user turn. Turn
one branches at event sequence zero; a later turn branches at the preceding
settled `done` receipt. The child is then resumed with protected authority off.

Edit leaves the exact retained text in the new branch composer. Retry and
Regenerate start the same text automatically only when the source message has
no attachments. If model start/send fails after the branch is open, the prompt
remains in the composer for an explicit manual send.

## Correctness boundaries

- Revision controls are available only for locally retained chats. A
  metadata-only chat has no text journal to revise and receives no false
  affordance.
- The source catalog revision and history revision are bound into the existing
  idempotent fork request. A catalog/history change, mismatched session,
  stalled page, changed retained head, or invalid turn mapping fails closed.
- Selection ownership is abortable. Switching chats while the catalog/history
  read is pending prevents the old action from creating a branch or taking over
  the new selection.
- The branch is created before the selected turn, so the retry request does not
  see the old user message or failed/completed answer as prior context.
- Source history is immutable. Existing file, command, web, and other workspace
  effects are neither hidden nor rolled back; the UI states this beside the
  controls.
- Existing fork/resume rules continue to omit approvals, reusable mutation
  authority, pending tool state, staged attachments, and artifacts.
- Attachments are never silently discarded or copied. Automatic Retry or
  Regenerate is disabled for an attached message; Edit creates the branch and
  tells the user to attach the media again.
- A dirty manual workspace editor still requires its existing discard
  confirmation before the visible chat can change.
- Consequential actions proposed by a regenerated response remain protected by
  their normal per-action review boundary.

## Validation

- Focused Agent page plus turn-receipt run: **151 tests passed**.
- Full Agent UI and Agent contract run: **46 files, 691 tests passed**.
- The first broad run had one unrelated archive/restore test exceed its
  five-second test timeout under suite load after 690 tests passed. That exact
  test passed alone, its local timeout was raised to ten seconds, and the full
  691-test run then passed.
- New integration coverage proves first-turn regeneration through sequence
  zero, later failed-turn retry through the preceding completion receipt,
  exact prompt send in the child, draft preservation after a stopped model,
  and cancellation after chat navigation.
- New component coverage proves completed-versus-failed labels, keyboard-
  reachable buttons, source/effect truth copy, and automatic attachment retry
  refusal while keeping Edit available.
- Repository-runtime backend branch suite: **5 tests passed**, covering durable
  idempotency, settled-prefix selection, root/invalid points, restart behavior,
  and concurrent repositories.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 518 kB Agent-page chunk warning remains tracked
  performance debt.
- Repository privacy scan passed. Targeted diff whitespace validation reported
  only the repository's existing Windows line-ending notices.
- The protected loopback app reloaded at `/agent`; the retained project/chat
  rail and stopped runtime rendered, and browser logs were empty. The visible
  retained chat had zero turns, so no real durable branch was created merely
  for this smoke test.
- Listener census showed only `127.0.0.1:8765` on the Prompt Enhancer ports and
  no known local-model runtime process. No model, GPU workload, command worker,
  or managed MCP host was started by this checkpoint. A generic name query did
  see `ifcmcp` processes not attributable to this slice; they were left
  untouched rather than guessed to be application-owned.

## Owner review

Use a disposable **Save locally** chat with at least two text-only turns:

1. Expand the first completed turn and choose **Regenerate in branch**. Confirm
   the UI opens a new branch, starts a response, and leaves the source chat in
   the project rail unchanged.
2. Open the source again, expand a later turn, choose **Edit in branch**, and
   confirm the new branch contains the old request as an editable unsent draft.
3. Stop or otherwise produce a disposable incomplete turn, choose **Retry in
   branch**, and confirm the branch begins before that failed turn rather than
   duplicating it in the same chat.
4. Repeat with an image or audio attachment. Confirm automatic retry is
   disabled and the explanation requires **Edit in branch** plus reattachment.
5. If the source turn changed files, confirm the warning says those existing
   workspace effects were not rolled back and any new protected effect still
   asks for its own review.

## Next slice

Agent-12b will audit and repair the remaining timeline ordering/recovery
semantics: duplicate and late terminal events, explicit long-operation
heartbeats, status settlement after reconnect/Stop races, and context evidence
presentation beyond the already exact-or-unknown path.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
