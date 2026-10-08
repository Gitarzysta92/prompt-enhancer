# Agent checkpoint 08s handoff: durable lifecycle and restart acceptance

Date: 2026-08-28

## Outcome

Durable Agent projects and chats now pass a complete fictional-data lifecycle in
the native desktop composition. A project and chat can be created without first
loading a model, renamed, pinned, searched by either project or chat title,
archived, restored, closed from live memory, reopened from retained history and
resumed after a clean application restart. Resuming restores conversation state
but deliberately restores no protected authority.

The project/chat action menus are now fixed, viewport-bounded action sheets. All
available actions remain visible at narrow and desktop sizes, Escape closes the
sheet and focus returns to its exact trigger. Catalog mutations synchronize
between the main and dedicated Agent windows without transmitting catalog
content.

## Repairs made during validation

- Model-free durable chat creation is accepted; the composer stays blocked with
  an explicit **Open Models** recovery path until a compatible model is ready.
- Project search now includes matching chat titles while preserving archived
  visibility rules.
- Project and chat action menus no longer clip inside the scrolling rail.
- Content-free catalog invalidation now updates the dedicated window's rail and
  current chat heading after a rename.
- The page publishes mutations through its existing BroadcastChannel endpoint.
  This prevents a mutation from echoing back into its own page and replacing an
  authoritative create, close or resume result with a stale catalog response.
- A successfully closed session clears its local closing marker, so the same
  durable chat can be resumed without a false **Session closing** state.
- Component and browser selectors now distinguish the chat-selection button
  from the accessible **Chat actions for ...** button.

## Native fictional-data pass

The native application was shut down completely and relaunched with
`pythonw.exe` in a hidden composition. After restart:

1. the fictional project and chat remained in the catalog;
2. a chat-title-only search still revealed both the chat and its parent project;
3. the retained chat reopened and resumed as **Recovered · protected actions
   off**;
4. File writes, Commands and Web fetches were all unchecked;
5. Files & review opened the empty repository-local fictional workspace and
   reported its state truthfully;
6. closing the resumed live chat kept its durable catalog entry available.

Earlier in the same pass, project/chat archive, restore, pin, rename, retained
close and cross-window title synchronization were exercised successfully. No
protected permission checkbox or approval confirmation was automated.

## Verification receipts

- **121/121** focused Agent page, catalog rail, layout and window-channel tests
  passed in one consolidated run.
- **94/94** backend catalog, retained-history, local-Agent, write-boundary and
  user-presence tests passed. The existing Starlette test-client deprecation
  warning remains informational.
- **66/66** Chromium workflows passed at 360 px and 1,440 px after rerunning the
  complete workflow file. The first run correctly exposed eight strict-selector
  failures caused by the newly accessible action buttons; those tests were
  repaired and the full file was repeated.
- The production frontend build completed with **536 transformed modules**.
- `git diff --check` passed.
- The unchanged privacy scanner reports exactly one known pre-existing finding:
  the untracked binary `docs/checkpoint-agent-02-shell.png`. This checkpoint
  introduced no new finding and did not weaken a scanner rule.
- The final cleanup removed Playwright's exact temporary listener on port 4173.
  The protected application remained on one loopback listener and one native
  window, with zero visible terminal windows and zero model processes.
- No model was loaded and no real provider session, credential, prompt or local
  configuration was read.

## Current capability boundary

Automated and fictional native evidence now covers the durable project/chat
hierarchy, restart retention, rename/search/pin/archive/restore, retained resume,
separate-window catalog synchronization and workspace inspection. It does not
substitute for these owner-visible or real-runtime checks:

1. click through native authority revalidation and one reviewed fictional file
   write, including diff approval and post-write verification;
2. run one finite compatible model through response, Stop, context reporting,
   placement switch, unload and GPU cleanup;
3. perform one real Codex or Claude Streamable HTTP MCP handshake with a newly
   created one-time credential;
4. complete the card-by-card visual polish pass after functional acceptance.

The next bounded implementation checkpoint should improve startup and
conversation ergonomics: do not cover an existing durable catalog with New chat
setup after restart, then audit Markdown/code actions, reasoning/tool feedback
and empty/error states as one coherent conversation-quality slice.
