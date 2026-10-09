# Architecture atlas

Audit date: 2026-10-08. This is a contributor map, not a beta certificate.

A later feature-branch proposal, [ADR 0022](../adr/0022-inference-provider-boundary.md),
separates inference providers from local runtime ownership. Its October 9 tests
and scope are recorded separately; the October 8 source observation stays frozen.

## Start here

1. Read the [system map](../images/architecture-overview.png).
2. Find the component ID in the [feature catalog](feature-catalog.md).
3. Check its evidence level, source publication state and next acceptance step.
4. Use [change recipes](change-recipes.md) to identify the files and tests.
5. Take one [bounded task](remaining-work.md), with owner review before merge.

Designers should also read the [journey/state handoff](design-handoff.md).

The [readiness matrix](../product-readiness-matrix-2026-09-12.md) remains the
authority for requirement acceptance. This atlas is a dated projection of code,
existing tests and that ledger. The [journal](../beta-progress-journal.md) records
execution history. Accepted architecture decisions live in [ADRs](../adr/README.md).
Updating this map never closes a gate by itself.

## Read the colors correctly

| Color | Meaning | What it does not establish |
| --- | --- | --- |
| Green — ready | The bounded component contract has recorded passing evidence; read the node's evidence scope. | Full user journey, every model, installation or beta approval. |
| Yellow — partial | Real implementation exists but a required integration, qualification, correction or acceptance step remains. | A mock, or proof the complete journey works. |
| Red — absent | The stated capability is planned but its required implementation/composition is absent. | That all supporting libraries or seams are absent. |
| Grey — mock | Deliberately synthetic/demo/test implementation. | A usable production integration. |

Color is independent of scope: required, experimental or deferred. A deferred
feature can have real partial code; an experimental feature is not automatically
a mock. Labels repeat the colors so the diagrams remain usable without color.
No percentage of green nodes is a release-completion percentage.

## Which source was inspected?

Two baselines are deliberately distinguished:

- Published source reference: `origin/main` at `bfb67b6`, freshly fetched on the
  audit date. The private repository metadata was checked separately.
- Development observation: `acdf0e5` plus 747 preserved changed/untracked files.
  This is not a clean commit or a distributable artifact. A separate five-file
  setup-recovery cohort is also uncommitted and was not included in this branch.

The catalog binds referenced implementation/test files to SHA-256 values and
reports whether each path is identical after CRLF-to-LF normalization, different from, or absent on the
published baseline. A path existing on main does not imply identical behavior.
Unpublished paths are shown as code text rather than broken clickable links.
`sha256` binds exact observed bytes; `normalized_sha256` binds LF-normalized text;
`main_sha256` binds Git blob bytes. Different raw hashes can therefore have the
same normalized content. No other semantic normalization is applied.
The documentation branch carries this map and its rendering tooling only;
it does not secretly publish those pending implementations.

## System shape and design patterns

Prompt Enhancer is a local modular monolith with explicit adapters around
provider access, SQLite, model runtimes, HTTP/MCP, native windows and filesystem
effects. `bootstrap.py` composes the backend; the HTTP app mounts bounded routes.
The React shell selects feature slices and uses shared API/platform adapters.
This is the governing pattern, not a claim that every file follows it perfectly.

Three execution lanes must stay distinct:

| Lane | Input and authority | Persistence and output |
| --- | --- | --- |
| Analytics | Consented, read-only provider signals; minimized/redacted before ordinary storage. | Versioned evidence, metrics and provenance; unknowns remain states. |
| Authored Agent | User's selected workspace and local chat; protected operations require exact native approval. | Private project/chat store and verified tool/artifact receipts. |
| Multimodel workflows | Planned typed local graphs; immutable revision and input bindings, bounded owned workers. | Planned private run/attempt/artifact store; explicit reviewed export. |

The trusted metric dependency graph is implemented analysis infrastructure.
It is **not** the planned user-editable multimodel workflow graph. The existing
project automation scheduler is also not that workflow engine.

Important patterns already present include ports/adapters, typed DTO boundaries,
explicit composition, consent/capability checks, immutable analysis snapshots,
optimistic revision checks, single-use approval receipts, owned subprocesses,
and separate command/query projections over SQLite. The design uses ordinary
transactional state; it is not universal event sourcing or microservices.

## Data and authority boundaries

Provider sessions remain external, read-only inputs. Authored Agent history is a
different store and retention decision. Model outputs are interpretations, not
objective evidence. Native presence cannot be synthesized by browser tests,
API clients or MCP. A model name in a catalog is not proof of genuine inference.

The runtime owner must confirm process-tree exit before releasing authority or
resource leases. Planned workflow workers must coexist with chat/research
runtimes without silently changing their selected model. Update evaluation and
signature verification are separate from executing an installer.

## What this audit validates

Static source/route/test inventory, source publication comparisons, design
consistency, documentation links, diagram/catalog consistency, and selected
synthetic contract/privacy checks. Existing dated runtime evidence is identified
as historical. No private provider data, personal app, GPU model, installation,
certificate trust or real update was used during this documentation audit.

See [validation](validation.md) for exact results and limits. There is no claim
that every source function or every UI state was dynamically exercised.

## Domain diagrams

Each PNG is readable without Mermaid. SVGs are editable and link node IDs to the catalog.

| Domain | PNG | Editable SVG |
| --- | --- | --- |
| System | [Overview](../images/architecture-overview.png) | [SVG](../images/architecture-overview.svg) |
| Analytics | [Pipeline](../images/architecture-metrics.png) | [SVG](../images/architecture-metrics.svg) |
| Twenty metrics | [Contracts](../images/architecture-contracts.png) | [SVG](../images/architecture-contracts.svg) |
| Agent | [Chat, tools, MCP](../images/architecture-agent.png) | [SVG](../images/architecture-agent.svg) |
| Workflows | [Engine and model families](../images/architecture-workflows.png) | [SVG](../images/architecture-workflows.svg) |
| Composer | [Workflow enhancement](../images/architecture-composer.png) | [SVG](../images/architecture-composer.svg) |
| Distribution | [Native and release](../images/architecture-release.png) | [SVG](../images/architecture-release.svg) |

The [route and source census](surfaces.md) covers all declared route families,
feature directories and HTTP route modules, including large-file hotspots.

## Maintaining the atlas

`atlas.json` is the editable graph/catalog input. It records component IDs,
dependencies, source/test references, status, scope, gap and next action.
`source-observation.json` is a generated, content-free source binding and census.
The generated catalog and PNG/SVG diagrams derive from those inputs.

After implementation, update the authoritative ledger first, then the affected
atlas nodes and evidence. Regenerate and review diagrams; changed PNGs need exact
hash approval in the existing privacy scanner. Do not add broad image exclusions.
The repository skill routes an agent through this workflow:
[prompt-enhancer-development](../../.agents/skills/prompt-enhancer-development/SKILL.md).
