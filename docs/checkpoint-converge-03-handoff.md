# Converge-03 handoff — Agent information architecture

Status: automated implementation complete on 2026-09-04; owner visual review pending

## Outcome

The live Agent conversation now owns its viewport. At a 1280 by 720 desktop
viewport the latest reply, compact composer and Send control remain visible,
while project navigation, runtime configuration, workspace review, project MCP
tools, controller/readiness surfaces and session metadata remain available
without competing with the chat.

This is not a claim that the packaged Agent/model journey is release-complete.
Native UI, real-model hardware and subjective visual evidence remain separate.

## Changed

- The live conversation has three direct layout rows: compact activity header,
  transcript-owned stage and composer. Notices and approvals are contained by the
  stage instead of silently creating extra grid rows that push the composer away.
- The project/chat rail has one desktop vertical scroll owner. Project and chat
  lists no longer create nested desktop scroll traps.
- Project MCP status moved from the conversation stack into Agent settings →
  Connections. A compact `Project tools` action opens that exact destination.
- Secondary workspace/model/session metadata moved behind `Chat details`.
  Healthy duplicate runtime readiness is no longer another visible status card.
  The disclosure has an explicit keyboard-focus-restoring close action, including
  when it becomes a bounded narrow-screen overlay.
- The compact composer retains attachments, model/placement/context and
  Send/Stop. It owns exactly one dedicated polite runtime-state announcer.
- The transcript header is no longer sticky over interactive turn receipts. Both
  main and separate-window receipts now accept a real pointer click as well as
  keyboard input.
- Agent folder, file and locked entries now use the shared icon system instead of
  ad-hoc emoji.
- `AgentPage.tsx` was reduced from 4,606 to about 4,038 lines. Header rendering,
  retained-history/timeline/event rendering and event presentation helpers now
  have separate testable modules.
- The zero-interception runner now finds the repository virtual environment when
  npm is launched from an unactivated shell, uses no-window child creation, and
  returns redacted child progress. Its real-loopback project-tools journey was
  reconciled with the new Connections location.

## Validated

- Production frontend build: passed.
- Standard serial browser matrix: **166/166 passed**.
- Intercepted frontend/HTTP contract matrix: **41/41 passed**.
- Production-build, zero-interception real-loopback matrix: **16/16 passed**.
- Focused backend and loopback-harness group: **87/87 passed**.
- Focused final Agent page/header contract: **168/168 passed**.
- Generated OpenAPI/TypeScript drift check: passed.
- Repository privacy scan: passed.
- Tracked-diff whitespace check: passed apart from Git's existing Windows
  LF-to-CRLF notices.

The browser evidence includes 320/360/768/1440 responsive semantics and contrast,
forced colors, reduced motion, keyboard focus, maximum Agent catalogs, main and
separate-window flows, the exact 720 px viewport contract, one runtime announcer,
one desktop rail scroll owner, dismissible Chat details and pointer-opened turn
receipts.

The real-loopback shutdown receipt records: listener released, runtime cleanup
confirmed, server thread clean, temporary state removed and **0 model runtimes
remaining**.

## Still locked or unproven

- Owner acceptance of the actual desktop and narrow appearance is pending.
- The owner's existing app was deliberately not restarted because an unobservable
  unsent draft may exist. No owner session, prompt, workspace content or provider
  configuration was inspected.
- Packaged native folder selection and approvals, real GGUF CPU/GPU/supported
  split inference, long-running Stop, app restart, model switch/unload, objective
  VRAM release and the no-visible-terminal process census remain Converge-04.
- A trusted third-party MCP package and a current external-controller walkthrough
  remain Converge-05. Signed update/apply/relaunch/rollback remains Converge-07.
- The Agent production chunk is still large even though source ownership is
  clearer. Performance/code-splitting remains a release-hardening concern, not a
  hidden success claim.

## Owner click-later checklist

After saving or sending any draft in the current app:

1. Reload the normal application and open one existing Agent chat at roughly
   1280 by 720. Confirm the latest reply and composer are visible together.
2. Open and close `Chat details`; confirm it feels secondary, remains readable and
   returns focus to its toggle.
3. Open `Project tools`, then `Files & review`; confirm each appears as a focused
   secondary surface and the composer draft remains unchanged after closing it.
4. Repeat at a narrow window. Confirm the conversation appears before the project
   rail, the metadata overlay has a reachable close control, and no terminal
   window appears.

No model download or load is required for this visual review.

## Next checkpoint

Converge-04: prove the packaged real Agent core loop and cleanup. Safe automated
preparation may proceed independently, but native folder/approval, physical
model/VRAM and owner-machine process evidence must remain explicitly owner-gated.
