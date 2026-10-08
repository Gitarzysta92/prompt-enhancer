# Agent checkpoint 08x handoff: truthful runtime, chat, and media context MCP

Date: 2026-08-28

## Outcome

Codex, Claude Code, and other scoped MCP clients now have a dedicated
`agent_context` tool instead of composing raw live-session, runtime,
compatibility, and attachment routes. The MCP surface contract is now
`prompt-enhancer-agent-mcp.v5` with ten default tools; an explicitly
lifecycle-enabled connection may add `agent_runtime` as the eleventh.

`agent_context` has two strict actions:

| Action | Read surface |
|---|---|
| `runtime` | sanitized runtime coordinator, path-free adapter/model compatibility, placement vocabulary, exact last-measured runtime context, and verified modality support |
| `chat` | the same runtime view plus one exact live chat's model settings, permission/recovery state, and staged image/audio metadata |

Every component response is parsed through its existing strict production
contract before projection. Project/chat scope, live-session identity, unique
model and attachment identities, staged state, expiry, and model binding are
rechecked. Installed models are sorted, capped at 200, and accompanied by exact
installed/returned/truncated counts.

## Truth and privacy boundary

The context receipt is the runtime coordinator's exact last measured request,
not a heuristic. The output explicitly labels it
`runtime_global_last_request` and sets `selected_chat_context_proven` to false;
this checkpoint does not misrepresent global evidence as selected-chat usage.
The complete snapshot is labelled `sequential_non_atomic` because its
read-only controller calls are not one database transaction.

The projection excludes:

- workspace paths and standing instructions;
- pending approval identifiers and reusable authority;
- process IDs and runtime binary digests;
- model-artifact and attachment digests;
- attachment or artifact bytes; and
- token-counting, attachment-staging, model-lifecycle, chat-mutation, approval,
  export, or deletion actions.

Image, audio, microphone recording, tools, and structured output are advertised
only from a verified live runtime capability probe. Accepted placement names
are reported as an API vocabulary, not as a claim that every placement will fit
the current hardware.

## Product guidance

The Agent settings drawer now explains `agent_context`, the global context
binding, the sequential snapshot boundary, verified modality reporting, and
the fields deliberately omitted. The controller guide, local-model integration
guide, architecture decision, and Agent trajectory ledger document the v5
surface and the remaining selected-chat context gap.

## Verification receipts

- The broader runtime/attachment/history/artifact/catalog/controller/MCP
  backend group passed **190/190** tests with one unchanged Starlette
  deprecation warning.
- The focused MCP unit and real-listener integration group passed **29/29**
  again after the final adapter/context-binding projection was added.
- The MCP connection card and cross-layer connection contract passed **9/9**
  frontend tests.
- Real synthetic coverage exercised both `runtime` and exact-project/chat
  views over the stdio fallback and direct process-free Streamable HTTP.
- Adversarial coverage rejects undeclared private fields, duplicate models,
  cross-project or cross-session records, attachment-byte extensions, stale
  attachment model binding, incoherent action shapes, and incomplete egress
  receipts.
- The production frontend build completed with **536 transformed modules**.
- A guarded native reload reached zero old listeners before starting the exact
  repository virtual-environment launcher with a hidden window. The updated
  Agent page hydrates as `Agent · Prompt Enhancer`; its settings show
  `agent_context` exactly once and state both the privacy and context-binding
  boundaries.
- The bounded hidden compatibility probes exited after startup. Final runtime
  state is one application listener, one native window, WebView children only,
  no test listener, and no provider or model child.
- `git diff --check` reports no whitespace error. The unchanged privacy scanner
  reports exactly the known pre-existing binary finding for
  `docs/checkpoint-agent-02-shell.png`; this checkpoint adds no finding and
  weakens no scanner rule.

No local model was loaded, so no GPU/VRAM cleanup was required. No commit or
push was performed.

## Remaining gates and next bounded checkpoint

The next owner-free slice should bind exact context-preflight evidence to the
live chat that produced it. Unmeasured and recovered chats must remain unknown;
the Agent runtime card and `agent_context` should consume the same session-bound
receipt. This closes the truthful per-chat context meter before adding an
external attachment-staging workflow.

The installed-client handshake, real compatible-model turn, Stop/unload
receipt, one reviewed fictional file write, and separate-window walkthrough
remain finite owner-visible acceptance checks.
