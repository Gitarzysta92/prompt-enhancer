# Prompt Enhancer owner feature acceptance register

Status: active release contract; Converge-06 automated implementation complete; C07a automated staging foundation validated/complete; C07b.1 automated security slice validated/complete; C07 remains partial
Established: 2026-08-31
Parent goal: [Prompt Enhancer finish goal](prompt-enhancer-finish-goal-2026-08-29.md)

## Purpose

This register translates the owner's requested product experience into small,
testable release obligations. It is not a wishlist and it is not a record of
controls that merely render. Every row marked **Required** must work through the
real local stack, expose truthful states, survive the stated recovery boundary
and have current evidence before Prompt Enhancer is called finished.

The parent finish goal defines privacy, checkpoint discipline and the connected
north-star journey. This register is the feature-level checklist used to prevent
requested behavior from being forgotten during implementation or UI cleanup.

## 2026-09-04 audit override

The [convergence audit](prompt-enhancer-convergence-audit-2026-09-04.md) is the
current evidence source. The `Current state` cells below were written during
earlier implementation checkpoints and are retained for traceability, but a row
that says `Automated complete` is **not** a current release pass. Every such row
is downgraded to `contract evidence exists; revalidation required` unless the
audit and a newer checkpoint explicitly close the contract, zero-interception
loopback, owner and packaged-release gates.

Converge-01 repaired the six reproducible browser failures. Converge-03 then
closed the Agent information-architecture gate and advanced the standard serial
suite to 166/166 while preserving the 41/41 intercepted and 16/16 real-loopback
gates. Live metric-operability response composition, separate contract/loopback/
owner states, and hard refusal of web fetch without a governed fetcher remain
covered. Converge-04 adds a page-owned, fail-closed core-loop receipt and a
physical-probe contract that requires hidden-window, coordinator-idle,
process-exit and accelerator-cleanup evidence. Packaged/native/hardware evidence
remains pending as stated per row. Converge-05a adds a separate page-owned,
content-free trusted-MCP receipt bound to one server, project, chat, plan, tool
snapshot and host instance. It requires retained-generation cleanup between
rollback and uninstall; packaged third-party execution remains pending.
Converge-05b adds an exact project/chat/credential/process-bound controller
receipt across connect, discovery, ownership, streaming, external Stop,
reconnect without resubmission, two-party handoff, revoke, refusal, and settled
native cleanup. Current external-client execution remains pending.

Converge-06 adds a Core/Review/Labs navigation boundary with a native Labs
disclosure and preserves route/deep-link, active-state, icon, update and privacy
behavior. It also corrects presentation of the existing 39 operational/task,
20/16/4 canonical coaching presentation (20 contracts, 16 shipped paths and 4
provider-adapter gaps) and 10 historical lexical definitions; it adds no
calculators, adapters or scientific-validity claim. Data sources now delivers
12 projects per page, collapsed lazy session lists, 20 rows per expanded page,
metadata-only search, accurate hidden selections, Clear selection and
transport-generation resets. Current checkpoint status is automated
implementation complete with owner visual review pending.

Converge-07a adds a bounded signed-manifest download/staging foundation: v2
instance/revision fences, progress, cancel-cleanup polling, failed-step retry,
truthful downloaded-not-installable copy and synthetic responsive evidence.
Current C07a status is **automated foundation validated/complete**; C07
remains partial. Windows DACL hardening, publisher/native installer/MSIX
handoff, relaunch/rollback, public release trust/signing and packaged
north-star evidence remain open. See the
[Converge-07a handoff](checkpoint-converge-07a-handoff.md).

C07b.1 is the bounded private-update-root and replay-security amendment. A
validated trust file may prepare only the fixed direct child; new Windows roots
receive the exact protected user/SYSTEM DACL and existing roots are
inspect-only. Signed-envelope compare-and-swap replay evidence survives
recomposition, while historical expiry stays distinct from current download
eligibility. Invalid trust/templates and quarantined or non-persisting ledgers
remain unconfigured or non-downloadable. The focused synthetic acceptance file
passes 13/13; native publisher/MSIX install, relaunch, rollback and owner UX
remain open. Its owning gates are validated: 244 backend tests passed with two
explicit Windows symlink-capability skips, all 2,806 frontend tests passed and
the rebuilt production real-loopback browser passed 16/16; build, API, privacy
and diff checks passed. See the [C07b.1 handoff](checkpoint-converge-07b-handoff.md).

