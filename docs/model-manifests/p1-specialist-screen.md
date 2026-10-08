# P1 specialist foundation pre-screen

Status: **bounded synthetic foundation only**. These 24 fictional cases are not
the planned preregistered 96+ case promotion screen. No candidate is activated
or promoted, and a synthetic score cannot satisfy the future larger screen or
the private, project- and time-separated human calibration gate.

## Frozen first slice

The runnable set is frozen to one deterministic abstaining baseline and exactly
two multilingual NLI challengers. BGE zero-shot and Qwen rubric configurations
are future, unfrozen work.

| Role | Hub repository | Immutable revision | SPDX | Safetensors SHA-256 | Product status |
|---|---|---|---|---|---|
| fast NLI challenger | [`MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli`](https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L6-mnli-xnli) | `0a71e92a985b6e1ad1828cf67ce9c459639c1dca` | MIT | `91b323ccf247ec1e3b5925d566230bae7c52de8147e6062b42e250089a3fc80b` | disabled; foundation pre-screen only |
| deeper NLI challenger | [`MoritzLaurer/multilingual-MiniLMv2-L12-mnli-xnli`](https://huggingface.co/MoritzLaurer/multilingual-MiniLMv2-L12-mnli-xnli) | `0d55db361c5f291640208c51ff8c181146aa8eff` | MIT | `47b82b3b1f18a0e4cc5cc80d470d75b3e2278603328b3dd67454b19148d7f85b` | disabled; foundation pre-screen only |

Each tokenizer is pinned to the same repository and revision as its model. The
reviewed label order is `entailment`, `neutral`, `contradiction`. The loader
uses standard `AutoModelForSequenceClassification`, `trust_remote_code=False`,
`use_safetensors=True`, `local_files_only=True`, a maximum sequence length of
512, and a bounded batch size. Its exact allowlist contains only declared
weights plus the hash-pinned artifacts below. Globally safe but undeclared
files are rejected, as are pickle weights and unexpected snapshot files.

| Candidate | Artifact | SHA-256 |
|---|---|---|
| L6 | `config.json` | `79862295be1538a947e0f56d495ef8d658c3eaebcfb42c7ad96229d195ca745d` |
| L6 | `tokenizer.json` | `098c131bb4423163db239755e309facaa6850059f850f9f3d88a78344a4b631c` |
| L6 | `tokenizer_config.json` | `86139ce1f39e814bcdb99a6fe30c0c4983911508aad07417e616d994fb74eb25` |
| L6 | `special_tokens_map.json` | `06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f` |
| L6 | `sentencepiece.bpe.model` | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |
| L12 | `config.json` | `15030844050f2df9cd2a8ab1e622cccfa0e42f15c87399aa1f8e8516a225783b` |
| L12 | `tokenizer.json` | `098c131bb4423163db239755e309facaa6850059f850f9f3d88a78344a4b631c` |
| L12 | `tokenizer_config.json` | `1e05e843ecf991ec0c148e0697f409f63032090d5f9729d052a8658c00786aff` |
| L12 | `special_tokens_map.json` | `06e405a36dfe4b9604f484f6a1e619af1a7f7d09e34a8555eb0b77b66318067f` |
| L12 | `sentencepiece.bpe.model` | `cfc8146abe2a0488e9e2a0c56de7952f7c11ab059eca145a0a727afce0db2865` |

## Oracle compatibility plumbing

The deterministic baseline always abstains because text alone cannot prove an
objective outcome. For this foundation screen, the fixture's authored
compatibility label is an oracle gate before NLI:

- compatible comparisons may reach the model;
- different scopes, superseded revisions, and insufficient evidence are
  withheld;
- compatible predictions below the exploratory threshold abstain;
- objective verification still outranks every model label.

Every report says `routing_mode=oracle_fixture_compatibility_labels` and
`router_evaluated=false`. The gate does not infer scope or temporal
compatibility, so router false-positive and incompatible-known rates remain
typed `null`, not structural zeros and not performance evidence. A real router
needs separate predictions, independently labeled truth, calibration, and an
untouched holdout.

The foundation corpus contains 24 English/Polish fictional cases: six cases for
each of bug fixes, features, code review, and research/design, balanced across
entailment, neutral, contradiction, and oracle-withheld abstention. Its reviewed
SHA-256 is
`facf05495e48966684446426157c423ebe661387c7a50860e43cc8d663943703`.
The script refuses a changed fixture. Reports carry evaluator
`specialist-foundation-evaluator-v2` and metric definition
`specialist-foundation-metrics-v2`.

Public output is aggregate-only: no text, case identifiers, paths, logits, or
per-case predictions. It reports the oracle-withheld count, NLI coverage,
selective risk/accuracy, three-way macro-F1, per-label metrics, confusion
counts, Brier score, log loss, ten-bin ECE, false-confident errors, EN/PL and
task slices, latency, memory, and dependency versions. Undefined quantities
remain `null`.

## Preserved history

`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7` at
`b5113eb38ab63efdd7f280f8c144ea8b13f978ce` remains a rejected historical
unscoped configuration. It is absent from the runnable registry and is not
compared with this oracle-gated plumbing screen. A future router experiment is
a new configuration, not a reversal or erasure of the historical decision.

## Reproduce safely

The default is network-closed and returns typed unavailable states when the
isolated cache is empty:

```powershell
python scripts/evaluate_specialist_screen.py --smoke
```

Explicit preparation of only reviewed public files is opt-in; subsequent full
evaluation is offline:

```powershell
python scripts/evaluate_specialist_screen.py --download --device cuda --smoke
python scripts/evaluate_specialist_screen.py --device cuda
```

Candidates execute serially and are unloaded between runs. Output is not
written to the product metric store and cannot create an activation record.

The measured run used Python `3.11.0`, `huggingface-hub` `0.35.1`,
`safetensors` `0.5.3`, SentencePiece `0.2.2`, PyTorch `2.8.0+cu126`, and
Transformers `4.56.2`. SentencePiece was installed only into the ignored
evaluation runtime from `sentencepiece-0.2.2-cp311-cp311-win_amd64.whl`,
SHA-256
`70d4ca6f4d06df7f0ccab6fe4f49c8a712c8c8b6847b4f0af9a0e1dbb0e0337e`.
The system environment and repository lockfile were unchanged. Reports record
package versions, not installation paths.

The distributable dependency policy now caps the optional model extra at the
reviewed PyTorch `2.8` minor. The universal PyPI lock deliberately does not
claim to reproduce the CUDA-specific `2.8.0+cu126` evaluation wheel; that wheel
belongs only to an ignored, explicit evaluation environment. A release must
not silently promote this evidence to a CUDA-13 or later PyTorch runtime.
The other locked model libraries may be newer than this historical screen;
their presence in the release lock is not new quality or calibration evidence.

## Bounded CUDA observation

The exploratory confidence threshold was `0.70`. Neural metrics cover only the
18 compatible NLI cases; six other cases are counted as oracle-withheld and
never as correct predictions.

| Configuration | Corpus / NLI / withheld | Coverage on 18 | Accuracy on 18 | 3-way macro-F1 | Selective accuracy | Brier | ECE | False-confident error at 0.9 | Inference ms | Peak CUDA MiB |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| deterministic objective-evidence abstainer | 24 / 18 / 6 | 0.000000 | 0.000000 | 0.000000 | unknown | unknown | unknown | unknown | - | - |
| MiniLMv2 L6 + oracle gate | 24 / 18 / 6 | 0.555556 | 0.444444 | 0.570707 | 0.800000 | 0.508809 | 0.208389 | 0.111111 | 193.842 | 423.177 |
| MiniLMv2 L12 + oracle gate | 24 / 18 / 6 | 0.722222 | 0.555556 | 0.626263 | 0.769231 | 0.596089 | 0.311066 | 0.111111 | 33.251 | 463.791 |

L12 covered more compatible cases and had higher macro-F1; L6 had higher
selective accuracy and better Brier/ECE. Both had an 11.1% false-confident
error rate. Neither is calibrated or near the campaign activation ECE gate.
Router metrics are unevaluated and `null`.

Latency and memory are one-machine observations. L6 ran first, so initialization
and accelerator warm-up confound timing; this is not a defensible speed ranking.
The planned 96+ preregistered screen, a separately evaluated real router, and
private calibration remain required. Both candidates stay product-disabled.
