# Research journal: measuring and improving coding-agent work

Snapshot: 2026-08-06
Corpus: 131 verified primary publications across 12 themes
Method: [structured scoping review](methodology.md), not a formal meta-analysis

## Executive conclusion

The product should not attempt to measure “prompt accuracy” directly. Accuracy belongs to outcomes with ground truth; prompts have properties such as clarity, context, constraints, ambiguity, decomposition, and verifiability. A strong prompt can still fail because of model/tool/environment limits, while a weak prompt can succeed by luck or through extensive clarification.

The defensible system is layered:

1. **Outcome truth:** executable checks, artifacts, explicit user acceptance, reopen/revert/escaped-defect evidence.
2. **Process evidence:** time, tokens, tool outcomes, retries, edits, test/fix loops, compactions, approvals, handoffs.
3. **Specification evidence:** requirements, constraints, output contract, ambiguity, examples, acceptance criteria.
4. **Logic and flow:** claim/evidence links, scoped contradictions, entity/state continuity, requirement drift, plan revisions.
5. **Human factors:** optional private workload, trust, and friction observations.

No single publication supports a universal prompt/developer score. The literature instead supports multidimensional evaluation, calibrated uncertainty, task-specific validation, and human oversight.

## What the evidence changes in the product

### 1. Task success must be an evidence graph

SWE-bench, HumanEval/MBPP, EvalPlus, and behavioral testing all demonstrate that evaluation quality depends on executable and adversarial tests, not fluent completion claims. Repository-level work also requires context that function-level benchmarks omit. The system should extract requirements and link them to actions/artifacts and then to verification evidence. Missing evidence stays unknown.

Proposed task views:

```text
Request
  -> atomic requirements and constraints
  -> plan/decision nodes
  -> tool/edit/research actions
  -> test/build/lint/review/artifact evidence
  -> acceptance, reopen, revert, or unknown outcome
```

LLM judges may help with unevaluable dimensions, but judge research shows order, verbosity, style, self-preference, and rubric effects. Judges must cite evidence, allow abstention, be calibrated against humans/outcomes, and never override executable facts.

### 2. Prompt quality is a profile

Prompting research supports decomposition, examples, iterative refinement, and explicit reasoning/acting patterns in some tasks. It does not show that chain-of-thought or longer prompts universally improve coding-agent outcomes. Measure observable prompt features and later learn their conditional relationship to outcomes within task strata.

Recommended prompt dimensions:

- explicit goal and requested artifact;
- context availability and references;
- constraints and priority/tradeoffs;
- acceptance criteria and output contract;
- requirement atomicity and dependencies;
- ambiguity/unresolved references;
- examples/edge cases;
- safety/privacy boundaries;
- verifiability and assumption burden.

### 3. “Logic” should use interpretable components

Argument-mining and coherence work suggests separable features: claims, premises, support/attack relations, entity continuity, local semantic flow, and logical/rhetorical/dialectical quality. NLI can propose contradictions but is vulnerable to annotation artifacts and domain shift. A practical pipeline is:

1. extract typed claims/invariants;
2. attach time, branch, environment, speaker, authority, and modality;
3. resolve explicit supersession/last-write rules;
4. apply deterministic conflict checks;
5. run NLI only on unresolved candidates;
6. show both spans and allow dismissal.

A single opaque “logic score” would be less useful than a list of evidence-linked issues and coverage rates.

### 4. Dialogue metrics need domain calibration

USR, FED, GRADE, DynaEval, QuantiDCE, BERTScore, and BLEURT provide useful ideas but were not designed for conversations mixing code, shell output, tools, subagents, and compaction. They are challengers, not defaults. Requirement traceability, state consistency, verification flow, and repetition are more directly useful for engineering agents.

### 5. Sentiment is secondary

Emotion datasets can detect expressed affect, but Reddit/social/dialog datasets do not measure engineering competence or task correctness. Frustration should combine a calibrated text signal with observable friction: repeated correction, tool failures, retries, blocked time, or unresolved loops. It stays private and must not feed a team leaderboard or task-success score.