The user workflow is explicit: root reads code, assigns bounded work, reviews
and independently validates; Terra handles harder scoped work, Luna handles
easier scoped changes, tests and docs, and root does not implement this packet.
Existing privacy, scope, synthetic-fixture and checkpoint rules remain in
force. No model or real data was used for Converge-06.

## Status vocabulary

- **Contract verified:** current unit/component evidence is green with synthetic
  inputs; this is not an end-to-end claim.
- **Loopback integrated:** the built frontend completed the named journey against
  the real temporary local API without route interception.
- **Owner accepted:** native UI, real hardware or named external integration was
  observed and its cleanup receipt recorded.
- **Active:** the only production implementation packet currently changing.
- **Pending/blocked:** a required behavior or evidence level is absent.
- **Release complete:** contract, loopback, owner and packaged evidence are green
  where applicable, with no misleading/no-op control.

No status means “probably works.” Unknown evidence remains pending.

## A. Application shell and lifecycle

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| APP-01 | Starting Prompt Enhancer opens one application instance and exactly one loopback listener. | Repeated launch, reload, shutdown and listener-collision tests; no recursive window creation. | Release-01a/01b | Automated through Release-01a.3; C07b.1 delivers scoped private update-root DACL preparation and replay evidence, while all-application DACL, packaged install/update/relaunch/rollback proof remains pending. See [C07b.1 handoff](checkpoint-converge-07b-handoff.md) |
| APP-02 | Model, command, MCP and helper processes never flash terminal windows. | Hidden-process integration tests plus a real Windows process/window census. | Store-07c, Acceptance-01, Release-01b | Automated Release-01a.3 source-policy, hidden-owned-helper and live server-tree proof is green; packaged owner review remains pending |
| APP-03 | Shutdown stops every owned listener, model, command and MCP descendant or reports cleanup uncertainty truthfully. | Normal, crash, timeout and forced-stop census; zero silently orphaned owned processes. | Store-07c, Release-01a | Automated Release-01a.3 proof is complete for every owned runtime/helper path; packaged updater/relaunch proof remains pending |
| APP-04 | Reload restores durable state without pretending interrupted operations completed. | Supported-schema migrations and restart reconciliation for projects, chats, downloads, artifacts and MCP operations. | Release-01a | Automated complete through Release-01a.2b: exact migrations plus download, artifact, MCP-call/package and controller restart reconciliation are green; owner continuity review queued |
| APP-05 | Navigation, page titles and back/forward behavior preserve the exact selected project and chat. | Route-state, stale-response and direct-link tests at narrow and desktop widths. | Sweep-01a/01b | Automated route and accessibility matrices complete; owner route review pending |

