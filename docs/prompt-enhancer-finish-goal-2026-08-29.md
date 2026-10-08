# Prompt Enhancer finish goal

Status: Converge-06 automated implementation complete; C07a automated staging foundation validated/complete; C07b.1 automated security slice validated/complete; C07b.2 offline manifest-verification slice complete after owning gates; C07b.3 standalone read-only MSIX preflight implementation and automated validation complete; C07b.4 staged package-review automated slice complete; C07 remains partial; installer/relaunch/rollback, owner visual, packaged and final release evidence remain pending
Established: 2026-08-29
Expanded and reconciled: 2026-09-04
Scope owner: local user

## Product outcome

Finish Prompt Enhancer as a local-first, privacy-preserving AI workbench that
combines:

1. a Codex/Claude-style project and chat experience;
2. reliable local Hugging Face model download, loading, switching and cleanup;
3. a reviewed coding-agent workspace for reading, creating, editing, moving,
   comparing and viewing files and generated artifacts;
4. safe external orchestration through a direct loopback Agent API and MCP;
5. a searchable MCP Store with trustworthy source metadata, icons, review,
   install/update/uninstall, project-scoped tool permissions and observable tool
   execution;
6. a coherent, responsive and accessible UI across the whole application.

The product is not finished because a page renders or a narrow unit test passes.
Every advertised control must work through the real local stack, survive the
appropriate restart boundary, report failures truthfully, and have automated
and owner-visible acceptance evidence.

The feature-level release obligations are enumerated in the
[owner feature acceptance register](prompt-enhancer-owner-feature-register-2026-08-31.md).
The two documents form one goal: this document controls sequencing and safety;
the register prevents any requested capability from disappearing inside a broad
milestone label.

The [2026-09-04 convergence audit](prompt-enhancer-convergence-audit-2026-09-04.md)
is the current empirical baseline. It supersedes broad historical
`Automated complete` wording as a release claim. Earlier handoffs remain useful
implementation evidence, but every affected feature is reopened until it passes
the audit's contract, real-loopback, owner and release evidence ladder. The
standard browser gate is green at 166/166 after the Converge-03 information
architecture repair. Converge-02 and 03 preserve 16/16 zero-interception journeys
through the production-built dashboard and a disposable real loopback API; later
checkpoints must preserve both results. The separately labelled intercepted
frontend/HTTP contract suite is also green at 41/41; that result is supporting
contract evidence, not a substitute for the real-loopback gate. See the
[Converge-03 handoff](checkpoint-converge-03-handoff.md). Converge-04 adds a
fail-closed Agent owner-evidence ledger and stronger opt-in physical-model
cleanup probe. Converge-05a adds a separate exact, page-owned trusted-MCP
lifecycle ledger. Converge-05b adds the equivalent ordered external-controller
ledger with a content-free process epoch and tool-admission sequence; see the
[Converge-04 handoff](checkpoint-converge-04-handoff.md),
[Converge-05a handoff](checkpoint-converge-05a-handoff.md), and
[Converge-05b handoff](checkpoint-converge-05b-handoff.md), and the current
[Converge-06 handoff](checkpoint-converge-06-handoff.md). Converge-07a adds a
bounded signed-manifest download/staging foundation with fenced recovery and
truthful downloaded-not-installable copy; see the
[Converge-07a handoff](checkpoint-converge-07a-handoff.md). C07 remains partial
pending Windows packaged evidence. C07b.1 adds the bounded private update-root
preparation and durable signed-envelope replay floor; see the
[C07b.1 handoff](checkpoint-converge-07b-handoff.md).
C07b.2 adds offline deterministic public build-manifest validation for duplicate,
ambiguous and non-normalized paths; see the
[C07b.2 handoff](checkpoint-converge-07b2-handoff.md).
C07b.3 adds a standalone, read-only MSIX identity/digest/signer-pin preflight
and release-tool CLI; see the
[C07b.3 handoff](checkpoint-converge-07b3-handoff.md).
C07b.4 connects that preflight only to authenticated staged-package review;
see the [C07b.4 handoff](checkpoint-converge-07b4-handoff.md).

## Automatic execution directive

Continue autonomously from the Converge-06 automated boundary through Converge-07
in dependency order. Do not wait for approval between safe,
repository-local implementation, synthetic testing, zero-interception loopback
testing, documentation and app reload steps. At each checkpoint:

1. reproduce the named defect or missing behavior;
2. implement the smallest coherent production slice;
3. test success, refusal, failure, cancellation, stale state, restart, privacy,
   accessibility and responsive behavior as applicable;
4. rerun the owning regression gates once;
5. update the convergence audit, feature register and owner click-later list;
6. reload the app with one loopback listener and no test model left loaded; and
7. advance automatically only when the checkpoint's exact exit gate is green.

Owner interaction is required only for a genuinely native, hardware, external-
account, protected-authority or subjective visual acceptance step. Record those
items without claiming success, continue other safe independent work where the
dependency graph permits, and never use an owner-pending check to hide a code,
test or integration failure. Do not commit, push, install a real third-party
package, read real provider content or perform a protected external action unless
the owner separately authorizes it.

## Supervised delegation rule

For future checkpoints, root reads the code, assigns bounded work, reviews the
result and independently validates it; root does not edit implementation.
Terra handles harder implementation, while Luna handles smaller implementation
changes, tests and docs. Defects return to the implementer for correction, and
bounded ownership plus targeted gates prevent duplicate work. Existing privacy,
scope, synthetic-fixture and checkpoint rules remain in force.

## Active C07b.4 owner constraint

This work is being performed in a remote session. Until the owner explicitly
approves a later native step, do not reboot the PC, restart or relaunch the
application, install a package, kill processes, open visible windows, load a
model, or use real provider/release data. The standing protected-reload step is
skipped while this constraint is active; continue only with offline code review
and temporary synthetic-fixture tests. Earlier reload evidence remains dated
historical evidence and is not rewritten.

## Goal hierarchy and completion rule

This program has four nested levels. They must never be confused:

1. **Product goal:** the complete local AI workbench described in this document.
2. **Milestone:** one coherent product area such as Agent, Runtime, Workspace,
   Artifacts, Orchestration, MCP Store, application sweep or release hardening.
3. **Checkpoint:** one bounded, independently testable user outcome inside a
   milestone. Exactly one implementation checkpoint is active at a time.
4. **Owner acceptance:** the short real-machine review that cannot be replaced
   honestly by synthetic automation.

`Automated implementation complete` therefore does not mean `released`. A
milestone is release-complete only when its current automated evidence, required
owner evidence and integration evidence are all green. An old handoff is useful
history, but cannot hide a new regression.

Status terms have exact meanings:

- **Pending:** required production behavior is not implemented.
- **Implementation active:** the current bounded code slice.
- **Automated implementation complete:** current synthetic, integration and
  browser gates pass; listed owner evidence may remain.
- **Owner review pending:** automation is green, but a real-machine or
  subjective check is still explicitly open.
- **Locked:** the UI and backend deliberately refuse an action until a later
  authority, safety or compatibility checkpoint exists.
- **Release complete:** no required acceptance debt, workaround or falsely
  advertised control remains.

## North-star release journey

The final representative walkthrough is one connected journey. Passing its
parts on different pages or with different hidden setup does not pass release:

1. Launch the packaged Windows application once. Exactly one loopback listener
   appears, no terminal window flashes, and no model or MCP process starts by
   surprise.
2. Create or reopen a durable Agent project, choose its workspace, create a
   chat, switch chats and restart the application without losing retained state.
3. Discover or import an exact Hugging Face model revision, review provenance
   and capabilities, choose CPU, GPU or supported split placement, load it and
   receive an honest readiness result.
4. Chat with text and, only where capability evidence permits, image, audio or
   document input. Streaming, Stop, retry, edit/regenerate, Markdown/code,
   context usage and recovery behave deterministically.
5. Observe concise model-provided reasoning summaries, plans, progress and tool
   activity without exposing or pretending to expose hidden chain of thought.
6. Let the Agent inspect the admitted workspace, propose a multi-file change,
   review the exact diff, approve or deny it, run one reviewed command and
   verify the result objectively.
7. Open a generated artifact from its producing turn, inspect it in the safe
   viewer, compare or export the intended version and return to the same chat.
8. Search the MCP Store, inspect a source-provenanced tile and detail view,
   install an exact compatible server, select exact project tools, approve one
   consequential call, then update, roll back or uninstall it cleanly.
9. Create a project-bound Codex-, Claude- or provider-neutral controller
   connection, observe its ownership, run and stop a scoped turn, revoke it and
   prove that another project or controller is unaffected.
10. Rename, search, pin, archive, restore, fork and export retained work; delete
    only after an explicit consequence preview.
