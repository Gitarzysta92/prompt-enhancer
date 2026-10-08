# Agent checkpoint 09h — controller onboarding parity

Date: 2026-08-28

## Outcome

The native Agent settings window now teaches the controller lifecycle that the
application actually implements. Before this checkpoint, the MCP v12 and
controller-CLI v5 backends supported finite turn, Stop/wait, exact-revision
live close, retained export, resume, and fork, but the owned setup card still
omitted the CLI `turn` and `close` commands and contained obsolete export copy.
A user following that card could not reproduce the supported flow.

## Native setup changes

- **Direct app connections** now states that there are sixteen core tools and
  presents the complete exact inventory in four compact groups: discovery,
  projects/chats, conversation, and workspace/output.
- The long capability wall is collapsed behind one keyboard-reachable
  **Connected-agent tools · 16 core** disclosure, reducing default density at
  desktop and 320 px.
- The visible lifecycle is now open → turn → stop/wait when needed → live-close.
  It states that close preserves the durable chat/history and permanent delete
  remains native.
- Resume/fork authority, exact path-free export, artifact metadata-only output,
  read-only workspace inspection, inline path-free media staging, and truthful
  context boundaries remain explicit inside the disclosure.
- **Advanced: templates, stdio fallback, and scripts** now includes copyable
  commands for generic `invoke`, finite `turn`, and dedicated `close` in
  addition to config, discover, open, runtime, and wait.
- The CLI explanation now names all six envelope actions and states that runtime
  and live-close mutate at most once while close retains durable history.

## Verification

- Focused connection/controller component slice: **8 passed**.
- Complete Agent component suite, run serially: **255 passed**.
- Responsive Chromium workflow matrix at 1440 px and 360 px, including a 320 px
  resize within the controller case: **67 passed**.
- Production TypeScript/Vite build passed.
- Static stale-copy and whitespace/diff checks passed.
- The repository privacy scanner passed two of three checks and reproduced only
  the previously recorded `docs/checkpoint-agent-02-shell.png` binary finding;
  no scanner rule, exclusion, or safety test was changed.
- A concurrent component-plus-Playwright stress run caused two existing Stop
  tests to exceed their five-second test budget. Both passed immediately in an
  isolated **2/2** rerun, and the complete serial Agent suite then passed
  **255/255**; no timeout was hidden or converted into a product success claim.

### Native reload proof

- Closed the existing Agent workspace through its owned quit confirmation and
  verified the listener, `pythonw`, and `llama-server` process counts all
  returned to zero before relaunch.
- Relaunched the packaged Agent executable without a terminal. The fictional
  project and chat reopened after restart, proving the retained catalog was not
  replaced by a fresh in-memory shell.
- Opened **Agent settings → Connections** and visually verified the collapsed
  sixteen-tool inventory, including `agent_export`, `agent_close`, and
  `agent_stop`.
- Expanded the advanced controller guidance and visually verified the generic
  `invoke`, finite `turn`, and live-`close` command rows plus the retained-chat
  and at-most-once explanation.
- Final state: one Agent window, one loopback-only port 8765 listener owned by
  `pythonw`, zero `llama-server` processes, and zero terminal windows. The
  runtime remains stopped and no model was loaded.

## Privacy and process boundary

The checkpoint changes only static native onboarding UI, layout, and synthetic
tests. It creates no connection credential, reads no credential or provider
configuration, sends no content to a provider, loads no model, touches no GPU,
and starts no terminal or bridge process. Test names, commands, paths, and
identities remain fictional or token-free templates.

## Remaining work

The next evidence audit should target the document/artifact experience itself:
the backend supports inert image and PDF previews, but the current focused UI
suite proves Markdown/text behavior more strongly than image/PDF rendering and
object-URL cleanup. After that code-only proof, real installed-client and
model-backed owner acceptance remains required.

No commit or push was requested.
