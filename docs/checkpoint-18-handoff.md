# Checkpoint 18 handoff

Status date: 2026-08-25

Status: **Agent model-to-chat startup repaired and locally validated**

## What was wrong

- Starting a local model and creating an Agent chat were two separate actions,
  but the page did not make that boundary clear. A running model could therefore
  look like a failed session because no composer exists until a session is
  created.
- After a successful session creation, the page immediately refreshed the
  session list before selecting the returned session. A temporarily failed or
  stale empty list could clear the valid session and make the composer vanish.
- A session-list request failure was rendered as **No session yet**, which hid
  the difference between an empty list and an unavailable list.
- When no workspace was selected, the disabled action did not identify the
  missing prerequisite clearly enough.

## Accepted implementation

- The primary Agent action now completes the whole transition. If necessary it
  starts the selected model, then creates the session, selects the returned
  chat, scrolls to the composer, and focuses the message box.
- The button labels expose the actual next step: choose a workspace, choose a
  model, wait for a starting model, start model and open chat, or open chat.
- The session returned by the create request is treated as authoritative and
  merged into the visible list immediately. It is no longer dependent on a
  second list request succeeding.
- Session-list failures now have a distinct error and **Retry sessions** action;
  they are never represented as an authoritative empty list.
- The empty conversation explains exactly which prerequisite remains and where
  the message box will appear.

## Validation checkpoints

- Independent read-only audit confirmed the explicit legacy flow worked and
  identified the successful-create/session-list race. The validator made no
  edits.
- Rebuilt localhost flow from a stopped runtime: one primary click started the
  runtime, created and selected a new session, and exposed an enabled composer.
- One synthetic local-only message completed with one user turn, one assistant
  turn, and zero UI errors.
- Focused Agent gate: **38/38 passed**.
- Complete frontend gate: **1,371/1,371 passed** across **120/120 files**.
- Local model and Agent backend gate: **48/48 passed**; the only warning is the
  existing Starlette TestClient deprecation notice.
- TypeScript production build, Python compilation, repository privacy scan,
  and whitespace checks: **passed**.

## Owner check when convenient

1. Keep the protected Agent desktop window open; it owns the loopback server,
   running models, and memory-only sessions.
2. Choose a workspace folder and a registered model.
3. Click **Start model & open chat** (or its **read-only** browser variant) when
   the model is stopped, or **Open chat session** when it is already running.
4. Confirm a session card appears and **Message to the agent** is focused and
   enabled without another startup action.
5. Send one harmless request and confirm the user turn, activity, and final
   reply appear.

## Explicitly not claimed complete

- Sessions remain server-memory-only. Closing or restarting the protected
  Agent window intentionally clears them.
- Model runtimes remain separate from sessions and can be reused or stopped;
  the Agent page now orchestrates both only for its explicit open-chat action.
- Controlled shutdown still emits the existing generic
  `runtime_component_shutdown_failed` marker on this machine even when the
  listener releases. That cleanup defect remains a later checkpoint.
- Durable conversations, per-turn timing/token telemetry, richer changed-file
  summaries, and broader coding-agent polish remain later checkpoints.
