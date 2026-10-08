# Agent checkpoint 08j handoff: truthful direct event streaming

Date: 2026-08-27
State: implementation and synthetic validation complete; native owner acceptance remains pending

## Outcome

Agent-08j fixes a remaining mismatch between the private direct SSE endpoint
and the `local-agent-orchestration.v6` terminal contract. The relay previously
ended whenever a page was not running, had no pending approval, and its cursor
reached `last_seq`. That older condition ignored `closing`, `stopping`, and
cleanup quarantine, so stream closure could be mistaken for a settled turn.

The relay now has two explicit terminal outcomes:

- settled only when running, closing, stopping, and cleanup quarantine are all
  false, no approval is pending, and the cursor has fully drained `last_seq`;
- cleanup quarantine when `cleanup_unconfirmed` is true.

In both cases the exact final `AgentEvents` JSON page is emitted before EOF,
including when the controller connected with a cursor already at `last_seq`.
While a session is closing or stopping, the relay remains open and continues
waiting. EOF without a validated final page is not a success receipt.

The content-free orchestration manifest now states that behavior in the
`stream_events` endpoint purpose. No route, authentication boundary, native
approval rule, model lifecycle, or workspace authority changed.

## Verification receipts

- Focused closing/stopping/quarantine stream tests: **4 passed**.
- Agent session, command, controller, orchestration, and release regression
  group, including OpenAPI parity: **107 passed**.
- Frontend event transport and orchestration-contract gate: **179 passed across
  3 files**.
- Python source and test compilation: passed.
- `git diff --check`: passed; Windows line-ending notices only.
- Ports 8765 and 8766 had no listeners after validation.

All validation used fictional in-process fixtures. This checkpoint did not
launch Prompt Enhancer, a visible terminal, a local model, or a GPU workload.

The repository privacy scan still reports only the previously known untracked
binary screenshot `docs/checkpoint-agent-02-shell.png`; Agent-08j introduced no
new privacy finding.

## Remaining owner gate

The native acceptance remains intentionally separate. One controlled local
model run must still verify streaming, Stop, a protected write and native
decision, controller `wait` continuation, artifact review, model unload,
process exit, and CPU/GPU cleanup on the owner's Windows composition.
