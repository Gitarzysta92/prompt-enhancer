# Checkpoint Agent-12f entry: usable composer runtime chooser

Date: 2026-09-01

This checkpoint repairs the compact Model & context control after owner review
showed that its expanded content could fall below a short browser viewport. It
also replaces the ambiguous `Improve` action with an explicit no-send prompt
review. Tests use only synthetic chats, models, paths, and runtime receipts.

## Frozen owner-visible contract

1. Model & context opens above its composer trigger in a viewport-bounded
   popover with its own scroll region; expanding it cannot grow the page below
   the visible short-window boundary.
2. Model, placement, context and the start/switch/bind action appear before
   optional diagnostic evidence.
3. Choosing settings changes only the pending selection. No model starts,
   switches, unloads, or binds until the person activates the primary action
   and that operation succeeds.
4. The popover has an explicit Close control and also dismisses on Escape and
   outside pointer interaction. Keyboard focus returns to the trigger after an
   explicit or Escape dismissal.
5. Compatibility, exact context and runtime facts remain available in a
   secondary evidence disclosure instead of crowding the decision path.
6. `Improve` becomes `Review prompt`, with persistent visible copy saying
   `Optional · no agent send`. It reviews the unsent draft and may offer a
   rewrite, but never submits a chat message or applies a rewrite automatically.
7. The behavior remains touch-sized, forced-colors compatible, and usable at
   the narrow Agent breakpoint.
8. Automated and live validation must not start or switch a local model.

## Required evidence

1. Component tests prove model selection, pending-switch state, explicit Close,
   Escape, outside-click, focus restoration and collapsed diagnostic evidence.
2. Layout contract tests prove upward anchoring, viewport-relative maximum
   height, internal scrolling and sticky decision controls.
3. Prompt-review tests prove the revised label/explanation and that checking a
   draft does not call the Agent send path.
4. The complete Agent test file, production build, API contract check, privacy
   scan and content-free live loopback DOM check pass.
