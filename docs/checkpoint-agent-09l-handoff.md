# Agent checkpoint 09l — content-free MCP tool activity

Date: 2026-08-28

## Outcome

Direct Agent MCP connections previously exposed only whether a scoped bearer
had reached the app. They now retain and display a bounded receipt for the last
validated MCP tool call: tool name, protocol outcome, and server time. This lets
an owner distinguish authentication from actual controller use without storing
the delegated task, tool input, or tool result.

## Contract and implementation

- The durable connection contract is now `agent-mcp-connection.v2`; the Agent
  catalog schema is version 9.
- `last_tool_at`, `last_tool_name`, and `last_tool_outcome` are nullable but
  all-or-none. Existing and migrated connections remain honestly unknown until
  a tool call occurs.
- Exact allowlisted names such as `agent_discover` and `agent_open` are retained.
  A malformed or unknown name collapses to the fixed `unknown_tool` label rather
  than persisting arbitrary client input.
- Outcomes are the closed vocabulary `succeeded` or `failed`. They describe the
  MCP protocol result only; they do not certify a turn, write, artifact, model,
  approval, or cleanup outcome.
- The receipt update is monotonic and applies only to a still-active,
  non-expired connection. Revocation and expiry continue to fail before tool
  execution.
- Receipt persistence is observational. If it becomes unavailable after a tool
  has settled, the original MCP response is returned unchanged so the client is
  not encouraged to retry a possibly mutating call.

## Native UI

Each active connection card now separates:

- **Last MCP request** or **Never connected**; and
- **Last tool** with name, outcome, and time, or the explicit
  **No MCP tool call receipt recorded yet** state.

Status remains refresh-driven. The surrounding guidance states that a tool
receipt is not domain-success evidence.

## Privacy boundary

The catalog stores no tool arguments, results, prompt or response text,
workspace path, project/chat identity, attachment, token, exception, model
choice, or provider configuration. No new process, terminal, bridge, listener,
model, GPU use, network destination, or approval authority was introduced.

## Automated verification

- Focused MCP connection and HTTP tests: **18 passed**.
- Broad MCP/controller/catalog/OpenAPI/release/Windows backend slice:
  **213 passed** across 11 files.
- Focused connection parser, transport, panel, and controller UI tests:
  **195 passed** across 4 files.
- Complete Agent component suite, one worker: **274 passed** across 20 files.
- Responsive Chromium workflow matrix: **69 passed**, including the connection
  receipt at 360 px and 1,440 px plus its 320 px touch-target check.
- Production TypeScript/Vite build passed with 543 transformed modules.
- Generated API drift check passed.
- `npm audit --audit-level=low` reported zero known vulnerabilities.
- Targeted `git diff --check` and trailing-whitespace checks passed.
- The repository privacy scan reports only the unchanged, pre-existing binary
  finding for `docs/checkpoint-agent-02-shell.png`; this checkpoint adds no text
  finding and weakens no scanner rule.

## Native restart proof

The first soft WebView reload deliberately exposed a version mismatch: the new
v2 frontend was talking to the still-running pre-09l backend and showed
**Connections could not be loaded**. That was not accepted as a pass. The old
native instance was closed through its confirmation, zero Prompt Enhancer
processes and zero listeners were observed, and the repository launcher was
started again with a hidden window.

After the full restart, **Agent settings → Connections** reported the controller
as **Ready**, loaded **0 Active** direct connections without error, exposed
`POST /mcp/agent`, and retained the connection-status refresh control. The
shared runtime remained **Stopped**. Final host state is one Prompt Enhancer
window, one listener on `127.0.0.1:8765` owned by the app, zero `llama-server`
processes, and zero targetable terminal windows. No connection credential was
created or copied.

## Remaining owner acceptance

Displaying a non-empty receipt requires the owner to create the first real
scoped connection and configure a chosen local Codex, Claude Code, or other MCP
client. The bounded owner check is: call `agent_discover`, refresh connection
status, verify the tool receipt, then revoke the credential. A later compatible
model-backed turn, Stop, reviewed fictional write, separate-window behavior,
and CPU/GPU cleanup check remain required before retiring legacy Agent surfaces.

No commit or push was requested.
