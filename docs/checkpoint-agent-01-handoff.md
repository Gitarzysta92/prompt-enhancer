# Agent-01 handoff: durable Agent project and session catalog

Date: 2026-08-27
Status: scoped implementation and bounded automated verification complete; visual rail review belongs to Agent-02

## Outcome

The local Agent now has a private, versioned database hierarchy for
owner-authored projects and session navigation metadata. Projects and session
stubs survive a backend/app restart. They can be created, listed, searched,
renamed, pinned, archived, restored, moved between projects and safely deleted
through strict loopback contracts.

This checkpoint does **not** claim that conversation history survives restart.
Message text, event streams, tool activity, approvals and workspace capability
remain in memory. A session stub always reports `history_state=memory_only` and
separately reports whether its live in-memory conversation is currently
available. After restart that value is false; no empty or successful
conversation is invented.

## Implementation boundary

- `agent-catalog.sqlite3` is separate from imported provider analytics. It
  contains only authored project/session navigation metadata and is excluded
  from export and current backup flows.
- The fixed-name SQLite boundary refuses links/reparse components, uses a
  dedicated migration ledger, rejects a newer schema, enables foreign keys,
  WAL, full synchronous durability and bounded waits, and closes every
  connection.
- Projects have optimistic revisions, deterministic ordering, a single guarded
  default project and derived session counts. The default cannot be archived or
  deleted, and any non-empty project must be emptied deliberately before
  deletion.
- Session metadata writes are revision-bound. A metadata record cannot be
  hard-deleted while its live conversation exists. Closing the live session
  removes only runtime state; the restart-safe metadata stub remains until the
  owner deliberately deletes it.
- Live session creation now resolves an explicit project or the single default
  project and returns that project identifier in `AgentSettings`.
- The shared Agent response contract moved from `local-agent.v6` to
  `local-agent.v8` because the exact settings shape gained `project_id`.
- Project and catalog routes are private/no-store. The frontend requires those
  headers and exact `agent-catalog.v2` payloads, validates identifier binding,
  timestamps, bounds and duplicate IDs, and preserves only fixed failure codes.

## Correctness repair found by testing

A repeated two-instance test found that two connections could race while each
attempted to enable SQLite WAL before normal operations. WAL setup now happens
once during database initialization, before concurrent repository operations;
the busy timeout is installed before lock-sensitive setup. Eight consecutive
fresh-database two-instance races then produced exactly one default project in
each database.

The catalog also prevents archiving the default project. Without that guard,
future default-session creation could resolve an archived project and fail in a
confusing loop.

## Verification receipts

- 7 focused catalog tests pass, including restart truth, HTTP integration,
  optimistic conflicts, guarded deletion, newer-schema refusal, connection
  closure, UTC ordering and eight repeated two-instance races.
- 130 Agent, completion, usage, turn-detail, OpenAPI and API/CLI regression
  tests pass after the migration and concurrency repairs.
- 1,897 frontend tests across 136 files pass, including 170 strict catalog and
  HTTP transport cases.
- 31 focused privacy tests and 45 Windows distribution/path-inventory tests
  pass.
- The production TypeScript/Vite build, Python compilation, generated OpenAPI
  parity and scoped whitespace checks pass.
- A complete Python run was sampled through roughly 4% with no failure, then
  intentionally stopped because its projected duration was outside this
  bounded checkpoint. This is not reported as a complete-suite receipt.

All fixtures use fictional projects, paths, identifiers and chats. No provider
session, credential, owner workspace, prompt or model output was read. No
network model was consulted. No native app, terminal window or model runtime
was launched.

## Capability status after Agent-01

| Capability | Status after this checkpoint |
| --- | --- |
| Create/browse/switch/close chats | Live behavior remains implemented; durable navigation backend exists, rail UI pending |
| Durable Agent projects | Backend/database and contracts implemented; UI pending |
| Chats surviving app restart | Metadata stub only; conversation history explicitly not implemented |
| Rename/search/pin/archive/restore | Backend/database and transport implemented; UI pending |
| Project/session database hierarchy | Implemented for navigation metadata |
| Text chat, streaming, Stop, workspace review and approvals | Existing behavior preserved; still memory-only |
| Reasoning/tool presentation, rich rendering, artifacts, multimodal, model switching/context and branching/export | Later checkpoints |

## Next checkpoint

Agent-02 mounts this real hierarchy into a chat-first left rail, extracts the
current page orchestration into bounded controllers, and keeps the dominant
chat/composer visible. Metadata-only stubs must remain visibly unavailable;
selecting one may show its truthful restart state but cannot silently create a
new conversation or imply restored messages.

The Agent-00 native open/focus/close checklist remains deferred until the owner
has time. Agent-02 implementation may proceed without a native launch, but its
final owner-visible gate cannot claim Agent-00 passed.
