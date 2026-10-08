# ADR 0001: Modular monolith with hexagonal boundaries and an explicit metric graph

- Status: Accepted
- Date: 2026-08-06
- Scope: local application architecture, provider integration, metric extension,
  persistence boundaries, and dashboard integration

## Decision

Build Prompt Enhancer as a **modular monolith** with:

1. hexagonal (ports and adapters) boundaries at provider, storage, analysis,
   network-egress, HTTP, CLI, charting, and desktop-runtime interfaces;
2. a staged privacy ingress pipeline that is the only route from ephemeral
   provider data to safe canonical data;
3. an explicit, trusted registry of feature extractors and metric calculators;
4. a validated directed acyclic graph (DAG) for reusable analysis features and
   derived metrics;
5. SQLite as the local system of record, with append-only analysis runs and
   query-oriented projections in the same database;
6. a React modular frontend organized as vertical feature slices; and
7. one composition root that selects concrete adapters and is the only place
   where the application is wired together.

This is not a decision to use microservices, full event sourcing, an unrestricted
runtime plugin host, or a general-purpose workflow orchestrator. We may use
individual ideas from those architectures where they solve a measured problem.

## Context

Prompt Enhancer is a public, local-first desktop analytics application. It will
eventually read user-approved coding-agent activity, compute deterministic and
model-assisted analyses, preserve longitudinal results, and present them through
a dashboard and narrowly scoped agent interfaces.

The architecture must support all of the following at the same time:

- private inputs and privacy-sensitive derived data;
- operation without a cloud service or application login;
- provider integrations whose documented and compatibility interfaces evolve;
- deterministic, local-model, and explicitly approved remote analyses;
- many independently versioned metrics with different applicability and data
  requirements;
- explicit unknown, not-applicable, and abstained states;
- reproducible results with provider, adapter, algorithm, redactor, model,
  tokenizer, prompt, rubric, and schema provenance;
- browser-first UI development followed by a constrained desktop shell; and
- a contributor-friendly public repository that remains testable on one machine.

The Phase 1 implementation already validates three useful boundaries: read-only
provider adapters, ephemeral `Source*` versus persistable `Safe*` types, and a
consent check before provider access. It also exposes two scaling problems: the
database module currently owns many unrelated responsibilities, and all metrics
are computed by one central function.

## Decision method

This decision was cross-validated in four ways:

1. **Constraint fit:** alternatives were scored against the repository's stated
   privacy, offline, provenance, extensibility, and maintenance requirements.
2. **Change-scenario walkthroughs:** each alternative was tested conceptually
   against adding a provider, metric, local model, remote judge, task-discovery
   strategy, dashboard visualization, and future team aggregation.
3. **Threat-boundary review:** we checked which architecture makes provider
   content, filesystem access, arbitrary code loading, network egress, and SQL
   access easiest to constrain and test.
4. **External triangulation:** the rationale was compared with original or
   authoritative descriptions of modularity, ports and adapters, microservices,
   CQRS/event sourcing, plugin discovery, workflow orchestration, and SQLite's
   intended local-application use.

The scoring is a transparent decision aid, not an empirical performance
benchmark. Scores range from 1 (poor fit) to 5 (strong fit).

| Criterion | Weight | Modular monolith + hexagonal + metric DAG | Conventional layered monolith | Microservices | Full event sourcing + CQRS | Runtime plugin core | Airflow/notebook-centered pipeline |
|---|---:|---:|---:|---:|---:|---:|---:|
| Privacy and capability enforcement | 5 | 5 | 4 | 3 | 3 | 2 | 2 |
| Modular change isolation | 5 | 5 | 3 | 5 | 4 | 5 | 3 |
| Metric composition and reproducibility | 5 | 5 | 3 | 4 | 5 | 4 | 4 |
| Local operational simplicity | 4 | 5 | 5 | 1 | 2 | 3 | 2 |
| Automated testability | 4 | 5 | 4 | 3 | 3 | 3 | 3 |
| Contributor iteration cost | 3 | 4 | 5 | 1 | 2 | 3 | 2 |
| Evolution toward larger-scale analysis | 2 | 4 | 3 | 5 | 4 | 4 | 4 |
| **Weighted total / 140** | | **135** | **107** | **89** | **94** | **96** | **79** |

The selected architecture remained first when each individual criterion weight
was varied by one point. The much more important validation is the change-scenario
analysis below; the decision must be revisited if its assumptions stop holding.

## Change-scenario cross-check

