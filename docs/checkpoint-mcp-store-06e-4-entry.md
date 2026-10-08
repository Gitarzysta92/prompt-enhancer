# Checkpoint Store-06e.4 entry

Status: implementation active
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)

## Frozen user outcome

An admitted managed MCP tool must feel like a first-class Agent action instead
of an opaque model alias. The conversation shows the reviewed server and tool,
fresh native approval, ordered execution state, a bounded result and
content-free evidence. Stop, denial, timeout, failure and cleanup uncertainty
remain truthful. The compact project-tools control and MCP Store remain the
escape hatches for configuration; the chat is not turned into another Store.

## Evidence at entry

- Managed project tools are already added to the selected model's function
  schema only while exact project authority is ready.
- Every actual managed call already passes through a fresh native approval and
  the managed runtime records a content-free receipt.
- The runtime already bounds and validates arguments and result projection,
  handles cancellation/timeout and synchronously contains unsafe cleanup.
- The Agent event layer currently discards the safe server/tool identity and
  managed result receipt. The UI therefore renders an opaque `mcp_…` alias,
  generic approval copy and generic result facts.

## In scope

1. Add a strict, content-free Agent event projection for managed MCP server/tool
   identity and terminal result evidence.
2. Bind pending approval, approval resolution and terminal result to the exact
   model tool-call identity without persisting arguments or output.
3. Render concise MCP-specific request, waiting, approved/denied and terminal
   cards, with retained-history behavior that never implies raw output remains.
4. Preserve the redacted server-created approval preview and the fresh,
   non-reusable native confirmation boundary.
5. Prove success, tool error, denial, timeout, cancellation, stale/late ordering,
   cleanup uncertainty, privacy, keyboard and screen-reader behavior.
6. Validate 360 px and 1440 px chat layouts and the settings/Store escape hatch.

## Explicit exclusions

- No real MCP server is started and no protected action is approved during
  automated implementation.
- Registry/logo hostility belongs to Store-07a.
- Remote transport hostility belongs to Store-07b.
- Local child-process escape and terminal-window hostility belong to Store-07c.
- Schema bombs and approval replay beyond this UI integration belong to
  Store-07d; secret and cross-project hostility belong to Store-07e.
- No hidden chain of thought, raw credential, unredacted argument or durable raw
  tool result is added to Agent history.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Fresh request | Friendly server/tool identity and “one call only” authority are visible; opaque alias is secondary or hidden. |
| Waiting | The exact call has one accessible pending state and native approve/deny controls. |
| Approved success | Ordered resolution and terminal receipt show duration, approval, untracked external-effect truth, content mode, bounded bytes and verified cleanup. |
| Tool-reported error | The card says the tool reported an error; it does not claim transport failure or verified no effect. |
| Denied or approval timeout | Nothing is invoked; the terminal card records no effect and no reusable approval. |
| Stop before decision | Pending authority disappears, the call is cancelled before invocation and late approval cannot execute it. |
| Stop during invocation | Cancellation and cleanup evidence are terminal and later events cannot rewind the card. |
| Cleanup uncertain | The result is visibly unverified and further unsafe work remains blocked by the existing runtime boundary. |
| Retained history | Server/tool identity and content-free receipt survive; raw preview, arguments and result text do not. |
| Accessibility/layout | Keyboard-only approve/deny/expand/copy flow, descriptive names, status announcements and 360/1440 px layouts pass. |

## Expected touched surfaces

- Agent event and durable-history contracts;
- managed MCP-to-Agent execution projection;
- OpenAPI artifact and generated frontend contracts;
- Agent MCP activity component, approval dialog and timeline styles;
- focused backend, frontend, contract and two-width browser tests;
- checkpoint handoff and master milestone board.

Any unrelated regression is recorded against its owning future checkpoint. It
does not silently expand Store-06e.4.
