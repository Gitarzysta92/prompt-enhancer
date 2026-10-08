# Checkpoint 33: atomic native launch and shutdown evidence

Status: scoped implementation and Windows verification complete. The whole
application remains open against the verification ledger. The single existing
privacy-artifact finding remains open.

## What changed

- Native-owned services receive an exact-loopback socket that is bound before
  application startup and is not inheritable. Uvicorn consumes this socket;
  there is no longer a free-port check followed by a separate server bind.
- Protected Agent still never attaches native approval authority to another
  process. If the configured port is occupied, it reserves an OS-assigned
  loopback port, builds the HTTP/native composition against that exact origin and
  leaves the configured listener untouched. The metrics overlay retains its
  authenticated attach behavior and does not use fallback when configured-port
  ownership is required.
- Listener ownership is carried into shutdown and the pre-bound handle is closed
  even on startup/force-exit paths. Existing component cleanup and bounded join
  authority remain required before shutdown succeeds.
- Agent and overlay GUI/terminal entry points write separate private
  `native-lifecycle.v1` latest-state records below the application diagnostics
  directory. The only fields are contract, window kind, fixed phase,
  terminal flag, fixed reason/component codes and previous fixed outcome/phase.
  There are no timestamps, PIDs, ports, paths, prompts, sessions, providers,
  models or exception strings.
- Marker updates use same-directory atomic replacement and sync. Failed replace
  preserves the last valid record and removes the private temporary stage. An
  invalid/oversized prior file becomes `previous: unknown` and is never copied.
- A clean close now requires the native window's `closed` event. Returning from
  the WebView loop without that receipt is `window_close_unconfirmed`, triggers
  owned cleanup and exits unsuccessfully. A hard process exit leaves the last
  non-terminal phase; the next launch carries only `interrupted` plus that fixed
  phase. A marker failure cannot replace an earlier primary failure.

## Verification receipts

- Pre-fix reproductions: occupied configured port raised `port_in_use` instead
  of creating an independently owned Agent listener; a successful Agent close
  created no lifecycle file. Both regressions now pass.
- Focused lifecycle/privacy/distribution selection: **191 passed / 7 files** in
  **33.17 s**, with the existing Starlette/httpx deprecation warning.
- Two real Windows native-engine probes passed. Agent and overlay each created a
  hidden WebView, loaded the current document, emitted the close event, stopped
  their listener, removed disposable state and returned zero.
- Two generated GUI executable probes passed through the installed
  `prompt-enhancer-agent.exe` and `prompt-enhancer-desktop.exe` entry points.
  The Agent's configured port was deliberately occupied; it loaded on its owned
  fallback, closed, published `stopped`, left the occupied listener alone and
  returned zero. Entry-point metadata matched the registered functions.
- Frozen-state backend coverage ran all `tests/test_*.py` files in four
  non-overlapping, cache-free shards: **4,204 passed, 9 expected Windows symlink
  skips and 1 failed**. Shard receipts were 729 passed in 457.79 s; 1,168 passed
  / 6 skipped in 549.19 s; 1,287 passed / 2 skipped in 796.74 s; and 1,020 passed
  / 1 skipped / 1 failed in 486.21 s. The sole failure is the unchanged privacy
  assertion for the old synthetic SQLite artifact below; it is not a functional
  regression and is not counted as a pass.
- The frozen frontend suite passed **1,760 tests across 129 files**. Browser
  acceptance passed **105 synthetic workflows** and **30 loopback-backed HTTP
  workflows** in separate port-safe runs.
- Production frontend build, generated API consistency, Python compilation,
  `uv lock --check --offline`, `git diff --check` and targeted trailing-whitespace
  checks passed. No frontend/API contract changed in this checkpoint.
- The unmodified privacy scanner reports exactly one finding:
  `test-results/browser-workflow-e3rix2kz/application/shared-folders.sqlite3`.
  It remains an explicit open repository artifact; no rule, exclusion or test was
  weakened and the file was not removed.
- Cleanup checks found zero `llama-server` processes, zero Agent/overlay native
  launcher processes and no listeners on the owned test ports 4175 or 8765. The
  pre-existing frontend development listener on loopback port 4173 was preserved.

## Explicit limits and next work

- The marker distinguishes confirmed clean shutdown, a fixed failure and an
  interrupted prior phase. It intentionally is not a crash dump and cannot
  explain the operating-system cause of the historical unexplained exit.
- Fallback is private to the native Agent window; an ordinary browser already on
  the configured port remains connected to that existing service and does not
  gain protected actions.
- Actual native folder selection and protected-action approval still require the
  owner's presence. Hidden auto-closing probes do not certify those clicks or
  owner window-size/style preferences.
- The generated environment launcher was exercised. A signed installer/MSIX,
  upgrade/uninstall flow and another Windows installation are separate release
  acceptance tasks.
- No real provider data, credentials or owner configuration were used. No model
  or GPU runtime was loaded. The normal owner app was not restarted.