| Change | Expected extension point | Existing modules that should change |
|---|---|---:|
| Add a documented provider | provider adapter plus canonical mapper | 1 registration plus new adapter package |
| Add an ordinary deterministic metric | calculator plus definition and contract test | no storage, API, or UI change |
| Reuse an expensive derived fact | feature extractor node | dependent calculators only |
| Replace an embedding or NLI model | analysis backend adapter and model manifest | no provider or UI change |
| Add a task-discovery method | discovery-signal strategy | no canonical event or metric rewrite |
| Add an unusual visualization | frontend metric presenter or chart adapter | no backend calculator change |
| Add optional remote judging | egress-gated analysis adapter | no implicit fallback from local analysis |
| Add DuckDB later | disposable analytical/query adapter | SQLite remains the system of record |

If ordinary changes repeatedly cross more boundaries than shown here, the
architecture is failing its primary modularity claim.

## Module and dependency rules

Backend dependencies point inward:

```text
interfaces -> application -> domain
infrastructure -> application ports -> domain
bootstrap -> interfaces + infrastructure
```

- `domain` does not import FastAPI, SQLite, provider SDKs, Hugging Face, Tauri,
  or remote clients.
- `application` expresses use cases and required ports; it does not choose
  concrete infrastructure.
- `infrastructure` owns provider decoders, SQLite SQL, model runtimes, and privacy
  mechanisms implementing application ports.
- `interfaces` translate HTTP and CLI requests into application use cases.
- `bootstrap` is the explicit composition root. A service locator or automatic
  package scan is not used.

Frontend dependencies also point inward:

```text
app -> features -> entities -> shared
```

Features do not import another feature's internals. FastAPI DTOs, ECharts options,
and Tauri APIs are contained behind API, chart, and platform adapters.

## Metric extension model

The trusted registry contains three compositional elements:

- a **feature extractor** computes reusable facts such as usage totals, tool
  attempts, verification evidence, workflow phases, or embeddings;
- a **metric calculator** converts features into one immutable, versioned
  observation; and
- a **metric pack** selects calculators appropriate for a task type, privacy
  tier, or analysis cost profile.

The engine validates duplicate identifiers, missing dependencies, cycles, privacy
tier requirements, and definition/version consistency before execution. Shared
features are cached once per run. Normal metric addition is explicit source-code
composition, not runtime execution of newly discovered packages.

Every result distinguishes `known`, `unknown`, `not_applicable`, `abstained`, and
execution failure. An execution failure is diagnostic information and is never
converted into a user score. Results include coverage, evidence references, and
complete provenance. A changed definition or implementation creates a new result
under a new analysis run; it does not rewrite history.

## Privacy consequences

- Only the ingress pipeline can convert ephemeral provider types into safe
  canonical types.
- Ordinary repositories and metric contexts cannot accept plaintext transcript
  content. A future encrypted content vault is a separate port.
- Network-capable analysis uses one mandatory egress gateway. It requires
  destination-specific consent, local redaction, a payload preview, and recorded
  provenance.
- Provider adapters remain read-only and do not receive persistence or UI
  capabilities.
- The trusted registry is explicit. Python entry-point discovery is deferred
  because loading an entry point imports and executes third-party code in the
  application process.
- The frontend receives narrow query DTOs, never filesystem paths, provider
  credentials, unrestricted SQL, or general shell/filesystem handles.

## Alternatives considered

### Conventional layered monolith

This has the lowest initial ceremony and is a viable implementation technique for
small CRUD applications. It was rejected as the governing architecture because
horizontal layers tend to let provider, database, and framework representations
spread through business logic. The current large database module and central
metric function already demonstrate that pressure. We retain a single process and
deployment unit, but place explicit ports only at real volatility and privilege
boundaries.

### Microservices

Microservices can isolate deployment and scale services independently, but this
product initially has one user, one device, one database, and strong local
transaction and deletion requirements. Service discovery, interservice security,
distributed tracing, versioned network contracts, and eventual consistency would
add risk without providing current value. The architecture can extract a worker
later if profiling demonstrates a real process-isolation or scaling need.

### Full event sourcing and CQRS

Provider activity is naturally event-shaped, and metric history should be
append-only. That does not require making an event store the authority for every
application entity. Full event sourcing adds event evolution, replay, projection,
idempotency, and deletion complications; immutable personal-data histories also
conflict with reliable erasure. We therefore store canonical observed events and
immutable analysis runs, while using ordinary transactional state for consent,
task review, configuration, and deletion. We use only a light command/query
separation over the same SQLite database.

### Unrestricted runtime plugin architecture

Automatic plugin discovery makes third-party extension convenient, but it grants
installed code the application's provider, filesystem, database, and potentially
network authority. That is the wrong default for a privacy-sensitive public tool.
Built-in extensions use explicit registration and contract tests. If external
plugins become necessary, a later ADR must define manifests, capability grants,
process isolation, resource limits, signatures or trust UX, and a stable protocol.

