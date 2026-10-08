# WP-11 local text-model candidates

Status: **synthetic exploratory screen only**. These models are not activated in
product metrics. A model must still pass private, consented,
project-stratified and time-separated calibration before it can produce a
calibrated metric.

| Purpose | Hub repository | Immutable revision | SPDX | Reviewed primary weight SHA-256 | Gate status |
|---|---|---|---|---|---|
| requirement-to-action retrieval | `intfloat/multilingual-e5-small` | `614241f622f53c4eeff9890bdc4f31cfecc418b3` | MIT | `1a55775f53449dac10a2bcbc312469fac40b96d53198c407081a831f81c98477` | evaluated |
| requirement-to-action retrieval | `intfloat/multilingual-e5-base` | `d128750597153bb5987e10b1c3493a34e5a4502a` | MIT | `a18a44fad1d0b46ded15928144138cff1135d5cc8233bdd90be5f18822de09a7` | evaluated exploratory; not activated |
| requirement-to-action retrieval | `Qwen/Qwen3-Embedding-0.6B` | `97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3` | Apache-2.0 | `0437e45c94563b09e13cb7a64478fc406947a93cb34a7e05870fc8dcd48e23fd` | evaluated |
| pair reranking | `BAAI/bge-reranker-v2-m3` | `953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e` | Apache-2.0 | `d9e3e081faff1eefb84019509b2f5558fd74c1a05a2c7db22f74174fcedb5286` | evaluated |
| pair reranking | `Qwen/Qwen3-Reranker-0.6B` | `e61197ed45024b0ed8a2d74b80b4d909f1255473` | Apache-2.0 | `27cd75a405b9c1b46b59abfd88aaa209e6fed2a1972cde9b70e7659537c5e65b` | evaluated |
| typed scoped NLI | `MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` | `b5113eb38ab63efdd7f280f8c144ea8b13f978ce` | MIT | `7c8e29f1115986d032e92b0fbaa0bdef1062a46f658b08705f237c05014a8541` | evaluated |
| structured rubric | `Qwen/Qwen3-4B-Instruct-2507` | `cdbee75f17c01a7cc42f958dc650907174af0554` | Apache-2.0 | `75311d91bb08cf0b882913da464a1e722a31fb44db35208663487efb7a3d8ed6` | evaluated; three verified shards |
| dense retrieval | `BAAI/bge-m3` | `142964af7e05de16511657561de8e8750fc153a0` | MIT | `993b2248881724788dcab8c644a91dfd63584b6e5604ff2037cb5541e1e38e7e` | evaluated exploratory; not activated |

Each tokenizer is pinned to the same repository and commit as its model. The
runtime accepts only the manifest's reviewed safetensors files, verifies every
declared digest before loading, sets `trust_remote_code=False`, and loads the
verified snapshot with `local_files_only=True`. Pickle-style artifacts are
rejected. The structured Qwen manifest verifies all three weight shards; the
table shows its first shard only to keep the inventory readable.

The earlier BGE-M3 decision remains part of the audit trail: revision
`5617a9f61b028005a4858fdac845db406aefb181` was blocked because its reviewed
primary artifact was pickle-only (`pytorch_model.bin`, SHA-256
`b5e0a70128ad4f26da749a34c4a202c9ba503069e0f40a27d3c35619a358ad38`).
The newer immutable revision supersedes that artifact decision without erasing
it. Its standard XLM-RoBERTa config and tokenizer declare no remote-code map;
the evaluator verifies the safetensors weight plus every required config and
tokenizer artifact before standard `AutoModel` CLS-pooling inference.

Required BGE-M3 auxiliary artifacts at the superseding revision:

| Artifact | SHA-256 |
|---|---|
| `config.json` | `26159e7ad065073448460117eb24b7a4572f6f4e78eadff65dc0a11c052449fa` |
| `tokenizer.json` | `21106b6d7dab2952c1d496fb21d5dc9db75c28ed361a05f5020bbba27810dd08` |
| `tokenizer_config.json` | `a62b2b6784f990259fddef5f16388693a8043be4f69179e6a5257eeb3f9abac4` |
| `special_tokens_map.json` | `8c785abebea9ae3257b61681b4e6fd8365ceafde980c21970d001e834cf10835` |
| `sentencepiece.bpe.model` | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| `modules.json` | `84e40c8e006c9b1d6c122e02cba9b02458120b5fb0c87b746c41e0207cf642cf` |
| `config_sentence_transformers.json` | `1eef72430e7194a1e59680e635aed81ffa083f05668dbc5bb1c56c04c0999c38` |
| `sentence_bert_config.json` | `eb9b44b13c0f52a3b3685c3b1cbdea1ba8b04bea123b98f61610048940776eb1` |
| `1_Pooling/config.json` | `e54c164a07274f2eb45bb724f54a79d1efcc90c41573887cd9a29aeee0597352` |

## Network and privacy boundary

- The benchmark reads one checked-in fictional EN/PL fixture. It has no external
  corpus argument and no provider adapter.
