# Checkpoint Agent-12e handoff: model-neutral chat entry

Date: 2026-09-01

Status: automated implementation complete; owner browser/native click review pending

Entry contract: [Agent-12e entry](checkpoint-agent-12e-entry.md)

## Outcome

New chat no longer requires, inherits, starts, or pins a local model. The default
setup choice is `Choose later in chat · no model`; after the workspace chat
opens, the existing integrated Model & context control beside the message box is
where the person explicitly chooses, places, starts and binds a model.

Workspace selection and model selection are independent. A model-neutral chat
can open while the optional model catalogue is still loading or while another
shared model is already running. Send remains unavailable until that exact chat
has an explicitly bound, ready model.

## Folder behavior

- In an ordinary loopback browser, the absolute-path field is enabled and the
  adjacent truthful affordance says `Paste path`. Browsers cannot return a full
  Windows folder path through a normal web file chooser.
- In the protected console-free Agent desktop window, the exact-origin native
  bridge replaces `Paste path` with `Browse…` and returns only the selected
  folder path.
- The absence of `Browse…` in an ordinary browser is unrelated to whether a
  model is installed or running.

No HTTP or browser workaround was added around the native boundary.

## Changed

- New-session model state is separate from active-chat runtime state.
- The blank optional model choice serializes as `model_alias: null`, including
  when another model is already running.
- Opening New chat resets the optional setup model instead of leaking the
  active chat's selection.
- Optional catalogue loading/readiness only gates an explicitly selected setup
  model; it cannot block model-neutral creation.
- A model-neutral active chat does not silently bind the global running model.
- New-session button and empty-state copy describe the actual no-model flow.
- Browser and native folder affordances are now visibly distinct.

## Automated evidence

- The complete Agent page gate passed: **1 file / 163 tests**.
- The previously load-sensitive retained-history journey passed in isolation
  and in the complete Agent page gate with a bounded test-only timeout.
- Focused adjacent Agent/runtime/layout/native tests passed: **4 files / 66
  tests**.
- Relevant backend/native/privacy tests passed: **113 tests**.
- The complete frontend gate passed: **184 files / 2,729 tests**. Two unrelated
  asynchronous catalog assertions were tightened to await their exact settled
  states after they proved green in isolation.
- Production frontend build, generated API check, Python compilation, privacy
  scan and `git diff --check` passed.

All fixtures and browser checks were synthetic or content-free. No provider
transcript, real prompt, response, tool payload, credential or private workspace
content was read.

## Live reload evidence

- `/agent` was rebuilt and reloaded in the loopback browser.
- Health returned HTTP **200** with exactly **1** listener bound to
  `127.0.0.1:8765`.
- With no setup model selected, `Choose later in chat · no model` was displayed,
  the workspace input was enabled, `Paste path` was visible, no fake disabled
  Browse button was rendered, and the open action became enabled after a
  synthetic absolute path was entered.
- An existing model-neutral chat rendered the integrated Shared local model
  runtime control in the composer with `Choose a model` and Model & context
  settings.
- No session was created and no model action was performed during the live DOM
  check.
- Model-process census remained **0**; no GPU/VRAM was consumed.

## Click later

1. In this browser, open New chat, paste an existing absolute folder path, leave
   `Choose later in chat · no model`, and choose `Open read-only chat without
   model`.
2. In the open chat, expand Model & context beside the message box and explicitly
   choose/start/bind the desired model.
3. In the console-free Agent desktop window, repeat step 1 with `Browse…` and
   confirm cancel and selection both behave normally.
4. Confirm a second New chat again defaults to no model after using a model in
   the first chat.

## Next checkpoint

Return to **Release-01a.3**: prove combined Windows process ownership and cleanup
under repeated start, Stop, crash, timeout and listener collision, with no
visible terminal storm and no orphaned model, command, MCP or helper descendant.
