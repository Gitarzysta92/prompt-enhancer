# MCP Store checkpoint 06 readiness

Date: 2026-08-30
Status: Store-06c implementation and focused automated gates complete; protected live review pending
Runtime effect of the original audit: none; subsequent Store-06c tests use synthetic in-process transports only

> Current implementation evidence and the owner review ledger are in the
> [Store-06c handoff](checkpoint-mcp-store-06c-handoff.md). The readiness text
> below is retained as the historical authority design that Store-06c now
> implements; statements that Store-06b/06c are still locked describe that
> earlier gate, not current runtime availability.

## Outcome

Store-05c is a sound package-management boundary, but it is not yet an MCP
runtime. The next work must add four separate authorities and keep them visibly
distinct:

1. **reviewed tool metadata** — what one exact server generation reported;
2. **project admission** — which exact tools the owner allowed for one project;
3. **app-run host authority** — which admitted server the owner started for the
   current application run;
4. **single-call approval** — which exact revision-bound invocation the owner
   approved once.

No later authority may be inferred from an earlier one. Installing a package
does not admit tools, admitting tools does not start code, starting a host does
not approve a call, and an approval cannot be reused after it settles or after
restart.

## Store-06a implementation update

The owner approved Store-06a. Exact reviewed tool snapshots and per-project
tool allowlists are now implemented without adding persistent host or tool-call
authority. See the
[Store-06a handoff](checkpoint-mcp-store-06a-handoff.md) for its exact behavior,
test receipts, deliberately locked capabilities, and owner click checklist.

The **Verified starting point** below is retained as the historical pre-06a
audit baseline. The separate
[Store-06b readiness contract](checkpoint-mcp-store-06b-readiness.md) records
the completed lifecycle audit, corrected modern health design, exact authority
increase, implementation order, and acceptance matrix. Shared connection and
exact launch resolvers plus content-free managed-host contracts are now
prepared and tested without starting a host. Store-06b persistent execution
remains locked until its own explicit approval.

## Verified starting point

- Agent catalog schema 17 stores managed plans, requirements, secret
  references, project-level coarse permission plans, compatibility receipts,
  package generations, lifecycle journals, rollback state, and recovery
  receipts.
- It has no durable host-instance, reviewed-tool, per-tool admission, tool-call,
  or call-approval tables.
- A saved project binding can truthfully be only `disabled` or
  `inactive_host_unavailable`; managed servers can report only
  `host_state=not_started` and `tool_routing_state=inactive`.
- The managed HTTP surface supports create/review/probe/install/update/rollback/
  uninstall/recovery, project plan, and secret-reference actions. It exposes no
  host start/stop, tool admission, tool listing, or tool-call route.
- The guarded host is a bounded compatibility probe. It validates an MCP
  handshake and paginated tool contracts, persists only count/digest evidence,
  closes the connection, and discards names and schemas.
- The local stdio transport already provides the critical Windows safety
  primitive: atomic Job Object ownership, hidden pipes, bounded responses,
  descendant-wide termination, and verified stream cleanup.
- The application lifecycle has no managed MCP supervisor component. Shutdown
  currently owns analysis workers, local models, the local Agent, and model
  evaluation only.
- The pinned official MCP SDK is version 2.1.1. Its persistent `Client` context
  supports tool listing, calls, progress callbacks, and explicit async close
  over the existing guarded transports. Ping is legacy-only; modern health must
  use a bounded cache-bypassed re-list/transport-liveness check.
- Installed MCPB evidence retains tree and manifest digests but not executable,
  argument, environment, or working-directory values. Runtime launch material
  therefore must be re-derived from the verified installed tree; it must never
  be copied into the public API or durable receipts.
- User-supplied ordinary configuration is not collected. Non-empty MCPB
  `user_config` is intentionally refused today; fixed remote endpoints and
  configuration-free packages are the currently executable subset.
- The local Agent already has project identity, streaming tool events, Stop,
  native per-call approval, revision-aware history, and cancellation. Its tool
  schema and dispatch are currently a closed built-in enum and need a narrow
  injected MCP provider rather than a second chat loop.
- The similarly named Agent MCP connection feature is inbound orchestration
  (Codex/Claude clients controlling Prompt Enhancer). It must remain separate
  from Store-installed outbound MCP servers.

