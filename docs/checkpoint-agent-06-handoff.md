# Agent-06 handoff: capability-gated image, audio, and microphone input

Date: 2026-08-27
Status: implementation and synthetic automated/browser verification complete; native owner reload and real multimodal-model checks remain deferred

## Outcome

The authored local Agent chat now accepts bounded image and audio attachments
without pretending every local LLM supports them. PNG/JPEG, PCM WAV, and local
microphone controls are driven by the exact served runtime's verified
capabilities. Text-only or unverified runtimes show a locked explanation.

The complete flow now covers explicit projector registration, runtime probing,
private upload and preview, staged recovery/removal, attachment-only messages,
OpenAI-compatible image/audio forwarding, payload-free history identity, and
retention-specific settlement.

## Implemented boundary

- Local model registration has an explicit `mmproj_path`; activation adds
  `--mmproj`. Automatic scans skip projectors rather than guessing pairings.
- `local-runtime-multimodal-probe.v2` checks the live served runtime. Vision,
  audio, and microphone eligibility fail closed and never derive from a model
  name, filename, or catalog claim.
- `agent-attachment.v1` stores exact session/model/probe identity, sanitized
  display name, media kind/type, digest, bytes, dimensions or WAV properties,
  source, state, retention, expiry, and the bound user-event sequence.
- Admission supports structure-valid PNG/JPEG and uncompressed PCM WAV only.
  It rejects empty, mismatched, corrupt, oversized, over-dimension, excessive
  pixel/duration, unsupported sample-rate/channel, duplicate, expired,
  wrong-session, wrong-model, unsupported-capability, and already-sent cases.
- Current ceilings are four attachments and 16 MiB per message; 16 staged and
  64 MiB per session; 8 MiB per image; 12 MiB per WAV; 8,192 pixels per
  dimension; 33,554,432 pixels; and five minutes per admitted WAV. Staged
  authority expires after one hour.
- Images are forwarded as `image_url` data URLs; WAV is forwarded as
  `input_audio` with raw base64 and `format: "wav"`. The exact capability and
  payload are revalidated immediately before each model request.
- Event/history journals retain metadata and digest only, never bytes.
  Metadata-only chats delete sent payloads. Save-locally chats retain private
  payloads for exact restart recovery and cascade-delete them with the chat.
- The composer supports multiple file selection, local previews, removal,
  recovered staged drafts, attachment-only sends, successful-send cleanup, and
  preservation after failure. Sent messages render payload-free media cards.
- The microphone path records local mono PCM16 WAV, resamples to 16 kHz, stops
  at two minutes, and releases every media track and audio context on stop,
  cancellation, error, remount, and session switch.
- Attachment preview routes use private/no-store, no-sniff, same-origin,
  no-referrer, safe-disposition and exact-size headers. No remote media fetch or
  browser-storage transcript cache was added.
- The UI reports audio as experimental and media context cost as unknown. No
  unreported token usage is estimated.

## Correctness repairs found during validation

1. Runtime capability contracts initially allowed `recording=true` while
   `audio=false`. Backend and frontend parsers now reject that incoherent state.
2. A failed object-URL preview could have erased a valid admitted attachment.
   Preview failure now affects only the optional local rendering, not identity.
3. The microphone control originally followed audio alone. It now additionally
   requires the explicit recording capability and a usable local media API.
4. Rendered acceptance found older synthetic Agent events without the new
   mandatory empty `attachments` collection. The full chat surface crashed on
   those fixtures; the event factory now emits the exact current contract.
5. The cleanup-quarantine browser test looked for a disabled New Chat action
   while its sheet was intentionally closed. It now opens the sheet, proves the
   action is disabled, closes it, and keeps the responsive boundary assertion.
6. User-facing validation language now says strict format-structure validation;
   it no longer implies a general-purpose image decoder ran.

## Verification receipts

