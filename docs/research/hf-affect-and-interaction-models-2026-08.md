# Hugging Face affect and interaction models: decision memo

Snapshot: 2026-08-17 · independent research pass (Researcher A), isolated public worktree
Scope: small/local Hub candidates for emotion, affect, sentiment, empathy, politeness,
toxicity, urgency/frustration language, dialogue acts, stance, disagreement, social tone,
EN/PL

**Recommendation: activate no affect model.** Pursue one assistant-output safety signal as
research under gates, self-only. No manager, team, cohort, or peer-comparison scoring is
proposed anywhere in this document. Nothing here changes runtime code, manifests, lockfiles,
or metric definitions.

---

## 1. Evidence basis and its limits

Candidate-model rows were resolved on 2026-08-17 against the official Hub API and, where the
repository was not gated, a card at the named model commit; Section 11 identifies gated,
mutable dataset, and Moritz-reference exceptions explicitly. Repository claims were read from
this worktree and are cited by file path.

Four limits bound everything below.

**Publisher-reported and out-of-domain.** Every F1, AUC, precision, and alert figure was
self-reported by the model's author on that author's own split — Reddit, Twitter,
Wikipedia-style comments, Polish social media, or synthetic customer-service text. None was
independently replicated and **none was measured on coding-agent conversations**. These are
signals for ruling candidates *out*. The repository already requires replication of card
results (`docs/research/model-shortlist.md:32`).

**Bounded search.** Discovery was targeted: direct lookups of the candidates in the review
brief, plus one downloads-sorted Hub listing filtered to Polish text-classification and
capped at 40 results. Every negative statement in this memo is therefore scoped to that
slice — "not found in the searched slice", never "does not exist". A recent, low-download, or
differently-tagged model could have been missed.

**No weight digests.** The API resolves revisions but not per-file content digests. The
repository computes and verifies them in its reviewed `--download` step
(`docs/model-manifests/wp-11-local-candidates.md:55-59`); that is the correct place. Revisions
below are immutable, so digest capture is deterministic.

**Licence findings are admission policy, not legal advice** (Section 4.6).

---

## 2. Boundary: what may and may not be measured

### 2.1 Language is not a person

A classifier observes **language**. `P(label="annoyance") = 0.83` states that a redacted
token sequence resembles a region of a training distribution that annotators labelled
"annoyance" in another domain. It is not a measurement that a human was annoyed. The
repository already holds this (`docs/metrics-catalog.md:386`;
`docs/research/research-journal.md` finding 5); Section 7.2 makes it structural.

Permanently out of scope: inner emotional state, mood, personality, mental health, burnout,
stress, wellbeing, engagement, motivation, developer worth, skill, seniority, intelligence,
and any comparison of one person to another (`AGENTS.md:22`, `PRIVACY.md:69`).

**Self-only.** Every signal is computed for, and visible only to, the person whose session it
is. No manager view, team view, cohort view, peer comparison, or export path.

### 2.2 Six-test screen

All must pass; one failure rejects the feature.

| # | Test | Reject if |
|---|---|---|
| 1 | **Subject** — about the text or the person? | Framed as a property of the person |
| 2 | **Attribution** — can anyone but the measured user see a value attributable to them? | Yes |
| 3 | **Aggregation** — can it enter a composite, ranking, comparison, or export? | Yes |
| 4 | **Self-benefit** — concrete action inside the user's own session? | No |
| 5 | **Reversibility** — can the user disable and delete it, with cascade? | No |
| 6 | **Chilling effect** — would measurement make honest expression costlier? | Yes |

Test 6 is decisive and usually skipped: a user who learns their frustration language is
scored has a rational incentive to write blander prompts, degrading the corpus the product
exists to analyse. That makes an inferred-frustration metric self-defeating on its own terms.

**Passing all six does not discharge residual duties.** Classifier output over message text
is **sensitive derived data** — "pseudonymized is not anonymous" (`AGENTS.md:12`,
`PRIVACY.md:33`). Even a self-only signal needs bounded retention, local access control,
deletion that cascades to caches and aggregates, and a recorded lawful basis.

### 2.3 Regulatory position, stated precisely

The AI Act (Regulation (EU) 2024/1689) defines an **emotion recognition system** as "an AI
system for the purpose of identifying or inferring emotions or intentions of natural persons
**on the basis of their biometric data**" (recital 18; Article 3(39) contains the operative
definition). AI Act Article 3(34) directly defines *biometric data*; recital 14 directs that
concept to be interpreted in light of GDPR Article 4(14), concerning personal data resulting
from specific technical processing of physical, physiological, or behavioural characteristics
allowing unique identification.

Three consequences, and no more than three:

1. **Text-only affect analysis is most likely outside that category**, because prose typed
   into a prompt is not biometric data under the cross-referenced definition. The Act's
   workplace prohibition — "the placing on the market, the putting into service, or the use of
   AI systems intended to be used to detect the emotional state of individuals in situations
   related to the workplace and education should be prohibited", with the carve-out that it
   "should not cover AI systems placed on the market strictly for medical or safety reasons,
   such as systems intended for therapeutical use" (recital 44) — is therefore **not
   established to apply** to a text classifier. **Applicability is unresolved**, not settled
   in either direction, and this memo does not assert a blanket ban on text-based affect
   analysis.
2. **GDPR workplace profiling is a separate question** that does not depend on the AI Act
   analysis. It stands on its own regardless of how (1) resolves.
3. **A DPIA is indicated for employer-controlled systematic monitoring**, which is the
   scenario likely to be high risk under GDPR Article 35 and the EDPB-endorsed criteria in
   WP248 rev.01; the Polish DPA has published its own Article 35(4) list. **Self-only local
   use by an individual on their own machine is not automatically employer processing**, and
   the controller question must be settled before any DPIA duty is assumed. Assess with
   counsel and, where one exists, the DPO. Primary links in Section 11.

Nothing above is legal advice. The one operational conclusion that does not depend on
resolving any of it: **assistant-output safety classification sits further from every one of
these questions than user-affect inference does**, which is an independent reason to prefer it.

### 2.4 Flip the subject, and price the residual

Most product value needs no user-text classification: is the assistant's response abusive?
asking a real clarifying question, or stalling? hedging where it should commit? All are
answered from **assistant** text. The assistant is not a person, so misattribution of inner
state and chilling effects on the user's own expression — the two harms that make
user-directed affect indefensible — do not arise.

That makes assistant-text signals **materially lower risk, not risk-free.** Three residuals
remain and must be handled: assistant output quotes and is conditioned on user input, so the
classifier still processes a derivative of user content; the labels are sensitive derived
data per Section 2.2; and a per-message safety series is a behavioural record of one
identifiable user's sessions even when nobody else can read it.

### 2.5 One label class that must never touch user text

`speakleash/Bielik-Guard-*` emits **SELF-HARM** and **HATE**. On assistant output these are
content guardrails. On user text, SELF-HARM is a mental-health inference — precisely what
`PRIVACY.md:69` forbids — and HATE would build a record of a person's alleged hate speech.
Both heads must be **structurally dropped for user-authored text**, not merely unused.

### 2.6 Asymmetric harm

A wrong `prompt.constraint_precision` costs a mildly wrong hint; a wrong affect label tells a
person something untrue about their own state. The errors are not commensurable, so affect
does not inherit the default gate. Section 6.3 raises precision and defaults to abstention.

---

## 3. Baseline: what the existing cascade already shows

