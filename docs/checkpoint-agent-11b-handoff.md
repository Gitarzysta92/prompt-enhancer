# Agent checkpoint 11b handoff

## Outcome

Moving a chat now uses a complete active-project directory even while the left
rail is showing filtered search results.

Before this checkpoint, both the **Move to project** affordance and its
destination selector reused the visible `projects` array. Global search
deliberately filters that array, so a chat result could lose valid move
destinations merely because the destination project did not match the search
text. In the one-project case, the action silently disappeared and provided no
explanation.

Opening **Move to project** now performs a separate bounded catalog read for
active projects. Search remains a display filter and can no longer reduce the
set of valid destinations. The dialog owns loading, read-failure/retry,
no-destination, and ready states. Save remains disabled until an exact active
destination is available.

## Correctness boundaries

- The independent read requests at most 200 non-archived projects and carries
  an abort signal. It does not load prompts, transcript content, workspace
  files, approvals, model state, or tools.
- The source project and archived projects are removed from the selector.
- A failed directory read cannot submit a stale or guessed project ID. The
  dialog explains the failure and offers a local retry.
- With no other active project, the Move action remains discoverable and the
  dialog explains that the owner must create or restore a project first.
- The existing revision-bound update contract remains the only move mutation.
  No backend authority was widened.
- No project or chat was created, moved, renamed, archived, restored, or
  deleted during the live check.

## Validation

- Focused rail run: **20 tests passed**. Coverage includes the ordinary move,
  complete destinations under global search, read failure plus retry, and the
  one-project empty state.
- Frontend Agent integration: **165 tests passed** across the rail, complete
  Agent page, catalog parser, and retained-history parser.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 508 kB minified Agent-page chunk advisory remains
  performance debt, not a new correctness failure.
- Repository privacy scan passed and the two-file diff whitespace check passed.
- The rebuilt loopback app was reloaded at `/agent`. Its real one-project
  catalog exposed **Move to project**, rendered the explicit no-destination
  state, and kept **Save** disabled. The dialog was cancelled without a data
  mutation and the browser log remained empty.
- Runtime census after validation: one loopback `pythonw` listener on port 8765,
  no listener on 8766, and no known model-serving process. No model, GPU
  runtime, MCP host, or visible terminal was started.

## Owner review

The app is already reloaded.

1. Open a saved chat's actions and choose **Move to project**.
2. With one active project, confirm the dialog explains that no destination is
   available and **Save** is disabled.
3. After creating a second project, repeat the action and confirm the second
   project appears.
4. Search for a chat, open its actions while search remains active, and confirm
   every other active project is still offered as a destination.
5. Move only a disposable chat, then reload and confirm it remains under the
   destination project.

## Next slice

Agent-11c will repair move continuity for the chat that is currently open. The
backend already revision-updates the durable catalog and synchronizes a live
session's in-memory project setting, but the rail currently discards the
returned record. The Agent page therefore has no immediate way to reconcile its
`current` live-session or retained-session selection after moving that exact
chat. The next checkpoint will propagate the confirmed record, follow the
destination only for the open chat, preserve background-chat selection, and
test resume/export/fork/navigation state plus reload behavior.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
