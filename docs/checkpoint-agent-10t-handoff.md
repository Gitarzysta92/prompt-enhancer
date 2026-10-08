# Agent checkpoint 10t handoff

## Outcome

A saved output card now follows one exact verified file move without losing its
identity or rewriting its earlier history.

After a manual, local-model, or externally proposed file move settles, Prompt
Enhancer finds a source artifact only when its latest digest and byte size
match the move receipt. It then reopens and rehashes the destination through
the bounded no-follow workspace reader and appends an immutable
`reviewed_move` version under the same artifact ID. Earlier versions keep their
original paths, while the current card points to the verified destination and
survives application restart.

The reproduced pre-fix failure left the artifact head at the old path after the
workspace move. The regression now proves create/capture -> verified move ->
same artifact ID -> new path version -> fresh catalog/artifact service -> exact
destination content.

## Conflict and truth boundaries

- Only **Save locally** chats can project durable artifact lineage. Metadata-
  only chats and untracked files keep their existing lifecycle behavior.
- A stale artifact whose latest digest or size does not match the moved bytes
  is not associated with the destination. Its old card truthfully becomes
  missing while the different moved bytes remain untracked.
- If a distinct artifact card already owns the destination path, neither
  lineage is merged, replaced, or rewritten. Because the verified filesystem
  move has already happened, the metadata step returns
  `agent_artifact_relocation_target_conflict` and marks reviewed-change
  coverage partial.
- A `reviewed_move` version carries no invented turn or conversation-event
  provenance. Proposal content, diffs, approval identity, and file bytes are
  not stored in artifact metadata or returned through MCP.
- The artifact database update is atomic, but it follows the verified
  filesystem effect. The pair is not a power-loss-atomic filesystem
  transaction.
- Directory moves and recoverable-trash lineage are not implemented by this
  checkpoint and are disclosed as such in the Agent Connections guidance.

## Contract changes

- `agent-artifact.v2` adds `reviewed_move` provenance and immutable path
  versions.
- Agent catalog schema 11 migrates the artifact-version provenance constraint
  while preserving existing rows and the immutable-version trigger.
- Agent orchestration advances to `local-agent-orchestration.v16` and declares
  exact matching-file move continuity. Route coverage remains 61 Agent routes
  plus five runtime routes.
- Agent MCP advances to `prompt-enhancer-agent-mcp.v20`. The default surface
  remains 19 tools; no route, tool, approval, apply, byte-return, shell, model,
  or deletion authority was added.
- OpenAPI, generated TypeScript, strict frontend parsers, endpoint self-test,
  setup metadata, visible Connections copy, and controller documentation use
  the same versions and limitations.

## Validation

- The broad focused backend gate passed **245 tests** across artifact,
  migration, manual/model lifecycle, external MCP, controller, OpenAPI, and
  local-Agent modules.
- The broad focused frontend gate passed **384 tests** across artifact,
  controller/MCP, transport, Connections, and Agent-page modules.
- Post-disclosure focused reruns passed **16 backend** and **15 frontend**
  tests.
- A final entry-lane regression passed for a model-emitted `move_file` call,
  proving that manual review, local-model tool use, and external MCP lifecycle
  proposals all reach the same verified artifact-relocation path.
- Six Chromium workflows passed at 1,440 px and 360 px for controller health,
  generated-output capture, and inert image/PDF/Office viewers.
- The generated-API drift check, production TypeScript/Vite build (**553
  modules**), Python compilation, repository privacy scan, and tracked-diff
  whitespace check passed. Vite still reports the existing advisory for the
  approximately 506 kB minified Agent-page chunk; that is performance debt,
  not a failed build or a correctness claim.
- The rebuilt loopback app was checked live at 1,046 px and 390 px. It reports
  orchestration v16, 61 Agent routes, five runtime routes, ten native review
  gates, and the exact file/directory move guidance with no horizontal
  overflow or browser warning/error.
- The final runtime check found one loopback listener on 8765, none on 8766,
  zero visible terminal windows, zero local-model processes, and zero local-
  model GPU compute rows.

## Remaining owner gates and next slice

The owner artifact walkthrough and one real model-backed turn/Stop/review/
unload/cleanup run remain deliberately unperformed. No real MCP credential,
provider configuration, workspace approval, model, GPU allocation, or
microphone access was created here.

The next safe autonomous slice is bounded directory-move artifact continuity:
advance only already-known saved artifact cards beneath the reviewed directory
prefix, revalidate every destination independently, preserve all prior paths,
and fail closed on partial or conflicting mappings. Recoverable-trash artifact
state should remain a separate reviewed slice after that.
