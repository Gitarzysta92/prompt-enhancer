# Exotic open-weight specialist screen for the twenty-metric radar

Snapshot: 2026-08-17
Scope: candidate screen and router design for signals beyond ordinary NLI
Status: **research memo. No candidate is promoted, activated, downloaded, or
manifested. Nothing here authorizes a download.**

## 0. Verification status and its limits

Provenance facts in section 4 were read from official Hugging Face surfaces in
this run: the model API endpoint (`/api/models/{id}`) for the commit SHA,
license, tags, and file list, and the model card or raw `config.json` /
`License.md` for label semantics, context, base chain, and license text. Direct
URLs are in section 11, each marked with whether it was read at an immutable
revision or at `main`.

**What was established is repository metadata, not supply-chain clearance.** For
every candidate in this memo, two required checks remain **unresolved**:

- **Artifact digests.** The manifest requires a SHA-256 per weight file. The API
  listing does not expose one, and computing it requires downloading the
  artifact, which this memo does not authorize. **No weight digest appears
  anywhere in this document.**
- **Training-data license chains.** A permissive checkpoint tag and a permissive
  base model do not clear the *data*. Several candidates are trained on
  LLM-generated or aggregated pools whose license posture is unsettled
  (section 8).

So no candidate here has passed supply-chain review. The strongest status any
candidate holds is **metadata precheck passed, supply chain unresolved** — which
means "eligible to be considered for a screen," never "cleared," "adopted," or
"drop-in ready."

Recorded SHAs are repository HEAD **as observed on 2026-08-17**. A SHA is
immutable but HEAD moves; re-read the API before writing any pin.

Two classes of claim are kept distinct throughout:

- **Verified metadata.** Model ID, commit SHA, SPDX tag, weight format,
  remote-code status, label map, context, language tags, parameter count.
- **Contract-decidable analysis.** Conclusions following from this product's
  metric contract, resource contract, and previously measured local screens.

Where a number is an arithmetic estimate rather than a measurement, it is
labelled **(estimated)**. Measured figures come only from the repository's own
screen and are labelled **(measured)**.

## 1. Baseline under test

Live estimator: external mixture-of-specialists router, receipt
`local-factor-router-v3`, execution plan `small-factor-router-v5`.

| Lane | Members | Role |
|---|---|---|
| deterministic | `rules.en-pl.p1-text`, BM25, typed extraction | owns every denominator |
| small | MiniLMv2-L6-mnli-xnli, MiniLMv2-L12-mnli-xnli, mDeBERTa-v3-xnli-2mil7 | EN/PL factor estimate |
| deep (optional) | Qwen3-4B-Instruct-2507, 4-bit NF4, disposable child | adjudication on disagreement or ambiguity |
| pinned, disabled | ModernBERT-base-zeroshot-v2.0; deberta-small-long-nli | see below — the two are disabled for **different** reasons |

The two disabled challengers must not be conflated:

- **`MoritzLaurer/ModernBERT-base-zeroshot-v2.0`** — its current mapping is
  **binary** (`entailment` / `not_entailment`), which does not satisfy the
  three-state factor contract. It additionally requires separate resource and
  quality gates.
- **`tasksource/deberta-small-long-nli`** — its mapping is **three-way**
  (`0 entailment, 1 neutral, 2 contradiction`, as pinned in `manifests.py`). It
  is **not** disabled for a label-contract reason. It is disabled pending
  separate **resource and quality gates**, and it is independently English-only
  (section 4.0).

Both live pins were re-verified against HEAD in this run and both still match
`manifests.py`:

| Pinned model | Pinned revision | HEAD on 2026-08-17 | Match |
|---|---|---|---|
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | `b5113eb38ab63efdd7f280f8c144ea8b13f978ce` | `b5113eb38ab63efdd7f280f8c144ea8b13f978ce` | yes |
| `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` | `cdbee75f17c01a7cc42f958dc650907174af0554` | yes |

Resource contract: 8 GB VRAM-class target, 16 GB RAM, **6,144 MiB peak VRAM and
8,192 MiB RSS per child**, one GPU child at a time with no simultaneous weights,
≤ 2,048 tokens per semantic episode, 27 s deep inference deadline inside a 30 s
lane budget, CPU-only disables the deep lane.

**"One GPU child at a time" is a concurrency rule, not a headcount rule.**
Children execute **serially**, each in a disposable process so weights are
released on exit. The constraint is therefore on *total wall clock and peak
per-child footprint*, not on how many experts may contribute. Any reading of it
as "only one model may be involved" is wrong, and section 1.1 shows the live
design already runs several.

### 1.1 Live per-factor pooling design

The router does **not** pick a single estimator per factor. It routes a **small
compatible expert panel** to each factor and pools within that factor:

- **Panel per factor.** The experts selected for a factor are those whose output
  semantics and scope are compatible with that factor's contract.
- **Minimum contributors.** An experimental estimate requires **at least two
  expert contributors** (`PROBABILISTIC_MIN_EXPERT_CONTRIBUTORS = 2`); below
  that the pool is refused rather than published from a single opinion.
- **Current pooling.** A **component-wise median** across contributors —
  deliberately conservative against one extreme challenger, and explicitly
  **uncalibrated**.
- **Planned pooling.** A **calibrated non-negative stacker**, replacing the
  median once calibration data exists.

Two consequences matter for this memo. First, panel membership is the unit of
admission, so a new expert *joins* a factor's panel; it does not automatically
displace an incumbent. Second, the median is a robustness device, not a
correctness device: it resists a single outlier but not a bias shared across the
panel, which is exactly the risk quantified in 2.2.

The **older unquantized** local screen already in the repository
(`docs/model-manifests/wp-11-local-candidates.md`, one 16 GB CUDA device, tiny
authored fixtures — screening evidence, not accuracy). A newer NF4 diagnostic
supersedes its Qwen row for memory and rubric quality; see 1.2:

| Backend | Primary | Critical gate | Inference ms (measured) | Peak CUDA MiB (measured) |
|---|---:|---:|---:|---:|
| BM25 | top-1 0.583 | recall@3 0.750 | 0.534 | — |
| multilingual E5 small | top-1 0.667 | recall@3 1.000 | 285 | 462 |
| multilingual E5 base | top-1 0.833 | recall@3 1.000 | 453 | 1,078 |
| BGE reranker v2 m3 | top-1 0.750 | recall@3 1.000 | 236 | 2,194 |
| mDeBERTa scoped NLI | 3-way acc 0.556 | **different-scope FP 1.000** | 461 | 1,122 |
| Qwen3 4B rubric *(unquantized)* | exact agreement 0.667 | abstention F1 0.521 | **10,791** | **7,769.893** |

Two numbers govern this memo.

**Different-scope false-positive rate 1.000.** The incumbent marked *every*
different-scope negative as a contradiction. This run resolves an ambiguity about
that failure: the incumbent's card tags **27 languages including `pl`**, so
Polish coverage is present and the failure is **not** a language gap. It is
scope-blindness — XNLI training never conditions on branch, environment,
timestamp, speaker, or supersession. That redirects the remedy from "find a more
multilingual model" to "change the training recipe, or keep scope routing
deterministic."

**10,791 ms and 7,769.893 MiB (measured) for the 4B judge.** At a 27 s deadline
the deep lane adjudicates roughly two units per invocation. That peak exceeds the
6,144 MiB child ceiling — because it is an **unquantized** screen-harness figure
on a different code path from the live NF4 child, as the newer diagnostic below
confirms.

### 1.1 Two different Qwen3-4B baselines — do not conflate them

