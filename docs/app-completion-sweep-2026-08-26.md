# Application completion sweep — 2026-08-26

Status: repair batch implemented and regression-verified; full backend run passed with nine platform skips. This is an acceptance ledger, not a claim that every feature is finished or visually approved.

## Scope and evidence rules

The owner requested an A–Z functional and UI/UX sweep with Opus 5 review, implementation, and regression tests. The recorded baseline is checkpoint 18 (`efb19e2`). Six bounded, tool-free `claude-opus-5` audit passes examined curated public source. Opus implementation patches were independently reviewed, refined, and tested before integration; findings were not accepted automatically. The CLI reported Opus 5 as the primary model and a Haiku helper. No provider sessions, credentials, local configuration, screenshots, or real transcripts were included in these reviews or fixtures.

The requirements inventory is `ui-card-review-backlog.md` (UI-00 through UI-20), the product trajectory, work-package acceptance criteria, and the applicable ADRs. Existing test coverage is evidence of particular behaviors, not proof of complete product parity or visual approval.

Acceptance for each repair: reproduce the failure with synthetic data; implement without weakening consent or provenance; test success, failure, cancellation/navigation and unavailable states where relevant; check keyboard/small-screen behavior; record the commands and remaining limitations. Real model tests, if needed, must end with model deactivation and a GPU-process check.

## A–Z surface inventory

