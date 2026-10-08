# Agent checkpoint 10g — exact setup before authority

Date: 2026-08-29

## Outcome

The Agent Connections card can now show the exact Codex, Claude Code, or
provider-neutral Streamable HTTP setup before the owner creates a credential.
The preview is explicitly disconnected and read-only: it contains no bearer,
grants no connection authority, starts no process or terminal, and changes no
provider configuration.

The existing one-time private setup is unchanged. A real connection still
requires the owned native window, one-shot user-presence confirmation, and a
new scoped token.

## Implemented boundary

- `GET /v1/integrations/agent-mcp/setup` requires the normal local application
  authentication and derives its endpoint from the exact validated loopback
  request origin.
- The strict `agent-mcp-client-setup.v1` document returns only the endpoint,
  bearer environment-variable name, canonical Codex TOML, canonical Claude
  JSON, and current token-free add commands.
- Backend and frontend validators require all safety facts exactly: credential
  absent, authority absent, native creation required, no process, no terminal,
  and no provider edit.
- A non-loopback host, extra field, altered command/config, embedded `pemcp1.`
  value, or changed safety fact fails closed.
- The preview loads independently of connection-list/native-mutation state.
  Codex, Claude Code, and Other MCP client views can inspect or copy only their
  applicable token-free values.
- The card identifies itself as **Disconnected · no credential** and keeps the
  existing native-only Create/Rotate/Revoke controls disabled in an ordinary
  browser.

## Verification

- Related backend connection/config/HTTP/OpenAPI suites: **39/39 passed**.
- Focused frontend contract, transport, and card suites: **197/197 passed**.
- Responsive browser acceptance: **2/2 passed** at 1440 px and 360→320 px,
  including keyboard access, no bearer rendering, exact client switching, and
  44 px preview actions.
- Production TypeScript/Vite build: **551 modules**, passed.
- Generated OpenAPI and TypeScript parity: passed.
- Privacy scanner, Python compilation, and whitespace check: passed.
- Whole frontend run: **162/163 files and 2,207/2,208 tests passed**. The one
  unrelated model-ensemble layout-concurrency test passed immediately when
  rerun alone and its complete file then passed **39/39**. No Agent code was
  changed to mask that timing observation, so this is not recorded as a fully
  green whole-suite receipt.
- The rebuilt live app was closed through its normal native confirmation,
  relaunched without a terminal, and reloaded at
  `http://127.0.0.1:8765/agent`. The Connections panel showed the exact
  `http://127.0.0.1:8765/mcp/agent` preview and emitted zero browser diagnostics.
  All six live preview controls measured 44 px high.
- Final runtime inventory: one listener on `127.0.0.1:8765`, no owned test
  listeners or frontend test workers, and zero `llama-server` processes.

No model, microphone, command, web fetch, provider configuration, real
credential, real provider session, or owner workspace content was used.

## Remaining owner gate

This checkpoint proves setup preview and contract integrity, not an external
client installation. The owner still needs to create one real scoped
connection in the native Agent window, place its one-time token only in the
chosen client process, verify one fictional MCP request, review one fictional
file proposal, then rotate and revoke the credential. Any selected model must
be unloaded afterward.

## Next checkpoint

The next list item should be the bounded owner artifact/viewer walkthrough:
create fictional text, image, PDF, and Office-style outputs; exercise Preview,
Reveal, Review changes, and Download; stale one exact version and confirm that
the viewer refuses it. If owner time is unavailable, the safe alternative is a
card-by-card visual/accessibility sweep that does not create authority, load a
model, use the microphone, or modify provider settings.
