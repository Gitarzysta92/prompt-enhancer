# MCP Store checkpoint 06b readiness

Date: 2026-08-30
Status: architecture and inert contract preparation complete; explicit owner approval required before persistent-host implementation
Runtime effect of this checkpoint: none; no MCP server, model, tool call, listener, or terminal was started

## Outcome

Store-06b is now specified as one bounded authority increase: the owner may
start and stop an already-installed, already-reviewed, project-admitted MCP
server for the current Prompt Enhancer app run. The host may negotiate MCP,
enumerate tool contracts, and perform health/drift checks. It may not expose a
tool to a model and it may not invoke `tools/call`.

This checkpoint requires a fresh owner decision because it changes the runtime
from short compatibility probes that always close to a persistent third-party
process or network connection. Approval of Store-06a did not grant that
authority.

## Approval-safe preparation update

The first behavior-preserving implementation seam is complete without adding
persistent-host authority:

- exact tool-contract normalization is now the public
  `review_mcp_tool_contracts` application boundary used by the existing probe;
- guarded remote/stdio target construction, SDK handshake, session ownership,
  and cleanup now live in one inert `OfficialSdkMcpConnectionFactory` context;
- `OfficialSdkMcpProbeClient` composes through that factory, so the probe and a
  future supervisor cannot drift into different network/process policies;
- `McpbPackageInstaller.resolve_installed_connection` now re-derives launch
  material read-only from an existing exact tree and refuses tree, manifest
  evidence, or runtime drift without probing or starting the package;
- `McpManagedServerService.resolve_transient_host_connection` now requires an
  installed current revision and current reviewed snapshot, re-resolves the
  exact remote Registry plan or local package evidence, reads vault values only
  just in time, rechecks the durable revision after resolution, and returns no
  durable/public connection material;
- strict `McpManagedHostBinding`, start/Stop command, status, digest, and state
  transition contracts now bind exact server, project-admission, plan, and tool
  snapshot revisions while keeping tool calls and routing literal-locked off;
- `McpManagedServerService.resolve_host_binding` now joins those exact durable
  records read-only, rejects uninstalled/disabled/cross-project/stale/raced
  authority, and neither reads vault values nor derives connection material;
- the exact start preview is now a deterministic, content-free contract: local
  previews disclose current-user OS authority and hidden owned process-tree
  execution, remote previews disclose a reviewed remote connection, and both
  state that previewing starts nothing, confirmation is required, persistence,
  auto-start/restart, model registration, routing, and calls remain off;
- strict action-receipt and cleanup-block contracts now distinguish local
  process truth from remote connection truth, refuse false Stop/cleanup claims,
  make uncertain cleanup lifecycle-blocking, and structurally forbid endpoints,
  credentials, commands/paths, process identities, tools, prompts, and results;
- host status refuses endpoint, credential, executable, PID, tool-name, and
  other connection/process content, and reports cleanup uncertainty instead of
  claiming an unverified Stop;
- factory construction starts nothing, connection material is excluded from
  the lease representation, and the SDK client is unusable after context exit;
- no supervisor, runtime component, host route, durable host state, model tool,
  or tool-call path exists yet.

Validation for this preparation: 167 managed-host-contract/guarded-host/package/
server-management tests passed, including boolean deadline coercion refusal,
authority-skip transition refusal, deterministic revision-bound preview
digests, preview authority/content drift refusal, false receipt and cleanup
truth refusal, content-free status enforcement, exact local/remote project
binding, cross-project and TOCTOU refusal, hidden stdio descendant cleanup,
direct no-tool-call assertions, absent-package read-only behavior, local
integrity/runtime drift, remote plan drift, stale revision, and vault-secret
non-persistence. Python compileall and the repository privacy scan passed after
the earlier resolver preparation; both gates are rerun after each preparation
edit. The running app remained one loopback `pythonw` listener. The persistent
authority described below remains approval-gated.

## Authority at the checkpoint boundary

