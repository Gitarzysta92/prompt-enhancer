# Windows beta acceptance gates

This is the **gate contract**, not a progress ledger or a release certificate.
The [product-readiness matrix](product-readiness-matrix-2026-09-12.md) remains
the only current status/priority ledger. The
[owner feature register](prompt-enhancer-owner-feature-register-2026-08-31.md)
contains 67 finer-grained behavior rows; none is waived by a scenario below.
The [CI quality gate](ci-quality-gate.md) checks synthetic source behavior but
cannot substitute for installed, native, real-model, or clean-machine evidence.

## Inventory and decision rule

The existing ledger defines B00–B11 and W00–W08 and names V01–V18. The owner
register defines feature-level expected behavior. Before this contract, the V
scenarios lacked one explicit, testable closure predicate in the repository.
The W model/data, topology, and placement matrices were approved but had no
durable acceptance checklist. This document fills those **definition** gaps;
it does not claim that any scenario has executed.

Evidence levels are ordered by what they can prove, not by test count:

| Level | Required observation | Does not establish |
| --- | --- | --- |
| Contract | Bounded calculation/state transition on synthetic inputs. | A complete user journey. |
| Integration | Real local storage, API, and service boundaries together. | Native confirmation or installation. |
| Browser | Rendered interaction at a named viewport and browser. | Native picker, approval, or physical inference. |
| Packaged | Exact candidate payload runs the journey. | Clean install or trusted update. |
| Native/real model | Actual Windows window, approval, model, and owned-resource behavior as applicable. | Other models or hardware. |
| Clean machine | Standard-user install/update/uninstall on the declared Windows baseline. | Universal compatibility. |

For each required gate, record a content-free receipt with: gate/case ID;
source commit and exact package SHA-256; test or manual procedure version;
Windows/hardware/runtime/model profile and hashes where relevant; expected and
observed outcome; pass/fail/blocked/not-run; start/end time; cleanup outcome;
and reviewer. Do not store prompts, model responses, workspace contents,
credentials, private paths, or screenshots in the ledger or public artifacts.
An old receipt is historical after relevant code, dependency, model, or package
changes. A skip, unknown cleanup, or missing required environment is **not a
pass**. An automated contract pass never upgrades itself to native acceptance.

The release decision is fail-closed: every required V01–V18 gate and the W07/W08
end-to-end gates must pass at their stated level on the exact release candidate;
W00–W06 evidence must match its unchanged source, model and runtime inputs;
B00–B11 must be closed; no P0/P1 remains; full backend/frontend/build/privacy checks pass; two
consecutive packaged core smokes pass; CPU and physical NVIDIA profiles are
covered; no test-owned process/model remains; and the owner accepts the core
journeys. A missing owner input is a blocker, not a synthetic substitute.

## Core user-journey gates (V01–V18)

The named test files are **existing candidate anchors**, not evidence that the
gate passed. Each gate needs a current receipt at the minimum level shown. The
negative/refusal path is part of the pass condition.
Uncommitted local draft tests are not portable automated anchors and are not
cited here; omitting those drafts does not waive any required browser, packaged,
native, real-model or clean-machine evidence.