## B. Agent projects, sessions and conversation

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| AGT-01 | Agent is a focused coding-chat workspace, with projects and chats in a navigable rail and secondary controls outside the conversation focus. | 360/768/1440 px hierarchy, keyboard order and owner visual review. | Agent-11, Sweep-01b | Converge-03 automated complete: conversation/composer own the viewport and secondary controls use coherent surfaces; owner visual review pending |
| AGT-02 | Create, browse and switch durable projects and chats. | Restart, duplicate-request, stale-selection and cross-project isolation tests. | Agent-11 | Automated complete; owner review pending |
| AGT-03 | Rename, search, pin, archive, restore, move and explicitly delete chats. | Mutation reconciliation, consequence preview, stale-head and restart tests. | Agent-11 | Automated complete; owner review pending |
| AGT-04 | Fork or branch retained work and export the exact visible history without altering the source chat. | Lineage, idempotency, exact-head and cross-scope tests. | Agent-11 | Automated complete; owner review pending |
| AGT-05 | A visible composer accepts text, supports keyboard send/newline behavior and retains a failed draft. | Empty, disabled, send failure, navigation and accessibility tests. | Agent-12 | Automated complete; owner review pending |
| AGT-06 | Streaming, Stop, retry, edit and regenerate are deterministic and never duplicate or rewind turns. | Late, duplicate, out-of-order, reconnect, Stop-race and unexpected-EOF tests. | Agent-12 | Automated complete; owner review pending |
| AGT-07 | Markdown, code blocks, copy actions, diffs, citations and long responses render legibly. | Safe renderer fixtures, overflow, keyboard and narrow-width tests. | Agent-12, Workspace-01, Sweep-01b | Converge-03 automated complete at narrow/desktop and 720 px height; owner visual review pending |
| AGT-08 | The chat shows ready, thinking, waiting, running, streaming, stopping, failed, cleanup-uncertain and complete states. | Event-order state matrix with screen-reader labels and no silent success state. | Agent-12, Store-06e.4 | Converge-03 removed the duplicate healthy state and enforces one runtime announcer; Converge-04 adds fail-closed lifecycle acceptance; owner runtime review pending |
| AGT-09 | Reasoning display is limited to model-provided summaries, plans and progress; hidden chain of thought is never claimed. | Contract provenance, truthful labels, absent-data and unsafe-content tests. | Agent-12 | Automated complete; owner review pending |
| AGT-10 | Context usage is exact when evidenced and visibly unknown or stale otherwise. | Model/chat/turn identity, compaction, refusal and stale-evidence tests. | Agent-12 | Automated complete; owner review pending |
| AGT-11 | Retained metadata, resumable history and a currently live model session are visually distinct. | Restart, unavailable-runtime, resume/fork and metadata-only route tests. | Agent-11/12, Sweep-01a | Automated route/accessibility core complete; owner restart review pending |

## C. Local model acquisition and runtime

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| MOD-01 | Discover or import a compatible Hugging Face model at an exact revision with provenance, license and runtime requirements. | Pinned-revision, missing-license, incompatible-format and offline tests; `trust_remote_code` remains disabled by default. | Runtime-01, Acceptance-01 | Automated complete; owner review pending |
| MOD-02 | Download with truthful size/progress, pause, resume, retry, cancel, integrity verification and partial cleanup. | Low-disk, disconnect, digest mismatch, restart and owned-partial tests. | Runtime-01 | Automated complete; owner review pending |
| MOD-03 | Choose CPU, GPU or supported CPU/GPU split placement only when current evidence admits it. | Unsupported placement, stale capacity, OOM and admission-race tests. | Runtime-01, Acceptance-01 | Automated complete; physical acceptance pending |
| MOD-04 | Configure supported generation and context parameters with safe defaults and clear limits. | Boundary, unsupported-field, persistence and model-switch reset tests. | Runtime-01, Sweep-01a | Automated core complete; final sweep pending |
| MOD-05 | Start, readiness, health and failure states identify the exact selected model and revision. | Slow start, crash, stale health, wrong-runtime and cancellation tests. | Runtime-01 | Automated complete; physical acceptance pending |
| MOD-06 | Switching models first stops the owned previous runtime and verifies process/VRAM release before declaring the replacement ready. | Switch-under-load, failed cleanup, GPU memory and stale-command tests. | Runtime-01, Acceptance-01 | Contract and loopback evidence green; Converge-04 owner receipt now requires a distinct second ready alias and final latest-runtime cleanup; physical acceptance pending |
| MOD-07 | Stop/unload is visible, bounded and truthful even when cleanup cannot be confirmed. | Double-stop, timeout, descendant escape and accelerator-release tests. | Runtime-01, Acceptance-01 | Contract and loopback evidence green; physical probe v2 now requires coordinator-idle/process-exit/VRAM evidence and fails closed on unknown cleanup; physical acceptance pending |
| MOD-08 | Text, image and audio controls appear only for capabilities the selected model/runtime actually supports. | Modality negotiation, incompatible attachment and model-switch tests. | Artifact-01, Acceptance-01 | Automated complete; owner review pending |