11. Switch to another model and prove the previous owned runtime released its
    processes and accelerator memory before the replacement becomes ready.
12. Reload and then shut down. Durable state reconciles, interrupted work is
    truthful, and no listener, model, command or MCP child remains orphaned.

Any failure in this journey reopens the owning checkpoint. The release is not
accepted by bypassing the failing control or performing an undocumented manual
setup.

## Feature closure scorecard

Every requested capability belongs to one scorecard row and must close all four
columns: behavior, persistence/recovery, interface and independent evidence.

| Area | Required owner-visible capability | Mandatory failure/recovery coverage | Release evidence |
| --- | --- | --- | --- |
| Agent projects and chats | Durable project rail and searchable chats with create, switch, rename, pin, archive, restore, move, fork, export and explicit delete | restart, stale selection, concurrent mutation, duplicate request and interrupted stream | backend state-machine tests, strict UI contracts and real two-width browser journey |
| Conversation experience | Streaming Markdown/code, attachments, Stop, edit/retry/regenerate, safe reasoning summaries, progress, tool cards and truthful context | late/out-of-order events, reconnect, Stop race, unsupported input and failed-send recovery | event-order tests, accessibility states and owner conversation review |
| Local models | Exact revision discovery/download, readiness, parameters, CPU/GPU/supported split placement, switch and unload | disk refusal, cancellation, crash, OOM, stale health, incompatible modality and cleanup uncertainty | synthetic runtime matrix plus owner-approved real CPU/GPU and VRAM-release run |
| Workspace agent | Bounded discovery/search/read, editor, multi-file diffs, create/move/recover, commands and reviewed web actions | traversal, symlink/race, stale revision, partial publication, denial, timeout and child cleanup | objective read-back, approval tests and owner file/command walkthrough |
| Artifacts and multimodal | Capability-gated image/audio/document input and versioned safe viewers linked to exact turns | spoofed/oversized/corrupt/encrypted input, unsupported viewer, stale version and export race | format matrix, exact-byte evidence and narrow/desktop viewer journeys |
| Direct orchestration | Project-bound Codex/Claude/provider-neutral connections with visible owner, status, Stop, reconnect, resume/fork and revocation | stale token, restart, cross-project access, simultaneous clients and cancellation | direct HTTP/MCP isolation tests and owner-approved client handshake |
| MCP Store | Provenanced searchable tiles, safe details, compatibility, install/update/rollback/uninstall, health, permissions and project tool drawer | malicious metadata/logo, secret handling, schema bombs, redirects/DNS, hangs/crashes, floods and orphan escape | registry/transport/adversarial matrices plus Store-to-Agent browser journey |
| Whole application UI | Coherent hierarchy, icons, responsive panes, truthful controls and complete loading/empty/error states | narrow layout, keyboard traps, stale responses, slow lists, offline/local failures and unavailable authority | route/control inventory, 320–1440 px matrix, accessibility and console checks |
| Privacy and release | Loopback-only operation, content-free diagnostics, recoverable migrations, bounded performance and Windows package parity | migration interruption, retention, startup/shutdown recursion, listener collision and process leak | privacy/OpenAPI/build suites, process census and packaged owner walkthrough |

Features are not traded between rows. For example, a polished chat does not
compensate for unreliable model cleanup, and a safe MCP installer does not
compensate for missing project-scoped tool admission.

## Non-negotiable product truths

- Local services bind to loopback. No transcript, prompt, file content,
  credential, tool argument/result or sensitive derived data leaves the machine
  without an exact task-specific action and visible review.
- Hidden chain of thought is never claimed or exposed. The chat may show
  model-provided reasoning summaries, plans, progress, tool activity and evidence
  when available.
- Starting or stopping a model, agent, command or MCP server must not open a
  terminal window. Cleanup is successful only when the owned root and ordinary
  descendants are verified gone.
- Missing duration, tokens, cost, outcome, context use or capability stays
  unknown. It is never silently converted to zero, failure or support.
- A model's statement that work is complete is not proof. File state, command
  results, tests, diffs and other objective evidence outrank completion text.
- All protected writes, commands, web access, MCP installation and consequential
  tool calls require the exact scoped approval defined for that action.
- Existing user work and unrelated dirty-worktree changes are preserved.

## Checkpoint discipline

Each checkpoint ends with one compact handoff containing:

- what changed and what deliberately remains locked;
- backend, frontend, contract, privacy and browser evidence;
- process/model cleanup evidence where relevant;
- a short owner click checklist;
- the exact next checkpoint.

No checkpoint is called complete while its acceptance test is red, its state is
ambiguous, or the UI claims authority the backend does not provide.

## Operational milestone board

This board is the execution source of truth. Earlier checkpoint documents are
evidence and design history; they do not make a later regression disappear.
Existing implemented behavior is reconciled and repaired in place rather than
needlessly rewritten.

Rows below Release-01 describe the historical implementation inventory. Their
old `complete` wording means contract or synthetic evidence only unless the
2026-09-04 convergence audit explicitly says otherwise. The new Converge rows
control execution and release status.

