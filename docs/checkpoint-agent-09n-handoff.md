# Agent checkpoint 09n — verified Codex and Claude client setup

Date: 2026-08-28

## Outcome

The direct Agent MCP endpoint is no longer handed to external coding clients
through two independently maintained templates. Native connection credentials
and the token-free `agent-mcp-config` command now use one canonical generator
that parses and exactly validates both the Codex TOML and Claude Code JSON
before either snippet is returned.

The one-time private setup in **Agent settings → Connections** is now a bounded
three-step flow for one selected client: copy the hidden token, copy the exact
configuration, then copy a read-only client verification command and the
provider-neutral orchestration starter. The card visibly separates endpoint
validity, config-shape validity, and actual server-observed authentication.

## Correctness and safety changes

- Only exact `http` loopback URLs ending in `/mcp/agent` are accepted. User
  information, non-loopback hosts, wrong paths, queries, and fragments fail
  closed.
- Endpoint validation now runs before connection creation or credential
  rotation. A bad endpoint cannot leave behind an unseen connection row or
  advance a credential revision.
- The Codex shape requires the exact URL, bearer environment variable,
  330-second tool timeout, and prompt-mode tool approval policy.
- The Claude Code shape requires Streamable HTTP and an `Authorization` header
  that expands the same bearer environment variable at client runtime.
- Neither snippet embeds the bearer. The app still stores no bearer secret and
  starts no client, shell, terminal, bridge process, agent, or model.
- Provider configuration remains an explicit owner action. The app exposes
  copy operations only and never edits Codex or Claude settings.
- The selected-client tabs form a complete accessible tab/tabpanel relation;
  mobile layout stacks every step and action without horizontal dependence.
- **Awaiting first request** is not presented as a connection failure or a
  success claim. Only a later authenticated request recorded by this server
  promotes the client-proof state.

## Compatibility evidence

The configuration keys and header expansion were checked against the official
[Codex MCP documentation](https://developers.openai.com/codex/mcp/) and
[Claude Code MCP documentation](https://code.claude.com/docs/en/mcp). The
installed Codex and Claude Code CLIs also exposed the expected HTTP MCP,
bearer/header, add, and get contracts through read-only version/help commands.
No real provider configuration, credential, or session was read or changed.

Protocol acceptance remains stronger than template inspection: the existing
disposable listener test connects two independent Streamable HTTP clients,
validates the exact seventeen-tool surface, and proves immediate rejection
after credential revocation.

## Verification

- Broad Agent/backend/runtime/workspace matrix: **822 passed** across 47 files.
- Direct MCP/config-focused matrix: **68 passed**, including the real
  two-client listener and invalid-endpoint authority regression.
- Serial Agent UI suite: **277 passed** across 20 files.
- Agent transport, contract, and native-bridge suite: **428 passed** across 20
  files.
- Focused private-setup interaction suite: **6 passed**; canonical backend
  config suite: **13 passed**.
- The initial parallel Agent UI run had two five-second load-sensitive timeouts
  after 274 passes. Both passed alone, and the complete serial rerun passed
  277/277; no timeout was hidden by increasing a product assertion budget.
- Production TypeScript/Vite build passed with **543 transformed modules**.
- Generated OpenAPI drift check, Python compilation, repository privacy scan,
  and `git diff --check` passed. Windows line-ending notices remain
  informational.

## Native reload proof

The previous owner window was closed through its normal native confirmation.
Before relaunch there were zero Prompt Enhancer processes, zero port-8765
listeners, and zero model processes. The repository build was relaunched with
`pythonw` and a hidden launcher.

The final state is one Prompt Enhancer window, one listener bound only to
`127.0.0.1:8765` and owned by `pythonw`, zero `llama-server` processes, and a
stopped shared runtime. The rebuilt Agent settings load the direct endpoint and
empty connection state without a frontend/backend version error. No connection
credential was created during automation.

## Remaining owner acceptance

The code and synthetic evidence are complete for client setup, but a real
provider connection is intentionally owner-gated because it creates persistent
access. In the native window the owner still needs to create one scoped
connection, copy the token and chosen config, connect Codex or Claude Code,
call `agent_discover`, refresh the receipt, and revoke the credential.

The broader legacy-retirement gate also still requires one chosen compatible
model for a streamed turn, bounded Stop, reviewed fictional write, artifact and
attachment review, exact-or-unknown context observation, model switch/unload,
process exit, and CPU/GPU cleanup evidence. No commit or push was requested.
