# Agent checkpoint 09o — local MCP endpoint self-test

Date: 2026-08-28

## Outcome

The one-time direct-connection card can now prove its generated credential and
endpoint against the real in-app Streamable HTTP server before the owner edits
Codex or Claude configuration. **Run local self-test** performs a bounded MCP
initialize/initialized exchange, validates the exact scoped tool list, and
calls only `agent_discover`.

This closes the gap between static configuration validation and live endpoint
validation. It intentionally does not claim that an external client connected;
the read-only Codex or Claude verification command plus an external tool call
remains a separate owner gate.

## Safety boundary

- The target must be the exact `/mcp/agent` URL on the current page's `http`
  loopback origin. HTTPS, non-loopback hosts, cross-origin ports, user info,
  queries, fragments, and other paths fail before the bearer is sent.
- The bearer remains in component memory, appears in no rendered text or test
  result, and is sent with `credentials: omit`, `redirect: error`,
  `cache: no-store`, and `no-referrer`.
- The server must return private no-store JSON/notification responses, MCP
  protocol `2025-06-18`, server identity `prompt-enhancer-agent`, the exact
  seventeen core tools, scoped `agent_runtime` presence or absence, MCP
  contract v13, and orchestration contract v9.
- The test starts no model, process, terminal, project, chat, turn, attachment,
  workspace read, proposal, or protected effect.
- Its `agent_discover` call updates the existing content-free connection
  activity receipt. The UI therefore calls this **MCP activity**, not external
  client proof.

## Verification

- Focused endpoint and connection-card suite: **18 passed** across two files.
- Serial Agent UI and Agent-contract suite: **522 passed** across 39 files.
- Live-listener/direct-HTTP/config backend suite: **23 passed** with one
  existing Starlette deprecation warning.
- Negative coverage includes unsafe scheme/host/path/query/user-info,
  cross-origin loopback, malformed tool surfaces, incorrect lifecycle scope,
  invalid discovery contracts, and credential non-rendering/non-storage.
- Production TypeScript/Vite build passed with **544 transformed modules**.
  OpenAPI drift, repository privacy scan, and `git diff --check` passed; the
  latter reports only existing Windows line-ending notices.
- The first two attempted focused-test commands used unsupported Jest/older
  Vitest worker flags and exited before collecting tests. The supported serial
  invocation then passed; no product failure was hidden.
- The rebuilt Agent route reloaded at `http://127.0.0.1:8765/agent`; the
  Connections drawer reports the controller ready, `POST /mcp/agent`, zero
  active connections, and a stopped runtime. Final process checks found two
  expected `pythonw` owner/launcher processes, one loopback-only port-8765
  listener, no non-loopback listener, and no `llama-server` process.

## Remaining owner acceptance

Create one scoped connection in the owned native window, run the new local
self-test, copy the selected client configuration, verify it through Codex or
Claude, call `agent_discover` externally, refresh the content-free receipt, and
revoke the connection. The real-model turn/Stop/file/artifact/context/unload
walkthrough remains separately owner-gated.
