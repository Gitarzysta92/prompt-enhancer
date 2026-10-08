# Orchestration-01a checkpoint handoff

Status: automated implementation and protected live gate complete; owner
external-client setup review pending

## Outcome

Prompt Enhancer can create, inspect, rotate and revoke a direct Codex-, Claude-
or provider-neutral Agent MCP connection that is bound to exactly one active
Agent project. The credential cannot browse or operate on another project, does
not receive generic invocation authority and never inherits native approval
authority.

Connection creation and management remain inside the existing Agent settings
surface. They do not spawn a bridge terminal, load a model, start an MCP Store
server or grant workspace mutation merely because a credential exists.

## Frozen connection and scope contract

- `agent-mcp-connection.v4` stores one exact project scope and exposes it through
  `agent-mcp-scope.v1`.
- One-time bearer material uses the `pemcp2` format. Its connection identity and
  credential revision must match the returned setup document; malformed,
  substituted or stale material fails closed.
- A new connection must name an existing, non-archived Agent project. The UI
  requires an explicit project selection and does not silently bind a fallback
  project after a catalog-load failure.
- The credential principal carries the exact project identity. Project, chat,
  workspace, history, artifact, proposal, turn, Stop and wait operations enforce
  that scope before the controller call.
- Project discovery returns only the bound project. Chat discovery is bound to
  that same project. A chat or workspace belonging to another project is never
  accepted through a caller-supplied identifier.
- The scoped direct surface advertises 18 project-scoped tools. The generic
  `agent_invoke` escape hatch is absent. The unscoped local stdio development
  surface remains a separate 19-tool contract.
- Native user-presence confirmation is never inherited. File, command, web,
  model-lifecycle and other protected effects retain their native approval
  boundaries even when the connection advertises the corresponding capability.
- Revocation takes effect independently per connection. Rotation invalidates the
  previous credential revision without changing another connection.
- Legacy rows without a project scope become `scope_missing`; they cannot
  authenticate or rotate and the UI directs the owner to create a replacement.
- The token-free endpoint document advertises the URL, contract, safeguards and
  supported client configuration without returning secret setup material.

## Interface behavior

- Agent settings loads active durable projects into a dedicated scope selector.
- Every connection card names its exact project, project-only catalog/chat/
  workspace access and the absence of inherited native approvals.
- Ready, expired, revoked and missing-scope states use different truthful
  actions and recovery copy.
- The one-time setup result can be copied for Codex, Claude or another MCP client
  without rendering the bearer token in later list or endpoint-preview calls.
- A local self-test checks endpoint discovery, authentication, initialization and
  the exact scoped tool list without invoking an Agent tool.

## Validation ledger

- Current backend connection, surface, HTTP, integration and live-probe matrix:
  **76 passed**.
- Focused connection contract, endpoint self-test, HTTP transport, controller
  panel and connection-panel frontend matrix: **249 passed**.
- Broad Agent frontend split: **781 passed**. One unrelated dedicated-window
  Agent page case exceeded the shared 5-second parallel jsdom timeout and then
  passed alone in 2.4 seconds; this remains visible Sweep-01c harness debt.
- Responsive synthetic browser acceptance: **2 passed** at **360 px** and
  **1,440 px** for the private connection-management journey.
- Production frontend build: **passed**, **563 modules transformed**. The
  existing non-fatal large-chunk advisory remains.
- Generated OpenAPI export and TypeScript drift check: **passed**.
- OpenAPI/privacy tests: **14 passed**; repository privacy scan: **passed**.
- Current Python bytecode compilation and patch whitespace check: **passed**;
  existing Windows line-ending notices remain informational.

Negative coverage includes nonexistent and archived projects, legacy unscoped
rows, malformed and mismatched setup material, stale credential revisions,
expiry, independent revocation, cross-project project/chat/workspace/turn
requests, undeclared tools, extra response keys, missing native approval and two
simultaneous project credentials with disjoint visibility.

## Protected live-app gate

The prior exact repository listener was replaced with one hidden service entry
point. The final gate observed:

- `/health`: HTTP 200;
- exactly one listener on `127.0.0.1:8765`;
- one four-process launcher/service tree, with a zero main-window handle on every
  member and no visible terminal;
- zero `llama-server` or `llama-cli` model workers and zero known MCP workers;
- the existing in-app `/agent` tab reloaded against the replacement service;
- one project/chat rail, one **New chat** control, one Agent settings dialog and
  one Connections panel;
- one enabled project-scope selector plus the exact project-only and
  no-inherited-native-approval disclosure;
- **Create direct connection** remained disabled in the ordinary browser and
  displayed the protected-native-window requirement; and
- zero visible alerts and zero browser console errors, with one script and two
  stylesheet resources observed.

An initial console-module launch through `pythonw` exited before binding because
that console entry point expects output streams. It created no listener, model,
MCP worker or visible window. The installed service entry point was then launched
once with `WindowStyle Hidden` and produced the verified final state above.

The browser smoke deliberately inspected fixed shell labels, counts and control
states only. It did not read project names, chat titles, messages, workspace
paths/files, connection labels, setup material or retained history.

## Privacy and safety

- Tests use only reserved synthetic projects, chats, workspaces, credentials and
  controller responses.
- No provider session, credential file, model weight, real prompt, transcript,
  workspace content or unrelated local configuration was read.
- No connection setup material or derived Agent data was sent to a network
  service.
- The service remains loopback-only. Authentication does not replace CSRF,
  project scope, capability admission or native user-presence confirmation.

## Click later

1. Open **Agent settings → Connections**, select one disposable Agent project
   and create a Codex, Claude or provider-neutral connection.
2. Confirm the setup secret appears only in the immediate setup result and the
   retained card shows the exact project plus **project only** access.
3. Run the local self-test; confirm it reports 19 scoped tools and invokes none.
4. Configure a real external client, list projects and chats, and confirm only
   the selected disposable project is visible; try no real protected mutation.
5. Revoke the connection and confirm its next request is refused while another
   separately created project connection remains usable.

## Deliberately remaining

- Orchestration-01b adds visible external-controller ownership and exact
  start/observe/Stop/reconnect/resume/fork/handoff coordination for turns.
- A real Codex or Claude client handshake remains owner-controlled because it
  exposes one-time local setup material to that explicitly selected client.
- Physical model loading, model switching and VRAM-release acceptance remain on
  Acceptance-01. This checkpoint deliberately loads no model.

The next proposed implementation checkpoint is **Orchestration-01b**. No commit
or push was made for this checkpoint.
