# Checkpoint Agent-12g handoff: localhost Windows folder chooser

Date: 2026-09-01

Status: automated implementation complete; owner folder-dialog click pending

Entry contract: [Agent-12g entry](checkpoint-agent-12g-entry.md)

## Outcome

The ordinary localhost Agent page now shows an enabled `Browse…` control for a
new workspace even when no model is running. The control opens one in-process
Windows directory dialog through a dedicated local-UI endpoint. Selecting a
folder only fills the draft workspace field; session creation and authoritative
workspace admission remain separate.

The endpoint requires a valid browser cookie, exact same-origin request and
CSRF proof. API-token and bearer callers cannot trigger the dialog. It is not
part of the Agent-controller orchestration surface and grants no protected
action authority. Dialogs are serialized, errors are content-free, and no
subprocess or terminal is used.

The owned desktop bridge remains first choice. Its unavailable response or
bridge failure falls back to the localhost chooser. Cancel preserves the path,
and busy/unavailable states remain explicit with validated manual entry as the
last fallback.

## Automated evidence

- The picker unit and assembled HTTP security suite passed **4 tests**.
- The complete strict HTTP transport file passed **201 tests**.
- The complete Agent page file passed **165 tests**, including selection,
  cancel, busy, no-auto-create and native-to-browser fallback.
- The broader API, orchestration, OpenAPI and desktop-overlay batch passed
  **73 tests**; the final exact OpenAPI/picker rerun passed **10 tests**.
- Generated API drift, TypeScript production build, Python compilation,
  repository privacy scan and whitespace checks passed.

All fixtures use reserved example paths. No provider history, prompt, response,
tool payload, workspace content or credential was inspected or retained.

## Live reload evidence

- The old exact loopback listener was stopped once and one hidden replacement
  process tree was started once.
- Exactly one listener is bound to `127.0.0.1:8765`; health is `ok`.
- The service has zero visible Python windows and no `llama-server` or
  `llama-cli` process.
- The existing `/agent` tab was reloaded, New session was opened, and one
  enabled `Browse…` button, one no-model option and the no-scan explanation
  were confirmed.
- No dialog was opened, no folder was selected, no session was created and no
  model was started during automation.

## Click now or later

1. Press `Browse…` in the open New session drawer.
2. Choose a harmless local folder and confirm its path fills the field.
3. Press `Browse…` again, cancel, and confirm the existing path remains.
4. Open the chat without a model if desired; choose a model later in the chat
   composer.

## Next checkpoint

Return to **Release-01a.3**: repeated Windows process ownership, Stop, crash,
timeout and listener-collision cleanup with no console storm or orphaned model,
command, MCP or helper descendants.