| Milestone | Deliverable | Current state | Exit gate |
| --- | --- | --- | --- |
| Audit-02 | Independent Fable 5.1 review, primary source audit, live route traversal and current test baseline | Complete | One privacy-safe audit distinguishes contract evidence, real-loopback evidence, owner acceptance, placeholders and missing work. |
| Converge-01 | Truthful status and reachable Agent/metrics controls | Complete | Six repeatable browser failures repaired; 165/165 standard browser tests green; live 20/16/0/4 operability renders; static readiness and production web no-op removed. |
| Converge-02 | Zero-interception local-stack acceptance harness | Complete | Sixteen critical built-frontend journeys pass against a temporary synthetic real backend with no intercepted application routes; shutdown removes its state, listener and model-runtime ownership. See [handoff](checkpoint-converge-02-handoff.md). |
| Converge-03 | SOTA-focused Agent information architecture | Automated implementation complete; owner visual review pending | Chat owns the viewport; composer and latest reply stay visible at 720 px; secondary tools use coherent disclosures/drawers; one runtime state is announced; responsive, accessibility and real-loopback gates are green. See [handoff](checkpoint-converge-03-handoff.md). |
| Converge-04 | Packaged real Agent core loop and cleanup | Automated acceptance instrumentation complete; packaged owner/hardware execution pending | The page-owned receipt now requires recovered history, workspace, two-model lifecycle, complete/Stop turns, approved write/command, review, artifact, context and final cleanup evidence. Native dialogs, physical placement/VRAM, terminal census and package restart remain owner-gated. See [handoff](checkpoint-converge-04-handoff.md). |
| Converge-05 | Trusted MCP and external-client production acceptance | 05a and 05b automated instrumentation complete; both real owner journeys pending | The trusted-MCP ledger requires install, admission, host/call/stop, update, rollback, retained-generation cleanup and uninstall. The external-controller ledger requires connect/discover/own/stream/Stop/reconnect/handoff/revoke/refusal/cleanup with exact process and activity ordering. One real MCPB lifecycle and one current external-controller lifecycle still need owner execution. See the [05a handoff](checkpoint-converge-05a-handoff.md) and [05b handoff](checkpoint-converge-05b-handoff.md). |
| Converge-06 | Metric validity and product-surface simplification | Automated implementation complete; owner visual review pending | Core/Review/Labs navigation and the 39 operational vs 20 canonical vs 10 historical metric presentation are implemented; existing 20/16/4 presentation is preserved, with no new calculators/adapters or scientific-validity claim. Data sources delivers 12 projects per page, collapsed lazy sessions, 20 rows per expanded page, metadata-only search, accurate hidden selections, Clear selection and transport-generation resets. |
| Converge-07 | Signed Windows updater and final release | **Partial: C07a foundation and C07b.1/C07b.2 slices validated; C07b.3 preflight and C07b.4 staged review automated slice complete** | C07a covers fenced signed-manifest download/stage/progress/cancel/retry and truthful downloaded-not-installable UI. C07b.1 adds scoped private update-root DACL preparation and durable signed-envelope replay CAS; C07b.2 adds deterministic public build-manifest boundaries; C07b.3 adds a standalone read-only MSIX identity/digest/signer-pin preflight and CLI; C07b.4 exposes only fenced verified/rejected review of the authenticated fixed staged candidate, without persisting a verified badge or enabling apply. Publisher/native signer positive acceptance, installer/MSIX handoff, relaunch, rollback, public release trust and the complete packaged north-star journey remain open. See [C07b.4 handoff](checkpoint-converge-07b4-handoff.md). |
| Goal-00 | Product contract, privacy boundaries and finish definition | Complete | This document exists, the active goal matches it and the dirty worktree is preserved. |
| Store-05c | Exact local MCP update, one retained rollback generation, uninstall and interrupted-operation cleanup | Complete; owner UI review pending | Install/update/rollback/uninstall/cleanup survive failure and restart tests; UI and API agree; one protected app reload passes with no terminal, MCP or model leak. |
| Store-06 | Project-scoped MCP admission, configuration, tool routing and approvals | Automated implementation complete through Store-06e.4; owner protected clicks remain | Exact reviewed snapshots and project allowlists are durable. An installed admitted host starts only after an exact revision-bound preview and native confirmation, stays memory-only for the current app run, rechecks tool contracts, never auto-starts, and is omitted from model schemas as soon as durable authority drifts. Every call receives a separate non-reusable native confirmation, bounded schema validation/result projection, cancellation/timeout handling, synchronous cleanup on unsafe outcomes, and a content-free SQLite receipt. Configuration-bearing MCPB packages require an exact non-executing schema inspection whose archive, staging and values are discarded. The Store separates focused Browse and Managed workspaces, exposes source-provenanced catalog and compatibility evidence, reconciles exact project/tool/host authority, and renders each actual call as one friendly approval/activity/result card without retaining raw arguments or output. See [Store-06c handoff](checkpoint-mcp-store-06c-handoff.md), [Store-06d handoff](checkpoint-mcp-store-06d-handoff.md), [Store-06e.1 handoff](checkpoint-mcp-store-06e-1-handoff.md), [Store-06e.2 handoff](checkpoint-mcp-store-06e-2-handoff.md), [Store-06e.3 handoff](checkpoint-mcp-store-06e-3-handoff.md), and [Store-06e.4 handoff](checkpoint-mcp-store-06e-4-handoff.md). |
| Store-07 | Adversarial MCP acceptance | Automated complete through Store-07e; owner trusted-MCP review remains in Acceptance-01 | Registry, transport, process, network, schema, secret, crash and isolation matrix passes with content-free diagnostics. See [Store-07e handoff](checkpoint-mcp-store-07e-handoff.md). |
| Agent-11 | Durable project/session/chat parity reconciliation | Automated implementation complete through 11f; native restart review pending | Durable create/browse/switch/rename/pin/archive/restore/move/delete, retained-history resume/fork/export, and restart behavior have automated evidence. Global search follows ownership; Move loads every valid destination; confirmed chat mutations reconcile open state; selected deletion clears stale history/actions without hijacking a background foreground chat; browser export is bound to the visible catalog/history heads; and dedicated routes fall back from cleared live memory to exact durable retained or metadata-only records without accepting stale lookup results. See [Agent-11a handoff](checkpoint-agent-11a-handoff.md), [Agent-11b handoff](checkpoint-agent-11b-handoff.md), [Agent-11c handoff](checkpoint-agent-11c-handoff.md), [Agent-11d handoff](checkpoint-agent-11d-handoff.md), [Agent-11e handoff](checkpoint-agent-11e-handoff.md), and [Agent-11f handoff](checkpoint-agent-11f-handoff.md). |
| Agent-12 | Chat timeline, reasoning summaries and truthful context | Converge-03 automated implementation complete; owner visual review pending | Streaming, Stop, branch-based retry/edit/regenerate, Markdown/code, context and model-neutral entry contracts remain intact. Chat now owns the bounded viewport, runtime state is announced once, project tools and metadata are secondary, and transcript interaction is pointer- and keyboard-operable. |
| Runtime-01 | Production local-model acquisition and lifecycle | Automated implementation complete through Runtime-01c; Converge-04 now enforces the owner receipt; physical real-runtime acceptance remains | Models and Agent share one revision-bound lifecycle coordinator and placement admission. CPU/GPU/split requests fail closed from current evidence. Verified immutable downloads now have disk admission, a durable restart-reconciled ledger, monotonic progress, pause/resume/retry/cancel, provenance revalidation and confirmed owned-partial cleanup. Runtime processes use minimized environments, exact crash/OOM classification and atomic Windows descendant ownership. The UI exposes truthful capacity, recovery and stale-command states. The opt-in physical probe now requires hidden-window, coordinator-idle, process-exit and GPU-cleanup evidence; owner-approved CPU/GPU/switch/unload remains pending. See [Runtime-01a handoff](checkpoint-runtime-01a-handoff.md), [Runtime-01b handoff](checkpoint-runtime-01b-handoff.md), [Runtime-01c handoff](checkpoint-runtime-01c-handoff.md), and [Converge-04 handoff](checkpoint-converge-04-handoff.md). |
| Workspace-01 | Reviewed coding workspace and tool execution | Production web no-op removed in Converge-01; Converge-04 acceptance ledger green; native/package execution remains | Preserve bounded file/search/diff/transaction/command contracts. Web fetch is hard-disabled in the production UI and rejected before session creation when no governed fetcher is composed. The owner receipt now requires an admitted workspace plus verified approved write and command evidence, but the native picker/approval/read-back walkthrough is still pending. |
| Artifact-01 | Multimodal input and generated artifact experience | Automated implementation complete through Artifact-01d; Converge-04 viewer evidence is fail-closed; owner attachment/lifecycle/viewer review pending | Producing-turn navigation, exact project/chat-bound lifecycle, native PNG/JPEG/PCM-WAV input, bounded inert projections for supported text/data/Office/ODT documents, and the complete version-aware text/code/image/PDF/Office viewer are automated at 360 px and 1440 px. Converge-04 counts only a successfully revalidated/rendered viewer; stale or failed previews do not pass. Raw download and sensitive lineage export are separate exact-readback actions; export contains no artifact bytes or absolute workspace path. PDF input still fails closed; staged projections survive service reconstruction and remain model/session bound. See [Artifact-01a handoff](checkpoint-artifact-01a-handoff.md), [Artifact-01b handoff](checkpoint-artifact-01b-handoff.md), [Artifact-01c handoff](checkpoint-artifact-01c-handoff.md), [Artifact-01d handoff](checkpoint-artifact-01d-handoff.md), and [Converge-04 handoff](checkpoint-converge-04-handoff.md). |
| Orchestration-01 | Governed Codex/Claude/provider-neutral control | Automated implementation complete through Orchestration-01b; owner external-client walkthrough remains | Two isolated clients can connect within exact project scope, atomically own one live chat operation, reconnect without resubmission, perform a revision-bound two-party handoff, and be revoked without inheriting native approvals or exposing private state. Owner-only wait/Stop, proof-gated release, visible recovery state and restart-safe content-free ownership are verified. See [Orchestration-01a handoff](checkpoint-orchestration-01a-handoff.md) and [Orchestration-01b handoff](checkpoint-orchestration-01b-handoff.md). |
| Sweep-01 | Route-by-route UI/UX, accessibility and scale repair | Agent and C06 slices automated complete; owner visual review remains | Converge-01 through 03 repaired Agent overcrowding/clipping, unreachable controls, duplicate runtime status, the operability panel and inconsistent Agent file icons. Converge-06 adds the Core/Review/Labs boundary and bounded Data sources surfaces; owner visual review remains. |
| Release-01 | Recovery, performance, Windows packaging and owner acceptance | Reopened; signed discovery only is current updater scope | Current browser gates must return green, genuine local-stack journeys must be added, physical process/model evidence must be collected and the missing package/update lifecycle must be built. |

## Detailed remaining checkpoint map

This is the bounded sequence from the present application state to release. A
checkpoint may be split further when a safety boundary or migration would make
one review too large, but it may not silently absorb a later checkpoint.

