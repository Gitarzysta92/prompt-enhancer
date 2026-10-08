# Agent checkpoint 11e handoff

## Outcome

Retained-history export is now revision-bound from the visible Agent chat to
the loopback export route, and its browser download has request ownership plus
a WebView-safe temporary-link lifecycle.

Before this checkpoint, the backend could validate expected catalog and
history revisions, but the frontend requested a bare export URL. A chat changed
in another window could therefore be exported under stale UI assumptions.
AgentPage also had no export request owner: changing chats while a request was
pending could let the old result download later, and the detached link's object
URL was revoked immediately after `click()`.

The transport contract now requires both visible revision heads. The HTTP
transport validates them before network access and emits both as exact query
parameters. AgentPage owns each request with an abort controller and a
project/session/revision key, cancels it when the selected record changes, and
ignores every stale completion. A successful export clicks a hidden link only
while it is attached to the document, removes it immediately, and revokes the
object URL after a bounded delay.

## Correctness boundaries

- Catalog revision must be a positive safe integer and history revision a
  non-negative safe integer. Invalid heads fail locally before authentication
  or export network access.
- The request carries the exact project, session, catalog revision, and history
  revision visible when the owner clicks **Export JSON**.
- Switching projects/chats, changing either visible revision, changing
  transports, deleting the selection, or unmounting cancels ownership. A late
  result cannot create a download or replace feedback for the next chat.
- Backend catalog/history conflicts produce specific recovery guidance rather
  than a generic file-download error.
- Object URL support is checked before creating a download. The temporary link
  is attached for the click, removed even if the click fails, and its URL is
  revoked after 1 second so embedded WebViews can consume it first.
- Export remains local and no transcript content is sent to a remote service.
- No real retained history was downloaded during live validation.

## Validation

- Focused AgentPage export matrix: **3 tests passed** for exact revision and
  connected-link behavior, revision-conflict feedback, and selection-switch
  cancellation with a stale late result.
- Full frontend Agent integration: **179 tests passed** across the project/chat
  rail, complete Agent page, catalog parser, and retained-history parser. The
  prior 176 behaviors remain green.
- Complete HTTP transport suite: **181 tests passed**. This includes three
  malformed-head cases that prove invalid export revisions make no network
  request.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 510 kB minified Agent-page chunk advisory remains
  performance debt rather than a correctness failure.
- Repository privacy scan passed. `git diff --check` found no whitespace error;
  the already-dirty Windows working tree continues to emit line-ending
  conversion notices.
- The rebuilt loopback app was reloaded at `/agent`. A real retained chat
  rendered **Export JSON** and browser logs were empty. The export was not
  clicked because that would create a new local copy of sensitive retained
  history.
- Runtime census after validation: one desktop `pythonw` wrapper and its one
  loopback worker on `127.0.0.1:8765`, no listener on 8766, and no known
  model-serving process. No model, GPU runtime, MCP host, or visible terminal
  was started.

## Owner review

Use a disposable locally retained chat:

1. Open it, click **Export JSON**, and confirm one JSON file downloads with the
   expected `agent-chat-<id>.json` name.
2. Open the file locally and confirm its project/session identity and
   `history_revision` match the selected chat.
3. Start another export only if it can be delayed, switch chats before it
   completes, and confirm the old chat does not download afterward.
4. If another window modifies the chat first, confirm export explains that the
   chat changed and asks you to reopen it.

## Next slice

Agent-11f will audit and close the next evidence-backed gap in the durable
project/session parity matrix, with restart survival and route-driven selection
continuity checked before any new Agent-12 presentation work.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