## Required architecture

### Reviewed tool snapshot

One successful bounded inspection creates an immutable, local-only snapshot
bound to the managed-server revision, exact plan revision, installed tree and
manifest digests when local, protocol version, and full contract digest.

Each tool record needs a stable internal identity plus bounded normalized name,
title, description, input schema, optional output schema, per-tool schema
digest, and deterministic model-facing alias. Tool annotations, icons, schema
descriptions, defaults, and examples are untrusted metadata and grant no safety
property. The model-facing schema must be a separately derived safe projection;
the exact canonical schema remains the validation and drift evidence.

Tool names and schemas are sensitive derived local data. They may be retained
only in the dedicated local catalog, served through authenticated private/
no-store routes, deleted with the managed server, excluded from logs and error
text, and never uploaded. Controls, excessive nesting, duplicate identities,
external references, unsupported schema dialects, prompt-like metadata abuse,
and alias collisions fail closed.

Any exact contract change creates a new snapshot and makes every prior tool
admission stale. An update, rollback, or relevant configuration change must
stop routing before publication and require a new owner review.

### Project admission

Admission is an allowlist of exact tool-record identities for one exact Agent
project and one exact snapshot revision. It also binds every existing inferred
coarse permission. The project sees no unselected tool and a session can never
borrow admission from another project.

Saving admission is native-confirmed, revision-checked, idempotent, and durable.
It still leaves the host stopped. Removing admission revokes routing first,
cancels or settles pending work, and then requests host cleanup.

The model receives deterministic aliases, never routing authority encoded in a
model-chosen server/tool string. Alias lookup must resolve through the current
project, snapshot, and admission records before and again after approval.

### App-run host supervisor

A dedicated supervisor owns one isolated client instance per project/server
pair. It runs an async actor loop behind a bounded synchronous facade so the
existing Agent worker never owns SDK event-loop or process handles directly.
Active host count, queued calls, response bytes, deadlines, and concurrency are
bounded.

For local packages, start must re-read the installed manifest, verify the exact
tree and manifest digests, re-derive confined launch material, and use the
existing atomic hidden-process transport. For remote servers, start must
re-resolve the exact reviewed Registry plan, load only deterministic vault
references just in time, re-pin the public origin, disable redirects and proxy
inheritance, and discard connection secrets on close.

Initialization re-lists the complete tool contract and must match the admitted
snapshot before routing becomes active. Ping failure, process exit, schema
drift, update, rollback, uninstall, project disable, Stop, or app shutdown first
revokes routing and then closes the client. Unconfirmed process-tree cleanup is
a durable blocking state, never a successful stop.

Admission survives restart; execution authority does not. After restart the UI
shows **Allowed, stopped after restart** until the owner starts the server for
that app run. No third-party package code auto-starts during boot.

### Approval-bound calls

Every external MCP call initially requires a fresh native approval, including
apparently read-only tools. The approval binds project, session, turn, host
instance, managed server, tool record, snapshot/admission revisions, canonical
argument digest, deadline, and one call ID. It is memory-only and single-use.

Arguments are validated against the exact input schema before review and again
after approval. The approval card shows server, tool, risk/permission summary,
and a bounded redacted argument preview; raw secret values and exact arguments
are not written to receipts or logs. A stale binding, changed schema, stopped
host, different session/project, repeated approval, or expired deadline fails
before the SDK call.

The first usable result lane supports bounded MCP text and structured JSON.
Unsupported image, audio, embedded-resource, resource-link, elicitation,
sampling, roots, or incomplete result modes fail visibly and closed until the
multimodal/artifact checkpoint adds their reviewed projection. Server logging
is not retained. Progress may be shown only through bounded ephemeral activity
updates.

Stop cancels a pending approval or active call. If cooperative cancellation does
not settle, the supervisor closes that client; a local client is not reusable
until tree cleanup is verified. A retry is a new call and a new approval.

Durable call receipts are content-free: identity/revision links, state,
approval outcome, fixed error code, timestamps/duration, bounded byte counts,
result digest, cancellation truth, and cleanup truth. They contain no arguments,
results, credentials, endpoints, commands, paths, prompts, or transcript text.
The chat timeline may retain only the already-governed local history projection.

