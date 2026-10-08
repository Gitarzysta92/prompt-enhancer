# Agent checkpoint 11a handoff

## Outcome

The Agent project rail now performs the global search its label promises.

Before this checkpoint, entering text into **Search projects and chats** sent
the selected project ID with both catalog requests. Project search was already
global and the backend already returned a project when one of its chat titles
matched, but chat search remained restricted to the currently selected
project. A matching chat in any other project was therefore invisible.

While search text is present, the rail now requests the bounded global chat
catalog, labels the result section **Matching chats**, shows each chat's owning
project, and selects that project before opening the live or retained chat.
Clearing search returns to the selected project's ordinary chat list.

## Reconciled durable behavior

The audit confirmed that the existing Agent catalog already implements more of
Agent-11 than the earlier milestone board recorded:

- durable project and chat navigation across restart;
- create, browse, switch, rename, pin/unpin, archive/restore, move, and
  revision-bound permanent deletion;
- bounded retained local history as an explicit alternative to metadata-only
  navigation;
- revision-bound resume, export, and branching through a completed turn;
- durable branch lineage without copying approvals, protected authority,
  staged attachments, or artifact ownership;
- project and chat title search in SQLite, including parent-project matches for
  chat titles;
- fail-closed history-write, resume/delete race, and cross-project checks.

Agent-11 is therefore in reconciliation/repair rather than greenfield
implementation. This checkpoint does not claim the whole milestone complete;
the remaining route/UI/restart matrix still needs one current end-to-end audit.

## Correctness boundaries

- Empty search remains project-scoped, so ordinary browsing and chat counts do
  not silently change.
- Non-empty search omits `projectId` deliberately and retains the existing
  200-result, archived-state, debounce, cancellation, and strict-parser bounds.
- Search does not change the selected project by itself. Opening a result from
  another project changes project selection first, then opens that exact chat.
- Search input and results remain navigation-only. No prompt, transcript,
  workspace file, approval, model, or tool content is exported or indexed by a
  remote service.
- No project/chat was created, renamed, archived, restored, or deleted during
  the live check.

## Validation

- Backend durability reconciliation: **30 tests passed** across Agent catalog,
  retained history, and session forking.
- Frontend integration: **162 tests passed** across the rail, complete Agent
  page, catalog parser, and history parser.
- Focused post-fix rail run: **17 tests passed**, including an exact assertion
  that global search sends `projectId: undefined`, renders the owning project,
  changes selection to that project, and opens the exact matching chat.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 507 kB minified Agent-page chunk advisory remains
  performance debt rather than a correctness failure.
- The rebuilt loopback app was reloaded at `/agent`. Its real local catalog
  switched to **Matching chats**, rendered the owning project alongside the
  matching saved chat, cleared back to **Chats**, and emitted no browser warning
  or error. That database currently contains one project, so the automated
  exact transport/selection test supplies the cross-project live-data case.
- No model, GPU runtime, MCP server, credential, workspace mutation, or terminal
  process was started by this checkpoint.

## Owner review

The app is already reloaded. In the left Agent rail:

1. type part of any saved chat title into **Search projects and chats**;
2. confirm the section reads **Matching chats** and each result includes its
   project name;
3. if multiple projects exist, search for a chat in another project and open
   it; the project selection should follow the result;
4. clear search and confirm the rail returns to the chosen project's chats.

## Next slice

Complete the Agent-11 parity reconciliation matrix against the current API and
UI, then repair the next evidence-backed gap. Store-06b persistent MCP hosting
remains separately frozen pending explicit owner approval.