| Group | Required surface / workflow | Existing test anchors | Sweep status |
| --- | --- | --- | --- |
| UI-00 | Shell, navigation, dialogs, focus, theme, primitives | `App`, `AppScopedRoutes`, `primitives`, shell/mobile browser suites | Navigation walked; Agent/Prompt-check unavailable headings repaired; responsive/keyboard suites pass. |
| UI-01 | Project catalog, filtering, provider/provenance context | `ProjectCatalog`, `ProjectCatalog.provenance` | Bounded source audit found no confirmed defect; existing regressions pass. |
| UI-02 | Project overview, sessions, workspace | `ProjectWorkspace`, `ProjectTimelinePane`, `AppScopedRoutes` | Successful analysis now leaves an explicit workspace receipt; regressions pass. |
| UI-03 | Ensemble entry, overlay, scope and close/focus behavior | `ModelEnsemblePanel`, `ModelEnsembleOverlay`, ensemble browser suite | Existing shell/ownership tests and compact browser suite pass; no visual redesign claimed. |
| UI-04 | Metric workspace, sources, unknown/missing evidence | `metricWorkspaceSurfaces`, `MetricWorkspace`, `MetricObservationCard` | Bounded source audit and metric tests pass; local HTTP fixture verifies unsupported axes stay unsupported. |
| UI-05 | Radar, knowledge, guidance and explanations | `ModelEnsembleRadar`, `MetricKnowledgeCard`, `MetricExplainer`, guidance tests | Radar/context source review and existing tests pass; prompt-check finite-value guard strengthened separately. |
| UI-06 | Metric history, model stages, trajectory selection | `MetricHistoryDrawer`, `modelStages`, trajectory tests | History source audit found no confirmed defect; raw/oriented values and existing regressions pass. |
| UI-07 | Generic evidence preview/import and immutable receipts | `MetricEvidenceFilePanel`, metric-evidence contract tests | Expiry, incomplete/duplicate proposal lists, and contradictory native capability repaired/tested. |
| UI-08 | Requirement-plan evidence preview/import | `RequirementPlanEvidencePanel`, plan evidence transport/contract tests | Included in evidence review; existing strict consent/ownership tests pass; native click-through remains owner review. |
| UI-09 | Requirement-action evidence preview/import | `RequirementActionEvidencePanel`, action evidence transport/contract tests | Retry contract load, reselect same file, and close review repaired/tested. No new native browser workflow claimed. |
| UI-10 | Quality profiles, local analysis, share cards, declared task profile | quality-profile tests, `AnalyzeLocallyDialog`, `DeclaredTaskProfilePanel` | Analysis completion receipt and truthful unavailable-compatibility action repaired; callback-rerender allegation rejected. |
| UI-11 | Session transcript/timeline, coaching, judge, model-link experiment | `SessionTranscriptPane`, `SessionTimelinePane`, `CoachingLoop`, `ModelJudgePane`, `ModelLinkExperimentPanel` | Judge and model-link late-result/annotation ownership repaired. Tests use fictional excerpts only; no real transcript inspection. |
| UI-12 | Source detection, onboarding and explicit local ingestion | `LocalSources`, `ClaudeSourceCard`, `FirstRunPanel`, local-real browser suite | Native/local-only boundary preserved; live consent workflow not exercised with owner data. |
| UI-13 | Overview and session catalog, filters and truthful totals | `OverviewPage`, `SessionsPage`, standalone mobile suite | Partial-coverage labels, explicit next-page loading, invalid duration, and runtime-specific empty guidance repaired/tested. |
| UI-14 | Job centre, project automation, cancellations and retries | `AnalysisJobCentre`, `ProjectAutomationSettings`, browser suites | Exact-job cancellation ownership and provider-specific consent text repaired; unknown consent is not denied consent. |
| UI-15 | Prompt check, calibration, model install/start/stop/chat | `PromptCheckPage`, `CalibrationPage`, `LocalModelsPage` | Chat/reset/retry, lookup ownership, calibration save/recovery, prompt metric/history/copy and narrow result layout repaired/tested. |
| UI-16 | Reviewed task, immutable analysis, lifecycle/task flow | `TaskDetail`, `taskFlow`, lifecycle controls/contracts | Four new task-detail regressions reproduced and repaired; flow route walked. |
| UI-17 | Methods, model inventory and metric operability | `ResearchLab`, `ModelLabInventoryPanel`, `MetricOperabilityPanel`, research browser suite | Benchmark-status recovery and duplicate/stale start guards repaired/tested. Evaluation/licence/readiness gates stay closed. |
| UI-18 | Agent session, workspace editor, protected actions, teamfolders | Agent page/workspace/prompt-check/change-set/discovery tests; workspace/event contracts | Full start/chat/reasoning/stop flow is covered by desktop/mobile fixtures. Checkpoint 34 adds the live reviewed-path net change set; checkpoint 35 adds bounded content-free selected-folder/Git observation; checkpoint 36 adds failure-atomic existing-file batches; checkpoint 37 adds separately reviewed new-file creation and no-overwrite file moves; checkpoints 38/39 add reviewed directory create/move plus first-class model lifecycle tools; checkpoint 40 adds exact recoverable Windows single-file removal. None grants unreviewed content, permanent deletion, directory removal, recursive parent creation or durable retention. The chat-first Projects/Sessions/runtime/artifact trajectory is specified but not yet implemented. Teamfolder actions/recovery remain repaired. |
| UI-19 | Team analytics, member visibility, social and direct-transfer prototype | team/social component, contract, privacy and browser suites | Routes walked; bounded source review plus existing suites pass. Prototypes are still not production internet collaboration. |
| UI-20 | Native Agent window, live mini window, experiment/auxiliary surfaces | `LiveMiniWindow`, native bridge/platform tests | Checkpoint 33 closes the prior packaged-launch uncertainty: real generated Agent/overlay executables loaded hidden WebView documents, closed, released disposable state and published clean lifecycle records. Native approval/folder-picker clicks and owner visual preferences remain separate. |

## Confirmed repair queue

