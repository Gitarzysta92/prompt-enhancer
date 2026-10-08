# Checkpoint Release-01a.2b entry: restart reconciliation

Date: 2026-09-01

This checkpoint closes crash windows in durable work without retaining private
content or inventing success. Tests use only synthetic repositories, paths,
identities, model bytes, sessions, and tool calls.

## Frozen restart contract

| System | Durable evidence observed after restart | Required projection | Forbidden projection |
| --- | --- | --- | --- |
| Local-model download | Transient ledger row plus an exact registry record and an exact verified final artifact | `completed`; preserve the reviewed immutable provenance and record one ledger revision | `interrupted`, a second transfer, or deletion of the verified artifact |
| Local-model download | Transient ledger row without that exact registry binding | `interrupted`; retain only a bounded owned partial when present | `completed` or automatic registration |
| Local-model download | Transient ledger row conflicts with an existing alias or published bytes | `failed` with `download_registry_conflict`; leave the conflicting record and bytes untouched for explicit owner recovery | `completed`, overwrite, or cleanup of data not proven to belong to the interrupted job |
| Local-model cancellation | `cancelling` ledger row | Clean only the immutable job-owned directory; settle `cancelled` only after cleanup is confirmed, otherwise `failed` | Silent cleanup claims or broad deletion |
| Reviewed artifact projection | Source history contains a verified write receipt but the SQLite projection transaction was interrupted | Roll back the incomplete transaction; replay the source receipt idempotently on the next artifact read | A partial head/version pair or a claim that the artifact exists without both rows |
| MCP package lifecycle | `installing`, `reserved`, or `prepared` durable operation | Existing startup reconciliation moves it to `cleanup_required` with fixed content-free interruption evidence | `installed`, `updated`, `uninstalled`, or verified cleanup without evidence |
| MCP managed tool call | A prior app run has a one-use claim but no terminal receipt | Write one content-free terminal receipt. Approved calls become `failed` / `mcp_tool_call_interrupted` with cleanup unverified; non-approved calls preserve their already-decided denial, timeout, or cancellation outcome | `succeeded`, replayable approval, retained arguments/results, or a pending live call |
| Controller ownership | Durable ownership has no matching live local session in the new app run | Active/submission states become `submission_uncertain`; stop/cleanup states become `cleanup_unconfirmed`; clear approval and handoff authority | `running`, `waiting_native_approval`, inherited approval, or a transferable live handoff |
| Controller ownership | Durable ownership has an exact matching live local session | Preserve its current state for the current process composition | Guessing liveness from a catalog row alone |

## Evidence and privacy rules

- Reconciliation may persist fixed identifiers, state classes, revisions, counts,
  digests, byte counts, timestamps, and fixed error codes only.
- It may not persist or log prompts, responses, MCP arguments/results, file
  contents, credentials, absolute workspace paths, or provider transcript data.
- Every reconciler is idempotent: a second startup makes no additional state
  change once the first reconciliation is terminal.
- No reconciler starts a model, host, command, network request, or tool call.
- Objective file/digest and transaction evidence outranks a previous process's
  completion claim.

## Required synthetic interruption tests

1. Model crash after registry publication but before ledger completion.
2. Model registry/final-artifact conflicts that fail closed without deletion.
3. Artifact faults at each SQLite head/version transaction boundary followed by
   restart replay from the reviewed source event.
4. MCP package-operation startup matrix plus prior-run orphaned call claims.
5. Controller startup matrix for live and non-live sessions, including pending
   approval and handoff removal.
6. Repeat every reconciler to prove idempotency and run content-field/schema
   privacy assertions over its durable evidence.
