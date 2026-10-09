# ADR 0020: Current product boundaries and beta scope

- Status: consolidation of already owner-approved scope; pending review of this
  documentation. No new implementation or acceptance is conferred.
- Date: 2026-10-08
- Clarifies/supersedes historical scope statements in ADRs 0001, 0007 and 0016;
  retains their useful boundary rationale.

## Context

The initial design was analytics-only and mentioned public source and a future
Tauri host. Later scope added authored local Agent chats, pywebview native
windows, private source, MSIX distribution and required multimodel workflows.
Historical decisions must not be interpreted as the current implementation map.

## Decision

Keep a local modular monolith with explicit adapters and composition. The native
host in the current code is pywebview; Tauri is not the implemented desktop host.
Use private source and a separate binary-only distribution destination. The beta
is account-free Windows 11 x64 with CPU and qualified NVIDIA/hybrid execution.
Installation, signed updates, privacy, durable history and native approvals are
release requirements. A push to main alone is not an update delivery pipeline.

Separate analytics, authored Agent work and multimodel workflows. The metric
dependency DAG is a trusted internal computation graph. The planned workflow
DAG is user-authored and needs its own versioned contracts, private run store,
scheduler, adapters, resource admission, editor and installed headless runner.
The existing project automation and prompt-check hook do not implement it.

Workflow beta scope includes text, image and bounded WAV audio; the eight
declared families and a second text LLM; series/branch/join graphs; real admitted
parallel inference; Build/Run/Results; reviewed composer enhancement; and local
headless export/import. Limits remain one run, 32 nodes, 16 model nodes and two
simultaneous inference stages. llama.cpp/GGUF and pinned PyTorch/Transformers are
the agreed runtime families. Do not introduce another runtime family by default.

Authored chats can have durable private history under their retention policy.
Native approvals, stale proposals and execution authority are not restored with
that history. Browser authentication is not native user-presence proof.

Accounts, billing, teams/social, hosted analysis and external workflow connectors
remain deferred for beta. Existing records/code stay intact. Historical remote
annotation ADRs do not authorize transcript egress in ordinary development.
Any such egress still needs task-specific consent and a redaction preview.

## Consequences

Keep B00–B11, W00–W08 and WP01–WP08 as separate acceptance gates. A source seam,
synthetic test, compiled spike or verifier is not an installed user journey.
Current status is in the readiness ledger and dated atlas, not inferred from an
ADR marked Accepted. Qualification must use exact artifacts and hardware scope.

New architecture proposals must describe how they preserve all three lanes,
retention boundaries and shared process/resource ownership. A rewrite or scope
reduction requires a separate owner decision.
