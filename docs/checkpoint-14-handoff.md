# Checkpoint 14 handoff

Status date: 2026-08-25

Status: **Agent workspace entry and native-approval composition repaired; owner
native-window visual approval remains pending**

## What was wrong

- The browser showed an example folder only as placeholder text. It had no
  folder chooser, so clicking the field did not select a workspace and the
  empty form correctly kept Start disabled.
- The three protected-action checkboxes were intentionally fail-closed in an
  ordinary browser, but the page did not give the owner a usable native Agent
  path. The existing desktop host opened only the metrics overlay.
- A first implementation review found and repaired a local port-ownership
  race. A second integration review caught the launch-readiness route behind
  the SPA fallback; the route now participates in normal app assembly and is
  tested against the real assembled FastAPI app.

## Accepted implementation

- The browser form remains usable for explicitly typed or pasted absolute
  paths and clearly labels the resulting session as read-only.
- Browse and protected scopes explain why they are unavailable in a browser
  and point to `prompt-enhancer agent-desktop`.
- `prompt-enhancer-agent` and `prompt-enhancer agent-desktop` open a dedicated
  owned Windows Agent window. The launcher refuses an occupied port instead of
  attaching its native approval bridge to a different server process.
- The owned server and native window share one in-process, one-shot
  user-presence manager. Startup succeeds only after persistent application
  identity and exact per-launch instance readiness both verify.
- The native Browse bridge is limited to the expected loopback origin and
  exact `/agent` route. It returns one explicitly selected absolute Windows
  path or a content-free cancelled/unavailable result; the backend remains the
  authoritative workspace validator.
- Protected scopes begin unchecked. Selecting a scope authorizes only the
  corresponding session capability, and every actual write, command, or web
  fetch still requires a separate native confirmation.

## Validation checkpoints

- Focused desktop/Agent backend gate: **65/65 passed**.
- Windows distribution, desktop identity, and user-presence gate:
  **112/112 passed**.
- Final assembled-app Agent/SPA/identity/user-presence gate:
  **154/154 passed**.
- Complete frontend unit gate: **1,340/1,340** across **119/119 files**.
- Native bridge/Agent/transport focus: **124/124 passed**.
- TypeScript/production build, generated API drift check, frozen dependency
  check, Python compilation, privacy scan, and whitespace checks: **passed**.
- The locked pywebview runtime exposes the folder-dialog enum and the
  single-selection parameter used by the launcher.
- Targeted localhost verification exercised the New session controls with a
  fictional absolute path and did not open a session or invoke an action: Start
  enabled without submission, Browse and all protected scopes remained
  effectively disabled, scopes remained unchecked, and clearing the field
  disabled Start again.
- Independent final review verdict: **ship; no remaining correctness blocker**.

## Owner check when convenient

1. Reload the current browser `/agent` page. Entering or pasting a real
   absolute folder should enable **Start read-only session**; Browse and the
   three protected scopes should stay unavailable by design.
2. Stop the running `prompt-enhancer serve` process so port 8765 is free.
3. From the environment installed with the desktop extra, run
   `prompt-enhancer agent-desktop` (or `prompt-enhancer-agent`).
4. In the native window, confirm that Browse opens the Windows folder chooser,
   the chosen path fills the field, and all protected scopes start unchecked
   but are selectable.
5. Start a disposable session. If desired, request one harmless protected
   action and confirm that the separate native approval dialog appears. Do not
   approve a write or command whose effect you have not reviewed.

The ordinary browser remaining read-only is a safety boundary, not an
unfinished checkbox bug. The only pending item in this checkpoint is the
owner's real native-window visual/interaction approval.