The repository holds **two** Qwen3-4B measurements taken under different
configurations. Earlier drafts of this memo cited only the first and wrongly
concluded that no NF4 baseline existed.

| Source | Configuration | Peak VRAM | Exact rubric labels | Per-case latency |
|---|---|---:|---:|---:|
| `docs/model-manifests/wp-11-local-candidates.md` (older screen) | **unquantized**, screen harness | **7,769.893 MiB** | **0.667** (16 / 24) | **10,791 ms** |
| `docs/real-metrics-campaign-ledger.md`, 2026-08-17 synthetic-only diagnostic re-screen | **bitsandbytes NF4**, disposable child | **~3.84 GiB (≈ 3,932 MiB)** | **15 / 24** (0.625) | **not recorded** |

What this settles and what it does not:

- **Settled: the NF4 child fits the envelope.** ~3.84 GiB is comfortably under
  the 6,144 MiB per-child ceiling, and the ledger states it "fit the resource
  envelope." The older 7,769.893 MiB figure is not evidence of a ceiling
  violation; the two numbers describe different configurations.
- **Settled: quantized quality is measured, not assumed.** 15 / 24 exact rubric
  labels under NF4 against 16 / 24 unquantized, on 24-case fixtures. **One label
  on 24 cases is not a distinguishable difference**, so this supports neither
  "quantization is free" nor "quantization costs quality."
- **Not settled: per-case NF4 latency is unknown.** The diagnostic did not record
  it. The nearby "approximately one minute" cold serial figure in the ledger is a
  whole-pipeline pass, not a per-case NF4 adjudication cost, and must not be
  substituted for one.
- **Not settled: nothing here is calibration.** The ledger is explicit that the
  re-screen "did not promote any neural metric expert," that the results
  "prohibit interpreting model count or agreement as metric correctness," and
  that Qwen3-4B NF4 "remains a selective experimental adjudicator." It stays
  **uncalibrated and product-ineligible**, and 15 / 24 is a synthetic diagnostic
  observation, not an accuracy claim.

## 2. Hypothesis test: would ten heterogeneous model scores improve the product?

**Verdict: rejected on three independent grounds.** Any one is sufficient.
Arbitrary averaging is rejected a fortiori.

### 2.1 Construct incommensurability — averaging is a category error

The contract gives each metric **one observation owner** and states that "a
physical fragment or chunk boundary never creates an additional denominator."
Aggregation is `ratio_of_sums`; averaging session ratios is explicitly forbidden.

A discourse-coherence score, an argument-span probability, a reward scalar, and a
grounding entailment probability are defined over four reference classes with
four units and no shared denominator. Their mean has no unit, no denominator, and
no direction. `metric_contract_v2` validates denominator basis and opportunity
unit kind at construction and rejects forged fields, so the proposal fails at the
publication boundary before accuracy is ever discussed.

### 2.2 Correlated error — ensembling a shared bias does not cancel it

Averaging N estimators reduces variance only when errors are conditionally
independent given the truth. This run makes the shared-bias claim concrete rather
than theoretical: among the candidates resolved in section 4, the grounding
models are trained on Wikipedia/summarization factuality, the reward model on
chat preference, the zero-shot heads substantially on LLM-generated synthetic NLI
pools (`MoritzLaurer/synthetic_zeroshot_mixtral_v0.1`,
`urchade/pile-mistral-v0.1`), and the NLI heads on MNLI/XNLI/ANLI. Several
candidates therefore share not merely a domain but *literal training pools*, and
`microsoft/mdeberta-v3-base` appears as the encoder in the incumbent, in the C1
candidate, and in the C3 candidate.

Their dominant error term is shared domain shift, not independent noise. The
repository already has the demonstration: FP 1.000 is systematic blindness, and
nine further scope-blind models yield a *more confident* wrong consensus. The
confidence is the harm — a tight spread reads on the radar as agreement.

### 2.3 It does not relieve the actual binding constraint

Decisive. The guidance contract permits `focus_factor_keys` only with
`per_factor_measured` sufficient statistics; aggregate rows publish as
`method-only` and may name no focus factor. Ten added models each emit an
**aggregate** score. Ten aggregate signals still yield zero per-factor sufficient
statistics, so the product stays exactly where it is: `method-only`, no focus
factor, no actionable guidance.

The blocked capability is blocked by missing per-factor observation plumbing, not
by missing model capacity.

A fourth, practical cost: calibration labels scale with the number of calibrated
estimators. Ten specialists make the private-holdout burden roughly ten times
larger for a product that has not passed the gate for one.

### 2.4 What is admissible instead

Additional specialists are admissible, and the live design already expects more
than one per factor (section 1.2). What is rejected is *ten heterogeneous
scores pooled across unlike constructs*, not panel membership as such. Each
added expert must:

1. contribute to a *named factor* of a *named metric* — not a metric, not a
   session;
2. emit a **typed factor state** on the contract's own scale (binary, ordinal
   `0 / 0.5 / 1`, or an exact proportion), never a free scalar pooled across
   different constructs;
3. be **scope-compatible** with that factor, so it joins the factor's expert
   panel rather than forming a parallel opinion about a different question;
4. carry an explicit abstention state routing to `unknown`, never to `0`;
5. pass its calibration gate before its value leaves `neural_uncalibrated`;
6. fit the **total** serial latency and resource budget for the lane.

Combination is by routing then within-factor pooling: the router selects the
compatible expert panel for a factor and abstains when the panel cannot reach
its minimum contributor count. Pooling happens **within one construct**, which is
precisely what averaging ten unlike metric scores is not — see 2.1.

Point 6 is a budget constraint, not a slot constraint. Because children execute
serially, every added expert spends wall clock that the lane must still fit. When
the budget is already exhausted, **replacement is the preferred way to admit a
new expert** — but that is an economic consequence, not a logical requirement,
and it does not follow from the one-child-at-a-time rule.

## 3. What no model can solve

Four distinct blockers bound this product. Only one of them is about model
capability, and none is fixed by a better checkpoint.

### 3.1 Lifecycle structure — five metrics

`collaboration.ambiguity_resolution`, `collaboration.clarification_yield`,
`collaboration.exploration_conversion`, `collaboration.scope_change_discipline`,
`logic.open_loop_closure`.

These count *episodes*: an opening, a resolution horizon, a closure. The horizon
is a product decision (when is a loop still open rather than abandoned?), not a
textual fact. The contract already states the correct behaviour: "An open
right-edge episode is `Pending` rather than a negative."

A model asked "was this loop closed?" answers from narrative plausibility and
converts `Pending` into a negative, because no public checkpoint's training
objective distinguishes *not yet closed* from *closed unsuccessfully*. The
requirement is an event state machine over the session graph.

`collaboration.rework_candidate_rate` is **not** in this group — see 3.5.

### 3.2 Objective evidence — five metrics

The five keys whose value depends on an objective receipt are:

- `logic.hypothesis_test_linkage`
- `logic.requirement_action_traceability`
- `outcome.agent_claim_grounding`
- `outcome.first_pass_verification`
- `outcome.verified_requirement_coverage`

The catalog's evidence precedence puts assistant self-report **last**, below CI,
tests, artifacts, and structured tool state. A grounding model scores whether a
claim is supported by nearby text — it measures the transcript's internal
consistency, and a confidently wrong agent emits an internally consistent
transcript. The better the grounding model, the more reliably it certifies a
coherent falsehood.

This is not an abstract worry about the grounding class; it is what the class is
built to do. HHEM and MiniCheck are document-grounded *summary-faithfulness*
checkers: they answer "is this sentence supported by the provided source text,"
which is the wrong question when the question is "did the test actually pass."

