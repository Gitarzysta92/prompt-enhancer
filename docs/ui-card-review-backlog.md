# UI card review backlog

Status: Checkpoint 13 UI-00 objective repair complete; UI-00 and UI-03 through UI-20 owner visual review pending

The initial inventory was assembled from the route map, component tree, CSS,
tests, and current diff because localhost browser automation was unavailable at
that time. Targeted localhost reloads now work, and Checkpoint 9A adds synthetic
360 px route coverage for Overview, Sessions, Calibration, and Models. This
inventory still does not claim that a visual defect exists until that defect is
reproduced in the rendered application.

Checkpoint 9B has now landed objective route/focus, asynchronous ownership,
confirmation-dialog, and timeline-control corrections. Those correctness
changes do not visually approve UI-03 through UI-10; their card-by-card owner
review remains pending.

Checkpoint 9D adds a code-only cross-surface audit of state truth, consent,
focus, navigation icons, asynchronous request ownership, prompt-check chart
direction, model-judge prompting, timestamp provenance, and schema migration.
Its deterministic and synthetic-browser evidence closes objective defects but
does not visually approve any card. The owner review boundary therefore remains
unchanged.

Checkpoint 13 repairs the application shell and shared primitive contract before
more card-level polish. Desktop navigation now owns its overflow without hiding
the footer or current route; mobile uses a contained navigation dialog while
retaining privacy/runtime truth; bootstrap and route failures recover safely;
and shared dialog, loading, coverage, progress, tab, and status semantics have
direct synthetic coverage. The implementation is objectively validated, but
the owner has not yet visually approved the shell.

The application currently contains 18 routed or window shells and roughly 60
distinct card, panel, drawer, and dialog work units. The current r7 tranche
directly changes only the canonical metric/evidence workflow and metric
operability surfaces.

## Rules for every card checkpoint

Each later card checkpoint must remain independent and use this sequence:

1. Reproduce the issue on localhost and record the route, viewport, theme, and
   data state without copying private session content.
2. Inspect ready, loading, empty, unavailable, error, and stale states that the
   card actually supports.
3. Check desktop and mobile widths, light and dark themes, keyboard focus,
   accessible names, wrapping, clipping, and action feedback.
4. Agree on the intended copy and interaction before editing.
5. Change only that card or one inseparable card group.
6. Run focused tests, TypeScript, build, privacy, and diff checks.
7. Restart localhost, review the result, and stop for approval.

Unknown or missing evidence must stay unknown. UI repair must not turn missing
values into zero, promote provider capability, weaken native review, or expose
raw transcript content.

## Dependency-ordered backlog