| Capability | Store-06a | Store-06b exit |
| --- | --- | --- |
| Retain reviewed tool names and schemas locally | Yes | Yes |
| Persist exact project/tool admission | Yes | Yes |
| Start third-party package code automatically | No | No |
| Owner-start one admitted project/server host | No | Yes, current app run only |
| Keep one remote MCP connection open | No | Yes, current app run only |
| Re-list exact tool contracts for health/drift | Probe only | Yes |
| Expose MCP tools to a model | No | No |
| Invoke `tools/call` | No | No route exists |
| Resume a host after app restart | No | No; owner must start again |
| Remember an approval to run third-party code | No | No |

Installation remains separate from project admission, and project admission
remains separate from app-run hosting. A successful host start is not a tool
call approval.

## Verified implementation seams

The audit reviewed the current application, transport, package, SDK, API,
frontend, persistence, and shutdown boundaries.

1. `OfficialSdkMcpProbeClient` already supplies the safe connection primitives:
   fixed-origin public DNS pinning, no redirects, no proxy inheritance, bounded
   remote responses, validated stdio launch material, and content-free errors.
   Its target construction is currently private and must be extracted into one
   shared connection factory rather than duplicated by the supervisor.
2. `owned_stdio_client` already starts Windows processes without a console,
   atomically assigns the process tree to an owned Job Object, drains stderr,
   bounds JSON-RPC bytes, closes every stream, kills descendants when needed,
   and returns explicit cleanup evidence. Its current stdout limit is cumulative
   for the entire short probe, and stderr is discarded without a lifetime byte
   counter. Persistent hosting must add separate per-message and per-instance
   stdout/stderr budgets so an ordinary long-lived host neither exhausts a
   probe-only counter nor permits an unbounded flood.
3. The pinned official MCP SDK `Client` owns its transport and session through
   one async context. Its `__aenter__`, all operations, and `__aexit__` must stay
   on the same supervisor-owned async actor. SDK objects must never cross into
   the synchronous Agent worker or an HTTP request thread.
4. The SDK's `send_ping` is legacy-only. Store-06b therefore uses a complete,
   cache-bypassed, bounded `tools/list` as the portable health check. The same
   result is normalized through the Store-06a contract reviewer and compared
   exactly with the admitted snapshot. No tool result is requested.
5. `McpbPackageInstaller` retains the exact tree and manifest digests but does
   not expose a public read-only launch resolver. Store-06b must add one that
   re-verifies the installed location, tree digest, manifest digest, runtime,
   entry point, arguments, environment, and confined working directory before
   each start. Paths and launch values remain infrastructure-only.
6. `McpManagedServerService.probe_remote` already re-resolves the exact Registry
   plan and reads deterministic secret references just in time. That logic must
   become a shared transient connection-material resolver used by both probes
   and persistent starts. Endpoint and secret values must not enter DTOs,
   receipts, logs, exceptions, or supervisor status.
7. The application lifecycle has no MCP supervisor component today. The new
   component must join the one idempotent desktop/ASGI shutdown path and close
   before Agent/model shutdown can strand work.
8. `McpManagedServer.host_state=not_started` is currently a server-wide constant,
   while Store-06b hosting is project/server-specific. Runtime truth must be a
   separate strict project-host view. The UI must not infer pair state from the
   old constant field.
9. The local Agent's tool enum remains intentionally closed. Store-06b adds no
   MCP tool provider and no chat dispatch seam; that authority belongs only to
   Store-06c.

## Important safety truth for local packages

Project admission limits which tools Prompt Enhancer may later route. It is not
an operating-system sandbox for the third-party server process. A local MCP
package runs native code under the current user's operating-system permissions,
even while no model can call it. The start preview and confirmation must say
this plainly.

The existing Windows Job Object provides process-tree ownership and cleanup,
not filesystem or network confinement. Store-06b may enable persistent local
hosting on Windows only after the hidden-process and descendant-cleanup tests
pass. On a platform without an equally strong abrupt-parent-death guarantee,
local persistent start remains unavailable with a specific reason; remote
hosting is independent.

## Runtime ownership design

### Supervisor

Add one first-party `McpManagedHostSupervisor` per Prompt Enhancer process.
Creating it starts no third-party code. It owns one async event-loop thread and
a bounded command queue. Each running project/server pair is one isolated actor
task and one SDK `Client` context.