| Checkpoint | User-visible outcome | Required acceptance before advancing |
| --- | --- | --- |
| Artifact-01a | Reviewed outputs link back to the exact producing turn; immutable versions can be compared truthfully; unsafe PDFs never enter the renderer. | Complete: focused backend/frontend tests, full Agent frontend regression, two-width browser E2E, production build, privacy scan and protected live reload are green. |
| Artifact-01b | Artifacts have durable rename, archive, restore and explicit recover/remove behavior inside the owning project and chat. | Complete: schema migration, restart, replay/stale-revision, cross-scope, missing/current-file and removed-resynchronization tests; strict API/frontend contracts; keyboard and 360/1440 px browser lifecycle journeys; production build, privacy scan and protected live reload are green. |
| Artifact-01c | The composer admits images, audio and supported documents only when the selected model/runtime can consume them. Recording and upload state are understandable and recoverable. | Complete: strict MIME/suffix/signature/structure/size/capability matrices; restart reprojection and identity binding; explicit PDF refusal; no original document bytes sent to a model; MCP/controller propagation; keyboard and 360/1440 px browser tests; production build, privacy scan and protected live reload are green. |
| Artifact-01d | Generated files and admitted inputs have coherent previews, safe open/download/export, lineage and exact-byte evidence across all supported viewers. | Complete: text/code/image/PDF/Office viewer matrix; active-content refusal; corrupted/encrypted/oversized fixtures; exact scope/revision/version/size/digest read-back; metadata-race refusal; progressive transport fallback; responsive reload/linkage/export tests; production build, privacy scan and protected live reload are green. |
| Orchestration-01a | A user can create, inspect and revoke a scoped Codex-, Claude- or provider-neutral controller connection without opening a terminal. | Complete except owner setup review: project-bound v4 credentials, one-time `pemcp2` setup material, restart/fail-closed legacy-scope behavior, independent revocation, two-client isolation, zero inherited native approval authority and the protected hidden reload are verified. See [Orchestration-01a handoff](checkpoint-orchestration-01a-handoff.md). |
| Orchestration-01b | External controllers can start, observe, stop, resume/fork and hand off exact project/chat turns with visible ownership and status. | Complete: atomic same-project ownership, owner-only wait/Stop, reconnect, stale credential, concurrent claim, revocation, revision-bound handoff, restart migration and proof-gated native release tests pass; strict API/UI projections agree; 360/1440 px ownership journeys, hidden live reload and process/browser census are green. See [Orchestration-01b handoff](checkpoint-orchestration-01b-handoff.md). |
| Store-06c | Installed MCP servers can be started under exact project scope and consequential tool calls enter the native approval lane. | Automated implementation and read-only live gates complete: inert reads, exact start/stop, host ownership, schema and binding revalidation, per-call approval, denial, concurrency, timeout/cancel, malformed/oversized result, cleanup, receipt privacy, Agent activity, protected hidden reload, responsive no-plan Store review and process census pass. Owner authority-increasing clicks remain. |
| Store-06d | Configuration-bearing local MCPB plans are inspected, configured and recovered without retaining plaintext values or accidentally executing the package. | Automated implementation complete: strict v0.3/v0.4 scalar `user_config` inspection, vault-backed required values, install/start just-in-time resolution, exact invalidation, schema-27 restart migration, private confirmed HTTP/UI contracts, 151-test MCP regression, 2,504-test frontend regression, build, privacy scan and hidden loopback reload pass. Owner protected click-through remains. See [Store-06d handoff](checkpoint-mcp-store-06d-handoff.md). |
| Store-06e | The MCP Store and Agent tool drawer expose search, detail, install state, permissions, health, project tool selection and actual call evidence without crowding the chat. | Complete through 06e.4: exact per-call approval/activity/result ordering, denial/Stop/interruption truth, retained-history privacy, keyboard accessibility and 360/1440 px layouts are green. Owner protected clicks remain. See [Store-06e.4 handoff](checkpoint-mcp-store-06e-4-handoff.md). |
| Store-07 | Malicious metadata, transports, schemas and process behavior fail closed without leaking data or leaving children. | Automated complete through Store-07e. Registry presentation, redirect/DNS/proxy/TLS/stream hostility, local process containment, schema/replay, exact vault binding, canary non-disclosure and project/chat/client isolation are green. Owner trusted-MCP click-through remains Acceptance-01. See [Store-07a handoff](checkpoint-mcp-store-07a-handoff.md), [Store-07b handoff](checkpoint-mcp-store-07b-handoff.md), [Store-07c handoff](checkpoint-mcp-store-07c-handoff.md), [Store-07d handoff](checkpoint-mcp-store-07d-handoff.md), and [Store-07e handoff](checkpoint-mcp-store-07e-handoff.md). |
| Converge-05a | A trusted local MCPB has one fail-closed, content-free lifecycle receipt in the ordinary Agent/Store UI. | Automated instrumentation complete: exact plan/project/chat/snapshot/host binding; fresh approved call; stop; update; rollback; retained-generation cleanup; uninstall; cross-scope/stale/out-of-order refusal; settings-unmount persistence and responsive tests. Packaged third-party execution remains owner-gated. See [handoff](checkpoint-converge-05a-handoff.md). |
| Converge-05b | One external controller proves the complete governed Agent lifecycle without inheriting native approval authority. | Automated instrumentation complete: a page-owned ten-step receipt is exact-project/chat/credential/process bound; in-flight admission, sequence gaps, Stop, reconnect without resubmission, two-party handoff, revoke/refusal and native cleanup are fail-closed. Current external-client owner execution remains pending. See [handoff](checkpoint-converge-05b-handoff.md). |
| Converge-06 | Primary navigation is simplified into Core, Review and Labs while metric counts remain truthful and separately presented. | Automated implementation complete; owner visual review pending. Existing 39 operational/task, 20 canonical and 10 historical definitions remain separate, including the 20/16/4 presentation; no new calculators/adapters or scientific-validity claim. Data sources paging/disclosure and selection behavior are delivered. See [handoff](checkpoint-converge-06-handoff.md). |
| Acceptance-01 | Previously automated Agent, Runtime, Workspace and Store milestones receive the remaining physical owner evidence without reopening their scope. | Retained-chat restart; real CPU/GPU/split admission; model switch/unload and VRAM release; native picker/confirmation; workspace and Store click ledgers. |
| Sweep-01a | Every route and interactive element has an inventory tied to a real contract and test. Dead, duplicated and misleading controls are fixed or explicitly gated. | Route/control/state matrix; click and keyboard automation; no unexplained disabled controls; no console errors. |
| Sweep-01b | The application uses one coherent responsive design system for hierarchy, panes, icons, focus, status, empty/loading/error states and reduced motion. | 320/360/768/1440 px visual matrix, forced colors, keyboard order and automated accessibility checks. |
| Sweep-01c | Long histories, catalogs, trees and event streams remain usable and truthful under load. | Pagination/virtualization, cancellation, stale-response and layout-shift tests against bounded synthetic stress fixtures. |
| Release-01a | Data migrations, interrupted-operation reconciliation, retention, diagnostics and process cleanup are production-safe. | Active through 01a.2b: migration and interrupted-operation reconciliation are automated complete, with full gates and a hidden live reload at one listener and zero model processes. Crash/start/stop process composition stays pending in 01a.3. See [Release-01a.2b handoff](checkpoint-release-01a-2b-handoff.md). |
| Release-01b.1 | Users see truthful update availability in the left sidebar and can download only an immutable, signed, newer release into private staging. | **C07b.4 staged-review automated slice complete; release remains partial**: v2 fenced status/check/stage/cancel/retry, bounded progress, cleanup recovery, default no-egress UI, private update-root hardening, durable replay CAS, deterministic build-manifest validation, and C07b.3 read-only MSIX identity/digest/signer-pin verification are synthetic-tested. C07b.4 wires v3 explicit package pins to review of the authenticated fixed `artifact.staged` candidate, with fenced verified/rejected results only, no durable verified badge, and no apply capability. Production release identity/signing, real native acceptance, installer handoff, relaunch, and rollback remain open. See [C07b.4 handoff](checkpoint-converge-07b4-handoff.md). |
| Release-01b.2 | A reviewed staged update can close the exact owned app/process tree, install, relaunch and recover without corrupting the prior version or user data. | Native consequence preview, installer signature recheck, exact process shutdown, atomic handoff to a minimal updater, interruption matrix, rollback/recovery receipt, one relaunched listener, zero orphan descendants and no visible console storm. |
| Release-01b.3 | The installed Windows application behaves like the validated development stack and the representative owner journey has no hidden workaround. | Production-package install/start/update/reload/shutdown smoke; privacy/API/build gates; signed owner acceptance checklist. |

### Acceptance debt that remains visible

Automated completion does not erase physical checks that need the owner's real
machine or judgment. The following items stay on the release board while new
implementation continues:

- Agent-11/12: retained project/chat restart and subjective conversation-layout
  review;
- Runtime-01: an explicitly approved real CPU, GPU and supported split run,
  model switch, unload and accelerator-memory release;
- Workspace-01: native picker/confirmation plus create/edit/move/test/recover
  walkthrough;
- Store-05/06: native confirmation and final Store-to-Agent tool-use review;
- each finished visual checkpoint: the short click-later list recorded in its
  handoff.

### Remaining delivery packets

The remaining milestones are deliberately divided into reviewable packets. A
packet may be split when a newly discovered safety boundary demands it, but it
may not absorb unrelated work merely to keep implementation moving.