- It never reads provider caches, global Hugging Face caches, credentials, or
  local conversations.
- Public model artifacts live only under the ignored `runtime/model-eval`
  directory. Symlink escapes and cache paths outside that boundary are rejected.
- Network access is disabled by default. `--download` is the only switch that
  permits downloading the allowlisted files at the pinned revisions, with
  `token=False` for these public repositories.
- Standard output contains aggregate counts, scores, deltas, latency, memory,
  device, and public model pins only. It contains no fixture text, case IDs,
  embeddings, cache paths, host identifiers, or exception details.

## Benchmark design

The retrieval slice contains English and Polish requirement/action pairs with
near-topic hard negatives. It reports unique top-1 accuracy, mean reciprocal
rank, and recall at three. A transparent per-query BM25 implementation is the
deterministic lexical baseline. Embedding and reranking candidates run against
the same bounded candidate sets, but their results remain separate capability
screens rather than one leaderboard.

The NLI slice contains typed entailment, neutral, and contradiction examples in
both languages. Every item declares whether the two statements address the same
scope. It reports three-way accuracy, binary contradiction accuracy and macro-F1,
plus the false-positive rate on different-scope examples. No lexical NLI
baseline is claimed because surface negation is not a valid general
contradiction detector.

The structured-rubric slice contains balanced fictional English and Polish
examples for task definition, constraint precision, acceptance testability,
and deliverable contract. It reports exact label agreement, language slices,
abstention macro-F1, schema compliance, latency, and memory. Valid JSON is an
integration gate, not evidence that the labels are correct.

The fixture is intentionally small. Scores are functional screening evidence,
not population accuracy, not proof of prompt quality, and never a developer
ranking.

## Reproduce locally

Offline behavior and guards:

```powershell
python -m pytest -q tests/test_local_text_model_evaluation.py
python scripts/evaluate_local_text_models.py --smoke
```

The second command returns a safe `model_cache_missing_or_invalid` status when
the isolated cache is empty. Explicit public download and GPU smoke test:

```powershell
python scripts/evaluate_local_text_models.py --download --device cuda --smoke
```

After the verified snapshots exist, the full screen is network-free:

```powershell
python scripts/evaluate_local_text_models.py --device cuda
```

## Synthetic reference result

Network-closed full screens completed all eight safe neural candidates one
model at a time on one 16 GB CUDA device. The historical BGE-M3 pickle-only pin
was blocked before download; its superseding safetensors revision completed.
These are one-machine exploratory observations on tiny authored fixtures, not
model-quality or population-accuracy claims.

| Capability | Backend | Cases | Primary | Secondary | Critical gate | Inference ms | Peak CUDA MiB |
|---|---|---:|---:|---:|---:|---:|---:|
| retrieval | BM25 | 12 | top-1 0.583333 | MRR 0.729167 | recall@3 0.750000 | 0.534 | — |
| retrieval | multilingual E5 small | 12 | top-1 0.666667 | MRR 0.819444 | recall@3 1.000000 | 285.495 | 462.436 |
| retrieval | multilingual E5 base | 12 | top-1 0.833333 | MRR 0.902778 | recall@3 1.000000 | 453.488 | 1,078.121 |
| retrieval | BGE-M3 dense | 12 | top-1 0.666667 | MRR 0.819444 | recall@3 1.000000 | 432.376 | 2,179.602 |
| retrieval | Qwen3 Embedding 0.6B | 12 | top-1 0.750000 | MRR 0.861111 | recall@3 1.000000 | 573.687 | 1,197.371 |
| reranking | BGE Reranker v2 M3 | 12 | top-1 0.750000 | MRR 0.875000 | recall@3 1.000000 | 236.369 | 2,194.156 |
| reranking | Qwen3 Reranker 0.6B | 12 | top-1 0.666667 | MRR 0.826389 | recall@3 0.916667 | 388.045 | 1,488.585 |
| scoped NLI | multilingual DeBERTa | 18 | 3-way accuracy 0.555556 | contradiction F1 0.600000 | different-scope FP 1.000000 | 460.529 | 1,121.560 |
| structured rubric | Qwen3 4B Instruct | 24 | exact agreement 0.666667 | abstention F1 0.521368 | JSON compliance 1.000000 | 10,791.454 | 7,769.893 |

Multilingual E5 base led this retrieval slice, while BGE Reranker led the
separate reranking slice. Its 12-case top-1 advantage over BM25 was 0.25, but
the smoke/full variance and small case counts make all results unstable. The
candidate is neither promoted nor activated. BGE-M3 dense tied E5 small,
improved on BM25 by 0.083334 top-1 and 0.090277 MRR, and trailed E5 base and
Qwen while using the most accelerator memory of the dense retrieval group.
The NLI candidate marked every
different-scope negative as a contradiction, a hard failure for scoped use.
The Qwen rubric model always returned valid JSON but did not reach a defensible
agreement or abstention gate. None of the neural candidates is activated in
product metrics.

Latency and memory are local operational observations only. They cannot be
compared across machines, and a faster or larger model is not automatically a
better metric extractor.
