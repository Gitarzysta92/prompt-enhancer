# Checkpoint Store-07c entry

Status: implementation active
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Previous evidence: [Store-07b handoff](checkpoint-mcp-store-07b-handoff.md)

## Frozen user outcome

Starting, stopping, crashing or restarting a local MCP server must never create
a terminal-window storm, escape the owned process tree, hang the application or
leave an orphan worker. Every lifecycle transition settles once with truthful,
content-free status; cleanup uncertainty remains visible and blocks reuse.

## Evidence at entry

- Store-07b closes remote transport authority on timeout, cancellation and
  unsafe outcomes and prevents late data from reviving a stopped host.
- Existing runtime work already establishes minimized environments, Windows
  descendant ownership and hidden-process launch patterns for local models.
- A previous reload briefly exposed an unexpected console-host descendant. The
  latest bounded census observed one persistent hidden console-host child but no
  visible window, model/MCP worker, non-loopback connection or GPU workload.
- These observations are not accepted as harmless. Store-07c must attribute the
  process, reproduce or disprove the launch path and prove deterministic cleanup
  without terminating unrelated user processes.

## In scope

1. Inventory every local MCP process-launch path and require one shared hidden,
   non-shell Windows launch contract with a minimized, reviewed environment.
2. Establish exact owned-root and descendant identity before activation; reject
   ambiguous, detached or reparented workers and never sweep unrelated processes.
3. Bound spawn, initialize, stderr/stdout drain, health, tool enumeration, idle,
   call, Stop and shutdown phases with monotonic lifecycle states.
4. Drain bounded output without blocking the child; reject floods and binary or
   malformed control traffic without persisting raw process content.
5. Make simultaneous Stop, timeout, crash, app reload and late-exit callbacks
   idempotent. A stopped or uncertain host cannot return to ready.
6. Terminate the exact owned Windows process tree on failure or confirmed Stop,
   then verify exit. Surface `cleanup_required` when objective exit cannot be
   proven.
7. Reconcile interrupted startup and prior-run state on service restart without
   auto-starting a server or inheriting stale authority.
8. Prove the launcher does not open visible console windows and explain or remove
   the persistent hidden console-host child associated with the service launch.
9. Keep lifecycle diagnostics content-free: no command line, environment value,
   private path, server output, tool payload or transcript enters UI, logs or
   durable receipts.

## Explicit exclusions

- Remote proxy, DNS, TLS, HTTP and SSE policy is closed in Store-07b.
- Recursive tool schemas, malformed arguments/results, output floods after the
  MCP tool boundary and approval replay belong to Store-07d.
- Vault values, secret canaries and project/chat/client isolation belong to
  Store-07e.
- No real third-party MCP package, credential, model or protected activation is
  authorized for the automated gate. Process fixtures must be synthetic and
  inert.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Normal synthetic start/Stop | One hidden owned tree starts, becomes ready once, exits and is objectively absent. |
| Startup crash or malformed handshake | Bounded content-free failure; no ready state and no descendant remains. |
| stdout/stderr flood | Bounded drain and refusal without deadlock, unbounded memory or raw-output retention. |
| Detached/reparented child | Activation fails closed; only objectively owned processes are targeted. |
| Start/Stop/timeout race | Exactly one terminal state; late callbacks cannot revive the host. |
| Slow or resistant shutdown | Bounded return as `cleanup_required`; host cannot be reused. |
| Service restart | Interrupted state reconciles without auto-start or stale project/tool authority. |
| Windows visibility | No visible console or terminal window appears during a repeated bounded launch monitor. |
| Final census | One loopback app listener and zero owned MCP/test/orphan workers; unrelated processes untouched. |

## Expected touched surfaces

- local managed-host launch, process ownership, output drain and shutdown
  adapters;
- app/service reload reconciliation and content-free lifecycle receipts;
- safe reason-code and Agent recovery contracts where required;
- synthetic crash, flood, tree, race, restart and Windows-window fixtures;
- Store-07c handoff and the master milestone board.
