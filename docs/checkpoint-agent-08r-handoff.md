# Agent checkpoint 08r handoff: chat-first shell and subordinate setup drawers

Date: 2026-08-28

## Outcome

The Agent page now keeps durable projects and chats as its persistent navigation
surface while moving secondary setup out of the main workbench. **New chat**
opens a dedicated setup drawer. **Agent settings** opens a separate drawer with
direct tabs for Connections, Owner checks and Team folders. The conversation
remains the visual and keyboard focus of the page.

No capability was removed. Workspace/model/retention/permission controls still
exist in New chat, while direct MCP setup, native acceptance and sharing remain
available from Agent settings. Lower-level stdio and script templates stay in
the explicit Advanced disclosure.

## Repairs made during validation

- The settings drawer was given explicit header, tab and scroll rows after live
  browser validation found its tabs overlapping panel content.
- Drawer insets and maximum height were corrected at desktop and 360 px so the
  sheets remain inside the viewport without horizontal overflow.
- The Agent settings trigger now keeps a minimum 44 px target despite the
  global button rule.
- Selecting a saved chat closes the New chat drawer before focusing the
  conversation.
- During uncertain command cleanup, New chat setup can be inspected safely,
  while actual session creation remains blocked.
- Escape closes either drawer and restores focus to the originating settings
  trigger where applicable.

## Verification receipts

- **115/115** focused Agent page, catalog rail, controller and layout component
  tests passed in one isolated consolidated run.
- **66/66** Chromium workflows passed at 360 px and 1440 px, covering the main
  and dedicated Agent views alongside cleanup, saved history, multimodal input,
  workspace, model and keyboard behaviors.
- A first deliberately parallel run placed the 115 component cases beside ten
  Playwright workers. It produced one five-second Stop-test timeout and one
  cascading missing-control failure while all 66 browser cases passed. The
  complete component suite then passed alone; the failed oversubscribed run is
  retained here rather than presented as a clean receipt.
- The production frontend build completed with 536 transformed modules.
- `git diff --check` passed. The unchanged repository privacy scan reports one
  finding: the pre-existing untracked binary
  `docs/checkpoint-agent-02-shell.png`; this checkpoint introduced no new
  finding and did not weaken or bypass the scanner.
- Live in-app browser validation opened every settings tab, opened and closed
  the New chat drawer, verified Escape behavior, observed zero console errors,
  and measured no horizontal overflow at a temporary 360 px viewport.
- The native Agent window was refreshed after the production build. The final
  runtime audit found one responsive loopback listener, one Agent window, zero
  targetable visible terminal windows and zero `llama-server`/`llama-cli`
  processes.
- No model was loaded and no real provider/session content or configuration was
  read. Validation used synthetic UI state only.

## Current capability boundary

This checkpoint improves hierarchy and interaction quality; it does not expand
the authority or acceptance claims from Agent-08q. Durable projects/chats,
rename/search/pin/archive/restore, artifacts, multimodal input, model placement,
context reporting, branching/export and process-free direct MCP are
implemented. The following still require owner-visible or real-runtime
acceptance:

1. Native click-through for project/chat lifecycle, file approvals and the
   separate chat window.
2. One real Codex or Claude Streamable HTTP MCP handshake using a deliberately
   created one-time credential.
3. One finite compatible-model run covering response, Stop, context reporting,
   placement switching, unload and GPU cleanup.
4. Card-by-card visual polish after those functional acceptance passes.

The next bounded checkpoint should be item 1: native project/chat lifecycle and
approval acceptance, using fictional content and without loading a model.
