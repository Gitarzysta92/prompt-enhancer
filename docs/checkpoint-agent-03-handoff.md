# Agent-03 handoff: coordinated local model runtime

Date: 2026-08-27
Status: implementation and bounded automated/browser verification complete; native GPU/model owner validation remains deferred

## Outcome

The Agent workspace now has one revision-bound global model coordinator instead
of independent per-card start/stop state. At most one local runtime can be
served. Switching from model A to model B serializes request drain, unload,
cleanup assessment, load and a loopback text-capability probe before B is
reported ready.

The Agent page exposes this coordinator as a compact bottom-left model control.
Model, GPU/GPU+CPU/CPU placement, context limit, Apply and Stop remain visible.
Requested-versus-served state, cleanup receipts and capability details are in
an expandable diagnostic section. Projects and setup tools scroll independently
above it, so the control remains visible without stretching the chat page.

An idle live chat can be rebound to the verified served model through a
revision-bound durable catalog update. The operation does not clear its
conversation or unsent draft. If the runtime switch succeeds but catalog
rebinding fails, the UI reports that split outcome and retries only the binding
instead of unnecessarily reloading the model.

## Implemented boundary

- `GET /v1/local-models/runtime` returns the coordinator revision, lifecycle
  state, active request count, requested and served selections, context truth,
  cleanup receipt, capability receipt and a safe error code.
- `POST /v1/local-models/runtime/switch` and
  `POST /v1/local-models/runtime/stop` require the expected coordinator
  revision. Legacy model activation and deactivation also pass through the
  same coordinator.
- Cross-alias activation is globally serialized. A replacement never starts
  while the previous process or an admitted inference request is still owned.
- Every completion and stream reserves the exact served runtime generation and
  releases it once, including cancellation and transport-failure paths.
- A stop confirms process exit and records measured, unknown or failed GPU
  cleanup. Unknown or failed cleanup blocks replacement loading instead of
  claiming VRAM was freed.
- Only the exact capability-verified served alias is exposed as active to Agent
  session creation and message handling.
- The load handshake performs a bounded loopback synthetic text completion.
  Failure never becomes `ready`. Tool templates can be configured, but a real
  tool-call exchange is not verified; the UI therefore says `Tools configured`
  rather than `Tools available`.
- `POST /v1/agent/sessions/{session_id}/model` rebinds only an idle, live,
  non-closing session to the exact ready model. It updates durable model
  metadata and in-memory settings under the same session locks used by Send.
- OpenAPI, generated TypeScript contracts, the strict runtime payload parser,
  HTTP transport and synthetic fallback transport include the new operations.

## Runtime and persistence truth after Agent-03

| State | Truth now |
| --- | --- |
| Global runtime ownership | One in-memory coordinator and at most one served process |
| Requested versus served model | Reported separately with placement and context limit |
| Text capability | Bounded loopback probe required before Ready |
| Tool capability | Configuration reported; actual model tool-call behavior not yet probed |
| Context use | Limit is known; used tokens remain explicitly unknown |
| VRAM cleanup | Measured when observable; otherwise unknown/fail-closed |
| Chat model binding | Durable catalog metadata plus live in-memory session setting |
| Projects and chat navigation | Durable |
| Conversation messages after restart | Still unavailable; Agent-04 owns persistence |
| Runtime after app restart | Not restored as a live process or lease |

## Correctness repairs found during validation

The first browser pass showed that the complete diagnostic card appeared below
the project rail instead of behaving like a bottom-left model picker. The side
column now has a bounded viewport-height budget, its upper project/settings
region scrolls independently, and runtime diagnostics collapse behind
`Runtime details`. At a 1280 x 720 synthetic browser viewport the document now
fits the viewport, has no horizontal overflow, and the model control is visible
on first load.

The broader backend sweep also found that the real HTTP-stream fixture borrowed
the runtime transport without the coordinator's new ownership hooks. The
fixture now acquires/releases a synthetic lease and asserts that its final
active-request count is zero. All bounded usage trailer, framing, cancellation
and no-EOF cases pass without weakening the production coordinator.

The UI initially described the tool flag as `Tools available`. Because the
current handshake verifies text rather than a real tool exchange, that label
was corrected to `Tools configured`.

## Verification receipts

- 1,924 frontend tests across 139 files passed in the complete regression run.
- After the final compact-layout and capability-copy adjustment, 100 focused
  Agent page, runtime-control and layout tests passed.
- Six dedicated runtime-control component tests cover requested/served truth,
  placement/context payloads, revision-bound session rebinding, active-turn
  blocking, Stop, cleanup-unknown failure and binding-only retry.
- 201 selected Python tests passed across the model coordinator, Agent catalog,
  orchestration manifest, Agent lifecycle/completion/usage/receipts and OpenAPI.
- Coordinator tests cover concurrent A/B activation, at-most-one live runtime,
  active inference during switching, stale revisions, capability-probe failure,
  cleanup-unknown quarantine and exact served-alias exposure.
- The production TypeScript/Vite build, Python compilation, OpenAPI export
  tests and generated TypeScript API parity check passed.
- A synthetic browser switch changed the runtime and active chat from
  `example-small-cpu` to `example-medium-split`, retained the unsent draft,
  displayed the successful binding receipt and produced no page-wide overflow.
- Zero Prompt Enhancer or llama-server processes were running afterward. Port
  8765 had no listener. The already-running loopback Vite fixture remained on
  127.0.0.1:4173; no app server or model process was launched.
- The repository-wide privacy scanner was run but is not green: it flags the
  pre-existing untracked binary `docs/checkpoint-agent-02-shell.png`. No new
  Agent-03 screenshot or non-synthetic fixture was added.

## Owner checklist for the later native reload

1. Start a small model on CPU, send one prompt and confirm the card reports the
   requested and served aliases, placement and context limit.
2. Type an unsent draft, switch to a second model and verify the first process
   exits, the second passes its text probe, the chat binding changes and the
   draft remains.
3. Repeat CPU -> GPU+CPU -> GPU placement while watching operating-system and
   GPU process state. Confirm only one llama-server exists at every boundary.
4. Send a long-running prompt and attempt a switch. Verify the UI blocks it
   until the response is stopped or finishes.
5. Stop the model and confirm VRAM/process cleanup before loading another. If
   cleanup cannot be measured, verify the card reports unconfirmed/quarantined
   rather than Ready.
6. Resize the native window below 900 px and verify the conversation remains
   first, runtime controls stack without horizontal overflow, and project/chat
   navigation remains reachable below it.

These checks are intentionally not marked passed. This checkpoint used only
synthetic in-memory and loopback fixtures because relaunching the native owner
or a real llama-server previously caused visible terminal-window cascades.

## Capability-list status and next checkpoint

Agent-03 completes the planned reliable model-switching and placement slice,
subject to the native owner checks above. Durable projects, searchable/pinnable
chat navigation and the project/session hierarchy already exist from Agent-01
and Agent-02, but only navigation metadata survives restart.

Agent-04 should persist conversation messages and safe turn/activity receipts
so chats can genuinely reopen after an app restart. It must not restore pending
approvals, runtime leases, command authority or unverifiable model state. Rich
Markdown/code blocks, artifact viewers, multimodal input, branching and export
remain later checkpoints after durable conversation history.
