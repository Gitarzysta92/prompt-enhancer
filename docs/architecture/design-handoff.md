# Design handoff: usable journeys and honest states

Read the [catalog](feature-catalog.md) before designing a component. A source UI
can be present while its installed journey remains partial. New visual designs
are proposals until reviewed; this audit does not authorize a framework rewrite.

## Information architecture

Primary work remains Agent, Models, Overview, imported Projects/Sessions, Data
sources and Settings. Prompt check, calibration, task/evidence review and analysis
jobs remain reachable where supported. Research is experimental; deferred teams,
social, billing and hosted actions must not look like available beta features.

Always distinguish an imported provider session from an authored Agent chat.
Selecting a workspace or creating a chat does not require a loaded model.
Selecting a model, downloading it, loading it, and sending a message are distinct
actions. A loaded model's identity/readiness belongs near the composer alongside
placement, truthful context usage and Stop.

## Per-surface acceptance checklist

| Surface / nodes | Primary journey | States the design must expose | Boundary to preserve |
| --- | --- | --- | --- |
| Data sources / MA01–MA05 | Select and consent to a supported source | Checking, empty, unsupported version, revoked, denied, failed, retry | No implicit provider reads; no raw diagnostic details |
| Analysis / MA08–MA15 | Review evidence, run bounded analysis, inspect result | Queued, loading, running, cancel, failed, interrupted, stale prior result | No model claim becomes objective success |
| Radar / MA16 | Choose session and watch the current bounded snapshot | Known zero, unknown, pending, not applicable, unavailable, error; source coverage and age | A sparse radar is honest missing evidence, not an excuse to draw fabricated axes |
| Calibration / MA17 | Review, rate, save/reopen and export selected data | Unrated, saved, stale review, insufficient sample, failed export | Experimental model estimate is separate from measured facts |
| Agent / A02–A07 | Create chat, draft, choose model, send/stop, reopen | Model-free drafting, loading, streaming, waiting for approval, interrupted, retry | Completed history survives; permission/approval does not silently survive |
| Models / A08–A10 | Find an approved model, download/load/switch/unload | Unsupported profile, disk/memory limit, partial download, invalid hash, cleanup unconfirmed | Fit estimate versus measured use; no universal 'best model' claim |
| Workspace / A11–A17 | Browse folder, read, review exact diff, approve/reject | Native/browser limitation, missing folder, stale file, changed workspace, cancellation, failed tool | No workspace deletion from project deletion; native approval stays exact |
| Artifacts / A17–A19 | Open a verified result or supported attachment | Proposed versus actual file, unsupported/large media, safe fallback | No artifact based solely on assistant prose; no embedded script execution |
| MCP / A23–A26 | Browse/review/setup/use/revoke/remove | Registry outage, cache age, unreviewed package, connection failure, revoked, cleanup unresolved | Discovery is not trust; removal cannot invent cleanup proof |
| Workflows / W01–W08 | Build, validate, preview, run, inspect results | Invalid port, cycle, missing input/model, waiting resource, failed branch, interrupted, cleanup unconfirmed | Backend enforces types; visual parallelism is not inference overlap |
| Composer hook / WP01–WP08 | Select compatible workflow, compare suggestion, apply/undo | Draft changed, late result, canceled, failure, preserved original | No silent rewrite/send; no recursive enhancement; no wrong-chat application |
| Updates / R11–R23 | Check, review verified update, approve apply, reopen | Not configured, unavailable, staged, rejected signature, busy, applying, recovery needed | Do not show Apply enabled until exact native prerequisites are present |

## Accessibility and layout

Check 1280×720, 1366×768 and 1920×1080, plus supported 100/125/150/200% scaling.
Menus and model pickers stay within the usable viewport. The composer and Stop
must remain reachable. Keep inventory, diagnostic and advanced configuration
panels collapsed by default. Provide an accessible list alternative to the
workflow canvas, visible focus, meaningful labels, keyboard traversal, focus
return and understandable loading announcements.

Use text as well as color for statuses. Do not show missing usage as zero or a
model score as a calibrated probability. In graphs, label the type/unit and
direction of each connection; joins bind stable port identity, not completion
order. Show configured preprocessing rather than silently cropping/resampling.

## Review artifact

A design PR names component IDs, the user task, current evidence, changed states,
keyboard/layout behavior, synthetic fixtures and backend capability dependency.
If a UI exposes a new authority or changes data retention, include the affected
ADR proposal. The owner reviews before merge. Rendered synthetic UI and component
tests do not replace the final native/installed owner journey.
