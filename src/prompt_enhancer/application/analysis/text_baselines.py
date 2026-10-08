"""Conservative, model-free EN/PL baselines for the P1 text metric pack.

The rules in this module are useful executable baselines, not calibrated truth.
They consume only an already-redacted, explicitly authorized conversation window
and return content-free observations.  No provider read, network access, model
download, embedding, transcript persistence, or assistant completion claim is
performed here.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from itertools import combinations
import re
from types import MappingProxyType

from ...domain import DataTier, MetricObservation, MetricSource, SAFE_VERSION_PATTERN
from ..persistence import MetricValueState
from .text_contracts import (
    ConstraintKind,
    DeliverableSlot,
    EphemeralRedactedMessage,
    EvidenceOrigin,
    GoalSlot,
    MetricApplicability,
    MetricDirection,
    MetricFraction,
    P1LocalAnalysisGrant,
    P1TextAnalysisInput,
    TEXT_METRIC_SCHEMA_VERSION,
    TextAnalysisPrivacyError,
    TextLanguage,
    TextMessageKind,
    TextMetricCalculation,
    TextMetricDefinition,
    TextMetricEvidence,
    TextMetricProvenance,
    TextMetricResult,
    TextMetricSignal,
    TextMetricSignalStatus,
    TextRole,
)


TEXT_METRIC_ENGINE_VERSION = "text-rules-en-pl-1"
TEXT_METRIC_ALGORITHM_ID = "rules.en-pl.p1-text"
TEXT_METRIC_ALGORITHM_VERSION = "1"
TEXT_METRIC_RUBRIC_VERSION = "prompt-logic-rubric-1"
DEFAULT_TEXT_METRIC_PACK_KEY = "core.redacted-text.prompt-logic"
DEFAULT_TEXT_METRIC_PACK_VERSION = 1
MAX_RESULT_EVIDENCE = 32


PROMPT_GOAL_DEFINITION = TextMetricDefinition(
    key="prompt.goal_definition",
    version=1,
    dimension="prompt",
    display_name="Goal definition",
    description="Detected action, target, and intended-outcome slots divided by the explicitly expected goal slots.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
PROMPT_CONSTRAINT_RESOLUTION = TextMetricDefinition(
    key="prompt.constraint_resolution",
    version=1,
    dimension="prompt",
    display_name="Constraint resolution",
    description="Expected constraint categories expressed without unresolved-language markers divided by expected categories.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
PROMPT_COMPLETION_EVALUABILITY = TextMetricDefinition(
    key="prompt.completion_evaluability",
    version=1,
    dimension="prompt",
    display_name="Completion evaluability",
    description="Requested outcomes with an observable check divided by explicitly expected or conservatively extracted outcomes.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
PROMPT_DELIVERABLE_CONTRACT = TextMetricDefinition(
    key="prompt.deliverable_contract",
    version=1,
    dimension="prompt",
    display_name="Deliverable contract",
    description="Detected deliverable slots divided by the task profile's explicitly expected slots.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
PROMPT_OPEN_DECISION_LOAD = TextMetricDefinition(
    key="prompt.open_decision_load",
    version=1,
    dimension="prompt",
    display_name="Open decision load",
    description="Active prompt clauses containing unresolved choice markers divided by active prompt clauses; deliberate delegation is excluded.",
    unit="risk_ratio",
    direction=MetricDirection.LOWER_IS_BETTER,
)
LOGIC_REQUIREMENT_ACTION_TRACEABILITY = TextMetricDefinition(
    key="logic.requirement_action_traceability",
    version=1,
    dimension="logic",
    display_name="Requirement-to-action traceability",
    description="Active requirement clauses with a conservative lexical link to an observed action event divided by active requirements.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
LOGIC_PLAN_STATE_ACCOUNTING = TextMetricDefinition(
    key="logic.plan_state_accounting",
    version=1,
    dimension="logic",
    display_name="Plan-state accounting",
    description="Plan items with an explicit state or a conservative link to an observed action divided by plan items.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
LOGIC_DECISION_RATIONALE_COVERAGE = TextMetricDefinition(
    key="logic.decision_rationale_coverage",
    version=1,
    dimension="logic",
    display_name="Decision-rationale coverage",
    description="Observed decision clauses containing an explicit rationale marker divided by observed decisions.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)
LOGIC_SCOPED_CONSISTENCY_CANDIDATE_RATE = TextMetricDefinition(
    key="logic.scoped_consistency_candidate_rate",
    version=1,
    dimension="logic",
    display_name="Scoped consistency candidates",
    description="Differing values among comparable, non-superseded typed claims divided by comparable claim pairs.",
    unit="risk_ratio",
    direction=MetricDirection.LOWER_IS_BETTER,
)
LOGIC_CONVERSATION_LOOP_CLOSURE = TextMetricDefinition(
    key="logic.conversation_loop_closure",
    version=1,
    dimension="logic",
    display_name="Conversation-loop closure",
    description="Detected actionable questions linked to a later opposite-role answer and not subsequently reopened divided by detected questions.",
    unit="ratio",
    direction=MetricDirection.HIGHER_IS_BETTER,
)


TEXT_METRIC_DEFINITIONS = (
    PROMPT_GOAL_DEFINITION,
    PROMPT_CONSTRAINT_RESOLUTION,
    PROMPT_COMPLETION_EVALUABILITY,
    PROMPT_DELIVERABLE_CONTRACT,
    PROMPT_OPEN_DECISION_LOAD,
    LOGIC_REQUIREMENT_ACTION_TRACEABILITY,
    LOGIC_PLAN_STATE_ACCOUNTING,
    LOGIC_DECISION_RATIONALE_COVERAGE,
    LOGIC_SCOPED_CONSISTENCY_CANDIDATE_RATE,
    LOGIC_CONVERSATION_LOOP_CLOSURE,
)


_CLAUSE_SPLIT = re.compile(r"(?:\r?\n)+|(?<=[.!?;])\s+")
_BULLET_PREFIX = re.compile(r"^\s*(?:[-*•]|\d+[.)]|\[[ xX-]\])\s*")
_TOKEN = re.compile(r"[^\W_]+(?:[-/.][^\W_]+)*", re.UNICODE)

_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "and",
        "are",
        "as",
        "be",
        "by",
        "can",
        "do",
        "for",
        "from",
        "in",
        "is",
        "it",
        "of",
        "on",
        "or",
        "that",
        "the",
        "this",
        "to",
        "we",
        "with",
        "aby",
        "albo",
        "czy",
        "dla",
        "do",
        "i",
        "jest",
        "lub",
        "na",
        "oraz",
        "po",
        "się",
        "ta",
        "ten",
        "to",
        "w",
        "z",
        "że",
    }
)

_ACTION = re.compile(
    r"\b(?:add|build|change|check|create|design|display|export|fix|implement|"
    r"improve|integrate|make|measure|render|run|show|test|update|validate|verify|"
    r"zbuduj|dodaj|utwórz|stwórz|zmień|sprawdź|napraw|zaimplementuj|ulepsz|"
    r"zintegruj|mierz|pokaż|testuj|zaktualizuj|zweryfikuj)\b",
    re.IGNORECASE,
)
_REQUIREMENT_MODAL = re.compile(
    r"\b(?:must|must not|needs? to|should|shall|has to|musi|nie może|powinien|"
    r"powinna|powinno|należy)\b",
    re.IGNORECASE,
)
_OUTCOME = re.compile(
    r"\b(?:so that|so users?|in order to|to allow|to enable|so we can|"
    r"aby|żeby|tak aby|dzięki temu)\b",
    re.IGNORECASE,
)
_EVALUABLE = re.compile(
    r"\b(?:acceptance|assert|equals?|exactly|exists?|must pass|passes|returns?|"
    r"test(?:s|ed)?|threshold|verify|verified|visible|without errors?|"
    r"akceptacj|dokładnie|istnieje|musi przejść|przechodzi|test|próg|"
    r"zwraca|zweryfik|widoczn)\w*\b|(?:<=|>=|==|<|>)\s*\d+|\b\d+(?:\.\d+)?%",
    re.IGNORECASE,
)
_VAGUE = re.compile(
    r"\b(?:and so on|maybe|probably|somehow|something|or something|"
    r"i tak dalej|jakoś|może|chyba|coś|lub coś)\b",
    re.IGNORECASE,
)
_DECISION = re.compile(
    r"\b(?:choose|decide|either|option|which|whether|or something|maybe|"
    r"wybierz|zdecyduj|opcja|który|która|które|czy|lub coś|może)\b",
    re.IGNORECASE,
)
_DELEGATION = re.compile(
    r"\b(?:you (?:can )?choose|use your (?:best )?judg(?:e)?ment|choose the best|"
    r"decide based on|wybierz najleps|zdecyduj na podstawie|według twojej oceny)\b",
    re.IGNORECASE,
)
_RATIONALE = re.compile(
    r"\b(?:because|due to|given that|in order to|so that|to preserve|trade-?off|"
    r"because of|ponieważ|dlatego że|ze względu|aby zachować|kompromis)\b",
    re.IGNORECASE,
)
_PLAN_STATE = re.compile(
    r"(?:^|\s)(?:\[[xX]\]|done|completed|blocked|deferred|revised|in progress|"
    r"finished|gotowe|ukończone|zablokowane|odroczone|zmienione|w toku)(?:\s|$)",
    re.IGNORECASE,
)
_QUESTION_PREFIX = re.compile(
    r"^\s*(?:what|which|who|where|when|why|how|can|could|should|would|"
    r"co|który|która|które|kto|gdzie|kiedy|dlaczego|jak|czy)\b",
    re.IGNORECASE,
)
_ASSERTION = re.compile(
    r"^\s*(?P<key>[\wąćęłńóśźż -]{2,48}?)\s+"
    r"(?:is|equals|must be|jest|wynosi|musi być)\s+"
    r"(?P<value>[\wąćęłńóśźż.+/-]{1,32})\s*[.!]?\s*$",
    re.IGNORECASE,
)

_CONSTRAINT_PATTERNS = {
    ConstraintKind.PRIVACY: re.compile(
        r"\b(?:private|privacy|personal data|redact|local only|offline|"
        r"prywatn|dane osobowe|redakc|tylko lokaln|offline)\w*\b",
        re.IGNORECASE,
    ),
    ConstraintKind.COST: re.compile(
        r"\b(?:free|no api fees?|budget|cost|bezpłatn|darmow|bez opłat|budżet|koszt)\w*\b",
        re.IGNORECASE,
    ),
    ConstraintKind.PLATFORM: re.compile(
        r"\b(?:windows|linux|macos|android|ios|browser|desktop|mobile|"
        r"przeglądark|komputer|mobiln)\w*\b",
        re.IGNORECASE,
    ),
    ConstraintKind.VERSION: re.compile(
        r"\b(?:version|revision|compatible with|pin(?:ned)?|wersj|rewizj|zgodn)\w*\b",
        re.IGNORECASE,
    ),
    ConstraintKind.SCOPE: re.compile(
        r"\b(?:only|must not|never|without|scope|for now|tylko|nie wolno|nigdy|bez|zakres|na razie)\b",
        re.IGNORECASE,
    ),
    ConstraintKind.PERFORMANCE: re.compile(
        r"\b(?:fast|latency|throughput|memory|compact|speed|szybk|opóźnien|przepustow|pamięć|kompakt)\w*\b",
        re.IGNORECASE,
    ),
    ConstraintKind.DELIVERY: re.compile(
        r"\b(?:deadline|today|before|after|first|one by one|termin|dzisiaj|przed|po|najpierw|jeden po drugim)\b",
        re.IGNORECASE,
    ),
    ConstraintKind.SAFETY: re.compile(
        r"\b(?:safe|safety|read-only|do not delete|no deletion|bezpiecz|tylko do odczytu|nie usuw)\w*\b",
        re.IGNORECASE,
    ),
}

_DELIVERABLE_PATTERNS = {
    DeliverableSlot.ARTIFACT: re.compile(
        r"\b(?:api|app|application|card|component|dashboard|document|file|image|"
        r"report|script|view|aplikacj|karta|komponent|panel|dokument|plik|obraz|"
        r"raport|skrypt|widok)\w*\b",
        re.IGNORECASE,
    ),
    DeliverableSlot.FORMAT: re.compile(
        r"\b(?:csv|html|json|markdown|pdf|png|svg|table|yaml|format|tabela|format)\b",
        re.IGNORECASE,
    ),
    DeliverableSlot.LOCATION: re.compile(
        r"\b(?:endpoint|page|route|screen|view|dashboard|strona|trasa|ekran|widok|panel)\b",
        re.IGNORECASE,
    ),
    DeliverableSlot.AUDIENCE: re.compile(
        r"\b(?:user|users|reviewer|team|engineer|client|użytkownik|recenzent|zespół|inżynier|klient)\w*\b",
        re.IGNORECASE,
    ),
    DeliverableSlot.INTERFACE: re.compile(
        r"\b(?:api|button|cli|endpoint|interface|menu|route|ui|przycisk|interfejs|trasa)\b",
        re.IGNORECASE,
    ),
    DeliverableSlot.COMPATIBILITY: re.compile(
        r"\b(?:compatible|works? (?:on|with)|windows|linux|macos|android|ios|browser|"
        r"zgodn|działa (?:na|z)|przeglądark)\w*\b",
        re.IGNORECASE,
    ),
}


#: Public, read-only aliases so a later contract registry can reuse the exact
#: reviewed slot vocabulary instead of restating it with different coverage.
CONSTRAINT_SLOT_PATTERNS = MappingProxyType(dict(_CONSTRAINT_PATTERNS))
DELIVERABLE_SLOT_PATTERNS = MappingProxyType(dict(_DELIVERABLE_PATTERNS))


@dataclass(frozen=True, slots=True, repr=False)
class _Clause:
    message_id: str
    sequence: int
    role: TextRole
    kind: TextMessageKind
    scope_key: str
    origin: EvidenceOrigin
    text: str
    tokens: frozenset[str]


@dataclass(frozen=True, slots=True, repr=False)
class _Assertion:
    clause: _Clause
    key: str
    value: str


@dataclass(frozen=True, slots=True, repr=False)
class _TextFeatures:
    supported_language: bool
    available_message_kinds: frozenset[TextMessageKind]
    observed_message_kinds: frozenset[TextMessageKind]
    analyzable_message_kinds: frozenset[TextMessageKind]
    analyzable_message_count: int
    active_clauses: tuple[_Clause, ...]
    prompt_clauses: tuple[_Clause, ...]
    requirements: tuple[_Clause, ...]
    actions: tuple[_Clause, ...]
    plan_items: tuple[_Clause, ...]
    decisions: tuple[_Clause, ...]
    questions: tuple[_Clause, ...]
    goal_evidence: dict[GoalSlot, tuple[_Clause, ...]]
    constraint_evidence: dict[ConstraintKind, tuple[_Clause, ...]]
    resolved_constraints: frozenset[ConstraintKind]
    evaluable_requirements: tuple[_Clause, ...]
    deliverable_evidence: dict[DeliverableSlot, tuple[_Clause, ...]]
    open_decisions: tuple[_Clause, ...]
    requirement_action_links: tuple[tuple[_Clause, _Clause], ...]
    accounted_plan_items: tuple[_Clause, ...]
    decisions_with_rationale: tuple[_Clause, ...]
    comparable_claim_pairs: tuple[tuple[_Assertion, _Assertion], ...]
    conflicting_claim_pairs: tuple[tuple[_Assertion, _Assertion], ...]
    closed_questions: tuple[_Clause, ...]


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        token.casefold()
        for token in _TOKEN.findall(text)
        if token.casefold() not in _STOPWORDS and len(token) > 1
    )


def _similarity(left: _Clause, right: _Clause) -> float:
    if not left.tokens or not right.tokens:
        return 0.0
    return len(left.tokens & right.tokens) / len(left.tokens | right.tokens)


def _clauses(
    message: EphemeralRedactedMessage,
    *,
    focus_sequence: int,
) -> tuple[_Clause, ...]:
    origin = (
        EvidenceOrigin.DIRECT
        if message.sequence >= focus_sequence
        else EvidenceOrigin.INHERITED
    )
    values: list[_Clause] = []
    for raw_clause in _CLAUSE_SPLIT.split(message.text.get_secret_value()):
        text = _BULLET_PREFIX.sub("", raw_clause).strip()
        if not text:
            continue
        values.append(
            _Clause(
                message_id=message.message_id,
                sequence=message.sequence,
                role=message.role,
                kind=message.kind,
                scope_key=message.scope_key,
                origin=origin,
                text=text,
                tokens=_tokens(text),
            )
        )
    return tuple(values)


def _first_evidence(
    clauses: tuple[_Clause, ...],
) -> tuple[_Clause, ...]:
    seen: set[str] = set()
    result: list[_Clause] = []
    for clause in clauses:
        if clause.message_id not in seen:
            seen.add(clause.message_id)
            result.append(clause)
    return tuple(result)


def _target_present(clause: _Clause) -> bool:
    match = _ACTION.search(clause.text)
    if match is None:
        return False
    return bool(_tokens(clause.text[match.end() :]))


def _extract_assertion(clause: _Clause) -> _Assertion | None:
    match = _ASSERTION.match(clause.text.casefold())
    if match is None:
        return None
    key = " ".join(_tokens(match.group("key")))
    if not key:
        return None
    return _Assertion(clause=clause, key=key, value=match.group("value").casefold())


class DeterministicTextFeatureExtractor:
    """Build a bounded ephemeral feature snapshot from redacted EN/PL text."""

    required_tier = DataTier.REDACTED_CONTENT
    algorithm_id = TEXT_METRIC_ALGORITHM_ID
    algorithm_version = TEXT_METRIC_ALGORITHM_VERSION

    def extract(self, context: P1TextAnalysisInput) -> _TextFeatures:
        messages_by_id = {message.message_id: message for message in context.messages}
        focus_sequence = messages_by_id[context.focus_message_id].sequence
        superseded_ids = {
            superseded
            for message in context.messages
            for superseded in message.supersedes_message_ids
        }
        active_messages = tuple(
            message
            for message in context.messages
            if message.message_id not in superseded_ids
        )
        analyzable_messages = tuple(
            message
            for message in active_messages
            if message.language
            in {TextLanguage.ENGLISH, TextLanguage.POLISH, TextLanguage.MIXED}
        )
        active_clauses = tuple(
            clause
            for message in analyzable_messages
            for clause in _clauses(message, focus_sequence=focus_sequence)
        )
        prompt_clauses = tuple(
            clause
            for clause in active_clauses
            if clause.role is TextRole.USER
            and clause.kind in {TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}
        )
        requirements = tuple(
            clause
            for clause in prompt_clauses
            if not (
                clause.text.rstrip().endswith("?")
                or _QUESTION_PREFIX.search(clause.text)
            )
            and (
                _ACTION.search(clause.text)
                or _REQUIREMENT_MODAL.search(clause.text)
                or any(
                    pattern.search(clause.text)
                    for pattern in _CONSTRAINT_PATTERNS.values()
                )
            )
        )
        actions = tuple(
            clause
            for clause in active_clauses
            if clause.role is TextRole.AGENT and clause.kind is TextMessageKind.ACTION
        )
        plan_items = tuple(
            clause for clause in active_clauses if clause.kind is TextMessageKind.PLAN
        )
        decisions = tuple(
            clause for clause in active_clauses if clause.kind is TextMessageKind.DECISION
        )
        questions = tuple(
            clause
            for clause in active_clauses
            if clause.text.rstrip().endswith("?") or _QUESTION_PREFIX.search(clause.text)
        )

        goal_evidence: dict[GoalSlot, tuple[_Clause, ...]] = {
            GoalSlot.ACTION: tuple(
                clause for clause in prompt_clauses if _ACTION.search(clause.text)
            ),
            GoalSlot.TARGET: tuple(
                clause for clause in prompt_clauses if _target_present(clause)
            ),
            GoalSlot.OUTCOME: tuple(
                clause for clause in prompt_clauses if _OUTCOME.search(clause.text)
            ),
        }
        constraint_evidence = {
            kind: tuple(
                clause for clause in prompt_clauses if pattern.search(clause.text)
            )
            for kind, pattern in _CONSTRAINT_PATTERNS.items()
        }
        resolved_constraints = frozenset(
            kind
            for kind, clauses in constraint_evidence.items()
            if clauses and all(not _VAGUE.search(clause.text) for clause in clauses)
        )
        evaluable_requirements = tuple(
            clause for clause in requirements if _EVALUABLE.search(clause.text)
        )
        deliverable_evidence = {
            slot: tuple(
                clause for clause in prompt_clauses if pattern.search(clause.text)
            )
            for slot, pattern in _DELIVERABLE_PATTERNS.items()
        }
        open_decisions = tuple(
            clause
            for clause in prompt_clauses
            if _DECISION.search(clause.text) and not _DELEGATION.search(clause.text)
        )

        requirement_action_links = tuple(
            (requirement, action)
            for requirement in requirements
            for action in actions
            if _similarity(requirement, action) >= 0.2
        )
        accounted_plan_items = tuple(
            plan
            for plan in plan_items
            if _PLAN_STATE.search(plan.text)
            or any(_similarity(plan, action) >= 0.2 for action in actions)
        )
        decisions_with_rationale = tuple(
            decision for decision in decisions if _RATIONALE.search(decision.text)
        )

        assertions = tuple(
            assertion
            for clause in active_clauses
            if clause.kind in {
                TextMessageKind.RESPONSE,
                TextMessageKind.DECISION,
                TextMessageKind.SUMMARY,
            }
            if (assertion := _extract_assertion(clause)) is not None
        )
        comparable_claim_pairs = tuple(
            (left, right)
            for left, right in combinations(assertions, 2)
            if left.clause.scope_key == right.clause.scope_key and left.key == right.key
        )
        conflicting_claim_pairs = tuple(
            pair for pair in comparable_claim_pairs if pair[0].value != pair[1].value
        )

        closed_questions: list[_Clause] = []
        for question in questions:
            later_opposite = tuple(
                clause
                for clause in active_clauses
                if clause.sequence > question.sequence
                and clause.role is not question.role
                and clause not in questions
            )
            answer = next(
                (
                    clause
                    for clause in later_opposite
                    if _similarity(question, clause) >= 0.1
                    or clause.kind in {
                        TextMessageKind.RESPONSE,
                        TextMessageKind.FEEDBACK,
                        TextMessageKind.DECISION,
                    }
                ),
                None,
            )
            if answer is None:
                continue
            reopened = any(
                later.sequence > answer.sequence
                and later.role is question.role
                and _similarity(question, later) >= 0.25
                for later in questions
            )
            if not reopened:
                closed_questions.append(question)

        analyzable_message_count = sum(
            message.language
            in {TextLanguage.ENGLISH, TextLanguage.POLISH, TextLanguage.MIXED}
            for message in context.messages
        )
        return _TextFeatures(
            supported_language=analyzable_message_count > 0,
            available_message_kinds=context.available_message_kinds,
            observed_message_kinds=frozenset(
                message.kind for message in active_messages
            ),
            analyzable_message_kinds=frozenset(
                message.kind for message in analyzable_messages
            ),
            analyzable_message_count=analyzable_message_count,
            active_clauses=active_clauses,
            prompt_clauses=prompt_clauses,
            requirements=requirements,
            actions=actions,
            plan_items=plan_items,
            decisions=decisions,
            questions=questions,
            goal_evidence=goal_evidence,
            constraint_evidence=constraint_evidence,
            resolved_constraints=resolved_constraints,
            evaluable_requirements=evaluable_requirements,
            deliverable_evidence=deliverable_evidence,
            open_decisions=open_decisions,
            requirement_action_links=requirement_action_links,
            accounted_plan_items=accounted_plan_items,
            decisions_with_rationale=decisions_with_rationale,
            comparable_claim_pairs=comparable_claim_pairs,
            conflicting_claim_pairs=conflicting_claim_pairs,
            closed_questions=tuple(closed_questions),
        )


def _without_value(
    state: MetricValueState,
    explanation_code: str,
    signals: tuple[TextMetricSignal, ...] = (),
) -> TextMetricCalculation:
    return TextMetricCalculation(
        value_state=state,
        explanation_code=explanation_code,
        signals=signals,
    )


def _known(
    numerator: int,
    denominator: int,
    evidence: tuple[_Clause, ...],
    explanation_code: str,
    signals: tuple[TextMetricSignal, ...],
) -> TextMetricCalculation:
    safe_evidence = tuple(
        TextMetricEvidence(message_id=clause.message_id, origin=clause.origin)
        for clause in _first_evidence(evidence)[:MAX_RESULT_EVIDENCE]
    )
    return TextMetricCalculation(
        value_state=MetricValueState.KNOWN,
        fraction=MetricFraction(numerator=numerator, denominator=denominator),
        evidence=safe_evidence,
        signals=signals,
        explanation_code=explanation_code,
    )


def _binary_signal(code: str, detected: bool) -> TextMetricSignal:
    return TextMetricSignal(
        code=code,
        status=(
            TextMetricSignalStatus.DETECTED
            if detected
            else TextMetricSignalStatus.MISSING
        ),
        count=1 if detected else 0,
    )


def _counted_signal(code: str, count: int) -> TextMetricSignal:
    return TextMetricSignal(
        code=code,
        status=TextMetricSignalStatus.COUNTED,
        count=count,
    )


def _unknown_signal(code: str) -> TextMetricSignal:
    return TextMetricSignal(
        code=code,
        status=TextMetricSignalStatus.UNKNOWN,
    )


class _BaseCalculator:
    definition: TextMetricDefinition
    required_message_kind_groups: tuple[frozenset[TextMessageKind], ...] = ()

    def _guard(
        self,
        context: P1TextAnalysisInput,
        features: _TextFeatures,
    ) -> TextMetricCalculation | None:
        applicability = context.task_profile.applicability_for(self.definition.key)
        if applicability is MetricApplicability.UNKNOWN:
            return _without_value(MetricValueState.UNKNOWN, "applicability_unknown")
        if applicability is MetricApplicability.NOT_APPLICABLE:
            return _without_value(
                MetricValueState.NOT_APPLICABLE,
                "explicitly_not_applicable",
            )
        if not context.text_extraction_complete:
            return _without_value(
                MetricValueState.ABSTAINED,
                "source_extraction_incomplete",
            )
        for group in self.required_message_kind_groups:
            if features.available_message_kinds.isdisjoint(group):
                return _without_value(
                    MetricValueState.ABSTAINED,
                    "message_kind_unavailable",
                )
            if features.observed_message_kinds.isdisjoint(group):
                return _without_value(
                    MetricValueState.UNKNOWN,
                    "message_kind_unobserved",
                )
            if features.analyzable_message_kinds.isdisjoint(group):
                return _without_value(
                    MetricValueState.ABSTAINED,
                    "unsupported_language",
                )
        if not features.supported_language:
            return _without_value(
                MetricValueState.ABSTAINED,
                "unsupported_language",
            )
        return None


class GoalDefinitionCalculator(_BaseCalculator):
    definition = PROMPT_GOAL_DEFINITION
    required_message_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
    )

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        expected = context.task_profile.expected_goal_slots
        if not expected:
            return _without_value(MetricValueState.ABSTAINED, "denominator_unknown")
        present = tuple(slot for slot in expected if features.goal_evidence[slot])
        evidence = tuple(
            clause for slot in present for clause in features.goal_evidence[slot]
        )
        signals = tuple(
            _binary_signal(f"goal.{slot.value}", bool(features.goal_evidence[slot]))
            for slot in expected
        )
        return _known(
            len(present),
            len(expected),
            evidence,
            "goal_slots_detected",
            signals,
        )


class ConstraintResolutionCalculator(_BaseCalculator):
    definition = PROMPT_CONSTRAINT_RESOLUTION
    required_message_kind_groups = GoalDefinitionCalculator.required_message_kind_groups

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        expected = context.task_profile.expected_constraint_kinds
        if not expected:
            return _without_value(
                MetricValueState.ABSTAINED,
                "denominator_unknown",
                (_unknown_signal("constraint.expected_categories"),),
            )
        resolved = tuple(
            kind for kind in expected if kind in features.resolved_constraints
        )
        evidence = tuple(
            clause
            for kind in expected
            for clause in features.constraint_evidence[kind]
        )
        return _known(
            len(resolved),
            len(expected),
            evidence,
            "constraint_categories_assessed",
            tuple(
                _binary_signal(
                    f"constraint.{kind.value}",
                    kind in features.resolved_constraints,
                )
                for kind in expected
            ),
        )


class CompletionEvaluabilityCalculator(_BaseCalculator):
    definition = PROMPT_COMPLETION_EVALUABILITY
    required_message_kind_groups = GoalDefinitionCalculator.required_message_kind_groups

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        denominator = context.task_profile.expected_outcome_count
        if denominator is None:
            denominator = len(features.requirements)
        if denominator == 0:
            return _without_value(MetricValueState.ABSTAINED, "denominator_unknown")
        numerator = min(len(features.evaluable_requirements), denominator)
        return _known(
            numerator,
            denominator,
            features.evaluable_requirements,
            "observable_checks_detected",
            (
                _counted_signal("completion.requirements", denominator),
                _counted_signal("completion.checkable", numerator),
            ),
        )


class DeliverableContractCalculator(_BaseCalculator):
    definition = PROMPT_DELIVERABLE_CONTRACT
    required_message_kind_groups = GoalDefinitionCalculator.required_message_kind_groups

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        expected = context.task_profile.expected_deliverable_slots
        if not expected:
            return _without_value(
                MetricValueState.ABSTAINED,
                "denominator_unknown",
                (_unknown_signal("deliverable.expected_slots"),),
            )
        present = tuple(slot for slot in expected if features.deliverable_evidence[slot])
        evidence = tuple(
            clause for slot in present for clause in features.deliverable_evidence[slot]
        )
        return _known(
            len(present),
            len(expected),
            evidence,
            "deliverable_slots_detected",
            tuple(
                _binary_signal(
                    f"deliverable.{slot.value}",
                    bool(features.deliverable_evidence[slot]),
                )
                for slot in expected
            ),
        )


class OpenDecisionLoadCalculator(_BaseCalculator):
    definition = PROMPT_OPEN_DECISION_LOAD
    required_message_kind_groups = GoalDefinitionCalculator.required_message_kind_groups

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.prompt_clauses:
            return _without_value(MetricValueState.UNKNOWN, "prompt_window_empty")
        return _known(
            len(features.open_decisions),
            len(features.prompt_clauses),
            features.open_decisions,
            "unresolved_choice_markers",
            (
                _counted_signal(
                    "choices.prompt_clauses", len(features.prompt_clauses)
                ),
                _counted_signal(
                    "choices.marker_clauses", len(features.open_decisions)
                ),
            ),
        )


class RequirementActionTraceabilityCalculator(_BaseCalculator):
    definition = LOGIC_REQUIREMENT_ACTION_TRACEABILITY
    required_message_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
        frozenset({TextMessageKind.ACTION}),
    )

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.requirements:
            return _without_value(MetricValueState.UNKNOWN, "requirements_unknown")
        linked_requirements_set = {
            requirement for requirement, _ in features.requirement_action_links
        }
        linked_requirements = tuple(
            requirement
            for requirement in features.requirements
            if requirement in linked_requirements_set
        )
        linked_actions = tuple(
            action for requirement, action in features.requirement_action_links
            if requirement in linked_requirements
        )
        return _known(
            len(linked_requirements),
            len(features.requirements),
            linked_requirements + linked_actions,
            "lexical_requirement_action_links",
            (
                _counted_signal("trace.requirements", len(features.requirements)),
                _counted_signal("trace.linked", len(linked_requirements)),
            ),
        )


class PlanStateAccountingCalculator(_BaseCalculator):
    definition = LOGIC_PLAN_STATE_ACCOUNTING
    required_message_kind_groups = (frozenset({TextMessageKind.PLAN}),)

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.plan_items:
            return _without_value(MetricValueState.UNKNOWN, "plan_items_unknown")
        denominator = len(features.plan_items)
        return _known(
            len(features.accounted_plan_items),
            denominator,
            features.accounted_plan_items,
            "plan_items_accounted",
            (
                _counted_signal("plan.items", denominator),
                _counted_signal(
                    "plan.accounted", len(features.accounted_plan_items)
                ),
            ),
        )


class DecisionRationaleCoverageCalculator(_BaseCalculator):
    definition = LOGIC_DECISION_RATIONALE_COVERAGE
    required_message_kind_groups = (frozenset({TextMessageKind.DECISION}),)

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.decisions:
            return _without_value(MetricValueState.UNKNOWN, "decisions_unknown")
        denominator = len(features.decisions)
        return _known(
            len(features.decisions_with_rationale),
            denominator,
            features.decisions_with_rationale,
            "decision_rationale_markers",
            (
                _counted_signal("rationale.decisions", denominator),
                _counted_signal(
                    "rationale.with_marker",
                    len(features.decisions_with_rationale),
                ),
            ),
        )


class ScopedConsistencyCandidateRateCalculator(_BaseCalculator):
    definition = LOGIC_SCOPED_CONSISTENCY_CANDIDATE_RATE
    required_message_kind_groups = (
        frozenset(
            {
                TextMessageKind.RESPONSE,
                TextMessageKind.DECISION,
                TextMessageKind.SUMMARY,
            }
        ),
    )

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.comparable_claim_pairs:
            return _without_value(
                MetricValueState.UNKNOWN,
                "comparable_claims_unknown",
            )
        evidence = tuple(
            assertion.clause
            for pair in features.conflicting_claim_pairs
            for assertion in pair
        )
        return _known(
            len(features.conflicting_claim_pairs),
            len(features.comparable_claim_pairs),
            evidence,
            "scoped_conflict_candidates",
            (
                _counted_signal(
                    "consistency.comparable_pairs",
                    len(features.comparable_claim_pairs),
                ),
                _counted_signal(
                    "consistency.conflict_candidates",
                    len(features.conflicting_claim_pairs),
                ),
            ),
        )


class ConversationLoopClosureCalculator(_BaseCalculator):
    definition = LOGIC_CONVERSATION_LOOP_CLOSURE
    required_message_kind_groups = (
        frozenset({TextMessageKind.REQUEST, TextMessageKind.FEEDBACK}),
        frozenset({TextMessageKind.RESPONSE, TextMessageKind.DECISION}),
    )

    def calculate(
        self, context: P1TextAnalysisInput, features: _TextFeatures
    ) -> TextMetricCalculation:
        if guard := self._guard(context, features):
            return guard
        if not features.questions:
            return _without_value(MetricValueState.UNKNOWN, "questions_unknown")
        return _known(
            len(features.closed_questions),
            len(features.questions),
            features.closed_questions,
            "question_answer_links",
            (
                _counted_signal("loops.questions", len(features.questions)),
                _counted_signal("loops.closed", len(features.closed_questions)),
            ),
        )


DETERMINISTIC_TEXT_CALCULATORS = (
    GoalDefinitionCalculator(),
    ConstraintResolutionCalculator(),
    CompletionEvaluabilityCalculator(),
    DeliverableContractCalculator(),
    OpenDecisionLoadCalculator(),
    RequirementActionTraceabilityCalculator(),
    PlanStateAccountingCalculator(),
    DecisionRationaleCoverageCalculator(),
    ScopedConsistencyCandidateRateCalculator(),
    ConversationLoopClosureCalculator(),
)


class TextMetricRegistry:
    """Explicit trusted registration with a definition/calculator order invariant."""

    def __init__(
        self,
        *,
        definitions: tuple[TextMetricDefinition, ...],
        calculators: tuple[_BaseCalculator, ...],
    ) -> None:
        definition_keys = tuple(definition.key for definition in definitions)
        calculator_keys = tuple(calculator.definition.key for calculator in calculators)
        if len(set(definition_keys)) != len(definition_keys):
            raise ValueError("text metric definitions cannot contain duplicates")
        if definition_keys != calculator_keys:
            raise ValueError(
                "text metric calculator order must exactly match definition order"
            )
        self.definitions = definitions
        self.calculators = calculators


DEFAULT_TEXT_METRIC_REGISTRY = TextMetricRegistry(
    definitions=TEXT_METRIC_DEFINITIONS,
    calculators=DETERMINISTIC_TEXT_CALCULATORS,
)


class TextMetricEngine:
    """Run the explicit deterministic pack inside an authorized P1 boundary."""

    def __init__(
        self,
        registry: TextMetricRegistry = DEFAULT_TEXT_METRIC_REGISTRY,
        extractor: DeterministicTextFeatureExtractor | None = None,
        *,
        pack_key: str = DEFAULT_TEXT_METRIC_PACK_KEY,
        pack_version: int = DEFAULT_TEXT_METRIC_PACK_VERSION,
        engine_version: str = TEXT_METRIC_ENGINE_VERSION,
        rubric_version: str = TEXT_METRIC_RUBRIC_VERSION,
        model_plan_identity: tuple[str, ...] = ("model", "none"),
    ) -> None:
        if SAFE_VERSION_PATTERN.fullmatch(pack_key) is None:
            raise ValueError("text metric pack key must be a safe identifier")
        if isinstance(pack_version, bool) or pack_version < 1:
            raise ValueError("text metric pack versions begin at one")
        for value in (engine_version, rubric_version, *model_plan_identity):
            if SAFE_VERSION_PATTERN.fullmatch(value) is None:
                raise ValueError("text metric plan identity must be content-free")
        if not model_plan_identity:
            raise ValueError("text metric model plan identity cannot be empty")
        self._registry = registry
        self._extractor = extractor or DeterministicTextFeatureExtractor()
        self._pack_key = pack_key
        self._pack_version = pack_version
        self._engine_version = engine_version
        self._rubric_version = rubric_version
        self._model_plan_identity = model_plan_identity

    @property
    def registry(self) -> TextMetricRegistry:
        return self._registry

    @property
    def engine_version(self) -> str:
        """Persistable identity of this engine implementation."""

        return self._engine_version

    @property
    def pack_key(self) -> str:
        return self._pack_key

    @property
    def pack_version(self) -> int:
        return self._pack_version

    @property
    def algorithm_id(self) -> str:
        """Identity of the composed extractor, not a global default."""

        return self._extractor.algorithm_id

    @property
    def algorithm_version(self) -> str:
        return self._extractor.algorithm_version

    @property
    def rubric_version(self) -> str:
        return self._rubric_version

    @property
    def model_plan_identity(self) -> tuple[str, ...]:
        """Canonical plan tokens for this deterministic no-model engine."""

        return self._model_plan_identity

    def compute(
        self,
        context: P1TextAnalysisInput,
        grant: P1LocalAnalysisGrant,
        *,
        pack_key: str = DEFAULT_TEXT_METRIC_PACK_KEY,
        pack_version: int = DEFAULT_TEXT_METRIC_PACK_VERSION,
        selected_metric_keys: tuple[str, ...] | None = None,
        cooperative_check: Callable[[], None] | None = None,
    ) -> tuple[TextMetricResult, ...]:
        if (
            grant.data_tier is not DataTier.REDACTED_CONTENT
            or not grant.consent_active
            or not grant.local_only
            or grant.content_persistence_allowed
            or grant.provider is not context.provider
            or grant.session_id != context.session_id
            or grant.analysis_window_fingerprint
            != context.analysis_window_fingerprint
        ):
            raise TextAnalysisPrivacyError(
                "local text-analysis capability does not match the selected window"
            )
        if pack_key != self._pack_key or pack_version != self._pack_version:
            raise ValueError("text metric engine does not own the requested pack")

        calculators = self._registry.calculators
        if selected_metric_keys is not None:
            if (
                not isinstance(selected_metric_keys, tuple)
                or not selected_metric_keys
                or selected_metric_keys != tuple(sorted(selected_metric_keys))
                or len(set(selected_metric_keys)) != len(selected_metric_keys)
                or any(
                    not isinstance(key, str)
                    or SAFE_VERSION_PATTERN.fullmatch(key) is None
                    for key in selected_metric_keys
                )
            ):
                raise ValueError(
                    "selected text metric keys must be unique and sorted"
                )
            calculators_by_key = {
                calculator.definition.key: calculator
                for calculator in self._registry.calculators
            }
            if not set(selected_metric_keys).issubset(calculators_by_key):
                raise ValueError("selected text metric key is not in the pack")
            # Select calculators before feature extraction and calculation.  The
            # shared extractor may still preprocess the authorized text window,
            # but no unselected metric calculator is invoked.
            calculators = tuple(
                calculators_by_key[key] for key in selected_metric_keys
            )

        if cooperative_check is not None:
            cooperative_check()
        try:
            features = self._extractor.extract(context)
        finally:
            if cooperative_check is not None:
                cooperative_check()
        results: list[TextMetricResult] = []
        for calculator in calculators:
            if cooperative_check is not None:
                cooperative_check()
            try:
                calculation = calculator.calculate(context, features)
            finally:
                if cooperative_check is not None:
                    cooperative_check()
            definition = calculator.definition
            applicability = context.task_profile.applicability_for(definition.key)
            fraction = calculation.fraction
            numeric_value = (
                fraction.numerator / fraction.denominator
                if fraction is not None
                else None
            )
            observation = MetricObservation(
                key=definition.key,
                version=definition.version,
                numeric_value=numeric_value,
                unit=definition.unit,
                source=MetricSource.DETERMINISTIC,
                observed_count=features.analyzable_message_count,
                eligible_count=context.eligible_message_count,
                coverage=(
                    features.analyzable_message_count
                    / context.eligible_message_count
                ),
                # Rule execution is deterministic, but the heuristic is not a
                # calibrated probability of correctness.
                confidence=None,
            )
            evidence = calculation.evidence
            results.append(
                TextMetricResult(
                    observation=observation,
                    value_state=calculation.value_state,
                    direction=definition.direction,
                    aggregation_method=definition.aggregation_method,
                    applicability=applicability,
                    evidence_data_tier=definition.required_tier,
                    fraction=fraction,
                    evidence=evidence,
                    signals=calculation.signals,
                    explanation_code=calculation.explanation_code,
                    error_code=calculation.error_code,
                    provenance=TextMetricProvenance(
                        provider=context.provider,
                        provider_version=context.provider_version,
                        adapter_version=context.adapter_version,
                        source_schema_version=context.source_schema_version,
                        content_schema_version=context.content_schema_version,
                        redactor_version=context.redactor_version,
                        analysis_window_fingerprint=(
                            context.analysis_window_fingerprint
                        ),
                        algorithm_id=self._extractor.algorithm_id,
                        algorithm_version=self._extractor.algorithm_version,
                        metric_schema_version=TEXT_METRIC_SCHEMA_VERSION,
                        model_id=None,
                        model_revision=None,
                        model_license=None,
                        tokenizer_id=None,
                        prompt_version=None,
                        rubric_version=self.rubric_version,
                        local_only=True,
                    ),
                )
            )
            result = results[-1]
            if (
                result.observation.key != definition.key
                or result.observation.version != definition.version
                or result.observation.unit != definition.unit
                or result.direction is not definition.direction
                or result.aggregation_method is not definition.aggregation_method
                or result.evidence_data_tier is not definition.required_tier
            ):
                raise RuntimeError(
                    "text metric calculator returned a result outside its definition"
                )
        return tuple(results)


DEFAULT_TEXT_METRIC_ENGINE = TextMetricEngine()
