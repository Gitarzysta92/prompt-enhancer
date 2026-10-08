# Agent checkpoint 08o handoff: standard external-agent MCP bridge

Date: 2026-08-28
State: implementation and synthetic validation complete; installed-client and native/model owner acceptance remain pending

## Outcome

Agent-08o closes the integration gap between the complete loopback Agent
controller and standard coding-agent clients. Codex, Claude Code, and another
MCP client can now discover and use Prompt Enhancer's authored projects, chats,
finite turns, event continuation, reviewed workspace operations, and artifacts
without a bespoke wrapper.

The new `prompt-enhancer agent-mcp` stdio server is separate from the read-only
analytics MCP surface. Its default toolset is:

- `agent_discover`: verify the complete content-free v6 controller manifest;
- `agent_invoke`: invoke one manifest-declared JSON operation;
- `agent_open`: create/select one durable project and open one validated chat;
- `agent_turn`: submit one message and observe one bounded turn; and
- `agent_wait`: continue from a returned cursor without resubmitting or
  requesting Stop.

`agent_runtime` is absent by default. It appears only when setup includes the
server-level model-lifecycle acknowledgement, and every call must also carry
`model_lifecycle_authorized: true`. The existing controller still performs at
most one revision-bound runtime mutation and one read-only reconciliation.

`prompt-enhancer agent-mcp-config` prints copyable `.mcp.json`, `claude mcp
add`, and Codex TOML snippets. `--with-model-lifecycle` prints the explicit
alternate configuration. Generation reads no private token, creates no app
state, writes no Codex or Claude file, and emits no absolute local path. The
Codex snippet uses a 330-second tool timeout for the 300-second bounded turn
ceiling and keeps MCP tool approval in prompt mode.

The Agent **Connection & setup** card now presents standard MCP setup first and
retains the lower-level single-request controller commands for non-MCP scripts.

## Safety boundary

- Every sensitive tool call requires literal task authorization, completed
  redaction preview, and an explicit destination.
- Generic POST, PATCH, and DELETE calls require mutation authorization; DELETE
  additionally requires destructive-action authorization.
- Native-only operations, binary responses, SSE responses, and raw runtime
  mutations remain unavailable through generic invoke.
- A token controller still cannot approve a file effect, command, web fetch,
  recovered authority, or manual artifact capture.
- Errors serialize only a closed code, validated optional HTTP status, and
  boolean retryability. Unrecognized detail keys and invalid detail types are
  dropped.
- The transport accepts only an authenticated exact loopback origin, follows no
  redirect, and uses no environment proxy.
- The bridge owns no Prompt Enhancer server, external agent, local model,
  listener, shell, terminal, or GPU lifecycle. It only calls an already-running
  application. No model was loaded for this checkpoint.

## Verification receipts

- Final focused Agent MCP and shared MCP protocol gate: **17 passed**.
- Controller/MCP/client regression gate: **61 passed**.
- Broad final `test_agent_*` backend gate: **196 passed**.
- Complete Agent component gate: **240 passed across 18 files**.
- Agent API contract gate: **186 passed across 13 files**.
- Chromium connection-card flow: **2 passed**, at 360 px and 1,440 px,
  including keyboard access and no horizontal overflow.
- Production TypeScript/Vite build: **533 modules transformed**.
- Python source/test compilation: passed.
- `git diff --check`: passed (line-ending notices only).

All fixtures use reserved synthetic values. The privacy scanner still reports
exactly one known pre-existing finding: the untracked binary screenshot
`docs/checkpoint-agent-02-shell.png`. Agent-08o introduced no additional
privacy finding and did not weaken a scanner rule.

## What remains

The source-tree implementation is complete, but this development shell does
not currently expose the installed `prompt-enhancer` console launcher on PATH.
An installed/rebuilt Prompt Enhancer distribution is therefore required before
the printed Codex or Claude configuration can start this new command. The
source entry point and snippets were validated in-process; a real installed
Codex/Claude MCP handshake is the next deployment/owner gate.

That gate must not silently enable model lifecycle. Start with the default
configuration, confirm discovery and read-only project/chat browsing, then test
one synthetic project/chat and finite turn. Only if the owner wants external
runtime control should the lifecycle-enabled configuration be installed. The
separate native owner walkthrough for live model streaming, Stop, file review,
dedicated window behavior, model unload, process exit, and CPU/GPU cleanup also
remains pending.