| Stage | Pinned checkpoint | Measured | Source |
|---|---|---|---|
| Scoped NLI | mDeBERTa-v3-base-xnli-2mil7 | 3-way accuracy 0.556; **different-scope FP 1.000** | `wp-11-local-candidates.md:129` |
| Fast NLI | multilingual-MiniLMv2-L6-mnli-xnli | accuracy 0.444; ECE 0.208; false-confident 0.111 | `p1-specialist-screen.md:121` |
| Deeper NLI | multilingual-MiniLMv2-L12-mnli-xnli | accuracy 0.556; ECE 0.311; false-confident 0.111 | `p1-specialist-screen.md:122` |
| Structured rubric | Qwen3-4B-Instruct-2507 | exact agreement 0.667; abstention F1 0.521; 10,791 ms/case; 7,770 MiB | `wp-11-local-candidates.md:130` |
| Retrieval | multilingual-e5-small / -base | top-1 0.667 / 0.833 vs BM25 0.583 | `wp-11-local-candidates.md:123-124` |

1. **No neural stage passes its own gate.** The ceiling is `maximum_ece = 0.05`
   (`gate_contracts.py:687`); measured NLI is 0.208 and 0.311.
2. **Scope handling is the demonstrated failure.** mDeBERTa marked 100% of different-scope
   negatives as contradictions, so any disagreement or stance feature built on entailment
   inherits that defect.
3. **The rubric stage is out of memory contract.** Its 7,770 MiB was measured "one model at a
   time on one **16 GB** CUDA device" (`wp-11-local-candidates.md:115`), against a supported
   target of 8 GB VRAM with a **per-child ceiling of 6,144 MiB peak VRAM and 8,192 MiB RSS**
   (`docs/live-metric-radar-pipeline.md:111-112`, sized to leave ~1.5 GiB headroom at `:114`;
   also fixed at 6,144 MiB in `docs/real-metrics-campaign-ledger.md:1062`). It exceeds that
   ceiling by ~1,626 MiB and has never been demonstrated within it.
4. **Size and recency were not reliable quality predictors.** L12 beat L6 on macro-F1 but was
   worse on Brier and ECE; E5-base beat E5-small and also beat larger BGE-M3 and
   Qwen3-Embedding on retrieval. The trade-offs were mixed, not monotonic with size.

---

## 4. Verified candidate register

Admission rules raise on violation (`src/prompt_enhancer/infrastructure/text_models/manifests.py`):
SPDX exactly `MIT` or `Apache-2.0` (`:91-92`); `.safetensors` only (`:93-94`); 40-character
commit hash (`:80-83`); tokenizer pinned to the same repo and commit (`:84-90`);
`trust_remote_code` raises if True (`:125-126`); `8 ≤ max_sequence_length ≤ 2048` (`:127-128`).

`ST` = safetensors present · `CC` = custom code / `auto_map` / `trust_remote_code` required ·
`G` = gated. Every candidate table carries both columns.

### 4.1 Emotion / affect

| Model ID | Revision | License | Base → base license | Params | ST | CC | G | Lang | Verdict |
|---|---|---|---|---:|---|---|---|---|---|
| `SamLowe/roberta-base-go_emotions` | `d75048347613a25d77de8cf6412eaae9fa7b26be` | mit | roberta-base → MIT | 124,667,678 | ✅ (+pickle) | no | no | **en** | offline-research |
| `cirimus/modernbert-base-go-emotions` | `690341c8744d225dfd7a1fddae23f541b362b487` | mit | `answerdotai/ModernBERT-base` → apache-2.0, **en-only** | 149,626,396 | ✅ only | no | no | **en** | offline-research |
| `nie3e/go-emotions-polish-gpt2-small-v0.0.1` | `5bd28027332095f8cb7d9e7a0fefa2ee33222417` | mit *(declared)* | `sdadas/polish-gpt2-small` → **lgpl** | 125,971,968 | ✅ | no | no | pl | **reject — base chain** |
| `nie3e/sentiment-polish-gpt2-small` | `0f42779ae7e0327b2f3bd25bc90e38b74cea40b9` | mit *(declared)* | same **lgpl** base; data PolEmo 2.0 `cc-by-sa-4.0` | 125,953,536 | ✅ | no | no | pl | **reject — base chain** |
| `yazoniak/twitter-emotion-pl-classifier` | `b1eb103b3c0c12d1d21dfc6205b83ab80cec3ac0` | **gpl-3.0** | `PKOBP/polish-roberta-8k` → apache-2.0 (gated) | 442,898,440 | ✅ | **YES** | no | pl | **reject — licence + remote code** |
| `tabularisai/multilingual-emotion-classification` | `a2b9b4d9640c53e84ab7abdd2a66146d3dafb10c` | **cc-by-nc-4.0** | xlm-roberta-base → MIT | 278,052,107 | ✅ | no | no | 23 incl. pl | **reject — noncommercial** |
| `tabularisai/multilingual-sentiment-analysis` | `eea032081f8d247b4303ef3565e7cec1b6f201c9` | **cc-by-nc-4.0** | distilbert-base-multilingual-cased | 135,328,517 | ✅ | no | no | 23 incl. pl | **reject — noncommercial** |
| `j-hartmann/emotion-english-distilroberta-base` | `0e1cd914e3d46199ed785853e12b57304e04178b` | **none** | distilroberta | — | ❌ pickle+TF | no | no | en | **reject — no licence, no safetensors** |

Both `tabularisai` models declare **synthetic** training data; neither publishes a source
dataset card, so the provenance record required by `AGENTS.md:20` cannot be completed.

#### Reported quality — two threshold regimes, kept distinct

| Model | Default 0.5 threshold | Per-label optimised thresholds |
|---|---|---|
| SamLowe | accuracy 0.474 · precision 0.575 · recall 0.396 · **F1 0.450** (card: an overall figure across all 28 labels, "more meaningful when measured per label") | unweighted P 0.542 · R 0.577 · **F1 0.541**; weighted P 0.572 · R 0.677 · **F1 0.611** |
| cirimus | **macro F1 0.500** · accuracy 0.971 | **macro F1 0.550** · accuracy 0.968; thresholds "tuned on F1" on the **training set** |
| nie3e PL | — | **macro F1 0.405–0.495** over a 0.3–0.9 sweep; Hamming accuracy 0.956–0.966 |

Per-label F1:

| Label | SamLowe @0.5 | SamLowe opt. | cirimus @0.5 | cirimus opt. |
|---|---:|---:|---:|---:|
| confusion | 0.463 | 0.470 | 0.458 | 0.474 |
| annoyance | 0.238 | 0.349 | 0.257 | 0.388 |
| disappointment | 0.302 | 0.390 | 0.211 | 0.387 |
| approval | 0.404 | 0.437 | 0.399 | 0.425 |
| curiosity | 0.428 | 0.568 | — | — |
| disapproval | 0.379 | 0.439 | — | — |
| realization | 0.220 | 0.266 | 0.213 | 0.280 |
| relief | 0.000 | 0.246 | 0.167 | 0.526 |
| grief | 0.000 | 0.333 | 0.000 | 0.444 |
| pride | 0.000 | 0.583 | — | — |
| neutral | 0.646 | 0.688 | — | — |
| gratitude | 0.919 | 0.922 | 0.929 | 0.924 |

The repository reserves expressed affect as "confusion, annoyance, disappointment,
satisfaction" (`docs/metrics-catalog.md:386`). Three findings:

- **"Satisfaction" has no GoEmotions label and is unmapped.** The taxonomy has no
  `satisfaction` class. Candidate proxies (approval, admiration, joy, relief) are different
  constructs, so one of the four reserved dimensions cannot be sourced from any GoEmotions
  checkpoint at all without first defining a mapping and validating it.
- **The three mappable labels reach F1 0.349–0.474 at each card's best published threshold.**
- **The largest tuned gain among target labels is disappointment, +0.176** (cirimus,
  0.211→0.387). Confusion moves +0.007/+0.016 and annoyance +0.111/+0.131. The much larger
  swings — relief +0.359, pride +0.583 — are on labels that are **not** target labels and are
  irrelevant to this decision.

**These are two architectures fine-tuned on the same dataset, not independent evidence.**
Both are GoEmotions checkpoints, sharing its Reddit corpus, its label taxonomy, its class
imbalance, and the labelling problems SamLowe's own card names ("labelling errors",
"ambiguity", "conflicts", "duplication"). Their agreement is therefore evidence about
GoEmotions, not two independent confirmations about affect detectability.

