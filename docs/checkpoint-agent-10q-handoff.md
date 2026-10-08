# Agent checkpoint 10q — external-controller acceptance receipts

## Outcome

The Agent Connections surface can now distinguish the app's own endpoint
self-test from a real external MCP request. A bounded, memory-only acceptance
card guides one scoped connection through external discovery, explicit native
revocation, and a rejected retry without automatically creating, rotating, or
revoking authority.

This checkpoint does not claim that a real Codex, Claude Code, or other client
was configured. That remains an owner action because the bearer is shown once
and provider configuration stays outside Prompt Enhancer.

## Closed gaps

- The durable connection contract is now `agent-mcp-connection.v3` and the
  Agent catalog schema is version 10.
- Every content-free tool receipt records whether it came from an
  `external_client` or `native_self_test`. The browser self-test marks all four
  handshake requests, so its successful `agent_discover` can no longer be
  presented as external-client evidence.
- A formerly valid rotated, expired, or revoked bearer records only a bounded
  rejection timestamp. Wrong, malformed, or differently keyed credentials do
  not create that receipt, and authentication still returns the same closed
  error.
- Connection cards label the last tool source and separately report whether an
  exact inactive credential was rejected. No prompt, arguments, response,
  token, path, error body, or provider identity is stored.
- **Begin external proof** captures a fresh baseline for one active credential
  revision. A pass requires, in order:
  1. a newer successful external `agent_discover` receipt;
  2. explicit native revocation;
  3. rejection of that exact credential strictly after revocation.
- Local self-test activity, old receipts, equal-time rejection, rotation during
  the run, expiry before revocation, and a missing connection all fail closed.
  The acceptance card never performs a protected mutation itself.

## Validation

- Backend connection, Streamable HTTP, direct-probe, integration, migration,
  attachment, artifact, and OpenAPI group: **59/59 passed**.
- Frontend connection, strict contract, endpoint-self-test, and transport
  group: **222/222 passed**.
- Chromium controller/settings scenario: **2/2 passed** at 360/320 px and
  1440 px. The acceptance card stays inside the viewport and its proof actions
  retain 44 px targets.
- Complete frontend run: **2,242/2,243 passed**. One unrelated Team Analytics
  interaction reached its five-second suite timeout; the exact failing test
  passed immediately in isolation (**1/1**) and changed no Agent code.
- Generated OpenAPI drift check, Python compilation, production TypeScript/Vite
  build (**553 modules**), privacy scan, and `git diff --check` all passed. The
  build retains its existing large-chunk advisory and the repository retains
  its existing Windows line-ending warnings.
- Live native reload at `http://127.0.0.1:8765/agent`:
  - an old-server/new-frontend contract mismatch was reproduced and failed
    closed as **Connections could not be loaded**;
  - restarting only the exact owned loopback app loaded the v3 catalog and the
    Connections empty state without error;
  - desktop 1046 px and narrow 390 px had zero document, dialog, or panel
    horizontal overflow;
  - all 26 visible settings buttons measured at least 44 px high;
  - browser warning/error diagnostics were empty.
- Final inventory: one listener on `127.0.0.1:8765`, zero visible terminal
  windows, zero local-model server processes, and zero owned frontend test
  workers.

No real bearer was created, no provider configuration was read or changed, no
model was loaded, no microphone was requested, and no workspace authority was
granted.

## Remaining owner acceptance

In the owned native Agent window, create one fictional scoped connection and
copy its one-time setup into the chosen external client. On that connection,
select **Begin external proof**, call only `agent_discover`, and refresh proof
evidence. After the discovery step passes, explicitly revoke the connection,
retry `agent_discover` once from the same client and expect HTTP 401, then
refresh again. Only the resulting four-step **Passed** receipt closes this
owner gate.

After that, continue the existing model-backed turn, Stop, reviewed fictional
file, artifact viewer, unload, process-exit, and CPU/GPU cleanup walkthrough.
