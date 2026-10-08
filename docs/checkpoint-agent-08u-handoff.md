# Agent checkpoint 08u handoff: dedicated workspace MCP and clean live reload

Date: 2026-08-28

## Outcome

External coding agents no longer need to discover low-level HTTP operations to
inspect an Agent workspace. The direct and stdio MCP surfaces now advertise the
dedicated `agent_workspace` tool with five bounded, read-only actions:

- `inspect` returns the session's workspace discovery snapshot;
- `list` returns one bounded relative-path tree;
- `read` returns one validated editable UTF-8 file;
- `changes` returns the reviewed change-set summary;
- `diff` returns the diff for one exact relative path.

The tool accepts only a strict session identifier and normalized relative path.
It rejects drive-qualified, absolute, traversal, backslash, empty-segment,
query, fragment, control-character and surrogate paths before any controller
request. Each response is parsed through the operation-specific strict schema,
must preserve the requested session and path identities, and cannot contain an
undeclared field.

`agent_workspace` cannot create, edit, move, delete or apply a file; approve an
effect; run a command; fetch a page; or start, stop or switch a model. An
external agent requests edits through `agent_turn`, the native Agent window
shows the protected effect and diff, and the external agent continues with
`agent_wait` only after the owner decides. This preserves the existing native
review boundary while making read-oriented coding work practical.

The MCP contract is now `prompt-enhancer-agent-mcp.v2`. The normal tool set is
six tools; the separately acknowledged model-lifecycle mode may add its
existing runtime tool. Generated Codex and Claude configurations continue to
reference the client-process `PROMPT_ENHANCER_AGENT_MCP_TOKEN` environment
variable rather than embedding a bearer.

The Agent Connections drawer explains the read/edit split directly. A guarded
native reload closed the prior window through its confirmation, reached zero
listeners and zero model/provider children, and launched one updated hidden
desktop instance from the repository environment. The final state is one
loopback application listener, one native Agent window, one WebView child, no
test listener, no provider child and no model process. No console window was
created.

## Updated capability status

| Capability | Current status | Remaining gate |
|---|---|---|
| Create, browse, switch, close and delete chats | Implemented with a durable local catalog | Native owner walkthrough |
| Text chat, streaming and bounded Stop | Implemented | One real compatible-model lifecycle |
| Model-provided reasoning, progress, tools and receipts | Implemented when the model/runtime exposes structured activity | No hidden chain-of-thought claim |
| Workspace files, reviewed edits, transactions and diffs | Implemented in the native UI and now directly readable through MCP | One owner-reviewed native write |
| Separate chat window | Implemented with one application-owned child window | Native refocus/close walkthrough |
| Durable Agent projects | Implemented | Native owner walkthrough |
| Chats surviving restart | Implemented for Save locally; metadata-only content intentionally does not persist | Native owner walkthrough |
| Rename, search, pin, archive, restore, move and delete | Implemented | None beyond regression monitoring |
| Project/session database hierarchy | Implemented | None beyond migration monitoring |
| Rich Markdown/code rendering and safe workspace links | Implemented | Card-by-card visual polish |
| Artifact/document cards, immutable versions and viewers | Implemented | Native owner review |
| Images, audio files and local recording | Implemented only when runtime capability probes admit them | Real compatible-model check |
| Model switching and CPU/GPU/split placement | Implemented with revision and cleanup truth | Real model/GPU cleanup check |
| Context-usage meter | Implemented as exact or unknown; no invented estimate | Real runtime report check |
| Session branching, forking and bounded export | Implemented | None beyond regression monitoring |
| Direct Codex/Claude/other MCP orchestration | Implemented with project/chat/turn/wait plus strict workspace reads | One owner-created installed-client handshake |

This table does not claim universal Hugging Face compatibility. A model is
usable only after its registered adapter and live capability probe admit it.
The UI also does not expose hidden chain of thought; it shows only structured
reasoning or progress explicitly supplied by the model/runtime.

## Verification receipts

- The direct MCP/controller/local-Agent backend group passed **83/83** tests.
- The MCP connection card and cross-layer response contract passed **9/9**
  frontend tests.
- All five workspace actions crossed a real synthetic listener in the MCP
  integration suite. The test proves direct HTTP dispatch does not spawn a
  process.
- Adversarial tests reject unsafe paths before I/O, reject incoherent action/path
  combinations, and reject cross-session or cross-path responses.
- The production frontend build completed with **536 transformed modules**.
- A live in-app-browser reload showed the Agent shell, project/chat navigation,
  model/context controls and the new MCP tool guidance with no lifecycle error.
- `git diff --check` found no whitespace error. Its output contains only the
  repository's existing line-ending warnings.
- The privacy scanner retains its single known pre-existing binary finding for
  `docs/checkpoint-agent-02-shell.png`; this checkpoint adds no new finding and
  changes no scanner rule.
- Runtime hygiene found one loopback application listener, no browser-test
  listener, no provider child and no local model process. No model was loaded.

## Next bounded checkpoint

The next owner-free implementation slice should add an ergonomic, strict MCP
catalog tool for browsing and selecting durable Agent projects/chats without
asking clients to compose raw manifest operations. Read actions can remain
unprivileged under the connection scope; rename, pin, move, archive and restore
must retain their existing authorization and revision checks; delete must not
bypass native owner review. That slice should be tested separately from the
still-pending owner-visible gates.

The installed-client handshake, one real compatible-model turn/Stop/unload,
one reviewed fictional file write, and the separate-window walkthrough remain
finite owner-visible acceptance checks. They are not silently treated as
passing because synthetic tests passed.
