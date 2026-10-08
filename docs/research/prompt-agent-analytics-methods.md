# Local methods for prompt and coding-agent analytics

Status: research catalog v2, reviewed 2026-08-09.

This note defines the method stack behind the dashboard's **Methods & models**
view. It is a research and release plan, not a claim that a model can measure a
person's intelligence, cognitive worth, or engineering rank.

The useful target is a multidimensional work profile:

- how clearly work and acceptance conditions are defined;
- how uncertainty is surfaced and resolved;
- how requirements, decisions, actions and evidence remain connected;
- how agent answers are grounded;
- whether delivery is objectively verified.

Each dimension keeps its own denominator, applicability, evidence, coverage,
calibration and version. There is no universal quality score. A compact summary
may show evidence coverage and the individual axes, but must not average
incompatible dimensions into a developer ranking.

## Why a method stack is necessary

No single model answers all of the product questions safely:

1. Deterministic extractors are explainable and cheap, but miss paraphrases and
   cannot establish intent.
2. Lexical retrieval provides a transparent baseline.
3. Multilingual embeddings retrieve paraphrased candidate links, but similarity
   does not establish entailment or correctness.
4. Cross-encoders can rerank a bounded top-k set more precisely, but relevance
   is still only a candidate relationship.
5. NLI can test a *scoped* pair after retrieval, but direct application is prone
   to false contradictions across unrelated scopes.
6. Dialogue-act classifiers distinguish requests, questions, hypotheses,
   decisions, corrections and evidence.
7. A typed requirement/supersession graph provides the state needed for
   traceability and closure metrics.
8. Process metrics measure observable request-plan-action-test-correction loops.
9. A small local instruction model may answer bounded rubric questions where
   specialized models are insufficient.
10. Selective prediction and human calibration decide when every inferred
    component must abstain.

The expensive pair methods must follow retrieval. The pipeline is therefore
bounded rather than quadratic:

```text
redacted local window
  -> deterministic segmentation and typed candidates
  -> BM25 + embedding top-k retrieval
  -> optional cross-encoder reranking
  -> scoped classifier or bounded rubric
  -> typed traceability graph
  -> content-free metrics, receipts and provenance
```

Raw prompts, responses, model outputs, excerpts, paths and embeddings remain
ephemeral. The database stores only typed states, counts, content-free signal
codes, pseudonymous evidence references and full version provenance.

## Metric roadmap

| Profile | Metric question | Direction | Required evidence | First method |
|---|---|---|---|---|
| Prompt | Does the request state action, target, context and outcome? | Higher is better | Typed request fields | Rules, then calibrated extraction |
| Prompt | For diagnosis tasks, are observed/expected behavior, reproduction and environment stated? | Higher is better | Diagnosis applicability plus four factor receipts | Rules, then calibrated extraction |
| Prompt | Are component, current state, environment and boundaries stated? | Higher is better | Four context-factor receipts | Rules, then calibrated extraction |
| Prompt | Are material ambiguities resolved? | Higher is better | Ambiguity-to-resolution links | Requirement extraction + supersession |
| Prompt | Are applicable constraints concrete? | Higher is better | Reviewed constraint denominator | Typed extraction + rubric |
| Prompt | Can outcomes be checked objectively? | Higher is better | Requirement-to-check links | Extraction + traceability |
| Prompt | Is the artifact, interface or output contract explicit? | Higher is better | Deliverable clauses and contract factors | Extraction + rubric candidate |
| Collaboration | Do questions resolve uncertainty? | Contextual | Question-to-ambiguity-to-answer links | Dialogue acts + graph |
| Collaboration | Does exploration converge to action and evidence? | Contextual | Dialogue acts and process transitions | Process metrics |
| Logic | Are hypotheses followed by discriminating tests? | Higher is better | Hypothesis-test-conclusion links | Dialogue acts + graph |
| Logic | Can active requirements be linked to action or deferral? | Higher is better | Calibrated requirement-action links | Retrieval + reranking + graph |
| Logic | Is the observable plan updated after new evidence? | Higher is better | Plan versions and evidence | Supersession + process metrics |
| Logic | Are consequential decisions connected to evidence or constraints? | Higher is better | Decision-support links | Dialogue acts + rubric |
| Collaboration | Are scope changes explicit and obsolete requirements suppressed? | Higher is better | Active/superseded requirement state | Supersession graph |
| Collaboration | How much avoidable correction and rework occurs? | Lower is better | Cause-linked correction loops | Dialogue acts + process metrics |
| Agent answer | Are important claims supported by evidence? | Higher is better | Claim-to-tool/test/source links | Retrieval + graph |
| Agent answer | Does the plan connect requirements to suitable verification strategies? | Higher is better | Requirement-to-verification-plan links | Traceability + process metrics |
| Agent answer | Are open questions and commitments closed or carried forward? | Higher is better | Open-loop nodes at the snapshot boundary | Dialogue acts + graph |
| Outcome | Did the artifact pass relevant checks or acceptance? | Higher is better | Objective verification or human acceptance | Verification events + graph |
| Outcome | Did the first meaningful executable verification pass? | Higher is better | First versioned verification episode | Verification events + graph |

Question *frequency* and amount of *theorizing* are intentionally not standalone
quality scores. A useful question is one that resolves uncertainty; useful
exploration is exploration that produces a decision, check, or explicit
deferral. The right amount depends on task type and complexity.