| Packet | Bounded product outcome | Primary evidence gate |
| --- | --- | --- |
| Store-06e.1 | Complete. Establish the Store/chat information architecture: Store lives in a focused management view; the Agent keeps a compact project tool drawer; advanced lifecycle/configuration moves behind details. | 23 focused Store tests, 36 Store/layout contracts, 475 Agent tests, 2,506 full frontend tests, 360/1440 px rendered journeys, production build, privacy scan and live loopback/browser/process evidence pass. See [handoff](checkpoint-mcp-store-06e-1-handoff.md). |
| Store-06e.2 | Complete. Ship source-provenanced logo tiles, search/filter/sort, trustworthy details, compatibility, install/update/rollback/uninstall state and explicit empty/loading/offline/error recovery. | 29 focused Store tests, 42 Store/layout contracts, 26 backend Registry/icon checks, 20 strict frontend contracts, 481 Agent tests, 2,512 full frontend tests, 360/1440 px rendered journeys, build, privacy scan and live read-only Store/process evidence pass. See [handoff](checkpoint-mcp-store-06e-2-handoff.md). |
| Store-06e.3 | Complete. Reconcile permissions, health, project admission and tool selection between Store, project and active chat without stale authority. | 47 focused MCP UI tests, 497 Agent tests, 48 strict contract/transport tests, 92 backend state-machine tests, 2,528 full frontend tests, 360/1440 px chat-to-Store journeys, production build, privacy scan and loopback/process/GPU census pass. See [handoff](checkpoint-mcp-store-06e-3-handoff.md). |
| Store-06e.4 | Complete. Finish the in-chat tool experience: concise tool availability, exact approval/activity/result cards, settings escape hatch and no chat overcrowding. | 66 direct receipt/privacy tests, 168 affected backend tests, 186 affected frontend tests, 507 complete Agent tests, 360/1440 px keyboard/result journeys, generated API check, production build, privacy scan and loopback/process/GPU census pass. See [handoff](checkpoint-mcp-store-06e-4-handoff.md). |
| Store-07a | Complete. Registry and presentation hostility: poisoned metadata, icons, pagination, identity/version collisions and source disagreement. | 35 focused backend tests, 184 affected backend tests, 64 focused frontend tests, 224 affected contract tests, 514 Agent tests, normal and hostile 360/1440 px browser journeys, API/build/privacy gates and live reload/process evidence pass. See [handoff](checkpoint-mcp-store-07a-handoff.md). |
| Store-07b | Complete. Remote transport hostility: redirects, proxy inheritance, private/reserved DNS, rebinding, TLS/origin drift, SSE/HTTP hangs and oversized streams. | 121 focused backend tests, 202 core backend tests, 364 complete MCP regressions, 214 focused frontend tests, 515 Agent tests, API/build/privacy gates and live loopback/network/GPU evidence pass. No unauthorized connection is retained. See [handoff](checkpoint-mcp-store-07b-handoff.md). |
| Store-07c | Complete. Local process hostility: startup crash, stderr flood, process-tree escape, timeout, Stop race, restart and cleanup uncertainty. | 464-test combined MCP/process matrix, 102 Windows lifecycle/distribution tests, 734 frontend tests, build/API/privacy gates and a 10-second loopback/window/network/GPU census pass. See [handoff](checkpoint-mcp-store-07c-handoff.md). |
| Store-07d | Complete. Tool/schema hostility: recursive/schema bombs, alias collisions, malformed arguments/results, output flood and approval replay. | 476 affected backend tests, 803 affected frontend tests, build/API/compile/privacy gates and a read-only `/agent` smoke pass. Fresh approval claims are atomic and one-use. See [handoff](checkpoint-mcp-store-07d-handoff.md). |
| Store-07e | **Complete.** Secret and scope hostility: value/log leakage, stale vault references, cross-project/cross-chat access and concurrent clients. | Database/log/API/UI canaries, project/chat/client isolation, restart reconciliation, complete backend/frontend gates and a hidden live reload pass. See [handoff](checkpoint-mcp-store-07e-handoff.md). |
| Acceptance-01 | Collect only physical evidence automation cannot supply: retained-chat restart, native dialogs, real model placement/switch/unload/VRAM, workspace action and trusted MCP click-through. | Owner-observed receipts recorded without using private transcript content. |
| Sweep-01a | **Automated complete.** Twenty-two typed route families, 27 direct shapes, shared rendered/source control contracts, complete regressions and the rebuilt loopback-browser pass are green. | Route/control/state ledger, synthetic and local-real traversal, zero unexplained disabled controls or console errors, and a clean listener/process/VRAM census. See [handoff](checkpoint-sweep-01a-handoff.md) and [state recovery ledger](sweep-01a-state-recovery-ledger.md). |
| Sweep-01b | **Automated complete through 01b.4; owner review queued.** Shared hierarchy, typography, spacing, icons, status and primary-action ownership cover Agent and every inventoried route family. Twenty-six route shapes pass 208 settled audits at 320/360/768/1440 px in both themes; keyboard/focus, screen-reader names, contrast, forced colors and reduced motion are green. | Preserve the complete matrix while Sweep-01c proceeds. See [entry](checkpoint-sweep-01b-entry.md), [01b.1 handoff](checkpoint-sweep-01b-1-handoff.md), [01b.2 handoff](checkpoint-sweep-01b-2-handoff.md), [01b.3 handoff](checkpoint-sweep-01b-3-handoff.md) and [01b.4 handoff](checkpoint-sweep-01b-4-handoff.md). |
| Sweep-01c | **Automated complete through 01c.3; owner review queued.** Large loaded collections have fixed render pages or deterministic timeline sampling; Agent projects/chats/artifacts use strict immutable paging; maximum retained history has a fixed mounted window; and stale, cancelled or out-of-order continuations fail closed. | Preserve the maximum synthetic node, latency, overflow and settled-layout-shift gates while release work proceeds. See [entry](checkpoint-sweep-01c-entry.md), [01c.1 handoff](checkpoint-sweep-01c-1-handoff.md), [01c.2 handoff](checkpoint-sweep-01c-2-handoff.md) and [01c.3 handoff](checkpoint-sweep-01c-3-handoff.md). |
| Release-01a.1 | **Automated complete; owner click-later review queued.** Give the Agent project/chat catalog exact checksummed migration provenance and fail-closed recovery from every supported schema. | Schemas 1–29 upgrade to 30; corruption and forced interruption remain non-mutating; full backend/frontend/OpenAPI/build/privacy gates, responsive health journeys and a hidden live reload pass. See [handoff](checkpoint-release-01a-1-handoff.md). |
| Release-01a.2a | **Automated complete; optional owner continuity review queued.** Inventory and prove the remaining auxiliary SQLite migration boundaries. | Shared-folder, central-annotation, social and paid-product supported heads upgrade to exact checksummed heads; corruption and forced late failure remain non-mutating; 5,193 backend tests, privacy/static gates and a hidden reload pass. See [handoff](checkpoint-release-01a-2a-handoff.md). |
| Release-01a.2b | **Automated complete; optional owner continuity review queued.** Prove interrupted-operation reconciliation across restart. | Downloads settle only from exact registry/byte evidence; artifact transactions roll back/replay exactly once; prior-run MCP claims receive terminal content-free receipts; stale controller authority becomes explicit uncertainty. 5,215 backend and 2,723 frontend tests, privacy/build and hidden reload gates pass. See [handoff](checkpoint-release-01a-2b-handoff.md). |
| Agent-12d | **Automated complete; owner visual and real-runtime review queued.** Put the existing model/runtime, exact context, media, prompt-improvement and Send/Stop controls in one capability-aware chat composer while keeping projects/chats in the rail. | 221 focused Agent tests, complete frontend/backend/privacy/API/build gates, forced-colors and narrow-layout contracts, one loopback listener and zero model processes. See [handoff](checkpoint-agent-12d-handoff.md). |
| Agent-12e | **Automated complete; owner browser/native click review queued.** Open a workspace chat with no model, then choose and bind the model from the integrated composer; show truthful manual path entry in a browser and keep Browse in the protected native desktop window. | 163 Agent tests, 2,729 complete frontend tests, model-null, running-model non-inheritance, catalogue-loading/failure, selection-leak, browser/native picker, backend, build, API and privacy gates; one loopback listener and zero model processes. See [handoff](checkpoint-agent-12e-handoff.md). |
| Agent-12f | **Automated complete; owner narrow-window visual review queued.** Keep Model & context usable in a short composer, make start/switch/bind consequences explicit, and replace ambiguous prompt improvement with a no-send review. | 205 relevant Agent/runtime/layout tests, production build, API/privacy gates and a live loopback DOM reload; model choice, pending state, upward viewport-bounded scrolling, Close/Escape/outside dismissal, focus restoration and no-send prompt review pass. See [handoff](checkpoint-agent-12f-handoff.md). |
| Agent-12g | **Automated complete; owner Windows dialog click queued.** Let the ordinary authenticated localhost Agent page browse the PC for a workspace without a model or pasted path, while keeping selection separate from scanning, session creation and protected authority. | Picker concurrency/error tests, same-origin/CSRF/token rejection, strict transport parsing, selection/cancel/busy/native-fallback component tests, production build, API/privacy gates and a hidden one-listener live reload pass. See [handoff](checkpoint-agent-12g-handoff.md). |
| Release-01a.3 | **Automated complete; owner click-later review queued.** Prove combined process ownership and cleanup under repeated start, stop, crash, timeout and listener collision. | Atomic Windows Job ownership or POSIX process groups, bounded helper I/O and process counts, exact cleanup evidence, 5,232 backend and 2,733 frontend tests, privacy/build/API gates and a hidden one-listener collision smoke pass. See [entry](checkpoint-release-01a-3-entry.md) and [handoff](checkpoint-release-01a-3-handoff.md). |
| Release-01b.1 | **C07b.4 staged-review automated slice complete.** The left-sidebar/compact-navigation control, v2 fenced signed-manifest status, bounded artifact staging, progress/cancel/retry, interrupted-download recovery, private-root hardening, and replay evidence are synthetic-tested; v3 explicit package pins now wire the fixed authenticated `artifact.staged` candidate to fenced verified/rejected review only. Default unconfigured mode remains network-silent, verified review is not persisted, and apply remains unavailable. | Remaining: owner-controlled production release host/key and signed package, real publisher/native acceptance, installer handoff, packaged relaunch/recovery, rollback, and production trust. See [C07b.4 handoff](checkpoint-converge-07b4-handoff.md). |
| Release-01b.2 | Apply a reviewed staged update, stop the exact owned process tree, reinstall, reopen and recover or roll back truthfully. | Native review; updater process ownership; installer revalidation; crash/power-loss boundary matrix; prior-version recovery; preserved user data; one listener and zero orphan child/terminal/model processes after relaunch. |
| Release-01b.3 | Prove the installed Windows application matches the validated stack and complete the north-star journey. | Packaged install/start/update/reload/shutdown smoke and explicit owner sign-off with no undocumented workaround. |