## D. Coding workspace and protected tools

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| WSP-01 | Choose one absolute workspace with a native folder picker or validated path entry. | Cancel, invalid path, inaccessible path, restart and project-scope tests. | Workspace-01, Agent-12g, Acceptance-01 | Automated folder/path and loopback workspace contracts green; Converge-04 requires an admitted root; native owner dialog review pending |
| WSP-02 | Browse, filter, search and read bounded admitted files without escaping the workspace. | Traversal, symlink, race, oversized/binary and stale-map tests. | Workspace-01 | Automated complete; owner review pending |
| WSP-03 | Create and edit UTF-8 files with exact reviewed diffs and objective read-back. | Stale revision, encoding, line-ending, malformed diff and denial tests. | Workspace-01 | Automated complete; owner review pending |
| WSP-04 | Propose and publish multi-file changes atomically within the documented boundary. | Partial failure, rollback/quarantine, restart and concurrent-edit tests. | Workspace-01 | Automated complete; owner review pending |
| WSP-05 | Create folders and no-overwrite move/rename operations with explicit consequences. | Collision, traversal, race, failure-recovery and read-back tests. | Workspace-01 | Automated complete; owner review pending |
| WSP-06 | Run commands only after an exact native confirmation and show bounded execution evidence. | Denial, timeout, cancellation, descendant cleanup, output bound and duplicate-approval tests. | Workspace-01, Acceptance-01 | Automated complete; Converge-04 receipt requires an approved successful command plus a separately verified write; native owner review pending |
| WSP-07 | Fetch web content only after exact approval and within the documented network policy. | Denial, redirect, private-origin, timeout, size and content-type tests. | Workspace-01, Store-07b | Explicitly excluded from the current production release: no permission is advertised and session creation rejects web authority when no governed fetcher is composed |
| WSP-08 | Every file, command, web and MCP effect has a distinct timeline card with approval, progress, result and cleanup state. | Event-order, cancellation, safe-summary, keyboard and screen-reader matrix. | Workspace-01, Store-06e.4 | Automated complete; owner review pending |
| WSP-09 | Reviewed changes can be restored or recovered without hiding missing originals or partial effects. | Modified/missing/created path, restart, LF/CRLF and objective read-back tests. | Workspace-01 | Automated complete; owner review pending |

## E. Attachments, generated artifacts and viewers

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| ART-01 | Attach supported images, audio and documents with previews, limits and clear refusal reasons. | MIME/signature mismatch, corrupt, encrypted, oversized and unsupported fixtures. | Artifact-01 | Automated complete; owner review pending |
| ART-02 | Record audio only when the active model/runtime admits audio input, with cancel and discard behavior. | Permission denial, empty/corrupt recording, model switch and cleanup tests. | Artifact-01, Acceptance-01 | Automated complete; owner hardware review pending |
| ART-03 | A generated file becomes a versioned artifact card linked to the exact project, chat and producing turn. | Scope, lineage, reload, stale-version and missing-file tests. | Artifact-01 | Automated complete; owner review pending |
| ART-04 | Open text, code, image, PDF and supported Office/ODT output in inert safe viewers. | Active-content refusal, malformed/encrypted/oversized file and responsive-viewer tests. | Artifact-01 | Automated complete; Converge-04 counts only a successfully revalidated/rendered viewer and rejects stale/decode-failed evidence; owner review pending |
| ART-05 | Compare versions and explicitly open, download or export the intended bytes and lineage. | Digest/size/revision read-back, metadata race and cross-scope tests. | Artifact-01 | Automated complete; owner review pending |
| ART-06 | Unsupported or unsafe formats fail closed without being executed or silently treated as successful artifacts. | Parser/viewer failure matrix with content-free diagnostics. | Artifact-01, Release-01a | Automated core complete; release regression pending |