### 6. Longitudinal improvement needs statistics, not trend-line storytelling

EWMA/rolling medians are good visual summaries. PELT is useful for retrospective changes; BOCPD or ADWIN can flag online drift. GEE/mixed-effects or matched comparisons help with repeated measures. Every comparison must account for task type, complexity, repository, language, provider/model version, and metric/model-definition changes. A change point is not a cause.

### 7. Privacy remains after redaction

Text anonymization research shows that entity removal and differential privacy have utility and guarantee tradeoffs. Memorization/extraction work demonstrates why raw transcripts, fine-tuning data, embeddings, and summaries must be treated as sensitive. Deterministic secrets/PII first, contextual NER second, user preview, short retention, encryption, provenance, and deletion are required. Pseudonymization is not anonymization.

## Recommended algorithm stack

| Capability | MVP baseline | Challenger after benchmark | Decision rule |
|---|---|---|---|
| Outcome | Tests/build/lint/CI/artifact/acceptance events | Evidence-citing rubric judge | Objective evidence always wins |
| Event flow | Deterministic phases and directly-follows graph | PM4Py discovery/conformance | Use when event coverage is high |
| Search/similarity | FTS5/BM25, TF-IDF, char n-grams | MiniLM/E5/Qwen embedding + RRF | Require retrieval gain and latency budget |
| Requirement matching | Rules + BM25/cosine | Small cross-encoder reranker | Rerank a small candidate set |
| Contradiction | Typed invariants and temporal/scope rules | DeBERTa/mDeBERTa NLI | Calibrate, abstain, show spans |
| Topics | TF-IDF + NMF | BERTopic | Require seed stability and human labelability |
| Coherence | Entity/requirement continuity and repetition rules | Entity graph + embedding continuity | Interpret as candidate issue, not quality truth |
| PII/secrets | Regex, provider prefixes, entropy/checksums, Presidio | GLiNER challenger | Optimize leakage recall; preview over-redaction |
| Affect/friction | Failures/retries/corrections | Calibrated GoEmotions-family signal | Private exploratory view only |
| Summary | Extract decisions/actions/checks/entities/numbers | Small structured local generator | Require faithfulness/recall, preserve provenance |
| Judge | No default judge | Local/remote multidimensional rubric | Human anchors, order swaps, abstention |
| Trends | Task-stratified rolling median/EWMA | PELT, BOCPD/ADWIN, GEE/mixed effects | Show sample size and intervals |

The license-aware current implementation shortlist is maintained separately in [model-shortlist.md](model-shortlist.md).

## Improving delivery speed without degrading outcomes

### Product/runtime speed

- Parse and compute deterministic metrics incrementally.
- Cache inference by keyed content hash plus model, tokenizer, metric, redaction, and rubric revisions.
- Reuse one embedding for retrieval, novelty, matching, and topic features.
- Batch encoders; rerank only top candidates.
- Separate interactive queries from background NLP queues.
- Run generative judges only on sampled tasks, anomalies, disagreements, or weekly reviews.
- Build hierarchical summaries (message -> phase -> task -> week) with source IDs.
- Prefer quantized/local generation only after a small encoder/rule method fails the product need.

### User/task delivery speed

The dashboard should identify interventions, then evaluate them rather than issue generic prompting advice. Candidate interventions include:

- add observable acceptance criteria for bug/feature tasks;
- provide failing tests or error output early;
- state priority among speed, scope, safety, and compatibility;
- split research/design from implementation when the evidence graph shows oscillation;
- verify earlier when long untested edit sequences correlate with rework;
- use stable project instructions/templates for recurring constraints;
- reduce repeated context by referencing canonical artifacts;
- parallelize independent research/tests while preserving a shared decision record;
- compact only after authoritative state has been captured.

Evaluate interventions with randomized or matched within-task-type comparisons. Optimize verified outcomes per unit time/token, not tokens or cycle time alone.

## Proposed research program

### Dataset

- Begin with synthetic sessions covering success, failure, blocked work, compaction, forks/subagents, requirement changes, secrets/PII, and parser edge cases.
- Add consented personal sessions only after redaction/vault/deletion controls exist.
- Split train/calibration/test by user, repository/project, and time.
- Include English and Polish from the start, plus mixed code/log text.
- Double-label a subset and record annotator agreement.