**What F1 does and does not establish.** F1 **does not identify either component** and cannot
prove or disprove an operating-point precision or recall gate: many precision/recall pairs
yield the same F1. It supports one weak bound — for F1 `f`, both precision and recall are at
least `f/(2-f)`, so `f = 0.39` implies each is ≥ 0.242 — which is far below the gates in
Section 6.3 and settles nothing. Whether a high-precision operating point with useful
coverage exists is **unmeasured**, and the tuned figures maximise F1, not precision. It must
be measured directly (Section 8).

Neither GoEmotions checkpoint reports **any calibration evidence** — no ECE, no reliability
curve — so neither can be assessed against `maximum_ece = 0.05` from its card.

Two further notes. The high "accuracy" figures (0.971/0.968; 0.956–0.966) are **per-label
Hamming accuracy over 28 sparse labels**, where always predicting negative scores ~0.96; they
are not evidence of capability. And `nie3e`'s Polish data is **machine-translated
GoEmotions** with **80% of neutral-only rows removed** before evaluation — a translated Reddit
corpus scored on a rebalanced distribution, with no per-label breakdown published.

`yazoniak/twitter-emotion-pl-classifier` is the only candidate found in this search that
ships calibration artefacts (`calibration_artifacts.json`,
`calibration_reliability_diagrams.png`, `predict_calibrated.py`) — real methodological merit,
rejected on two independent hard rules rather than on quality.

### 4.2 Toxicity / safety

| Model ID | Revision | License | Base → base license | Params | ST | CC | G | Lang | Verdict |
|---|---|---|---|---:|---|---|---|---|---|
| `speakleash/Bielik-Guard-0.1B-v1.1` | `8667df307bf9cdee6bce78919d10f8c18c2cf53e` | apache-2.0 | `sdadas/mmlw-roberta-base` → apache-2.0 | 124,446,725 | ✅ | no | **auto** | pl | **selective — gating is the open barrier** |
| `speakleash/Bielik-Guard-0.5B-v1.1` | `0cd4124d73d99de6dc4bbd41acca3f603a31c9ff` | apache-2.0 | `PKOBP/polish-roberta-8k` → apache-2.0 (gated) | 442,895,365 | ✅ | **YES** | **auto** | pl | **reject — remote code** |
| `unitary/toxic-bert` | `4d6c22e74ba2fdd26bc4f7238f50766b045a0d94` | apache-2.0 | bert-base-uncased → apache-2.0 | 109,487,366 | ✅ | no | no | **en** | **selective — EN counterpart** |
| `unitary/multilingual-toxic-xlm-roberta` | `4ad6f5c104d9ce813a1a2f33cac0c5b579ef6ee5` | apache-2.0 | xlm-roberta | — | ❌ pickle only | no | no | multi, **no pl** | **reject — pickle-only** |
| `textdetox/xlmr-large-toxicity-classifier` | `b9c7c563427c591fc318d91eb592381ae2fbde66` | **openrail++** | xlm-roberta-large *(card inconsistency)* | 278,045,186 | ✅ | no | no | en ru uk es de am ar zh hi — **no pl** | **reject — licence outside admission set** |

`Bielik-Guard-0.1B-v1.1` is the strongest candidate found in this search and the only one
with a documented multi-rater annotation design. Labels: HATE, VULGAR, SEX, CRIME, SELF-HARM,
as multi-label probabilities. Data (Sojka2): 6,885 unique Polish texts, **60,000+ ratings
from 1,500+ annotators**, 7–8 per text, from Polish LLM prompts and social media, balanced
~55% safe / 45% harmful. Publisher-reported on the Sojka test set: F1 micro 0.775, ROC AUC
micro 0.974; per-class F1 self-harm 0.886, sex 0.889, vulgar 0.742, crime 0.707, hate 0.628.
Per the card it does **not** detect disinformation or jailbreaking, and is Polish-only.

**The 0.63% figure must be quoted with its definition.** The card defines
`FPR (Global): FP/(TP+FP+TN+FN)` — a **global false-alert share over all evaluated cases**,
not the conventional false-positive rate `FP/(FP+TN)` over negatives only. On 3,000 user
prompts it reports precision `TP/(TP+FP)` = 77.65%, alert rate `(TP+FP)/(all)` = 2.83%, and
that global false-alert share = 0.63%. The conventional FPR is **not published** and is
larger than 0.63% by construction, since the denominator is smaller. Do not restate 0.63% as
"FPR".

**The 0.5B is better by its publisher's numbers and is still rejected.** Sojka v1.1a: F1
micro 0.791, ROC AUC micro 0.980; per-class F1 self-harm 0.879, sex 0.915, vulgar 0.750,
crime 0.716, hate 0.667. In the card's separate comparison on 3,000 random user prompts:
precision 75.28%, publisher-defined global false-alert share 0.73%, alert rate 2.97%. The card
states it "generally outperforms" the 0.1B, "particularly on the
augmented test set", citing HATE 0.667 vs 0.628 and SEX 0.915 vs 0.889. Caveats: the two
variants' figures come from differently named evaluation sets, so only the card's own paired
comparison is matched; and all of it is publisher-reported. The rejection is unrelated to
quality — the 0.5B is tagged `custom_code`, carries a config `auto_map` to
`configuration_roberta`/`modeling_roberta`, and its card requires `trust_remote_code=True`.
That is a hard stop at `manifests.py:125-126`. **Prefer the 0.1B because the 0.5B is
inadmissible, not because it is worse.**

The 0.1B's open barrier is `gated: "auto"`. The repository fetches allowlisted public files
with `token=False` (`wp-11-local-candidates.md:57-59`); a gated repository needs an
authenticated terms acceptance, which conflicts with the isolated-download design and the
credential boundary at `AGENTS.md:8`. Whether a documented, non-credential-bearing acceptance
is permissible is a governance decision this review cannot settle. The 0.5B's base is gated too.

### 4.3 Politeness / social tone

| Model ID | Revision | License | Base → base license | Params | ST | CC | G | Lang | Verdict |
|---|---|---|---|---:|---|---|---|---|---|
| `Intel/polite-guard` | `b302b4b49319b6c7fb79dda6607d53526ac3a022` | apache-2.0 | `google-bert/bert-base-uncased` → apache-2.0 | 109,485,316 | ✅ (+ONNX) | no | no | **en** | offline-research |
| `Genius1237/xlm-roberta-large-tydip` | `e339ef04fbb56567569d712c5759cc59317770a3` | mit | xlm-roberta-large → MIT | 559,892,996 | ✅ (+pickle) | no | no | en hi ko es ta fr vi ru af hu — **no pl** | offline-research |

Both clear every mechanical admission rule — which is not a quality finding and not a legal
clearance. `polite-guard`'s barriers are substantive: **synthetic** training data, so no
observed human-authored distribution backs it; customer-service domain; English-only. `tydip` is 560M with no
Polish. Per Section 9, politeness of a *person* is where a coaching tool becomes a manners
inspector; neither has a user-directed path here.

### 4.4 Dialogue acts

| Model ID | Revision | License | Params | ST | CC | G | Lang | Verdict |
|---|---|---|---:|---|---|---|---|---|
| `diwank/silicone-deberta-pair` | `405127a73ef60674b1780e053cd52e538bf7ba7d` | mit | — | ❌ pickle+TF | no | no | en | **reject — pickle-only** |

**No admissible small dialogue-act checkpoint was found in the searched slice.** The dataset
licences suggest why supply is thin:

