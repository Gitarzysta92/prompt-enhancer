# Agent checkpoint 10j — medium-width chat-first shell

Date: 2026-08-29

## Outcome

The main Agent route no longer renders two permanent navigation rails at
medium desktop widths. From 861 through 1180 px, the global application rail
and top bar collapse into one compact header while the Agent project/chat rail
remains visible. The conversation therefore stays the primary work surface,
and every global destination remains available through **Menu**.

This is route-scoped. Overview, Projects, Sessions, and the other application
routes keep their existing desktop shell at the same widths. The existing
mobile shell below 861 px and the chrome-less dedicated Agent window are also
unchanged.

## Reproduced defect

At the owner's current 1046 × 912 in-app-browser viewport, the global
application rail and Agent project/chat rail consumed enough width to leave
only about 547 px for the conversation. The layout was technically responsive
but did not behave like a chat-first coding workspace.

## Implemented boundary

- The compact-shell query is route aware: Agent uses 1180 px; other routes use
  the existing 860 px boundary.
- The Agent route receives an explicit `app-shell--agent-focus` state.
- Between 861 and 1180 px, that state hides only the redundant global rail and
  top bar, and renders the existing identity, runtime, theme, and Menu controls
  in a one-row sticky header.
- Menu still opens the full grouped application navigation and marks Agent as
  the current destination.
- Touch targets remain at least 44 px and the focused shell is horizontally
  bounded.

No project, chat, model, workspace, approval, controller, MCP, retention, or
privacy contract changed.

## Verification

- Focused App/layout component contracts: **36/36 passed**.
- Exact Playwright scenario at 1046 × 912: **1/1 passed**.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live application at 1046 × 912:
  - `app-shell--agent-focus` present;
  - conversation width **761 px** (about **214 px wider** than the reproduced
    547 px state);
  - global rail absent, Agent rail retained, Menu reachable;
  - no horizontal overflow;
  - zero browser diagnostics.
- Final runtime inventory: one window, one listener on `127.0.0.1:8765`, the
  shared runtime visibly **Stopped**, and zero `llama-server`, Ollama, or
  KoboldCpp processes. The desktop app was restarted through its normal quit
  confirmation and relaunched with a hidden host process; no terminal window
  was opened.

The full historical frontend/backend/browser matrices were not rerun because
this slice changes only the route-aware shell and its responsive CSS. Their
last complete receipts remain in Agent-10i.

## Retained-chat audit note

Retained local-history chats do render their immutable artifact cards inline.
Their file editor and **Add output** capture flow intentionally appear after
**Resume chat**, because workspace access and native-confirmed capture are
live-session authorities and are not restored from history. The retained view
does not silently reconstruct those authorities.

## Next checkpoint

Continue the card-by-card audit with the Agent rail and runtime card at desktop
and narrow widths: verify density, collapse/reopen behavior, search/action
dialogs, stopped/transition/error truth, and keyboard focus. Only reproduced
failures become implementation work. The owner-controlled artifact,
separate-window, real-model, Stop, reviewed-write, unload, and GPU-cleanup
acceptance remains a later explicit gate.
