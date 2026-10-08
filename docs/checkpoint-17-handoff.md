# Checkpoint 17 handoff

Status date: 2026-08-25

Status: **Agent session-start failure repaired; one owner model turn remains**

## What was wrong

- The localhost page was still rendered after the native Agent process had
  stopped. Its cached catalog could therefore look as if a model was running
  even though no server existed to create the session.
- The default model option displayed the active running model, but session
  creation sent a null model alias instead of pinning that exact runtime.
- A reconnect could retain a session card from the previous server process,
  even though Agent sessions are intentionally memory-only and no longer
  existed after restart.
- The protected desktop composition did not explain clearly enough that its
  window owns the loopback server, models, and in-memory sessions.

## Accepted implementation

- Agent now probes the content-free runtime health endpoint every three seconds.
  A stopped server produces a prominent **Local app disconnected** state,
  invalidates cached model readiness, and blocks both session creation and the
  composer.
- The page retries automatically. On recovery it refreshes models and sessions;
  an authoritative empty session list clears the old conversation instead of
  leaving a ghost composer.
- A network failure during creation or send gets specific recovery copy. An
  unsent draft remains in the composer.
- The default active-model selection now sends the displayed running model's
  exact alias, so readiness validation and the created session refer to the
  same runtime.
- The protected-action note states that closing the native Agent window stops
  its models and memory-only sessions.

## Validation checkpoints

- Real localhost stop/restart: the already-open page detected disconnect,
  blocked stale controls, marked cached model state unusable, then reconnected
  and refreshed without a page reload.
- Complete frontend gate: **1,369/1,369 passed** across **120/120 files**.
- Focused Agent gate: **36/36 passed**.
- Local Agent backend gate: **26/26 passed**; the only warning is the existing
  Starlette TestClient deprecation notice.
- TypeScript production build, Python compilation, repository privacy scan,
  and whitespace checks: **passed**.

## Owner check when convenient

1. Keep the newly opened protected Agent desktop window open.
2. Start the intended local model and wait until it says running.
3. Choose a disposable workspace and click **Start session**.
4. Confirm the conversation card and enabled **Message to the agent** composer
   appear immediately.
5. Send one harmless request and confirm the user turn, activity, and final
   reply appear. If Thinking was enabled, confirm model-provided reasoning is
   visible or the honest no-separate-trace explanation is shown.

## Explicitly not claimed complete

- A real owner-selected model turn was not run automatically; choosing and
  loading a registered model can consume substantial local resources and must
  remain the owner's choice.
- Sessions remain server-memory-only. Closing or restarting the protected Agent
  window intentionally clears them.
- Controlled shutdown still emits the generic
  `runtime_component_shutdown_failed` marker on this machine, even though the
  loopback listener is released. That cleanup defect is a separate next repair.
- Durable conversations, per-turn timing/token telemetry, richer changed-file
  summaries, and broader SOTA coding-agent polish remain later checkpoints.