### Airflow, notebooks, or a general workflow platform

These tools are strong for exploratory or scheduled batch data processing.
Prompt Enhancer also needs a small distributable desktop runtime, low-latency local
queries, consent and deletion transactions, typed UI contracts, and deterministic
offline operation. A small internal feature DAG solves metric dependency reuse
without adopting a scheduler, metadata service, worker fleet, or notebook as a
production boundary. Notebooks remain useful for research, never as production
metric definitions.

## Consequences and trade-offs

Benefits:

- provider, database, model, UI, and desktop technologies can change behind
  narrow contracts;
- metrics are independently testable, composable, versioned, and explainable;
- the application remains one local deployment unit with one transactional store;
- privacy boundaries become architectural dependencies that tests can enforce;
- deterministic analysis remains useful even when no model is installed.

Costs:

- more packages and explicit wiring than a conventional layered script;
- registry and DAG validation code must be maintained;
- contributors must follow dependency-direction rules;
- SQLite schemas need deliberate projections and migrations as the dashboard
  grows; and
- a Python sidecar plus Tauri still requires platform-specific packaging work.

We will limit those costs by creating ports only at genuine external or privileged
boundaries, avoiding a DI framework, avoiding one package per metric, and migrating
incrementally with compatibility re-exports.

## Fitness functions and acceptance checks

The decision is enforced by automated checks where practical:

1. provider contract tests prove adapters are read-only and consent precedes
   source access;
2. persistence APIs accept safe canonical types, not provider DTOs;
3. registry tests reject duplicate keys, unresolved dependencies, and cycles;
4. metric contract tests verify deterministic results, unknown preservation,
   applicability, privacy tier, provenance, and version stability;
5. API contract tests prove there is no arbitrary SQL, raw transcript, or write
   surface;
6. synthetic-only fixture and privacy scanners run before publication;
7. generated frontend contracts are diff-checked against FastAPI schemas; and
8. tests prevent unexpected network access in offline profiles.

The architectural target for a normal metric is: one calculator, one explicit
registration, and one contract test, with no storage, API, or frontend edit.

## Revisit and falsification triggers

Create a superseding ADR if any of these conditions occurs:

- one local process cannot meet an established latency, memory, crash-isolation,
  or scheduling service-level objective after profiling and optimization;
- multiple machines or team collectors require independent deployment and
  ownership boundaries;
- SQLite measurements show sustained workloads that it cannot serve safely;
- more than two supported external metric ecosystems require third-party runtime
  extension rather than source contribution;
- most new metrics require cross-cutting edits despite the registry and feature
  graph;
- the DAG requires distributed retries, scheduling, backfills, or resource queues
  beyond a small local worker; or
- privacy tests cannot prove that a port or adapter boundary contains the data it
  is intended to protect.

Until such evidence exists, distributed or dynamically executable alternatives
are deferred rather than pre-built.

## Evidence reviewed

- D. L. Parnas, [On the Criteria To Be Used in Decomposing Systems into
  Modules](https://doi.org/10.1145/361598.361623), motivates decomposition around
  hidden design decisions rather than execution steps.
- Alistair Cockburn's original [Hexagonal Architecture](https://alistair.cockburn.us/hexagonal-architecture)
  describes isolating application behavior from UI and database technologies
  through ports and adapters.
- Microsoft documents the operational and consistency trade-offs of
  [microservices](https://learn.microsoft.com/en-us/azure/architecture/microservices/),
  [CQRS](https://learn.microsoft.com/en-us/azure/architecture/patterns/cqrs), and
  [event sourcing](https://learn.microsoft.com/en-us/azure/architecture/patterns/event-sourcing).
- Python's packaging guide shows that automatic
  [plugin discovery](https://packaging.python.org/en/latest/guides/creating-and-discovering-plugins/)
  ultimately loads registered code into the host process.
- Apache Airflow describes itself as a platform for
  [batch-oriented workflow orchestration](https://airflow.apache.org/docs/apache-airflow/stable/index.html),
  a broader operational scope than the required local feature graph.
- SQLite's own guidance identifies
  [local application storage](https://www.sqlite.org/whentouse.html) as a primary
  use case and distinguishes it from a shared client/server repository.

## Implementation sequence

1. Add application analysis contracts, an explicit registry, reusable feature
   extraction, and compatibility through the existing public metric function.
2. Add the composition root and move CLI construction into it.
3. Split persistence into focused repositories behind application ports.
4. Add immutable `analysis_run` and result history migrations.
5. Add task-discovery candidates and reviewable task revisions.
6. Add typed query DTOs and generate a build-time frontend contract.
7. Scaffold the React dashboard using only synthetic data.
8. Add the constrained Tauri host after the browser dashboard is stable.