- Attachment and local-runtime backend slice: **53 passed**. The broader
  catalog, Agent, attachment, model, completion, usage, background-control and
  cancellation selection: **230 passed**.
- Complete frontend unit/component gate: **1,979 tests across 146 files**.
  Focused attachment/runtime tests passed **36**, and the Agent page,
  HTTP-transport and Models integration selection passed **284**.
- Production TypeScript/Vite build passed with **523 modules transformed**;
  generated OpenAPI consistency passed.
- `git diff --check` passed; Git reported only the repository's existing
  Windows LF-to-CRLF notices and no whitespace error.
- The multimodal composed-UI Playwright slice passed at 360 and 1,440 px,
  including WAV stage/remove, PNG preview, attachment-only send, payload-free
  message card, successful cleanup and page-width containment.
- The complete Playwright gate passed **111/111** after the compatibility and
  cleanup-sheet assertion repairs.
- Manual rendered inspection passed at 1,440 x 1,000 and 390 x 844. The
  attachment region exactly matched the composer width, all verified controls
  were usable, and neither viewport had page-wide horizontal overflow. Browser
  logs contained no new error after the compatibility repair.
- The privacy scanner found only the known pre-existing untracked binary
  `docs/checkpoint-agent-02-shell.png`. No Agent-06 source, fixture, or document
  added another finding; the existing file was not deleted or bypassed.
- The repository-wide backend invocation was deliberately stopped during its
  initial pass because it is far larger than this checkpoint's bounded suite;
  no complete-suite claim is made. The 230-test selected receipt above is the
  backend evidence for Agent-06.
- No Prompt Enhancer or `llama-server` process remained. Ports 8765 and 8766
  were closed. Only the existing synthetic Vite fixture remained on loopback
  port 4173. No native app, local model, GPU inference job, Claude CLI, or
  additional server was launched.

## Owner checklist after the later native reload

1. Register a synthetic-compatible multimodal GGUF and its exact projector.
   Confirm the record shows the projector and the served runtime—not the name—
   decides which capabilities are verified.
2. Compare a text-only runtime, a verified vision runtime, and a verified audio
   runtime. Confirm image, WAV, and microphone controls lock/unlock exactly.
3. Attach a valid synthetic PNG/JPEG, preview it, remove it, then send an
   image-only message. Repeat with short PCM WAV and microphone recording.
4. Deny microphone permission and confirm no attachment appears and every
   capture track closes. Stop a recording, switch chat/model, and close the
   window while recording to confirm cleanup remains bounded.
5. Stage media, switch models, and send. Confirm the server rejects the stale
   model binding and the composer preserves enough identity to remove/re-add it.
6. Test wrong suffix, corrupt structure, oversized dimensions, long audio,
   duplicate IDs, fifth attachment, expired stage, interrupted upload, and a
   model that advertises no matching capability. None may reach inference.
7. Restart one metadata-only and one Save-locally chat. Confirm only the saved
   chat can recover exact attachment bytes, while neither restores approvals or
   reusable authority. Delete it and confirm its attachment rows disappear.
8. Inspect runtime context reporting. It must remain “context cost unknown”
   unless the runtime supplies real per-attachment usage.

These owner checks are intentionally not marked passed. They require native
permission prompts and optional real-model/GPU use, which were avoided after
the previously reported visible-terminal cascade.

## Capability-list status and next checkpoint

Agent-06 completes the list's basic image input, WAV input, local recording,
exact capability gating, private retention, and multimodal message rendering.
It does not claim arbitrary Hugging Face models, video, arbitrary audio codecs,
full image decode, or known media token cost.

The next correct slice is **Agent-07 — broader Hugging Face compatibility and
truthful context**: catalog-versus-executable compatibility states, pinned
runtime/model/tokenizer/licence identities, architecture-family admission,
server-side context admission/compaction policy, and a generated compatibility
matrix. Session branching/forking/export refinement remains a later explicit
slice rather than being mixed into runtime compatibility.