## F. MCP Store and in-chat MCP use

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| MCP-01 | Browse a local catalog sourced from the Official MCP Registry first, with adapter provenance and fetch time. | Source disagreement, offline, stale snapshot, pagination and identity/version tests. | Store-06e.2, Store-07a | Automated complete through Store-07a; owner review pending |
| MCP-02 | Search, filter and sort compact tiles with safe logos or deterministic fallbacks, descriptions, publishers, versions and management state. | Poisoned text/logo, broken image, duplicate identity, empty/loading/error and 360/1440 px tests. | Store-06e.2, Store-07a | Automated complete through Store-07a; owner review pending |
| MCP-03 | Review compatibility, provenance, integrity, declared inputs, permissions and risks before a lifecycle action. | Contradictory metadata, unsupported transport/package and strict-plan tests. | Store-04/06e.2, Store-07a | Automated complete through Store-07a; owner review pending |
| MCP-04 | Install an exact compatible revision only after native confirmation; retries are idempotent. | Failure, restart, digest mismatch, staging cleanup and duplicate-request tests. | Store-05, Converge-05a | Automated complete; 05a now binds the successful install/probe-cleanup receipt into one exact lifecycle; protected packaged owner review pending |
| MCP-05 | Update, retain one rollback generation, roll back, remove the retained superseded generation and uninstall with explicit consequences. | Crash/interruption, recovery, stale plan, retained-generation and final zero-package cleanup tests. | Store-05c, Converge-05a | Automated lifecycle and 05a evidence instrumentation complete; skipped rollback cleanup invalidates the run; protected packaged owner review pending |
| MCP-06 | Inspect configuration without executing the package and keep secret values outside ordinary state and logs. | Required/invalid values, vault reference, restart, canary and redaction tests. | Store-06d, Store-07e | Automated complete through Store-07e; owner protected review pending |
| MCP-07 | Admit exact installed servers and exact tools independently for each Agent project. | Revision drift, stale tool schema, cross-project and concurrent-change tests. | Store-06e.3, Store-07d/07e, Converge-05a | Automated complete through Store-07e; 05a binds admission to the exact reviewed snapshot and active project; owner protected review pending |
| MCP-08 | Start and stop an admitted host explicitly; installation or app restart never auto-starts it. | Restart, stale authority, crash, timeout and owned-process cleanup tests. | Store-06c/06e.3, Store-07c, Converge-05a | Automated complete through Store-07c; 05a requires a hidden local ready host followed by verified process/lease/routing cleanup; owner review pending |
| MCP-09 | Show truthful health, running/stopped/cleanup state and active project/tool counts in Store and Agent settings. | Wrong-scope, stale response, project switch and failed-cleanup tests. | Store-06e.3 | Automated complete; owner review pending |
| MCP-10 | Every model-requested MCP call receives a fresh, non-reusable native approval with a bounded preview. | Denial, replay, malformed arguments, cancel and authority-drift tests. | Store-06c, Store-06e.4, Store-07d, Converge-05a | Automated complete through Store-07d; 05a accepts only a post-host-start same-chat approved call for the admitted exact alias; owner approval click pending |
| MCP-11 | The chat shows concise requested, waiting, approved, running, succeeded, denied, cancelled, failed and cleanup-uncertain MCP activity without raw secret/tool payload leakage. | Streaming/order/Stop, safe receipt, keyboard, screen-reader and narrow/desktop tests. | Store-06e.4, Converge-05a | Automated complete; 05a consumes only the content-free ordered terminal receipt and stores no prompt/arguments/results; owner review pending |
| MCP-12 | A compact project-tools control and Store escape hatch expose capability without overcrowding the conversation. | Project switch, stale selection, no-op admission and responsive-layout tests. | Store-06e.3/06e.4 | Converge-01 repaired the intercepted Store control; Converge-02 verifies the empty project-tool state through the real loopback stack; owner trusted-tool review remains |
| MCP-13 | Malicious registry, package, schema, network, process and scope behavior fails closed and leaves no unauthorized process or connection. | Complete Store-07a through 07e adversarial matrix. | Store-07 | Automated complete through Store-07e; owner trusted-MCP review pending |

## G. External Codex, Claude and provider-neutral orchestration

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| ORC-01 | Create, inspect and revoke a project-scoped controller connection without a bridge terminal. | Exact scope, one-time setup material, restart and revocation tests. | Orchestration-01a, Converge-05b | Automated complete; 05b binds revocation and strictly later refusal into one page receipt; owner client review pending |
| ORC-02 | A controller can start, observe, stop, resume/fork and hand off an exact project/chat turn with visible ownership. | Same-project contention, reconnect, stale credential, Stop and handoff tests. | Orchestration-01b, Converge-05b | Automated complete; 05b now enforces the complete ordered connect/discover/own/stream/Stop/reconnect/handoff lifecycle and rejects hidden resubmission; owner client review pending |
| ORC-03 | Native approval authority is never inherited or forged by an external controller. | Two-client, cross-project, pending-approval and revocation isolation tests. | Orchestration-01, Converge-05b | Automated complete; the 05b release step accepts only an exact native settled-control receipt; owner client review pending |
| ORC-04 | Controller status and recovery remain content-free, durable and truthful across app restart. | Restart migration, interrupted ownership and proof-gated release tests. | Orchestration-01, Release-01a, Converge-05b | Automated release regression complete; management v2 adds a process epoch and admission sequence so page evidence fails closed across restart or missed calls; owner external-client review pending |