| Dataset | License | Note |
|---|---|---|
| `li2017dailydialog/daily_dialog` | **cc-by-nc-sa-4.0** | **Noncommercial.** Source of the common 4-way act taxonomy |
| `eusip/silicone` | cc-by-sa-4.0 | Aggregate is BY-SA, but its `dyda_*` configs derive from DailyDialog, so the stricter NC term flows through |
| `google-research-datasets/go_emotions` | apache-2.0 | Clean; the GoEmotions family has no data-licence barrier |
| `clarin-pl/polemo2-official` | **cc-by-sa-4.0** | **Not noncommercial.** ShareAlike is a separate counsel question |
| `MoritzLaurer/multilingual-NLI-26lang-2mil7` | **not specified in cardData** | Includes `pl`; machine-translated from multi_nli, anli, fever, lingnli, WANLI |

**Do not import dialogue acts.** Strategy 1 obtains them from already-pinned NLI checkpoints
with no new weights, no pickle, and no NC exposure.

### 4.5 Rejected on construct

| Family | Reason |
|---|---|
| EPITOME empathy models | Construct is empathy in **peer mental-health support**; applying it to developer text is the inference `PRIVACY.md:69` forbids. Rejected on ethics before technical review |
| `cardiffnlp/twitter-roberta-base-stance-*` | Targets are SemEval-2016 political topics; no demonstrated transfer to code review |
| "frustration", "urgency", "engagement", "burnout" classifiers | **No validated public construct was found in this search** for developer frustration or urgency. HCI measures workload by self-report (NASA-TLX, in the repo bibliography), which is why `docs/metrics-catalog.md:390` says "never inferred". Reject the construct, not only the checkpoints |

### 4.6 Barriers, and the licence-chain rule

| Barrier | Candidates |
|---|---|
| **Custom code / `trust_remote_code`** | `yazoniak/twitter-emotion-pl-classifier`, **`speakleash/Bielik-Guard-0.5B-v1.1`** |
| **Pickle-only** | `unitary/multilingual-toxic-xlm-roberta`, `j-hartmann/emotion-english-distilroberta-base`, `diwank/silicone-deberta-pair` |
| **Noncommercial licence** | both `tabularisai` models (`cc-by-nc-4.0`); DailyDialog-derived work |
| **Missing licence** | `j-hartmann/emotion-english-distilroberta-base` |
| **Copyleft weight licence** | `yazoniak/twitter-emotion-pl-classifier` (`gpl-3.0`) |
| **Base-chain conflict** | both `nie3e` models — `mit` declared over an **`lgpl`** base |
| **Licence outside admission set** | `textdetox/xlmr-large-toxicity-classifier` (`openrail++`) |
| **Gated** | both `speakleash/Bielik-Guard-*`, `PKOBP/polish-roberta-8k` |
| **Synthetic-only data** | `Intel/polite-guard`, both `tabularisai` models |
| **English-only** | SamLowe, cirimus, `unitary/toxic-bert`, `Intel/polite-guard`, j-hartmann |
| **Out-of-domain corpus** | all of them; **no candidate in this register was trained or evaluated on coding-agent text** |

Two candidates are blocked by two independent hard rules each: `yazoniak` (`gpl-3.0` **and**
`custom_code`) and `Bielik-Guard-0.5B` (`custom_code` **and** gated). Only the 0.1B guard has
a single, potentially resolvable barrier.

**Licence-chain rule.** Every licence statement in this memo is a finding about **this
repository's admission policy** — the closed SPDX set at `manifests.py:91-92` plus the
provenance rule at `docs/research/model-shortlist.md:120-127`. Whether a licence actually
permits the intended distribution, whether copyleft attaches to model weights at all (an
unsettled question), and whether ShareAlike propagates from a training corpus to a fine-tuned
checkpoint are **questions for counsel**. The output is "admit / do not admit under current
policy", never "lawful / unlawful".

The validator checks only the **declared weight licence**, and two verified cases show the
gap: both `nie3e` models declare `mit` over an `lgpl` base and would pass every mechanical
rule; `yazoniak` declares `gpl-3.0` over an `apache-2.0` base. **Therefore** a manifest review
must record the base-model ID and licence and the training-dataset ID and licence as explicit
fields. Under current policy a copyleft or noncommercial base or dataset disqualifies a live
path even when the weight tag is permissive — a deliberately conservative posture counsel
could relax with a documented opinion. The **data** side proved mostly clean (GoEmotions
apache-2.0, PolEmo 2.0 cc-by-sa-4.0); the barriers that bit were base weights, remote code,
and gating.

---

## 5. EN/PL strategies

### 5.1 Strategy 1 — zero-shot interaction acts on already-pinned NLI checkpoints *(do first)*

Use `multilingual-MiniLMv2-L12-mnli-xnli` (464 MiB measured) with mDeBERTa-2mil7 as a second
configuration, scoring a **versioned, frozen hypothesis set** per message in EN and PL,
abstaining below threshold. Hypotheses state *observable acts*, never states — for example
"This message asks the reader for missing information." / "Ta wiadomość prosi odbiorcę o
brakujące informacje."; likewise for correction, disagreement, agreement, and explicit
priority.

Strengths: no new supply-chain surface; one model covers EN and PL; memory and latency
already measured; the abstention path, evaluator harness, and fixture-freeze discipline exist
(`scripts/evaluate_specialist_screen.py`); acts are genuinely observable.

Weaknesses: measured ECE 0.311 (L12) / 0.208 (L6) against a 0.05 gate. The hypothesis wording
*is* a prompt and must be versioned as a first-class artefact (`interaction-act-hypotheses-v1`)
with a fixture digest. **Polish has no published evaluation**: the dataset includes `pl` but
it was machine-translated, the card's XNLI table covers 15 languages and excludes Polish, and
its author states machine translation "reduces the quality of the data for a complex task like
NLI". Expect worse PL calibration and report it as a language slice. And mDeBERTa's
different-scope FP of 1.000 means disagreement and stance hypotheses must sit behind an
evaluated scope router, which does not exist (`p1-scope-router.md:100-106`,
`router_evaluated=false`).

### 5.2 Strategy 2 — calibrated probe over already-pinned multilingual embeddings *(candidate live path)*

Freeze `intfloat/multilingual-e5-small` — `mit`, revision
`614241f622f53c4eeff9890bdc4f31cfecc418b3`, **matching the pin already at `manifests.py:229`**,
card lists 101 languages including `pl`. Train a multinomial-logistic or single-hidden-layer
probe on the repository's own authored EN/PL labels, then calibrate with Platt or isotonic
scaling on a held-out split.

Established advantages: **language symmetry by construction** (E5 is multilingual and labels
are authored in both languages under one rubric, so Polish is not a translation artefact — the
only design here that could satisfy `required_languages == (EN, PL)` without importing a
corpus that omits or machine-translates Polish); **the taxonomy becomes the repository's own
versioned rubric**, avoiding both GoEmotions' Reddit label distribution and its unmapped
"satisfaction" gap; **directly calibratable**, since ECE, Brier, and reliability curves come
from the probe's own held-out split; and cheap deterministic inference — one 118M forward pass
plus a small matrix multiply.

**A probe is a trained model, not an explanation.** It creates new weights requiring full
provenance: coefficients, training split, seed, library versions, feature convention, and
label set must be versioned, digest-pinned, stored, and reproducibly rebuildable exactly like
a downloaded checkpoint (`AGENTS.md:20`). The supply-chain surface shrinks — no third-party
download, no external licence chain — but does not vanish, and a locally trained head can
memorise its training text, so it is itself sensitive derived data. Its coefficients over 384
anonymous embedding dimensions are **not interpretable**: they can be printed, but no
dimension has human meaning, so they do not explain why an input scored as it did. The real
benefits are narrower — a linear decision function is auditable for stability, cheap to re-fit
and diff across versions, and measurable for calibration on demand.

**Two claims here are hypotheses to test, not established facts.** That a frozen-embedding
probe needs *fewer* labels than fine-tuning is a plausible expectation from the reduced
parameter count, not a measured result for this task. That a frozen encoder *caps* achievable
accuracy below full fine-tuning is likewise an expectation; the size of any gap on
coding-agent text is unknown. Both should be measured on the Section 8 screen before either is
relied on for planning. E5's `query:`/`passage:` prefix convention must be applied
consistently and recorded in the algorithm version.

