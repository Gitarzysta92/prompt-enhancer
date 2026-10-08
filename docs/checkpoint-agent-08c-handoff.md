# Agent-08c handoff: non-spawning release hardening

Date: 2026-08-27
Status: implementation complete; native visual and real-model acceptance remain deferred

## Outcome

Agent-08c adds an explicit, authenticated health check for the authored Agent
project/chat store and a deterministic release-hardening harness. The health
check is opt-in, is not polled automatically, and returns only bounded counts
and closed status codes. It cannot return project or chat names, workspace
paths, prompts, messages, identifiers, timestamps, artifact content, attachment
bytes, model names, tool arguments, exception details or credentials.

The diagnostic endpoint is `GET /v1/diagnostics/agent-hardening`. It deliberately
stays outside `/v1/agent`, so the frozen v4 controller manifest remains exactly
52 Agent routes plus five runtime routes and no controller gains new authority.
The response is authenticated and marked `no-store, private` / `no-cache`.

The UI places **Projects & chats health** inside the already-collapsed
**Connections & setup** area. It does no work until the owner selects **Run
health check**. A strict frontend parser rejects unknown keys, invalid counts,
contradictory integrity states, duplicate or incorrectly ordered recovery
actions, and any accidental content field.

## Recovery and soak evidence

All new hardening cases use fictional temporary workspaces, in-process model
doubles and fake process handles. They never launch a command, local model,
native application or external browser server.

- 24 turns with 64 chunks each remain bounded in the live event view, persist
  the exact durable event history, and resume cleanly after restart.
- Interrupted write approval and command journals resume read-only with no
  pending approval, restored command authority, tool arguments or preview data.
- An edit-preview capability does not survive restart and cannot be applied.
- Artifact access re-hashes current bytes after restart and rejects a changed,
  stale file.
- 32 fake runtime activate/deactivate cycles end idle with every fake handle
  terminated and no owned process left behind.
- A forced late schema-migration failure rolls back all earlier statements and
  maps to a closed, detail-free unavailable diagnostic.
- Exact aggregate counts prove that deleting a chat cascades its retained
  history, artifacts, artifact versions and attachment record.
- Export verification excludes approval identifiers, arguments and previews.

Existing runtime lifecycle tests in the broader non-spawning selection also
cover failed startup rollback, cancellation during activation/health wait,
shutdown races, unknown-cleanup quarantine and readiness refusal.

## Verification receipts

- OpenAPI export and TypeScript client generation passed.
- Focused backend hardening/catalog/history/orchestration/OpenAPI: **37 passed**.
- Focused frontend health panel and strict parser: **10 passed**.
- Broader non-spawning backend selection: **942 passed**, **1 expected Windows
  symlink-capability skip**, **1 intentionally deselected real hanging-child
  test**, and **1 repository privacy assertion failure**. The failure is solely
  the known pre-existing untracked `docs/checkpoint-agent-02-shell.png` binary;
  it was not deleted, modified, ignored or allowlisted.
- Complete frontend gate: **2,002 passed across 150 files**.
- Production TypeScript/Vite build: **528 modules transformed**.
- The in-app browser reached an already-running synthetic development build,
  but that build truthfully exposes no live Agent transport, so it cannot render
  this server-backed diagnostic. No new server was started for visual testing.
- No real model or model runtime was loaded by this checkpoint. No known
  `llama-server`, Prompt Enhancer runtime or owned model process remained from
  these tests. A pre-existing loopback development listener was observed and
  left untouched.

The privacy assertion is not a product regression and is not relabelled as a
pass. Repository-wide privacy sign-off remains blocked until the owner handles
that exact old screenshot through an authorized path.

## Owner review later

1. Restart Prompt Enhancer normally once; do not use a developer launcher.
2. Open **Agent → Connections & setup → Connections & controller API**.
3. Confirm no health request or result appears before selecting **Run health
   check**.
4. Run the check and verify the card shows only counts/status, never content,
   paths or identifiers.
5. At desktop width and 320 px, verify the collapsed setup does not crowd the
   project rail, transcript, Stop control or composer.
6. Create a retained fictional chat, close/reopen the application, and verify an
   interrupted chat is recovered read-only with an explicit revalidation action.
7. If a real local model is used for optional acceptance, stop/unload it and
   verify its process and GPU allocation are gone before closing the checkpoint.

## Next bounded slice

Agent-08d is the synthetic responsive/accessibility acceptance pass: 320 px and
desktop layout, keyboard and focus order, ARIA/live-region behavior, recovery
state presentation and overflow. It will not start a native app or real model.
Real-model/native reload acceptance stays separate and owner-gated. Legacy
layout retirement remains last, after explicit feature-parity evidence.
