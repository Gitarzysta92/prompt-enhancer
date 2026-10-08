# Agent checkpoint 10s handoff

## Outcome

Externally orchestrated create/edit work now produces the same durable,
reviewable output cards as native Agent writes after the person approves the
change and the workspace service verifies the effect.

For a **Save locally** chat, the terminal verified write receipt is retained
and projected into immutable artifact lineage. A later verified edit advances
that artifact with another version, and a fresh catalog/artifact service
rebuilds the complete lineage after application restart. The current artifact
viewer can then read the latest verified bytes through the existing bounded,
typed content route.

The original failure was reproduced first: an external create/edit could be
approved and correctly published while durable history contained only the
session status, leaving no artifact card after restart. The proposal settlement
path now persists only the same bounded verified receipt used by native writes.

## Privacy and authority boundaries retained

- Proposal content, diffs, approval identities, pending/denied/failed/
  unverified attempts, and status chatter remain live-only.
- Metadata-only chats retain neither a proposal nor its write receipt.
- Stored tool results contain no file content; only bounded terminal identity
  and verified receipt metadata can drive artifact lineage.
- MCP artifact list/get returns metadata, versions, provenance, size, and
  digest—not workspace bytes or native capture authority.
- The controller still cannot approve, directly apply, launch a shell, start a
  provider/model, permanently delete, or bypass native user-presence review.
- Artifact identity remains bound to the reviewed path. Continuity across a
  later lifecycle move is not claimed by this checkpoint.

## Contract changes

- Agent orchestration advances to `local-agent-orchestration.v15`: 61 Agent
  routes plus five runtime routes.
- The protocol now declares
  `external_write_artifacts=saved_chats_retain_verified_receipts_only_for_artifact_lineage`.
- Agent MCP advances to `prompt-enhancer-agent-mcp.v19`: 19 default tools.
- HTTP and stdio setup documents explicitly declare that proposal content is
  not retained and verified write-receipt projection is limited to saved chats.
- OpenAPI, generated TypeScript, strict frontend parsers, endpoint self-test,
  direct-client probe, setup copy, and controller documentation use the same
  exact contract.

## Validation

- The new restart regression covers approved external create followed by edit,
  two immutable versions, exact digest/size/provenance, latest-text viewer
  access, and absence of proposal content and approval IDs in durable history.
- The denied-proposal canary proves rejected content and its path never enter
  retained history.
- A real disposable loopback MCP transaction lists both reviewed artifacts and
  gets one exact metadata lineage after native approval, without returning file
  bytes or starting a model/process.
- The focused backend gate passed 182 tests. The focused frontend gate passed
  360 tests; the changed Connections panel additionally passed its 15-test
  focused rerun with assertions for the durable-output privacy wording.
- Six Playwright cases passed at 1,440 px and 360 px for controller health,
  generated-output review, and inert image/PDF/Office viewers.
- Generated-API drift checking, the production frontend build, Python
  compilation, and the repository privacy scan passed.
- The rebuilt loopback app was inspected at 1,046 px and 390 px. It reported
  orchestration v15, 61 Agent routes, five runtime routes, and 19 core tools;
  both layouts exposed the new durable-output guidance without horizontal
  overflow, and the browser console was empty.
- Runtime cleanup ended with one hidden two-process desktop owner tree and one
  loopback listener, zero visible terminal windows, zero local-model server
  processes, and zero local-model GPU compute rows.

## Remaining owner gates and next slice

The owner artifact walkthrough and one real model-backed turn/Stop/review/
unload/cleanup run remain deliberately unperformed. No real credential,
provider configuration, workspace effect, model, GPU allocation, or microphone
access was created here.

The next safe autonomous gap is artifact lifecycle continuity: after a verified
file or directory move, the card currently remains bound to its earlier path
and can become stale. That behavior needs an explicit provenance-preserving
design and tests before the product may claim that output lineage follows
reviewed moves.