### Initial hypotheses

1. Explicit acceptance criteria predict first-pass verification within bug/feature strata after controlling for complexity.
2. Earlier verification reduces edit churn and time in failing state for implementation tasks.
3. Requirement-to-evidence coverage predicts user acceptance better than prompt length, sentiment, or judge score.
4. Tool-failure/retry sequences explain friction better than generic sentiment models.
5. Task-stratified token efficiency is more stable and actionable than raw per-user token totals.
6. Deterministic + small-encoder models deliver most dashboard value; generative judges add value mainly for anomalies and qualitative review.

### Release gates for inferred metrics

- Published metric definition and failure modes.
- Representative held-out evaluation with task/language slices.
- Calibration and risk/coverage curve.
- Evidence spans and user dismissal/feedback path.
- Model/license/revision manifest.
- Drift detection and rollback to the deterministic baseline.
- Explicit prohibition on employee ranking where appropriate.

## Findings log

### 2026-08-06 — integration finding

Supported local interfaces exist for both providers, so raw cache scraping should not be the primary architecture. Codex app-server supports stored-thread listing/reading; Claude Agent SDK exposes local session-browser helpers. OpenTelemetry offers useful content-free operational events, although Claude telemetry can include identity/path attributes that must be stripped at ingress. Raw transcript decoders remain necessary only for compatibility/backfill gaps and must be version-gated.

### 2026-08-06 — database finding

SQLite is the best initial source of truth because the application needs transactions, migrations, deletion correctness, FTS5, and concurrent dashboard reads more than columnar scan speed. DuckDB/Parquet is a later disposable analytical layer. Raw content belongs in a separate encrypted vault, not an ordinary metrics table.

### 2026-08-06 — model finding

“SOTA sentiment” is the wrong starting target. The recommended bundle is deterministic metrics, FTS5/TF-IDF/NMF, small MiniLM/E5 embeddings, and Presidio/secret rules. NLI, BERTopic, affect, summaries, and rubric judges enter only after in-domain validation. License/provenance excludes several popular models from a safe public/commercial default.

### 2026-08-06 — governance finding

The same data that can coach an individual can become harmful surveillance in team views. Personal affect/workload stays local. Team aggregation should be content-free, cohort-suppressed, transparent, and multidimensional, with no individual leaderboard or developer-worth score.

## Publication map (131)

### 1. Prompting and prompt optimization (10)

