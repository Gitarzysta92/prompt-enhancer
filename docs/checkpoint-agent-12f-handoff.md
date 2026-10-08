# Checkpoint Agent-12f handoff: usable composer runtime chooser

Date: 2026-09-01

Status: automated implementation complete; owner narrow-window visual review pending

Entry contract: [Agent-12f entry](checkpoint-agent-12f-entry.md)

## Outcome

The active-chat Model & context control is now a compact anchored popover that
opens upward from the composer, stays bounded by the current viewport, and
scrolls internally. The model selector and the primary start/switch/bind action
are part of the decision path; detailed compatibility, context and runtime facts
remain available under a separate evidence disclosure.

Changing a select value still does not change the runtime. The visible guidance
and decision receipt state that nothing changes until the primary action
succeeds. The popover closes through its Close button, Escape, or an outside
pointer action, with focus restoration for keyboard dismissal.

The former `Improve` action is now `Review prompt` and permanently carries the
visible explanation `Optional · no agent send`. It checks the unsent draft and
can offer a rewrite for explicit adoption; it does not send a message or replace
the draft automatically.

## Automated evidence

- Runtime and layout contracts passed: **2 files / 42 tests**.
- The complete Agent page gate passed: **1 file / 163 tests**.
- Production TypeScript/Vite build passed.
- Generated API contract check, privacy scan and `git diff --check` passed.
- Tests cover model selection, pending-switch state, internal evidence,
  explicit Close, Escape, outside-click, focus restoration, narrow-layout CSS,
  prompt-review copy and no-send behavior.

All fixtures and browser checks were synthetic or content-free. No provider
transcript, real prompt, response, tool payload, credential or private workspace
content was read.

## Live reload evidence

- `/agent` was rebuilt and reloaded in the existing loopback browser.
- Health returned successfully with exactly one listener bound only to loopback.
- Exactly one runtime region, one exact Model select, one placement select, one
  context select, one runtime dialog and one no-send Review prompt action were
  present.
- The runtime dialog opened, its Apply guidance and evidence disclosure were
  visible, and Close and Escape both dismissed it.
- No model selection was applied and no model was started during validation.

## Click later

1. In a short or narrow Agent window, expand Model & context and confirm the
   entire choice flow stays reachable by scrolling inside the upward popover.
2. Choose a model and confirm the summary reports a pending change before you
   press Start model or Switch model.
3. Close with the button, reopen, then close with Escape.
4. Enter a harmless draft after a model is bound and use Review prompt; confirm
   the proposed rewrite waits for `Use suggested prompt` and nothing is sent.

## Next checkpoint

Return to **Release-01a.3**: prove combined Windows process ownership and cleanup
under repeated start, Stop, crash, timeout and listener collision, with no
visible terminal storm and no orphaned model, command, MCP or helper descendant.