| ID | Observable pass and required refusal/recovery | Minimum evidence | Existing anchor and current gap |
| --- | --- | --- | --- |
| V01 | A standard Windows 11 x64 user installs the signed MSIX and opens one usable app without Python, Node, or Git. Missing prerequisites and offline acquisition explain the failure without a partial installation. | Clean machine | `tests/test_bootstrap.py`, `tests/test_windows_distribution_hardening.py`; source/bootstrap and payload-policy anchors only, with no signed clean-machine install receipt. |
| V02 | Without an account or loaded model, create a project/chat, type a draft, navigate away and back, and retain it after restart. No model prompt or network login blocks composition. | Packaged + native | `tests/test_agent_catalog.py`; catalog/persistence contract only, with no exact browser, packaged or native restart receipt. |
| V03 | Native folder picker selects an admitted workspace or cancels with no unintended read/write; invalid/missing roots recover visibly. Browser-only mode states its limitation. | Native | `tests/test_desktop_overlay.py`, `frontend/src/shared/platform/nativeDesktopBridge.test.ts`; no owner-observed native select/cancel receipt. |
| V04 | Create, browse, switch, rename, search, pin, archive, restore and delete project chats; supported export/fork is exact and scoped. Restart retains results; duplicate submissions do not duplicate work; project deletion never deletes the workspace. | Packaged + native | `tests/test_agent_catalog.py`; catalog lifecycle contract only, with full browser/packaged/native lifecycle unverified. |
| V05 | One pinned, licensed CPU GGUF profile gives a real streaming answer; Stop, retry, crash and app restart leave truthful states and history. A merely registered or simulated model does not pass. | Packaged + real CPU model | `tests/test_local_models.py`; genuine installed-app inference unverified. |
| V06 | A pinned NVIDIA/hybrid profile loads only on supported placement; a second approved model switches through explicit stop-and-switch; prior owned process and VRAM are verified released. Unknown measurements stay unknown and block the claim. | Packaged + physical NVIDIA | `tests/test_model_compatibility_catalog.py`; physical switch/unload receipt absent. |
| V07 | Terminate during generation, reopen, and retain completed turns while the active turn is marked interrupted, never completed or silently resumed. Repeated open/close leaves no owned-process accumulation. | Packaged + native | `tests/test_agent_history.py`, `tests/test_desktop_lifecycle.py`; source integration/lifecycle anchors only, with packaged/native restart and repeated-process census unverified. |
| V08 | A native approval applies exactly the reviewed workspace change once; reject, cancel, stale diff, traversal/reparse escape, project switch and API-only forged approval cannot write. A command or fetch needs its own fresh approval. | Native protected approval | `tests/test_agent_write_proposals.py`, `tests/test_user_presence.py`; real native approval unverified. |
| V09 | A card appears only for a verified existing/committed artifact, linked to its producing turn; safe supported files open inertly. Prose claiming a document, malformed/oversized data or a failed write cannot create a success card. | Packaged + native | `tests/test_agent_artifacts.py`, `frontend/src/features/agent/AgentArtifactCaptureDialog.test.tsx`; backend/component contracts only, with packaged viewer, native-open and notice proof absent. |
| V10 | One checksum-pinned local and one loopback-remote curated MCP server complete reviewed setup, native approval, tool use, revocation, removal and restart recovery. Revocation is immediate; no host remains after removal. | Packaged + native | `tests/test_agent_mcp_integration.py`; source integration contract only, with packaged/native approval, use, revocation, removal and restart lifecycle unverified. |
| V11 | After a real app restart and injected registry outage, an exact cached listing identifies its age. Uncached query and registry-required exact review fail honestly; no other query's results are returned. | Packaged + integration | `tests/test_mcp_registry_catalog.py`; complete packaged restart/outage run was canceled. |
| V12 | Hand-computable fixture values agree through storage, API and rendered UI; zero differs from unknown/pending/unavailable; denominator, coverage, time basis and provenance remain visible. Missing usage is never zero and model prose is not objective success. Unsupported adapter cells remain unavailable. | Integration + browser | `tests/test_metric_operability.py`, `tests/test_metric_coverage_api.py`, `frontend/src/entities/analysis/SessionMetricCard.test.tsx`; backend/API/component anchors only, with the exact storage-to-rendered-browser matrix unverified. |
| V13 | Agent and mini-window stay usable at supported sizes/scales; stale/disconnected metrics are labeled, reconnect does not invent freshness, and closing a child window does not kill unrelated work. Keyboard/focus and ten open/close cycles pass. | Native + browser | `tests/test_desktop_overlay.py`, `frontend/e2e/sweep-01c-scale.spec.ts`; source/browser-scale anchors only, with native child-window, full scaling/keyboard/focus and ten-cycle census unverified. |
| V14 | Version N verifies exact signer/manifest/package, asks fresh native consent, applies N+1, relaunches with retained synthetic chats/settings. Tampering, replay, downgrade and consent cancel leave N usable. | Clean machine + signed N→N+1 | `tests/test_application_update_07b_acceptance.py`; real executor/install receipt absent. |
| V15 | Failure during download, staging, handoff or first launch has an honest durable journal and recoverable package/data pair; an older binary never opens an unsupported newer schema. No data is silently deleted or reboot requested. | Clean machine + fault injection | `tests/test_application_update_staging_failures.py`; native interrupted update unverified. |
| V16 | Uninstall and reinstall exhibit the documented retained-data policy for projects, chats and models; erasure, if offered, is a separate explicit confirmation. | Clean machine | No clean-machine uninstall/reinstall receipt. |
| V17 | Built payload, logs and diagnostics contain no prohibited private data; loopback auth/origin/CSRF and exact native approval boundaries reject unauthorized operations. No unrelated process or model is touched. | Packaged + native security | `scripts/privacy_scan.py`, `tests/test_user_presence.py`; final exact-candidate/native boundary proof absent. |
| V18 | Clean private commit builds the compiled source-private payload without first-party Python/TypeScript source or source maps; dependency inventory/notices are complete; it runs without development tools. Any PDF worker shipped has resolved provenance, otherwise it is removed. | Packaged + archive inspection | `scripts/verify_msix_package.py`, `tests/test_windows_distribution_hardening.py`; compilation and notice closure absent. |