## H. Whole-application UI, accessibility and scale

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| UX-01 | Every route, card, button, checkbox, picker, dialog and drawer maps to a real contract or explains why it is unavailable. | Route/control/state inventory; click and keyboard traversal; zero unexplained dead controls. | Sweep-01a | Converge-01 repaired static readiness, the production web no-op and research-panel integration; updater and later route-by-route release evidence remain pending |
| UX-02 | One coherent hierarchy keeps primary work prominent and moves advanced controls into purposeful drawers, details or settings. | Owner visual review plus 320/360/768/1440 px layout matrix. | Sweep-01b, Converge-06 | Agent automated complete in Converge-03; Converge-06 adds Core/Review/Labs primary navigation with Labs disclosure and responsive focus coverage; owner visual review remains pending |
| UX-03 | One icon, typography, spacing, focus and status system replaces repeated or misleading visual language. | Token/component audit, contrast and state snapshot tests. | Sweep-01b | Agent automated complete in Converge-03: one dedicated runtime announcer, duplicate healthy banner removed and file-tree emoji replaced by shared icons; broader whole-product visual unification remains |
| UX-04 | Keyboard, screen-reader, forced-colors, contrast and reduced-motion behavior are first-class correctness requirements. | Automated accessibility plus manual keyboard matrix on every primary journey. | Sweep-01b | Converge-03 standard browser matrix is 166/166, including the full responsive/contrast/forced-colors/reduced-motion sweep and pointer/keyboard transcript paths; manual owner and packaged keyboard evidence remain pending |
| UX-05 | Loading, empty, offline, unavailable, approval, retry, stale, error and cleanup-uncertain states are explicit and recoverable. | State inventory and failure-injection browser tests. | Sweep-01a/01b | False metric-operability unavailable state repaired and real-loopback rendered; later full state inventory remains pending |
| UX-06 | Long chats, catalogs, file trees, artifacts and event streams stay responsive and do not reorder or lose selection. | Bounded stress, pagination/virtualization, cancellation, stale-response and layout-shift budgets. | Sweep-01c, Converge-06 | Agent scale and scroll ownership are automated complete in Converge-03 at 360 and 1440 px; Converge-06 adds bounded Data sources paging/disclosure, metadata-only search and exact hidden-selection reset evidence; owner visual review remains pending |

## I. Privacy, packaging and release

| ID | Required owner-visible behavior | Acceptance boundary | Owner checkpoint | Current state |
| --- | --- | --- | --- | --- |
| REL-01 | Private prompts, transcripts, tool payloads, credentials and derived data remain local and are absent from diagnostics and synthetic fixtures. | Privacy scanner, canaries, API/database/log review and network-denial tests. | Store-07e, Release-01a | Release-01a.2b privacy and content-free receipt gates green; final packaged release gate remains |
| REL-02 | Every durable record carries the required schema/provenance/version identity; missing metrics remain unknown. | Migration, contract, metric and retention tests from every supported version. | Release-01a | Primary, Agent and auxiliary migration provenance plus operation restart receipts/reconciliation are complete through Release-01a.2b |
| REL-03 | Backend, frontend, strict API contracts, privacy checks and production build are green together after the final coherent change. | One recorded final gate with exact pass/fail counts and no waived safety test. | Release-01a | Converge-05b records 203 controller/MCP backend, 577 complete Agent, 89 responsive workflow, 41 intercepted-contract, and 16 real-loopback passes plus TypeScript/build/API/privacy checks; final all-suite packaged release regression remains pending |
| REL-04 | The packaged Windows application matches the validated development behavior for pickers, confirmations, hidden processes, listener and cleanup. | Install/start/reload/shutdown package smoke on the owner machine. | Release-01b | Pending |
| REL-05 | The complete north-star Agent + model + workspace + artifact + MCP + orchestration journey works without an undocumented workaround. | Explicit owner walkthrough and signed release checklist. | Release-01b | Pending |

