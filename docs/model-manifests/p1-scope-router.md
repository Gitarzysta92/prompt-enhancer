# P1 deterministic scope-router foundation

Status: synthetic contract foundation only. Promotion and activation are disabled.

## Purpose and boundary

The deterministic scope router decides whether a metric target and a typed
evidence packet are compatible before a classifier or rubric specialist may
inspect the packet. It is language-independent because it processes objective
metadata only. It never receives authored expected labels, prompt text, evidence
bodies, model judgments, local paths, or provider account identifiers.

The closed output states are:

- `compatible`
- `different_scope`
- `superseded`
- `insufficient_evidence`
- `not_applicable`

Every output includes a typed safe reason and evidence coverage. Unknown,
unsupported, failed, partial, and incompatible evidence never becomes zero.
Only explicit `absent` receipts produce a known missing fraction.

Reviewed precedence is:

1. explicit metric non-applicability;
2. explicit later superseding revision;
3. unknown applicability;
4. missing comparison scope;
5. project, session, revision, requirement identity, immutable requirement-version,
   and chronology incompatibility;
6. missing immutable requirement-version linkage;
7. incomplete extraction;
8. typed evidence availability;
9. compatible only when every required evidence kind is explicitly available.

The router accepts only `ScopeRouterInput`. The evaluator-only
`ScopeRouterCase` owns expected state and reason, and cannot be passed to the
router. Opaque identifiers are lowercase SHA-256 pseudonyms. Contract validation
rejects raw identifier payloads and extension fields.

## Frozen synthetic screen

- benchmark: `scope_router_metadata_screen_v1`
- fixture SHA-256:
  `04eae107e476c0e00dcada8f9445daaafeed60e91e03d2a7da873a75ffd6383c`
- generator: `scope-router-corpus-generator-v1`
- router: `deterministic-scope-router-v1`
- evaluator: `scope-router-evaluator-v1`
- metric definition: `scope-router-metrics-v1`
- 30 effective metadata scenarios; 6 for each closed output state
- 120 evaluator rows after repeating each scenario across bug fix, code review,
  feature, and research/design reporting strata; task stratum is not a router
  input, so those repetitions are not counted as distinct scenarios
- first promotion-screen target: at least 96 effective scenarios; this foundation
  has 30 and explicitly fails that size gate
- synthetic reserved-derived opaque identifiers only
- no model downloads, model weights, network calls, private sessions, or runtime
  artifacts

The corpus covers exact and prior compatible evidence; project/session/revision/
requirement/version/chronology boundaries; explicit supersession; unknown
applicability; missing scope, requirement, and immutable requirement-version
links; partial extraction; known absence; and non-applicability precedence.
Focused contract tests separately cover chronology, unknown availability,
unsupported evidence, and failed evidence states.

## Aggregate foundation result

| Measure | Result |
| --- | ---: |
| Effective scenarios / target | 30 / 96 — gate not met |
| Accuracy over repeated reporting rows | 1.000000 |
| Macro precision / recall / F1 | 1.000000 / 1.000000 / 1.000000 |
| Reason accuracy | 1.000000 |
| Insufficient-evidence precision / recall | 1.000000 / 1.000000 |
| Selective coverage | 0.800000 |
| Selective accuracy / risk | 1.000000 / 0.000000 |
| Repeat stability | 1.000000 |
| Reverse-order stability | 1.000000 |
| Authored-label mutation stability | 1.000000 |
| Opaque-ID perturbation stability | 1.000000 over 360 comparisons |

The public report contains aggregates, version identifiers, the fixture digest,
and safe limitation codes only. It contains no case identifiers, requirement or
evidence references, template identifiers, fixture paths, or per-case output.

## Interpretation and release limits

The exact synthetic result shows that the frozen precedence table and contracts
behave as specified. The 120 reporting rows contain only 30 distinct relational
metadata scenarios, and the public report exposes that effective count and a
false size-gate result. The score does not demonstrate estimator quality on real
provider metadata, private calibration performance, human agreement, drift
resistance, or state-of-the-art performance. The rules and test generator were
designed together, so synthetic success cannot be used as ground truth for
promotion.

Activation remains false until the corpus has at least 96 effective preregistered
scenarios and the router is evaluated on a separately frozen, representative,
time/project-separated private holdout with blind human or valid objective truth,
missingness slices, provider-version compatibility, stability, privacy, and
release-gate evidence. Any future rule change requires a new router, fixture,
generator, evaluator, and metric-definition version rather than silently
rewriting this result.
