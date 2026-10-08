# Orchestration-01b readiness contract

Status: automated implementation complete; owner external-client walkthrough remains

## User-visible outcome

One project-scoped external Codex, Claude Code or provider-neutral connection can
own one exact live Agent chat operation. Prompt Enhancer shows who owns it and
whether it is starting, running, waiting for native approval, reconnecting,
stopping, uncertain or cleanup-blocked. Another connection cannot silently
observe, Stop or continue that operation. The owner can offer an exact handoff;
only the named active target can accept it, and no native approval authority is
transferred.

## Frozen ownership contract

- Ownership identity is the durable connection ID plus exact project ID and chat
  session ID. A client label is display metadata, never authority.
- The durable catalog stores at most one active ownership row per chat. Claim is
  atomic and independently revalidates that the connection is active, project-
  bound and that the chat belongs to the same project.
- Ownership phases are `claimed`, `running`, `waiting_native_approval`,
  `reconnecting`, `submission_uncertain`, `stopping`, `stop_uncertain`,
  `cleanup_unconfirmed` and `revoked`.
- Cursor, last observed sequence, approval-pending truth, owner-since time and a
  monotonic ownership revision are stored without message, prompt, tool argument,
  workspace path or event content.
- `agent_turn` and the three reviewed proposal tools claim automatically.
  `agent_wait` and `agent_stop` require the same current owner. Terminal evidence
  releases ownership; incomplete, approval and uncertain outcomes retain it for
  safe reconnect.
- Same-connection reconnect uses the durable connection identity after token
  rotation and resumes from the caller's explicit cursor. A stale or revoked
  credential still fails authentication before ownership is consulted.
- Handoff is two-party and revision-bound: the current owner offers to one exact
  active connection on the same project; only that target can accept before the
  bounded expiry. Accept changes the owner atomically and clears the offer.
- Handoff transfers observation and Stop coordination only. File, command, web,
  model, MCP and native approval authority are neither copied nor remembered.
- Revocation marks retained ownership `revoked` instead of pretending the live
  turn stopped. The native UI can Stop the chat and then perform a native-
  confirmed release; the backend independently verifies the live session is
  absent or settled and cleanup-confirmed.
- Restart retains the content-free ownership record. If no live session remains,
  native reconciliation can release it before a retained-history resume.

## Surface and interface contract

- The project-scoped direct MCP surface replaces no existing tool and adds one
  typed `agent_control` tool for status, handoff offer/accept and safe release.
  The unscoped local stdio surface keeps generic invocation and has no connection
  ownership identity.
- The controller discovery protocol declares exact ownership, reconnect and
  handoff semantics. Direct HTTP advertises 19 project-scoped tools, or 20 when
  explicit model lifecycle control is granted.
- Agent settings shows every active ownership under its owning connection with
  chat, phase, cursor/sequence, owner time, handoff target/expiry and recovery
  guidance. It never renders message or workspace content in that card.
- Connection list, direct MCP status and native release use the same strict
  ownership projection. Contradictory project/chat/owner/state fields fail
  closed in Python and TypeScript.

## Deliberately excluded

- A connection does not gain the ability to approve its own protected action.
- Handoff does not move a chat between projects, copy a chat, fork retained
  history or migrate a model runtime. Existing exact resume/fork/runtime tools
  remain separate operations.
- No remote listener, broker, bridge process, terminal or provider credential
  store is added.
- Raw transcripts, prompts, tool arguments/results and workspace paths are not
  stored in ownership records or activity diagnostics.

## Acceptance matrix

1. Two connections bound to one project race to claim one chat; exactly one wins
   and the loser receives a content-free ownership conflict.
2. Connections bound to different projects cannot query, claim, Stop, release or
   receive a handoff for the other project's chat.
3. The same connection can resume observation after a transport interruption or
   token rotation; stale credentials remain rejected.
4. A pending native approval remains pending across reconnect and handoff, and
   neither owner can approve it through MCP.
5. Offer/accept rejects self-target, inactive target, cross-project target,
   wrong owner, wrong target, stale revision and expired offer.
6. Stop is sent at most once, only by the owner; terminal evidence releases the
   row while uncertainty and cleanup failure remain visible.
7. Revocation blocks new authenticated calls immediately, retains truthful
   orphan status and permits native release only after objective settled-state
   verification.
8. Schema-v23 migration creates the v24 ownership table without inventing an
   owner for legacy connections or chats; restart preserves valid records.
9. Strict backend, OpenAPI and frontend parsers reject extra, missing and
   contradictory ownership fields.
10. Desktop and 360-pixel browser fixtures show ownership, handoff and recovery
    states with keyboard-reachable controls and no crowding of the conversation.
11. Production build, privacy scan, one hidden reload, one loopback listener,
    zero model/MCP workers and zero browser console errors close the checkpoint.

No commit, push, real provider connection or model load is authorized by this
readiness contract.
