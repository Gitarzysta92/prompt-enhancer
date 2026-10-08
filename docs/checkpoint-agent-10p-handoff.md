# Agent checkpoint 10p — external-controller onboarding and recovery

## Outcome

The external-controller card now has one coherent setup and recovery flow for
Codex, Claude Code, and another Streamable HTTP MCP client. The work stays
inside the already-running loopback app: it starts no bridge process, terminal,
model, project, chat, or workspace mutation.

The generated Codex setup remains aligned with the official Streamable HTTP
and bearer-environment configuration described in the
[OpenAI MCP documentation](https://developers.openai.com/codex/extend/mcp).
The generated Claude Code setup remains aligned with Anthropic's documented
HTTP transport, header, environment-expansion, and server-status behavior in
the [Claude Code MCP documentation](https://code.claude.com/docs/en/mcp).

## Closed gaps

- A connection created for **Other MCP client** now opens a real generic
  private setup tab. It no longer silently falls back to Codex.
- The generic path exposes only the exact loopback endpoint, a separately
  copied one-time token, the required bearer-header shape, and a content-free
  orchestration starter. It offers no fake install or verification command.
- The local endpoint self-test has an enforced eight-second whole-workflow
  bound. A stalled initialize, initialized notification, tool list, or
  `agent_discover` request is aborted rather than hanging the card.
- Authentication rejection is distinguished from malformed protocol output
  without reading or displaying the response body. The UI gives bounded,
  content-free recovery for invalid endpoint, rejected credential, timeout,
  handshake mismatch, tool-surface mismatch, and discovery mismatch.
- Connection cards now explain the evidence they actually hold:
  never contacted, authenticated without a tool receipt, last tool failed,
  or last tool succeeded. None is presented as proof that a turn or file
  change completed.
- Active credentials retain the explicit **Rotate** recovery lane. Expired or
  revoked records offer **Prepare replacement**, which only pre-fills and
  focuses the creation form. It creates no credential and still requires the
  separate native confirmation.
- Backend tests now explicitly prove that expired authority cannot be rotated
  back to life, a fresh replacement can be created, and revocation immediately
  rejects the previously valid bearer at the HTTP endpoint.

## Validation

- Frontend controller/connection/self-test group: **32/32 passed**.
- Backend connection, Streamable HTTP, and client-config group: **33/33
  passed**. The only output was the existing Starlette `httpx` deprecation
  warning.
- Production frontend build: **553 modules transformed**.
- Live browser reload at `http://127.0.0.1:8765/agent`:
  - exact setup loaded with zero active connections;
  - the Other-client preview selected without exposing a token or enabling
    connection creation;
  - no browser warning or error was recorded;
  - at 390 px the document and dialog had no horizontal overflow;
  - all 24 visible dialog buttons measured at least 44 px high;
  - the normal desktop viewport and Codex preview were restored afterward.
- Final process inventory: one listener on `127.0.0.1:8765`, zero visible
  terminal windows, and zero `llama-server` processes.

No real bearer was created, no Codex or Claude setting was read or changed, no
model was loaded, no microphone was requested, and no protected authority was
granted.

## Next checkpoint

The implementation list is complete; the remaining work is owner acceptance,
not another hidden feature claim. Agent-10q should use one fictional,
native-confirmed connection with the owner's chosen external client, verify
`agent_discover` and the content-free tool receipt, revoke the connection, and
confirm that the client is rejected afterward. It must not load a model or
touch a workspace. Editing a real client configuration and creating the
one-time bearer remain explicit owner actions.