1. Brown et al. (2020), [Language Models are Few-Shot Learners](https://arxiv.org/abs/2005.14165) — in-context and few-shot prompting.
2. Liu et al. (2021), [Pre-train, Prompt, and Predict: A Systematic Survey of Prompting Methods in NLP](https://arxiv.org/abs/2107.13586) — prompting taxonomy.
3. Wei et al. (2022), [Chain-of-Thought Prompting Elicits Reasoning in Large Language Models](https://arxiv.org/abs/2201.11903) — explicit reasoning traces.
4. Kojima et al. (2022), [Large Language Models are Zero-Shot Reasoners](https://arxiv.org/abs/2205.11916) — zero-shot chain of thought.
5. Wang et al. (2022), [Self-Consistency Improves Chain of Thought Reasoning in Language Models](https://arxiv.org/abs/2203.11171) — sampled reasoning-path agreement.
6. Zhou et al. (2022), [Least-to-Most Prompting Enables Complex Reasoning in Large Language Models](https://arxiv.org/abs/2205.10625) — problem decomposition.
7. Yao et al. (2022/2023), [ReAct: Synergizing Reasoning and Acting in Language Models](https://arxiv.org/abs/2210.03629) — reasoning/tool-action trajectories.
8. Yao et al. (2023), [Tree of Thoughts: Deliberate Problem Solving with Large Language Models](https://arxiv.org/abs/2305.10601) — explicit search over intermediate states.
9. Madaan et al. (2023), [Self-Refine: Iterative Refinement with Self-Feedback](https://arxiv.org/abs/2303.17651) — critique/revision loops.
10. Pryzant et al. (2023), [Automatic Prompt Optimization with “Gradient Descent” and Beam Search](https://arxiv.org/abs/2305.03495) — ProTeGi prompt optimization.

### 2. LLM evaluation, judges, factuality, and task success (11)

1. Liang et al. (2023), [Holistic Evaluation of Language Models](https://arxiv.org/abs/2211.09110) — HELM multi-metric evaluation.
2. Srivastava et al. (2022), [Beyond the Imitation Game](https://arxiv.org/abs/2206.04615) — BIG-bench.
3. Hendrycks et al. (2021), [Measuring Massive Multitask Language Understanding](https://arxiv.org/abs/2009.03300) — MMLU.
4. Zheng et al. (2023), [Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena](https://arxiv.org/abs/2306.05685) — judge reliability and bias.
5. Chiang et al. (2024), [Chatbot Arena: An Open Platform for Evaluating LLMs by Human Preference](https://arxiv.org/abs/2403.04132) — pairwise preference evaluation.
6. Liu et al. (2023), [G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment](https://arxiv.org/abs/2303.16634) — rubric-based LLM judging.
7. Lin et al. (2022), [TruthfulQA: Measuring How Models Mimic Human Falsehoods](https://arxiv.org/abs/2109.07958) — truthfulness.
8. Manakul et al. (2023), [SelfCheckGPT](https://arxiv.org/abs/2303.08896) — sampling-based hallucination detection.
9. Min et al. (2023), [FActScore](https://arxiv.org/abs/2305.14251) — atomic factual precision.
10. Es et al. (2023), [Ragas: Automated Evaluation of Retrieval Augmented Generation](https://arxiv.org/abs/2309.15217) — faithfulness and context relevance.
11. Ribeiro et al. (2020), [Beyond Accuracy: Behavioral Testing of NLP Models with CheckList](https://arxiv.org/abs/2005.04118) — capability-oriented behavioral tests.

### 3. AI-assisted software engineering and productivity (11)

1. Chen et al. (2021), [Evaluating Large Language Models Trained on Code](https://arxiv.org/abs/2107.03374) — HumanEval, pass@k, and Codex.
2. Austin et al. (2021), [Program Synthesis with Large Language Models](https://arxiv.org/abs/2108.07732) — MBPP and human feedback.
3. Peng et al. (2023), [The Impact of AI on Developer Productivity: Evidence from GitHub Copilot](https://arxiv.org/abs/2302.06590) — controlled productivity evidence.
4. Vaithilingam et al. (2022), [Expectation vs. Experience](https://doi.org/10.1145/3491101.3519665) — completion time, success, and debugging burden.
5. Ziegler et al. (2022), [Productivity Assessment of Neural Code Completion](https://arxiv.org/abs/2205.06537) — acceptance and persistence metrics.
6. Barke et al. (2023), [Grounded Copilot](https://arxiv.org/abs/2206.15000) — acceleration versus exploration behavior.
7. Pearce et al. (2022), [Asleep at the Keyboard?](https://arxiv.org/abs/2108.09293) — security of generated code.
8. Perry et al. (2022), [Do Users Write More Insecure Code with AI Assistants?](https://arxiv.org/abs/2211.03622) — human/assistant security interaction.
9. Sandoval et al. (2023), [Lost at C](https://www.usenix.org/conference/usenixsecurity23/presentation/sandoval) — controlled secure-coding study.
10. Jimenez et al. (2024), [SWE-bench: Can Language Models Resolve Real-World GitHub Issues?](https://arxiv.org/abs/2310.06770) — repository-level completion.
11. Liu et al. (2023), [Is Your Code Generated by ChatGPT Really Correct?](https://arxiv.org/abs/2305.01210) — EvalPlus and stronger functional tests.

### 4. Dialogue and generated-text quality (11)

1. Mehri and Eskenazi (2020), [USR](https://aclanthology.org/2020.acl-main.64/) — unsupervised, reference-free, multi-facet dialogue evaluation.
2. Lowe et al. (2017), [Towards an Automatic Turing Test](https://aclanthology.org/P17-1103/) — ADEM.
3. Mehri and Eskenazi (2020), [Unsupervised Evaluation of Interactive Dialog with DialoGPT](https://aclanthology.org/2020.sigdial-1.28/) — FED.
4. Huang et al. (2020), [GRADE](https://aclanthology.org/2020.emnlp-main.742/) — graph-enhanced dialogue coherence.
5. Zhang et al. (2021), [DynaEval: Unifying Turn and Dialogue Level Evaluation](https://aclanthology.org/2021.acl-long.441/) — dynamic graph evaluation.
6. Ye et al. (2021), [Towards Quantifiable Dialogue Coherence Evaluation](https://aclanthology.org/2021.acl-long.211/) — QuantiDCE.
7. Finch and Choi (2020), [Towards Unified Dialogue System Evaluation](https://aclanthology.org/2020.sigdial-1.29/) — evaluation dimensions and protocols.
8. Yeh et al. (2021), [A Comprehensive Assessment of Dialog Evaluation Metrics](https://arxiv.org/abs/2106.03706) — robustness comparison.
9. Sai et al. (2020), [Improving Dialog Evaluation with a Multi-reference Adversarial Dataset](https://aclanthology.org/2020.tacl-1.52/) — DailyDialog++.
10. Zhang et al. (2020), [BERTScore](https://arxiv.org/abs/1904.09675) — contextual token matching.
11. Sellam et al. (2020), [BLEURT](https://arxiv.org/abs/2004.04696) — learned human-judgment metric.

### 5. Logic, argumentation, and coherence (10)

1. Barzilay and Lapata (2008), [Modeling Local Coherence: An Entity-Based Approach](https://aclanthology.org/J08-1001/) — entity-grid coherence.
2. Mesgar and Strube (2018), [A Neural Local Coherence Model for Text Quality Assessment](https://aclanthology.org/D18-1464/) — adjacent-sentence semantic flow.
3. Jeon and Strube (2022), [Entity-based Neural Local Coherence Modeling](https://aclanthology.org/2022.acl-long.537/) — explainable entity-centered coherence.
4. Wachsmuth et al. (2017), [Computational Argumentation Quality Assessment in Natural Language](https://aclanthology.org/E17-1017/) — logical, rhetorical, and dialectical dimensions.
5. Stab and Gurevych (2017), [Parsing Argumentation Structures in Persuasive Essays](https://aclanthology.org/J17-3005/) — claim/premise/relation extraction.
6. Persing and Ng (2015), [Modeling Argument Strength in Student Essays](https://aclanthology.org/P15-1053/) — argument-strength prediction.
7. Habernal and Gurevych (2016), [What Makes a Convincing Argument?](https://aclanthology.org/D16-1129/) — empirical convincingness attributes.
8. Clark et al. (2020), [Transformers as Soft Reasoners over Language](https://arxiv.org/abs/2002.05867) — RuleTaker.
9. Tafjord et al. (2020), [ProofWriter](https://arxiv.org/abs/2012.13048) — implications and proof generation.
10. Han et al. (2022), [FOLIO: Natural Language Reasoning with First-Order Logic](https://arxiv.org/abs/2209.00840) — formal-logic evaluation.

### 6. Sentiment, emotion, empathy, toxicity, and abuse (12)

1. Pang et al. (2002), [Thumbs up? Sentiment Classification using Machine Learning Techniques](https://aclanthology.org/W02-1011/) — foundational sentiment classification.
2. Socher et al. (2013), [Recursive Deep Models for Semantic Compositionality Over a Sentiment Treebank](https://aclanthology.org/D13-1170/) — SST and compositional sentiment.
3. Demszky et al. (2020), [GoEmotions](https://arxiv.org/abs/2005.00547) — 27 fine-grained emotions.
4. Barbieri et al. (2020), [TweetEval](https://arxiv.org/abs/2010.12421) — unified social-text classification.
5. Rashkin et al. (2019), [Towards Empathetic Open-domain Conversation Models](https://arxiv.org/abs/1811.00207) — empathy benchmark.
6. Chen et al. (2018), [EmotionLines](https://arxiv.org/abs/1802.08379) — emotions in multi-party conversations.
7. Poria et al. (2019), [MELD](https://arxiv.org/abs/1810.02508) — multimodal conversation emotion.
8. Ghosal et al. (2019), [DialogueGCN](https://arxiv.org/abs/1908.11540) — speaker/context graph emotion recognition.
9. Davidson et al. (2017), [Automated Hate Speech Detection and the Problem of Offensive Language](https://arxiv.org/abs/1703.04009) — hate/offense distinction.
10. Borkan et al. (2019), [Nuanced Metrics for Measuring Unintended Bias](https://arxiv.org/abs/1903.04561) — subgroup toxicity bias.
11. Gehman et al. (2020), [RealToxicityPrompts](https://arxiv.org/abs/2009.11462) — toxic degeneration.
12. Hartvigsen et al. (2022), [ToxiGen](https://arxiv.org/abs/2203.09509) — adversarial implicit hate.

### 7. Embeddings, clustering, and topic modeling (12)

1. Mikolov et al. (2013), [Efficient Estimation of Word Representations in Vector Space](https://arxiv.org/abs/1301.3781) — word2vec.
2. Pennington et al. (2014), [GloVe](https://aclanthology.org/D14-1162/) — global co-occurrence embeddings.
3. Reimers and Gurevych (2019), [Sentence-BERT](https://arxiv.org/abs/1908.10084) — efficient semantic similarity.
4. Gao et al. (2021), [SimCSE](https://arxiv.org/abs/2104.08821) — contrastive sentence embeddings.
5. Wang et al. (2022), [Text Embeddings by Weakly-Supervised Contrastive Pre-training](https://arxiv.org/abs/2212.03533) — E5.
6. Su et al. (2022), [One Embedder, Any Task](https://arxiv.org/abs/2212.09741) — INSTRUCTOR.
7. Blei et al. (2003), [Latent Dirichlet Allocation](https://www.jmlr.org/papers/v3/blei03a.html) — probabilistic topic modeling.
8. Grootendorst (2022), [BERTopic](https://arxiv.org/abs/2203.05794) — embeddings, clustering, and class-based TF-IDF.
9. Angelov (2020), [Top2Vec](https://arxiv.org/abs/2008.09470) — joint topic/document embedding.
10. McInnes et al. (2018), [UMAP](https://arxiv.org/abs/1802.03426) — nonlinear projection.
11. McInnes et al. (2017), [hdbscan: Hierarchical Density Based Clustering](https://doi.org/10.21105/joss.00205) — variable-density clustering and noise handling.
12. Bianchi et al. (2020), [Pre-training is a Hot Topic](https://arxiv.org/abs/2004.03974) — contextualized topic models.

### 8. Uncertainty, confidence calibration, and abstention (11)

1. Guo et al. (2017), [On Calibration of Modern Neural Networks](https://arxiv.org/abs/1706.04599) — temperature scaling and ECE.
2. Lakshminarayanan et al. (2017), [Simple and Scalable Predictive Uncertainty Estimation using Deep Ensembles](https://arxiv.org/abs/1612.01474) — ensemble uncertainty.
3. Ovadia et al. (2019), [Can You Trust Your Model’s Uncertainty?](https://arxiv.org/abs/1906.02530) — calibration under shift.
4. Jiang et al. (2021), [How Can We Know When Language Models Know?](https://arxiv.org/abs/2012.00955) — QA calibration.
5. Kadavath et al. (2022), [Language Models (Mostly) Know What They Know](https://arxiv.org/abs/2207.05221) — self-evaluated correctness.
6. Lin et al. (2022), [Teaching Models to Express Their Uncertainty in Words](https://arxiv.org/abs/2205.14334) — linguistic calibration.
7. Kuhn et al. (2023), [Semantic Uncertainty](https://arxiv.org/abs/2302.09664) — meaning-level entropy.
8. Xiong et al. (2023), [Can LLMs Express Their Uncertainty?](https://arxiv.org/abs/2306.13063) — elicitation comparison.
9. Tian et al. (2023), [Just Ask for Calibration](https://arxiv.org/abs/2305.14975) — calibrated verbal/numeric confidence.
10. Zhao et al. (2021), [Calibrate Before Use](https://arxiv.org/abs/2102.09690) — contextual calibration for few-shot models.
11. Angelopoulos and Bates (2021), [A Gentle Introduction to Conformal Prediction](https://arxiv.org/abs/2107.07511) — distribution-free coverage and abstention.

### 9. Privacy, PII anonymization, memorization, and differential privacy (11)

1. Dwork et al. (2006), [Calibrating Noise to Sensitivity in Private Data Analysis](https://doi.org/10.1007/11681878_14) — foundational differential privacy.
2. Abadi et al. (2016), [Deep Learning with Differential Privacy](https://arxiv.org/abs/1607.00133) — DP-SGD.
3. Carlini et al. (2019), [The Secret Sharer](https://arxiv.org/abs/1802.08232) — exposure and unintended memorization.
4. Carlini et al. (2021), [Extracting Training Data from Large Language Models](https://arxiv.org/abs/2012.07805) — practical extraction of PII.
5. Nasr et al. (2023), [Scalable Extraction of Training Data from Production Language Models](https://arxiv.org/abs/2311.17035) — production-scale extraction.
6. Shokri et al. (2017), [Membership Inference Attacks against Machine Learning Models](https://arxiv.org/abs/1610.05820) — membership inference.
7. Kandpal et al. (2022), [Deduplicating Training Data Mitigates Privacy Risks in Language Models](https://arxiv.org/abs/2202.06539) — memorization reduction.
8. Lison et al. (2021), [Anonymisation Models for Text Data](https://aclanthology.org/2021.acl-long.323/) — privacy/utility and inference risks.
9. Pilán et al. (2022), [The Text Anonymization Benchmark](https://aclanthology.org/2022.cl-4.19/) — entity-level privacy-oriented metrics.
10. Habernal (2021), [When Differential Privacy Meets NLP: The Devil Is in the Detail](https://aclanthology.org/2021.emnlp-main.114/) — formal-guarantee pitfalls.
11. Yu et al. (2022), [Differentially Private Fine-tuning of Language Models](https://openreview.net/forum?id=Q42f0dfjECO) — private parameter-efficient adaptation.

### 10. Local and efficient inference (11)

1. Dettmers et al. (2022), [LLM.int8()](https://arxiv.org/abs/2208.07339) — mixed 8-bit inference.
2. Dettmers et al. (2023), [QLoRA](https://arxiv.org/abs/2305.14314) — NF4 and quantized fine-tuning.
3. Frantar et al. (2023), [GPTQ](https://arxiv.org/abs/2210.17323) — post-training weight quantization.
4. Lin et al. (2023), [AWQ](https://arxiv.org/abs/2306.00978) — activation-aware quantization.
5. Xiao et al. (2023), [SmoothQuant](https://arxiv.org/abs/2211.10438) — weight/activation quantization.
6. Sanh et al. (2019), [DistilBERT](https://arxiv.org/abs/1910.01108) — encoder distillation.
7. Jiao et al. (2019), [TinyBERT](https://arxiv.org/abs/1909.10351) — transformer distillation.
8. Dao et al. (2022), [FlashAttention](https://arxiv.org/abs/2205.14135) — IO-aware exact attention.
9. Kwon et al. (2023), [Efficient Memory Management for LLM Serving with PagedAttention](https://arxiv.org/abs/2309.06180) — vLLM.
10. Leviathan et al. (2022), [Fast Inference from Transformers via Speculative Decoding](https://arxiv.org/abs/2211.17192) — draft/verify decoding.
11. Hu et al. (2021), [LoRA](https://arxiv.org/abs/2106.09685) — parameter-efficient adaptation.

### 11. Longitudinal analytics, change detection, and process mining (11)

1. Page (1954), [Continuous Inspection Schemes](https://academic.oup.com/biomet/article-abstract/41/1-2/100/456627) — CUSUM.
2. Adams and MacKay (2007), [Bayesian Online Changepoint Detection](https://arxiv.org/abs/0710.3742) — online run-length inference.
3. Killick et al. (2012), [Optimal Detection of Changepoints with a Linear Computational Cost](https://arxiv.org/abs/1101.1438) — PELT.
4. Matteson and James (2014), [A Nonparametric Approach for Multiple Change Point Analysis](https://arxiv.org/abs/1306.4933) — multivariate E-divisive detection.
5. Truong et al. (2018), [ruptures: Change Point Detection in Python](https://arxiv.org/abs/1801.00826) — practical offline segmentation.
6. Gama et al. (2014), [A Survey on Concept Drift Adaptation](https://doi.org/10.1145/2523813) — drift taxonomy and evaluation.
7. Bifet and Gavaldà (2007), [Learning from Time-Changing Data with Adaptive Windowing](https://doi.org/10.1137/1.9781611972771.42) — ADWIN.
8. Berti et al. (2019), [Process Mining for Python: Bridging the Gap Between Process and Data Science](https://arxiv.org/abs/1905.06169) — PM4Py.
9. Berti et al. (2023), [PM4Py: A Process Mining Library for Python](https://doi.org/10.1016/j.simpa.2023.100556) — maintained process-mining toolkit.
10. van der Aalst (2016), [Process Mining: Data Science in Action](https://link.springer.com/book/10.1007/978-3-662-49851-4) — discovery, conformance, and enhancement.
11. Liang and Zeger (1986), [Longitudinal Data Analysis using Generalized Linear Models](https://doi.org/10.1093/biomet/73.1.13) — repeated-measure GEE.

### 12. Human factors, trust, workload, and broad productivity (10)

1. Amershi et al. (2019), [Guidelines for Human-AI Interaction](https://doi.org/10.1145/3290605.3300233) — 18 validated interaction guidelines.
2. Lee and See (2004), [Trust in Automation: Designing for Appropriate Reliance](https://pubmed.ncbi.nlm.nih.gov/15151155/) — trust calibration.
3. Hoff and Bashir (2015), [Trust in Automation](https://pubmed.ncbi.nlm.nih.gov/25875432/) — systematic trust model.
4. Zhang et al. (2020), [Effect of Confidence and Explanation on Accuracy and Trust Calibration](https://doi.org/10.1145/3351095.3372852) — confidence versus explanation.
5. Buçinca et al. (2021), [To Trust or to Think](https://arxiv.org/abs/2102.09692) — cognitive forcing against overreliance.
6. Bansal et al. (2019), [Beyond Accuracy: The Role of Mental Models in Human-AI Team Performance](https://www.microsoft.com/en-us/research/publication/beyond-accuracy-the-role-of-mental-models-in-human-ai-team-performance/) — error-boundary understanding.
7. Hart and Staveland (1988), [Development of NASA-TLX](https://humansystems.arc.nasa.gov/publications/Hart_Staveland_ORIGINAL_1.pdf) — multidimensional workload.
8. Davis (1989), [Perceived Usefulness, Perceived Ease of Use, and User Acceptance](https://doi.org/10.2307/249008) — Technology Acceptance Model.
9. Noy and Zhang (2023), [Experimental Evidence on the Productivity Effects of Generative Artificial Intelligence](https://doi.org/10.1126/science.adh2586) — controlled knowledge-work productivity.
10. Brynjolfsson et al. (2023), [Generative AI at Work](https://www.nber.org/papers/w31161) — deployment-scale productivity and learning.

## Research cautions to carry into implementation

- Do not infer prompt quality from sentiment.
- Do not infer task success from a completed provider turn.
- Do not compare raw tokens or time across unlike tasks.
- Do not treat benchmark rank as local-domain fitness.
- Do not present classifier probabilities as objective facts without calibration.
- Do not erase uncertainty or unknown coverage.
- Do not claim causality from a dashboard trend.
- Do not publish employee rankings or infer intelligence/personality.
- Do not assume redacted or embedded text is anonymous.
- Do not send content to a remote judge by default.
