# Agent checkpoint 10n — media and verified-output UX

Date: 2026-08-29

## Outcome

The composer now keeps image, audio, and microphone choices in one compact
**Attach media** picker instead of exposing four peer actions at all times.
The trigger, refresh action, picker choices, removal actions, artifact cards,
viewer actions, zoom controls, and version selector now share a minimum 44 px
interaction target.

After a completed durable turn, the conversation also keeps a truthful output
card visible even when no reviewed write exists. It explicitly distinguishes a
model statement from a verified workspace file; no model claim is promoted to
an artifact.

## Reproduced defects

1. Live **Add image**, **Add audio**, and **Record audio** actions measured only
   37.6 px and permanently occupied the composer even when the model supported
   no media input.
2. Artifact Preview, Refresh, Close, Markdown view, footer, zoom, and version
   controls inherited 36–40 px targets.
3. A completed turn with zero reviewed writes unmounted the entire output
   surface, so an assistant could say it created a document while the UI gave
   no persistent verification or refusal feedback.

## Implemented boundary

- **Attach media** is the one always-visible entry point and includes the staged
  count; **Refresh staged** remains directly available for external-agent and
  remount recovery.
- Opening the picker reveals image, WAV, and recording choices plus the exact
  capability explanation. Unsupported choices remain disabled without
  pretending compatibility.
- Escape and outside-pointer dismissal close the picker; Escape restores focus
  to its trigger. Active or starting recording keeps Stop reachable.
- Runtime/session replacement closes the picker and retains all existing
  cancellation, track-release, Blob URL cleanup, serialization, model-match,
  and attachment-retention behavior.
- Empty artifact state appears only after a durable chat has at least one turn.
  Zero-turn chats remain uncluttered.
- Reviewed writes and exact native capture remain the only artifact sources.
  No file bytes, model, microphone, approval, controller, or remote authority
  were introduced by this checkpoint.

## Verification

- Focused attachment/artifact/capture/layout suite: **49/49 passed**.
- Complete Agent page integration suite: **121/121 passed**.
- Affected Chromium matrix: **6/6 unique scenarios passed** at 360 and 1440 px:
  multimodal stage/remove/attachment-only Send, revision-bound generated-output
  capture, and inert image/PDF/Office viewers.
- Browser assertions cover 44 px media, artifact-card, capture-dialog, viewer,
  and zoom actions; the existing retained-history scenario covers the
  multi-version selector.
- Production TypeScript/Vite build: **553 modules**, passed.
- Rebuilt live application:
  - Attach media and Refresh staged measured exactly 44 px;
  - image, audio, and recording choices measured exactly 44 px;
  - unsupported live-model choices were truthfully disabled;
  - Escape closed the picker and restored trigger focus;
  - no horizontal overflow and zero browser diagnostics.
- Final runtime inventory: one Prompt Enhancer window/listener on
  `127.0.0.1:8765`, zero detected local-model server processes, and zero visible
  terminal windows.

Live verification did not start a model or request microphone access. Verified
image/audio admission and capture are covered with synthetic files and a
mocked local microphone boundary; the real multimodal-model and native capture
walkthroughs remain explicit owner gates.

## Next checkpoint

Agent-10o should audit the separate-chat-window lifecycle and focus path as one
bounded slice: open/refocus/de-duplicate, selected-chat synchronization,
main/child close ordering, app-reload recovery, and terminal/process silence.
Use synthetic sessions and no model first; keep a real model-backed window turn
as a later owner-confirmed gate.
