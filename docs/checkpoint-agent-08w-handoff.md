# Agent checkpoint 08w handoff: retained history and artifact metadata MCP

Date: 2026-08-28

## Outcome

External Codex, Claude Code, and other MCP clients can now inspect bounded
retained conversation history and generated-document lineage without composing
raw controller routes. The MCP surface contract is now
`prompt-enhancer-agent-mcp.v4` with nine default tools; an explicitly
lifecycle-enabled connection may add the existing runtime tool.

| Tool | Read surface | Deliberate boundary |
|---|---|---|
| `agent_history` | one exact durable chat, strict `after` cursor, limit `1..500` | no export, live authority, approval state, raw tool arguments/results, or reusable receipts |
| `agent_artifacts` | bounded metadata list or one exact artifact lineage record | no artifact bytes, capture, workspace write, export, or delete |

Both inputs are strict discriminated models. Project, chat, and artifact IDs
must be exact local identifiers; integers and booleans are strict; undeclared
fields and incoherent action shapes are rejected before controller I/O.

Every response is parsed through the existing strict retained-history or
artifact contract and checked again for requested identity, scope, cursor and
limit coherence, ordering, uniqueness, allowed retained event kinds, and the
absence of live or privileged fields. Cross-project records, cross-chat
records, duplicate artifacts, unexpected binary responses, and response-schema
extensions fail closed.

## Product guidance

The Agent settings drawer now explains the intended boundary directly:

- `agent_history` pages through locally retained visible events;
- `agent_artifacts` returns generated-document lineage metadata only;
- neither tool exports history, returns artifact bytes, captures files, or
  deletes data; and
- image, PDF, and download-only artifact content stays in the native viewer.

The controller guide, local-model integration guide, architecture decision,
and Agent trajectory ledger now document the v4 surface.

## Verification receipts

- The broader history/artifact/catalog/controller/MCP backend group passed
  **127/127** tests with one unchanged Starlette deprecation warning.
- The focused MCP unit and real-listener integration group passed **26/26**
  again after the final condition-readability cleanup.
- The MCP connection card and cross-layer connection contract passed **9/9**
  frontend tests.
- Real synthetic loopback coverage exercised retained history and artifact-list
  reads over both the stdio fallback and direct process-free HTTP transport.
- Adversarial coverage rejects malformed bounds, undeclared action fields,
  cross-scope identities, raw tool arguments, live session state, incoherent
  cursors, duplicate artifacts, and binary artifact responses.
- The production frontend build completed with **536 transformed modules**.
- A guarded native reload reached zero old listeners before starting the exact
  repository virtual-environment launcher with a hidden window. The updated
  Agent page hydrates as `Agent · Prompt Enhancer`; its settings show each new
  tool exactly once and state the no-byte/no-export/no-delete boundary.
- The two bounded, hidden Codex compatibility probes exited after startup.
  Final runtime state is one application listener, one native window, WebView
  children only, no test listener, and no provider child.
- `git diff --check` reports no whitespace error. The unchanged privacy scanner
  reports exactly the known pre-existing binary finding for
  `docs/checkpoint-agent-02-shell.png`; this checkpoint adds no finding and
  weakens no scanner rule.

No model was loaded, so no GPU/VRAM cleanup was required. No commit or push was
performed.

## Remaining gates and next bounded checkpoint

The real installed-client handshake still requires the owner to create one
scoped connection in the native Agent window because that creates a revocable
bearer and requires owner presence. A real compatible-model turn, Stop/unload
receipt, one reviewed fictional file write, and the separate-window walkthrough
also remain finite owner-visible acceptance checks.

The next owner-free slice should add a dedicated, read-only MCP context and
capability view. It should report exact selected-chat/runtime context usage,
model placement support, and attachment capability metadata without returning
attachment bytes, loading a model, or granting mutation authority. That keeps
the Codex-style model/context/media controls truthful before the owner-visible
end-to-end checks.
