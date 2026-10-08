# Agent checkpoint 08y — chat-bound context truth

Date: 2026-08-28

## Outcome

The Agent window no longer presents the shared runtime's last token measurement
as though it belonged to the selected chat. One strict in-memory receipt now
binds exact chat-template preflight evidence to the session, turn, and model
that produced it. The native runtime card and the `agent_context` MCP tool read
that same receipt.

New, recovered, model-switched, not-yet-preflighted, and preflight-failed chats
remain explicitly unmeasured. Missing evidence is never converted to zero and
never replaced with another request's global runtime measurement.

## Implemented boundary

- Added the strict `agent-session-context.v1` contract.
- Added private, no-store `GET /v1/agent/sessions/{session_id}/context`.
- Advanced controller discovery to `local-agent-orchestration.v7`: 54 Agent
  routes plus five controller runtime routes.
- Advanced the MCP surface to `prompt-enhancer-agent-mcp.v6` and its sanitized
  context view to `agent-mcp-context.v2`.
- Kept runtime-wide context visibly labelled `runtime_global_last_request`.
- Added a separate chat receipt and `selected_chat_context_proven` truth flag
  under the selected chat only.
- Updated the Agent runtime card to show either exact `This chat · turn N`
  evidence, `not measured for this chat`, or `context evidence unavailable`.
- Refreshes that receipt as the selected chat's event cursor advances, so a
  long-running or approval-paused turn can surface preflight evidence before
  the whole turn settles.
- Regenerated the OpenAPI artifact and TypeScript bindings.

The receipt is deliberately not written to the durable history database.
Recovered chats therefore start with
`recovered_without_context_receipt`; stale evidence is not reconstructed or
guessed.

## Correctness cases covered

- new chat has no measurement;
- a compacted request binds the final successful preflight, not its refused
  first attempt;
- an exactly refused request retains the refusal evidence;
- a runtime without an exact input counter binds an explicit unknown receipt;
- a service without preflight remains unmeasured;
- recovery discards old in-memory evidence;
- model switching invalidates the previous receipt;
- the HTTP response is private/no-store and session-exact;
- MCP rejects cross-session context, extra private fields, and inconsistent
  chat binding;
- the browser parser rejects cross-chat, partially bound, extended, and forged
  token evidence;
- the runtime card cannot fall back to global evidence when the selected-chat
  receipt is missing or unavailable.

## Automated verification

- Backend, controller, history, catalog, MCP, real-listener, and OpenAPI slice:
  **149 passed**; one existing Starlette/httpx deprecation warning.
- Frontend contracts, transport, MCP guidance, and runtime-card slice:
  **193 passed**.
- OpenAPI generated-binding drift check: **passed**.
- Production TypeScript/Vite build: **passed**, 537 modules transformed.
- Python compilation and whitespace validation: **passed**.
- The unchanged repository privacy scanner reports exactly one known,
  pre-existing untracked binary: `docs/checkpoint-agent-02-shell.png`. No new
  finding was introduced and no scanner rule or exclusion was changed.
- Protected desktop acceptance: the prior owned window shut down cleanly after
  its native quit confirmation, the GUI entry reopened one window and one
  loopback listener, and the existing browser tab reloaded the rebuilt asset.
- Live recovered-chat acceptance: the card rendered **not measured for this
  chat** and its expanded Context, Evidence, and Admission rows all remained
  chat-specific. The runtime stayed stopped.
- Final ownership check: one listener on 8765; none on 8766 or 4173; the exact
  app tree contained only the GUI host, Python window host, and WebView2; zero
  terminal descendants and zero local-model runtime processes.

## Owner review later

1. Open any new Agent chat and expand **Model & context → Runtime details**.
   It should say **Not measured for this chat**, even if another request was
   measured by the shared runtime.
2. After a real turn reaches preflight, refresh or finish the turn. The card
   should show exact input, limit, available tokens, and **This chat · turn N**.
3. Switch the chat to another served model. The old token figure must disappear
   and the chat must return to unmeasured until its next preflight.
4. A recovered chat must also start unmeasured.

## Deliberate limits

- The runtime-wide snapshot and selected-chat reads are sequential, not one
  database transaction; every nested object is nevertheless identity-checked.
- Exact token use depends on the served runtime's chat-template counter. If it
  is unavailable or fails, the UI and MCP report unknown.
- This checkpoint changes context truth only. It does not load a model, send a
  prompt, alter workspace files through the Agent, or complete the broader
  Agent experience trajectory.
- No commit or push was requested for this checkpoint.