## Local Hugging Face candidates

Candidate selection requires public weights, a reviewed license, safetensors,
an immutable revision and digest, `trust_remote_code=False`, bounded token and
batch limits, and local inference. A model card or public benchmark never
activates a product metric by itself.

### Full local CUDA screen

| Candidate | Intended role | Synthetic observation | Decision |
|---|---|---|---|
| `intfloat/multilingual-e5-small` | EN/PL requirement-action retrieval | Full 12-case top-1 0.666667 and MRR 0.819444, above BM25; the 4-case smoke comparison reversed | Exploratory only; expand untouched corpus and privately calibrate |
| `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | Scoped contradiction | 18-case three-way accuracy 0.555556; different-scope contradiction FP 1.0 | Rejected for product use |
| `BAAI/bge-m3` | Hybrid multilingual retrieval | Pinned revision offered only a reviewed pickle weight, not safetensors | Blocked before download |
| `BAAI/bge-reranker-v2-m3` | Bounded pair reranking | 12-case top-1 0.750000 and MRR 0.875000; smoke performance was worse than BM25 | Exploratory only; variance and private precision gate remain |
| `Qwen/Qwen3-Embedding-0.6B` | Instruction-aware retrieval | 12-case top-1 0.750000 and MRR 0.861111; about 1.2 GB peak CUDA allocation | Strongest fictional retrieval candidate; not activated |
| `Qwen/Qwen3-Reranker-0.6B` | Bounded pair reranking | 12-case top-1 0.666667 and MRR 0.826389 | Exploratory only; not activated |
| `Qwen/Qwen3-4B-Instruct-2507` | Strict JSON rubric | 24-case exact accuracy 0.666667, JSON compliance 1.0, abstention macro-F1 0.521368; about 7.8 GB peak CUDA allocation | Rejected for product scoring |

These aggregate results are reproducible through
`scripts/evaluate_local_text_models.py`. They use fictional English and Polish
fixtures only. They are functional screens, not user accuracy estimates.

All results came from the same fictional EN/PL screen on an RTX 3080 Ti Laptop
GPU with 16 GB VRAM. They are not accuracy estimates for user sessions. Opening
the dashboard never downloads a model. The Model candidates view can explicitly
start an isolated subprocess that runs one model at a time; device selection is
CUDA first, Apple MPS second, then CPU. Downloads use immutable revisions,
reviewed SHA-256 digests, `token=False`, `trust_remote_code=False`, safetensors
only, and the ignored `runtime/model-eval` cache.

The 4B candidate consumes roughly 7.8 GB of accelerator memory before normal
desktop overhead. It may fit an 8 GB card only marginally, so the application
must report resource exhaustion rather than assume availability. No quantized
artifact is accepted until it has its own immutable manifest and license review.

## Evaluation and activation gates

### Deterministic and retrieval components

- 100% exact golden tests for typed state, fraction, coverage and provenance.
- Synthetic adversarial English/Polish cases for negation, supersession,
  unrelated scopes, vague references and mixed-language messages.
- Retrieval critical-link precision at least 0.95, with lower 95% confidence
  bound at least 0.90, before links can be presented as evidence rather than
  candidates.
- No O(n²) conversation scan: retrieve top-k before pair scoring.

### Inferred labels and rubric models

- Two independent human raters plus adjudication on a private local annotation
  set; only fictional examples enter the public repository.
- Krippendorff's alpha at least 0.80 for categorical/ordinal gold labels.
- On a project- and time-separated holdout: lower 95% bootstrap confidence
  bound of macro-F1 at least 0.75, every class recall at least 0.65, and expected
  calibration error at most 0.08.
- With abstention: at least 90% selective accuracy at at least 60% coverage.
- Critical false-positive gates are stricter for contradiction, acceptance and
  verified-delivery claims.

### Product usefulness

An inferred prompt metric becomes coaching evidence only after it adds
predictive value over task type, complexity, provider and time baselines on a
held-out set. Association is not a causal improvement claim. A later paired
experiment must use objective verification or human acceptance as the outcome.

## Sources

Primary papers and official model cards used by catalog v2:

- [Requirement-Oriented Prompt Engineering](https://arxiv.org/abs/2409.08775)
- [ISO-standard domain-independent dialogue-act tagging](https://aclanthology.org/C18-1300/)
- [Asking the Right Question at the Right Time](https://aclanthology.org/2024.eacl-long.16/)
- [LLM-Rubric](https://aclanthology.org/2024.acl-long.745/)
- [The Art of Abstention](https://aclanthology.org/2021.acl-long.84/)
- [Text Embeddings by Weakly-Supervised Contrastive Pre-training](https://arxiv.org/abs/2212.03533)
- [Multilingual E5 Text Embeddings](https://arxiv.org/abs/2402.05672)
- [BGE-M3](https://arxiv.org/abs/2402.03216)
- [Qwen3 Embedding](https://arxiv.org/abs/2506.05176)
- [Referential ambiguity and clarification requests](https://aclanthology.org/2025.crac-1.1/)
- [On the role of effective and referring questions](https://aclanthology.org/2020.alvr-1.4/)
- [cross-encoder multilingual MS MARCO model card](https://huggingface.co/cross-encoder/mmarco-mMiniLMv2-L12-H384-v1)
