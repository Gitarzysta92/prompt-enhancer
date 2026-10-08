# Agent checkpoint 11c handoff

## Outcome

Moving the chat that is currently open now preserves a coherent project and
session context immediately after the backend confirms the move.

Before this checkpoint, the move route returned the canonical updated catalog
record and the backend synchronized an active live session's in-memory project,
but the rail discarded that response. The Agent page could therefore keep an
old project ID in its live-session cache or retained-session selection. A later
reselection, retained-history reload, resume, export, or fork could target the
source project until another authoritative refresh happened.

The rail now publishes the canonical record only after the revision-bound move
succeeds. AgentPage applies that record to matching live-session caches and to
the selected retained record. The visible project follows the destination only
when that exact chat is open. Moving a background chat updates its cached live
identity, if present, without hijacking the user's current project.

## Correctness boundaries

- Failed, aborted, superseded, or stale move requests do not publish a session
  callback and do not change AgentPage selection.
- The callback carries only the strict catalog record already returned by the
  local route. It introduces no new backend authority or content read.
- The confirmed project and canonical title are reconciled together for every
  matching live-session view.
- A selected retained chat receives the returned catalog revision before its
  bounded history is reloaded from the destination project. Resume therefore
  uses the destination project and the new catalog revision.
- A background move never changes the visible project or foreground chat.
- Catalog synchronization still performs an authoritative live-session refresh;
  the local callback closes the UI consistency window and the backend refresh
  confirms the same result.
- No real project or chat was moved during validation.

## Validation

- Focused rail run: **21 tests passed**. This includes the canonical
  moved-session callback and a negative assertion that a failed mutation emits
  no callback and leaves the dialog recoverable.
- Focused AgentPage continuity matrix: **3 tests passed**:
  - an open live chat follows its destination and retains it after switching
    away and reselecting the chat;
  - an open retained chat reloads from the destination and resumes with the
    returned catalog revision;
  - moving a background chat preserves the foreground project and composer.
- Full frontend Agent integration: **169 tests passed** across the rail,
  complete Agent page, catalog parser, and retained-history parser.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 508 kB minified Agent-page chunk advisory remains
  performance debt rather than a correctness failure.
- Repository privacy scan passed. The diff check reported only the repository's
  existing LF-to-CRLF working-copy notices and no whitespace error.
- The rebuilt loopback app was reloaded at `/agent`. Its real one-project
  catalog opened the explicit no-destination move state with Save disabled; the
  dialog was cancelled without mutation and the browser log remained empty.
- Runtime census after validation: one loopback `pythonw` listener on port 8765,
  no listener on 8766, and no known model-serving process. No model, GPU
  runtime, MCP host, or visible terminal was started.

## Owner review

The app is already reloaded. A two-project walkthrough requires a disposable
second project and chat:

1. Open a disposable live chat and move it to the second project.
2. Confirm the rail follows the destination while the conversation remains
   open.
3. Select the source project, return to the destination, and reopen the moved
   live chat; confirm the rail does not jump back to the source.
4. Repeat with a retained **Save locally** chat, then resume it and confirm its
   conversation reloads normally.
5. Move a different background chat and confirm the foreground project and
   composer do not change.

## Next slice

Agent-11d will unify catalog-mutation continuity for rename, pin/unpin,
archive/restore, and deletion. The rail currently discards the canonical record
returned by non-move updates, while AgentPage's delete callback only removes an
in-memory composer draft. A currently open retained chat can therefore keep a
stale title or archive state, or remain visible with resume/export/fork controls
after its durable record has been deleted. The next checkpoint will publish
success-only canonical updates, reconcile the open chat without hijacking
background selection, and clear deleted selected state while preserving an
unrelated foreground chat.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
