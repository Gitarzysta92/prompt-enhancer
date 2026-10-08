# Agent checkpoint 09k — external-orchestrator handoff

Date: 2026-08-28

## Outcome

The provider-neutral controller was already implemented, but the owned Agent
window did not make its direct MCP handoff self-sufficient. The connection card
now exposes the protocol endpoint, a safe delegation workflow, and truthful
evidence that a scoped client reached the app. Codex, Claude Code, or another
Streamable HTTP MCP client no longer has to infer the endpoint or tool sequence
from the generated configuration.

## Native onboarding changes

- The card visibly identifies `POST /mcp/agent` as the recommended direct
  Streamable HTTP endpoint.
- After native creation of one scoped connection, the one-time private setup
  shows and can copy the exact loopback URL returned by the running app. This is
  especially useful for an arbitrary MCP client without a Codex/Claude-specific
  config format.
- A credential-free orchestration starter can be copied before or after setup.
  It defines the bounded `agent_discover` → `agent_open` → `agent_context` →
  `agent_turn` flow, native-review pause and `agent_wait` continuation, exact
  workspace/artifact inspection, and live-only `agent_close` semantics.
- Existing connection cards now distinguish **Never connected** from the last
  server-recorded authenticated MCP request. Status changes only after an
  explicit refresh.
- The copy and status UI remains keyboard reachable and at least 44 px tall at
  the 320 px acceptance width.

## Truth and privacy boundary

The starter contains no token, workspace path, project/chat identity, provider
configuration, model choice, prompt content, or standing authority. The bearer
still appears only in the one-time explicit copy action and is never rendered,
stored by the server, or placed in browser storage.

`last_used_at` proves only that a valid scoped credential authenticated to this
app. It is not presented as evidence that a project opened, a turn completed, a
file changed, an artifact rendered, or cleanup succeeded. Those claims still
require their exact domain receipts.

No new process, bridge, terminal, listener, model, GPU use, network destination,
or approval capability was introduced. The underlying controller remains
loopback-only and cannot approve protected file, command, or web effects.

## Automated verification

- Focused connection/controller components: **9 passed** across 2 files.
- Complete Agent component suite, run with one worker: **274 passed** across 20
  files.
- Direct connection, Streamable HTTP MCP, full MCP composition, controller
  client, controller HTTP, and controller CLI slice: **145 passed**.
- Responsive Chromium workflow matrix: **69 passed**, including the connection
  quickstart at 360 px, 1,440 px, and an in-test 320 px resize.
- Production TypeScript/Vite build passed.
- Generated API drift check passed.
- `npm audit --audit-level=low` reported zero known vulnerabilities.

The first parallel Agent-suite pass reported one existing workspace-help test
failure while the controller backend ran concurrently. That exact test passed
in isolation, and the complete low-contention single-worker Agent suite then
passed 274/274. No failure was suppressed or converted into a success claim.

The broader controller pass also found one stale migration test that still
expected catalog schema 7 after the Agent-09j schema-8 migration. The assertion
was corrected to the actual migration contract, and the complete 145-test slice
then passed.

## Native reload proof

- Reloaded the existing packaged Agent workspace in place without starting a
  second application, bridge, terminal, credential, or model.
- Opened **Agent settings → Connections** and verified the controller was Ready,
  `POST /mcp/agent` was visible, and both the orchestration-starter control and
  delegated-task quickstart were present.
- The connection count remained **0 active**; no bearer was created or copied.
  The shared runtime remained **Stopped**.
- Final process state is one Agent window, one listener bound only to
  `127.0.0.1:8765` and owned by `pythonw`, zero `llama-server` processes, and
  zero targetable terminal windows.

## Remaining owner acceptance

Creating the first real direct connection is intentionally still a native
owner-confirmed credential action. The next owner gate is to create one scoped
test connection, configure a local Codex/Claude/other MCP client, call
`agent_discover`, open one fictional project/chat, run one bounded turn, inspect
its receipts, and revoke the connection. The later model-backed Stop, reviewed
write, separate-window, and CPU/GPU cleanup checks remain required before
retiring any legacy Agent surface.

No commit or push was requested.