For all five keys a text model may at most **propose a candidate link**. It may
never decide the value. **The transcript is the wrong evidence substrate for
these metrics regardless of model quality** — hence
`objective_capability_missing`, and hence WP-10A's rule that zero observed
verification events in a partial snapshot means "none observed," never "not run."

### 3.3 Calibration — all twenty

Every neural contribution publishes as `neural_uncalibrated` / `experimental`
until a private, consented, project-stratified, time-separated holdout produces
reliability curves. A card's ANLI or RewardBench number is evidence about a
different population, not a prior for bilingual engineering dialogue.
Calibration converts a score into a metric and can only come from the target
distribution.

### 3.4 Provider authority

Objective contracts, `task.usage.*`, `task.verification.*`, and every
`ACTION`/`DECISION` linkage. If the adapter cannot expose the typed event, the
metric abstains by design. Authority is a property of the ingestion boundary; the
V2 gate is explicitly built to reject an objective contract resolved from
conversational material.

### 3.5 Projection wiring, not capability — two metrics

Two metrics are withheld today for a reason that is neither model capability,
nor lifecycle structure, nor objective evidence. Both have **conversational
evidence authority under V2 and a deterministic + small-model route**. They are
withheld because the canonical head still publishes frozen V1 results and the V2
projection is not wired to them.

| Metric | V2 contract | Why withheld today |
|---|---|---|
| `collaboration.rework_candidate_rate` | **immediate / conversational**, D + S route | frozen-v1 receipt plus unwired V2 projection — a plumbing gap. It is **not** lifecycle-bound: a rework candidate is judged on the immediate feedback turn, with no resolution horizon to wait out. |
| `outcome.verification_strategy_adequacy` | **conversational**, D + S route | same wiring gap. Despite the `outcome.` prefix it is not an objective key. V2 can evaluate the **stated method, oracle, scope, and edge strategy** conversationally — these are properties of what the verification plan says. What is objective is **actual execution success**, which lives in the receipt, not the text. |

This distinction matters for planning: closing these two needs persisted
semantic-unit reconciliation beside a run, which is product plumbing already
scoped elsewhere. **No model purchase, screen, or calibration campaign advances
them**, and neither should be counted against the model roadmap.

### 3.6 Exact partition of the twenty

| Group | Count | Metrics | What would unblock it |
|---|---:|---|---|
| **Live model lanes** | **8** | the six framing metrics (`prompt.task_definition_coverage`, `prompt.problem_evidence_quality`, `prompt.context_sufficiency`, `prompt.constraint_precision`, `prompt.acceptance_testability`, `prompt.deliverable_contract`) plus `logic.decomposition_coverage` and `logic.decision_rationale_coverage` | **Model work — the entire addressable surface.** |
| **Objective-evidence-bound** | **5** | `logic.hypothesis_test_linkage`, `logic.requirement_action_traceability`, `outcome.agent_claim_grounding`, `outcome.first_pass_verification`, `outcome.verified_requirement_coverage` | objective receipts. A model may propose a link; only a receipt decides. |
| **Lifecycle-structure-bound** | **5** | `collaboration.ambiguity_resolution`, `collaboration.clarification_yield`, `collaboration.exploration_conversion`, `collaboration.scope_change_discipline`, `logic.open_loop_closure` | an episode state machine over the session graph. |
| **Rework wiring** | **1** | `collaboration.rework_candidate_rate` | V2 projection wiring (3.5). |
| **Verification-strategy wiring** | **1** | `outcome.verification_strategy_adequacy` | V2 projection wiring (3.5). |

8 + 5 + 5 + 1 + 1 = 20. Calibration (3.3) and provider authority (3.4) bind
across groups and are not separate members of the partition.

**Eight of twenty run a live model lane. The other twelve are blocked by
objective evidence (5), lifecycle structure (5), or projection wiring (2) — none
of which a better checkpoint supplies. Five are permanently outside text
inference.**

## 4. Resolved candidate matrix

The **metadata precheck** is the subset of the manifest gate that can be
evaluated without downloading: permissive SPDX on checkpoint and base,
safetensors present, no `custom_code` tag or modelling `.py` files, standard
`transformers` loading, required auxiliary filenames on the
`_SAFE_AUXILIARY_ARTIFACTS` allowlist, and for `SCOPED_NLI` an `id2label` of
exactly `{0: entailment, 1: neutral, 2: contradiction}` **read at the immutable
revision**, not at `main`.

Passing it is **not** a Gate 0 pass. Gate 0 additionally requires the artifact
digest and the training-data license chain, both unresolved for every candidate
here (section 0, section 5.1).

### 4.0 The trilemma (headline finding, scoped to the resolved shortlist)

Within the shortlist resolved in this run, no model is simultaneously (a)
multilingual including Polish, (b) three-way NLI, and (c) long-context. Each
gives up one:

| Model | Multilingual + PL | Three-way NLI | Context | SPDX tag |
|---|:---:|:---:|---:|---|
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` (incumbent) | yes (`pl` tagged) | yes | 512 | MIT |
| `sileod/mdeberta-v3-base-tasksource-nli` | yes (`pl` tagged) | yes | 512 | Apache-2.0 |
| `MoritzLaurer/bge-m3-zeroshot-v2.0-c` | yes | **no — binary** | **8194** | MIT |
| `tasksource/deberta-small-long-nli` | **no — `en` only** | yes | 1680 | Apache-2.0 |

The product caps episodes at 2,048 tokens, so a 512-token model forces chunking
for the longest episodes. The only long-context multilingual option *in this
shortlist* is binary-labelled and so fails the three-state factor contract — the
same reason ModernBERT-base-zeroshot-v2.0 is pinned-but-disabled. This is a
property of the resolved shortlist, not a proof about all open weights; a wider
search could surface a counterexample. As it stands, **the chunking strategy —
not the model — is the lever for long episodes.**

### 4.1 Adopt

| # | Capability | Why adoptable now |
|---|---|---|
| A1 | Requirement change-point over **existing** embeddings (PELT / ADWIN / BOCPD over the already-computed multilingual E5 requirement trajectory) | **Zero new weights, zero new VRAM, zero new license surface, zero new provenance risk, and no download.** Serves two gaps the catalog names as open: `Requirement change rate` ("legitimate discovery must be distinguished from drift") and `Requirement drift` ("needs change-point and authority handling"). Methods already in the research journal (Killick 2012; Bifet and Gavaldà 2007; Adams and MacKay 2007). |

The only adopt row, and deliberately not a model. Contract in section 6.

### 4.2 Candidates — metadata precheck outcomes

Parameter counts and dtypes are as reported by the API/safetensors metadata.
On-disk sizes are arithmetic from parameter count × dtype width **(estimated)**.

| # | Model ID | Revision (HEAD 2026-08-17) | SPDX tag / base chain | Parameters, dtype, format | Context | Languages | Output semantics | Metadata precheck | Status |
|---|---|---|---|---|---:|---|---|:---:|---|
| **C1** | `sileod/mdeberta-v3-base-tasksource-nli` | `4b26406dc7eddd2eda8cac950fefa704bbb9e494` | Apache-2.0 tag; base `microsoft/mdeberta-v3-base` | 278.8M params, `torch_dtype: float32` at the pin ⇒ ~1.12 GB (estimated); `model.safetensors` **and** `pytorch_model.bin`; no `.py` | 512 (`max_position_embeddings`, read at the pin) | 27 tags incl. **`pl`** | `DebertaV2ForSequenceClassification`; `id2label` = **`{0: entailment, 1: neutral, 2: contradiction}`**, read at the pinned revision | **passed** | **Research only. Supply chain UNRESOLVED.** The label map matches `_SAFE_LABELS` and index order at the immutable revision, it is multilingual with Polish, and both checkpoint and base carry permissive tags — so it is the one shortlist member worth *considering* for a screen. It is **not** Gate-0 cleared and **not** drop-in ready: no weight digest is established, and the `mtasksource` training mix has not been license-traced. No download is authorized by this memo. |
| **C2** | grounding class | — | — | — | — | — | — | **none passed** | **None in the resolved shortlist passed** — see 4.3. |
| **C3** | `knowledgator/gliclass-x-base` | `4599a431a1b25b4eb076b46ae97c9ba61f82f416` | Apache-2.0 tag; base `microsoft/mdeberta-v3-base`; card states training data permits commercial use | **279,892,992 params, F32 ⇒ ~1.12 GB safetensors** (estimated); no `.py` | not documented | EN, ES, IT, FR, DE — **Polish not listed** | multi-label scores + threshold; loaded via `GLiClassModel` from the third-party `gliclass` package | **failed** | Two blockers: (a) Polish absent from documented coverage despite an mDeBERTa-v3 backbone pretrained on it — the "multilingual base, subset fine-tune" trap; (b) not `AutoModel`-loadable, so no manifest `architecture` path exists. Revisit only if a PL-covering, `transformers`-native variant ships. |
| **C4** | `urchade/gliner_multi-v2.1` | `443d26d654e0324125a96bebd8e796c14ff2efe6` | Apache-2.0 tag; trained on `urchade/pile-mistral-v0.1` (LLM-generated synthetic) | **288,949,504 params, F32 ⇒ ~1.16 GB safetensors** (estimated); plus `pytorch_model.bin`; no `.py` | not documented | multilingual | span/entity predictions from a user-supplied type list | **failed** | Ships `gliner_config.json`, not `config.json` — that filename is **not** on the `_SAFE_AUXILIARY_ARTIFACTS` allowlist — and loading requires the `gliner` package. Independently, replacing a deterministic extractor with a neural one converts a *measured* denominator into an *inferred* one, downgrading every metric it feeds. Admissible only as an offline recall-gap diagnostic proposing spans for the deterministic extractor to confirm. |

All three encoder-class candidates are F32 at roughly 1.1–1.2 GB of weights, not
the ~280 MB their raw parameter figures might suggest at a glance. Section 7.3
uses the corrected sizes.

On C1's dual weight files: the repository ships both `model.safetensors` and
`pytorch_model.bin`. The manifest accepts only reviewed safetensors and the
snapshot allowlist must exclude the pickle sibling; its presence is not itself
disqualifying.

### 4.3 Grounding — none in the resolved shortlist passed

Four grounding candidates were resolved. None passed the metadata precheck, each
for a different reason. This is a statement about the resolved shortlist, not a
proof that no eligible grounding checkpoint exists anywhere.

| Model ID | Revision | License | Blocking fact | Outcome |
|---|---|---|---|---|
| `vectara/hallucination_evaluation_model` (HHEM-2.1-Open) | `8e4a2e6e96c708cc76c2344f7e4757df2515292c` | Apache-2.0 tag | ships `configuration_hhem_v2.py` + `modeling_hhem_v2.py`, tagged `custom_code` → **requires `trust_remote_code=True`**; `en` only; base `google/flan-t5-base` | **precheck failed (X6).** `ModelManifest.__post_init__` raises unconditionally. |
| `lytang/MiniCheck-Flan-T5-Large` | `96eafd01cee2d16cf81aaa2fb226b14f422a37b3` | MIT tag | **no safetensors — `pytorch_model.bin` only**; `en` only; ships four `.py` files | **precheck failed.** Same artifact ground that blocked the historical BGE-M3 pin. |
| `bespokelabs/Bespoke-MiniCheck-7B` | `1ed7786bcda3fa1dc35f7c4ed9e3f36b785d33b8` | **CC BY-NC 4.0** (`License.md`; no SPDX in metadata) | non-commercial; `custom_code` with four `internlm2` `.py` files; `en` only | **precheck failed (X7 + X6).** |
| `PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct` | `5523f869eb5eecb4bca417b6e6d3532e746a9664` | **cc-by-nc-4.0** | non-commercial; `en` only; 8B on a Llama-3 base | **precheck failed (X7).** |

Even had one passed, section 3.2 bars any of them from *deciding* an
objective-evidence key. `logic.hypothesis_test_linkage` is itself one of the five
objective keys, so a grounding model's ceiling there is proposing a candidate
link for an objective receipt to confirm — never producing the value.

### 4.4 Reject — contract grounds, provenance-independent

| # | Class | Resolved exemplar | Ground for rejection |
|---|---|---|---|
| X1 | Reward models | `Skywork/Skywork-Reward-V2-Qwen3-0.6B`, rev `8c14a4e9e6321deaf572544339b16b8d6bbe8886`, Apache-2.0 tag, base `Qwen/Qwen3-0.6B`, 596,050,944 params BF16 ⇒ ~1.19 GB (estimated), safetensors, no `.py` — **passes the metadata precheck** | **Rejected anyway, and this is the point.** Metadata is spotless and it still has no home: no opportunity unit in the twenty-metric contract can own a preference scalar. It ranks chat responses by human-preferred helpfulness and style, carries documented verbosity/formatting bias, and has no denominator, no contract direction, and no per-factor decomposition. It is precisely the single-quality-scalar-over-a-person's-session that AGENTS.md forbids. A clean license does not create a denominator. |
| X2 | Generic LLM judges as an **added** lane | `prometheus-eval/prometheus-7b-v2.0`, rev `66ffb1fc20beebfb60a3964a957d9011723116c5`, Apache-2.0 tag, Mistral 7.2B BF16 ⇒ ~14.4 GB (estimated); `flowaicom/Flow-Judge-v0.1`, rev `b7a47acd7c86e981145168e4dea1bef7d84a0894`, Apache-2.0 tag, base `microsoft/Phi-3.5-mini-instruct`, **3.8B params ⇒ ~7.64 GB raw BF16** (estimated), **tagged `custom_code`** | Aggregate rubric scores, so per 2.3 they cannot unlock the focus-factor capability, and both compete for the same single GPU child. **Flow-Judge additionally fails the metadata precheck outright on `custom_code` (X6)**, independent of any language or size consideration. Prometheus is English-focused and at ~14.4 GB raw exceeds the 6,144 MiB child before quantization. |
| X3 | Argument mining | — | Construct mismatch. `logic.decision_rationale_coverage` v3 already counts explicit rationale/alternative/constraint/evidence markers deterministically. Replacing an observed marker with an inferred argumentative role is a strict evidence-tier downgrade for no new denominator. |
| X4 | Diachronic semantic change | `pierluigic/xl-lexeme`, rev `c9f85c6f05b85bc7c5014b5c23846f4467476263` — **no license declared**, **no safetensors** (`pytorch_model.bin` only) | Fails the precheck twice over, and independently fails on construct: these models detect word-sense drift across decades, while the product's unit is a ≤100-message window. The real need is intra-session requirement change-point — which is A1 and needs no checkpoint. |
| X5 | Emotion / affect / toxicity feeding the twenty | — | Catalog section G fixes affect as C-tier, private, non-evaluative, excluded from export and ranking. Any path into the twenty is a policy violation independent of accuracy. |
| X6 | Any `trust_remote_code=True` / `custom_code` checkpoint | HHEM-2.1-Open, Bespoke-MiniCheck-7B, Flow-Judge-v0.1 | `ModelManifest.__post_init__` raises unconditionally. A supply-chain boundary, not a preference. |
| X7 | Non-commercial or unlicensed | Bespoke-MiniCheck-7B (CC BY-NC 4.0), Lynx-8B (cc-by-nc-4.0), xl-lexeme (none) | Manifest accepts MIT/Apache-2.0 only. **Check the base too**, and check the *data*: `MoritzLaurer/bge-m3-zeroshot-v2.0` carries an MIT tag but its card states the mix "includes data with non-commercial licenses" — only the `-c` variant is described as trained on commercially-friendly data. A Hub license tag is not provenance clearance. |
| X8 | Third-party quantized repacks | — | Quantization is desirable; third-party repacks break provenance. The digest, tokenizer, and calibration data are not the upstream author's. Quantize locally from a verified upstream snapshot, as the NF4 Qwen child already does. |
| X9 | Code-review quality | `microsoft/codereviewer`, rev `094aaac6bdf47cc1eb5b3ab393dae76e7ba3b423`, Apache-2.0 tag, **no safetensors** (`pytorch_model.bin` only) | Fails the precheck on artifact format, and independently: no diff, patch, or artifact is an observation unit for any of the twenty metrics. Revisit only if catalog section F is scheduled. |

### 4.5 Research — deliberately unresolved

Not serious candidates; each is rejected or deferred on construct or data-license
grounds before provenance matters, so pinning revisions would be busywork.

| # | Class | Why unresolved |
|---|---|---|
| R1 | Discourse / RST parsing | Training corpora (PDTB, RST-DT) are LDC-licensed and cannot be vendored or redistributed. Clearing the *data* is the blocker, not finding a checkpoint. |
| R2 | Dialogue-act tagging | Taxonomy mismatch, not accuracy: act inventories encode statement/question/backchannel, not requirement, decision, verification, or supersession. Map an inventory onto the product's typed units and measure coverage loss **before** touching weights. |
| R3 | Topic segmentation | Serves `Topic-switch rate` and `Local semantic continuity`, neither in the twenty. A signal from already-pinned embeddings will likely dominate a dedicated checkpoint on cost, as in A1. |
| R4 | Uncertainty / abstention | **A method, not a model.** Selective risk, conformal prediction, and risk–coverage curves are the answer. Sampling-based semantic-uncertainty estimators need many generations per unit and are unaffordable under a 27 s deadline. Research item: risk–coverage reporting for the *existing* small lane. |

## 5. Benchmark and calibration gates

Ordered so the cheapest disqualifier runs first. Thresholds are proposals fixed
*before* screening, not chosen after.

### 5.1 Gate 0 — supply chain

Gate 0 has three parts. Only the first can be evaluated without downloading, and
**only the first was evaluated in this run**.

**Gate 0a — metadata precheck (evaluated).**

| Check | Requirement |
|---|---|
| SPDX tag | MIT or Apache-2.0 on checkpoint **and** base |
| Weights | safetensors present; pickle-only blocked and recorded |
| Remote code | no `custom_code` tag, no modelling `.py` files |
| Loading | standard `transformers` `AutoModel*`; a third-party package (`gliner`, `gliclass`) fails until an architecture path exists |
| Artifacts | every required auxiliary filename on `_SAFE_AUXILIARY_ARTIFACTS` |
| Label map | `id2label` read from `config.json` **at the immutable revision** (`/raw/{revision}/config.json`), never at `main` and never assumed |
| Pin | immutable 40-hex revision; model and tokenizer same repo and commit |

C1's label map, architecture, context, and dtype were read at revision
`4b26406dc7eddd2eda8cac950fefa704bbb9e494` in this run, satisfying the label-map
row. `bge-m3-zeroshot-v2.0-c`'s binary map was read at `main` only; since that
candidate is rejected on the label contract either way, the distinction does not
change its outcome, but the reading is recorded as unpinned in section 11.

**Gate 0b — artifact verification (UNRESOLVED for every candidate).** SHA-256
per weight file, computed from the downloaded artifact and reviewed before the
manifest is authored. Requires a separately authorized download.

**Gate 0c — training-data license chain (UNRESOLVED for every candidate).** The
dataset mix behind the checkpoint must be traced and cleared. A permissive
checkpoint tag over a non-permissive data mix does not clear; the
`bge-m3-zeroshot-v2.0` versus `-c` split in X7 is the worked example. For C1
this means license-tracing `mtasksource`.

C1 is the only section-4.2 row that passes 0a. **No candidate has passed 0b or
0c.**

### 5.2 Gate 1 — scope discrimination (the incumbent-killer)

**Different-scope false-positive rate ≤ 0.10.** Incumbent: 1.000 (measured).

This runs *before* any accuracy measurement — three-way accuracy on scope-matched
pairs is meaningless if the model fires on everything. Since Polish coverage is
confirmed present in the incumbent, a C1 challenger that also failed this gate
would be evidence that the defect is inherent to the NLI formulation as trained
on these corpora — itself a publishable negative result.

### 5.3 Gate 2 — bilingual parity

- Macro-F1 reported **separately** for EN and PL; pooled numbers rejected.
- `|EN − PL|` macro-F1 ≤ 0.10, else the model is registered English-only and the
  router abstains on Polish units rather than degrading silently.

This gate already eliminated C3 on documentation alone.

### 5.4 Gate 3 — calibration and abstention

- ECE ≤ 0.10 on the private holdout, **reliability curve published**, not just
  the scalar; Brier alongside, since ECE binning hides local failure.
- **Selective risk at 50% coverage strictly below the deterministic baseline's
  risk at the same coverage.** A model that cannot beat the rules where it is
  most confident has no admissible operating point.
- Full risk–coverage curve, per catalog section I.

### 5.5 Gate 4 — agreement with human labels

Quadratic-weighted κ ≥ 0.6 against private expert labels, per language slice;
order, verbosity, formatting, and model-name counterfactuals for judge-shaped
candidates; bootstrap CI reported, point estimate alone rejected.

### 5.6 Gate 5 — screen size

**≥ 96 effective scenarios**, matching the promotion-screen target already fixed
for the scope router. The current WP-11 screen has 12–24 cases per slice and
explicitly fails this. Split by user, project, and time to prevent leakage.

### 5.7 Gate 6 — resource and latency

Section 7. A candidate passing quality but failing the envelope is recorded as
*blocked on resources*, not rejected on merit.

### 5.8 Gate 7 — contract fit

Output must map onto the target factor's declared scale without a threshold
invented at integration time, and must have a declared abstention path to
`unknown`. This gate is what disables `ModernBERT-base-zeroshot-v2.0`, whose
mapping is binary, and it would equally disable `bge-m3-zeroshot-v2.0-c`, whose
`id2label` is `{0: entailment, 1: not_entailment}`. It is **not** the reason
`deberta-small-long-nli` is disabled — that model is three-way and is held back
by resource and quality gates (section 1).

## 6. Contract for the one adopted signal (A1)

Working key: `logic.requirement_stability` — *candidate, not scheduled*.

| Property | Value |
|---|---|
| Observation unit | one requirement-revision trajectory within the bounded window |
| Numerator | change-points classified as **superseded by an explicit authoritative revision** |
| Denominator | detected change-points in the requirement trajectory |
| Direction | **contextual, not "lower is better"** — discovery and drift differ, and the metric must not imply that changing requirements is a defect |
| Evidence tier | B only after Gate 3; C until then |
| Abstention | fewer than two requirement observations, or no authority signal, yields `not_applicable`, never `0` |
| Model dependency | **none new** — reuses the already-pinned multilingual E5 pass |
| Publication | `deterministic_local` for segmentation; authority classification is objective-evidence-owned and stays `unknown` without it |

Stated limitation: a change-point algorithm finds a *statistical* change, never a
causal or authoritative one. Separating discovery from drift needs the authority
signal, a provider/lifecycle capability per 3.1 and 3.4. This metric would ship
with its numerator frequently `unknown` — the correct behaviour, and why it is a
candidate rather than a deliverable.

## 7. Resource and latency budget

### 7.1 Envelope

| Constraint | Value |
|---|---|
| Target device | 8 GB VRAM class, 16 GB RAM |
| Per-child peak VRAM | 6,144 MiB |
| Per-child RSS | 8,192 MiB |
| Concurrency | one GPU child, no simultaneous weights |
| Episode | ≤ 2,048 tokens |
| Deep lane | 27 s inference deadline inside 30 s |
| CPU-only | deep lane disabled |

The single-child rule makes every deep candidate a **substitution**, never an
addition.

### 7.2 Does any 1B–7B quantized specialist justify its latency?

**No — not as an addition. Only as a substitution, and the substitution baseline
is now partly measured: NF4 memory and quality exist, per-case NF4 latency does
not.**

Using the repository's measured numbers:

- Qwen3-4B at **10,791 ms/case (measured, unquantized screen path)** ⇒ **~2
  adjudicated units per invocation** at a 27 s deadline. The corresponding NF4
  per-case cost is unrecorded (section 1.1), so this remains the only latency
  anchor and it is the wrong configuration.
- Small encoders at 285–461 ms (measured) ⇒ **20–40× cheaper per unit**.
- A window admits up to 100 messages, plausibly tens of candidate units. A
  1B-class specialist at an optimistic 1–3 s/unit would need 20–180 s — up to
  sixfold over the entire lane budget.

So a 1B–7B specialist is viable **only as a sparse adjudicator on a bounded,
router-selected set of contested units**, which is what the deep lane already is.
A second one doubles the lane to 60 s and breaks the interaction contract.

Fit against the 6,144 MiB child. **Estimated quantized figures below are
weights-only arithmetic at roughly 0.5–0.6 bytes/parameter, excluding KV cache,
activations, and runtime overhead. They are not measured peaks.** Measured
figures are labelled with their source configuration.

| Candidate | Raw BF16 (estimated) | NF4 weights only (estimated) | Measured peak | Fits child? |
|---|---:|---:|---:|:---:|
| `Qwen/Qwen3-4B-Instruct-2507` (incumbent) | ~8.0 GB | ~2.0–2.4 GB | **~3.84 GiB NF4 (measured, 2026-08-17 diagnostic)**; 7,769.893 MiB unquantized screen | **yes — measured under NF4** |
| `flowaicom/Flow-Judge-v0.1` (3.8B) | **~7.64 GB** | ~1.9–2.3 GB | none | **moot — precheck failed on `custom_code`** |
| `prometheus-eval/prometheus-7b-v2.0` (7.2B) | ~14.4 GB | ~3.6–4.3 GB | none | estimated marginal; little KV headroom |

The incumbent's measured NF4 peak (~3.84 GiB) is the one non-estimated
quantized number available, and it leaves roughly 2.2 GiB of headroom under the
ceiling. Note the gap between its estimated weights-only figure (~2.0–2.4 GB) and
its measured peak (~3.84 GiB): **measured peaks run well above weights-only
arithmetic**, which is the reason the estimates in rows two and three cannot be
read as fit verdicts.

Neither substitution candidate is worth a trial: **Flow-Judge fails the metadata
precheck on `custom_code`**, and Prometheus is English-focused against a
multilingual incumbent and estimated-marginal on memory. Language coverage and
supply chain settle this before latency does.

Were an eligible multilingual candidate to appear, it must beat all of:

| Incumbent baseline | Configuration | Value to beat |
|---|---|---|
| exact rubric labels | NF4 (measured, 2026-08-17) | > 15 / 24 |
| exact agreement | unquantized screen | > 0.667 (16 / 24) |
| abstention macro-F1 | unquantized screen | > 0.521 |
| JSON schema compliance | unquantized screen | = 1.000 (integration gate, not a quality claim) |
| peak VRAM | **NF4 (measured)** | **< ~3.84 GiB**, and hard-capped at 6,144 MiB |
| inference | **unrecorded under NF4** | no NF4 anchor; 10,791 ms/case is the unquantized figure |

Every row above is a **synthetic-fixture diagnostic observation, not a
calibration result**. Beating them is necessary, never sufficient: a challenger
that wins every row still faces Gates 1–5 and remains product-ineligible until a
private holdout passes.

**Remaining measurement gap — narrower than previously stated.** NF4 peak memory
and NF4 rubric quality are now recorded. What is still missing is **per-case NF4
latency**, without which the deadline arithmetic above rests on an unquantized
anchor and no substitution can be scored on time. Recording it is a small
addition to an already-existing diagnostic and remains the prerequisite work
item.

### 7.3 Small-lane budget

A new small-lane member must fit alongside the three existing encoders in
sequential execution without pushing small-stage wall clock past the point where
the deep lane becomes unaffordable. Guidance: ≤ 500 ms/unit and ≤ 1,500 MiB peak,
matching the observed envelope.

The corrected sizes matter here. All three encoder-class candidates are **F32 at
~1.1–1.2 GB of weights** — C1 at 278.8M params (~1.12 GB), C3 at 279,892,992
params (~1.12 GB), C4 at 288,949,504 params (~1.16 GB). Weights alone therefore
consume roughly three-quarters of the 1,500 MiB peak guidance before activations,
workspace, or batch effects. Loading any of them in F32 leaves little headroom;
half-precision loading should be evaluated as part of Gate 6 rather than assumed.

C1 is the same architecture family and parameter scale
(`DebertaV2ForSequenceClassification`) as the incumbent it would replace, so
**the hypothesis** is that its cost lands near the incumbent's measured 461 ms /
1,122 MiB, making it a replacement at parity rather than an addition. **This is
unmeasured.** Parameter count and architecture family predict cost only loosely —
dtype, tokenizer behaviour, sequence padding, and batch shape all move it. C1's
actual latency and peak memory must be measured on the local screen before any
parity claim is made, and the parity hypothesis is not a reason to skip Gate 6.

## 8. Datasets — stress tests and negative controls only

**None may serve as a calibration set.** Calibration requires the private target
distribution (3.3). These are for (a) confirming a candidate is not broken before
it touches private data, and (b) negative controls showing that a model scoring
well here still fails Gate 1.

| Corpus | Legitimate use | Why it cannot calibrate |
|---|---|---|
| MNLI / XNLI / ANLI | smoke test that the head loads and `id2label` is correct | genre mismatch is the documented source of FP 1.000; also **contamination** — the incumbent and C1 were both trained on NLI pools including these, so scores are not generalization evidence |
| `MoritzLaurer/synthetic_zeroshot_mixtral_v0.1`, `urchade/pile-mistral-v0.1`, `mtasksource` | provenance reading only | LLM-generated or aggregated pools underlying C1, C3, and C4; evaluating on them measures memorization, and their license chains are the unresolved Gate 0c question |
| FEVER-style fact verification | grounding smoke test | Wikipedia claims vs. retrieved passages; an engineering state change is not an encyclopedic fact |
| Summarization-factuality benchmarks (AggreFact/TofuEval class) | **negative control** for the grounding class | measures summary faithfulness to a source document — per 3.2 the wrong question entirely |
| Preference / reward benchmarks | none, given X1 | measures chat helpfulness preference; no denominator in this contract |
| Code-review comment corpora | none, given X9 | measures comment generation, not session logic |
| PDTB / RST-DT | reference reading only | **LDC-licensed; not redistributable or vendorable** — the binding constraint on R1 |
| Reddit-derived emotion corpora | none, given X5 | policy-excluded regardless of accuracy |
| Diachronic semantic-change tasks | none, given X4 | decade-scale drift; wrong unit and time scale |

The fictional EN/PL fixture remains the only in-repository evaluation surface and
remains too small (5.6). Growing it to ≥ 96 effective scenarios with EN/PL
parity, scope negatives, supersession, and partial-window cases is a
higher-value investment than any candidate here, because **no candidate can be
scored without it.**

## 9. Recommendation per metric

Lane key: `D` deterministic, `S` small encoder, `Deep` optional adjudicator,
`Obj` objective receipt required.

| # | Metric | Group | Route | Verdict |
|---:|---|---|---|---|
| 1 | `prompt.task_definition_coverage` | live lane | D + S | **Addressable.** C1 screen target; D keeps the denominator. |
| 2 | `prompt.problem_evidence_quality` | live lane | D + S, Deep on ambiguity | **Addressable.** Its four named cues (observed/expected/reproduction/environment) are the best candidate in the pack for genuine `per_factor_measured` statistics — the capability 2.3 identifies as the real blocker. |
| 3 | `prompt.context_sufficiency` | live lane | D + S | Addressable; "sufficient for what?" needs the task stratum first. |
| 4 | `prompt.constraint_precision` | live lane | D + S | Addressable, low ceiling — boundary/value/version cues are near-deterministic. |
| 5 | `prompt.acceptance_testability` | live lane | D + S, Deep on ambiguity | **Addressable.** Deep lane most justified here. |
| 6 | `prompt.deliverable_contract` | live lane | D + S | Addressable, low ceiling. |
| 7 | `collaboration.ambiguity_resolution` | lifecycle | D + S | Episode state machine first. No model until then. |
| 8 | `collaboration.clarification_yield` | lifecycle | D + S | As above. |
| 9 | `collaboration.exploration_conversion` | lifecycle | D + S (+ objective receipt when available) | As above; the catalog's `0 / 4` is a *linkage-rule* result, not a reasoning measurement, and no model repairs the rule. |
| 10 | `collaboration.scope_change_discipline` | lifecycle | D + S | As above. |
| 11 | `collaboration.rework_candidate_rate` | **rework wiring** | D + S | **Not lifecycle-bound.** V2 immediate/conversational authority, judged on the immediate feedback turn with no resolution horizon. Withheld today by frozen-v1 receipts and unwired V2 projection (3.5) — a plumbing fix, not a model or state-machine fix. Risk-direction metric, so Gate 3 abstention is binding once it is wired. |
| 12 | `logic.decomposition_coverage` | **live lane** | D + retrieval + S | **Addressable.** Would be the R1 target if that class ever clears its data licensing. |
| 13 | `logic.hypothesis_test_linkage` | **objective evidence** | D + S + **Obj** | **Not model-decidable.** A model may propose the hypothesis→check link; the objective receipt decides. No shortlist grounding model is eligible even for the proposal role (4.3). |
| 14 | `logic.decision_rationale_coverage` | **live lane** | D + S, Deep on ambiguity | **Addressable.** Per X3, do not replace observed rationale markers with inferred argumentative roles. |
| 15 | `logic.requirement_action_traceability` | **objective evidence** | D + retrieval + **Obj** | **Not model-decidable.** Retrieval may propose candidate links and is already served by the pinned E5/reranker; the receipt decides. No new model. |
| 16 | `logic.open_loop_closure` | lifecycle | D + S | Episode state machine first. |
| 17 | `outcome.agent_claim_grounding` | **objective evidence** | **Obj** decides | **Not model-decidable.** A grounding model may *link*; it may never *decide*. |
| 18 | `outcome.verification_strategy_adequacy` | **verification-strategy wiring** | D + S, Deep on ambiguity | V2 **conversational** authority despite the `outcome.` prefix — not an objective key. V2 can conversationally evaluate the **stated method, oracle, scope, and edge strategy**; **actual execution success is objective** and stays with the receipt. Withheld today by the same V2 projection wiring gap (3.5), so this is a genuine model-addressable surface once wired. |
| 19 | `outcome.first_pass_verification` | **objective evidence** | **Obj** only | **Not model-decidable.** |
| 20 | `outcome.verified_requirement_coverage` | **objective evidence** | **Obj** only | **Not model-decidable.** |
| + | `logic.requirement_stability` (A1) | proposed | D over existing embeddings | **Adopt as candidate.** Zero new weights. Section 6. |

Counts: 8 live lanes (1–6, 12, 14), 5 objective keys (13, 15, 17, 19, 20),
5 lifecycle (7–10, 16), 1 rework wiring (11), 1 verification-strategy wiring
(18) = 20.

## 10. Decisive conclusions

1. **One shortlist member is worth considering for a screen, and it is not
   cleared.** `sileod/mdeberta-v3-base-tasksource-nli` at
   `4b26406dc7eddd2eda8cac950fefa704bbb9e494` (Apache-2.0 tag, base
   `microsoft/mdeberta-v3-base`, 278.8M params F32, safetensors present, no
   `custom_code`, `pl` among 27 language tags, and `id2label` verified **at that
   revision** as `{0: entailment, 1: neutral, 2: contradiction}`) passes the
   **metadata precheck only**. Its artifact digest is unestablished and its
   `mtasksource` data license chain is untraced, so its supply chain is
   **unresolved**. It is research-only: no download, no manifest entry, no
   activation.
2. **No grounding candidate in the resolved shortlist passed.** HHEM-2.1-Open
   requires `trust_remote_code`; MiniCheck-Flan-T5-Large ships no safetensors;
   Bespoke-MiniCheck-7B is CC BY-NC 4.0 with custom code; Lynx-8B is
   cc-by-nc-4.0. All four are English-only. A wider search could surface an
   eligible checkpoint; this run did not.
3. **A trilemma within the resolved shortlist.** No shortlist model is at once
   multilingual-with-Polish, three-way NLI, and long-context. The one
   long-context multilingual option (`bge-m3-zeroshot-v2.0-c`, 8194 tokens) is
   binary-labelled and fails the three-state factor contract. For long episodes
   the lever is the chunking strategy, not the model.
4. **The incumbent's defect is scope-blindness, not language.** Its card tags 27
   languages including `pl`, so FP 1.000 cannot be blamed on Polish coverage.
   That redirects the remedy toward training recipe or toward keeping scope
   routing deterministic.
5. **The ten-score hypothesis is rejected**, now with concrete support for the
   correlated-error ground: resolved candidates share literal training pools and
   `microsoft/mdeberta-v3-base` appears as the encoder in three of them.
   Decisively, ten aggregate scores still yield zero per-factor sufficient
   statistics and unlock nothing the contract can publish.
6. **A clean license does not create a denominator.**
   `Skywork-Reward-V2-Qwen3-0.6B` passes the metadata precheck spotlessly and is
   still rejected, because no opportunity unit in the contract can own a
   preference scalar. The binding constraint is the metric contract, not model
   availability.
7. **No deep-lane substitution is worth running, and the reason is now the
   candidates rather than the baseline.** Flow-Judge-v0.1 fails the metadata
   precheck on `custom_code`; Prometheus-7b-v2.0 is English-focused against a
   multilingual incumbent and estimated-marginal at ~14.4 GB raw. The incumbent
   baseline is no longer absent: the 2026-08-17 diagnostic measured the NF4
   child at **~3.84 GiB peak, fitting the 6,144 MiB envelope, at 15 / 24 exact
   rubric labels**. That result stays **uncalibrated, product-ineligible, and a
   selective experimental adjudicator only**. The one remaining hole is
   **per-case NF4 latency**, which was not recorded; until it is, deadline
   arithmetic rests on the unquantized 10,791 ms anchor.
8. **Eight of twenty metrics run a live model lane.** The other twelve are
   blocked by objective evidence (5), lifecycle structure (5), or V2 projection
   wiring (2) — none of which a better checkpoint supplies. Five are permanently
   outside text inference. **Two of the twelve are pure plumbing**
   (`collaboration.rework_candidate_rate`,
   `outcome.verification_strategy_adequacy`): both are conversational D+S under
   V2 and neither should be counted against the model roadmap.
9. **The fixture is the bottleneck before any candidate is.** At 12–24 cases per
   slice the screen cannot support a promotion decision; the repository's own
   ≥ 96-scenario target already says so.

## 11. Sources used

Official Hugging Face API endpoints (`/api/models/{id}`), model cards, and raw
config/license files, all read 2026-08-17. Config reads are marked **[pinned]**
when read at an immutable revision and **[main]** when not.

- https://huggingface.co/api/models/sileod/mdeberta-v3-base-tasksource-nli
- https://huggingface.co/sileod/mdeberta-v3-base-tasksource-nli
- https://huggingface.co/sileod/mdeberta-v3-base-tasksource-nli/raw/4b26406dc7eddd2eda8cac950fefa704bbb9e494/config.json — **[pinned]**
- https://huggingface.co/api/models/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7
- https://huggingface.co/api/models/tasksource/deberta-small-long-nli
- https://huggingface.co/tasksource/deberta-small-long-nli
- https://huggingface.co/api/models/MoritzLaurer/bge-m3-zeroshot-v2.0
- https://huggingface.co/MoritzLaurer/bge-m3-zeroshot-v2.0
- https://huggingface.co/api/models/MoritzLaurer/bge-m3-zeroshot-v2.0-c
- https://huggingface.co/MoritzLaurer/bge-m3-zeroshot-v2.0-c/raw/main/config.json — **[main]**
- https://huggingface.co/api/models/vectara/hallucination_evaluation_model
- https://huggingface.co/api/models/lytang/MiniCheck-Flan-T5-Large
- https://huggingface.co/api/models/bespokelabs/Bespoke-MiniCheck-7B
- https://huggingface.co/bespokelabs/Bespoke-MiniCheck-7B/raw/main/License.md — **[main]**
- https://huggingface.co/api/models/PatronusAI/Llama-3-Patronus-Lynx-8B-Instruct
- https://huggingface.co/api/models/knowledgator/gliclass-base-v1.0
- https://huggingface.co/api/models/knowledgator/gliclass-x-base
- https://huggingface.co/knowledgator/gliclass-x-base
- https://huggingface.co/api/models/urchade/gliner_multi-v2.1
- https://huggingface.co/urchade/gliner_multi-v2.1
- https://huggingface.co/api/models/Skywork/Skywork-Reward-V2-Qwen3-0.6B
- https://huggingface.co/api/models/prometheus-eval/prometheus-7b-v2.0
- https://huggingface.co/api/models/flowaicom/Flow-Judge-v0.1
- https://huggingface.co/api/models/microsoft/codereviewer
- https://huggingface.co/api/models/pierluigic/xl-lexeme
- https://huggingface.co/api/models/Qwen/Qwen3-4B-Instruct-2507

In-repository measurement sources (no external network, no private data):

- `docs/model-manifests/wp-11-local-candidates.md` — the older unquantized
  screen: 7,769.893 MiB peak, 10,791 ms/case, exact agreement 0.667, abstention
  F1 0.521, JSON compliance 1.000.
- `docs/real-metrics-campaign-ledger.md` — the 2026-08-17 synthetic-only local
  diagnostic re-screen: Qwen3-4B NF4 at about 3.84 GiB peak VRAM and 15 / 24
  exact rubric labels, promoted nothing, and retains selective-experimental
  status.
- `docs/live-metric-radar-pipeline.md` — router, lane, and resource contract.
- `docs/metrics-catalog.md` — the twenty-metric pack and V2 publication contract.

Papers referenced by the above cards are recorded by arXiv identifier as listed
in card metadata (2311.08526 GLiNER; 2312.17543 zeroshot-v2.0; 2404.10774
MiniCheck; 2507.01352 Skywork-Reward-V2; 2508.07662 GLiClass; 2505.09388 Qwen3;
2203.09095 CodeReviewer). **Their full texts were not read in this run**; no
claim in this memo rests on their contents.

## 12. Remaining unknowns

1. **Weight SHA-256 digests — Gate 0b, unresolved for every candidate.** Not
   exposed by the API listing; must be computed from a separately authorized
   download. No digest appears in this memo.
2. **Training-data license chains — Gate 0c, unresolved for every candidate.**
   For C1 this means license-tracing `mtasksource`; for C3 and C4 the
   LLM-generated pools `synthetic_zeroshot_mixtral_v0.1` and
   `pile-mistral-v0.1`, whose license posture for derived weights is unsettled.
   C3's card asserts commercial usability, but a card assertion is not a traced
   chain.
3. **C1's actual scope behaviour.** Its Gate 1 result is unknown and is the whole
   question. The multi-task `mtasksource` recipe is a *hypothesis* about why it
   might beat FP 1.000, not evidence that it does.
4. **C1's parity cost — unmeasured.** The claim that it lands near the
   incumbent's 461 ms / 1,122 MiB is an architecture-family inference, not a
   measurement. Gate 6 must not be skipped on the strength of it, and its F32
   weights (~1.12 GB estimated) sit close to the 1,500 MiB small-lane guidance
   before activations.
5. **C1's effective context.** `max_position_embeddings` is 512 at the pin; how
   the router should chunk a 2,048-token episode across a 512-token model is
   unresolved and is the main open design question (conclusion 3).
6. **Per-case NF4 latency — not recorded.** NF4 peak VRAM (~3.84 GiB) and NF4
   rubric quality (15 / 24) *were* measured in the 2026-08-17 diagnostic, so the
   memory and quality baselines exist. Latency under NF4 does not; the ledger's
   "approximately one minute" cold serial figure is a whole-pipeline pass and is
   not a per-case substitute. Estimated NF4 figures for the two non-incumbent
   candidates in 7.2 remain weights-only arithmetic.
7. **Polish quality, as opposed to Polish presence.** Language tags confirm
   coverage; they are not evidence of per-language quality. Only Gate 2 on a
   private holdout settles this, for the incumbent and C1 alike.
8. **Whether an eligible grounding checkpoint exists outside this shortlist.**
   Four were resolved and none passed; the search was not exhaustive.
9. **C3 and C4 context lengths.** Neither card documents a maximum sequence
   length; both are rejected on other grounds, so this was not pursued.
10. **R1–R4 provenance.** Deliberately unresolved per 4.5; each is blocked on
    construct or data licensing before a checkpoint choice matters.
11. **Paper-level evidence quality.** Card-reported benchmark numbers were not
    independently verified against the papers, and per 3.3 they are not evidence
    about this product's population regardless.
