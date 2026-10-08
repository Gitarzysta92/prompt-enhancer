# Agent checkpoint 08v handoff: strict durable catalog MCP

Date: 2026-08-28

## Outcome

External Codex, Claude Code, and other MCP clients now have a dedicated
`agent_catalog` tool instead of composing raw project/chat routes. It exposes
seven finite actions over the existing durable local catalog:

| Action | Effect |
|---|---|
| `list_projects` | bounded search/list of project metadata |
| `get_project` | one exact project record |
| `create_project` | one explicitly authorized project creation |
| `update_project` | revision-bound rename, pin, archive, or restore |
| `list_chats` | bounded global or exact-project chat list |
| `get_chat` | one exact durable chat record |
| `update_chat` | revision-bound rename, move, model selection, pin, archive, or restore |

The input is a strict discriminated union: fields valid for one action are
rejected on another action before controller I/O. Boolean and integer bounds
are strict, visible text is normalized, and create/update actions require the
exact boolean value `true`; numeric truth does not pass. The same exact-true
rule now also applies to egress and optional model-lifecycle receipts.

Every returned project, chat, or list is parsed through the strict
`agent-catalog.v2` models. The surface then checks requested project/chat
identity, project-scoped membership, archive filtering, list bounds, requested
field postconditions, and an exact one-step revision increase for updates.
Undeclared response fields, wrong identities, cross-project list members,
incorrect statuses, and revision mismatches fail closed as
`catalog_response_invalid`.

The MCP surface contract is now `prompt-enhancer-agent-mcp.v3`. The normal tool
set is seven tools; an explicitly lifecycle-enabled connection may add the
existing runtime tool.

## Destructive boundary

There is deliberately no catalog delete action. Generic `agent_invoke` now
refuses every manifest-declared DELETE operation with
`destructive_action_requires_agent_ui`, regardless of caller-supplied values.
The obsolete self-asserted destructive flag is rejected as an undeclared
field. Permanent project/chat/retained-history deletion remains available only
through the Agent UI's explicit flows.

This checkpoint does not claim that a browser dialog is a native user-presence
capability. It simply removes destructive catalog authority from MCP.

## Product guidance

The Agent settings drawer now explains the intended division directly:

- `agent_catalog` browses and organizes durable projects/chats;
- permanent deletion stays in the Agent UI;
- `agent_workspace` performs bounded read-only workspace inspection; and
- `agent_turn` requests file effects that still arrive for native review.

The controller guide, local-model integration guide, architectural decision,
and Agent trajectory ledger now document the v3 surface and delete boundary.

## Verification receipts

- The broader catalog/controller/MCP backend group passed **106/106** tests.
- The MCP connection card and cross-layer connection contract passed **9/9**
  frontend tests.
- Real synthetic loopback coverage exercised catalog reads and revision-bound
  updates over both the stdio fallback and direct process-free HTTP transport.
- Adversarial coverage rejects missing/false/numeric authorization, incoherent
  action fields, an invented delete action, unsafe response extensions,
  cross-project/chat identity, and wrong revision transitions before returning
  data to the client.
- The production frontend build completed with **536 transformed modules**.
- A guarded native reload reached zero old listeners before starting the exact
  repository virtual-environment launcher with a hidden window. The updated
  Agent shell and `agent_catalog` guidance are visible in the in-app browser.
- Startup briefly ran the two existing content-free Codex compatibility probe
  commands. They use Windows `CREATE_NO_WINDOW`, read an isolated empty provider
  home, and exited. Final runtime state is one application listener, one native
  window, one WebView child, no test listener, no provider child, and no local
  model process.
- `git diff --check` reports no whitespace error. The unchanged privacy scanner
  reports exactly the known pre-existing binary finding for
  `docs/checkpoint-agent-02-shell.png`; this checkpoint adds no finding and
  weakens no scanner rule.

No model was loaded, so no GPU/VRAM cleanup was required.

## Remaining gates and next bounded checkpoint

The real installed-client handshake still requires the owner to create one
scoped connection in the native Agent window because that action creates a
revocable bearer and requires owner presence. A real compatible-model turn,
Stop/unload receipt, one reviewed fictional file write, and the separate-window
walkthrough also remain finite owner-visible acceptance checks.

The next owner-free implementation slice should add a strict read-oriented MCP
history/artifact tool. It should let connected agents inspect bounded retained
conversation pages and artifact metadata/content without composing raw routes,
while continuing to refuse capture, binary export, deletion, approval, and
reusable mutation authority. That slice should be checkpointed independently
before any owner-visible acceptance action.