## Current dependency-ordered trajectory

The authoritative sequence is now:

1. **Converge-01:** truth and reachability repair — complete.
2. **Converge-02:** zero-interception local-stack browser evidence — complete.
3. **Converge-03:** Agent information architecture and module decomposition — automated implementation complete; owner visual review pending.
4. **Converge-04:** automated acceptance instrumentation complete; packaged native/hardware execution pending.
5. **Converge-05:** 05a trusted-MCP and 05b external-controller automated ledgers complete; both real owner executions pending.
6. **Converge-06:** metric validity and product-surface simplification —
   automated implementation complete; owner visual review pending.
7. **Converge-07:** signed Windows update, Labs boundary and final release —
   C07a automated staging foundation validated/complete; C07b.1 private-root
   and replay-security slice complete; C07 remains partial. See [C07a handoff](checkpoint-converge-07a-handoff.md)
   and [C07b.1 handoff](checkpoint-converge-07b-handoff.md).

Exact exit gates and the reason for each reclassification are in the
[convergence audit](prompt-enhancer-convergence-audit-2026-09-04.md).

Completed checkpoints remain regression obligations throughout this sequence.
A failing current test reopens the owning behavior; it is never dismissed merely
because an older handoff was green.

## Evidence required for each feature row

Every row closes the same evidence dimensions when applicable:

1. success and truthful refusal;
2. cancellation, retry and duplicate request;
3. stale, late and out-of-order response protection;
4. restart, persistence and migration boundary;
5. privacy, scope and approval enforcement;
6. narrow/desktop, keyboard and screen-reader behavior;
7. real local integration and process cleanup;
8. a short owner click review when automation cannot supply the evidence.

An implementation may share tests with adjacent rows, but each row must be
traceable to at least one direct assertion and one integration or browser-level
receipt before release.

## Owner review and reporting contract

After each implementation packet, the owner receives one compact report in this
order: outcome, changed surfaces, exact validation, still locked, at most five
click-later checks and exactly one next packet. Broad suites are run once after a
coherent slice, not repeatedly without a relevant change. Real model downloads,
GPU use, protected actions, destructive real-data operations, commits and pushes
still require their own explicit authority.

## Converge-06 review record

Known current evidence is root's calibration/gate/report/ratings matrix at
**140/140**, Terra's metric **69/69 frontend** and **35/35 backend contract**
tests, root LocalSources + ClaudeSource **26/26**, root's original App run at
**117 pass and 3 failures** followed by the owning-file **25/25** resolution
(not a clean full 120-case rerun), root browser shell/research/metric-context/
standalone **23/23**, whole-route accessibility **20/20** across
320/360/768/1440 light/dark keyboard/forced-colors/reduced-motion, and source
maintenance **2/2** at 360/1440 after root review. Browser suites total **61
distinct cases**; earlier Luna 2-case evidence is not counted again. Isolated
strict fixture/spec TypeScript, production build and real-loopback **16/16**
passed with listener released, temporary state removed, zero model runtimes
remaining and runtime cleanup confirmed. API and privacy checks passed,
including the final post-docwrite privacy rescan; normal git diff check passed
and no listeners remained on the checked ports.

The packet used only synthetic fixtures and content-free diagnostics: no model
was consulted and no real provider data, transcript, hardware, native client or
external client was used. No app restart or reload was performed; app on port
8765 was not running when root checked. No commit or push is claimed.
Converge-04 real model/hardware/native checks and Converge-05a/05b
trusted-MCP/external-client owner runs remain pending and unchanged.

## Finish declaration

Prompt Enhancer is finished only when every **Required** row above is either
accepted or has an explicitly owner-approved release exclusion, all final gates
are green together, the protected Windows application completes the north-star
journey and no required behavior relies on a hidden workaround. Until then the
active goal remains open.
