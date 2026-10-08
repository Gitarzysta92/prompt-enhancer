# Sweep-01a route and control ledger

Status: automated complete; owner click-later review queued
Updated: 2026-08-31

This is the authoritative Sweep-01a map. “Shell green” means the direct route
resolves to a nonblank screen, receives the correct navigation owner, has a
truthful title policy, avoids the route error boundary and produces no console
error under synthetic traversal. It does not yet claim that every nested
control on that screen has completed the control-contract audit.

## Route families

| Surface | Supported direct paths | Navigation owner | Title owner | Current evidence |
| --- | --- | --- | --- | --- |
| Discovery | `/` | Discovery | Shell | Shell green; controls active |
| Overview | `/overview` | Overview | Shell | Shell green; controls active |
| Project catalogue | `/projects` | Projects | Shell | Shell green; controls active |
| Project overview | `/projects/{project}/overview` | Projects | Screen | Shell green; controls active |
| Project sessions | `/projects/{project}/sessions` | Projects | Screen | Shell green; controls active |
| Project metrics | `/projects/{project}/metrics/{category}` | Projects | Screen | Shell green; controls active |
| Session metrics | `/projects/{project}/sessions/{session}/metrics/{category}` | Projects | Screen | Shell green; controls active |
| Project automation | `/projects/{project}/automation` | Projects | Shell | Shell green; controls active |
| Global sessions | `/sessions` | Sessions | Shell | Shell green; controls active |
| Agent | `/agent` | Agent | Shell | Shell green; controls active |
| Agent child window | `/agent/window`, `/agent/window/{session}` | Chrome-less | Shell | Both shapes shell green; controls active |
| Reviewed task | `/tasks/{task}/revisions/{revision}` | Reviewed tasks | Shell | Shell green; controls active |
| Task flow | `/tasks/flow` | Task flow | Shell | Shell green; controls active |
| Prompt check | `/prompt-checks`, `/prompt-checks/{check}`, `/prompt-checks/for/{session}` | Prompt check | Shell | All three shapes shell green; controls active |
| Calibration | `/calibration` | Calibration | Shell | Shell green; controls active |
| Models | `/models` | Models | Shell | Shell green; controls active |
| Data sources | `/local-sources` | Data sources in local-real mode | Shell | Shell green; mode gate preserved; controls active |
| Analysis jobs | `/analysis-jobs` | Analysis jobs | Shell | Shell green; controls active |
| Methods & models | `/research/methods` | Methods & models | Shell | Shell green; controls active |
| Team analytics | `/team` | Team analytics | Shell | Shell green; controls active |
| Social hub | `/social` | Social | Shell | Shell green; controls active |
| Live child window | `/live/projects/{project}`, `/live/projects/{project}/sessions/{session}` | Chrome-less | Shell | Both shapes shell green; controls active |
| Unknown or malformed path | Any non-allowlisted path; canonical recovery `/not-found` | None | Shell | Fixed: truthful content-free recovery, two working exits |

Identifiers in this table are abstract placeholders. Production route parsing
accepts only allowlisted lowercase pseudonyms and metric categories.

## Global shell controls

| Control/state | Contract | Evidence | Status |
| --- | --- | --- | --- |
| Skip to main content | Focuses one stable `main` target | App keyboard test | Green |
| Desktop primary navigation | One active owner, grouped destinations, no duplicate history push | App/platform tests plus 27-shape traversal | Green |
| Mobile navigation dialog | Current destination receives focus; selection closes then navigates | App mobile tests | Green |
| Browser title | Shell-owned exact title or screen-owned bounded title | Typed manifest plus traversal | Green |
| Back/forward platform events | Parse and emit current allowlisted route and synchronize screen, title, focus and active owner | Platform tests plus integrated App history traversal | Green |
| Reviewed tasks shortcut | One abortable latest-task lookup with visible success/empty/error status | App async navigation tests | Green |
| Local-service retry | Rechecks health without replacing the current screen | App health tests | Green |
| Lazy route loading | Named stable loading state | App lazy-route tests and traversal | Green |
| Route failure | Content-free Retry, Reload and truthful exit | Route-boundary tests | Green |
| Unknown route | No silent Discovery substitution; Overview/Discovery exits | New parser, App and browser-platform tests | Green |

## Completed control-audit order

1. primary work: Agent, Models, Projects/Sessions and workspace controls;
2. review work: Discovery, Reviewed task, Task flow, Prompt check, Calibration;
3. system work: Data sources, Analysis jobs and Methods & models;
4. collaboration: Team and Social fail-closed controls;
5. child windows and every loading/empty/error/retry variant.

All five groups now share the rendered disabled-reason/name audit and the
TypeScript source contract for wired native controls. Focused state-recovery
packs are green; see [the state recovery ledger](sweep-01a-state-recovery-ledger.md).
Complete regressions and the rebuilt live-browser pass are green. The local-real
audit now covers Agent, Models, Prompt Check, Analysis jobs and Data sources
prerequisite states in addition to the exhaustive synthetic direct-route
traversal. See the [checkpoint handoff](checkpoint-sweep-01a-handoff.md) for the
exact gate and process receipts.
