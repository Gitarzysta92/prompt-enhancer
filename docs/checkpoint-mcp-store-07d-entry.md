# Checkpoint Store-07d entry

Status: implementation active
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Previous evidence: [Store-07c handoff](checkpoint-mcp-store-07c-handoff.md)

## Frozen user outcome

An MCP server cannot exhaust the application with a schema or result bomb,
confuse one tool for another, smuggle malformed arguments, replay approval or
retain authority after Stop. Every admitted call is bound to the exact reviewed
project, host instance, tool contract, arguments and one-use approval; failures
remain bounded and content-free.

## Evidence at entry

- Store-06 already has project-bound tool snapshots, schema and argument
  validation, per-call native approval, bounded result projection and durable
  content-free receipts.
- Store-07b closes remote transport authority on timeout, cancellation and
  oversized streams.
- Store-07c closes local process authority on output flood, visible-window
  policy failure, lifecycle races and unverified cleanup.
- This packet attacks the tool boundary itself. Existing happy-path validation
  is evidence to preserve, not proof against recursive or ambiguous hostility.

## In scope

1. Freeze finite tool-discovery budgets for aggregate bytes, tool count, name
   length, description length, schema bytes, depth, nodes, properties, branches,
   enums and regular-expression complexity where supported.
2. Define and enforce the accepted JSON Schema subset. Reject recursive or
   unresolved references, cycles, contradictory shapes and unsupported
   validators rather than partially interpreting them.
3. Canonicalize tool identity once and reject duplicate, case-folded, Unicode,
   separator, reserved-name or projected-alias collisions before any tool is
   exposed to a model.
4. Validate detached JSON arguments against the exact reviewed input-schema
   digest with finite depth, items and bytes. Reject non-JSON, non-finite,
   duplicate/unknown or schema-invalid data before approval and again before
   dispatch where authority may have changed.
5. Bind every approval to the exact project, chat/turn, management plan, live
   host instance, tool name, schema snapshot and argument digest. Make it
   expiring, one-use and atomically settled across concurrent callers.
6. Recheck installation revision, project admission, tool selection, host
   health and cleanup state immediately before dispatch. Stop, revocation or
   contract drift invalidates pending authority.
7. Bound result framing, aggregate bytes, nesting, item count, text, structured
   content, links and errors. Refuse malformed, contradictory, unsupported or
   partial results without retaining raw payloads.
8. Make timeout, cancellation, duplicate terminal messages and late result
   delivery settle once. A refused or stopped call cannot later become success.
9. Keep API, receipts, logs and Agent cards content-free on hostile failures;
   expose only allowlisted recovery categories and preserve keyboard-reachable
   review/Stop paths.

## Explicit exclusions

- Registry presentation, remote network policy and local process containment
  are closed in Store-07a through 07c and remain regression gates.
- Vault plaintext, log/database canaries and cross-project/chat/client isolation
  belong to Store-07e, except where exact scope binding is necessary to prove
  one-call approval non-replay.
- No real MCP package, private workspace, credential, model or protected call is
  authorized. All adversarial peers and payloads are synthetic and inert.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Recursive/deep/wide schema | Rejected within finite byte/depth/node/time budgets; no partial tool exposure. |
| Duplicate or confusable names | Entire ambiguous contract fails closed; no alias silently wins. |
| Malformed/oversized arguments | Rejected before approval/dispatch with no raw value in receipt or UI. |
| Contract or authority drift | Pending approval becomes unusable; no call reaches the server. |
| Concurrent approval replay | Exactly one caller may settle the exact approval; every replay is refused. |
| Malformed/oversized result | Exact call closes as bounded safe failure; no raw payload is retained. |
| Timeout/Stop/late result | One terminal state; late success cannot replace cancellation or revocation. |
| UI/API privacy | Only allowlisted category and recovery action render; synthetic canaries remain absent. |
| Regression | Store-06 behavior plus Store-07a/b/c transport/process gates remain green. |

## Expected touched surfaces

- tool contract review, canonicalization, schema complexity and projection;
- argument validation, approval binding/settlement and pre-dispatch revalidation;
- result framing/projection, call state machine and content-free receipts;
- safe HTTP/frontend error contracts and Agent tool activity cards;
- synthetic schema, alias, argument, result, replay, timeout and Stop fixtures;
- Store-07d handoff and the master milestone board.