The synchronous facade exposes only:

- `start(command) -> project host status`;
- `stop(command) -> project host status`;
- `status(project_id, management_id) -> project host status`;
- `list_statuses(management_id) -> bounded project host statuses`;
- `revoke_project(project_id, management_id, reason) -> cleanup evidence`;
- `revoke_server(management_id, reason) -> cleanup evidence`;
- `shutdown() -> aggregate cleanup evidence`.

There is deliberately no `call_tool` method in Store-06b.

### Bounds

The first implementation uses explicit conservative limits:

- at most 4 active project/server clients per app process;
- exactly 1 active client for a project/server pair;
- at most 16 pending supervisor control commands;
- 20 seconds for start negotiation and initial exact re-list;
- 10 seconds for one health/drift check;
- health checks no more often than every 30 seconds;
- at most 256 tools and 16 list pages, reusing existing schema/metadata limits;
- at most 2 MiB per JSON-RPC message/HTTP response, plus explicit bounded
  per-instance stdout and stderr budgets; reaching a lifetime budget makes the
  host unhealthy and closes it rather than silently resetting the safety bound;
- no automatic restart and no reconnect after a failure.

Limit exhaustion fails closed with a stable content-free code and starts no
additional host.

### Connection ownership

Refactor the current private transport constructors into an
`OfficialSdkMcpConnectionFactory`. The factory validates one transient remote
or stdio connection specification and returns an async context with:

- one connected SDK client;
- protocol/transport identity;
- local process cleanup evidence when applicable.

The probe adapter and persistent supervisor must both use this exact factory.
The supervisor actor enters the context, performs the complete re-list, remains
the sole owner while ready, and exits the same context on every stop/failure
path. Remote headers/endpoints and local commands/paths are released with the
actor and are never returned by status APIs.

## Start state machine

`not_started -> starting -> ready`

One native-confirmed start request binds all of the following:

- request ID and preview digest;
- current app-run identity;
- project ID and managed-server ID;
- managed-server revision and installation generation;
- project-binding revision;
- exact tool snapshot ID and schema digest;
- exact admitted tool IDs;
- start deadline.

The transition is allowed only when the plan is installed/active, no lifecycle
operation or cleanup block exists, the project binding is enabled and admitted,
the snapshot is current, and the pair is not already owned by a different
start.

Start then performs, in order:

1. reserve the pair in memory as `starting`;
2. resolve current durable plan, binding, snapshot, and package evidence again;
3. for local, re-derive launch material and verify exact tree and manifest;
4. for remote, re-resolve the exact Registry plan, vault references, endpoint,
   and public DNS pin;
5. enter the owned transport and SDK client on the actor;
6. enumerate the complete tool contract with cache bypass and existing limits;
7. normalize it with the Store-06a reviewer and compare every contract digest,
   protocol, count, schema digest, source generation, and admitted identity;
8. re-read the durable plan/binding/snapshot to close the start race;
9. publish `ready` in memory and write only a content-free transition receipt.

Any mismatch closes the client before returning `drifted`/`not_started`; it
never publishes ready.

## Health and drift state machine

`ready -> unhealthy -> stopping -> not_started`

While ready, the actor performs a bounded complete tool re-list on the same
connection. It uses `cache_mode="bypass"`, the Store-06a normalization limits,
and an exact snapshot comparison. A transport error, process exit, timeout,
malformed response, pagination violation, schema/metadata drift, changed
protocol, or changed durable admission immediately removes `ready`, records a
content-free reason, and closes the connection. It does not reconnect.

For a local package, tree and manifest are verified before launch and again
after close. A changed installed tree blocks the next start and enters existing
package cleanup/integrity handling. The health loop must not read unrelated
filesystem content.

## Stop and revocation state machine

`ready|starting|unhealthy -> stopping -> not_started|cleanup_required`

Stop reduces authority, so the authenticated loopback Stop route must remain
available without native confirmation. It is idempotent and may cancel a start
in progress. Shutdown, project disable/admission change, secret removal,
update, rollback, uninstall, and cleanup transitions call the same revocation
path before changing durable state.

