# Remaining work and finite delivery order

This is a task-routing view of the existing nine waves and B/W/WP gates.
Acceptance stays in the product-readiness matrix. No scope has been removed.

| Order | Work package | Concrete finish line | Main dependency |
| --- | --- | --- | --- |
| 1 | Baseline recovery | Dependency-complete reviewed commits; collaborators can reproduce the selected baseline; no blanket dirty-tree commit | B00–B01 |
| 2 | Test observability and build graph | Incremental frontend results identify unfinished/failing cases; deferred Agent chunks meet existing budgets | Full frontend timeout and `E_BOUNDARY` |
| 3 | Native foundation and early compilation | Owned lifecycle/no terminal storms; qualified compiled text/image/audio worker spike | B02, W00, approved model/hardware inputs |
| 4 | Model setup and useful metrics pilot | Approved model acquisition/load/unload; interpretation gates pass; storage/API/radar values and missing states agree | B04, B07, MI/MA/MS/MC/MU gates |
| 5 | Complete Agent journeys | Model-free persistent chats, native folder picker/tools, verified artifacts, supported MCP recovery | B03–B06 and relevant B10 checks |
| 6 | Workflow contracts and durable engine | Typed graph validation; immutable revisions; sequential chains/branches/joins and recovery | W01–W02 |
| 7 | Qualified adapters and real parallelism | Eight model families plus second LLM; actual admitted two-worker overlap and cleanup | W00, W03–W04 |
| 8 | Builder, advisor and enhancement hook | Accessible Build/Run/Results; device-fit explanations; reviewed draft suggestions; headless parity | W05–W06, WP01–WP08 |
| 9 | Signed distribution and update execution | Compiled inventory/notices; signed install; real consent-bound Apply, retained data, relaunch and recovery | B08–B09 |
| 10 | Exact release candidate | Full gates on fixed source/package; CPU/NVIDIA/clean-machine coverage; two packaged smokes and owner review | B10–B11, W07–W08 |

Parallel contributor work is possible when task cards name independent files and
accepted contracts. It cannot skip prerequisites or replace genuine inference,
native approval or installed update execution with mocks.

## Architecture corrections to propose, not silently rewrite

- Keep the modular monolith. Extract oversized coordinators one tested boundary
  at a time: composition, route translation, Agent use cases, model lifecycle,
  desktop orchestration and SQLite repositories. File length alone is not a bug;
  coupling, ownership ambiguity and regression risk justify extraction.
- Turn accepted dependency direction into focused import-boundary tests where
  missing. Inventory static imports first; explicitly document compatibility
  facades rather than forcing a wholesale package move.
- Inspect known boundary exceptions explicitly: update readiness uses an exact
  concrete infrastructure class check; prompt-check construction chooses concrete
  redaction/language adapters; annotation/shared-folder application modules use
  SQLite directly. Decide whether each is a documented compatibility boundary or
  should move behind an injected port. The census's zero absolute import matches
  does not cover these relative imports or framework coupling.
- Preserve a single model/process ownership vocabulary across chat, analysis,
  MCP and planned workflows. The future shared coordinator must account for
  load peaks and must not interrupt a personally loaded model.
- Keep three stores/retention contracts distinguishable: minimized analytics,
  private authored history, and future private workflow run contents. Avoid
  placing workflow payloads in content-free analysis job records.
- Resolve documentation drift: historical public-source/Tauri/in-memory-Agent
  statements do not describe the present target. See ADR 0020; keep historical
  rationale visible instead of rewriting old decisions as if always true.
- Keep UI capability labels driven by observed runtime/backend support. Avoid
  separate guessed truth in the model picker, Agent, radar and workflow advisor.
- Preserve the unresolved POSIX inventory ancestor-swap finding as a distinct
  dev-tool blocker. Two previous correction passes do not reset with a new task.
- The current beta design omits inline PDF parsing until provenance closes.
  Integrate that unpublished boundary and prove the worker is excluded from the
  package; hiding its viewer alone does not remove a bundled dependency.

## Decisions and environments still needed

The owner supplies public release identity/publisher metadata, signing and update
verification identities, a binary release destination, approved model/license/
artifact profiles, hardware budgets, clean Windows CPU and physical NVIDIA
acceptance environments, and beta support/terms. Secret keys stay outside chat
and source. These inputs can be prepared while independent source work proceeds.

Accounts, Stripe, teams, hosted services, arbitrary model compatibility and remote
workflow connectors remain deferred. Their code/data is preserved. The required
multimodel workflow editor, prompt-enhancement hook and real parallel execution
are not deferred merely to make the beta appear closer.