### Checkpoint control loop

Every packet uses the same six visible checkpoints so progress and token spend
remain reviewable:

1. **Entry snapshot:** state the user-visible problem, current evidence, frozen
   scope, exclusions, risk and expected files before broad edits.
2. **Implementation checkpoint:** make only the bounded behavior/API/UI changes;
   record newly discovered unrelated work in the later packet ledger.
3. **Focused proof:** run success, refusal, cancellation, stale/retry and privacy
   tests while the slice is changing. Do not repeatedly rerun broad suites.
4. **Independent gate:** run the affected backend/frontend integration matrix,
   strict contracts, build and privacy scanner once the slice is coherent.
5. **Protected reload:** restart the loopback app hidden, verify one listener,
   zero surprise model/MCP/terminal children and exercise the live route without
   inventing unavailable authority.
6. **Handoff:** update this board and write one compact receipt containing exact
   passes, remaining locks, at most five owner clicks and exactly one next packet.

No later packet starts with ambiguous red tests, undocumented process state or
a missing handoff. Owner-only acceptance may remain visibly pending while a
non-overlapping implementation packet proceeds.

### Anti-loop execution rules

1. Exactly one implementation checkpoint is active. Research may prepare later
   tests, but later production code does not drift into the active slice.
2. The checkpoint starts with a frozen user outcome, touched surfaces, explicit
   exclusions and adversarial acceptance matrix.
3. Focused tests run while code changes. The broad affected regression suite
   runs once after the slice is coherent, and is not rerun without a relevant
   change or a previously red result.
4. A regression discovered on the active path is repaired and recorded. An
   unrelated improvement is added to the named future checkpoint instead of
   expanding the current one invisibly.
5. The production frontend is built and the protected app is reloaded once at
   the end of the slice. Process, listener, model/VRAM and console evidence is
   captured after that reload.
6. Every handoff records exact pass counts, remaining limitations and a maximum
   five-action owner checklist. Unknown evidence remains pending, never passed.
7. No commit, push, real model download, destructive real-data action or remote
   disclosure is inferred from checkpoint approval; each needs its own explicit
   authority when applicable.
8. The next checkpoint begins only after the previous checkpoint has a coherent
   handoff and its state is reflected on this board. Owner visual review may stay
   pending while unrelated implementation proceeds.

Only one milestone is implementation-active at a time. A later milestone may be
researched or test-inventoried, but it does not receive broad code changes until
the current checkpoint has a coherent handoff. This is the guard against the
previous loop where many surfaces changed without a stable review point.

## Definition of done for every implementation checkpoint

A checkpoint is complete only when all applicable layers below are green:

1. **Behavior:** the real backend state machine implements success, refusal,
   cancellation, retry, stale-request and interrupted-operation outcomes.
2. **Persistence:** restart, migration, idempotency and recovery behavior are
   explicit; memory-only behavior is labelled as such.
3. **Contract:** strict request/response parsing, OpenAPI export and generated
   frontend types agree. Unexpected or contradictory fields fail closed.
4. **Interface:** loading, empty, ready, disabled, approval, stopping, failed,
   cleanup-uncertain and completed states are understandable and keyboard
   reachable at narrow and desktop widths.
5. **Evidence:** unit, integration, failure-injection and browser tests cover
   the feature from independent angles. A passing happy path alone is not an
   acceptance result.
6. **Privacy and safety:** only synthetic fixtures are used; diagnostics remain
   content-free; protected effects are exact and reviewed; no private provider
   data or credential store is inspected.
7. **Runtime hygiene:** owned listeners, model workers, command trees and MCP
   hosts have bounded lifecycle evidence. Relevant GPU/process cleanup is
   checked, and no visible terminal window is spawned.
8. **Integration:** the production frontend builds, the protected app is
   reloaded once for the coherent slice and the live route is smoke-tested.
9. **Handoff:** the checkpoint ledger records what changed, exact test receipts,
   limitations, what the user should click later and the next milestone.

## Owner interaction budget

Work continues autonomously for code, synthetic fixtures, migrations, contract
tests, browser automation, accessibility checks, failure injection, privacy
scans, builds and loopback smoke tests. The owner is needed only where evidence
cannot truthfully be synthesized:

- subjective visual preference after a checkpoint reload;
- native picker/confirmation clicks that automation cannot safely perform;
- an explicitly approved real model download or CPU/GPU/VRAM acceptance run;
- login or consent for a real external provider/client handshake;
- destructive handling of real user-created projects, chats, models or files;
- final release sign-off.

An unavailable owner check does not stall unrelated implementation. It is
recorded as **owner acceptance pending**, never silently reported as passed.

## Checkpoint report shown to the owner

Each checkpoint update uses the same compact order:

1. **Outcome:** the user-visible capability that now works.
2. **Changed:** the bounded implementation and UI surfaces touched.
3. **Validated:** exact automated receipts and live process/runtime evidence.
4. **Still locked:** behavior intentionally unavailable or awaiting acceptance.
5. **Click later:** a short numbered manual review, normally no more than five
   actions.
6. **Next:** one proposed checkpoint, requiring explicit approval before broad
   work moves to it.

## Workstream A — durable Agent projects and chats

Required experience:

- A left rail of durable projects and chats with create, switch, rename, search,
  pin, archive, restore and explicit delete/trash behavior.
- Chats survive app restart according to the selected retention mode. Project,
  chat, branch and fork lineage is visible and recoverable.
- New chat, Stop, retry, fork/branch, export and close have deterministic state
  machines and never duplicate turns after retry or reload.
- The main conversation remains the visual priority. Settings, files, artifacts,
  diagnostics and permissions live in drawers or secondary panes.
- Streaming text, Markdown, code blocks, copy actions, citations, diffs,
  attachments, tool cards, progress, errors and completion evidence render in a
  consistent timeline.

Acceptance evidence:

- SQLite restart/migration/idempotency tests;
- desktop-width, narrow-width and keyboard-accessibility UI tests;
- real browser create/switch/reload/archive/restore/fork/export walkthrough;
- zero conversation-content crossover between projects or chats.

## Workstream B — local model lifecycle and broad model use

Required experience:

- Discover or import compatible Hugging Face model artifacts with revision,
  license, tokenizer and runtime provenance. Never enable `trust_remote_code` by
  default and never vendor model weights.
- Download with progress, pause/cancel/retry, integrity checks, disk-space truth
  and recoverable partial-download cleanup.
- Select CPU, GPU or bounded GPU/CPU placement when the runtime supports it.
  Unsupported combinations are disabled with a reason.
