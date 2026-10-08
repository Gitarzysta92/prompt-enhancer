# Checkpoint Sweep-01c.2 entry

Status: automated and rebuilt-browser complete; owner review queued
Entered: 2026-09-01
Parent: [Sweep-01c entry](checkpoint-sweep-01c-entry.md)
Prerequisite: [Sweep-01c.1 handoff](checkpoint-sweep-01c-1-handoff.md)

## User-visible outcome

Agent projects, chats and artifacts remain browseable past the old 200-record
response boundary. Loading another server page never changes the selected
project/chat, silently accepts a reordered collection or claims that a partial
collection is complete.

## Frozen page contract

- New page responses use `agent-catalog-page.v1` or
  `agent-artifact-page.v1`; the existing list endpoints and record contracts
  remain compatible.
- A page contains a 64-character SHA-256 snapshot, requested `limit` and
  `offset`, exact `total`, coherent `next_offset`/`complete` fields and at most
  100 records.
- Offset zero may establish a snapshot. Every positive offset requires the
  exact snapshot returned by the first page.
- The snapshot binds the normalized search, archived-state filter, project or
  artifact view and the complete stable ordered record heads. Reusing it for a
  different scope or after any relevant mutation returns a content-free 409
  conflict.
- The SQLite adapter reads the complete bounded matching collection, computes
  the snapshot and slices the returned page inside one read transaction.
  Storage remains capped at 200 projects, 2,000 chats and 500 artifacts.
- Duplicate identifiers, incomplete non-final pages, invalid totals, replayed
  scope, out-of-range offsets and stale or out-of-order UI responses fail
  closed.
- The browser keeps already loaded records visible while a later page loads,
  exposes exact loaded/total coverage and provides an explicit restart action
  after snapshot conflict.

## Safety and evidence boundary

- Tests use only fictional names, reserved identifiers and synthetic relative
  paths. No provider cache, real transcript, workspace content or credential
  is read.
- Paging performs metadata-only reads. It starts no model, command, MCP host or
  protected action.
- Existing render budgets from Sweep-01c.1 remain independent of server page
  size and stay enforced after pages are appended.

## Exit gate

- Backend service, SQLite and HTTP tests cover maximum collections, exact
  order, restart, mutation conflicts, cross-scope replay and out-of-range
  requests.
- Strict frontend parsers and components cover duplicate pages, delayed or
  aborted requests, query resets, conflicts and preserved selection.
- Full backend/frontend, rendered 360/1440 px, production build, API/privacy
  and rebuilt loopback app gates pass with a zero-model process census.

Closed by: [Sweep-01c.2 handoff](checkpoint-sweep-01c-2-handoff.md)