| ID | Observable failure | Acceptance / regression evidence | State |
| --- | --- | --- | --- |
| SW-01 | Task A's late fetch/run completion can overwrite task B | Delayed task, delayed run-detail error and delayed analysis completion after navigation | Fixed; focused tests pass |
| SW-02 | Failed analysis replaces the entire task and exposes raw exception text | Keep prior results visible; safe inline error; reload without submitting another analysis | Fixed; focused tests pass |
| SW-03 | New conversation resurrects aborted output; stopped model hides chat; retries lose drafts | Owned stream callbacks; immediate Stop/reset; preserved partial output/model attribution; explicit retry keeps next draft | Fixed; 16 chat tests plus browser flow pass |
| SW-04 | Failed teamfolder refresh looks empty; optional actions do nothing; an interrupted refresh can stay loading forever | Retry/stale states, capabilities, serialized/context-owned commands, one-time token survives failed refresh; replace interrupted reads after success or failure without repeating transfers | Fixed; 14 unit tests plus browser flow pass |
| SW-05 | Late repository lookup shows another repository's files/provenance | Reverse-order lookups, edited-input invalidation, stale failure suppression | Fixed; 21 Models tests pass |
| SW-06 | Calibration save feedback disappears; partial save looks like no change; optional commands stay enabled | Acknowledgment survives refresh; ownership, explicit retry, save lock and missing-capability guards | Fixed; 18 tests pass |
| SW-07 | Prompt metric displays `3/null`/`known`; history lacks recovery and can overwrite new results | Finite values/fractions, unknown retained, quality-oriented history, request ownership and explicit copy/history feedback | Fixed; 14 tests plus browser flow pass |
| SW-08 | Agent/Prompt-check unavailable routes have no heading or recovery direction | Accessible headings and explicit local/native boundaries at narrow sizes | Fixed; route browser checks pass |
| SW-09 | Capped catalog looks like complete search/totals; reversed dates look like zero duration | Visible partial coverage even with zero matches, bounded manual pagination, duration unavailable, correct runtime CTAs | Fixed; 20 Overview/Sessions tests pass |
| SW-10 | Action evidence cannot recover a failed contract load, reselect the same file, or close a review | Retry exact owner, reset file input, close without accepting | Fixed; 37 tests pass |
| SW-11 | Generic evidence preview outlives expiry; malformed/partial lists look complete; inconsistent native flag is trusted | Expiry timer lifecycle; strict complete-list/duplicate checks; require coherent native capability | Fixed; 22 tests pass |
| SW-12 | Analysis success disappears with its dialog; compatibility action promises an unavailable callback | Workspace success receipt, aborted receipt guard; Close action when recheck is not provided | Fixed; workspace/dialog tests pass |
| SW-13 | Populated prompt-check grid exceeds narrow content bounds | Flexible minimum column width; test measures panel/control bounds, not only document scroll width | Fixed; new 360 px regression fails before repair and passes after |
| SW-14 | A cancelled job's late result/error affects another selected job | Exact job identity, request ownership and abort on selection/runtime/transport change | Fixed; 14 Job Centre tests pass |
| SW-15 | Claude project consent gate names Codex; unknown consent looks denied | Provider-specific gate copy; explicit not-verified state | Fixed; 16 automation tests pass |
| SW-16 | Session A's model judgment/explanation appears under session B | Owned context, abort signals, response/session validation, serialized actions, read-only Retry | Fixed; 10 model-judge tests pass |
| SW-17 | One failed benchmark status read leaves all run controls stuck with no recovery | Retry the same job; label status unknown; prevent duplicate start/late transport result; never invent worker failure | Fixed; 14 research tests pass |
| SW-18 | Model-link run/annotation survives session change; old finally clears newer cancellation | Context cleanup, owned run/annotation/load, exact run/link checks; Cancel wait does not claim worker termination | Fixed; 12 panel/contract tests pass |

## Baseline and new verification

