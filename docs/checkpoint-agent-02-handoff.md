# Agent-02 handoff: chat-first Agent shell

Date: 2026-08-27
Status: scoped implementation and bounded automated/browser verification complete; native owner reload remains deferred

## Outcome

The Agent page now behaves as a chat-first coding workspace. A collapsible left
rail exposes durable Agent projects and chat navigation, the conversation owns
the primary surface, the new-chat form opens as a subordinate setup sheet, and
Files & Review is closed by default in a resizable secondary drawer.

The rail uses the real Agent-01 catalog. Projects and chat navigation can be
created, selected, searched, renamed, pinned, archived, restored, moved and
deleted through revision-bound contracts. A live chat opens its retained
in-memory conversation. A catalog entry whose process has ended opens a
truthful, non-sendable `history unavailable` view; it never invents an empty
transcript or silently starts a replacement chat.

![Synthetic Agent-02 chat-first shell](checkpoint-agent-02-shell.png)

## Implemented boundary

- The expanded rail is 272 px and collapses to a compact 60 px navigator.
  Projects and chats have explicit live, archived, pinned and
  history-unavailable states.
- The active conversation remains dominant. Model readiness, Stop, turn count,
  observed tool activity and model-provided reasoning availability remain in
  its header.
- New Chat expands the rail and opens a side sheet over the existing chat on
  desktop and a bottom sheet at narrow widths. Closing it restores composer
  focus.
- Files & Review is closed by default, opens without clearing the chat draft,
  and can be resized from 352–760 px with pointer or keyboard controls. At
  narrower widths it becomes a subordinate stacked panel.
- The existing workspace tree, editor, reviewed changes, discovery, Team
  Folders and protected-action paths remain the implementation substrate; they
  were not replaced with mock behavior in production.
- Live catalog rename and project-move operations now update the active
  in-memory session settings as well as the durable metadata record.
- `GET /v1/agent/orchestration` publishes a provider-neutral,
  privacy-preserving controller manifest for loopback HTTP clients. It exposes
  operation paths and authentication placeholders, never the actual token,
  transcript content or a remote listener. Controller credentials cannot
  satisfy native user-presence confirmation for protected actions.

## Persistence truth after Agent-02

| State | Durable now? | UI behavior |
| --- | --- | --- |
| Agent projects and project metadata | Yes | Browsable and editable in the rail |
| Chat navigation metadata | Yes | Browsable, searchable and manageable in the rail |
| Live conversation messages/events | No | Available only while the owning app process retains them |
| Conversation after app restart | No | Explicit non-sendable history-unavailable stub |
| Pending approvals and workspace authority | No | Never restored or replayed after restart |
| Runtime/model lease | No new persistence | Existing model controls remain; Agent-03 owns coordinated switching |

## Correctness repairs found during validation

The first browser pass found that selecting a metadata-only chat briefly set
the correct state, then the page's automatic newest-live-session selection
overwrote it. Session selection now suspends that fallback while a durable
history stub is selected. A component regression test and the responsive
browser test both cover selecting the stub and returning to the live chat.

Hot reload of the synthetic workflow fixture also recreated a React root and
left a console error. The fixture now unmounts its root through Vite's dispose
hook. A fresh browser navigation reports no warnings or errors.

## Verification receipts

- 1,905 frontend tests across 137 files pass in the final complete run.
- 93 focused Agent page and catalog-rail tests pass, including durable project
  creation, metadata-only navigation, draft retention and keyboard resizing.
- Two responsive Chromium acceptance runs pass at 360 px and 1,440 px. They
  browse live and unavailable chats, collapse/expand the rail, open/read/close
  Files & Review, retain the composer draft, and open/close New Chat with focus
  restoration and no page-wide overflow.
- 370 bounded Agent, workspace, catalog and OpenAPI Python tests passed during
  this checkpoint. Eight orchestration/OpenAPI contract tests and the generated
  API parity check passed.
- 31 focused privacy tests passed. TypeScript, the production frontend build,
  Python compilation and generated OpenAPI checks passed.
- The browser fixture used fictional identifiers, paths, files, messages and
  tool events. Its fresh console contained zero warnings/errors.
- Final resource receipt: zero Prompt Enhancer/model-runtime processes and zero
  listeners on port 8765. The single listener on 4173 was the already-running
  synthetic Vite fixture and was reused; no native app, server or model was
  launched for this checkpoint.

## Owner checklist for the later native reload

1. Create two Agent projects and two chats; rename, pin, move, archive and
   restore them from the rail.
2. Close one live chat, restart the app, select its navigation entry and verify
   the explicit history-unavailable view.
3. Type an unsent draft, open and close Files & Review, and confirm the draft
   and composer focus remain.
4. Send and Stop one local-model response, then repeat rail and drawer use at a
   narrow window width.

This checklist is intentionally not marked passed. The native Agent window was
not relaunched because the earlier terminal-window cascade requires a bounded
owner-visible recheck.

## Next checkpoint

Agent-03 implements the single global runtime coordinator and truthful model
switcher: serialized drain/unload/load, selectable GPU/GPU+CPU/CPU placement,
requested-versus-served state, draft retention, capability handshake, and
measured-or-unknown cleanup. Conversation persistence remains Agent-04.
