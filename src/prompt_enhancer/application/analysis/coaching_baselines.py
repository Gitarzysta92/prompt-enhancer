"""Experimental, explainable EN/PL coaching metrics for agent sessions.

The pack intentionally measures observable communication and workflow evidence,
not intelligence, personality, hidden reasoning, or developer rank.  These
deterministic rules are candidate baselines: each result carries content-free
factor receipts and an uncalibrated confidence.  Objective outcome metrics
abstain until structured verification evidence is composed into the analysis
input; an assistant's completion claim is never treated as proof.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from ...domain import DataTier
from ..persistence import MetricValueState
from .text_baselines import TextMetricEngine, TextMetricRegistry
from .text_contracts import (
    EvidenceOrigin,
    MetricApplicability,
    MetricDirection,
    MetricFraction,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextMetricCalculation,
    TextMetricDefinition,
    TextMetricEvidence,
    TextMetricSignal,
    TextMetricSignalStatus,
    TextRole,
)


COACHING_METRIC_PACK_KEY = "experimental.redacted-text.coaching"
COACHING_METRIC_PACK_VERSION = 3
COACHING_METRIC_ENGINE_VERSION = "coaching-rules-en-pl-2"
COACHING_METRIC_ALGORITHM_ID = "rules.en-pl.coaching-observables"
COACHING_METRIC_ALGORITHM_VERSION = "2"
COACHING_METRIC_RUBRIC_VERSION = "coaching-observables-rubric-2"
COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION = (
    "coaching-evidence-capabilities-v1"
)
MAX_COACHING_EVIDENCE = 32


def _definition(
    key: str,
    dimension: str,
    display_name: str,
    description: str,
    *,
    risk: bool = False,
    version: int = 1,
) -> TextMetricDefinition:
    return TextMetricDefinition(
        key=key,
        version=version,
        dimension=dimension,
        display_name=display_name,
        description=description,
        unit="risk_ratio" if risk else "ratio",
        direction=(
            MetricDirection.LOWER_IS_BETTER
            if risk
            else MetricDirection.HIGHER_IS_BETTER
        ),
    )


PROMPT_TASK_DEFINITION_COVERAGE = _definition(
    "prompt.task_definition_coverage",
    "prompt",
    "Task definition coverage",
    "On the focus request only, detected action, target, and intended-outcome cues divided by three non-overlapping rubric factors.",
    version=2,
)
PROMPT_PROBLEM_EVIDENCE_QUALITY = _definition(
    "prompt.problem_evidence_quality",
    "prompt",
    "Problem evidence quality",
    "For detected diagnosis tasks, observed behavior, expected behavior, reproduction, and environment cues divided by four rubric factors.",
    version=2,
)
PROMPT_CONTEXT_SUFFICIENCY = _definition(
    "prompt.context_sufficiency",
    "prompt",
    "Context cue coverage",
    "On the focus request only, detected current-state, environment or version, and relevant-boundary cues divided by three non-overlapping rubric factors.",
    version=2,
)
PROMPT_CONSTRAINT_PRECISION = _definition(
    "prompt.constraint_precision",
    "prompt",
    "Constraint precision candidates",
    "Constraint clauses containing a concrete value, boundary, platform, version, or explicit prohibition divided by detected constraint clauses.",
    version=2,
)
PROMPT_ACCEPTANCE_TESTABILITY = _definition(
    "prompt.acceptance_testability",
    "prompt",
    "Acceptance testability cues",
    "Detected requirement clauses with an observable check, threshold, comparison, or explicit pass condition divided by detected requirements.",
    version=2,
)
PROMPT_DELIVERABLE_CONTRACT = _definition(
    "prompt.deliverable_contract",
    "prompt",
    "Deliverable contract cues",
    "Detected deliverable clauses with an explicit format, interface, location, audience, or compatibility cue divided by deliverable clauses.",
    version=3,
)
COLLABORATION_AMBIGUITY_RESOLUTION = _definition(
    "collaboration.ambiguity_resolution",
    "collaboration",
    "Ambiguity-resolution candidates",
    "Ambiguity-marker clauses followed by a related clarification or explicit replacement divided by detected ambiguity candidates.",
    version=2,
)
COLLABORATION_CLARIFICATION_YIELD = _definition(
    "collaboration.clarification_yield",
    "collaboration",
    "Clarification yield candidates",
    "Agent clarification questions followed by a related, substantive user answer divided by detected agent questions.",
    version=2,
)
COLLABORATION_EXPLORATION_CONVERSION = _definition(
    "collaboration.exploration_conversion",
    "collaboration",
    "Exploration-to-plan conversion",
    "Hypothesis or exploration clauses followed by a related plan, decision, action, or verification item divided by exploration clauses.",
    version=2,
)
COLLABORATION_SCOPE_CHANGE_DISCIPLINE = _definition(
    "collaboration.scope_change_discipline",
    "collaboration",
    "Scope-change acknowledgement",
    "Explicit user scope changes followed by a related agent acknowledgement or revised plan divided by detected scope changes.",
    version=2,
)
COLLABORATION_AVOIDABLE_REWORK_RATE = _definition(
    "collaboration.rework_candidate_rate",
    "collaboration",
    "Rework-candidate rate",
    "User feedback turns containing correction or misunderstanding markers divided by user feedback turns after an agent response.",
    risk=True,
    version=2,
)
LOGIC_DECOMPOSITION_COVERAGE = _definition(
    "logic.decomposition_coverage",
    "logic",
    "Requirement-to-plan coverage",
    "Detected requirements with a conservative lexical link to a plan item divided by detected requirements.",
    version=2,
)
LOGIC_HYPOTHESIS_TEST_LINKAGE = _definition(
    "logic.hypothesis_test_linkage",
    "logic",
    "Hypothesis-to-test linkage",
    "Hypothesis clauses linked to structured verification evidence divided by detected hypotheses.",
    version=2,
)
LOGIC_DECISION_RATIONALE_COVERAGE = _definition(
    "logic.decision_rationale_coverage",
    "logic",
    "Decision-rationale coverage",
    "Structured decision items containing an explicit rationale, alternative, constraint, or evidence marker divided by structured decisions.",
    version=3,
)
LOGIC_REQUIREMENT_ACTION_TRACEABILITY = _definition(
    "logic.requirement_action_traceability",
    "logic",
    "Requirement-to-action traceability",
    "Detected requirements linked to a structured action item divided by detected requirements.",
    version=3,
)
LOGIC_OPEN_LOOP_CLOSURE = _definition(
    "logic.open_loop_closure",
    "logic",
    "Open-loop closure candidates",
    "Questions followed by a related opposite-role response and not reopened divided by detected questions.",
    version=2,
)
OUTCOME_AGENT_CLAIM_GROUNDING = _definition(
    "outcome.agent_claim_grounding",
    "outcome",
    "Agent claim grounding",
    "Material agent claims linked to objective tool, test, source, or artifact evidence divided by eligible claims.",
    version=2,
)
OUTCOME_VERIFICATION_STRATEGY_ADEQUACY = _definition(
    "outcome.verification_strategy_adequacy",
    "outcome",
    "Verification-strategy coverage",
    "Detected requirements linked to a later plan or response containing a recognized verification-strategy cue divided by detected requirements.",
    version=2,
)
OUTCOME_FIRST_PASS_VERIFICATION = _definition(
    "outcome.first_pass_verification",
    "outcome",
    "First-pass verification",
    "Verification-eligible tasks whose first meaningful executable verification episode passed divided by evaluable tasks.",
    version=2,
)
OUTCOME_VERIFIED_REQUIREMENT_COVERAGE = _definition(
    "outcome.verified_requirement_coverage",
    "outcome",
    "Verified requirement coverage",
    "Active requirements linked to objective passing verification or explicit acceptance evidence divided by active requirements.",
    version=2,
)


COACHING_METRIC_DEFINITIONS = (
    PROMPT_TASK_DEFINITION_COVERAGE,
    PROMPT_PROBLEM_EVIDENCE_QUALITY,
    PROMPT_CONTEXT_SUFFICIENCY,
    PROMPT_CONSTRAINT_PRECISION,
    PROMPT_ACCEPTANCE_TESTABILITY,
    PROMPT_DELIVERABLE_CONTRACT,
    COLLABORATION_AMBIGUITY_RESOLUTION,
    COLLABORATION_CLARIFICATION_YIELD,
    COLLABORATION_EXPLORATION_CONVERSION,
    COLLABORATION_SCOPE_CHANGE_DISCIPLINE,
    COLLABORATION_AVOIDABLE_REWORK_RATE,
    LOGIC_DECOMPOSITION_COVERAGE,
    LOGIC_HYPOTHESIS_TEST_LINKAGE,
    LOGIC_DECISION_RATIONALE_COVERAGE,
    LOGIC_REQUIREMENT_ACTION_TRACEABILITY,
    LOGIC_OPEN_LOOP_CLOSURE,
    OUTCOME_AGENT_CLAIM_GROUNDING,
    OUTCOME_VERIFICATION_STRATEGY_ADEQUACY,
    OUTCOME_FIRST_PASS_VERIFICATION,
    OUTCOME_VERIFIED_REQUIREMENT_COVERAGE,
)


_CLAUSE_SPLIT = re.compile(r"(?:\r?\n)+|(?<=[.!?;])\s+")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX-]\])\s*")
_TOKEN = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*", re.UNICODE)
_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "be", "by", "do", "for", "from",
        "in", "is", "it", "of", "on", "or", "that", "the", "this", "to",
        "we", "with", "i", "jest", "lub", "na", "oraz", "po", "się", "to",
        "w", "z", "że", "dla", "czy",
    }
)
_ACTION = re.compile(
    r"\b(?:add|build|change|check|create|design|diagnose|display|export|fix|"
    r"implement|improve|integrate|make|measure|refactor|render|run|show|test|"
    r"update|validate|verify|dodaj|zbuduj|zmień|sprawdź|stwórz|utwórz|napraw|"
    r"zaimplementuj|ulepsz|zintegruj|zmierz|pokaż|przetestuj|zaktualizuj|zweryfikuj)\b",
    re.IGNORECASE,
)
_OUTCOME = re.compile(
    r"\b(?:so that|in order to|to allow|to enable|so (?:we|users?) can|"
    r"desired (?:result|outcome)|aby|żeby|tak aby|dzięki temu|docelowo)\b",
    re.IGNORECASE,
)
_CONTEXT = re.compile(
    r"\b(?:current|existing|currently|repository|repo|codebase|component|module|"
    r"service|endpoint|database|schema|screen|page|session|project|obecn|istniejąc|"
    r"repozytor|kod|komponent|moduł|usług|baza|schemat|ekran|stron|sesj|projekt)\w*\b",
    re.IGNORECASE,
)
_ENVIRONMENT = re.compile(
    r"\b(?:windows|linux|macos|ios|android|browser|desktop|mobile|python|node|"
    r"react|angular|fastapi|sqlite|duckdb|version|revision|gpu|cpu|cuda|mps|"
    r"przeglądark|wersj|rewizj|środowisk)\w*\b",
    re.IGNORECASE,
)
_BOUNDARY = re.compile(
    r"\b(?:only|must not|never|without|scope|limit|maximum|minimum|local|offline|"
    r"private|public|read-only|tylko|nie wolno|nigdy|bez|zakres|limit|maksymal|"
    r"minimal|lokaln|prywatn|publiczn|tylko do odczytu)\w*\b",
    re.IGNORECASE,
)
_REQUIREMENT = re.compile(
    r"\b(?:must|must not|needs? to|should|shall|has to|musi|nie może|powinien|"
    r"powinna|powinno|należy)\b",
    re.IGNORECASE,
)
_CHECK = re.compile(
    r"\b(?:acceptance|assert|equals?|exactly|exists?|must pass|passes|returns?|"
    r"test(?:s|ed|ing)?|threshold|verify|verified|visible|without errors?|"
    r"akceptacj|dokładnie|istnieje|musi przejść|przechodzi|test|próg|zwraca|"
    r"zweryfik|widoczn)\w*\b|(?:<=|>=|==|<|>)\s*\d+|\b\d+(?:\.\d+)?%",
    re.IGNORECASE,
)
_DIAGNOSTIC = re.compile(
    r"\b(?:bug|issue|error|exception|failure|failed|does not work|isn't working|"
    r"regression|incorrect|unexpected|broken|problem|błąd|problem|awari|nie działa|"
    r"zepsut|niepoprawn|nieoczekiwan)\w*\b",
    re.IGNORECASE,
)
_OBSERVED = re.compile(
    r"\b(?:actual|observed|currently|shows?|returns?|got|happens?|"
    r"faktyczn|obserwowan|obecnie|pokazuje|zwraca|otrzym|dzieje się)\w*\b",
    re.IGNORECASE,
)
_EXPECTED = re.compile(
    r"\b(?:expected|should|want|instead|desired|oczekiw|powin|chcę|zamiast|docelow)\w*\b",
    re.IGNORECASE,
)
_REPRODUCTION = re.compile(
    r"\b(?:reproduc|steps?|when|after|before|every time|only when|kroki|odtwor|"
    r"gdy|kiedy|po|przed|za każdym razem|tylko gdy)\w*\b",
    re.IGNORECASE,
)
_CONSTRAINT = re.compile(
    r"\b(?:must|must not|only|never|without|at most|at least|under|within|"
    r"compatible|version|privacy|private|safe|cost|free|latency|memory|"
    r"musi|nie może|tylko|nigdy|bez|co najwyżej|co najmniej|zgodn|wersj|"
    r"prywatn|bezpiecz|koszt|darmow|opóźnien|pamięć)\w*\b",
    re.IGNORECASE,
)
_CONCRETE = re.compile(
    r"\b(?:windows|linux|macos|ios|android|python|node|react|fastapi|sqlite|"
    r"cuda|mps|cpu|gpu|offline|local|read-only|public|private|free|no network|"
    r"bez sieci|lokaln|tylko do odczytu|bezpłatn)\w*\b|\bv?\d+(?:\.\d+){0,3}\b|"
    r"\b\d+(?:\.\d+)?\s*(?:ms|s|mb|gb|kb|%|tokens?|messages?|chars?)\b|"
    r"(?:<=|>=|==|<|>)\s*\d+",
    re.IGNORECASE,
)
_VAGUE = re.compile(
    r"\b(?:and so on|maybe|probably|somehow|something|some kind|or something|"
    r"i tak dalej|jakoś|może|chyba|coś|jakieś|lub coś)\b",
    re.IGNORECASE,
)
_AMBIGUITY = re.compile(
    r"\b(?:maybe|somehow|something|some kind|or something|not sure|which|whether|"
    r"it|this thing|that thing|może|jakoś|coś|jakieś|nie wiem|który|która|czy|to coś)\b",
    re.IGNORECASE,
)
_CLARIFICATION = re.compile(
    r"\b(?:actually|specifically|to clarify|I mean|instead|correction|"
    r"dokładnie|konkretnie|dla jasności|mam na myśli|zamiast|poprawka)\b",
    re.IGNORECASE,
)
_HYPOTHESIS = re.compile(
    r"\b(?:hypothesis|assume|could be|might be|possibly|likely|I think|theory|"
    r"hipotez|załóżmy|może być|prawdopodobn|możliw|wydaje się|teori)\w*\b",
    re.IGNORECASE,
)
_SCOPE_CHANGE = re.compile(
    r"\b(?:change scope|new requirement|instead|no longer|remove|additionally|"
    r"from now|for now|actually|zmień zakres|nowe wymaganie|zamiast|już nie|"
    r"usuń|dodatkowo|od teraz|na razie|właściwie)\b",
    re.IGNORECASE,
)
_CORRECTION = re.compile(
    r"\b(?:no[, ]|not what|wrong|incorrect|you misunderstood|still fails?|redo|"
    r"try again|actually|nie[, ]|nie o to|źle|niepoprawn|nie zrozumiał|nadal|"
    r"zrób ponownie|spróbuj ponownie|właściwie)\b",
    re.IGNORECASE,
)
_RATIONALE = re.compile(
    r"\b(?:because|due to|given that|so that|to preserve|trade-?off|alternative|"
    r"evidence|constraint|ponieważ|dlatego że|ze względu|aby zachować|kompromis|"
    r"alternatyw|dowód|ograniczen)\w*\b",
    re.IGNORECASE,
)
_DELIVERABLE = re.compile(
    r"\b(?:api|app|application|card|component|dashboard|document|file|image|"
    r"report|script|view|endpoint|page|route|table|chart|aplikacj|karta|komponent|"
    r"panel|dokument|plik|obraz|raport|skrypt|widok|stron|trasa|tabela|wykres)\w*\b",
    re.IGNORECASE,
)
_DELIVERABLE_DETAIL = re.compile(
    r"\b(?:csv|html|json|markdown|pdf|png|svg|yaml|format|button|cli|endpoint|"
    r"interface|menu|route|ui|user|team|reviewer|compatible|windows|linux|macos|"
    r"format|przycisk|interfejs|menu|trasa|użytkownik|zespół|recenzent|zgodn)\w*\b",
    re.IGNORECASE,
)
_QUESTION_PREFIX = re.compile(
    r"^\s*(?:what|which|who|where|when|why|how|can|could|should|would|"
    r"co|który|która|które|kto|gdzie|kiedy|dlaczego|jak|czy)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True, repr=False)
class _Clause:
    message_id: str
    sequence: int
    role: TextRole
    kind: TextMessageKind
    origin: EvidenceOrigin
    text: str
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True, repr=False)
class _CoachingFeatures:
    supported_language: bool
    available_message_kinds: frozenset[TextMessageKind]
    observed_message_kinds: frozenset[TextMessageKind]
    analyzable_message_kinds: frozenset[TextMessageKind]
    analyzable_message_count: int
    clauses: tuple[_Clause, ...]
    user_clauses: tuple[_Clause, ...]
    focus_request_clauses: tuple[_Clause, ...]
    agent_clauses: tuple[_Clause, ...]
    requirements: tuple[_Clause, ...]
    plan_items: tuple[_Clause, ...]
    questions: tuple[_Clause, ...]
    agent_questions: tuple[_Clause, ...]
    hypotheses: tuple[_Clause, ...]
    diagnostic_clauses: tuple[_Clause, ...]
    constraint_clauses: tuple[_Clause, ...]
    precise_constraints: tuple[_Clause, ...]
    deliverable_clauses: tuple[_Clause, ...]
    detailed_deliverables: tuple[_Clause, ...]
    checkable_requirements: tuple[_Clause, ...]
    ambiguity_clauses: tuple[_Clause, ...]
    resolved_ambiguities: tuple[_Clause, ...]
    productive_questions: tuple[_Clause, ...]
    converted_hypotheses: tuple[_Clause, ...]
    scope_changes: tuple[_Clause, ...]
    acknowledged_scope_changes: tuple[_Clause, ...]
    feedback_turns: tuple[_Clause, ...]
    correction_feedback: tuple[_Clause, ...]
    requirement_plan_links: tuple[tuple[_Clause, _Clause], ...]
    closed_questions: tuple[_Clause, ...]
    verification_strategy_links: tuple[tuple[_Clause, _Clause], ...]


def _tokens(value: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _TOKEN.findall(value)
        if len(token) > 1 and token.casefold() not in _STOPWORDS
    )


def _similarity(left: _Clause, right: _Clause) -> float:
    if not left.tokens or not right.tokens:
        return 0.0
    return len(left.tokens & right.tokens) / len(left.tokens | right.tokens)


def _later_related(
    source: _Clause,
    candidates: tuple[_Clause, ...],
    *,
    threshold: float = 0.1,
) -> _Clause | None:
    return next(
        (
            candidate
            for candidate in candidates
            if candidate.sequence > source.sequence
            and _similarity(source, candidate) >= threshold
        ),
        None,
    )


def _has_later_boundary(
    source: _Clause,
    candidates: tuple[_Clause, ...],
    *,
    opposite_role: bool = False,
) -> bool:
    """Return whether the bounded window proves an episode horizon advanced.

    A missing relation is a measured negative only after the kind of later turn
    that could have closed the episode was actually observed. At the right
    edge there is no such evidence, so candidate baselines remain non-numeric
    until typed semantic-unit lifecycle receipts can represent pending.
    """

    return any(
        candidate.sequence > source.sequence
        and (not opposite_role or candidate.role is not source.role)
        for candidate in candidates
    )


def _has_open_episode_horizon(
    candidates: tuple[_Clause, ...],
    closed: tuple[_Clause, ...],
    boundary_candidates: tuple[_Clause, ...],
    *,
    opposite_role: bool = False,
) -> bool:
    closed_set = frozenset(closed)
    return any(
        candidate not in closed_set
        and not _has_later_boundary(
            candidate,
            boundary_candidates,
            opposite_role=opposite_role,
        )
        for candidate in candidates
    )


class CoachingTextFeatureExtractor:
    required_tier = DataTier.REDACTED_CONTENT
    algorithm_id = COACHING_METRIC_ALGORITHM_ID
    algorithm_version = COACHING_METRIC_ALGORITHM_VERSION

    def extract(self, context: P1TextAnalysisInput) -> _CoachingFeatures:
        focus_sequence = next(
            message.sequence
            for message in context.messages
            if message.message_id == context.focus_message_id
        )
        superseded = {
            value
            for message in context.messages
            for value in message.supersedes_message_ids
        }
        active = tuple(
            message
            for message in context.messages
            if message.message_id not in superseded
        )
        analyzable = tuple(
            message
            for message in active
            if message.language
            in {TextLanguage.ENGLISH, TextLanguage.POLISH, TextLanguage.MIXED}
        )
        clauses: list[_Clause] = []
        for message in analyzable:
            origin = (
                EvidenceOrigin.DIRECT
                if message.sequence >= focus_sequence
                else EvidenceOrigin.INHERITED
            )
            for raw in _CLAUSE_SPLIT.split(message.text.get_secret_value()):
                value = _BULLET.sub("", raw).strip()
                if value:
                    clauses.append(
                        _Clause(
                            message_id=message.message_id,
                            sequence=message.sequence,
                            role=message.role,
                            kind=message.kind,
                            origin=origin,
                            text=value,
                            tokens=_tokens(value),
                        )
                    )
        all_clauses = tuple(clauses)
        user_clauses = tuple(clause for clause in all_clauses if clause.role is TextRole.USER)
        agent_clauses = tuple(clause for clause in all_clauses if clause.role is TextRole.AGENT)
        request_clauses = tuple(
            clause
            for clause in user_clauses
            if clause.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        )
        focus_request_clauses = tuple(
            clause
            for clause in request_clauses
            if clause.message_id == context.focus_message_id
        )
        requirements = tuple(
            clause
            for clause in request_clauses
            if not (clause.text.rstrip().endswith("?") or _QUESTION_PREFIX.search(clause.text))
            and (_ACTION.search(clause.text) or _REQUIREMENT.search(clause.text))
        )
        plan_items = tuple(clause for clause in agent_clauses if clause.kind is TextMessageKind.PLAN)
        questions = tuple(
            clause
            for clause in all_clauses
            if clause.text.rstrip().endswith("?") or _QUESTION_PREFIX.search(clause.text)
        )
        agent_questions = tuple(clause for clause in questions if clause.role is TextRole.AGENT)
        hypotheses = tuple(clause for clause in all_clauses if _HYPOTHESIS.search(clause.text))
        diagnostic = tuple(clause for clause in request_clauses if _DIAGNOSTIC.search(clause.text))
        constraints = tuple(clause for clause in request_clauses if _CONSTRAINT.search(clause.text))
        precise_constraints = tuple(
            clause
            for clause in constraints
            if _CONCRETE.search(clause.text) and not _VAGUE.search(clause.text)
        )
        deliverables = tuple(clause for clause in request_clauses if _DELIVERABLE.search(clause.text))
        detailed_deliverables = tuple(
            clause for clause in deliverables if _DELIVERABLE_DETAIL.search(clause.text)
        )
        checkable = tuple(clause for clause in requirements if _CHECK.search(clause.text))
        ambiguities = tuple(clause for clause in request_clauses if _AMBIGUITY.search(clause.text))
        resolved_ambiguities = tuple(
            ambiguity
            for ambiguity in ambiguities
            if _later_related(
                ambiguity,
                tuple(
                    clause
                    for clause in user_clauses
                    if _CLARIFICATION.search(clause.text)
                    or clause.message_id in {
                        message.message_id
                        for message in active
                        if ambiguity.message_id in message.supersedes_message_ids
                    }
                ),
            )
            is not None
        )
        productive_questions = tuple(
            question
            for question in agent_questions
            if _later_related(
                question,
                tuple(
                    clause
                    for clause in user_clauses
                    if _ACTION.search(clause.text)
                    or _CONSTRAINT.search(clause.text)
                    or _OUTCOME.search(clause.text)
                    or _CONCRETE.search(clause.text)
                ),
            )
            is not None
        )
        conversion_targets = tuple(
            clause
            for clause in all_clauses
            if clause.kind
            in {
                TextMessageKind.PLAN,
                TextMessageKind.DECISION,
                TextMessageKind.ACTION,
                TextMessageKind.VERIFICATION,
            }
        )
        converted_hypotheses = tuple(
            item for item in hypotheses if _later_related(item, conversion_targets) is not None
        )
        scope_changes = tuple(clause for clause in request_clauses if _SCOPE_CHANGE.search(clause.text))
        acknowledgements = tuple(
            clause
            for clause in agent_clauses
            if clause.kind in {TextMessageKind.RESPONSE, TextMessageKind.PLAN}
        )
        acknowledged_scope_changes = tuple(
            change for change in scope_changes if _later_related(change, acknowledgements) is not None
        )
        agent_sequences = {clause.sequence for clause in agent_clauses}
        feedback_turns = tuple(
            clause
            for clause in user_clauses
            if clause.kind is TextMessageKind.FEEDBACK
            and any(sequence < clause.sequence for sequence in agent_sequences)
        )
        correction_feedback = tuple(
            clause for clause in feedback_turns if _CORRECTION.search(clause.text)
        )
        requirement_plan_links = tuple(
            (requirement, plan)
            for requirement in requirements
            for plan in plan_items
            if plan.sequence >= requirement.sequence and _similarity(requirement, plan) >= 0.1
        )
        closed: list[_Clause] = []
        for question in questions:
            opposite = tuple(
                clause
                for clause in all_clauses
                if clause.sequence > question.sequence
                and clause.role is not question.role
                and clause not in questions
            )
            answer = _later_related(question, opposite, threshold=0.05)
            if answer is None:
                continue
            reopened = any(
                later.sequence > answer.sequence
                and later.role is question.role
                and _similarity(question, later) >= 0.25
                for later in questions
            )
            if not reopened:
                closed.append(question)
        strategy_clauses = tuple(
            clause
            for clause in agent_clauses
            if clause.kind
            in {TextMessageKind.PLAN, TextMessageKind.RESPONSE, TextMessageKind.VERIFICATION}
            and _CHECK.search(clause.text)
        )
        verification_strategy_links = tuple(
            (requirement, strategy)
            for requirement in requirements
            for strategy in strategy_clauses
            if strategy.sequence >= requirement.sequence
            and _similarity(requirement, strategy) >= 0.05
        )
        return _CoachingFeatures(
            supported_language=bool(analyzable),
            available_message_kinds=context.available_message_kinds,
            observed_message_kinds=frozenset(message.kind for message in active),
            analyzable_message_kinds=frozenset(message.kind for message in analyzable),
            analyzable_message_count=len(analyzable),
            clauses=all_clauses,
            user_clauses=user_clauses,
            focus_request_clauses=focus_request_clauses,
            agent_clauses=agent_clauses,
            requirements=requirements,
            plan_items=plan_items,
            questions=questions,
            agent_questions=agent_questions,
            hypotheses=hypotheses,
            diagnostic_clauses=diagnostic,
            constraint_clauses=constraints,
            precise_constraints=precise_constraints,
            deliverable_clauses=deliverables,
            detailed_deliverables=detailed_deliverables,
            checkable_requirements=checkable,
            ambiguity_clauses=ambiguities,
            resolved_ambiguities=resolved_ambiguities,
            productive_questions=productive_questions,
            converted_hypotheses=converted_hypotheses,
            scope_changes=scope_changes,
            acknowledged_scope_changes=acknowledged_scope_changes,
            feedback_turns=feedback_turns,
            correction_feedback=correction_feedback,
            requirement_plan_links=requirement_plan_links,
            closed_questions=tuple(closed),
            verification_strategy_links=verification_strategy_links,
        )


def _signal(code: str, present: bool) -> TextMetricSignal:
    return TextMetricSignal(
        code=code,
        status=(TextMetricSignalStatus.DETECTED if present else TextMetricSignalStatus.MISSING),
        count=1 if present else 0,
    )


def _count(code: str, value: int) -> TextMetricSignal:
    return TextMetricSignal(code=code, status=TextMetricSignalStatus.COUNTED, count=value)


def _unknown(code: str) -> TextMetricSignal:
    return TextMetricSignal(code=code, status=TextMetricSignalStatus.UNKNOWN)


def _empty(
    state: MetricValueState,
    explanation: str,
    *,
    signals: tuple[TextMetricSignal, ...] = (),
) -> TextMetricCalculation:
    return TextMetricCalculation(
        value_state=state,
        explanation_code=explanation,
        signals=signals,
    )


def _known(
    numerator: int,
    denominator: int,
    evidence: tuple[_Clause, ...],
    explanation: str,
    signals: tuple[TextMetricSignal, ...],
) -> TextMetricCalculation:
    seen: set[str] = set()
    refs: list[TextMetricEvidence] = []
    for clause in evidence:
        if clause.message_id in seen:
            continue
        seen.add(clause.message_id)
        refs.append(TextMetricEvidence(message_id=clause.message_id, origin=clause.origin))
        if len(refs) == MAX_COACHING_EVIDENCE:
            break
    return TextMetricCalculation(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=numerator, denominator=denominator),
        evidence=tuple(refs),
        signals=signals,
        explanation_code=explanation,
    )


class _Calculator:
    definition: TextMetricDefinition
    required_kind_groups: tuple[frozenset[TextMessageKind], ...] = ()

    def _guard(
        self,
        context: P1TextAnalysisInput,
        features: _CoachingFeatures,
    ) -> TextMetricCalculation | None:
        applicability = context.task_profile.applicability_for(self.definition.key)
        if applicability is MetricApplicability.UNKNOWN:
            return _empty(MetricValueState.UNKNOWN, "applicability_unknown")
        if applicability is MetricApplicability.NOT_APPLICABLE:
            return _empty(MetricValueState.NOT_APPLICABLE, "explicitly_not_applicable")
        if not context.text_extraction_complete:
            return _empty(MetricValueState.ABSTAINED, "source_extraction_incomplete")
        for group in self.required_kind_groups:
            if features.available_message_kinds.isdisjoint(group):
                return _empty(MetricValueState.ABSTAINED, "message_kind_unavailable")
            if features.observed_message_kinds.isdisjoint(group):
                return _empty(MetricValueState.UNKNOWN, "message_kind_unobserved")
            if features.analyzable_message_kinds.isdisjoint(group):
                return _empty(MetricValueState.ABSTAINED, "unsupported_language")
        if not features.supported_language:
            return _empty(MetricValueState.ABSTAINED, "unsupported_language")
        return None


class _RequestCalculator(_Calculator):
    required_kind_groups = (frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),)


class TaskDefinitionCalculator(_RequestCalculator):
    definition = PROMPT_TASK_DEFINITION_COVERAGE

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        text = "\n".join(clause.text for clause in features.focus_request_clauses)
        factors = (
            ("task.action", bool(_ACTION.search(text))),
            ("task.target", bool(_DELIVERABLE.search(text) or _CONTEXT.search(text))),
            ("task.outcome", bool(_OUTCOME.search(text) or _CHECK.search(text))),
        )
        return _known(
            sum(present for _, present in factors),
            len(factors),
            features.focus_request_clauses,
            "task_definition_cues",
            tuple(_signal(code, present) for code, present in factors),
        )


class ProblemEvidenceCalculator(_RequestCalculator):
    definition = PROMPT_PROBLEM_EVIDENCE_QUALITY

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.diagnostic_clauses:
            return _empty(MetricValueState.UNKNOWN, "diagnostic_task_not_detected")
        text = "\n".join(clause.text for clause in features.user_clauses)
        factors = (
            ("problem.observed", bool(_OBSERVED.search(text) or _DIAGNOSTIC.search(text))),
            ("problem.expected", bool(_EXPECTED.search(text))),
            ("problem.reproduction", bool(_REPRODUCTION.search(text))),
            ("problem.environment", bool(_ENVIRONMENT.search(text))),
        )
        return _known(
            sum(present for _, present in factors),
            len(factors),
            features.diagnostic_clauses,
            "diagnostic_evidence_cues",
            tuple(_signal(code, present) for code, present in factors),
        )


class ContextSufficiencyCalculator(_RequestCalculator):
    definition = PROMPT_CONTEXT_SUFFICIENCY

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        text = "\n".join(clause.text for clause in features.focus_request_clauses)
        factors = (
            ("context.current_state", bool(_OBSERVED.search(text))),
            ("context.environment", bool(_ENVIRONMENT.search(text))),
            ("context.boundary", bool(_BOUNDARY.search(text))),
        )
        return _known(
            sum(present for _, present in factors),
            len(factors),
            features.focus_request_clauses,
            "context_cues",
            tuple(_signal(code, present) for code, present in factors),
        )


class ConstraintPrecisionCalculator(_RequestCalculator):
    definition = PROMPT_CONSTRAINT_PRECISION

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.constraint_clauses:
            return _empty(MetricValueState.UNKNOWN, "constraints_unobserved")
        return _known(
            len(features.precise_constraints),
            len(features.constraint_clauses),
            features.precise_constraints,
            "constraint_precision_candidates",
            (
                _count("constraints.detected", len(features.constraint_clauses)),
                _count("constraints.precise", len(features.precise_constraints)),
            ),
        )


class AcceptanceTestabilityCalculator(_RequestCalculator):
    definition = PROMPT_ACCEPTANCE_TESTABILITY

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _empty(MetricValueState.UNKNOWN, "requirements_unknown")
        return _known(
            len(features.checkable_requirements),
            len(features.requirements),
            features.checkable_requirements,
            "acceptance_check_cues",
            (
                _count("acceptance.requirements", len(features.requirements)),
                _count("acceptance.checkable", len(features.checkable_requirements)),
            ),
        )


class DeliverableContractCalculator(_RequestCalculator):
    definition = PROMPT_DELIVERABLE_CONTRACT

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.deliverable_clauses:
            return _empty(MetricValueState.UNKNOWN, "deliverables_unobserved")
        return _known(
            len(features.detailed_deliverables),
            len(features.deliverable_clauses),
            features.detailed_deliverables,
            "deliverable_detail_cues",
            (
                _count("deliverables.detected", len(features.deliverable_clauses)),
                _count("deliverables.detailed", len(features.detailed_deliverables)),
            ),
        )


class AmbiguityResolutionCalculator(_RequestCalculator):
    definition = COLLABORATION_AMBIGUITY_RESOLUTION

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.ambiguity_clauses:
            return _empty(MetricValueState.UNKNOWN, "ambiguity_candidates_unobserved")
        ambiguity_boundaries = tuple(
            clause
            for clause in features.user_clauses
            if clause.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        )
        if _has_open_episode_horizon(
            features.ambiguity_clauses,
            features.resolved_ambiguities,
            ambiguity_boundaries,
        ):
            return _empty(
                MetricValueState.UNKNOWN,
                "episode_horizon_open",
                signals=(
                    _count("ambiguity.candidates", len(features.ambiguity_clauses)),
                    _unknown("ambiguity.pending_right_edge"),
                ),
            )
        return _known(
            len(features.resolved_ambiguities),
            len(features.ambiguity_clauses),
            features.resolved_ambiguities,
            "ambiguity_resolution_candidates",
            (
                _count("ambiguity.candidates", len(features.ambiguity_clauses)),
                _count("ambiguity.resolved", len(features.resolved_ambiguities)),
            ),
        )


class ClarificationYieldCalculator(_Calculator):
    definition = COLLABORATION_CLARIFICATION_YIELD
    required_kind_groups = (
        frozenset({TextMessageKind.RESPONSE}),
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.agent_questions:
            return _empty(MetricValueState.UNKNOWN, "agent_questions_unobserved")
        if _has_open_episode_horizon(
            features.agent_questions,
            features.productive_questions,
            features.user_clauses,
        ):
            return _empty(
                MetricValueState.UNKNOWN,
                "episode_horizon_open",
                signals=(
                    _count("clarification.questions", len(features.agent_questions)),
                    _unknown("clarification.pending_right_edge"),
                ),
            )
        return _known(
            len(features.productive_questions),
            len(features.agent_questions),
            features.productive_questions,
            "clarification_answer_candidates",
            (
                _count("clarification.questions", len(features.agent_questions)),
                _count("clarification.productive", len(features.productive_questions)),
            ),
        )


class ExplorationConversionCalculator(_Calculator):
    definition = COLLABORATION_EXPLORATION_CONVERSION
    required_kind_groups = (frozenset({TextMessageKind.REQUEST, TextMessageKind.RESPONSE, TextMessageKind.PLAN}),)

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.hypotheses:
            return _empty(MetricValueState.UNKNOWN, "hypotheses_unobserved")
        if features.available_message_kinds.isdisjoint(
            {TextMessageKind.PLAN, TextMessageKind.DECISION, TextMessageKind.ACTION, TextMessageKind.VERIFICATION}
        ):
            return _empty(MetricValueState.ABSTAINED, "conversion_evidence_unavailable")
        conversion_boundaries = tuple(
            clause
            for clause in features.clauses
            if clause.kind
            in {
                TextMessageKind.PLAN,
                TextMessageKind.DECISION,
                TextMessageKind.ACTION,
                TextMessageKind.VERIFICATION,
            }
        )
        if _has_open_episode_horizon(
            features.hypotheses,
            features.converted_hypotheses,
            conversion_boundaries,
        ):
            return _empty(
                MetricValueState.UNKNOWN,
                "episode_horizon_open",
                signals=(
                    _count("exploration.hypotheses", len(features.hypotheses)),
                    _unknown("exploration.pending_right_edge"),
                ),
            )
        return _known(
            len(features.converted_hypotheses),
            len(features.hypotheses),
            features.converted_hypotheses,
            "exploration_conversion_candidates",
            (
                _count("exploration.hypotheses", len(features.hypotheses)),
                _count("exploration.converted", len(features.converted_hypotheses)),
            ),
        )


class ScopeChangeDisciplineCalculator(_RequestCalculator):
    definition = COLLABORATION_SCOPE_CHANGE_DISCIPLINE

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.scope_changes:
            return _empty(MetricValueState.UNKNOWN, "scope_changes_unobserved")
        scope_boundaries = tuple(
            clause
            for clause in features.agent_clauses
            if clause.kind in {TextMessageKind.RESPONSE, TextMessageKind.PLAN}
        )
        if _has_open_episode_horizon(
            features.scope_changes,
            features.acknowledged_scope_changes,
            scope_boundaries,
        ):
            return _empty(
                MetricValueState.UNKNOWN,
                "episode_horizon_open",
                signals=(
                    _count("scope.changes", len(features.scope_changes)),
                    _unknown("scope.pending_right_edge"),
                ),
            )
        return _known(
            len(features.acknowledged_scope_changes),
            len(features.scope_changes),
            features.acknowledged_scope_changes,
            "scope_change_acknowledgement_candidates",
            (
                _count("scope.changes", len(features.scope_changes)),
                _count("scope.acknowledged", len(features.acknowledged_scope_changes)),
            ),
        )


class ReworkCandidateRateCalculator(_Calculator):
    definition = COLLABORATION_AVOIDABLE_REWORK_RATE
    required_kind_groups = (
        frozenset({TextMessageKind.RESPONSE}),
        frozenset({TextMessageKind.FEEDBACK}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.feedback_turns:
            return _empty(MetricValueState.UNKNOWN, "feedback_turns_unobserved")
        return _known(
            len(features.correction_feedback),
            len(features.feedback_turns),
            features.correction_feedback,
            "rework_marker_candidates",
            (
                _count("rework.feedback_turns", len(features.feedback_turns)),
                _count("rework.candidates", len(features.correction_feedback)),
            ),
        )


class DecompositionCoverageCalculator(_Calculator):
    definition = LOGIC_DECOMPOSITION_COVERAGE
    required_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
        frozenset({TextMessageKind.PLAN}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _empty(MetricValueState.UNKNOWN, "requirements_unknown")
        linked = {requirement for requirement, _ in features.requirement_plan_links}
        evidence = tuple(linked) + tuple(plan for _, plan in features.requirement_plan_links)
        return _known(
            len(linked),
            len(features.requirements),
            evidence,
            "requirement_plan_link_candidates",
            (
                _count("decomposition.requirements", len(features.requirements)),
                _count("decomposition.linked", len(linked)),
            ),
        )


class HypothesisTestLinkageCalculator(_Calculator):
    definition = LOGIC_HYPOTHESIS_TEST_LINKAGE

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.hypotheses:
            return _empty(MetricValueState.UNKNOWN, "hypotheses_unobserved")
        return _empty(
            MetricValueState.ABSTAINED,
            "objective_verification_stream_required",
            signals=(
                _count("hypothesis.detected", len(features.hypotheses)),
                _unknown("hypothesis.verified_links"),
            ),
        )


class DecisionRationaleCalculator(_Calculator):
    definition = LOGIC_DECISION_RATIONALE_COVERAGE
    required_kind_groups = (frozenset({TextMessageKind.DECISION}),)

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        decisions = tuple(clause for clause in features.clauses if clause.kind is TextMessageKind.DECISION)
        if not decisions:
            return _empty(MetricValueState.UNKNOWN, "decisions_unknown")
        with_rationale = tuple(clause for clause in decisions if _RATIONALE.search(clause.text))
        return _known(
            len(with_rationale),
            len(decisions),
            with_rationale,
            "decision_rationale_cues",
            (
                _count("decision.items", len(decisions)),
                _count("decision.with_rationale", len(with_rationale)),
            ),
        )


class RequirementActionTraceabilityCalculator(_Calculator):
    definition = LOGIC_REQUIREMENT_ACTION_TRACEABILITY
    required_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
        frozenset({TextMessageKind.ACTION}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _empty(MetricValueState.UNKNOWN, "requirements_unknown")
        actions = tuple(clause for clause in features.clauses if clause.kind is TextMessageKind.ACTION)
        linked = tuple(
            requirement
            for requirement in features.requirements
            if _later_related(requirement, actions) is not None
        )
        return _known(
            len(linked),
            len(features.requirements),
            linked,
            "requirement_action_link_candidates",
            (
                _count("trace.requirements", len(features.requirements)),
                _count("trace.linked", len(linked)),
            ),
        )


class OpenLoopClosureCalculator(_Calculator):
    definition = LOGIC_OPEN_LOOP_CLOSURE
    required_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK, TextMessageKind.RESPONSE}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.questions:
            return _empty(MetricValueState.UNKNOWN, "questions_unobserved")
        non_question_clauses = tuple(
            clause for clause in features.clauses if clause not in features.questions
        )
        if _has_open_episode_horizon(
            features.questions,
            features.closed_questions,
            non_question_clauses,
            opposite_role=True,
        ):
            return _empty(
                MetricValueState.UNKNOWN,
                "episode_horizon_open",
                signals=(
                    _count("loops.questions", len(features.questions)),
                    _unknown("loops.pending_right_edge"),
                ),
            )
        return _known(
            len(features.closed_questions),
            len(features.questions),
            features.closed_questions,
            "question_response_link_candidates",
            (
                _count("loops.questions", len(features.questions)),
                _count("loops.closed", len(features.closed_questions)),
            ),
        )


class AgentClaimGroundingCalculator(_Calculator):
    definition = OUTCOME_AGENT_CLAIM_GROUNDING

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        claims = tuple(
            clause
            for clause in features.agent_clauses
            if clause.kind in {TextMessageKind.RESPONSE, TextMessageKind.SUMMARY}
        )
        if not claims:
            return _empty(MetricValueState.UNKNOWN, "agent_claims_unobserved")
        return _empty(
            MetricValueState.ABSTAINED,
            "objective_evidence_stream_required",
            signals=(
                _count("grounding.claim_candidates", len(claims)),
                _unknown("grounding.objective_links"),
            ),
        )


class VerificationStrategyCalculator(_Calculator):
    definition = OUTCOME_VERIFICATION_STRATEGY_ADEQUACY
    required_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
        frozenset({TextMessageKind.PLAN, TextMessageKind.RESPONSE, TextMessageKind.VERIFICATION}),
    )

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _empty(MetricValueState.UNKNOWN, "requirements_unknown")
        linked = {requirement for requirement, _ in features.verification_strategy_links}
        evidence = tuple(linked) + tuple(strategy for _, strategy in features.verification_strategy_links)
        return _known(
            len(linked),
            len(features.requirements),
            evidence,
            "verification_strategy_link_candidates",
            (
                _count("strategy.requirements", len(features.requirements)),
                _count("strategy.linked", len(linked)),
            ),
        )


class FirstPassVerificationCalculator(_Calculator):
    definition = OUTCOME_FIRST_PASS_VERIFICATION

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        return _empty(
            MetricValueState.ABSTAINED,
            "objective_verification_episode_required",
            signals=(_unknown("verification.first_episode"),),
        )


class VerifiedRequirementCoverageCalculator(_Calculator):
    definition = OUTCOME_VERIFIED_REQUIREMENT_COVERAGE

    def calculate(self, context: P1TextAnalysisInput, features: _CoachingFeatures) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _empty(MetricValueState.UNKNOWN, "requirements_unknown")
        return _empty(
            MetricValueState.ABSTAINED,
            "objective_verification_stream_required",
            signals=(
                _count("verified.requirements", len(features.requirements)),
                _unknown("verified.passing_links"),
            ),
        )


COACHING_METRIC_CALCULATORS = (
    TaskDefinitionCalculator(),
    ProblemEvidenceCalculator(),
    ContextSufficiencyCalculator(),
    ConstraintPrecisionCalculator(),
    AcceptanceTestabilityCalculator(),
    DeliverableContractCalculator(),
    AmbiguityResolutionCalculator(),
    ClarificationYieldCalculator(),
    ExplorationConversionCalculator(),
    ScopeChangeDisciplineCalculator(),
    ReworkCandidateRateCalculator(),
    DecompositionCoverageCalculator(),
    HypothesisTestLinkageCalculator(),
    DecisionRationaleCalculator(),
    RequirementActionTraceabilityCalculator(),
    OpenLoopClosureCalculator(),
    AgentClaimGroundingCalculator(),
    VerificationStrategyCalculator(),
    FirstPassVerificationCalculator(),
    VerifiedRequirementCoverageCalculator(),
)

COACHING_METRIC_REGISTRY = TextMetricRegistry(
    definitions=COACHING_METRIC_DEFINITIONS,
    calculators=COACHING_METRIC_CALCULATORS,  # type: ignore[arg-type]
)

DEFAULT_COACHING_METRIC_ENGINE = TextMetricEngine(
    registry=COACHING_METRIC_REGISTRY,
    extractor=CoachingTextFeatureExtractor(),  # type: ignore[arg-type]
    pack_key=COACHING_METRIC_PACK_KEY,
    pack_version=COACHING_METRIC_PACK_VERSION,
    engine_version=COACHING_METRIC_ENGINE_VERSION,
    rubric_version=COACHING_METRIC_RUBRIC_VERSION,
    model_plan_identity=(
        "model",
        "none",
        "activation",
        "deterministic-candidate",
        "evidence-capability-catalog",
        COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
    ),
)


__all__ = [
    "COACHING_METRIC_ALGORITHM_ID",
    "COACHING_METRIC_ALGORITHM_VERSION",
    "COACHING_METRIC_CALCULATORS",
    "COACHING_METRIC_DEFINITIONS",
    "COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION",
    "COACHING_METRIC_ENGINE_VERSION",
    "COACHING_METRIC_PACK_KEY",
    "COACHING_METRIC_PACK_VERSION",
    "COACHING_METRIC_REGISTRY",
    "COACHING_METRIC_RUBRIC_VERSION",
    "CoachingTextFeatureExtractor",
    "DEFAULT_COACHING_METRIC_ENGINE",
]