### 5.3 Strategy 3 — EN/PL assistant-output safety pair *(the one import worth negotiating)*

| Role | Model | Revision | Params |
|---|---|---|---:|
| EN assistant-text abuse | `unitary/toxic-bert` | `4d6c22e74ba2fdd26bc4f7238f50766b045a0d94` | 109,487,366 |
| PL assistant-text abuse | `speakleash/Bielik-Guard-0.1B-v1.1` | `8667df307bf9cdee6bce78919d10f8c18c2cf53e` | 124,446,725 |

Both Apache-2.0 on Apache-2.0 bases, both safetensors, neither requiring remote code. This is
the only place where importing weights buys a capability the pinned models cannot: a Polish
safety classifier built on 60,000+ human ratings. It maps onto exactly one proposed metric,
`safety.agent_response_abuse_event`, on assistant text only, with SELF-HARM and HATE
structurally dropped for user text (Section 2.5). The 0.5B is not an option — remote code.

Open barriers: Bielik-Guard is **gated**; the taxonomies differ (6 Jigsaw vs 5 Bielik
categories) so the languages are **not comparable** and must publish as separate slices, never
pooled; and both models were trained on public comment and social-media text, not on assistant
output, so applying them to model-generated text is itself a domain shift the Section 8 screen
must measure first.

### 5.4 Not recommended: English-only affect import with Polish abstention

At each card's best threshold the mappable target labels reach F1 0.349–0.474, "satisfaction"
has no label at all, neither model publishes calibration, both are Reddit-trained, and the
result would exist in English but not Polish — not comparable across the primary user's two
working languages and unable to pass `required_languages`. **Never machine-translate user
content** to reach a supported language: remote translation is egress, local translation
silently changes the object of measurement.

---

## 6. Gates

### 6.1 Inherited, non-negotiable

From `src/prompt_enhancer/application/estimators/gate_contracts.py`:

| Gate | Threshold | Line |
|---|---|---|
| Expected calibration error | ≤ 0.05 | `:687` |
| Human-agreement gap | ≤ 0.05 | `:686` |
| Repeat stability | ≥ 0.95 | `:688` |
| Active-learning label count | 100–200 | `:46-47`, `:673-678` |
| Holdout per metric / stratum / language | > 0 each | `:680-682` |
| Task strata | all four required | `:731-732` |
| Languages | **EN and PL both required** | `:733-734` |
| Subgroup dimensions | task_stratum, language, provider, evidence_tier | `:198-202`, `:701-703` |
| Preregistration + split freeze | required before evaluation | `real-metrics-campaign-ledger.md:153` |

The language gate is code, not policy — `required_languages` must equal
`tuple(CalibrationLanguage)`, which is exactly `(EN, PL)` (`:133-135`). **Every English-only
candidate — SamLowe, cirimus, `unitary/toxic-bert`, `Intel/polite-guard` — is individually
unable to pass the first release gate.** `unitary/toxic-bert` qualifies only as half of the
Section 5.3 pair, and then only as a language slice.

### 6.2 Gate 0 — construct validity, before any model is scored

The most important gate, and it involves no model. Demonstrate the label is observable from
redacted text alone: ≥ 2 independent raters on the same synthetic EN/PL window, blind to each
other; third-rater adjudication; **Krippendorff's α ≥ 0.67** per label, computed separately for
EN and PL; raters see **only the redacted window**, the same input the model gets. If agreement
requires raw text or out-of-band context, the metric cannot be computed on P1 data and must be
withdrawn rather than approximated.

A model cannot be more valid than its label. SamLowe's card attributes weak performance to
dataset "labelling errors", "ambiguity", "conflicts" and "duplication"; cirimus attributes its
weakest labels to scarcity and reports grief at F1 0.000 **at the default threshold** (0.444
once tuned — the label is learnable, the default operating point simply never fires). These are
at least partly label-quality and operating-point problems. The cards do not exclude an
architecture contribution, and architecture choice alone cannot establish construct validity.

### 6.3 Affect-specific additions

| Gate | Threshold | Rationale |
|---|---|---|
| Precision, `interaction.expressed_friction_language_rate` | ≥ 0.90, with ≥ 50 positive predictions | Asymmetric harm (Section 2.6) |
| Precision, `safety.agent_response_abuse_event` | ≥ 0.95 | A false abuse flag misdirects a real safety report |
| Recall floor, `safety.agent_response_abuse_event` | ≥ 0.80, reported separately | For a guardrail the *missed* event is the expensive error |
| Redaction invariance | ≥ 0.95 label agreement pre/post redaction | The model only ever sees redacted text |
| Stack-trace false-positive rate | ≤ 0.02 on the log/error slice | Predicted dominant failure mode (Section 8) |
| Identity-term subgroup bias | Borkan et al. subgroup AUC within `maximum_material_subgroup_regression` | Jigsaw-derived models have documented identity bias |
| PL/EN parity | PL not materially worse than EN on the `language` dimension | Otherwise publish EN-only with an explicit reason, never a pooled number |
| Quotation attribution | ≥ 0.95 on the quoted-text slice | Quoting an error or the agent's words is not expressing it |
| Abstention coverage | always reported with selective risk | Mirrors `docs/metrics-catalog.md:359` |

**What the cards establish about these gates: nothing dispositive.** No published figure in
Section 4 shows whether a candidate meets or misses a precision or recall gate, because the
cards report F1 for the affect labels and F1 does not identify either component. The GoEmotions,
`polite-guard`, and `unitary` cards publish no per-label precision/recall split at a usable
operating point. The one partial exception is `Bielik-Guard-0.1B-v1.1`, which reports precision
77.65% at a stated operating point — below the 0.95 gate, on out-of-domain data, with no
matching recall figure, so its recall standing is unknown. Measure the components directly.

**Contract gap:** `HighRiskPrecisionRule` (`gate_contracts.py:657-665`) carries
`minimum_precision` and `minimum_positive_predictions` but **has no recall field**, so the
safety recall floor cannot be expressed today. That is a required contract extension, not
something to approximate with the precision rule.

### 6.4 Publication state

Until every gate passes, an interaction signal publishes `value_origin = neural_uncalibrated`,
`basis = experimental` (`docs/metrics-catalog.md:567`), or `MetricValueStateV2.ABSTAINED` —
which should be the **default**. It may never publish `basis = measured`.
`PredictiveMetricState.CALIBRATED` (`probabilistic_metrics.py:74`) is unreachable until Gate 0
and all of 6.1–6.3 pass, in that order.

---

## 7. Optional metric contracts, separate from the twenty

### 7.1 Separation

Pack `experimental.redacted-text.interaction-signals` v0, registry
`interaction-signal-contracts-v0`, contract version `interaction-signal-contract-v0`, default
**disabled**. `docs/metrics-catalog.md:552` states the existing states "partition exactly
twenty metrics"; that must stay literally true, so these are counted nowhere in it. They also
need a workspace view outside the existing four (`probabilistic_metrics.py:101-104`) —
proposed `PRIVATE_COACHING`, never rendered in a shared or exported surface. That requires a
later code change; it is proposed here, not made.

### 7.2 Two contract fields that encode the boundary in types

```
subject_of_measurement ∈ { assistant_text, user_text, message_pair }
construct_class        ∈ { observable_language, dialogue_act, safety_event }
```

`construct_class` has **no member for inner state** — no `emotion`, `mood`,
`sentiment_of_person`, `personality`, or `wellbeing`. A contributor cannot express "this
metric measures how the user feels" because the type system has no word for it; the attempt
raises at construction, exactly as `trust_remote_code=True` raises (`manifests.py:125-126`).
Prose prohibitions decay across refactors; a closed enum does not. Every contract also carries
`export_policy = never_export`, `composite_eligibility = forbidden`,
`ranking_eligibility = forbidden`, and `visibility = self_only`.