The feature register's row families remain independently binding. This map
prevents a broad journey from hiding a finer-grained behavior:

| Feature rows | Core journey gates |
| --- | --- |
| APP | V01, V07, V13, V17 |
| AGT | V02, V04, V05, V07, V13 |
| MOD | V05, V06, V07 |
| WSP | V03, V08, V17 |
| ART | V09, V17 |
| MCP | V10, V11, V17 |
| ORC | V07, V08, V17 |
| UX | V02–V04, V08, V12, V13, V14 |
| REL | V01, V14–V18 |

## Workflow gates (W00–W08)

Workflow scope is required for this expanded beta but not started. No existing
research adapter or canvas mock is a production pass. Each advertised model
profile is pinned by artifact hashes, revision, license, preprocessing, runtime,
resource limits and qualified hardware. Missing owner-approved profiles block
the corresponding cell rather than authorizing an invented replacement.

| ID | Exit predicate | Minimum evidence |
| --- | --- | --- |
| W00 | Freeze fixtures, eight family profiles plus a second text LLM, runtime/toolchain pins and hardware budgets. Compile and run representative text/image/audio workers on CPU; load NVIDIA dependencies; verify owned exit. Stop after two understood compilation corrections if infeasible. | Compiled packaged spike + physical NVIDIA dependency load. |
| W01 | Versioned ports reject every unsupported family/input pair before load, reject cycles and graphs over 32 nodes/16 model nodes, and require explicit converters; malformed media and incompatible embedding identities/dimensions fail closed. | Exhaustive contract matrix + backend validation. |
| W02 | Immutable workflow revisions and exact run bindings survive restart. Synthetic chain/fork/join preserves port identity; duplicate Run creates one run; cancellation and crash mark interrupted nodes truthfully; no auto-resume. | Durable integration + restart. |
| W03 | Each qualified text, vision-language, text/image classifier, detector, embedding, speech-recognition and audio-classifier profile performs genuine inference and validates declared typed output. Preprocessing and resource cleanup are observed. | Real model on every advertised backend/profile. |
| W04 | Sequential, automatic and require-parallel modes obey admission. Demonstrate overlapping inference for admitted CPU/CPU, CPU/GPU and GPU/GPU cells; automatic serializes visibly when needed, require-parallel refuses. Existing chat/research runtimes are neither unloaded nor killed. | Physical CPU/NVIDIA resource measurements + owned cleanup. |
| W05 | Saved typed graph works in accessible canvas and keyboard list; invalid links explain why; device recommendations show evidence and unknowns; Build/Run/Results stay usable at supported sizes. Compatible saved workflows can enhance an Agent composer draft through the WP01–WP08 review contract below. | Browser + native owner journey. |
| W06 | Export/import binds a versioned definition and model locks, omits contents/credentials/absolute paths/weights/source, and runs through the installed headless engine with GUI-equivalent results and limits. Import never downloads or executes on its own. | Installed runner with GUI closed + privacy inspection. |
| W07 | All declared model/data, topology, scheduler, placement, cancellation, crash, restart and cleanup cells, including WP01–WP08, pass; unsupported cells reject. Two consecutive packaged smoke runs leave no test-owned process or GPU model. | Exact packaged candidate + genuine model/hardware. |
| W08 | B00–B11 release gates still pass after workflow integration, including signed install/update, retention, privacy and native approvals. | Exact signed release candidate + clean machine + owner review. |

