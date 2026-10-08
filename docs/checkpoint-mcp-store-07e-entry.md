# Checkpoint Store-07e entry

Status: automated implementation complete; owner protected-action review pending
Entered: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)
Previous evidence: [Store-07d handoff](checkpoint-mcp-store-07d-handoff.md)
Completion evidence: [Store-07e handoff](checkpoint-mcp-store-07e-handoff.md)

## Frozen user outcome

MCP configuration values, derived secret-bearing data and per-call authority
remain inside their exact reviewed scope. Stale, missing, replaced or revoked
vault references fail closed. A different project, chat, client, process or app
run cannot observe or spend another scope's value, host, approval, result or
receipt, and hostile failures leave only bounded content-free evidence.

## Evidence at entry

- Store-06d keeps configured values behind vault references and resolves them
  only at the protected lifecycle boundary.
- Store-07a through 07c close hostile registry, remote transport and local
  process behavior.
- Store-07d closes schema, identity, argument, one-use approval and result
  boundaries.
- This packet attacks confidentiality and scope separation. Existing redaction
  and happy-path project binding remain regression evidence, not proof against
  stale references, concurrency or cross-scope substitution.

## In scope

1. Plant reserved synthetic canaries in configuration values, arguments,
   results, transport failures and lifecycle faults; prove they remain absent
   from ordinary SQLite state, logs, diagnostics, HTTP errors, retained Agent
   history, exports and rendered UI.
2. Exercise missing, invalid, expired, rotated, replaced, revoked and wrong-plan
   vault references. Re-resolution must bind to the exact reviewed project,
   server revision, field identity and lifecycle operation; no stale plaintext
   fallback is permitted.
3. Verify project and chat isolation for plans, configuration readiness, tool
   admission, running hosts, approvals, calls, receipts and retained activity.
   Guessing or substituting another scope's identifiers must return a bounded
   not-found/conflict result without confirming whether private state exists.
4. Verify independent controller/client identity. Concurrent clients may
   observe only their allowed projections and cannot settle, cancel, Stop,
   resume or reuse another client's in-flight authority.
5. Race revocation, project/chat switches, configuration replacement, host Stop,
   app shutdown and restart against preparation, approval, dispatch and receipt
   persistence. The most restrictive valid state wins and cannot be reversed by
   a late completion.
6. Reconcile restart state without restoring plaintext, live host authority,
   pending approvals, raw arguments/results or reusable mutation permission.
   Unknown cleanup remains an explicit block.
7. Keep server, API and UI errors content-free and allowlisted while preserving
   a useful fixed recovery action for the owner.
8. Preserve every Store-06 and Store-07a-d regression gate plus privacy scans,
   migration support and one-loopback-process ownership.

## Explicit exclusions

- No real credential, provider configuration, credential file, private session,
  workspace content or unrelated home-directory data may be read.
- No real MCP package/host, model, GPU workload, remote secret service or
  protected action is authorized. All values and competing clients are
  synthetic and inert.
- Physical native-confirmation, packaged-app and trusted-server checks remain
  Acceptance-01/Release-01b evidence.
- General route/control design cleanup and performance work remain Sweep-01.

## Acceptance matrix

| Case | Required result |
| --- | --- |
| Secret canary in any hostile path | Absent from database, logs, diagnostics, HTTP, retained history, export and UI. |
| Missing/stale/revoked vault reference | Exact operation fails closed; no fallback value or partial start. |
| Wrong project or chat identifier | No private existence oracle, state projection, authority or receipt crosses scope. |
| Concurrent independent clients | One client cannot approve, Stop, resume or spend another client's operation. |
| Revocation/switch/Stop race | Restrictive state wins once; late success cannot restore authority. |
| Restart | No plaintext, live host, pending approval, raw payload or reusable permission is resurrected. |
| Recovery UI | Fixed, content-free and keyboard reachable; no synthetic canary renders. |
| Regression | Store-06 plus Store-07a-d, migrations, API/build/privacy and live census remain green. |

## Expected touched surfaces

- vault-reference identity, resolution, invalidation and restart reconciliation;
- project/chat/client scope checks across management, runtime, call and receipt
  repositories;
- content-free logging, HTTP projections, retained history and export filters;
- concurrent revocation/settlement/Stop state machines;
- synthetic secret and cross-scope adversarial fixtures;
- Store-07e handoff, owner ledger and master milestone board.
