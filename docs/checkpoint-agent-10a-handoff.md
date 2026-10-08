# Agent checkpoint 10a — media composer lifecycle ownership

Date: 2026-08-28

## Outcome

The Agent composer now treats image selection, WAV selection, microphone
permission, active recording, staged-media refresh, upload, removal, and Send
as one scope-owned lifecycle. A stale chat, model runtime, transport, disabled
chat, or unmounted window cannot keep a microphone capture alive or apply a
late media result to the replacement composer.

This slice does not claim that an installed model supports media because of its
name or metadata. Image, audio, and recording controls remain gated by the
exact served runtime's successful capability probe.

## Repaired behavior

- Requesting microphone permission and recording now block Send continuously
  through WAV encoding and staging. The UI distinguishes **Starting
  microphone…**, **Recording locally…**, and **Updating staged media…**.
- A microphone grant that resolves after model/runtime replacement, chat
  disablement, session replacement, transport replacement, or unmount is
  immediately cancelled and its tracks are released. No recording is staged.
- Partial Web Audio setup failure disconnects every constructed node, stops all
  granted tracks, and closes the audio context.
- Upload and removal mutations carry `AbortSignal` ownership and ignore late
  results after their exact runtime/session scope is replaced.
- Staged-media listing is serialized ahead of user mutation, so a late initial
  or manual refresh cannot overwrite a newer upload or removal. Hidden file
  inputs are disabled with their visible controls.
- A failed refresh preserves the current chat's already-known staged identities
  instead of blanking the draft. Cross-session identities are still filtered
  immediately.
- Retained media staged for another model is labelled **different model** and
  blocks Send until removed and added again. The user can still refresh or
  remove staged media while no model is running.
- Local image/audio bytes remain private Blob-backed previews. External-agent
  media remains explicitly labelled, and only staged identities enter a Send
  request.

No real microphone, model, GPU worker, file write, download, provider session,
or remote endpoint was used by this checkpoint. It grants no approval,
workspace, command, web, controller, MCP, or reusable mutation authority.

## Verification

- Composer and WAV recorder: **19/19 tests passed** across two files.
- Attachment/event contracts: **12/12 tests passed**.
- HTTP attachment boundary: **4/4 focused tests passed**.
- Backend attachment vault: **17/17 tests passed**.
- Page-level model-mismatch admission proof: passed.
- Complete Agent surface: **41/41 files and 581/581 tests passed**.
- Complete frontend: **160/160 files and 2,183/2,183 tests passed**.
- TypeScript and production build: **547 transformed modules**, passed.
- Repository privacy scan and `git diff --check`: passed.

## Live and process evidence

A fresh temporary in-app tab loaded the rebuilt
`http://127.0.0.1:8765/agent`. The durable fictional project/chat rail was
visible. With the shared runtime truthfully **Stopped**, Add image, Add audio,
Record audio, the composer, and Send stayed disabled. The read-only **Refresh
staged** action completed with `0/4`, no alert, and no dialog. The temporary tab
was closed. No microphone prompt was requested and no model was selected.

After validation there was exactly one loopback-only listener on port 8765,
zero matching model workers, zero matching model GPU workers, and zero Vite,
Vitest, or Playwright test workers.

## Next checkpoint

The next autonomous slice is **Agent-10b: shared runtime switching, placement,
and context-truth lifecycle hardening**. It will audit request ownership and UI
truth across model selection, start/bind/switch/stop, CPU/GPU/GPU+CPU
placement, chat changes, transport replacement, stale observations, and
exact-or-unknown context reporting without starting a real model.

Owner acceptance remains separate: use a probe-verified vision/audio model for
one fictional image and WAV turn plus one local recording, then Stop and unload
with measured process/GPU cleanup. Native file/artifact acceptance also remains
pending.
