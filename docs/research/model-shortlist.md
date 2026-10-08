# Local model and algorithm shortlist

Snapshot: 2026-08-06
Policy: permissive-license, CPU-first defaults; neural scores are evidence, not truth

## Recommended first bundle

Ship a useful deterministic product before adding generative analysis:

- SQLite FTS5/BM25, TF-IDF, character n-grams, NMF, rules, checksums, and process metrics;
- `sentence-transformers/all-MiniLM-L6-v2` for short English prompts or `intfloat/multilingual-e5-base` for multilingual use;
- Microsoft Presidio plus a deterministic secret scanner such as Gitleaks;
- no emotion, NLI, generative summary, or LLM judge in the first default path.

After an in-domain benchmark, add challengers one capability at a time.

## Embeddings

| Candidate | License | Approx. size/scope | Best use | Caveat |
|---|---|---|---|---|
| [all-MiniLM-L6-v2](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2) | Apache-2.0 | 22.7M, 384d, English, 256 word-piece truncation | Fast CPU baseline for short prompts/summaries | English and short-context ceiling |
| [multilingual-e5-base](https://huggingface.co/intfloat/multilingual-e5-base) | MIT | ~0.3B, 768d, multilingual, 512 tokens | Recommended multilingual baseline | Must follow `query:`/`passage:` conventions; low-resource quality varies |
| [Qwen3-Embedding-0.6B](https://huggingface.co/Qwen/Qwen3-Embedding-0.6B) | Apache-2.0 | 0.6B, 100+ natural/programming languages, 32K, Matryoshka dimensions | Multilingual/code challenger | Heavier; GPU preferred for bulk |
| [bge-m3](https://huggingface.co/BAAI/bge-m3) | MIT | ~0.6B, multilingual, 8K, dense+sparse+multi-vector | Hybrid-retrieval experiment | Operational complexity and compute |

Always compare dense retrieval with FTS5/BM25 and reciprocal-rank fusion. MTEB rank alone does not select the best model for engineering conversations.

## Reranking

| Candidate | License | Use | Caveat |
|---|---|---|---|
| [ettin-reranker-17m-v1](https://huggingface.co/cross-encoder/ettin-reranker-17m-v1) | Apache-2.0 | New CPU-first English challenger | Very new; self-reported card results require replication |
| [ms-marco-MiniLM-L6-v2](https://huggingface.co/cross-encoder/ms-marco-MiniLM-L6-v2) | Apache-2.0 | Mature small English fallback | Web-relevance training differs from requirement/evidence matching |
| [Qwen3-Reranker-0.6B](https://huggingface.co/Qwen/Qwen3-Reranker-0.6B) | Apache-2.0 | Multilingual/code top-k reranking | GPU preferred; score is not a calibrated probability |
| [bge-reranker-v2-m3](https://huggingface.co/BAAI/bge-reranker-v2-m3) | Apache-2.0 | Multilingual encoder reranking | Too slow for full-corpus CPU scoring; rerank a small candidate set |

## NLI and contradiction candidates

| Candidate | License | Scope | Caveat |
|---|---|---|---|
| [nli-deberta-v3-small](https://huggingface.co/cross-encoder/nli-deberta-v3-small) | Apache-2.0 | Small English CPU starting point | SNLI/MNLI genres are not engineering state changes |
| [DeBERTa-v3-base-mnli-fever-anli](https://huggingface.co/MoritzLaurer/DeBERTa-v3-base-mnli-fever-anli) | MIT | More robust English challenger | Still needs domain calibration |
| [mDeBERTa-v3-base-mnli-xnli](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-mnli-xnli) | MIT | Multilingual challenger | Supervised XNLI covers fewer languages than pretraining |

Read each checkpoint's `id2label`; label order differs. Extract typed, scoped claims before NLI. A changed requirement, later timestamp, different branch/environment, conditional statement, or different speaker is not automatically a contradiction.

## Affect and friction

[SamLowe/roberta-base-go_emotions](https://huggingface.co/SamLowe/roberta-base-go_emotions) (MIT, ~0.1B, English) is a reasonable exploratory challenger. Its Reddit domain and uneven per-label performance make it unsuitable as truth about frustration. Combine any text signal with observable corrections, repeated failures, and retries, then calibrate on a voluntary engineering dataset.

VADER is a fast auditable English baseline. A multilingual positive/neutral/negative model can be tested, but coarse sentiment adds less value than outcome and friction events.

The UI should call this “expressed affect/friction,” keep it private, and never export it to team rankings.

## PII and secrets

Recommended order:

1. Structured patterns, provider-token prefixes, entropy, and checksums (Luhn, IBAN, country formats).
2. [Microsoft Presidio](https://github.com/microsoft/presidio) with custom recognizers.
3. A GLiNER challenger for missed contextual entities, such as [gliner_multi_pii-v1](https://huggingface.co/urchade/gliner_multi_pii-v1), only after domain evaluation.
4. Conservative span merging and redaction before persistence, embedding, logs, or APIs.

Presidio explicitly does not guarantee detection of all PII. Neural PII models can have low precision or synthetic-data bias. Store only type, span position, detector version, and a keyed match hash; never print/store the matched secret.

## Topic discovery

Baseline: word/character TF-IDF plus NMF. It is fast and interpretable.

Challenger: BERTopic (embeddings -> UMAP -> HDBSCAN -> class-based TF-IDF), applied to task/session summaries rather than isolated turns. Report seed stability, outlier rate, topic diversity/coherence, and human labelability. UMAP/HDBSCAN density choices can substantially change results.

## Summarization and compaction

Prefer a schema-preserving summary:

```text
goal, authoritative requirements, constraints, decisions and rationale,
unresolved questions, actions, files/artifacts, verification outcomes,
failures/blocks, next actions, source event IDs
```

Candidates:

- [Qwen3-1.7B](https://huggingface.co/Qwen/Qwen3-1.7B), Apache-2.0, multilingual local generative challenger;
- `distilbart-cnn-12-6`, Apache-2.0, English extractive/generative baseline but news-domain and short-context limited;
- deterministic extraction of decisions, actions, checks, entities, and numbers as the mandatory baseline.

Evaluate requirement/decision/action recall, number/entity preservation, groundedness, compression ratio, and human usefulness. ROUGE is insufficient. Never delete source history merely because a summary exists.

## Optional quality judges

- [Prometheus 2 7B](https://huggingface.co/prometheus-eval/prometheus-7b-v2.0), Apache-2.0 weights, specialist rubric judge, workstation-class and English-focused.
- [Qwen3-4B-Instruct-2507](https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507), Apache-2.0, smaller multilingual structured-output challenger but not judge-specialized.
- `gpt-oss-20b`, Apache-2.0, higher local tier requiring roughly workstation memory and careful calibration.

Use a versioned multidimensional rubric: goal clarity, context sufficiency, constraints, verifiability, safety, requirement coverage, and evidence. Require cited source spans, allow abstention, swap pairwise order, normalize verbosity/formatting, and compare with human/outcome labels. Do not create a single “prompt IQ” or “design intelligence” score.

## Domain benchmark

Build consented/synthetic gold data and split by user/project/repository and time to prevent near-duplicate leakage. Include English/Polish, later languages, task types, context lengths, code/text ratios, successes/failures, and same-repository hard negatives.

| Capability | Required evaluation |
|---|---|
| Retrieval | Recall@k, nDCG@10, MRR, hard negatives, cold/warm latency, memory/index size |
| Reranking | Delta over BM25/dense, nDCG/MRR, tail latency by pair length |
| NLI | Macro-F1 and per-class precision/recall, Brier/ECE, abstention; temporal/scope/environment/quantity suites |
| Affect/friction | Per-label AUPRC/F1, calibration, language slices, relationship to observed correction/failure events |
| PII/secrets | Exact and overlap span recall/precision, token leakage, Polish/EU/code/log canaries; false negatives weighted heavily |
| Judge | Weighted kappa/rank correlation with expert labels; order, verbosity, formatting, and model-name counterfactuals |
| Summary | Requirement/decision/action recall, entity/number preservation, groundedness, human utility |
| Topics | Coherence/diversity plus bootstrap/seed stability, outlier rate, word intrusion, and downstream usefulness |

## Model supply-chain policy

- Pin an immutable Hub revision and file SHA-256.
- Record SPDX license, base model, datasets, tokenizer, context/dimensions, and a model-card snapshot.
- Keep `trust_remote_code=false`; accept safetensors/ONNX, not arbitrary pickle weights.
- Run downloads and inference outside the repository in an isolated worker/cache.
- Do not vendor weights or real evaluation conversations.
- A Hub license tag is metadata, not complete provenance clearance.

Do not use as defaults without a license change or explicit legal review:

- `jinaai/jina-embeddings-v3` (CC-BY-NC-4.0);
- `iiiorg/piiranha-v1-detect-personal-information` (CC-BY-NC-ND-4.0);
- checkpoints with no explicit license such as the commonly used `j-hartmann` English emotion model;
- models whose base or training-data terms conflict with the intended public/commercial distribution.

## Phased selection

1. Deterministic telemetry + FTS5/TF-IDF/NMF + MiniLM/E5 + Presidio/secret patterns.
2. In-domain benchmark, then optional reranker, NLI, and BERTopic challengers.
3. Opt-in local structured summaries and calibrated multidimensional judge.
4. Affect stays experimental/non-evaluative even if it performs well.
