# Agent checkpoint 09q — mixed create/edit atomic change sets

Date: 2026-08-28

## Outcome

The Agent transaction boundary now supports explicit mixtures of new-file
creation and exact edits to existing files in one reviewed change set. Both an
external scoped controller and consecutive model-generated `write_file` calls
use the same two-to-eight-file, one-review, failure-atomic path.

The strict workspace transaction contract is now
`local-agent-workspace-transaction.v2`; the orchestration contract is
`local-agent-orchestration.v11`; and the MCP discovery contract is
`prompt-enhancer-agent-mcp.v15`. The Agent surface still exposes 58 Agent
routes, 5 runtime routes, 10 native review gates, and 18 core MCP tools.

## Correctness boundary

- Every member declares `create` or `edit`; the operation cannot silently
  change while a proposal is pending.
- An edit requires the exact current revision, identity, byte count, digest,
  and line-ending policy. A create requires the target to remain absent from
  preview through publication.
- The complete two-to-eight-file set receives one native review card and one
  combined diff. MCP, HTTP, and model output cannot approve or directly apply
  the transaction.
- After approval, the preview is rebuilt and must be byte-for-byte equivalent
  before any publication begins.
- A later failure rolls back earlier edits and removes earlier creates. Each
  rollback is permitted only while the exact file identity published by this
  transaction is still present with the expected digest.
- A concurrent replacement is preserved, even when it contains the same
  bytes. The result becomes `unverified`; it is never reported as success.
- Missing edits are not reinterpreted as creates, and a newly occupied create
  target is not overwritten.
- Stop and cancellation enter the same protected rollback path, so an exact
  created file is removed and an exact edited file is restored before the
  transaction settles.
- Durable receipts retain bounded operation, hash, state, and provenance
  metadata only. Proposed content, diffs, transient file identities, approval
  decisions, and apply capabilities are not persisted.

## Verification

- Focused adversarial transaction, proposal, controller, orchestration, and
  MCP coverage: **82 passed**.
- Combined transaction/controller/orchestration/MCP integration coverage:
  **180 passed**.
- Direct HTTP/MCP integration, packaging, live probe, and CLI coverage:
  **27 passed**.
- Focused Agent UI and strict contract coverage: **334 passed**.
- Full backend suite: **4,659 passed, 9 skipped** in 37 minutes 35 seconds. The
  skips are the expected Windows environments without symlink capability.
- Full frontend suite: **158 files and 2,125 tests passed**.
- Production TypeScript/Vite build passed with **544 transformed modules**.
- Generated OpenAPI drift check, Python bytecode compilation, repository
  privacy/secret scan, and `git diff --check` passed. The repository continues
  to emit its existing Windows line-ending notices.
- Negative coverage includes create collisions before and after preview,
  missing edits, identity replacement with identical bytes, injected
  mid-transaction failure, Stop during publication, and rollback refusal when
  ownership can no longer be proven.

## Live checkpoint

The app was reloaded at `http://127.0.0.1:8765/agent`. The Connections panel
reported **Ready** with orchestration v11 and the expected route, gate, and tool
counts. The disabled in-app connection action explains that connection grants
must be created in the owned native window.

The final runtime inventory found one loopback-only listener owned by one
console-free application process tree and no `llama-server` process. No model
was loaded for this checkpoint, so it consumed no model VRAM and left none to
unload.

## Remaining owner acceptance

The automated boundary is complete, but the real native-presence path still
needs one owner walkthrough. In the owned native Agent window, create a scoped
direct connection for a synthetic workspace; submit a benign mixed create/edit
proposal; deny it once; retry with a new request id; approve it once; verify
both files; and revoke the connection. A real-model turn, Stop, file review,
artifact viewing, and model unload remain separate owner-gated acceptance
checks.

## Next slice

Agent-09r should bring the same mixed create/edit staging into the manual
workspace transaction UI. The service and controller paths now support it, but
the manual multi-file card still stages existing-file edits only. This slice
should add explicit new-file staging, operation labels, collision-safe preview,
one combined review, removal-on-rollback evidence, and focused UI plus service
tests without broadening deletion authority.