### Required workflow matrix dimensions

- **Family/input:** text LLM←text; vision-language←image+text; text
  classifier←text; text embedding←text; image classifier←image; object
  detector←image; speech recognition←WAV audio; audio classifier←WAV audio.
  Test every other text/image/audio/embedding direct pair as a pre-load refusal.
- **Conversions:** transcript→text; scores/detections→formatted text or JSON;
  detections+original image→separate vision-language ports; detection→overlay;
  same-encoder, same-dimension embeddings→similarity. Never call a raw model
  score a calibrated probability without calibration evidence.
- **Topology:** chain, fork/join, fan-out, reverse-finish ordering, failed
  required branch, mixed image/audio report and cycle rejection. Exercise each
  applicable valid graph in sequential, automatic and require-parallel modes.
- **Placement:** CPU-only, NVIDIA, hybrid where the adapter supports it,
  CPU/CPU, CPU/GPU and admitted GPU/GPU concurrency; single-stage too-large,
  concurrent-only too-large, missing driver and unknown memory are refusal or
  explicit serialization cases, never silent success.
- **Recovery/security:** cancellation at loading/inference/join/artifact/unload,
  process crash, disk full, changed input/model hash, malicious import,
  traversal/reparse escape, unsafe renderer content and ten run/stop cycles.
  Confirm worker exit before releasing a lease; unknown cleanup blocks relaunch.

For each cell, record case ID, workflow revision, model/runtime hashes,
hardware/placement, scheduling mode, expected/actual outcome, duration,
RAM/VRAM evidence, source/package digest and cleanup. Raw media and model
responses stay out of diagnostic receipts. A queued pair is not parallel proof.

### Composer prompt-enhancement hook (WP01–WP08)

Required by the owner's September 26 scope decision. These are subcases of the
existing W checkpoints, not an additional implementation campaign. A "hook"
here is an internal Agent composer integration with the same workflow engine,
validation, run journal and resource coordinator used by the visual builder and
installed runner. It does not authorize shell callbacks, external connectors or
changes to existing provider hooks. The basic prompt-check service described in
[ADR 0015](adr/0015-prompt-check.md) remains available; its presence is not proof
of this new saved-workflow integration.

The composer offers a compact workflow selector and an **Enhance prompt** action.
Manual invocation is the default; an optional, visibly enabled before-send hook
pauses submission for review. Neither mode silently rewrites or sends. Review
offers the original and suggested text, an explicit apply action with undo, and
the choice to keep/send the original or cancel. Sending the reviewed suggestion
still requires an explicit Send action and must not recursively invoke the hook.

A compatible workflow declares a bounded text draft input and a bounded text
suggestion output. Context and attachments are optional, separately declared,
explicitly selected inputs: no automatic workspace or full-history collection.
Declared image/audio inputs use the existing qualified media limits and visible
preprocessing. An enhancement cannot silently remove or replace the attachments
that will accompany the chat message. Empty, malformed, incomplete or incompatible
outputs are failures, not successful empty prompts. Explanations are optional
model advice; measured prompt-check metrics retain their own provenance and
unknown states. No invented facts, permissions or quality score may be presented
as verified merely because a workflow generated them.