### 7.3 Proposed contracts

All C-tier, P1, private, self-only, off by default, never exported, never composited.

| Key | Subject | Construct | Numerator / denominator | Lane |
|---|---|---|---|---|
| `safety.agent_response_abuse_event` | `assistant_text` | `safety_event` | assistant messages with an abuse candidate above the calibrated threshold / analyzed assistant messages | selective, highest priority |
| `interaction.agent_clarification_act_rate` | `assistant_text` | `dialogue_act` | assistant messages classified as clarification requests / analyzed assistant messages | selective |
| `interaction.agent_commitment_hedge_rate` | `assistant_text` | `observable_language` | assistant claims with hedging markers and no linked evidence / material assistant claims | offline-research |
| `interaction.user_correction_marker_rate` | `user_text` | `observable_language` | user messages with explicit correction markers / analyzed user messages | offline-research, challenger only |
| `interaction.scoped_disagreement_candidate_rate` | `message_pair` | `dialogue_act` | scope-compatible pairs with a disagreement candidate / scope-compatible comparable pairs | blocked on an evaluated scope router |
| `interaction.expressed_friction_language_rate` | `user_text` | `observable_language` | user messages with calibrated friction-language candidates / analyzed user messages | offline-research indefinitely |
| `interaction.signal_abstention_coverage` | n/a | n/a | abstained eligible judgments / eligible judgments | **mandatory whenever any row above is enabled** |

`interaction.user_correction_marker_rate` deliberately overlaps existing
`collaboration.rework_candidate_rate` v2 (`docs/metrics-catalog.md:182`); it must publish as a
**separate challenger**, never merged into or overwriting the v2 key — the V1 provenance gate
(`:522-530`) exists to prevent exactly that mixing. The name is
`expressed_friction_language_rate`, not `frustration`: the metric measures **language**. Every
row is sensitive derived data with the Section 2.2 duties.

**Prefer improving detectors over adding metrics.** A better clarification-act detector
improves `collaboration.clarification_yield` v2; a better correction detector improves
`collaboration.rework_candidate_rate` v2. That adds measurement quality without adding surface
area or exposure. The exception is `safety.agent_response_abuse_event`, a genuinely new
construct with no existing home.

---

## 8. Synthetic screen

Benchmark `interaction_signal_screen_v1`; generator `interaction-signal-corpus-generator-v1`;
evaluator `interaction-signal-evaluator-v1`; metrics `interaction-signal-metrics-v1`;
hypothesis artefact `interaction-act-hypotheses-v1`. Fixture digest reviewed and pinned, and
the script **refuses a changed fixture**. ≥ 96 effective preregistered cases, matching the
promotion target at `p1-scope-router.md:57` that the existing 24- and 30-case foundations
explicitly fail. Balanced across 4 task strata × {EN, PL} × label classes, fictional
identities and reserved example values only.

| Slice | Contents | Tests |
|---|---|---|
| Stack trace / log | messages dominated by `ERROR`, `FATAL`, `panic`, `failed`, non-zero exits | Predicted dominant failure: negativity models firing on error text. Gate ≤ 0.02 FP |
| Tone/content confound | a polite hard rejection; a blunt agreement | Tone is not read as disagreement, or vice versa |
| Quotation | user quoting an error string or the agent's earlier words | Quoted affect is not attributed to the speaker |
| Redaction artefact | identical text before and after masking paths, tokens, URLs | Label invariance to masking |
| PL diacritics | Polish with and without diacritics (`prosze` / `proszę`) | Tokenizer robustness on the PL slice |
| PL benign intensifiers | Polish colloquialisms unremarkable in engineering speech | PL false positives; Bielik-Guard has an explicit VULGAR head trained partly on social media |
| Subject symmetry | byte-identical text attributed to user and to assistant | `subject_of_measurement` routes, and the two score under different contracts |
| Code-only | a pure diff or code block, no prose | Should abstain, not score |
| Mixed / unknown language | EN+PL in one message, and neither | Must reduce coverage, never be relabelled to force a score (`docs/privacy-text-analysis.md:127-136`) |
| Threshold sweep | the same cases across a threshold range | How much apparent performance is threshold selection; among target labels the largest published tuned gain is disappointment +0.176 |
| Assistant-output domain shift | model-generated prose, including refusals and hedges | Both Strategy 3 models were trained on human comment text |

Report **precision and recall separately** — never F1 alone, since F1 does not identify either
component and the Section 6.3 gates are stated on the components — plus macro-F1, coverage,
selective risk at coverage levels, Brier, 10-bin ECE, false-confident error at 0.9, EN/PL and
task slices, redaction invariance, stack-trace FP, quotation attribution, peak VRAM against the
6,144 MiB ceiling, latency, and dependency versions. **Every operating point must name its
threshold**; a result quoted without one is not reproducible, which is exactly the ambiguity
that made the published GoEmotions numbers easy to misread.

Aggregate-only output: no text, case identifiers, logits, or per-case predictions
(`p1-specialist-screen.md:69-73`). Undefined quantities are typed `null`, never structural
zero. **Do not report Hamming accuracy** on multi-label affect. A synthetic pass is functional
screening only: rules, fixture, and labels would be authored by the same effort, so synthetic
success is not ground truth for promotion (`p1-scope-router.md:94-98`), and it cannot
substitute for Gate 0 or for a private, project- and time-separated calibration.

---

## 9. Resources against the 6,144 MiB ceiling

The governing budget is the **per-child ceiling of 6,144 MiB peak VRAM and 8,192 MiB RSS**
(`docs/live-metric-radar-pipeline.md:111-112`), not the raw 8 GB device size.

Measured anchors (`wp-11-local-candidates.md:120-130`, `p1-specialist-screen.md:118-122`), all
taken on **a 16 GB CUDA device**, so none demonstrates behaviour under the ceiling: MiniLMv2 L6
423 MiB / 194 ms, L12 464 / 33, E5-small 462 / 285, E5-base 1,078 / 453, mDeBERTa 1,122 / 461,
Qwen3-Embedding-0.6B 1,197 / 574, Qwen3-Reranker-0.6B 1,489 / 388, BGE-M3 2,180 / 432,
BGE-Reranker-v2-m3 2,194 / 236, **Qwen3-4B rubric 7,770 / 10,791**. One machine, confounded by
load order and warm-up; not a speed ranking.

| Candidate | Params | Expected peak | Status |
|---|---:|---|---|
| `unitary/toxic-bert` | 109,487,366 | ≈ 450 MiB est. | estimate below ceiling |
| `Intel/polite-guard` | 109,485,316 | ≈ 450 MiB est. | estimate below ceiling |
| `speakleash/Bielik-Guard-0.1B-v1.1` | 124,446,725 | ≈ 500 MiB est. | estimate below ceiling |
| `SamLowe/roberta-base-go_emotions` | 124,667,678 | ≈ 500 MiB est. | estimate below ceiling |
| `cirimus/modernbert-base-go-emotions` | 149,626,396 | ≈ 600 MiB est. | estimate below ceiling |
| `textdetox/xlmr-large-toxicity-classifier` | 278,045,186 | ≈ 1,120 MiB (mDeBERTa anchor) | estimate below ceiling |
| `speakleash/Bielik-Guard-0.5B-v1.1` | 442,895,365 | ≈ 1,800 MiB est. | estimate below ceiling; rejected for remote code |
| `Genius1237/xlm-roberta-large-tydip` | 559,892,996 | ≈ 2,250 MiB est. | estimate below ceiling |

**These are estimates extrapolated from the 278M → 1,122 MiB anchor. "Below the ceiling on
paper" is not a proven fit**: no candidate has been measured under an enforced 6,144 MiB VRAM
and 8,192 MiB RSS budget, and activation memory at the intended sequence length and batch size
is unverified. A candidate is within budget only after a ceiling-enforced run.