The order is mandatory:

1. revoke the in-memory ready lease;
2. cancel health/start activity;
3. exit the SDK client and transport on the actor;
4. verify remote close or local root/tree/stream cleanup;
5. only then permit an invalidating durable mutation;
6. publish `not_started` and a content-free stop receipt.

If cleanup cannot be proven, publish `cleanup_required`, persist a blocking
content-free cleanup record for the exact project/server instance, and refuse
restart, update, rollback, uninstall, or replacement hosting until a dedicated
recovery action proves cleanup. An uncertain stop is never reported as stopped.

## Restart semantics and persistence

Normal running state and connection material are memory-only. No host starts at
boot and no previous start receipt grants a new start.

Schema 21 should add only content-free host evidence:

1. `mcp_managed_host_action_receipts`
   - request ID, action, project/server IDs, instance ID;
   - bound plan, binding, snapshot, and app-run digests;
   - outcome/reason, timestamps, process-started truth, cleanup truth;
   - no endpoint, header, credential, executable, argument, path, tool name,
     prompt, transcript, or result.
2. `mcp_managed_host_cleanup_blocks`
   - one exact project/server/instance cleanup uncertainty;
   - fixed reason code, created/updated time, and resolved state;
   - no reusable process authority and no raw process command.

Durable start request IDs are consumed tombstones, not replay authority. A
repeated request in the same app run may return the same in-memory result. The
same request after restart returns an expired/replayed refusal and never starts
code. Stop replays remain safe.

After restart, an admitted pair is shown as **Allowed, stopped after restart**.
The last content-free receipt explains that state; the user must issue a new
native-confirmed start.

## Strict API contract

Add a project-scoped runtime contract rather than overloading the durable
server plan:

- `GET /v1/integrations/mcp/managed/{management_id}/projects/{project_id}/host`
- `GET /v1/integrations/mcp/managed/{management_id}/projects/{project_id}/host/start-preview`
- `POST /v1/integrations/mcp/managed/{management_id}/projects/{project_id}/host/start`
- `POST /v1/integrations/mcp/managed/{management_id}/projects/{project_id}/host/stop`
- a bounded host-status collection used by the managed-server detail view.

The strict status DTO contains only:

- project/server/instance identifiers;
- `not_started`, `starting`, `ready`, `unhealthy`, `stopping`, or
  `cleanup_required`;
- fixed reason code and transport kind;
- bound plan/binding/snapshot revisions;
- admitted and observed tool counts/digests, never tool content;
- started/last-checked/stopped timestamps;
- process-started and cleanup truth;
- `tool_calls_available=false` and `tool_routing_state=inactive` literals.

The start preview states exactly what will persist, what runs, what remains
unavailable, the local-code OS-authority warning when relevant, and whether
native confirmation is available. Mutating responses use private/no-store
headers and the existing user-presence body binding.

No API path containing `call`, `invoke`, or model tool registration is added in
Store-06b.

## UI contract

The Managed server detail keeps install/review/project admission separate from
runtime hosting. Each admitted project row receives one compact runtime block:

- **Allowed · stopped** with `Start for this app run`;
- **Starting** with a working Stop action;
- **Ready · N contracts matched** with last health time and Stop;
- **Unhealthy/Drifted** with the fixed explanation and cleanup state;
- **Stopping**;
- **Cleanup required** with restart and lifecycle actions disabled.

Start opens the exact native confirmation preview. Local packages prominently
state that the process runs with the current user's OS permissions. Ready copy
states **Tool calls are still locked until Store-06c**. There is no Tools-ready
control in Agent chat yet.

Keyboard focus returns to the initiating project row after confirmation or
failure. Loading, stale revision, offline Registry, secret-vault failure,
unsupported platform, drift, cancellation, and cleanup-uncertain states each
have strict tested copy. The layout must work at desktop and 320 px widths.

## Integration points

Store-06b implementation is expected to touch these bounded seams:

- `application/mcp_guarded_host.py`: public reusable contract normalization;
- `infrastructure/mcp_guarded_host.py`: shared SDK connection factory;
- `application/mcp_local_packages.py` and
  `infrastructure/mcp_package_installer.py`: exact installed launch resolver;
- `application/mcp_server_management.py`: transient remote resolver and
  revoke-before-mutation port;
- new application/infrastructure managed-host supervisor modules;
- `application/runtime_lifecycle.py`, `bootstrap.py`, and `api.py`: lifecycle
  ownership and liveness;
- agent-catalog schema 21 plus the managed-host evidence repository;
- managed MCP HTTP routes, OpenAPI, strict frontend contracts, transport, Store
  UI, and synthetic fixtures.

The local Agent dispatcher, model prompt/tool schema, chat events, and tool-call
receipts remain unchanged.

## Correctness and adversarial acceptance matrix

### Unit and contract

- actor ownership, queue/host limits, duplicate start, start/stop races, and
  idempotent Stop;
- exact complete tool re-list, pagination, cursor loops, schema/metadata drift,
  alias collision, protocol change, malformed and oversized messages;
- local tree/manifest/runtime/entry/argument/environment/path re-verification;
- remote plan revision, vault reference, DNS, origin, redirect, proxy, header,
  timeout, and response bounds;
- strict request/response parsing, no extra fields, OpenAPI/frontend agreement;
- direct proof that no Store-06b object exposes or calls `call_tool`.

### Failure and lifecycle

- stdio start failure, immediate exit, hang, stderr flood, descendant spawn,
  cooperative close, forced close, and cleanup-unconfirmed injection;
- remote disconnect, silent connection, server error, health timeout, and drift;
- project disable, admission change, secret removal, update, rollback,
  uninstall, app Stop, normal shutdown, forced desktop shutdown, and app reload;
- start interrupted at every boundary, including after process creation and
  before ready publication;
- migration from schemas 1 through 20, corrupted cleanup/receipt rows, request
  replay across restart, and no auto-start at schema migration or boot.

### Privacy and UI

- synthetic reserved identities only; secret/PII canaries and privacy scanner;
- captured logs/errors/receipts contain no endpoint path, secret, command,
  package path, tool content, prompt, transcript, or result;
- project A cannot inspect/start/stop project B's instance through stale IDs;
- desktop/narrow/keyboard/focus/empty/loading/error/cleanup states;
- production build and protected app reload;
- Windows process census proves one app listener, zero visible terminal
  processes, zero orphan MCP processes after Stop and shutdown;
- zero model runtime/GPU allocation during the entire Store-06b gate.

## Implementation order and current boundary

1. **Prepared:** extract and test the shared connection factory and public
   exact-contract reviewer without changing runtime behavior.
2. **Prepared:** add the installed-package and remote transient connection
   resolvers with integrity and privacy tests.
3. **Contracts, exact read-only authority resolution, and confirmation preview
   prepared; execution approval-gated:** strict binding, command, status, limit,
   cleanup-truth, and transition contracts exist; an exact admitted
   project/server binding and truthful start preview can be resolved without
   connection material. The actor, persistent connection, health/drift loop,
   route, UI control, and process execution do not.
4. **Evidence contracts prepared; persistence approval-gated:** add schema 21
   content-free receipts/cleanup blocks and migration tests. No table or
   repository wiring exists yet.
5. Wire revoke-before-mutation and app lifecycle shutdown/liveness.
6. Add start-preview/start/status/Stop routes and regenerate strict contracts.
7. Add the project runtime UI and responsive/accessibility tests.
8. Run focused suites, full backend/frontend suites, privacy/OpenAPI/build
   gates, protected reload, live synthetic start/Stop, and process census.
9. Record a Store-06b handoff and owner click checklist. Store-06c remains
   locked until its own approval.

## Approval gate

Approval means: implement an owner-started persistent MCP host for the current
app run, including execution of reviewed local package code or a persistent
reviewed remote connection, with no model-visible tools and no tool calls.

It does not approve Store-06c, remembered tool-call permissions, automatic
startup, background reconnection, real third-party credentials, or any real MCP
package in automated tests.
