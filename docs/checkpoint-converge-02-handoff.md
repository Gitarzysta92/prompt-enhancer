# Converge-02 handoff — genuine local-stack acceptance

Status: automated implementation complete on 2026-09-04

## Outcome

Prompt Enhancer now has a repeatable release gate that serves the current
production-built dashboard from the real FastAPI application and exercises it
through actual authenticated loopback routes. It does not intercept, mock or
replace an application route.

The old browser suite was accurate frontend/HTTP contract evidence but was
misnamed `local-real` despite owning 33 route interceptions. It is now
`intercepted-contract.spec.ts`, with a matching Playwright configuration and npm
command. Historical results remain valuable, but cannot be cited as real-stack
evidence.

## Implemented boundary

The convergence runner:

- builds the production dashboard before the gate;
- creates a temporary app home, SQLite stores, empty provider directory and a
  reserved-example workspace;
- seeds one fictional retained conversation through the production catalog and
  history implementation;
- disables provider adapters/schema process launch and makes local-model
  discovery empty by construction;
- starts one OS-reserved IPv4 loopback listener in-process;
- starts Node/Playwright with Windows `CREATE_NO_WINDOW` and no shell;
- redacts the temporary workspace and origin from child output;
- rejects any off-origin browser request, page/console exception, non-cancelled
  request failure or HTTP 5xx response; and
- always stops workers/services, releases the listener, removes temporary state
  and checks that zero model runtimes remain.

The source guard fails if the zero-interception spec later gains `page.route`,
`context.route`, HAR routing, `setContent` or a synthetic transport.

## Current evidence

- Production frontend build: green.
- Standard browser regression suite: **165/165 passed** with one worker.
- Intercepted frontend/HTTP contract suite: **41/41 passed** after its fixtures
  were reconciled with the current runtime, placement and paginated-catalog
  contracts.
- Harness safety/static tests: **4/4 passed**.
- Focused backend and harness regression group: **86/86 passed**.
- Generated OpenAPI/TypeScript parity and the unchanged repository privacy
  scanner: passed.
- Production-build/real-loopback browser journeys: **16/16 passed** with one
  worker and zero retries.
- Journey coverage: shell/security headers, browser auth, worker liveness,
  updater truth, all-twenty metric operability, stopped empty model registry,
  retained history, project persistence, model-neutral setup, saved no-model
  chat, real workspace read with refused/unapplied mutation, composer
  model/context state, durable rename/pin, archive/restore, artifact truth, MCP
  project state, project deletion and authenticated deep links.
- Network/browser diagnostics: zero off-origin requests, page errors, console
  errors, non-cancelled request failures and HTTP 5xx responses.
- Shutdown receipt: listener released; runtime cleanup confirmed; temporary state
  removed; server thread clean; **0 model runtimes remaining**.
- Tracked-diff whitespace validation: passed; only Git's existing Windows
  LF-to-CRLF notices were emitted.

The contract rerun also caught and repaired stale fixture expectations for the
compact composer disclosure, prompt-review naming, semantic diff counters and
catalog pagination. Turn details remain operable by keyboard when nested scroll
and sticky transcript surfaces make pointer auto-scrolling ambiguous; the
transcript now reserves scroll margins above and below interactive turn rows.

Run the complete gate from the repository root with:

```powershell
.venv\Scripts\python.exe tests\support\convergence_loopback_runner.py
```

The direct Playwright command is intentionally separate and requires the runner's
ephemeral origin/workspace environment. The convenience npm command invokes the
coordinator rather than silently starting a fixture server.

## What this does not claim

This is loopback-integration evidence over fictional data. It does not prove a
packaged native folder dialog, native approvals, real GGUF inference, GPU/VRAM
release, a trusted third-party MCP package, an external controller, or signed
installer apply/relaunch/rollback. Those remain in Converge-04, 05 and 07.

The owner's existing application was not reloaded for this checkpoint because
it may contain an unobservable unsent draft. The gate used and removed its own
listener and state without touching that process.

## Owner click-later note

No manual action is needed for Converge-02. During the Converge-03 visual
checkpoint, verify the redesigned Agent at desktop and narrow widths; the
existing 16-journey loopback gate must remain green before that review.

## Next checkpoint

Converge-03: make the conversation and compact composer own the Agent viewport,
consolidate secondary status/tools into coherent drawers, remove competing
scroll regions, replace remaining ad-hoc file icons and split the oversized
Agent modules along user-visible boundaries.