Rules. **(1)** Sequential only, unload between stages — the rubric stage alone already exceeds
the per-child ceiling, so nothing may share a process with it. **(2)** No interaction stage may
be co-resident with the rubric stage. **(3)** Target ≤ 1,300 MiB peak at 512 tokens, batch 8 —
a self-imposed band well under the ceiling, so an interaction stage never becomes the reason to
raise it; Strategies 1 and 2 measure 464 and 462 MiB, and the Strategy 3 pair is ≈ 450–500 MiB
estimated. **(4)** Prefer the 0.1B guard because the 0.5B is inadmissible, not because it is
worse; memory was never the deciding factor. **(5)** Cap `max_sequence_length` at 512 — affect
and act labels are per-message, and the validator's 2,048 allowance need not be approached.
**(6)** CPU fallback for a 110–150M encoder in fp32 is ≈ 0.5–0.6 GB against the 8,192 MiB RSS
ceiling; the Qwen-class rubric model is not a CPU option at acceptable latency.

**Latency.** The live window is 100 messages / 100,000 redacted characters
(`docs/metrics-catalog.md:157`, `docs/privacy-text-analysis.md:33`), so per-message cost
multiplies by up to 100: ~33 ms → ~3.3 s (acceptable); ~50 ms → ~5 s (acceptable); ~460 ms →
~46 s (poor); ~10,800 ms → ~18 min (not viable). Strategy 1 scores one hypothesis per act per
message, so a 5-act set at 33 ms is ~16 s per window — bound the act set and prefer
Strategy 2 for any live path.

---

## 10. Decision, unknowns, blockers

### 10.1 Decision

**Activate no affect model.** Both viable strategies run on checkpoints already pinned,
digest-verified, admission-cleared, and memory-anchored here. The bottleneck is not model
availability but **label validity and calibration**, which no import improves: at each card's
best published threshold the mappable target labels reach F1 0.349–0.474, "satisfaction" has no
GoEmotions label at all, the two checkpoints are two architectures on one shared dataset rather
than independent evidence, and neither publishes calibration.

1. Run the **Gate 0 inter-rater study** (Section 6.2) on a small authored EN/PL label set. If
   α < 0.67, stop and record the withdrawal.
2. Build `interaction_signal_screen_v1` (Section 8) and run **Strategy 1** on the already-pinned
   MiniLMv2 L12 and mDeBERTa configurations, under an enforced 6,144 MiB ceiling, reporting
   precision and recall separately. No new manifest.
3. If Gate 0 clears, build the **Strategy 2** probe over already-pinned
   `intfloat/multilingual-e5-small`, register its trained weights with full provenance, and
   measure ECE against 0.05 — testing the fewer-labels and capped-accuracy hypotheses rather
   than assuming them.
4. Separately resolve the **gating governance question** for `Bielik-Guard-0.1B-v1.1`.
5. Pursue `safety.agent_response_abuse_event` **as research under gates only**: assistant
   output, self-only, SELF-HARM and HATE dropped for user text, with consent, bounded
   retention, cascading deletion, and the Section 2.3 controller/DPIA question settled with
   counsel first.
6. Treat `interaction.expressed_friction_language_rate` as offline-research indefinitely.

The likeliest honest outcome remains **no affect activation**, with the category shipping as one
gated, self-only assistant-output safety guardrail plus improved deterministic detectors inside
the existing twenty. That is a good outcome, not a failure.

### 10.2 Remaining unknowns

| # | Unknown | Why |
|---|---|---|
| 1 | Per-file SHA-256 weight digests | Not exposed by the API; captured by the reviewed `--download` step |
| 2 | Polish accuracy of mDeBERTa-2mil7 | No Polish evaluation published; XNLI table excludes `pl`. Must be measured locally |
| 3 | `multilingual-NLI-26lang-2mil7` dataset licence | Not specified in cardData |
| 4 | Which MT system produced the Polish GoEmotions translation | Card says machine translation without naming the system |
| 5 | `textdetox` true backbone | Card says `xlm-roberta-large` but the index reports 278,045,186 params (base-sized). Moot — `openrail++` excludes it |
| 6 | Precision and recall at a usable operating point, for every affect candidate | Cards report F1, which does not identify either component. Only Bielik reports a precision figure (77.65%, out of domain, no recall) |
| 7 | Which split SamLowe's optimised thresholds were tuned on | Not stated. cirimus states the training set; SamLowe's is unstated, so selection optimism cannot be excluded |
| 8 | A validated mapping for "satisfaction" | No GoEmotions label exists; any proxy needs definition and validation |
| 9 | Whether the AI Act workplace prohibition reaches text-only affect analysis | Article 3(39) defines an emotion-recognition system through biometric data, defined at Article 3(34); applicability to text-only analysis remains unresolved (Section 2.3) |
| 10 | Whether self-only local use constitutes employer-controlled processing | Controller question, unsettled; determines whether a DPIA duty arises |
| 11 | In-domain performance of every candidate on coding-agent text | No public card evaluates this domain |
| 12 | Behaviour of any candidate under an enforced 6,144 MiB ceiling | All anchors were measured on a 16 GB device |
| 13 | Whether a better candidate exists outside the searched slice | Discovery was bounded (Section 1) |

### 10.3 Blockers

| # | Blocker | Effect |
|---|---|---|
| 1 | Construct validity unestablished | Gate 0 has never been run here; no affect metric has a defensible denominator |
| 2 | Target-label classification F1 is low at every published threshold | annoyance 0.349/0.388, disappointment 0.390/0.387, confusion 0.470/0.474 at best settings. Whether a high-precision point exists is **unmeasured**, not disproven |
| 3 | No affect checkpoint publishes calibration | `maximum_ece = 0.05` cannot be assessed from any card |
| 4 | Polish supervised affect is barrier-blocked in the searched slice | Every permissive Polish option is excluded by an LGPL base, GPL + remote code, noncommercial terms, remote code, or gating |
| 5 | `HighRiskPrecisionRule` cannot express a recall floor | The safety recall gate is unrepresentable; needs a contract extension |
| 6 | `MetricWorkspaceView` has no private-coaching value | The proposed pack has no compliant placement |
| 7 | Scope router oracle-gated and unevaluated | `interaction.scoped_disagreement_candidate_rate` is blocked |
| 8 | No neural stage passes ECE ≤ 0.05 | Plan for *no activation* as the realistic screen outcome |
| 9 | Rubric stage out of memory contract | 7,770 MiB measured on a 16 GB device against a 6,144 MiB ceiling |
| 10 | No retention policy, controller determination, or DPIA for interaction signals | Sensitive derived data with no defined retention, access model, or deletion-cascade test |

---

## 11. Sources

### Model cards at immutable revisions (retrieved 2026-08-17)

Links resolve the card at the exact revision used, so quoted figures cannot drift. Gated
repositories serve raw files only to authenticated clients; those rows were read from the
rendered card page and carry a repository-root link plus their revision.