| Case | Checkpoint mapping | Observable pass and required refusal/recovery | Minimum evidence |
| --- | --- | --- | --- |
| WP01 | W01, W03 | Draft-to-suggestion and declared optional context/media contracts validate before load. Missing ports, wrong types, oversize inputs and invalid outputs fail without modifying the draft. Only compatible workflows are selectable; unavailable ones explain why. | Exhaustive contract cases + qualified adapter output validation. |
| WP02 | W05 | Select a saved workflow beside the composer, run it manually, compare original/suggestion, apply, undo, keep original or cancel. Explicitly enabled before-send mode pauses for review. Nothing is silently sent; switching the hook off restores ordinary Send. Keyboard/focus and supported viewport checks pass. | Browser + native interaction. |
| WP03 | W02, W05 | Bind each run/result to the chat, draft revision, workflow revision, model-profile versions and selected input snapshots. Editing a draft/attachment, switching chats, closing a chat or replacing a workflow cannot apply a late result to a different target. Editing a graph cannot mutate its active run. | Integration + adversarial browser completion ordering. |
| WP04 | W02, W05 | Double-click Enhance/Send or reconnect resolves to one enhancement run and at most one explicitly authorized message. Sending a reviewed draft does not re-enter enhancement. A newly edited draft requires fresh review; no recursive hook chain or automatic retry. | Integration + browser duplicate/reconnect tests. |
| WP05 | W02, W05 | Cancel, timeout, worker crash, invalid suggestion and restart preserve the original draft/attachments with truthful interrupted/failed states. Nothing resumes, applies or sends automatically. The user can retry or deliberately send the original. | Fault injection + packaged restart. |
| WP06 | W04, W05 | Enhancement shares the one-run/two-stage resource budget with builder runs. A loaded chat model is neither silently unloaded nor replaced; show waiting or require explicit stop-and-run. Low-memory refusal is recoverable, Stop remains available and owned cleanup is confirmed before lease reuse. | Integration + physical CPU/NVIDIA ownership/cleanup. |
| WP07 | W02, W06, W08 | Show exactly which draft/context/attachments enter the local workflow. Any retained content uses the private run store with explicit retention controls, never analytics records, diagnostics or default exports. Preserve ADR 0015's content-free prompt-check storage. Export/import carries no chat binding, content or hook authority by default and never auto-enables a hook. | Storage/export inspection + privacy tests. |
| WP08 | W05, W06, W07, W08 | The same pinned prompt-enhancement workflow works in Build/Run/Results, the composer and installed headless runner without a second engine. Genuine-model results satisfy declared contracts/tolerances; completed private results and selected hook settings survive upgrade with no automatic execution. Two packaged smokes and owner review cover the composer path. | Exact packaged/signed candidate + real model + update retention + owner review. |

Every case requires its own content-free receipt using the fields above; source
contract tests alone do not pass the packaged/native cases. These gates define
required behavior only, not an implementation or acceptance claim.

## How to use this contract at each checkpoint

1. Select one open ledger row and its linked V/W/feature gates; do not resweep
   every passing row.
2. Run the smallest direct regression, then the relevant integrated journey.
   Record exact commit/artifact scope and cleanup. Do not repeat a failed
   command unchanged; after two hypothesis-driven corrections, report blocked.
3. Update only the authoritative ledger's status and next action. Mark a gate
   passed only at its required evidence level; retain negative-case failures.
4. Record a checkpoint report and continue to the next safe dependency only
   when the current exit gate is met. Stop for owner-dependent decisions or
   required owner acceptance. Recheck affected gates after relevant changes
   and all gates on the frozen release candidate.

The structural inventory test `tests/test_beta_acceptance_gate_inventory.py`
guards IDs and required fields in this document. It tests documentation
completeness only; it cannot certify application behavior.
