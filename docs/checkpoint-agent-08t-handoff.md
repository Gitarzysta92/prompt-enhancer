# Agent checkpoint 08t handoff: startup, workspace links, and direct MCP setup

Date: 2026-08-28

## Outcome

The Agent route now behaves like a returning chat workspace. After reload, an
existing durable catalog no longer opens the New chat drawer over the workbench.
The newest chat in the first active project that contains chats is selected,
its retained conversation is loaded when available, and both its project and
chat rows show the selected state. A truly empty catalog still opens onboarding.
A failed catalog request remains an error and is never presented as an empty
installation.

Live assistant messages may now cite a reviewed workspace file with a strict
relative link such as `[app.py](workspace:src/app.py)`. Selecting the link opens
Files & review at that path. Absolute paths, traversal, query/fragment suffixes,
control characters and malformed path segments remain inert. Retained or
inactive conversation content cannot trigger file navigation.

Direct Streamable HTTP MCP setup now keeps the bearer separate from generated
client configuration. Codex configuration refers to
`PROMPT_ENHANCER_AGENT_MCP_TOKEN` through `bearer_token_env_var`; Claude Code
configuration refers to the same client-process environment variable in its
Authorization header. Strict frontend and backend parsers reject a response
that inlines the bearer into either configuration.

## Updated capability status

The capability table that originally motivated this pass is no longer current.
The truthful status after this checkpoint is:

| Capability | Current status | Remaining gate |
|---|---|---|
| Create, browse, switch, close and delete chats | Implemented with a durable local catalog | Native owner walkthrough |
| Text chat, streaming and bounded Stop | Implemented | One real compatible-model lifecycle |
| Model-provided reasoning, progress, tools and receipts | Implemented when the model/runtime exposes structured activity | No hidden chain-of-thought claim |
| Workspace files, reviewed edits, transactions and diffs | Implemented | One owner-reviewed native write |
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
| Direct Codex/Claude/other MCP orchestration | Implemented at `/mcp/agent` with scoped expiring credentials | One owner-created installed-client handshake |

This does not claim universal Hugging Face compatibility. A model is usable only
after its registered adapter and live capability probe admit it. It also does
not expose hidden chain of thought; only model-provided structured reasoning or
progress events may be shown.

## Verification receipts

- The complete Agent page suite passed **101/101** lifecycle, race, Stop,
  runtime, retained-history, workspace, prompt-check and attachment cases.
- The catalog rail, message renderer, direct-connection card and cross-layer MCP
  response parser passed **23/23** focused tests.
- The direct MCP, controller and local-Agent backend group passed **74/74**
  tests.
- The production frontend build completed with **536 transformed modules**.
- A live in-app-browser reload found one selected project, one selected chat, a
  visible conversation, no catalog error and no New chat overlay. The
  Connections drawer loaded without creating a credential.
- A live unauthenticated request to `/mcp/agent` returned **401**, confirming the
  endpoint fails closed. Authenticated initialize/discovery/tool calls are
  covered by the synthetic backend integration suite.
- Runtime hygiene found one loopback application listener, no browser-test
  listener and no local model process. No model was loaded during this pass.
- `git diff --check` passed. The privacy scanner retains its single known
  pre-existing binary finding for `docs/checkpoint-agent-02-shell.png`; this
  checkpoint adds no new finding and changes no scanner rule.

## Next bounded checkpoint

Implementation should now pause at the real-runtime boundary. The next useful
checkpoint is an owner-visible, finite acceptance run:

1. create one scoped direct MCP connection and complete one Codex or Claude Code
   Streamable HTTP initialize/discover call;
2. load one explicitly chosen compatible local model, send one synthetic turn,
   exercise Stop and context reporting, then unload it and verify process/GPU
   cleanup;
3. revalidate protected authority, review one fictional file diff and approve or
   decline it in the native window;
4. after those functional gates, perform the promised card-by-card visual polish
   pass without reopening the architecture.

These steps require owner-visible native confirmation or a real model choice.
They should remain bounded and recorded separately so they cannot recreate the
earlier open-ended loop.
