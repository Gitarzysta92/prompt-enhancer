# Checkpoint 15 handoff

Status date: 2026-08-25

Status: **Agent composer and model-readiness flow repaired; owner visual and
real-model response check remains**

## What was wrong

- The tall setup and workspace panels stretched the conversation grid. The
  transcript absorbed that height and pushed the unlabeled composer below the
  visible native window.
- The model picker showed registered models without showing that most were
  stopped. An explicit stopped alias could create a normal-looking session and
  fail only when the first message was sent.
- Every session-create conflict was presented as session capacity, which hid
  model-readiness failures. Message conflicts similarly merged stopped-model,
  no-model, and already-running-turn states.
- Narrow and own-window layouts placed secondary workspace content before the
  conversation, so restoring a session could again put the composer below the
  fold.

## Accepted implementation

- The conversation is viewport-bounded; the transcript owns scrolling and the
  visible **Message to the agent** composer remains in the card. A newly
  created session scrolls to and focuses it.
- Every installed-model option includes `running`, `stopped`, `starting`, or
  `failed`. A stopped selection exposes **Start selected model**, while session
  creation remains disabled with **Start model first**.
- Existing sessions show their model state beside the conversation. The
  composer stays disabled until that exact model is running and exposes
  **Start session model** or **Open Models** as the applicable recovery.
- Starting models use bounded status polling, manual refresh remains
  available, window focus refreshes status changed elsewhere, and asynchronous
  runtime failures also trigger a refresh.
- The service verifies an explicit model alias both when a session is created
  and immediately before every turn. A runtime exit after that preflight emits
  safe, actionable text without exception or local-path leakage.
- Safe HTTP reason codes now distinguish model-not-ready, no-active-model,
  capacity, and turn-in-progress failures. Creation feedback stays beside the
  New session form; turn feedback stays associated with the composer.
- Own-window mode is chat-only. When the normal page stacks, the conversation
  precedes the workspace and setup panels. Model readiness and turn errors are
  programmatically associated with the composer.

## Validation checkpoints

- Complete frontend unit gate: **1,360/1,360 passed** across **120/120 files**.
- Final Agent/layout/transport focus: **134/134 passed**.
- Local Agent backend focus: **26/26 passed**; the only warning is the existing
  Starlette TestClient deprecation notice.
- TypeScript production build, Python compilation, privacy scan, and whitespace
  checks: **passed**.
- Independent backend and UX re-reviews found no remaining P1/P2 issue after
  the final feedback-scope repair.
- Live loopback validation returned HTTP 200, loaded the rebuilt Agent with no
  browser-console errors, verified that every installed option has an explicit
  runtime state, and confirmed the stopped-model recovery action and disabled
  session gate.

## Owner check when convenient

The native Agent is already running on loopback for this check.

1. In **Model**, choose the model you intend to use. If it says `stopped`,
   click **Start selected model** and wait for `running · ready`.
2. Choose a disposable workspace folder and click **Start session**.
3. Confirm that **Message to the agent** is visible in the conversation card
   and focused. Send one harmless read-only request.
4. Confirm that a completed or failed reply is visible and that a runtime
   failure leaves a clear Start-model recovery action.
5. Optionally open the session in its own window and confirm that the popup is
   chat-only and the composer remains visible.

No local model was started automatically during validation because model size,
device placement, and compute use are owner choices. The remaining check is the
owner's real-model response and visual approval, not an untested readiness or
layout contract.