- Start, health-check, chat, Stop and unload are explicit. Switching models first
  closes the old session/runtime and verifies VRAM/process release before loading
  the replacement.
- Show truthful context-window capacity and usage as known, estimated or unknown.
- Negotiate text, image and audio input only when the selected model/runtime
  declares and passes that capability.

Acceptance evidence:

- synthetic runtime matrices plus at least one owner-approved real CPU and GPU
  model walkthrough;
- timeout, crash, cancellation, out-of-memory and switch-under-load tests;
- before/after process and accelerator-memory cleanup evidence;
- no visible terminal windows.

## Workstream C — coding workspace and reviewed file operations

Required experience:

- Choose one absolute workspace with a native folder picker and retain only the
  project-scoped reference the user approved.
- Bounded tree/search/read for admitted files; exact UTF-8 editor; rich diff;
  create, edit, multi-file transaction, new folder, no-overwrite move/rename and
  recoverable deletion where supported.
- The agent can propose changes and tests, but every publication is revision-
  bound and reviewable. Multi-file publication is failure-atomic within its
  documented boundary, with truthful rollback or cleanup quarantine.
- File-change, command and web effects appear as distinct timeline cards with
  status, duration, evidence and approval state.
- Git metadata is local and bounded. No private remote, credential or unrelated
  repository content enters logs or model context.

Acceptance evidence:

- adversarial path, symlink, race, stale revision, partial failure and restart
  tests;
- objective read-back of every applied file effect;
- owner walkthrough: create, edit, move, diff, run tests, revert/recover and open
  the resulting artifact.

## Workstream D — artifacts, documents and multimodal chat

Required experience:

- Image, audio and supported document attachments have upload/record controls,
  previews, validation, size/type limits and explicit model-capability routing.
- Generated files become versioned artifact cards linked to their producing turn
  and objective filesystem evidence.
- Safe viewers exist for text, code, images, PDF and other explicitly supported
  formats. Active content is never executed inside a viewer.
- Artifact open, download/export, compare versions, rename/archive and recovery
  behavior are explicit.

Acceptance evidence:

- malformed, oversized, spoofed MIME, truncated, encrypted and unsupported-file
  tests;
- viewer render tests at desktop and narrow widths;
- generated-file link, reload and exact-byte read-back tests.

## Workstream E — reasoning, activity and agent feedback

Required experience:

- Show a compact state header: ready, thinking, waiting for approval, running a
  tool, streaming, stopping, failed, cleanup uncertain or complete.
- Render model-provided reasoning summaries or structured plans when the runtime
  supplies them. Label inferred summaries separately; never label hidden chain
  of thought as available.
- Tool and command cards show what class of action is requested, why approval is
  needed, bounded input summaries, progress, result evidence and cleanup state.
- Long operations provide visible progress or heartbeat evidence and a working
  Stop control. Empty or silent panels are never used as success signals.

Acceptance evidence:

- event ordering, reconnect, duplicate, late-event and Stop-race tests;
- UI tests for every state and failure class;
- real-model walkthrough with at least one file proposal and one command.

## Workstream F — external Codex/Claude/agent orchestration

Required experience:

- Keep the direct loopback `/mcp/agent` direction distinct from the third-party
  MCP Store direction.
- Create scoped, revocable Agent connections with one-time private setup material
  for Codex, Claude Code and provider-neutral MCP clients.
- External controllers can discover projects/chats, start bounded turns, inspect
  events, propose reviewed file changes, fork/export sessions and coordinate
  local models only within their granted scopes.
- Native approvals cannot be forged or delegated through MCP. Revocation takes
  effect immediately and restart behavior is explicit.
- Support a parent agent orchestrating multiple local sessions without sharing
  chat content, credentials, workspace authority or pending approvals between
  them.

Acceptance evidence:

- direct HTTP and MCP contract tests for two simultaneous clients, revocation,
  reconnect, stale token, cross-project isolation and Stop;
- synthetic Codex/Claude configuration round trips with no bridge terminal;
- owner-approved live orchestration walkthrough.

## Workstream G — MCP Store discovery and lifecycle

Required experience:

- Search the Official MCP Registry first. Additional portal adapters use
  documented APIs or permitted feeds, retain source/provenance/fetch time and do
  not treat popularity or listing as a security approval.
- Deduplicate exact identities and versions. Small tiles show a safely proxied
  raster logo or deterministic fallback, name, publisher, description, source,
  version, local/remote transport and current management state.
- Detail review shows provenance, license/integrity evidence, declared inputs,
  permissions, risks and compatibility evidence without exposing endpoint paths,
  secrets or tool data.
- Install, update, uninstall and rollback/cleanup are separate native-confirmed
  state machines. Buttons reflect the real backend state and are idempotent.
- Local stdio servers use hidden, atomically owned process trees. Remote servers
  use exact reviewed HTTPS origins, public-only pinned DNS, no proxy/redirect and
  bounded I/O.
- Tool schemas are admitted separately from installation. Each Agent project
  selects exact servers, permissions and tools. Consequential tool calls receive
  per-action review unless a narrowly scoped remembered policy explicitly covers
  them.
- Store pages show health, update availability, recent content-free failures,
  tool count/schema revision and whether a host is stopped or running.

Acceptance evidence:

- malicious Registry metadata, logo and source-adapter fixtures;
- install/update/uninstall crash, retry, restart and rollback tests;
- modern/legacy stdio, Streamable HTTP and SSE protocol tests;
- schema bomb, pagination, response-size, redirect, DNS rebinding, credential,
  stderr flood, child escape, hang, crash and Stop tests;
- zero visible terminal or orphan process; no tool result requested by a health
  probe; strict project isolation for actual tool calls.

Current status: Store-01 discovery, Store-02 exact review, Store-03 durable
plans, Store-04 guarded compatibility checks, Store-05a exact durable remote
activation/deactivation and Store-05b checksum-pinned isolated MCPB installation
are implemented. Store-05c update/uninstall/rollback/cleanup is also complete,
with automated and protected live gates passed and owner UI review pending.
Store-06a exact tool review and project admission is complete. Store-06c adds an
inert-until-confirmed app-run supervisor, exact project host controls, fresh
approval for every admitted call, bounded result projection, content-free
receipts, stale-authority fail-closed behavior, and synchronous cleanup on
cancel or unsafe results. Its automated and read-only live gates are green;
authority-increasing owner clicks remain. Store-06d adds exact non-executing
MCPB configuration inspection, content-free durable schema evidence,
vault-backed just-in-time required values, strict invalidation and schema-27
restart migration. Its automated, build, privacy and hidden-reload gates are
green; protected click-through remains. Store-06e management/chat UX is
automated-complete through 06e.4; Store-07 adversarial acceptance is
automated-complete through 07e, with trusted protected click-through retained
for Acceptance-01. See the
[Store-05c handoff](checkpoint-mcp-store-05c-progress.md) and
[Store-06c handoff](checkpoint-mcp-store-06c-handoff.md) and
[Store-06d handoff](checkpoint-mcp-store-06d-handoff.md) for current evidence and
the authority that remains deliberately locked.

## Workstream H — whole-application UI/UX completion sweep

Required experience:

- Audit every route, card, button, checkbox, picker, dialog, drawer, empty state,
  loading state and error state against its backend contract.
- Remove duplicated icons, misleading affordances, dead controls, overcrowding,
  inconsistent terminology and layout shifts.
- Establish one icon system, spacing/type scale, focus system, status palette,
  responsive pane behavior and reusable primitives.
- Keyboard, screen-reader, contrast, reduced-motion and 320 px behavior are part
  of correctness, not polish deferred after release.

Acceptance evidence:

- route inventory mapped to interactive tests;
- screenshot/browser matrix for desktop and narrow widths;
- automated accessibility checks plus manual keyboard walkthrough;
- every intentionally unavailable control explains the next gate.

## Workstream I — privacy, recovery, performance and distribution

Required experience:

- Versioned migrations, bounded retention, content-free diagnostics and recovery
  states for interrupted model, Agent, file and MCP operations.
- Startup and shutdown cannot recursively spawn app windows or leave listeners,
  workers, models, commands or MCP hosts behind.
- Large histories, catalogs, file trees and event streams remain responsive via
  pagination, virtualization or bounded summaries.
- Packaged Windows behavior matches development behavior: folder picker,
  confirmations, hidden processes, loopback listener and cleanup.

Acceptance evidence:

- full backend/frontend/privacy/OpenAPI/build suites;
- migration from every supported schema version;
- cold start, reload, shutdown and crash-recovery process census;
- production-package smoke test on the owner's machine.

## Execution order

The 2026-09-04 audit reopened historical completion claims. Existing Agent,
Runtime, Workspace, Artifact, Orchestration and Store implementations remain
valuable regression obligations, but none may skip the current evidence ladder.

