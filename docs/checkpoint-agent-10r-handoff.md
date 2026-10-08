# Agent checkpoint 10r handoff

## Outcome

External Codex, Claude Code, and other scoped MCP controllers now reach the
same safe path-lifecycle review lane as the native Agent without receiving
apply or approval authority.

The new `agent_propose_lifecycle` tool and
`POST /v1/agent/sessions/{session_id}/lifecycle-proposals` accept exactly one:

- directory create under an existing parent;
- no-overwrite directory move;
- exact-revision, no-overwrite UTF-8 file move; or
- exact-revision recoverable file removal to the Windows Recycle Bin.

Submission is idempotent by request id and never changes the workspace. The
operation appears in the existing native approval card. After the person's
decision, Prompt Enhancer rebuilds the short-lived lifecycle capability and
requires the reviewed public identity to remain unchanged before applying it.
Only a verified effect becomes `applied`; stale, denied, stopped, timed-out,
failed, or uncertain outcomes remain explicit.

## Safety boundaries retained

- No controller route can approve or directly apply the proposal.
- File move/removal is bound to the caller-observed SHA-256 revision.
- Moves never overwrite; removal is never permanent.
- Altered idempotent replay and request-id reuse across proposal lanes fail.
- Proposal paths, approval data, and live tool events are not retained in
  durable conversation history.
- The implementation starts no model, shell, terminal, provider client, or
  child process.

## Contract changes

- Agent orchestration advances to `local-agent-orchestration.v14`: 61 Agent
  routes plus five runtime routes.
- Agent MCP advances to `prompt-enhancer-agent-mcp.v18`: 19 default tools.
- OpenAPI, generated TypeScript, strict frontend discovery parsing, endpoint
  self-test, direct-client probe, setup copy, and controller documentation are
  updated to the same exact surface.

## Validation

- Core proposal/controller/MCP/orchestration tests cover approval, denial,
  exact revision, source races, idempotency, malformed receipts, generic-call
  refusal, and no-publication-before-review.
- A real disposable loopback MCP run creates a durable project/chat, publishes
  a reviewed edit/create transaction, submits a reviewed file move through
  `agent_propose_lifecycle`, and reads the verified destination back through
  `agent_workspace` without loading a model or spawning a child process.
- Focused frontend tests cover the strict 66-endpoint manifest, 19-tool MCP
  handshake, connection onboarding copy, and controller route counts.
- The final combined backend gate passed 252 tests; the focused frontend gate
  passed 319 tests. Generated-API drift checking, the production frontend
  build, Python compilation, the repository privacy scan, and `git diff
  --check` also passed.
- The rebuilt loopback app was inspected at 1046 px and 390 px. It reported
  controller contract v14, 61 Agent routes, 19 core tools, and the lifecycle
  tool; neither viewport overflowed, no interactive control was clipped, and
  the browser console was empty.
- The controller workflow Playwright acceptance passed at both 1440 px and
  360 px, including keyboard reachability and the updated tool inventory.
- Runtime cleanup was checked after validation: one hidden Agent desktop
  process tree owns the loopback listener, with zero visible terminal windows,
  zero local-model server processes, and no local-model GPU compute row.

## Remaining owner gates

This checkpoint does not replace the owner walkthrough. The remaining gates
are still the generated artifact/viewer walkthrough and one model-backed turn,
Stop, fictional reviewed file effect, unload, process-exit, and CPU/GPU cleanup
check. No real provider configuration, credential, workspace effect, model, or
microphone access was created automatically here.
