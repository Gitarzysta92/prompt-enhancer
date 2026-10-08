# Checkpoint Agent-12d entry: integrated capability-aware composer

Date: 2026-09-01

This checkpoint moves the controls required for one chat turn into the chat
composer without weakening the existing model-lifecycle, context-evidence,
attachment, privacy, or approval contracts. Tests use synthetic models,
projects, chats, paths, messages, media, and runtime receipts only.

## Frozen owner-visible contract

1. The project/chat rail remains navigation. It does not carry the primary
   model, context, media, or send controls for an open chat.
2. An open chat has one visually unified composer containing:
   - the message field;
   - the selected or served local model and its truthful runtime state;
   - exact context use when evidenced, and an explicit unknown/stale state when
     it is not;
   - capability-gated document, image, audio, and microphone controls;
   - prompt checking as a secondary action;
   - one unambiguous Send or Stop-response action.
3. Changing a model selection never claims the runtime changed. Start/switch,
   unload, placement admission, chat rebinding, cleanup uncertainty, and errors
   remain explicit and revision-safe.
4. Model switching preserves the exact chat, draft, attachments, and retained
   history. Media staged for another model remains visibly incompatible and is
   never silently reused.
5. Send is available only for a ready, correctly bound model and a non-empty
   text or attachment payload. While a response runs, the field remains usable
   for the next draft and the primary action becomes Stop response.
6. Text entry keeps Enter for a newline and Ctrl/Command+Enter for send. Every
   icon-only control has an accessible name, a 44 px target, visible focus, a
   truthful disabled reason, and a non-icon fallback in forced colors.
7. The composer remains usable at 360 px and desktop widths without horizontal
   scrolling, hiding the message field, or making expanded runtime/media
   settings overlap private conversation content.

## Implementation boundary

- Add a compact composer presentation to the existing runtime coordinator;
  do not create a second model state machine.
- Move that coordinator from the left rail into the active-chat composer.
- Present placement, context-limit, lifecycle actions, capability evidence, and
  diagnostics as progressively disclosed settings attached to the compact
  model/context row.
- Compact the existing attachment surface and expose microphone state in the
  composer toolbar; reuse its existing strict admission and cancellation logic.
- Use the existing send, Stop, prompt-check, draft, attachment, and session
  handlers. This slice is a UI composition change, not a parallel transport.

## Required evidence

1. Component tests for ready, loading, stopped, switching, cleanup-uncertain,
   unknown context, exact context, and active-response states.
2. A model switch test proving revision-bound unload/load/rebind calls and
   preserved draft/session identity.
3. Capability tests proving unsupported image/audio/microphone controls stay
   unavailable and supported controls use the existing local admission path.
4. Keyboard, accessible-name, focus-return, forced-color, reduced-motion, and
   360 px layout tests.
5. Full frontend, relevant backend/API/privacy gates, production build, and a
   protected localhost reload with one listener and zero model processes.