## Implementation checkpoints

| Slice | Deliverable | Runtime authority at exit | Acceptance gate |
| --- | --- | --- | --- |
| Store-06a | Exact reviewed tool snapshots and per-project tool allowlists | None; probes still close and routing remains inactive | Schema migration, strict API/parser/UI, drift invalidation, alias collision, malicious metadata/schema, stale revision, cross-project, privacy scan, and full regression pass. |
| Store-06b | App-run start/stop supervisor for the already-supported fixed/configuration-free subset | Owner-started host only; no tool call route | Hidden owned process/remote client, exact re-handshake, health, Stop/shutdown/restart truth, crash and cleanup tests, zero terminal windows. |
| Store-06c | Revision-bound call approval, cancellation, result projection, and Agent chat activity | One approved call at a time | Argument validation, approval replay/bypass, stale admission, cross-project, timeout/cancel, oversized/malformed result, chat ordering, and content-free receipt tests pass. |
| Store-06d | Configuration breadth: vault-backed user values, remote templates, and reviewed MCPB `user_config` staging | Same call boundary for newly supported configurations | No value returned/logged/stored in plaintext; template/path/env injection, missing/changed config, install/probe compensation, and migration tests pass. |
| Store-06e | SOTA management/chat UX, recovery, live reload, and owner walkthrough | Complete Store-06 behavior | Desktop/narrow/keyboard/focus/empty/error/loading states, process census, production build, real app reload, and owner checklist pass. |

Only one slice becomes implementation-active at a time. Each receives a
separate handoff, test ledger, reload, and owner review opportunity.

## UI contract

- **MCP Store / managed server:** Install, Configure, Reviewed tools, Projects,
  Runtime health, and Lifecycle history are separate sections. Advanced package
  details stay in settings rather than crowding the conversation.
- **Project row:** use truthful states — Off, Review required, Allowed/stopped,
  Starting, Ready, Unhealthy, Drifted, Stopping, or Cleanup required.
- **Chat header:** a compact `Tools · N ready` control opens the current project
  tool drawer; it does not duplicate the Store.
- **Conversation:** one compact activity card moves through requested, awaiting
  approval, approved/denied, running, succeeded/failed/cancelled. Server and
  tool are always named; duration and bounded result state are visible.
- **Approval:** the primary action is **Allow once**. There is no remembered
  approval in Store-06.
- **Restart:** admitted servers visibly return as stopped, not falsely ready.
- **Unsupported content/configuration:** explain the exact missing capability
  and preserve all existing package/project state.

## Cross-cutting test matrix

- Synthetic fixtures only; no real Registry package or private configuration in
  tests, logs, screenshots, or documentation.
- Fresh schema plus migration from every supported agent-catalog version;
  interrupted writes and corrupted rows fail closed.
- Exact idempotency and optimistic concurrency for snapshot, admission, start,
  stop, approval, and receipt actions.
- Tool pagination, duplicate names, Unicode/control text, alias collisions,
  hostile descriptions, external references, depth/node/byte limits, schema
  drift, and output-schema mismatch.
- Cross-project, cross-session, stale-revision, disabled-tool, stopped-host,
  changed-generation, expired approval, duplicate approval, and direct-route
  bypass attempts.
- Stdio spawn/crash/hang/descendant escape/oversized stdout/malformed JSON and
  cleanup failure; remote DNS rebinding/private address/redirect/proxy/header/
  response-limit cases.
- App boot never starts third-party code. Disable, Stop, update, rollback,
  uninstall, close, app reload, and forced shutdown leave no owned host or
  terminal process; uncertainty remains owner-visible and blocking.
- Strict frontend contract parsing, accessible keyboard operation, responsive
  layouts, focus restoration, truthful loading/empty/error states, OpenAPI
  generation, TypeScript compile, production build, backend/full frontend
  regressions, privacy scanner, and diff checks.

## Historical gate that began Store-06a

Owner approval is required because Store-06a intentionally changes the prior
privacy contract from digest-only probes to local retention of reviewed tool
names and schemas. It still starts no persistent host and executes no tool.

That approval was received and Store-06a finished its documented automated and
live gates. Store-06b now waits at its separate persistent-host approval gate.
