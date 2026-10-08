# Agent checkpoint 09u — verified external-orchestrator handshake

Date: 2026-08-28

## Outcome

The direct Agent MCP handshake now gives Codex, Claude Code, and other MCP
clients a bounded, actionable workflow instead of safety notes alone. The owned
native endpoint self-test refuses to report readiness unless that workflow,
the exact 18-tool surface, and controller discovery all validate.

This slice changes guidance and verification only. It grants no project, chat,
file, approval, model, process, provider, or remote-network authority.

## Connection contract

- The server-wide instructions fit within the 512-character MCP guidance bound
  and lead with the complete normal sequence: `agent_discover`, `agent_open`,
  `agent_context`, one `agent_turn`, then `agent_wait` or `agent_stop`.
- They direct controllers to use `agent_workspace` and `agent_artifacts` as
  evidence and distinguish an externally authored proposal from a completed
  file change.
- They state that single-file and transactional proposals only stage native
  review, sensitive calls need an egress receipt, model lifecycle is opt-in,
  and live close retains durable history.
- The browser self-test now fails closed when initialize guidance is missing,
  incomplete, or longer than 512 characters. A pass therefore proves the local
  protocol, workflow guidance, exact tool inventory, and read-only discovery.
- The setup card names this stronger result as **Handshake + workflow passed**
  while continuing to state that it does not prove an external client was
  configured or connected.

## Verification

- Focused frontend endpoint/setup coverage passed **21 tests**.
- MCP transport, HTTP, configuration, packaging, connection persistence,
  generated OpenAPI, and full synthetic integration coverage passed **76
  tests** under the repository's pinned Python environment.
- The integration lane includes create/open, catalog/history, context,
  workspace inspection, native-review refusal, wait/stop, resume, and close.
- The complete frontend suite passed **160/160 files and 2,154/2,154 tests** in
  one serial run.
- TypeScript compilation and the production build passed with **547 transformed
  modules**. The repository privacy scan and touched-diff whitespace check
  passed.
- A first OpenAPI check made with system Python correctly failed because that
  interpreter carried FastAPI 0.116/Pydantic 2.11 instead of the repository's
  pinned FastAPI 0.141/Pydantic 2.13. No artifact was regenerated from that
  environment; the pinned-environment byte-exact OpenAPI check passed.

## Runtime and privacy

All automated calls use reserved synthetic fixtures. The self-test is read-only
and starts no terminal, subprocess, model, project, chat, or file action. It
returns no bearer token and sends the credential only to the exact same-origin
loopback MCP path. No provider configuration is read or edited.

The live browser reloaded the rebuilt production Agent bundle at
`http://127.0.0.1:8765/agent`; its Agent settings expose the controller v12
manifest, direct `/mcp/agent` connection card, 18-core-tool disclosure, and no
active connection. Final process inventory found one native-owned listener on
8765, no Vite process, and no local model process. Windows automation could not
safely bind the existing pywebview window, so the process was not killed or
force-restarted. The new backend initialize guidance becomes live at the next
normal native-app restart; its packaged HTTP behavior is already covered by the
pinned 76-test backend gate.

## Remaining owner acceptance

Prompt Enhancer can generate exact token-free Codex and Claude Code client
snippets and can prove its local endpoint. The final external-client proof still
requires the owner to create one scoped credential, place it in the selected
client process, reload that client, and produce a server-recorded tool receipt.
The app must not automate that provider-configuration change.
