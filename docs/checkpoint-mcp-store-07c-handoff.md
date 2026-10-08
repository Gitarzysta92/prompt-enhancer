# MCP Store checkpoint 07c handoff

Date: 2026-08-31
Status: automated implementation complete; packaged/native owner review pending
Runtime effect of the automated gate: synthetic local stdio peers, finite
sleeping descendants, mocked window-policy failures and read-only inspection of
the already-running loopback application. No real MCP package, model, protected
action, credential, workspace content or GPU workload was started.

## Outcome

A local MCP process now enters one hidden, atomically owned Windows Job before
it can execute. Startup, protocol failure, output flood, timeout, Stop, shutdown
and concurrent start/Stop paths settle within finite budgets. A late task cannot
restore Ready after authority is removed, and unverified cleanup remains a
durable block instead of being reported as success.

## Changed

- The shared Windows launcher resolves the reviewed executable to an explicit
  image path, uses `CREATE_NO_WINDOW` plus `SW_HIDE`, inherits only the intended
  stdio handles and admits the root to its Job atomically at creation.
- Every local MCP Job has kill-on-close ownership and a finite 16-process active
  limit. Breakaway and silent-breakaway permissions are absent. The launcher can
  inventory exact Job process IDs and inspect only those PIDs for visible
  top-level windows.
- MCP stdout is framed through a bounded queue. Oversized or malformed JSON-RPC
  terminates the exact tree immediately with a stable content-free reason.
  Stderr is drained without retention and a two-MiB flood terminates the tree.
- A Windows visibility monitor fails closed if an owned process opens a visible
  window or if visibility cannot be confirmed. Neither window titles nor process
  command lines enter diagnostics.
- Managed-host startup now owns and exposes its in-flight task. Stop cancels and
  joins startup before closure, and post-connect or post-discovery late results
  cannot publish Ready after the actor is tombstoned.
- Stop, unsafe calls and service shutdown share a finite cleanup budget. Missing
  local cleanup evidence is never replaced with invented success; persistent
  cleanup uncertainty blocks restart and removes the host from model tool
  routing.
- HTTP and Agent UI contracts recognize only allowlisted lifecycle reasons for
  output limits, visible-window policy, visibility uncertainty, cancellation,
  timeout and cleanup uncertainty. Raw process or transport errors are not
  rendered.
- Synthetic fixtures can create a bounded descendant tree and output flood.
  Tests prove the real Windows active-process limit, exact descendant reaping,
  no breakaway flags and no tool execution during compatibility probing.

## Regression repaired during the gate

The first explicit-image implementation correctly removed executable ambiguity
but passed a bare program name to `CreateProcessW`. That API path did not match
the earlier PATH lookup and broke ordinary reviewed commands. The launcher now
resolves the executable to an absolute image path before creation. The complete
command, cancellation, local-model and release-hardening regression returned to
green without weakening atomic Job admission.

## Automated evidence

- Final combined MCP, Agent-MCP, Windows process, command, local-model and
  release-hardening matrix: **464 passed**.
- Core guarded-host, managed-runtime, server-management and Windows launcher
  matrix after executable resolution: **182 passed**.
- Direct command/process-control/local-model/release regression: **82 passed**.
- Windows desktop lifecycle, single-instance and distribution regression:
  **102 passed**.
- Agent and shared HTTP/MCP frontend regression: **734 passed / 33 files**.
- Focused recovery-contract frontend matrix: **36 passed**.
- TypeScript project build, production Vite build, generated API check, Python
  compile check and repository privacy scan passed.

The matrix covers startup failure, malformed and oversized control traffic,
stderr flood with a live descendant, hidden launch, simulated visible-window
and visibility-inventory failures, a requested 32-child storm constrained by
the 16-process Job budget, exact tree reaping, Stop during tool discovery,
cancellation, late completion, resistant cleanup and restart reconciliation.
Fixtures contain only reserved fictional data.

## Live process and network evidence

- Exactly **1** listener remained on loopback port 8765.
- The stable service tree contained **3** processes: the existing console-mode
  development launcher and worker plus one hidden Windows console host.
- Maximum visible top-level windows across 20 samples / 10 seconds: **0**.
- Prompt Enhancer-owned established non-loopback connections: **0**.
- Prompt Enhancer-owned GPU compute contexts: **0**.
- `/health` and the Agent HTML fallback both returned HTTP 200.

The retained hidden console host belongs to the already-running console CLI
development launch, not to an MCP or model worker. It produced no visible
terminal. The installed desktop and Agent entry points are declared as Windows
GUI scripts and their lifecycle/distribution tests are green; the physical
installed-package repetition remains an honest Release-01b owner gate.

## Still bounded

- Recursive schemas, alias collisions, malformed tool arguments/results,
  post-tool output floods and approval replay belong to Store-07d.
- Secret/log canaries, stale vault values and project/chat/client isolation
  belong to Store-07e.
- Automation did not activate an owner-installed MCP server or manufacture a
  native approval. Those protected clicks remain in Acceptance-01.

## Owner click-later ledger

1. From the installed Agent shortcut, repeat start, reload and close while
   confirming that no terminal window appears.
2. With one explicitly trusted inert local MCP plan, review and approve Start;
   confirm one Ready transition and that chat remains responsive.
3. Stop it once and confirm the plan reaches Not started without a delayed Ready
   card or a second terminal/process.
4. Close and reopen the installed app and confirm the stopped server does not
   auto-start. If cleanup cannot be confirmed, verify restart stays blocked with
   safe recovery copy.

## Next checkpoint

Store-07d is active next: make tool discovery, schema/alias handling, argument
validation, result projection and per-call approval replay fail closed under
bounded synthetic hostility.
