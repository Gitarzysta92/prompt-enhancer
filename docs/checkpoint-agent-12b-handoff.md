# Agent checkpoint 12b handoff

## Outcome

The Agent conversation now reconciles event-stream pages and command responses
as one monotonic state machine. A page with an older event head cannot rewind a
newer turn, and a page captured at the same head before a Stop request cannot
clear the newer Stop acknowledgement.

Live recovery is also bounded by actual progress. A duplicate running snapshot
no longer resets the consecutive-failure counter, so a stream that repeatedly
reconnects, reports no new event or state, and disconnects reaches the existing
five-failure circuit breaker instead of retrying forever. A fresh event, a
forward state transition, or a clean terminal stream resets recovery. An
unexpected clean EOF while the reconciled turn is still running is treated as
a failure rather than success.

Partial streamed output survives a disconnect. The next connection starts at
the exact accepted event cursor, and a late terminal assistant event removes
the matching deltas and renders one final response.

## Correctness boundaries

- The strict transport contract still rejects foreign sessions, replayed or
  unordered event sequences, invalid event shapes, and forged stream states.
- Event sequence is the primary ordering boundary. Closing and cleanup
  quarantine remain latched even when reported by an older page.
- At an equal event head, settled state cannot be reopened. While a turn is
  running, Stop and pending-approval state can advance but cannot be cleared by
  an older same-head snapshot. A terminal `running: false` snapshot remains an
  allowed forward settlement.
- Newer event heads may replace running, stopping and pending-approval state;
  lower heads may not.
- Recovery failures are consecutive stalled failures, not a lifetime count.
  Real event/state progress begins a new outage budget.
- A clean terminal connection clears an earlier reconnect notice. EOF during a
  running turn increments the same bounded failure budget as an exception.
- The manual **Retry live updates** action creates a fresh recovery budget after
  the automatic circuit breaker pauses.
- Stream reconciliation changes no retained history, workspace effects,
  approvals, model lifecycle or MCP authority.

## Validation

- New regression matrix: **4 tests passed**, covering an equal-head pre-Stop
  snapshot, repeated duplicate running snapshots, unexpected running-turn EOF,
  and a late terminal reply after exact-cursor reconnect.
- Full Agent page suite: **144 tests passed**.
- Strict event-contract and HTTP transport suites: **185 tests passed**.
- Full Agent UI and shared Agent contract gate: **46 files, 695 tests passed**.
- Backend stream and Stop boundary selection: **9 tests passed**, including
  closing/stopping non-terminal states, cleanup quarantine, stream cancellation
  and history integrity.
- Production TypeScript/Vite build passed with **559 transformed modules**.
  The existing approximately 519 kB Agent-page chunk warning remains tracked
  performance debt.
- Targeted diff whitespace validation passed apart from the repository's
  existing Windows line-ending notices.
- The protected loopback app reloaded at `/agent`; the durable project/chat
  rail, retained conversation and Model & context control rendered, and browser
  logs were empty. No retained chat was mutated for this smoke test.
- Listener census showed only `127.0.0.1:8765` on the application ports and no
  known local-model process. This checkpoint started no model, GPU workload,
  command worker or MCP host.

## Owner review

Use a disposable chat with a deliberately slow local-model response:

1. Send a request, type the next draft while output is streaming, then choose
   **Stop response**. Confirm **Stopping…** cannot revert to **Stop response**
   before the worker actually settles, and the next draft remains intact.
2. Briefly interrupt only the loopback connection while a response is active,
   then restore it. Confirm partial text is not duplicated and the final reply
   replaces the streaming bubble once.
3. If the service remains unavailable, confirm retries pause after repeated
   failures and **Retry live updates** is available; confirm no terminal windows
   appear.
4. Restore the service and retry. Confirm the reconnect warning clears after
   new activity or terminal settlement and the chat remains usable.
5. Confirm Stop affects the response only: the selected model remains loaded
   until its separate model-stop control is used.

## Next slice

Agent-12c will finish truthful context evidence and budget presentation: exact,
estimated and unknown usage must remain visually distinct; model/context
changes must invalidate stale evidence; warning thresholds must be accessible;
and no missing tokenizer or runtime usage may be displayed as zero.

Store-06b persistent MCP hosting remains separately frozen pending explicit
owner approval.