1. **Converge-01 — truth and reachability repair (complete).** The six stable
   Agent browser failures, live metric-operability composition, static readiness
   claim and production web-tool no-op are repaired; the result remains covered
   by the current 166/166 serial standard browser gate.
2. **Converge-02 — genuine local-stack harness (complete).** Sixteen critical
   built-frontend journeys now run against a temporary synthetic real backend
   with no application-route interception. The old suite is named
   `intercepted-contract` and is green at 41/41, while the independent standard
   suite remains 166/166. The real gate verifies cleanup after every run. See
   [handoff](checkpoint-converge-02-handoff.md).
3. **Converge-03 — Agent information architecture (automated implementation
   complete; owner visual review pending).** The chat and composer own the live
   viewport, secondary controls use coherent disclosures/drawers, competing
   rail scroll regions and duplicate healthy runtime status are removed, file
   icons use the shared system, and conversation rendering is split along visible
   boundaries. Current evidence is 166/166 standard browser, 41/41 intercepted
   contract, 16/16 real loopback and 87/87 focused backend/harness tests. See
   [handoff](checkpoint-converge-03-handoff.md).
4. **Converge-04 — real packaged Agent core loop (automated instrumentation
   complete; owner execution pending).** The fail-closed page-owned ledger now
   requires recovered history, workspace admission, two distinct ready models,
   completed and stopped turns, approved write and command, review, a
   successfully rendered artifact, truthful context and final coordinator
   cleanup. The physical probe now requires hidden-window/process-exit/GPU
   cleanup evidence. Collect the remaining native picker/approval,
   CPU/GPU/supported split, package restart, VRAM and terminal-census evidence.
   Production web remains excluded when no governed fetcher is composed. See
   [handoff](checkpoint-converge-04-handoff.md).
5. **Converge-05 — trusted MCP and external-client acceptance (05a and 05b
   automated instrumentation complete; owner runs pending).** The exact MCPB
   and external-controller ledgers remain fail-closed and keep unsupported
   Registry formats browse-only. See the [05a handoff](checkpoint-converge-05a-handoff.md)
   and [05b handoff](checkpoint-converge-05b-handoff.md).
6. **Converge-06 — metric validity and surface simplification (automated
   implementation complete; owner visual review pending).** Separate the
   existing 39 operational/task definitions from the 20 canonical coaching
   contracts and 10 historical lexical rules; preserve the 20/16/4 presentation,
   retire legacy default duplication, resolve or visibly block the four
   provider-adapter gaps, and require a representative human holdout for
   calibration claims. Core/Review/Labs navigation and Data sources paging,
   disclosure and exact-selection behavior are delivered.
7. **Converge-07 — signed Windows update and final release.** C07a’s automated
   staging foundation is validated/complete and C07b.1’s bounded private-root
   and replay-security slice is implemented; C07b.2’s offline manifest
   acceptance is complete; C07b.3’s standalone read-only MSIX preflight focused
   acceptance and automated owning validation are complete; C07b.4 connects
   the fixed authenticated staged artifact to a verified/rejected review-only
   action with no apply capability. Its automated slice is complete, while C07
   remains partial. Build artifact staging, reviewed apply/relaunch, rollback,
   signed packaging and the connected north-star journey remain.

At each numbered boundary the board, evidence ledger and click-later list are
updated before implementation advances. If a test exposes a regression in a
previously complete milestone, that regression becomes the bounded repair inside
the current dependency checkpoint; it is never hidden as historical debt.

## Converge-06 review record

Converge-06 is **automated implementation complete; owner visual review
pending**. Core, Review and Labs now have an explicit boundary, while the
existing 39 operational/task definitions, 20 canonical coaching contracts and
10 historical lexical rules remain separate, including the 20/16/4
presentation. Data sources delivers 12 projects per page, collapsed lazy session
lists, 20 rows per expanded page, metadata-only search, accurate hidden
selections, Clear selection and transport-generation resets. No new
calculators/adapters or calibration/scientific-validity claim is made.

Final evidence: root calibration/gate/report/ratings matrix **140/140**;
Terra metric **69/69 frontend** and **35/35 backend contract**; root LocalSources
and ClaudeSource **26/26**. Root's original App run had **117 pass and 3
failures**; the owning-file rerun resolved them at **25/25**, without claiming a
clean full 120-case rerun. Root browser shell/research/metric-context/standalone
is **23/23**; whole-route accessibility is **20/20** across 320/360/768/1440,
light/dark, keyboard, forced-colors and reduced-motion. Browser suites total
**61 distinct cases**; earlier Luna 2-case evidence is not counted again.
Source-maintenance is **2/2** at 360/1440 after root review. Isolated strict
fixture/spec TypeScript, production build and real-loopback **16/16** passed,
with `listener_released=true`, `temporary_state_removed=true`,
`model_runtimes_remaining=0` and `runtime_cleanup_confirmed=true`. API and
privacy checks passed, including root's final post-docwrite rescan; normal git
diff check passed.

The execution workflow is explicit: root reads code, assigns bounded work,
reviews it and independently validates; Terra handles harder scoped work, Luna
handles easier scoped changes, tests and docs, and root does not implement this
packet. Existing privacy, scope, synthetic-fixture and checkpoint rules remain
in force. No model or real data was used; no app restart or reload was
performed, and app on port 8765 was not running when root checked. No commit or
push is claimed. Converge-04 real model/hardware/native and
Converge-05a/05b trusted-MCP/external-client owner evidence remain pending.
C07a automated staging foundation is implemented and validated;
Converge-07 Windows packaging, native installation/relaunch/rollback and final
release evidence remain outstanding. C07b.1 now covers the private
`application-updates` root and durable signed-envelope replay floor, but does
not make the updater installable or usable. See the
[C07a handoff](checkpoint-converge-07a-handoff.md) and
[C07b.1 handoff](checkpoint-converge-07b-handoff.md).

C07b.1’s owning gates are current: 244 backend tests passed with two explicit
Windows symlink-capability skips, all 2,806 frontend tests passed, and rebuilt
production real-loopback browser coverage passed 16/16 with cleanup and
listener-release evidence. Build, API, privacy and diff checks passed. These
are security-slice gates, not publisher, installer, relaunch or rollback proof.

C07b.2’s focused offline acceptance is **17/17 passed**. It rejects duplicate,
case-insensitive, prefix-ambiguous and Windows-ambiguous staged names, refuses
hardlinked leaves, bounds source reads and collections, preserves deterministic
host-free output, and emits content-free CLI errors. The owning C07b.2 gate is
**172 backend tests passed with one explicit Windows symlink-capability skip**
in 10.68s across the selected build/distribution/private-root/updater/replay/
config/privacy/scanner files; the 17-case file is an overlapping subset. No
frontend, browser, API-contract, build-output or app-reload gate was rerun for
this isolated offline tool change under the active remote-session restriction.
Privacy scanning and normal `git diff --check` passed. No package is declared
distributable; publisher/signing/MSIX, installation, relaunch and rollback
remain open under C07.

C07b.3’s focused standalone read-only MSIX preflight acceptance is **53/53
passed**. It checks authenticated release metadata, exact `X.Y.Z.0` identity
mapping, package digest/size, namespaced XML, bounded archive structure,
signer-pin outcomes and content-free CLI behavior while keeping
`can_install=false`. The root-owned combined gate is **336 passed, 2 Windows
symlink-fixture skips and 1 intentionally deselected native smoke** in 17.21s;
the 53 focused cases, 15 CLI/non-native regressions and 31 fake-native cases
are overlapping subsets. A separate real-Windows unsigned-container smoke
failed closed with successful native close and typed `PackageSignerUnavailable`;
it is not publisher/signing proof or cleanup-failure evidence. No
frontend/browser/API/app-reload gate was rerun, and the preflight is not wired
to the sidebar or `artifact.staged` action. No package is declared
distributable; owner-signed native positive acceptance and the
installer/relaunch/rollback gates remain open.

C07b.4’s automated staged-review slice is complete. The next bounded release
work is the separately authorized owner-native publisher/signing,
installer/relaunch and rollback path. `can_apply=false` remains an invariant;
no PC/app restart, relaunch or install is permitted until separately authorized.
See the [C07b.4 handoff](checkpoint-converge-07b4-handoff.md).

## Final release gate

The finish goal is achieved only when all workstreams above have direct current
evidence, no required feature remains labelled partial or unavailable, every
protected action has the intended review boundary, all automated suites pass,
the production app reloads cleanly, and the owner can complete the representative
Agent + model + files + artifact + MCP + external-orchestrator walkthrough without
using a hidden workaround.
