# Converge-05b handoff — external controller lifecycle evidence

Status: automated acceptance instrumentation complete on 2026-09-04; current
external-client execution and owner review pending; Converge-05 is not complete

## Outcome

The ordinary Agent **Direct app connections** workspace now contains a
page-owned, fail-closed ten-step acceptance guide for one exact external
controller lifecycle:

1. external client connection and `agent_discover`;
2. project-scoped `agent_catalog` discovery bound to the exact live chat;
3. atomic ownership of that chat;
4. objectively observed running state;
5. external `agent_stop` and ownership release;
6. one new turn followed by reconnect/wait without message resubmission;
7. a revision-bound offer and acceptance by a second same-project connection;
8. native revocation of the current owner;
9. a strictly later authentication refusal for that exact revoked credential;
10. an exact native settled-control release receipt.

The guide performs none of those actions itself. It observes normal connection
management, tool, ownership, revocation, rejection, and release receipts. The
run survives closing Agent settings, is bound to the current page's exact
project/chat, and clears on application reload.

## Exact activity evidence

`agent-mcp-management.v2` adds one random current-process `activity_epoch` and
one `agent-mcp-tool-activity-sequence.v1` cursor for every listed connection and
credential revision. The cursor contains only:

- connection identity and credential revision;
- a monotonic integer sequence;
- the admitted tool name and `external_client` or `native_self_test` source;
- admission/completion timestamps; and
- a nullable protocol outcome while the call is in flight.

It contains no token, prompt, message, tool arguments, result, path, model
content, provider configuration, or exception. The sequence is memory-only for
the current service process. A new process receives a new epoch and sequence
baseline, so a page receipt cannot combine calls across an app restart.

Tool admission is recorded before dispatch. A call that cannot receive an exact
sequence fails before its tool executes. Completion fills the same cursor; it
does not increment it. If a later call is admitted while an earlier one is still
running, the earlier late completion cannot overwrite the newer cursor or the
durable last-completed-tool receipt. This is what makes an in-flight
`agent_turn` and a later external Stop observable without retaining content.

The page advances only across a `+1` sequence change. A gap of two or more calls,
a different tool, a failed required call, a changed process epoch, credential
rotation, project drift, cross-chat ownership, lost ownership, a stale handoff,
an early release, or any target activity after handoff invalidates the run. The
optional native endpoint self-test can advance the baseline by one but never
passes an external-client step. Multiple calls between refreshes are rejected
as unverifiable even when the latest tool happens to be the expected one.

## Implementation map

- `src/prompt_enhancer/application/agent_mcp_connections.py` owns the strict
  management v2 contract, process epoch, sequenced admission/completion ledger,
  credential-revision checks, and late-completion ordering rule.
- `src/prompt_enhancer/interfaces/http/agent_mcp_routes.py` admits each MCP tool
  before dispatch and completes its exact sequence afterward.
- `frontend/src/features/agent/externalControllerAcceptance.ts` owns the
  content-free ten-stage acceptance state machine and adversarial refusal rules.
- `AgentPage` owns the page-memory receipt; `AgentControllerPanel` and
  `AgentMcpConnectionsPanel` render and update it without duplicating state.
- `AgentMcpConnectionsPanel.css` keeps all ten checkpoint tiles bounded at
  narrow and wide viewport sizes.
- The strict frontend parser, handwritten contracts, checked OpenAPI document,
  and generated TypeScript bindings all use management v2.

## Automated evidence

The final coherent tree passed:

- **203/203** direct MCP, client configuration, HTTP, controller client/CLI/HTTP,
  ownership, integration, packaging, probe, and OpenAPI backend tests;
- **577/577** Agent frontend component and state-machine tests;
- **89/89** responsive workflow browser journeys with one worker, including the
  controller guide at 360 px and 1440 px;
- **41/41** intercepted HTTP contract browser journeys with one worker;
- **16/16** production-build/real-loopback browser journeys with no intercepted
  application route; their cleanup receipt reports listener released, zero
  model runtimes, runtime cleanup confirmed, and temporary state removed;
- strict TypeScript compilation, production build, generated API parity,
  repository privacy scan, and whitespace validation.

The focused evidence includes:

- a blocking HTTP tool test proving admission is visible before completion;
- concurrent call ordering proving a late turn completion cannot overwrite a
  newer Stop;
- complete ordered two-controller success;
- a native self-test that does not count as external evidence;
- service restart, credential rotation, cross-chat ownership, inactive/cross-
  project handoff, stale release, and pre-revocation refusal rejection;
- direct hidden-resubmission detection where `agent_turn` followed by the
  expected `agent_control` between refreshes still fails because the sequence
  jumped by two; and
- settings-unmount persistence plus bounded ten-tile responsive layout.

All test identities, projects, chats, paths, tool outcomes, and timestamps are
synthetic. No real controller, model, prompt, workspace content, or credential
was used.

## Still owner-gated and unproven

This checkpoint does **not** claim that a current Codex, Claude Code, or other
real external client completed the lifecycle. It also does not certify physical
model placement, GPU/VRAM cleanup, native dialogs, the packaged Windows build,
or a process census on the owner machine. The app currently open on port 8765
was not restarted or mutated during this automated pass.

The real run needs two fresh active connections bound to one saved Agent
project, one live chat, and a model/runtime suitable for a deliberately bounded
long-running synthetic request. To observe streaming and issue external Stop,
the chosen client must support a second concurrent MCP request using the same
owning credential (or a second client instance using that exact credential).
For reconnect evidence, use a very short turn deadline and drain bound only on
a disposable request so the turn remains incomplete long enough to observe and
hand off. If the turn settles normally, the guide must not pretend reconnect was
proved; restart the page receipt with a suitable disposable case.

## Owner walkthrough

1. Restart into the reviewed packaged build and confirm exactly one loopback
   listener, no unexpected visible terminal, and no model already owned.
2. Open one saved project/chat, prepare two direct connections scoped to that
   project, and keep their one-time tokens only in their respective client
   processes.
3. In Agent settings, select the primary connection and choose **Begin external
   lifecycle proof**.
4. From the primary client call `agent_discover`; refresh once. Call
   `agent_catalog` with `list_chats` for the bound project; refresh once.
5. Start one disposable long-running `agent_turn` for the exact chat. While it
   is running, refresh until ownership and streaming pass. From a concurrent
   request using the same credential, call `agent_stop`; wait for its successful
   response and refresh once.
6. Submit the second disposable turn exactly once with the minimum suitable
   deadline/drain bounds. Refresh while running and again after it becomes
   reconnecting. Do not submit that message again. Call `agent_control` status,
   refresh, then `agent_wait` from the returned cursor with a short deadline and
   refresh.
7. From the primary owner offer handoff at the displayed revision to the second
   same-project connection. Refresh. From that exact target credential accept
   the displayed revision and refresh.
8. Revoke the target with the native **Revoke** button. Retry one MCP request
   with that exact revoked token, require HTTP 401, then refresh.
9. Settle the disposable live turn if needed and choose **Release settled
   control**. Require all ten tiles to show **Passed**.
10. Stop/unload the model, close the packaged app, and confirm the listener,
    owned process tree, and GPU allocation are gone. Record only content-free
    state/cleanup facts; never copy the token, prompt, output, path, or tool
    payload into this handoff.

## Next boundary

Converge-06 is the next repository-local implementation checkpoint: separate
operational metrics from experimental quality signals, remove misleading legacy
defaults, keep unsupported provider evidence visibly blocked, and simplify the
remaining dense non-Agent surfaces. The real Converge-04, 05a, and 05b owner
journeys remain open acceptance work and must not be relabelled complete.