- Baseline synthetic browser suite: 49/49 passed before repairs. This did not catch the new delayed-response failures.
- Primary synthetic navigation: all 14 destinations opened; no alerts or document-width overflow at the initial desktop viewport. Agent and Prompt check correctly reported unavailable capabilities, but lacked a level-one heading.
- `npm run test -- --run src/features/task-detail/TaskDetail.test.tsx`: four newly added regressions failed against checkpoint 18; after the repair, all five task-detail tests pass.
- Final Team folders review reproduced three additional stuck-loading cases (pull success/failure during refresh and failed sharing during initial load). All three failed before the correction; all 14 panel tests pass afterward. Recovery rereads metadata and never repeats a transfer.
- Final frontend: `npm test -- --maxWorkers=3` — **1,460 passed / 122 files** (89 more tests than checkpoint 18).
- Browser: `npm run test:e2e -- --workers=3` — **59 passed**, including eight new populated-workflow cases at 360 and 1440 px. Fixture operations are in-memory; no files, real models or GPU were used.
- Local HTTP browser contracts: `npm run test:e2e:local` — **8 passed**. All API traffic is intercepted with synthetic fixtures; this is not an owner-data/native approval end-to-end claim. Two old runtime-label selectors were made exact to distinguish desktop and mobile markers.
- Production build: `npm run build` — passed. The dev-only workflow fixture also passed an explicit strict TypeScript check.
- Generated API contract: `npm run check:api` — passed; generated client matches the API schema.
- Privacy scanner and whitespace check passed, including the completed repair documentation.
- Complete backend: `.venv/Scripts/python.exe -m pytest -q` — **3,608 passed, 9 skipped, 1 warning** in 40m13s. Skips are symlink tests because this Windows environment cannot create symlinks: database, model provenance/evaluation, quarantined file reading, scanner, social SQLite, and home-directory boundaries. They require a symlink-capable host and are not counted as passes. The warning is the test client's deprecated `httpx` integration; no dependency migration was attempted.
- Native application: the earlier direct protected-Agent check started successfully, but a later unexplained exit and first packaged-launch attempt had no durable diagnosis. Checkpoint 33 supersedes that open state with an atomic owned-listener implementation, content-free shutdown evidence, two real native-engine probes and two generated-executable probes. It does not retrospectively identify the historical process exit.
- GPU scope: zero models activated by this sweep, zero `llama-server` processes at verification. Other graphics/GPU applications were left alone; this does not claim all GPU memory is free.

## Rejected finding and non-bug boundaries

- An audit suggested changing Agent session IDs from 32 to 64 hexadecimal characters. Rejected: in-memory Agent session IDs intentionally differ from 64-character analytics pseudonyms. Changing them would break a correct contract.
- An audit alleged that parent rerenders close local analysis because callbacks are unstable. Rejected: the quality-profile view deliberately captures the opener callbacks; its existing regression verifies that behavior. The separate missing success receipt was repaired.
- A suggested `NaN%` queue defect required `progress_total = 0`. Rejected: both the backend job contract and HTTP parser already require a positive integer total. No fake zero-progress fallback was added.
- A proposed benchmark recovery marked the job failed after unsuccessful status reads. Rejected: an unreachable worker's outcome is unknown. The implemented recovery retries the same status endpoint and keeps new runs disabled until a terminal receipt is known.
- Native approval, folder picker and protected writes cannot be enabled by pretending an ordinary browser has the desktop bridge.
- Metric calibration, hosted identity/billing, external annotation destinations, internet sharing and encrypted-vault policy remain subject to the decisions documented in `pending-owner-decisions.md`. This sweep does not authorize them or mark them complete.
- Generated model commentary remains separate from objective metrics and verification evidence. Unknown is not zero, failure, or a low score.
- Visual preference and actual model usefulness still need owner review; automated tests cannot supply those judgments.

## Next bounded acceptance step

Review the running Agent and Models screens first, then calibration/prompt check and evidence controls, using the checklist in `checkpoint-19-handoff.md`. Record each owner finding against UI-00 through UI-20 rather than restarting an unbounded redesign. Checkpoints 26 and 32 provide bounded per-turn telemetry and historical write receipts; checkpoint 33 supplies packaged-launch and shutdown evidence; checkpoints 34-39 supply the memory-only reviewed change set, selected-folder/Git discovery, failure-atomic existing-file batches and reviewed file/directory lifecycle; checkpoint 40 supplies recoverable Windows single-file removal without permanent or directory-delete authority. The next proposed implementation is Agent-01 in `agent-chat-experience-plan-2026-08-27.md`: freeze the current safety contract and extract the page controller before the first visible chat-first shell. Remaining product work includes owner-gated durable authored Agent content, global runtime arbitration, artifacts/viewers, capability-gated modalities, broader probe-confirmed model adapters, richer editing, directory/POSIX trash, native click-through, POSIX publication acceptance, owner visual preferences, justified indexing and the explicitly gated sharing/vault decisions. No new checkpoint should silently treat these as complete.

Later evidence: checkpoints 20 through 25 add bounded repairs and verification,
including native lifecycle cleanup, Agent recovery, model completion and exact
human/model calibration cases. This original sweep's counts and next-step wording
are historical. Use `goal-verification-ledger-2026-08-26.md` and
`checkpoint-25-handoff.md` for the current status, review list and remaining
privacy/product gaps; later tests do not retroactively certify this whole list.
