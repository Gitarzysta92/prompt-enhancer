# Checkpoint Agent-12d handoff: integrated capability-aware composer

Date: 2026-09-01

Status: automated implementation complete; owner visual and real-runtime review pending

Entry contract: [Agent-12d entry](checkpoint-agent-12d-entry.md)

## Outcome

The active Agent chat now owns one unified composer. The message field, compact
attachment and microphone controls, truthful selected/served model state, exact
or unknown chat-context status, prompt improvement, and one Send/Stop action are
in the same interaction area. The left rail remains project/chat navigation and
Agent settings; it no longer owns a second runtime card.

This checkpoint reused the existing runtime coordinator, context evidence,
media admission, draft, attachment, send, Stop and session-rebinding state
machines. It did not create a parallel model lifecycle or infer context use.

## Changed

- The shared model/runtime control has an in-flow composer disclosure with the
  selected model, actual coordinator state and exact context percentage when a
  bound turn provides evidence.
- Expanding the disclosure exposes model, placement, context limit, admission
  evidence, capabilities, Start/Switch/Bind, Stop runtime and Refresh.
- A changed but unapplied model/placement/context selection says `Pending
  change`; a switched runtime awaiting chat rebinding says `Chat binding
  pending` instead of claiming readiness.
- Document/image/WAV selection stays behind one paperclip control. Microphone
  recording is a direct capability-gated control. A runtime capability refresh
  no longer dismisses an already-open source menu, but it still cancels stale
  capture or mutations and re-gates every choice.
- Send and Stop response are one circular primary action; prompt checking stays
  secondary. Enter remains newline and Ctrl/Command+Enter remains Send.
- New icons follow the shared icon system. Icon-only controls have exact
  accessible names, 44 px targets, focus treatment, and visible text fallbacks
  in Windows forced-colors mode.
- Desktop and 360 px layouts keep expanded settings in document flow rather
  than overlaying the conversation.

## Automated evidence

- Agent composer checkpoint: **4 files / 221 tests passed** after the
  capability-refresh race repair.
- Full frontend gate: **184 files / 2,726 tests passed** after the final
  forced-colors and pending-selection tightening.
- Relevant backend/browser/security/privacy gate: **74 passed**.
- Generated OpenAPI client check passed.
- Repository privacy scanner passed.
- Python compilation for `src` and `tests` passed.
- Production frontend build passed. The pre-existing large Agent chunk warning
  remains visible and is not reclassified as a checkpoint failure.
- `git diff --check` passed.

All tests and browser checks used only synthetic fixtures or content-free
structural evidence. No provider transcript, real prompt, response, tool
payload, credential or private workspace content was read.

## Live reload evidence

- Health: `ok`; cost mode: `offline_only`; data tier: `metadata`.
- Listener census: exactly **1**, bound to `127.0.0.1:8765`.
- Model-process census: **0** `llama-server` processes; no model was loaded and
  no GPU/VRAM acceptance claim is made.
- `/agent` reloaded to `Agent · Prompt Enhancer`, with one main landmark, one
  Agent shell and no rendered alert.
- The loaded browser state did not contain an active live chat, so the composer
  was not mounted. I did not create a chat or start a model merely to force the
  UI. Interactive visual acceptance therefore remains an explicit owner check.

## Still pending

- Subjective visual acceptance of the integrated composer in one real open
  chat.
- Native microphone permission behavior and a real supported multimodal model.
- Real CPU/GPU/split switching, unloading and accelerator-memory release. Those
  remain Runtime-01 / Acceptance-01 evidence, not synthetic Agent-12d claims.
- The large Agent bundle still needs a later performance/code-splitting slice.

## Click later

1. Open or resume a safe Agent chat and confirm the left rail contains projects,
   chats and Agent settings—not a separate model-runtime card.
2. At the bottom composer, expand the model/context pill and confirm model,
   placement, context limit, evidence and lifecycle actions stay in flow.
3. Type an unsent draft, choose a different model and confirm `Pending change`
   appears while the draft remains. Apply only when you want a real model run.
4. Check paperclip, microphone, Improve and Send/Stop at desktop and a narrow
   window; unsupported media controls must remain disabled with an explanation.

## Next checkpoint

Return to **Release-01a.3**: prove combined Windows process ownership and cleanup
under repeated app start, Stop, crash, timeout and listener collision, with no
visible terminal storm and no orphaned model, command, MCP or helper descendant.
The newly requested signed in-app update channel follows as Release-01b.1 and
Release-01b.2, because safe replacement/relaunch depends on that process gate.
