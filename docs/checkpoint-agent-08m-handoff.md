# Agent checkpoint 08m handoff: safe external runtime coordination

> Historical contract note (2026-08-28): checkpoint 09g advances the lower-level
> controller CLI to v5 by adding a dedicated exact-revision, live-only `close`
> command. The v4 evidence below remains the record of checkpoint 08m.

Date: 2026-08-27
State: implementation and synthetic validation complete; native/model owner acceptance remains pending

## Outcome

Agent-08m closes the model-lifecycle gap between the provider-neutral Agent
controller and the durable project/chat flow. A Codex, Claude Code, or other
local orchestrator no longer has to improvise a runtime status read, revision,
switch or stop body, response validation, and ambiguity recovery before using
`open`, `turn`, and `wait`.

The stdio bridge contract is now
`prompt-enhancer-agent-controller-cli.v4`. Its typed `runtime` action accepts:

- `desired_state: ready` with one registered alias and optional exact
  `cpu`, `gpu`, or `split` placement, GPU-layer count, and context size; or
- `desired_state: stopped` with one exact alias and no activation settings.

For either path the client:

1. validates the complete v6 orchestration manifest;
2. reads and validates the v2 global runtime coordinator;
3. returns immediately when the requested state is already proven;
4. blocks on cleanup uncertainty and refuses to stop a different selected
   alias;
5. submits at most one mutation bound to the observed coordinator revision;
6. validates exact requested/served placement or clean idle/process-exit
   evidence; and
7. after a lost or malformed mutation response, reads status once without
   repeating the mutation.

Closed outcomes distinguish `ready`, `ready_reconciled`, `stopped`,
`stopped_reconciled`, `activation_uncertain`, `stop_uncertain`, and
`cleanup_unconfirmed`. Generic `invoke` now refuses raw switch and stop so the
stdio path cannot bypass these invariants. The command requires both the
existing sensitive-context acknowledgement and a separate
`--acknowledge-model-lifecycle` flag before stdin is read.

The bridge still owns and spawns no process. It never starts Prompt Enhancer,
Codex, Claude, another agent, or a terminal. The explicit runtime action can
ask the already-running application to manage its one owned model. Native file
applies, approvals, recovered authority, and manual artifact capture remain
unavailable to token-authenticated controllers.

## Recommended external-agent sequence

1. `discover` the content-free contract.
2. `runtime` the selected alias and placement to `ready`.
3. `open` one durable project and live chat.
4. Use bounded `turn`, native review when requested, and cursor-based `wait`.
5. Close or retain the chat intentionally.
6. `runtime` that exact alias to `stopped` and require a clean idle receipt.

## Verification receipts

- Focused controller client and stdio CLI gate: **47 passed**.
- Focused Controller card gate: **5 passed**.
- Controller, orchestration, runtime lifecycle, request cancellation, and
  release regression group: **167 passed**.
- Focused Agent/controller frontend gate: **114 passed across 4 files**.
- Complete populated-workflow Chromium gate: **66 passed** at 360 px and
  1,440 px.
- Generated OpenAPI/TypeScript parity: passed.
- Production TypeScript/Vite build: **533 modules transformed**.
- Python source and test compilation: passed.
- `git diff --check`: passed.
- Ports 8765 and 8766 had no listeners, and no `llama-server` process remained
  after validation.

All fixtures are fictional and local. Runtime ownership tests used only their
synthetic stub process and verified shutdown. This checkpoint did not launch
Prompt Enhancer, a visible terminal, a real local model, or a GPU workload.

The unchanged privacy scanner still reports exactly one known pre-existing
finding: the untracked binary screenshot
`docs/checkpoint-agent-02-shell.png`. Agent-08m introduced no new privacy
finding, and no scanner rule or exclusion was weakened.

## Remaining owner gate

The guarded real-runtime acceptance remains separate: reload the application,
prepare a registered model through the selected CPU/GPU placement, open and
refocus the dedicated Agent window, complete one streamed turn and one Stop,
review one file and artifact, then unload and verify process/GPU cleanup. No
automated receipt substitutes for that native owner observation.