- [`SamLowe/roberta-base-go_emotions` @ `d750483`](https://huggingface.co/SamLowe/roberta-base-go_emotions/blob/d75048347613a25d77de8cf6412eaae9fa7b26be/README.md)
- [`cirimus/modernbert-base-go-emotions` @ `690341c`](https://huggingface.co/cirimus/modernbert-base-go-emotions/blob/690341c8744d225dfd7a1fddae23f541b362b487/README.md)
- [`nie3e/go-emotions-polish-gpt2-small-v0.0.1` @ `5bd2802`](https://huggingface.co/nie3e/go-emotions-polish-gpt2-small-v0.0.1/blob/5bd28027332095f8cb7d9e7a0fefa2ee33222417/README.md)
- [`nie3e/sentiment-polish-gpt2-small` @ `0f42779`](https://huggingface.co/nie3e/sentiment-polish-gpt2-small/blob/0f42779ae7e0327b2f3bd25bc90e38b74cea40b9/README.md)
- [`yazoniak/twitter-emotion-pl-classifier` @ `b1eb103`](https://huggingface.co/yazoniak/twitter-emotion-pl-classifier/blob/b1eb103b3c0c12d1d21dfc6205b83ab80cec3ac0/README.md)
- [`tabularisai/multilingual-emotion-classification` @ `a2b9b4d`](https://huggingface.co/tabularisai/multilingual-emotion-classification/blob/a2b9b4d9640c53e84ab7abdd2a66146d3dafb10c/README.md)
- [`tabularisai/multilingual-sentiment-analysis` @ `eea0320`](https://huggingface.co/tabularisai/multilingual-sentiment-analysis/blob/eea032081f8d247b4303ef3565e7cec1b6f201c9/README.md)
- [`j-hartmann/emotion-english-distilroberta-base` @ `0e1cd91`](https://huggingface.co/j-hartmann/emotion-english-distilroberta-base/blob/0e1cd914e3d46199ed785853e12b57304e04178b/README.md)
- [`unitary/toxic-bert` @ `4d6c22e`](https://huggingface.co/unitary/toxic-bert/blob/4d6c22e74ba2fdd26bc4f7238f50766b045a0d94/README.md)
- [`unitary/multilingual-toxic-xlm-roberta` @ `4ad6f5c`](https://huggingface.co/unitary/multilingual-toxic-xlm-roberta/blob/4ad6f5c104d9ce813a1a2f33cac0c5b579ef6ee5/README.md)
- [`textdetox/xlmr-large-toxicity-classifier` @ `b9c7c56`](https://huggingface.co/textdetox/xlmr-large-toxicity-classifier/blob/b9c7c563427c591fc318d91eb592381ae2fbde66/README.md)
- [`Intel/polite-guard` @ `b302b4b`](https://huggingface.co/Intel/polite-guard/blob/b302b4b49319b6c7fb79dda6607d53526ac3a022/README.md)
- [`Genius1237/xlm-roberta-large-tydip` @ `e339ef0`](https://huggingface.co/Genius1237/xlm-roberta-large-tydip/blob/e339ef04fbb56567569d712c5759cc59317770a3/README.md)
- [`diwank/silicone-deberta-pair` @ `405127a`](https://huggingface.co/diwank/silicone-deberta-pair/blob/405127a73ef60674b1780e053cd52e538bf7ba7d/README.md)
- [`intfloat/multilingual-e5-small` @ `614241f`](https://huggingface.co/intfloat/multilingual-e5-small/tree/614241f622f53c4eeff9890bdc4f31cfecc418b3) — matches the pin at `manifests.py:229`
- [`speakleash/Bielik-Guard-0.1B-v1.1`](https://huggingface.co/speakleash/Bielik-Guard-0.1B-v1.1) — rev `8667df307bf9cdee6bce78919d10f8c18c2cf53e` (gated)
- [`speakleash/Bielik-Guard-0.5B-v1.1`](https://huggingface.co/speakleash/Bielik-Guard-0.5B-v1.1) — rev `0cd4124d73d99de6dc4bbd41acca3f603a31c9ff` (gated)
- [`MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7`](https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7) — repository pin `b5113eb38ab63efdd7f280f8c144ea8b13f978ce` (`manifests.py:257`)

### Base models (chain checks)

- [`answerdotai/ModernBERT-base` @ `8949b90`](https://huggingface.co/answerdotai/ModernBERT-base/tree/8949b909ec900327062f0ebf497f51aef5e6f0c8) — apache-2.0, English only
- [`sdadas/polish-gpt2-small` @ `c4daf60`](https://huggingface.co/sdadas/polish-gpt2-small/tree/c4daf60e7a839a62f2203c7784514aa9fbc45382) — **lgpl**
- [`sdadas/mmlw-roberta-base` @ `ba17139`](https://huggingface.co/sdadas/mmlw-roberta-base/tree/ba17139a1b0d4c422d253402556bbcfa5f14db8e) — apache-2.0
- [`PKOBP/polish-roberta-8k`](https://huggingface.co/PKOBP/polish-roberta-8k) — apache-2.0, gated, rev `ea444423540e1edd82c8f61e0f23eebe004fd9dd`

### Dataset cards

- [`google-research-datasets/go_emotions`](https://huggingface.co/datasets/google-research-datasets/go_emotions) — apache-2.0
- [`clarin-pl/polemo2-official`](https://huggingface.co/datasets/clarin-pl/polemo2-official) — cc-by-sa-4.0 (not noncommercial)
- [`li2017dailydialog/daily_dialog`](https://huggingface.co/datasets/li2017dailydialog/daily_dialog) — cc-by-nc-sa-4.0 (noncommercial)
- [`eusip/silicone`](https://huggingface.co/datasets/silicone) — cc-by-sa-4.0; `dyda_*` configs derive from DailyDialog
- [`MoritzLaurer/multilingual-NLI-26lang-2mil7`](https://huggingface.co/datasets/MoritzLaurer/multilingual-NLI-26lang-2mil7) — licence unstated; includes `pl`; machine-translated

### Legal and regulatory primary sources

- [Regulation (EU) 2024/1689 (AI Act), Official Journal via ELI](https://eur-lex.europa.eu/eli/reg/2024/1689/oj) — Article 3(34) directly defines biometric data; Article 3(39) defines emotion recognition; Article 5(1)(f) is the operative workplace/education prohibition; recitals 14, 18, and 44 provide interpretive context, including recital 14's direction to read biometric data in light of GDPR Article 4(14)
- [Regulation (EU) 2016/679 (GDPR), Official Journal via ELI](https://eur-lex.europa.eu/eli/reg/2016/679/oj) — Article 4(14) biometric data; Article 35 data protection impact assessment
- [EDPB — endorsed WP29 guidelines](https://www.edpb.europa.eu/our-work-tools/general-guidance/endorsed-wp29-guidelines_en) — the EDPB endorsement covering WP248 rev.01
- [Guidelines on Data Protection Impact Assessment (DPIA), WP248 rev.01](https://ec.europa.eu/newsroom/article29/items/611236) — high-risk criteria
- [Polish DPA Article 35(4) DPIA list, as published in Monitor Polski (via EDPB)](https://www.edpb.europa.eu/sites/default/files/decisions/pl-dpia-list_monitor_polski.pdf)

### Papers cited by the cards

- [GoEmotions (Demszky et al., 2020)](https://arxiv.org/abs/2005.00547) — the shared dataset behind all three GoEmotions checkpoints
- [ModernBERT (Warner et al., 2024)](https://arxiv.org/abs/2412.13663) — cirimus backbone
- [Automated Hate Speech Detection (Davidson et al., 2017)](https://arxiv.org/abs/1703.04009) — cited by both `unitary` models
- [Nuanced Metrics for Measuring Unintended Bias (Borkan et al., 2019)](https://arxiv.org/abs/1903.04561) — the subgroup-bias gate in Section 6.3

### Read first-hand in this worktree

`AGENTS.md`, `CLAUDE.md`, `PRIVACY.md`, `docs/metrics-catalog.md`,
`docs/live-metric-radar-pipeline.md`, `docs/model-manifests/wp-11-local-candidates.md`,
`docs/model-manifests/p1-specialist-screen.md`, `docs/model-manifests/p1-scope-router.md`,
`docs/privacy-text-analysis.md`, `docs/research/model-shortlist.md`,
`docs/research/research-journal.md`, `docs/real-metrics-campaign-ledger.md`,
`src/prompt_enhancer/infrastructure/text_models/manifests.py`,
`src/prompt_enhancer/application/estimators/gate_contracts.py`,
`src/prompt_enhancer/application/analysis/metric_contract_v2.py`,
`src/prompt_enhancer/application/analysis/probabilistic_metrics.py`.
