# Agent checkpoint 09p — externally proposed atomic change sets

Date: 2026-08-28

## Outcome

An external Codex, Claude Code, or other scoped MCP controller can now propose
two to eight exact edits to existing workspace files as one change set. The
native Agent presents one combined review, applies the set through the existing
failure-atomic transaction engine, and returns content-free per-file evidence.

This extends the single-file `agent_propose` path without giving the external
controller approval or direct-apply authority. The strict orchestration
contract is now `local-agent-orchestration.v10`; the MCP discovery contract is
`prompt-enhancer-agent-mcp.v14`; the default surface contains eighteen core
tools, including `agent_propose_transaction`.

## Correctness boundary

- Every member must target an existing file and provide its exact current
  revision and line-ending policy. New-file members, duplicates, stale
  revisions, and sets outside the two-to-eight-file bound fail closed.
- The whole set receives one native approval card and one combined diff. MCP,
  HTTP, and controller clients cannot approve or apply it.
- The reviewed draft is transient. After a potentially long native decision,
  the service rebuilds the preview and requires exact equivalence before it
  applies, avoiding expiry of the short-lived internal capability without
  weakening the review.
- Publication is failure-atomic: a later write failure rolls earlier writes
  back. Unconfirmed rollback becomes `unverified`, never success.
- Stop, denial, timeout, stale state, cleanup failure, replay with changed
  content, and cross-kind request-id reuse all settle without partial apply.
- Exact idempotent replay returns the same settled receipt. The retained
  proposal record stores hashes and bounded metadata, never proposed content,
  diffs, approval decisions, paths, or reusable apply capability.
- Model-generated multi-file batches use the same preview-rebuild rule, fixing
  the prior mismatch between the preview TTL and native approval timeout.

## Verification

- Focused transaction/service regressions: **31 passed**.
- Controller, orchestration, MCP surface, HTTP, and OpenAPI suite: **167
  passed**.
- Direct HTTP/MCP integration, packaging, live probe, and CLI suite: **27
  passed**.
- Focused Agent UI and contract suite: **306 passed** across six files.
- Production TypeScript/Vite build passed with **544 transformed modules**;
  generated OpenAPI drift check and Python bytecode compilation passed.
- Repository privacy/secret scan passed. `git diff --check` reported no patch
  errors; the repository still emits its existing Windows line-ending notices.
- Negative coverage includes denial, Stop, stale revisions, expired preview
  rebuild, missing files, changed idempotent replay, injected mid-transaction
  failure with rollback, and exclusion of proposal content from durable
  history.
- The live reload initially exposed an old-backend/new-frontend contract
  mismatch. A normal window-close request did not settle the stale owner within
  the bounded 20-second wait, so the two exact, previously inventoried old
  `pythonw` processes were stopped and one console-free owner was relaunched.
  The Agent Connections card then reported **Ready**, orchestration v10, 58
  Agent routes, 5 runtime routes, 10 native review gates, and 18 core MCP tools.
- Final runtime checks found one loopback-only listener on
  `127.0.0.1:8765`, two expected console-free `pythonw` owner/launcher
  processes, no non-loopback port-8765 listener, and no `llama-server` process.

## Remaining owner acceptance

Use the owned native Agent window to create a scoped direct connection. From a
real external client, open a synthetic workspace chat and propose two benign
edits to existing synthetic files. Confirm that exactly one native review is
shown, deny once, retry with a new request id, approve once, verify both files,
then revoke the connection. The broader real-model turn/Stop/context/artifact
and model-unload walkthrough remains separately owner-gated.

## Agent-09q close-baseline addendum

The bounded close observation was reproduced with the exact native window. The
owner was waiting at pywebview's intentional **Do you really want to quit?**
confirmation because `confirm_close=True`; cleanup had not yet been asked to
run. Accepting that confirmation released the native window in 0.52 seconds,
released the listener, and left no `pythonw` or `llama-server` process. No
cleanup change was needed, and the safety confirmation remains enabled.
