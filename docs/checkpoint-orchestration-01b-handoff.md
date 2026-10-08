# Orchestration-01b handoff

Status: automated implementation complete; owner external-client walkthrough remains

## Delivered outcome

A project-scoped direct Agent MCP connection can now own one exact live chat
operation without creating a process, terminal, model or second listener. The
same durable connection can reconnect and continue from an explicit cursor
without resending the original message. A different connection cannot wait for
or Stop that operation unless the current owner offers a revision-bound handoff
and the exact active same-project target accepts it before expiry.

Agent settings shows the owner, project, chat, operation, phase, cursor, last
sequence, update time, ownership revision and handoff state beneath the owning
connection. Pending native approval remains visible and never transfers. A
revoked or uncertain owner is retained until the backend independently proves
the chat is absent or settled and a native-confirmed release succeeds.

## Backend and protocol

- The Agent catalog advances to schema v24 with one content-free durable
  ownership row per chat and atomic claim, update, handoff and release methods.
- Ownership phases distinguish claimed, running, native-approval wait,
  reconnect, submission uncertainty, stopping, Stop uncertainty, cleanup
  quarantine and revoked authority.
- `agent_turn` and reviewed proposal tools claim ownership. `agent_wait` and
  `agent_stop` are owner-only. Terminal evidence releases ownership; ambiguous
  or incomplete evidence retains it.
- Project-scoped direct HTTP exposes `agent_control` for status, handoff offer,
  handoff acceptance and owner release. Generic unscoped invocation remains
  absent from that surface. The scoped surface has 19 tools, or 20 only when
  explicit model lifecycle authority is granted.
- Controller discovery advances to `local-agent-orchestration.v20`; connection
  management uses `agent-mcp-management.v1`; OpenAPI includes the strict
  ownership, handoff and native-release schemas.
- Native release is a one-shot user-presence action. The route rechecks exact
  revision and settled/cleanup-confirmed session evidence before deleting only
  the ownership record.

Ownership metadata contains no prompt, message, tool argument or result,
workspace path, credential or provider session content.

## UI and recovery behavior

- Connection cards show outgoing and incoming handoffs next to the exact
  controller identity.
- State-specific copy tells an owner whether to wait for native approval,
  reconnect from the saved cursor, observe uncertain delivery, inspect cleanup
  quarantine or reconcile a revoked credential.
- Unsafe native release stays disabled while an operation is claimed, running,
  stopping or approval-blocked. The backend remains authoritative for every
  allowed attempt.
- The token-free setup and self-test now advertise the exact 19 scoped tools,
  including `agent_control`, and still invoke no consequential operation.

## Verification evidence

- Backend orchestration/controller pack: **170 passed**. This includes concurrent
  claims, cross-project refusal, same-connection reconnect, foreign wait/Stop
  refusal, two-party handoff, expiry/stale revision, revocation, v23-to-v24
  migration, native release and real loopback MCP integration.
- Focused frontend contract/panel pack: **257 passed**. The complete frontend
  suite is green at **173 files / 2,489 tests**.
- Synthetic browser ownership journey: **2 passed** at 360 px and 1440 px.
  The existing controller-health journey also remains green at both widths.
- Production TypeScript/Vite build, generated API drift check, Python compile,
  and repository privacy scan pass.
- One coordinated hidden reload produced exactly one loopback listener. The app
  tree has no visible window, the shared model runtime is stopped, no MCP worker
  is active, and the live Agent page reports zero browser console warnings or
  errors.

The frontend test gate now waits for asynchronous reviewed-action and workspace
readiness states and uses a bounded 15-second ceiling for the large Agent JSDOM
integration surface, eliminating host-scheduling false failures without
weakening hang detection.

## Still intentionally open

- No real Codex, Claude Code or other external client was configured during this
  checkpoint. Creating its one-time scoped credential and completing one owner
  handoff/Stop walkthrough remains explicit owner evidence.
- No model was loaded and no protected file, command, web or native approval
  action was exercised. Those existing physical checks remain in Acceptance-01.
- No commit or push was performed.

## Next checkpoint

Store-06c: run an already installed MCP server under exact project scope, route
consequential tool calls into the native approval lane, and prove bounded
timeout, Stop, denial, result validation and owned process cleanup without a
health probe invoking a tool.