| ID | Surface | Main components | Code-established state | Visual work still required |
| --- | --- | --- | --- | --- |
| UI-00 | Application shell and primitives | `App`, route error/loading boundaries, navigation, `AsyncState`, `Dialog`, `Disclosure`, `EmptyState`, `Tabs`, status/coverage primitives | Frozen implementation; desktop/mobile navigation, bootstrap/route recovery, modal stack isolation, truthful unknown coverage/progress, manual tabs, status semantics, 12 px mobile navigation copy, and synthetic responsive/a11y regressions are covered ([checkpoint note](ui-card-checkpoints/UI-00-shell-and-primitives.md)) | Owner visual review remains pending; inspect desktop/mobile shell, both themes, drawer hierarchy, focus transfer, short-height scrolling, and shared state tour |
| UI-01 | Project catalog | project cards, metric coverage, selection/comparison | Search, sorting, bounded selection, aggregate and incompatibility states tested | Review card hierarchy, selection density, empty/error presentation, desktop/mobile |
| UI-02 | Project workspace | masthead, metric category deck, project facts, timeline, session cards | Route/focus, bounded scope, planned and missing-analysis states tested | Review navigation hierarchy, compact masthead, deck scanability, session-card density |
| UI-03 | Canonical model-ensemble shell | `ModelEnsemblePanel`, run/watch controls, definitions alert | Frozen shell repair; truthful receipt authority, serialized/context-safe controls, terminal/retry states, and responsive/a11y regressions are covered ([checkpoint note](ui-card-checkpoints/UI-03-model-ensemble-shell.md)) | User visual review remains pending; then keep nested metric-card changes in UI-04+ |
| UI-04 | Metric workspace | `MetricWorkspace`, exact-value board, lens controls, snapshot/comparison context | Frozen implementation; 20-contract authority partition, raw-value truth, explicit nonnumeric states, A→B context safety, comparison truth, and responsive/a11y regressions are covered ([checkpoint note](ui-card-checkpoints/UI-04-metric-workspace.md)) | User visual review remains pending; keep radar/card placement changes in UI-05 and drawers in UI-06 |
| UI-05 | Metric radar and knowledge | `ModelEnsembleRadar`, `MetricKnowledgeCard`, `MetricExplainer`, context facts | Frozen implementation; 12 px copy floor, named radar/help regions, viewport-safe overlays, long-copy/mobile rules, and same-key A→B card ownership are covered and independently rechecked ([checkpoint note](ui-card-checkpoints/UI-05-radar-and-knowledge.md)) | User visual review remains pending; inspect light/dark, enlarged text, keyboard/touch pinning, viewport edges, and scroll/resize behavior |
| UI-06 | Metric history and model stages | `MetricHistoryDrawer`, `ModelConstellationDrawer` | Frozen implementation; numeric/state history truth, raw versus oriented values, snapshot/stage context reset, provenance, compact parity, and true/false/unknown unload receipts are covered and independently rechecked ([checkpoint note](ui-card-checkpoints/UI-06-history-and-model-stages.md)) | User visual review remains pending; inspect disclosure affordance, dense trajectories, long identities, comparison readability, and narrow layouts |
| UI-07 | Generic evidence import | `MetricEvidenceFilePanel`, definitions alert | Frozen implementation; exact-run ownership, bounded file validation, fail-closed native decisions, state hierarchy, focus/Escape, and first-render A→B stale-action rejection are covered and independently rechecked ([checkpoint note](ui-card-checkpoints/UI-07-generic-evidence-import.md)) | User visual review remains pending; inspect full/compact hierarchy, all file/transport states, action feedback, long safe metadata, and narrow layouts |
| UI-08 | Requirement-plan evidence | `RequirementPlanEvidencePanel` | Frozen implementation; exact owner/live-control epochs, strict r5/r6/r7 contract/file/proposal/review/decision checks, complete clause truth, coherent fail-closed presence, decided states, focus/`Escape`, and responsive wrapping are independently rechecked ([checkpoint note](ui-card-checkpoints/UI-08-requirement-plan-evidence.md)) | User visual review remains pending; inspect complete clause sets, exclusions/bases/links, long coordinates, acknowledgement clarity, and mobile/full/compact modes |
| UI-09 | Requirement-action evidence | `RequirementActionEvidencePanel` | Frozen implementation; exact public binding/source/transport ownership, strict descriptor/candidate/membership receipts, inert import plus native review/decision, decided-state truth, full opaque IDs, focus/`Escape`, and responsive wrapping are independently rechecked ([checkpoint note](ui-card-checkpoints/UI-09-requirement-action-evidence.md)) | User visual review remains pending; highest visual risk remains long escaped text, dense indices/memberships, clipping, light/dark, and mobile/full/compact modes |
| UI-10 | Quality profile | `QualityProfileView`, `QualityRadar`, metric board, analyze/share dialogs | Frozen implementation; exact preset/profile/pack/session/provider readiness ownership, malformed-input withholding, authoritative board-before-radar hierarchy, direction-safe axes, same-kind A→B context resets, captured dialog handlers, and focus/responsive rules are independently rechecked ([checkpoint note](ui-card-checkpoints/UI-10-quality-profile.md)) | User visual review remains pending; inspect radar/board hierarchy, all empty/unknown/incompatible states, analyze/share dialogs, long identifiers, themes, and mobile information hierarchy |
| UI-11 | Session metric surroundings | `SessionRadarCard`, session timeline/transcript, coaching, model judge, model-link experiment | Most nested panels have direct tests; radar card is mainly composite-covered | Review competing disclosures and primary-action hierarchy around the canonical metric panel |
| UI-12 | Local sources | Codex and Claude source cards, bounded controls, readiness, project/session selector | Consent, bounds, labels, capabilities, empty/error states tested | Review source-card parity, truth-copy density, selection/editor flow, mobile layout |
| UI-13 | Overview and session catalog | four overview tiles, next steps, session rows | Independent loading/ready/unavailable and navigation tested | Review scanability, unavailable values, row density, empty/search states |
| UI-14 | Jobs and automation | job cards/detail, health/filter controls, project grant/readiness panels | Strong direct and viewport tests | Review progress hierarchy, destructive-action clarity, dense failure/recovery copy |
| UI-15 | Prompt checks, calibration, models | prompt cue/commentary cards, rating workspace, hardware/runtime/model cards and chat | Core workflows and gating tested | Review complex forms, history tables/plots, local-model provenance, small-screen behavior |
| UI-16 | Reviewed tasks and task flow | task summary, observation cards, provenance, board cards, audit/lifecycle controls | Task-flow browser coverage is strong; task summary/provenance are weakly targeted | Review task-detail hierarchy first, then board/timeline density and lifecycle confirmation |
| UI-17 | Research lab | operability panel, metric/method/model cards, inventory, compatibility | Operability and inventory direct; some compatibility coverage is composite | Preserve honest 16/0/4 messaging while reviewing tabs, card density, unknown/unavailable states |
| UI-18 | Agent workspace | history/settings, team folders, conversation/tool activity, approvals, diff review | Agent/workspace workflows tested; `TeamFoldersPanel` lacks targeted coverage | Review streaming/tool/diff hierarchy, approval prominence, compact window; add TeamFolders coverage before redesign |
| UI-19 | Team and social | readiness cards, aggregates, member visibility, conversations, file offers, transfer controls | Extensive state and responsive coverage | Review privacy language, suppressed/denied states, dialogs, mobile multi-pane navigation |
| UI-20 | Secondary windows and experiments | live mini window, model-ensemble overlay, local model-link and other experimental panels | Overlay has strong viewport/a11y coverage; live window is directly tested | Review window chrome, compact-mode consistency, disconnect/retry states, experimental labeling |

## First recommended visual tranche

Begin with one owner spot-check of UI-00, then continue UI-03 through UI-10
because those are the card surfaces changed by the stabilized r7 tranche. Use
this internal order:

1. Application shell at short desktop height and 360 px, including the mobile drawer and shared state tour.
2. Model-ensemble shell and metric workspace.
3. Radar, knowledge card, history, and model-stage drawers.
4. Generic evidence import.
5. Requirement-plan evidence.
6. Requirement-action evidence in full and compact modes.
7. Quality profile exact board, secondary radar, readiness, analyze, and share dialogs.

Only after those surfaces are visually stable should work expand to unrelated
project, source, task, agent, team, or social cards.

## Coverage gaps to close when reached

- No screenshot visual-regression tests exist.
- `RequirementActionEvidencePanel` has no real-browser visual flow despite its
  long exact strings and nested receipt/membership content.
- `TeamFoldersPanel`, `SessionRadarCard`, `TaskSummary`, and `ProvenancePanel`
  have the weakest targeted component coverage.
- Local Sources and the live mini window still lack a route-level responsive
  check. Checkpoint 9A now covers Overview, Sessions, Calibration, and Models;
  it also requires every Models state to retain its labelled page heading.

These are backlog priorities, not claims that the cards are currently broken.
