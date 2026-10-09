# Architecture decision records

Architecture decision records (ADRs) capture consequential technical decisions,
their evidence, their trade-offs, and the conditions that should cause them to be
revisited. An accepted ADR describes the current default; it is not permission to
weaken the repository's privacy or safety rules.

For implementation status, use the [dated architecture atlas](../architecture/README.md)
and authoritative readiness ledger. Historical accepted scope is not a release
pass. ADR 0020 records the current private-source/native-host/workflow scope;
ADR 0019 records owner review. Any collaborator may propose a new decision;
only owner acceptance changes the default.

| Current clarification | Review disposition |
| --- | --- |
| [0019 — Owner-reviewed architecture and contributions](0019-owner-reviewed-architecture-and-contributions.md) | Existing owner policy, documentation under PR review |
| [0020 — Current product boundaries and beta scope](0020-current-product-boundaries-and-beta-scope.md) | Consolidates approved scope; does not confer implementation acceptance |
| [0022 — Inference provider boundary](0022-inference-provider-boundary.md) | Proposed reviewed remote-inference exception; owner acceptance pending |
| [0021 — Evidence-bound architecture atlas](0021-evidence-bound-architecture-atlas.md) | Proposed maintenance convention for owner review |

| ADR | Status | Decision |
|---|---|---|
| [0001](0001-modular-monolith-hexagonal-metric-graph.md) | Accepted | Modular monolith with hexagonal boundaries and an explicit metric graph |
| [0002](0002-codex-app-server-read-boundary.md) | Accepted | Bounded Codex local-history access with selector-gated detail reads |
| [0003](0003-offline-provider-schema-compatibility-lifecycle.md) | Accepted | Offline, reviewed provider-schema compatibility releases without runtime adapter downloads |
| [0004](0004-full-available-session-scope-boundary.md) | Accepted seam | Full available-session coverage is an explicit completeness claim; durable incremental publication remains follow-up work |
| [0005](0005-team-control-plane-boundary.md) | Accepted foundation | Content-free team control plane with default-deny authorization and a replaceable storage port; no deployment, identity provider, or billing is accepted |
| [0006](0006-private-social-and-direct-file-foundation.md) | Accepted S0 foundation; partly superseded by 0008 | Invite-only social metadata and direct-only owner-hosted files; no production identity, cryptography, signaling, relay or payload routes are accepted |
| [0007](0007-windows-distribution-and-local-data-foundation.md) | Accepted offline foundation | Packaged resource, private-path, inventory, deterministic artifact, backup, diagnostic, update-verification, and egress contracts without a supported installer or release path |
| [0008](0008-durable-local-social-metadata-runtime.md) | Accepted local development runtime | Separate transactional social metadata persistence and a principal-gated, default-off loopback composition; no production identity, E2EE, signaling, or byte transport |
| [0009](0009-synthetic-browser-direct-transfer-prototype.md) | Accepted synthetic development prototype | Exact-opt-in, generated-byte WebRTC data-channel exercise with ephemeral in-process signaling; no real file, identity, cross-device signaling, STUN/TURN, relay, or production claim |
| [0010](0010-claude-code-hook-capture-boundary.md) | Accepted prospective capture surface | Content-free Claude Code capture through documented hooks into an append-only ledger under separate consent; separate loopback OTLP receiver for token usage; no task-outcome inference; the only private-directory read is the owner-authorized reader in 0011 |
| [0011](0011-owner-authorized-session-reader.md) | Accepted, on by default since 2026-08-19 | Owner-authorized on-demand reading of the owner's own Codex and Claude Code sessions in the local dashboard: catalog- and consent-gated, bounded, never persisted, `raw_transcripts` truthful; no network path and no vault. Addenda: transcript adapter as the primary Claude source; Claude text window and default-on analysis |
| [0013](0013-local-model-runtimes.md) | Accepted | Local model runtimes: llama.cpp llama-server per activated model on loopback, cpu / gpu / split device choice, per-model OpenAI-compatible endpoint under the authenticated local API, size-confirmed downloads through the person's own Hugging Face login; the model-judge lane stores model judgments separately from product metrics |
| [0012](0012-task-scoped-verification-evidence.md) | Accepted | Safe-event decoder 4: a reviewed (accepted) task revision is the only verification-task denominator; test/build runs with exit status are receipts; no revision or an ambiguous one declares no family, so first-pass verification is numeric only when someone asserted the task |
| [0014](0014-read-only-agent-surface.md) | Accepted | Read-only, allowlisted agent surface served as MCP over stdio without an SDK: six bounded metadata/metric tools, no transcript text, paths or tokens, explicit context-egress acknowledgement before serving, configuration printed rather than written |
| [0015](0015-prompt-check.md) | Accepted | Prompt check: validate a prompt in context before an agent acts - the coaching pack's prompt metrics with detected/missing cues, content-free context inference, local-model commentary with a reformulated prompt (visibly model output), via HTTP, the MCP tool `check_prompt` and an opt-in Claude Code hook; only metrics are stored |
| [0016](0016-local-agent-workspace.md) | Historical accepted slices; authority/history clarified by [0020](0020-current-product-boundaries-and-beta-scope.md) | Local workspace, streaming and editor rationale. Earlier browser-approval/in-memory descriptions are historical: current protected actions require native approval, and private durable chat history does not retain reusable authority. |
| [0017](0017-remote-annotation-providers.md) | Accepted, both paths implemented locally | Annotation paths: after an allowance, any model the person drives (Codex, Claude Code, a local model) annotates through the app's `/v1/annotation/*` endpoint with a prepared metaprompt; a separate "annotate remotely" action submits redacted windows + pseudonymous ids to the central annotation server (`/central/v1/*`, embedded today, VPS beside login later), which annotates with its strongest model and keeps the submissions as the training dataset |
| [0018](0018-shared-team-folders.md) | Accepted, first slice implemented | Shared team folders: a person explicitly shares one folder (token shown once, stored hashed); peers join it directly over `/p2p/v1/*` (no central server in the data path), pull it into a local copy that agents use as an ordinary workspace, and push edits back with last-synced-hash conflict detection - simultaneous edits survive as conflict copies. LAN listener and background sync deferred |

Changes that reverse an accepted decision should add a superseding ADR rather
than silently rewriting the original rationale.
