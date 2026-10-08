# Agent checkpoint 08q handoff: process-free direct MCP connections

Date: 2026-08-28

## Outcome

The Agent window now exposes an authenticated Streamable HTTP MCP endpoint at
`http://127.0.0.1:8765/mcp/agent`. Codex, Claude and other compatible clients
can connect to the already-running Prompt Enhancer listener without launching
an extra bridge process or terminal window for each client.

The Agent setup card can create, rotate and revoke narrowly scoped connection
credentials. Each secret is returned once, is never stored in plaintext, and
is not written to browser storage or left in the DOM after the user clears it.
Generated setup snippets are process-free by default. The prior stdio bridge
remains available only as an explicitly selected advanced fallback.

## Capability status after this checkpoint

| Capability | Verified implementation status | Remaining acceptance |
| --- | --- | --- |
| Create, browse, switch and close chats | Durable project/chat catalog implemented | Native owner click-through |
| Text chat, streaming and Stop | Implemented with cancellation and recovery states | Real chosen-model acceptance |
| Reasoning and tool activity | Model-provided reasoning summaries, actions and receipts are shown; hidden chain-of-thought is intentionally not claimed | Check presentation with the owner's models |
| Workspace files, diffs and protected approvals | Implemented; create, read, edit, move, recycle and change-set paths have bounded authority | Native approval click-through |
| Separate chat window | Implemented with synchronized state and closing recovery | Native multi-window acceptance |
| Durable Agent projects and chats after restart | Implemented in the Agent catalog with explicit retention controls | Owner restart check |
| Rename, search, pin, archive and restore | Implemented for Agent projects/chats | Owner UX pass |
| Project/chat database hierarchy | Implemented with migrations and lifecycle rules | Owner data-retention choice |
| Markdown and code rendering | Implemented with bounded rendering and safe links | Visual polish pass |
| Artifact/document cards and viewers | Implemented with safe local artifact contracts | Owner review with representative files |
| Image, audio and recording inputs | Implemented and capability-gated | Real multimodal model acceptance |
| Model switching and CPU/GPU placement | Implemented with explicit lifecycle states | Real hardware unload/placement acceptance |
| Context-usage meter | Reports known values and labels unavailable values as unknown | Real backend/tokenizer acceptance |
| Chat branching/forking/export | Implemented without restoring protected authority | Owner UX pass |
| External Agent orchestration | Direct scoped HTTP MCP implemented; process-free Codex and Claude setup snippets supplied | One real client handshake |

This table replaces the older screenshot's temporary/in-memory status. It does
not claim that every combination of native window, model, hardware and provider
has been accepted on the owner's machine.

## Security and lifecycle decisions

- The direct MCP transport accepts only its scoped bearer credential. The
  browser cookie and broad application token are rejected.
- Credential administration is outside the Agent controller's invocable
  namespace, so an attached controller cannot create or rotate its own access.
- Create, rotate and revoke require browser authentication and native user
  presence. Listing returns metadata only.
- Rotation invalidates the prior secret immediately; revocation is immediate;
  optional expiry and optional model-lifecycle authority are explicit.
- MCP requests are bounded, single-message JSON-RPC. Batches, malformed
  payloads, invalid encodings and unsupported methods fail closed.
- The controller re-enters the existing loopback listener through a worker
  thread, avoiding both a second server and same-listener deadlock.
- No provider configuration file was read or changed. No model was loaded for
  this checkpoint.
- The Windows Codex app-server adapter now prefers a native `codex.exe` over an
  npm `codex.cmd` shim and always supplies a nonzero no-window creation flag.
  The shim remains a compatibility fallback when no native executable exists.

## Verification receipts

- 216 focused/broad backend Agent tests passed after the final management-route
  isolation repair.
- 2,061 frontend tests across 155 files passed before the final route-string
  isolation; the changed contract/transport area then passed 177 focused tests.
- 66 Playwright workflows passed at 360 px and 1440 px.
- 87 focused Codex transport, schema-preflight, Windows-distribution and
  desktop-lifecycle tests passed after the console-launch repair. These overlap
  prior gates and are not an additional whole-suite total.
- 163 focused backend file-workflow tests and 209 focused frontend
  file/change/artifact tests passed. These overlap the broader gates and must
  not be added to them.
- A real ephemeral loopback integration exercised MCP initialization,
  discovery, workspace opening and durable project listing while any process
  launch was patched to fail.
- The production frontend build compiled 536 modules.
- OpenAPI generation parity, Python compilation, the frozen dependency lock
  and `git diff --check` passed. Ruff is not installed in the frozen offline
  environment and was not downloaded.
- The unchanged privacy scan reports only the pre-existing untracked binary
  `docs/checkpoint-agent-02-shell.png`; no new finding was introduced.
- A clean native restart left exactly one responsive Agent window and one owned
  listener. A second launch focused that instance and exited with code zero;
  it did not create a second window or listener. Windows UI inspection found
  zero visible terminal windows. The native connection form rendered with its
  create control enabled, but no credential was created during validation.

## Defect found during the broad gate

The first implementation placed connection administration below `/v1/agent`.
That made the endpoints candidates for the Agent controller manifest and could
have allowed self-administration. The routes were moved to
`/v1/integrations/agent-mcp/connections`, marked private/no-store and covered by
manifest and authorization regressions.

The final process audit also caught the Codex metadata adapter resolving the
npm command shim before a native executable. Although `CREATE_NO_WINDOW` was
already requested, the shim necessarily introduced `cmd.exe` into the child
tree. Resolution now prefers the native executable, the fallback flag is
nonzero even in frozen/package probes, and a live single-instance restart
showed no targetable terminal window.

## What remains genuinely unverified

1. An owner-visible native-window pass for project/chat management, the
   separate window, approvals and setup copy actions.
2. One real Codex or Claude HTTP MCP handshake after the owner deliberately
   pastes the one-time credential into that client's environment/config.
3. One finite real-model acceptance run covering response, stop, context usage,
   switch/unload and GPU cleanup. This is intentionally separate from automated
   tests so it cannot consume VRAM unexpectedly.
4. A final card-by-card visual polish pass after functional acceptance.

The next checkpoint should begin with items 1 and 2, then use the smallest
compatible local model for item 3 and explicitly unload it afterward.
