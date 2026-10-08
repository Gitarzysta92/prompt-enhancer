"""Versioned, content-free research catalog for local text analytics.

The catalog is product metadata. Reading it never reads a provider, a session,
or a model cache. Candidate models are deliberately disabled until a pinned
local evaluator and a private calibrated holdout both pass their release gates.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from types import MappingProxyType
from typing import Mapping


CATALOG_KEY = "text-analysis-methods"
CATALOG_VERSION = 4
CATALOG_REVIEWED_ON = "2026-08-12"


class ResearchMaturity(StrEnum):
    PRODUCT_BASELINE = "product_baseline"
    EVALUATED_EXPLORATORY = "evaluated_exploratory"
    RESEARCH_CANDIDATE = "research_candidate"
    FAILED_GATE = "failed_gate"


class ModelCandidateStatus(StrEnum):
    EVALUATED_EXPLORATORY = "evaluated_exploratory"
    RESEARCH_SHORTLIST = "research_shortlist"
    REJECTED_SCREEN = "rejected_screen"


class MetricRoadmapState(StrEnum):
    BASELINE_AVAILABLE = "baseline_available"
    RESEARCH = "research"
    NEEDS_OBJECTIVE_EVIDENCE = "needs_objective_evidence"


class ScoreDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    CONTEXTUAL = "contextual"


@dataclass(frozen=True, slots=True)
class ResearchSource:
    key: str
    title: str
    url: str
    kind: str


@dataclass(frozen=True, slots=True)
class AnalysisMethod:
    key: str
    name: str
    family: str
    approach: str
    maturity: ResearchMaturity
    privacy_tier: str
    purpose: str
    produces: tuple[str, ...]
    candidate_model_keys: tuple[str, ...]
    source_keys: tuple[str, ...]
    limitations: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ModelBenchmark:
    benchmark_key: str
    case_count: int
    primary_metric: str
    primary_value: float
    secondary_metric: str | None = None
    secondary_value: float | None = None
    critical_metric: str | None = None
    critical_value: float | None = None


@dataclass(frozen=True, slots=True)
class ModelCandidate:
    key: str
    display_name: str
    repository_id: str
    task: str
    license_spdx: str
    revision: str | None
    parameter_scale: str
    language_scope: str
    status: ModelCandidateStatus
    product_enabled: bool
    trust_remote_code: bool
    decision: str
    benchmark: ModelBenchmark | None
    source_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class MetricRoadmapItem:
    key: str
    name: str
    profile: str
    question: str
    direction: ScoreDirection
    state: MetricRoadmapState
    evidence: str
    method_keys: tuple[str, ...]
    caution: str


SOURCES: tuple[ResearchSource, ...] = (
    ResearchSource(
        "rope",
        "Requirement-Oriented Prompt Engineering",
        "https://arxiv.org/abs/2409.08775",
        "paper",
    ),
    ResearchSource(
        "dialogue_acts",
        "ISO-standard domain-independent dialogue act tagging",
        "https://aclanthology.org/C18-1300/",
        "paper",
    ),
    ResearchSource(
        "clarification",
        "Asking the Right Question at the Right Time",
        "https://aclanthology.org/2024.eacl-long.16/",
        "paper",
    ),
    ResearchSource(
        "llm_rubric",
        "LLM-Rubric: a multidimensional calibrated approach",
        "https://aclanthology.org/2024.acl-long.745/",
        "paper",
    ),
    ResearchSource(
        "selective_prediction",
        "The Art of Abstention",
        "https://aclanthology.org/2021.acl-long.84/",
        "paper",
    ),
    ResearchSource(
        "e5_paper",
        "Multilingual E5 text embeddings",
        "https://arxiv.org/abs/2402.05672",
        "paper",
    ),
    ResearchSource(
        "e5_model",
        "multilingual-e5-small model card",
        "https://huggingface.co/intfloat/multilingual-e5-small",
        "model_card",
    ),
    ResearchSource(
        "e5_base_model",
        "multilingual-e5-base model card",
        "https://huggingface.co/intfloat/multilingual-e5-base",
        "model_card",
    ),
    ResearchSource(
        "mdeberta_model",
        "mDeBERTa multilingual NLI model card",
        "https://huggingface.co/MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        "model_card",
    ),
    ResearchSource(
        "bge_m3",
        "BGE-M3 model card",
        "https://huggingface.co/BAAI/bge-m3",
        "model_card",
    ),
    ResearchSource(
        "bge_reranker",
        "BGE multilingual reranker model card",
        "https://huggingface.co/BAAI/bge-reranker-v2-m3",
        "model_card",
    ),
    ResearchSource(
        "qwen_embedding",
        "Qwen3 Embedding 0.6B model card",
        "https://huggingface.co/Qwen/Qwen3-Embedding-0.6B",
        "model_card",
    ),
    ResearchSource(
        "qwen_reranker",
        "Qwen3 Reranker 0.6B model card",
        "https://huggingface.co/Qwen/Qwen3-Reranker-0.6B",
        "model_card",
    ),
    ResearchSource(
        "qwen_rubric",
        "Qwen3 4B Instruct model card",
        "https://huggingface.co/Qwen/Qwen3-4B-Instruct-2507",
        "model_card",
    ),
)


METHODS: tuple[AnalysisMethod, ...] = (
    AnalysisMethod(
        "deterministic_structure",
        "Deterministic structure cues",
        "extraction",
        "rules",
        ResearchMaturity.PRODUCT_BASELINE,
        "redacted_content",
        "Find explicit goals, constraints, outcomes, questions and plan markers with an explainable EN/PL baseline.",
        ("structure receipts", "candidate clauses", "coverage"),
        (),
        ("rope",),
        (
            "Lexical cues do not prove clarity, correctness or intent.",
            "The current baseline is functional, not calibrated on private engineering sessions.",
        ),
    ),
    AnalysisMethod(
        "dialogue_act_tagging",
        "Dialogue-act tagging",
        "conversation",
        "classifier",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Separate requests, clarification questions, hypotheses, decisions, corrections, evidence and closure acts.",
        ("act distribution", "question context", "response transitions"),
        (),
        ("dialogue_acts", "clarification"),
        (
            "Generic dialogue datasets do not directly represent software-agent work.",
            "Polish and mixed-language labels need a local engineering annotation set.",
        ),
    ),
    AnalysisMethod(
        "requirement_extraction",
        "Requirement and contract extraction",
        "extraction",
        "hybrid",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Extract goals, quality constraints, deliverables, acceptance criteria and unresolved references into typed local records.",
        ("typed requirements", "denominators", "unknown fields"),
        ("qwen3_4b_rubric",),
        ("rope", "qwen_rubric"),
        (
            "Generated structure must be validated against human labels.",
            "No excerpt or generated summary may cross the content-free persistence boundary.",
        ),
    ),
    AnalysisMethod(
        "lexical_retrieval",
        "BM25 lexical retrieval",
        "linking",
        "statistical",
        ResearchMaturity.EVALUATED_EXPLORATORY,
        "redacted_content",
        "Retrieve likely requirement, action, test and answer pairs with a transparent local baseline.",
        ("candidate links", "rank", "retrieval coverage"),
        (),
        ("e5_paper",),
        ("Vocabulary mismatch and paraphrases can hide valid links.",),
    ),
    AnalysisMethod(
        "multilingual_embeddings",
        "Multilingual semantic retrieval",
        "linking",
        "embedding",
        ResearchMaturity.EVALUATED_EXPLORATORY,
        "redacted_content",
        "Link paraphrased requirements, actions, answers and verification evidence across English and Polish.",
        ("candidate links", "semantic similarity", "retrieval coverage"),
        (
            "multilingual_e5_small",
            "multilingual_e5_base",
            "bge_m3",
            "qwen3_embedding_06b",
        ),
        (
            "e5_paper",
            "e5_model",
            "e5_base_model",
            "bge_m3",
            "qwen_embedding",
        ),
        (
            "Similarity is not entailment, causality or correctness.",
            "Top-k retrieval must precede expensive pairwise checks.",
        ),
    ),
    AnalysisMethod(
        "cross_encoder_reranking",
        "Cross-encoder reranking",
        "linking",
        "reranker",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Re-score a small retrieved candidate set for more precise requirement-to-action and question-to-answer links.",
        ("reranked links", "abstained ambiguous links"),
        ("bge_reranker_v2_m3", "qwen3_reranker_06b"),
        ("bge_reranker", "qwen_reranker"),
        (
            "Must never run over every conversation pair.",
            "Ranking relevance still does not prove task completion.",
        ),
    ),
    AnalysisMethod(
        "scoped_nli",
        "Scoped entailment and contradiction",
        "semantic_inference",
        "nli",
        ResearchMaturity.FAILED_GATE,
        "redacted_content",
        "Test whether linked statements agree, conflict or remain unrelated after scope matching.",
        ("entailment candidates", "contradiction candidates", "abstentions"),
        ("mdeberta_xnli",),
        ("mdeberta_model", "selective_prediction"),
        (
            "The current candidate failed the different-scope false-positive gate.",
            "NLI is disabled for product metrics until a safer candidate passes.",
        ),
    ),
    AnalysisMethod(
        "supersession_tracking",
        "Supersession and specification state",
        "conversation",
        "graph_rules",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Track which requirement is active, replaced, narrowed or reopened instead of treating all historical prompts as current.",
        ("active requirements", "superseded links", "scope changes"),
        (),
        ("rope",),
        (
            "Sequence and scope must be preserved.",
            "A similarity match alone cannot establish supersession.",
        ),
    ),
    AnalysisMethod(
        "traceability_graph",
        "Requirement-action-evidence graph",
        "workflow",
        "graph",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Build a typed graph from request to plan, action, verification and outcome while retaining Unknown edges.",
        ("traceability coverage", "orphan actions", "unverified requirements"),
        (),
        ("rope",),
        (
            "Edges need evidence-specific extractors and cannot be inferred from chronology alone.",
        ),
    ),
    AnalysisMethod(
        "process_sequence_metrics",
        "Conversation process metrics",
        "workflow",
        "process_mining",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "metadata",
        "Measure observable loops such as request-plan-action-test-correction without judging hidden reasoning.",
        ("loop counts", "transition rates", "time-to-evidence"),
        (),
        (),
        (
            "More or fewer loops are not inherently better.",
            "Comparisons must be stratified by task type and complexity.",
        ),
    ),
    AnalysisMethod(
        "local_rubric_judge",
        "Local structured rubric judge",
        "evaluation",
        "generative_model",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "redacted_content",
        "Produce bounded JSON judgments for dimensions that rules and pair models cannot express, with explicit evidence and abstention.",
        ("rubric labels", "safe explanation codes", "abstention"),
        ("qwen3_4b_rubric",),
        ("llm_rubric", "qwen_rubric"),
        (
            "LLM judges require human calibration and can be biased or inconsistent.",
            "Raw generations must remain ephemeral and local.",
        ),
    ),
    AnalysisMethod(
        "selective_prediction",
        "Calibration and selective prediction",
        "evaluation",
        "calibration",
        ResearchMaturity.RESEARCH_CANDIDATE,
        "metadata",
        "Calibrate each inferred metric and abstain when the expected error is too high.",
        ("calibrated confidence", "coverage-risk curve", "abstention reason"),
        (),
        ("selective_prediction",),
        (
            "Model softmax scores are not calibrated confidence.",
            "Release thresholds require a held-out private annotation set.",
        ),
    ),
)


MODEL_CANDIDATES: tuple[ModelCandidate, ...] = (
    ModelCandidate(
        "multilingual_e5_small",
        "Multilingual E5 small",
        "intfloat/multilingual-e5-small",
        "semantic retrieval",
        "MIT",
        "614241f622f53c4eeff9890bdc4f31cfecc418b3",
        "118M",
        "multilingual including English and Polish",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "Improved the full synthetic retrieval screen over BM25, but reversed on the smoke subset; private calibration is still required.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.666667,
            "mean_reciprocal_rank",
            0.819444,
        ),
        ("e5_model", "e5_paper"),
    ),
    ModelCandidate(
        "multilingual_e5_base",
        "Multilingual E5 base",
        "intfloat/multilingual-e5-base",
        "semantic retrieval",
        "MIT",
        "d128750597153bb5987e10b1c3493a34e5a4502a",
        "278M",
        "multilingual including English and Polish",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "Led the tiny synthetic retrieval screen, but remains disabled; representative private calibration and release gates are still required.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.833333,
            "mean_reciprocal_rank",
            0.902778,
        ),
        ("e5_base_model", "e5_paper"),
    ),
    ModelCandidate(
        "mdeberta_xnli",
        "mDeBERTa multilingual NLI",
        "MoritzLaurer/mDeBERTa-v3-base-xnli-multilingual-nli-2mil7",
        "scoped NLI",
        "MIT",
        "b5113eb38ab63efdd7f280f8c144ea8b13f978ce",
        "278M",
        "multilingual including English and Polish",
        ModelCandidateStatus.REJECTED_SCREEN,
        False,
        False,
        "Rejected: it classified every different-scope hard negative as a contradiction in the synthetic screen.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            18,
            "three_way_accuracy",
            0.555556,
            "macro_f1",
            0.6,
            "different_scope_false_positive_rate",
            1.0,
        ),
        ("mdeberta_model", "selective_prediction"),
    ),
    ModelCandidate(
        "bge_m3",
        "BGE-M3",
        "BAAI/bge-m3",
        "hybrid semantic retrieval",
        "MIT",
        "142964af7e05de16511657561de8e8750fc153a0",
        "568M",
        "100+ languages",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "The safe pin beat BM25 on the tiny full screen but tied E5 small and trailed E5 base and Qwen while using more accelerator memory; it remains disabled.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.666667,
            "mean_reciprocal_rank",
            0.819444,
        ),
        ("bge_m3",),
    ),
    ModelCandidate(
        "bge_reranker_v2_m3",
        "BGE reranker v2 M3",
        "BAAI/bge-reranker-v2-m3",
        "multilingual reranking",
        "Apache-2.0",
        "953dc6f6f85a1b2dbfca4c34a2796e7dde08d41e",
        "568M",
        "multilingual",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "Improved full-screen top-one and ranking over BM25, but performed worse on the smoke subset; it remains uncalibrated and disabled.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.75,
            "mean_reciprocal_rank",
            0.875,
        ),
        ("bge_reranker",),
    ),
    ModelCandidate(
        "qwen3_embedding_06b",
        "Qwen3 Embedding 0.6B",
        "Qwen/Qwen3-Embedding-0.6B",
        "instruction-aware semantic retrieval",
        "Apache-2.0",
        "97b0c614be4d77ee51c0cef4e5f07c00f9eb65b3",
        "0.6B",
        "100+ languages",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "Best retrieval candidate on the fictional full screen, but the 12-case result is insufficient for product activation.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.75,
            "mean_reciprocal_rank",
            0.861111,
        ),
        ("qwen_embedding",),
    ),
    ModelCandidate(
        "qwen3_reranker_06b",
        "Qwen3 Reranker 0.6B",
        "Qwen/Qwen3-Reranker-0.6B",
        "instruction-aware reranking",
        "Apache-2.0",
        "e61197ed45024b0ed8a2d74b80b4d909f1255473",
        "0.6B",
        "100+ languages",
        ModelCandidateStatus.EVALUATED_EXPLORATORY,
        False,
        False,
        "Improved over BM25 on the full screen but trailed the BGE reranker and showed smoke/full variance; it remains disabled.",
        ModelBenchmark(
            "bilingual-model-screen-v1-full",
            12,
            "top1_accuracy",
            0.666667,
            "mean_reciprocal_rank",
            0.826389,
        ),
        ("qwen_reranker",),
    ),
    ModelCandidate(
        "qwen3_4b_rubric",
        "Qwen3 4B Instruct 2507",
        "Qwen/Qwen3-4B-Instruct-2507",
        "structured local rubric",
        "Apache-2.0",
        "cdbee75f17c01a7cc42f958dc650907174af0554",
        "4B",
        "100+ languages and dialects",
        ModelCandidateStatus.REJECTED_SCREEN,
        False,
        False,
        "Rejected for product scoring: JSON compliance passed, but exact agreement and abstention behavior missed the release gates.",
        ModelBenchmark(
            "bilingual-rubric-screen-v1-full",
            24,
            "exact_label_accuracy",
            0.666667,
            "json_schema_compliance_rate",
            1.0,
            "abstention_macro_f1",
            0.521368,
        ),
        ("qwen_rubric", "llm_rubric"),
    ),
)


METRIC_ROADMAP: tuple[MetricRoadmapItem, ...] = (
    MetricRoadmapItem(
        "task_definition",
        "Task definition",
        "prompt",
        "Does the request state the action, target, context and desired outcome?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.BASELINE_AVAILABLE,
        "Typed request fields with content-free detection receipts.",
        ("deterministic_structure", "requirement_extraction"),
        "Measures stated structure, not whether the chosen task is wise.",
    ),
    MetricRoadmapItem(
        "problem_evidence_quality",
        "Problem evidence quality",
        "prompt",
        "For diagnosis tasks, are observed behavior, expected behavior, reproduction, and environment stated?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.BASELINE_AVAILABLE,
        "Explainable EN/PL cue receipts with diagnosis-task applicability.",
        ("deterministic_structure", "requirement_extraction"),
        "Cue coverage does not prove that the observations or reproduction are correct.",
    ),
    MetricRoadmapItem(
        "context_sufficiency",
        "Context sufficiency",
        "prompt",
        "Does the request identify the relevant component, current state, environment, and boundary?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.BASELINE_AVAILABLE,
        "Content-free receipts for four explicit context factors.",
        ("deterministic_structure", "requirement_extraction"),
        "The baseline detects stated context cues, not whether omitted context mattered.",
    ),
    MetricRoadmapItem(
        "ambiguity_and_specificity",
        "Ambiguity resolution",
        "prompt",
        "Are material references, choices and vague constraints resolved before implementation?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Ambiguity candidates linked to a later clarification or explicit assumption.",
        ("requirement_extraction", "supersession_tracking", "local_rubric_judge"),
        "Longer prompts are not automatically more specific.",
    ),
    MetricRoadmapItem(
        "constraint_precision",
        "Constraint precision",
        "prompt",
        "Are relevant privacy, compatibility, scope, performance and delivery constraints concrete?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "User-reviewed applicable constraint types and extracted values.",
        ("requirement_extraction", "local_rubric_judge"),
        "Unknown task-specific denominators must abstain.",
    ),
    MetricRoadmapItem(
        "acceptance_testability",
        "Acceptance testability",
        "prompt",
        "Can each important outcome be checked with an observable pass condition?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Requirement-to-acceptance links plus objective verification events.",
        ("requirement_extraction", "traceability_graph"),
        "Words such as test or verify are not proof of a usable criterion.",
    ),
    MetricRoadmapItem(
        "deliverable_contract",
        "Deliverable contract",
        "prompt",
        "Is the requested artifact, format, interface, location, audience, or compatibility contract explicit?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Deliverable clauses with typed contract-factor receipts.",
        ("deterministic_structure", "requirement_extraction", "local_rubric_judge"),
        "A detected format word does not establish a coherent or feasible deliverable.",
    ),
    MetricRoadmapItem(
        "clarification_value",
        "Clarification value",
        "collaboration",
        "Do questions resolve material uncertainty rather than merely increase question count?",
        ScoreDirection.CONTEXTUAL,
        MetricRoadmapState.RESEARCH,
        "Question acts linked to an ambiguity, answer and downstream decision.",
        ("dialogue_act_tagging", "traceability_graph"),
        "Question frequency alone is not a quality signal.",
    ),
    MetricRoadmapItem(
        "exploration_execution_balance",
        "Exploration-to-execution balance",
        "collaboration",
        "Does theorizing converge into decisions, actions and evidence at an appropriate point?",
        ScoreDirection.CONTEXTUAL,
        MetricRoadmapState.RESEARCH,
        "Dialogue acts and process transitions stratified by task type.",
        ("dialogue_act_tagging", "process_sequence_metrics"),
        "There is no universal ideal ratio for research and implementation tasks.",
    ),
    MetricRoadmapItem(
        "hypothesis_test_linkage",
        "Hypothesis-to-test linkage",
        "logic",
        "Are technical hypotheses followed by a discriminating check and an updated conclusion?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Hypothesis, verification and conclusion edges in the traceability graph.",
        ("dialogue_act_tagging", "traceability_graph", "process_sequence_metrics"),
        "Chronological proximity is not sufficient evidence of a link.",
    ),
    MetricRoadmapItem(
        "requirement_action_traceability",
        "Requirement-to-action traceability",
        "logic",
        "Can each active requirement be linked to an implementation or explicit deferral?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Top-k semantic links, reranking and typed graph edges.",
        ("multilingual_embeddings", "cross_encoder_reranking", "traceability_graph"),
        "Relevance links are candidates until calibrated or reviewed.",
    ),
    MetricRoadmapItem(
        "plan_adaptation",
        "Plan adaptation",
        "logic",
        "When evidence changes, is the observable plan updated or the deviation explained?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Plan versions, evidence events and supersession links.",
        ("supersession_tracking", "process_sequence_metrics", "traceability_graph"),
        "This evaluates observable plan state, never hidden chain of thought.",
    ),
    MetricRoadmapItem(
        "decision_rationale",
        "Decision rationale",
        "logic",
        "Are consequential choices connected to alternatives, constraints or evidence?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Decision acts and their typed supporting links.",
        ("dialogue_act_tagging", "traceability_graph", "local_rubric_judge"),
        "A fluent explanation can still be incorrect.",
    ),
    MetricRoadmapItem(
        "scope_stability",
        "Scope stability",
        "collaboration",
        "Are scope changes explicit, tracked and incorporated without reviving obsolete requirements?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Active/superseded requirement state and change events.",
        ("supersession_tracking", "traceability_graph"),
        "Intentional iteration is not scope failure.",
    ),
    MetricRoadmapItem(
        "correction_rework",
        "Correction and rework load",
        "collaboration",
        "How much avoidable work is repeated after misunderstood requirements or unsupported claims?",
        ScoreDirection.LOWER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Correction acts linked to the changed requirement, action and evidence.",
        ("dialogue_act_tagging", "supersession_tracking", "process_sequence_metrics"),
        "Corrections caused by new information must be separated from avoidable rework.",
    ),
    MetricRoadmapItem(
        "agent_answer_grounding",
        "Agent answer grounding",
        "agent_answer",
        "Are important agent claims supported by tool, test, source or artifact evidence?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.NEEDS_OBJECTIVE_EVIDENCE,
        "Claim-to-evidence links with evidence type and outcome.",
        ("multilingual_embeddings", "cross_encoder_reranking", "traceability_graph"),
        "Agent self-report never counts as proof.",
    ),
    MetricRoadmapItem(
        "verification_strategy_adequacy",
        "Verification strategy adequacy",
        "agent_answer",
        "Does the observable plan connect each important requirement to an appropriate verification strategy?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Requirement-to-verification-plan links, reported separately from executed outcomes.",
        ("traceability_graph", "process_sequence_metrics"),
        "Planning a check is not evidence that the check ran or passed.",
    ),
    MetricRoadmapItem(
        "first_pass_verification",
        "First-pass verification",
        "outcome",
        "Did the first meaningful executable verification episode pass for an eligible task?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.NEEDS_OBJECTIVE_EVIDENCE,
        "The first versioned test, build, lint, type, security, or artifact check episode.",
        ("traceability_graph", "process_sequence_metrics"),
        "Missing or unsupported verification evidence remains Unknown, never failure.",
    ),
    MetricRoadmapItem(
        "conversation_closure",
        "Conversation closure",
        "agent_answer",
        "Are open questions, deferred decisions and requested artifacts explicitly closed or carried forward?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.RESEARCH,
        "Open-loop graph nodes at the analysis boundary.",
        ("dialogue_act_tagging", "traceability_graph", "supersession_tracking"),
        "An open session snapshot must not be judged as a failed closure.",
    ),
    MetricRoadmapItem(
        "verified_delivery",
        "Verified delivery",
        "outcome",
        "Did the requested artifact pass relevant executable checks or receive explicit acceptance?",
        ScoreDirection.HIGHER_IS_BETTER,
        MetricRoadmapState.NEEDS_OBJECTIVE_EVIDENCE,
        "Versioned test, build, lint, security, artifact or human-acceptance evidence.",
        ("traceability_graph", "process_sequence_metrics"),
        "This is the outcome anchor; assistant completion text is never sufficient.",
    ),
)


def _index(values: tuple[object, ...], attribute: str) -> Mapping[str, object]:
    return MappingProxyType({getattr(value, attribute): value for value in values})


SOURCE_BY_KEY: Mapping[str, ResearchSource] = _index(SOURCES, "key")  # type: ignore[assignment]
METHOD_BY_KEY: Mapping[str, AnalysisMethod] = _index(METHODS, "key")  # type: ignore[assignment]
MODEL_CANDIDATE_BY_KEY: Mapping[str, ModelCandidate] = _index(  # type: ignore[assignment]
    MODEL_CANDIDATES, "key"
)


def validate_research_catalog() -> None:
    """Fail closed if a curated reference or product-safety invariant drifts."""

    for collection, label in (
        (SOURCES, "source"),
        (METHODS, "method"),
        (MODEL_CANDIDATES, "model candidate"),
        (METRIC_ROADMAP, "metric roadmap"),
    ):
        keys = [getattr(item, "key") for item in collection]
        if len(keys) != len(set(keys)):
            raise RuntimeError(f"duplicate {label} key")
    if len(METRIC_ROADMAP) < 10:
        raise RuntimeError("research catalog must expose at least ten metric questions")
    for method in METHODS:
        if not set(method.source_keys) <= set(SOURCE_BY_KEY):
            raise RuntimeError("method references an unknown research source")
        if not set(method.candidate_model_keys) <= set(MODEL_CANDIDATE_BY_KEY):
            raise RuntimeError("method references an unknown model candidate")
    for candidate in MODEL_CANDIDATES:
        if candidate.product_enabled or candidate.trust_remote_code:
            raise RuntimeError("research candidates must remain disabled and code-free")
        if not set(candidate.source_keys) <= set(SOURCE_BY_KEY):
            raise RuntimeError("model candidate references an unknown source")
    for metric in METRIC_ROADMAP:
        if not set(metric.method_keys) <= set(METHOD_BY_KEY):
            raise RuntimeError("metric roadmap references an unknown method")


validate_research_catalog()
