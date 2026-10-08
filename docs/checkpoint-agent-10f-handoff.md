# Agent checkpoint 10f — external client setup and reviewed-file acceptance

Date: 2026-08-29

## Outcome

The direct Agent MCP path now has a practical client-registration workflow and
an end-to-end reviewed-file proof. The one-time setup card can copy current,
token-free Codex and Claude Code registration commands in addition to the exact
validated TOML/JSON documents. Prompt Enhancer never executes those commands,
edits client settings, or places the one-time bearer inside them.

A new real-loopback synthetic acceptance test proves the full protected file
loop: open a durable project/chat, propose one revision-bound edit and one new
file as a failure-atomic transaction, confirm neither is published before
review, approve through the same one-shot browser/native boundary used by the
owned app, wait for settlement, replay the request idempotently, and read both
verified revisions back through MCP.

## Repaired behavior

- The Codex setup copies `codex mcp add` with the exact loopback URL and
  `--bearer-token-env-var`; the bearer value is absent.
- The Claude Code setup copies `claude mcp add --transport http --scope local`
  with a literal `${PROMPT_ENHANCER_AGENT_MCP_TOKEN}` authorization template;
  the bearer value is absent.
- Each client keeps **Copy config** as a portable/manual alternative, while the
  page states that Prompt Enhancer copies but never runs the install command.
- `prompt-enhancer agent-mcp-config` emits both token-free registration commands
  ahead of the unchanged machine-parseable Claude JSON and Codex TOML blocks.
- The generated commands are derived only after the endpoint passes the exact
  loopback `/mcp/agent` validator.
- The synthetic acceptance host owns and closes one hidden loopback server. It
  rejects any child-process spawn, invokes no model, and verifies listener
  cleanup after the reviewed transaction.
- A stale controller-test fixture was repaired to match the hardened event
  contract: terminal `done` events carry no borrowed text, and resolved approval
  events carry their required tool, approval identity, and decision.

No real model, microphone, command, web fetch, provider configuration, external
account, owner credential, or owner workspace was used.

## Verification

- Focused client-config, packaging, MCP surface, and integration selection:
  **52/52 tests passed**.
- Widened MCP/controller/native-review/transaction/orchestration selection:
  **156/156 tests passed**.
- Complete frontend: **163/163 files and 2,207/2,207 tests passed**.
- Connection-panel unit coverage: **8/8 tests passed**, including exact Codex
  and Claude clipboard values and absence of the one-time bearer.
- TypeScript and production build: **551 transformed modules**, passed.
- Python compilation, repository privacy scanner, and tracked whitespace check:
  passed.
- Live `http://127.0.0.1:8765/agent` loaded the new production entry asset,
  opened Agent settings → Connections, showed the direct MCP card, and emitted
  zero browser diagnostic entries. Creating a real connection remained disabled
  in the non-owned browser, as required by the native-confirmation boundary.
- The synthetic acceptance listener closed cleanly after every run. No model or
  child process was left by this checkpoint.

## Exact remaining owner gate

This checkpoint proves Prompt Enhancer's direct MCP and reviewed-file workflow,
not an owner's external client installation. The remaining owner action is to
create one real scoped connection in the owned native Agent window, set its
one-time token in the chosen client process, run the copied registration and
verification commands, make one fictional tool call, approve one fictional
proposal in Prompt Enhancer, then rotate and revoke the credential. Record only
content-free receipts and unload any explicitly selected model afterward.

## Next checkpoint

Do not add more controller authority before that owner gate. The next safe
autonomous work should be a bounded card-by-card visual/accessibility review or
a repair driven by a failed owner observation. Model loading, microphone access,
provider configuration, and real protected approvals remain explicit owner
actions.
