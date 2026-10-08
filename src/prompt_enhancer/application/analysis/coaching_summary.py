"""Provider-neutral, content-free Coaching Loop v1 summary decisions.

The engine accepts only bounded numeric receipts and safe codes.  It cannot read
provider data, transcript text, labels, paths, or identifiers.  Its output is a
small coaching decision surface rather than an overall score or a claim about a
person.  Objective verification evidence is the sole outcome authority;
assistant completion claims are deliberately ignored for outcome status.
Deterministic strength and friction selections remain uncalibrated candidates
under an explicit versioned minimum-evidence policy.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import math
import re

from pydantic import Field, field_validator, model_validator

from ...domain import StrictModel


COACHING_SUMMARY_PACK_KEY = "coaching.loop"
COACHING_SUMMARY_PACK_VERSION = 1
COACHING_SUMMARY_ALGORITHM_ID = "rules.coaching-loop.summary"
COACHING_SUMMARY_ALGORITHM_VERSION = "1"
COACHING_RECOMMENDATION_POLICY_VERSION = 1
COACHING_CANDIDATE_POLICY_VERSION = 2
COACHING_DENOMINATOR_KIND_PRIORITY_VERSION = 1
COACHING_RULE_PRIORITY_VERSION = 1
COACHING_CANDIDATE_MIN_DENOMINATOR = 2
COACHING_CANDIDATE_MIN_COVERAGE = 0.75
COACHING_CANDIDATE_STRENGTH_FLOOR = 0.75
COACHING_CANDIDATE_FRICTION_CEILING = 0.25
COACHING_CANDIDATE_WILSON_Z = 1.959963984540054
MAX_COACHING_SUMMARY_SIGNALS = 64
MAX_COACHING_BASIS_CODES = 8
_OBJECTIVE_OUTCOME_METRIC = "outcome.objective_verification"
_HUMAN_OUTCOME_METRIC = "outcome.human_acceptance"

_SAFE_CODE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")
_PSEUDONYM_SHAPE = re.compile(r"^[a-f0-9]{64}$")


def _safe_code(value: str | None) -> str | None:
    if value is not None and (
        not _SAFE_CODE.fullmatch(value) or _PSEUDONYM_SHAPE.fullmatch(value)
    ):
        raise ValueError(
            "coaching summary values must be content-free non-identifier codes"
        )
    return value


def _safe_codes(values: tuple[str, ...]) -> tuple[str, ...]:
    if len(values) > MAX_COACHING_BASIS_CODES:
        raise ValueError("coaching evidence basis exceeds its fixed bound")
    if len(set(values)) != len(values):
        raise ValueError("coaching evidence basis cannot contain duplicates")
    return tuple(_safe_code(value) for value in values)  # type: ignore[arg-type,return-value]


class CoachingSignalState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSTAINED = "abstained"
    NOT_APPLICABLE = "not_applicable"


class CoachingApplicabilityState(StrEnum):
    APPLICABLE = "applicable"
    NOT_APPLICABLE = "not_applicable"
    UNKNOWN = "unknown"


class CoachingSignalDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"


class CoachingDenominatorKind(StrEnum):
    RUBRIC_FACTOR = "rubric_factor"
    EVENT_COUNT = "event_count"


class CoachingTaskType(StrEnum):
    IMPLEMENTATION = "implementation"
    DIAGNOSIS = "diagnosis"
    RESEARCH = "research"
    REVIEW = "review"
    PLANNING = "planning"
    UNKNOWN = "unknown"


class CoachingEvidenceKind(StrEnum):
    OBJECTIVE_VERIFICATION = "objective_verification"
    DETERMINISTIC_CANDIDATE = "deterministic_candidate"
    HUMAN_REVIEW = "human_review"
    ASSISTANT_CLAIM = "assistant_claim"


class CoachingEvidenceBasisCode(StrEnum):
    """Closed evidence categories; identifiers and free-form labels cannot enter."""

    OBJECTIVE_VERIFICATION_RESULTS = "objective.verification_results"
    HUMAN_ACCEPTANCE_DECISION = "human.acceptance_decision"
    RULE_FACTOR_COUNTS = "rule.factor_counts"
    RULE_LINK_COUNTS = "rule.link_counts"
    RULE_CORRECTION_COUNTS = "rule.correction_counts"
    ASSISTANT_COMPLETION_CLAIM = "assistant.completion_claim"


class CoachingEvidenceTier(StrEnum):
    METADATA = "metadata"
    REDACTED_CONTENT = "redacted_content"
    OBJECTIVE_EVENT = "objective_event"
    HUMAN_REVIEW = "human_review"


class CoachingDecisionState(StrEnum):
    CANDIDATE = "candidate"
    SUPPORTED = "supported"
    ABSTAINED = "abstained"


class CoachingOutcomeStatus(StrEnum):
    VERIFIED = "verified"
    FAILED = "failed"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class CoachingHumanAcceptanceStatus(StrEnum):
    ACCEPTED = "accepted"
    REJECTED = "rejected"
    UNKNOWN = "unknown"


class CoachingSourceProvenance(StrictModel):
    """Version identity for an immutable source receipt."""

    pack_key: str
    pack_version: int = Field(ge=1)
    algorithm_id: str
    algorithm_version: str

    _validate_codes = field_validator(
        "pack_key", "algorithm_id", "algorithm_version"
    )(_safe_code)


class CoachingSignalReceipt(StrictModel):
    """One bounded, content-free observation supplied to the summary engine."""

    metric_code: str
    metric_version: int = Field(ge=1)
    state: CoachingSignalState
    applicability: CoachingApplicabilityState
    direction: CoachingSignalDirection
    denominator_kind: CoachingDenominatorKind
    evidence_kind: CoachingEvidenceKind
    evidence_tier: CoachingEvidenceTier
    evidence_basis: tuple[CoachingEvidenceBasisCode, ...] = Field(
        default=(), max_length=MAX_COACHING_BASIS_CODES
    )
    numerator: int | None = Field(default=None, ge=0)
    denominator: int | None = Field(default=None, ge=1)
    coverage: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    task_terminal: bool | None = None
    outcome_eligible: bool | None = None
    evidence_relevant: bool | None = None
    evidence_complete: bool | None = None
    provenance: CoachingSourceProvenance

    _validate_metric = field_validator("metric_code")(_safe_code)

    @model_validator(mode="after")
    def validate_state(self) -> CoachingSignalReceipt:
        has_fraction = self.numerator is not None and self.denominator is not None
        if (self.numerator is None) != (self.denominator is None):
            raise ValueError("metric fraction fields must be supplied together")
        if has_fraction and self.numerator > self.denominator:
            raise ValueError("metric numerator cannot exceed its denominator")
        if self.state is CoachingSignalState.KNOWN:
            if (
                not has_fraction
                or self.coverage is None
                or self.applicability is not CoachingApplicabilityState.APPLICABLE
            ):
                raise ValueError("known coaching signals require a fraction and coverage")
        elif has_fraction or self.confidence is not None:
            raise ValueError("non-known coaching signals cannot claim a value or confidence")
        if (
            self.state is CoachingSignalState.NOT_APPLICABLE
        ) != (
            self.applicability is CoachingApplicabilityState.NOT_APPLICABLE
        ):
            raise ValueError(
                "not-applicable signal state and applicability must agree"
            )
        if (
            self.evidence_kind is CoachingEvidenceKind.OBJECTIVE_VERIFICATION
        ) != (self.evidence_tier is CoachingEvidenceTier.OBJECTIVE_EVENT):
            raise ValueError("objective verification requires the objective-event tier")
        if (self.evidence_kind is CoachingEvidenceKind.HUMAN_REVIEW) != (
            self.evidence_tier is CoachingEvidenceTier.HUMAN_REVIEW
        ):
            raise ValueError("human review requires the human-review tier")
        if self.evidence_kind is CoachingEvidenceKind.DETERMINISTIC_CANDIDATE:
            if self.confidence is not None:
                raise ValueError("uncalibrated deterministic candidates have unknown confidence")
            if self.evidence_tier is not CoachingEvidenceTier.REDACTED_CONTENT:
                raise ValueError("deterministic coaching candidates use redacted content")
            allowed_rule_basis = {
                CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,
                CoachingEvidenceBasisCode.RULE_LINK_COUNTS,
                CoachingEvidenceBasisCode.RULE_CORRECTION_COUNTS,
            }
            if not set(self.evidence_basis).issubset(allowed_rule_basis):
                raise ValueError(
                    "deterministic candidates require rule-count evidence basis"
                )
        outcome_fields = (
            self.task_terminal,
            self.outcome_eligible,
            self.evidence_relevant,
            self.evidence_complete,
        )
        if self.evidence_kind in {
            CoachingEvidenceKind.OBJECTIVE_VERIFICATION,
            CoachingEvidenceKind.HUMAN_REVIEW,
        }:
            if any(value is None for value in outcome_fields):
                raise ValueError("outcome authority requires complete eligibility flags")
            expected_basis = (
                CoachingEvidenceBasisCode.OBJECTIVE_VERIFICATION_RESULTS
                if self.evidence_kind is CoachingEvidenceKind.OBJECTIVE_VERIFICATION
                else CoachingEvidenceBasisCode.HUMAN_ACCEPTANCE_DECISION
            )
            if self.evidence_basis != (expected_basis,):
                raise ValueError("outcome authority requires its typed evidence basis")
            if self.denominator_kind is not CoachingDenominatorKind.EVENT_COUNT:
                raise ValueError("outcome authority requires an event-count denominator")
            if (
                self.evidence_kind is CoachingEvidenceKind.HUMAN_REVIEW
                and self.denominator != 1
            ):
                raise ValueError("human acceptance is a single typed decision")
        elif any(value is not None for value in outcome_fields):
            raise ValueError("coaching candidates and claims cannot carry outcome flags")
        if (
            self.evidence_kind is CoachingEvidenceKind.ASSISTANT_CLAIM
            and self.evidence_basis
            != (CoachingEvidenceBasisCode.ASSISTANT_COMPLETION_CLAIM,)
        ):
            raise ValueError("assistant claims require their typed evidence basis")
        if not self.evidence_basis:
            raise ValueError("coaching signals require a typed evidence basis")
        if len(set(self.evidence_basis)) != len(self.evidence_basis):
            raise ValueError("coaching evidence basis cannot contain duplicates")
        return self

    @property
    def value(self) -> float | None:
        if self.state is not CoachingSignalState.KNOWN:
            return None
        assert self.numerator is not None and self.denominator is not None
        return self.numerator / self.denominator


class CoachingSummaryInput(StrictModel):
    """Bounded input without free-form text or persistent-identifier fields.

    Source provenance values are safe codes, not labels.  A composition boundary
    must supply them from its registered analysis catalog rather than user input.
    It must also supply an explicit task type from a separately reviewed task
    decision; the current all-metrics-applicable analysis preset is not evidence
    of task type.  ``unknown`` therefore abstains from coaching recommendations.
    """

    task_type: CoachingTaskType
    signals: tuple[CoachingSignalReceipt, ...] = Field(
        default=(), max_length=MAX_COACHING_SUMMARY_SIGNALS
    )

    @model_validator(mode="after")
    def reject_duplicate_metrics(self) -> CoachingSummaryInput:
        metric_codes = tuple(signal.metric_code for signal in self.signals)
        if len(set(metric_codes)) != len(metric_codes):
            raise ValueError(
                "coaching summary input cannot contain duplicate metric codes"
            )
        return self


class CoachingDecisionBasis(StrictModel):
    """Common content-free receipt attached to each of the five decisions."""

    code: str
    decision_state: CoachingDecisionState
    metric_basis: tuple[str, ...] = Field(max_length=MAX_COACHING_BASIS_CODES)
    evidence_basis: tuple[CoachingEvidenceBasisCode, ...] = Field(
        max_length=MAX_COACHING_BASIS_CODES
    )
    evidence_kind: CoachingEvidenceKind | None = None
    evidence_tier: CoachingEvidenceTier | None = None
    construct_version: int | None = Field(default=None, ge=1)
    denominator: int | None = Field(default=None, ge=1)
    denominator_kind: CoachingDenominatorKind | None = None
    polarity_successes: int | None = Field(default=None, ge=0)
    evidence_lower_bound: float | None = Field(default=None, ge=0, le=1)
    evidence_upper_bound: float | None = Field(default=None, ge=0, le=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    coverage: float | None = Field(default=None, ge=0, le=1)
    abstention_code: str | None = None
    source_provenance: CoachingSourceProvenance | None = None
    task_type: CoachingTaskType
    pack_key: str = COACHING_SUMMARY_PACK_KEY
    pack_version: int = COACHING_SUMMARY_PACK_VERSION
    algorithm_id: str = COACHING_SUMMARY_ALGORITHM_ID
    algorithm_version: str = COACHING_SUMMARY_ALGORITHM_VERSION
    recommendation_policy_version: int = COACHING_RECOMMENDATION_POLICY_VERSION
    candidate_policy_version: int = COACHING_CANDIDATE_POLICY_VERSION
    denominator_kind_priority_version: int = (
        COACHING_DENOMINATOR_KIND_PRIORITY_VERSION
    )
    rule_priority_version: int = COACHING_RULE_PRIORITY_VERSION

    _validate_codes = field_validator(
        "code",
        "abstention_code",
        "pack_key",
        "algorithm_id",
        "algorithm_version",
    )(_safe_code)
    _validate_metric_basis = field_validator("metric_basis")(_safe_codes)

    @model_validator(mode="after")
    def validate_decision(self) -> CoachingDecisionBasis:
        if self.abstention_code is None:
            if self.decision_state is CoachingDecisionState.ABSTAINED:
                raise ValueError("non-abstained decisions cannot be abstained")
            if (
                not self.metric_basis
                or self.coverage is None
                or self.evidence_kind is None
                or self.evidence_tier is None
                or self.construct_version is None
                or self.denominator is None
                or self.denominator_kind is None
                or self.polarity_successes is None
                or self.evidence_lower_bound is None
                or self.evidence_upper_bound is None
                or self.source_provenance is None
            ):
                raise ValueError("known decisions require complete content-free basis")
            if self.polarity_successes > self.denominator:
                raise ValueError("polarity successes cannot exceed denominator")
            if self.evidence_lower_bound > self.evidence_upper_bound:
                raise ValueError("evidence bounds must be ordered")
        else:
            if self.decision_state is not CoachingDecisionState.ABSTAINED:
                raise ValueError("abstention code requires abstained decision state")
            if any(
                value is not None
                for value in (
                    self.confidence,
                    self.coverage,
                    self.evidence_kind,
                    self.evidence_tier,
                    self.construct_version,
                    self.denominator,
                    self.denominator_kind,
                    self.polarity_successes,
                    self.evidence_lower_bound,
                    self.evidence_upper_bound,
                    self.source_provenance,
                )
            ):
                raise ValueError("abstained decisions cannot claim evidence or confidence")
        return self


class CoachingOutcomeDecision(CoachingDecisionBasis):
    status: CoachingOutcomeStatus
    human_acceptance_status: CoachingHumanAcceptanceStatus
    evidence_disagreement: bool

    @model_validator(mode="after")
    def validate_outcome(self) -> CoachingOutcomeDecision:
        unknown = self.status is CoachingOutcomeStatus.UNKNOWN
        if unknown != (self.abstention_code is not None):
            raise ValueError("unknown outcome and abstention must agree")
        expected_disagreement = (
            self.status is CoachingOutcomeStatus.VERIFIED
            and self.human_acceptance_status
            is CoachingHumanAcceptanceStatus.REJECTED
        ) or (
            self.status is CoachingOutcomeStatus.FAILED
            and self.human_acceptance_status
            is CoachingHumanAcceptanceStatus.ACCEPTED
        )
        if self.evidence_disagreement != expected_disagreement:
            raise ValueError("objective and human evidence disagreement must be exact")
        return self


class CoachingPromptTemplateDecision(CoachingDecisionBasis):
    slot_codes: tuple[str, ...] = Field(max_length=8)
    template_version: int | None = Field(default=None, ge=1)

    _validate_slots = field_validator("slot_codes")(_safe_codes)

    @model_validator(mode="after")
    def validate_template(self) -> CoachingPromptTemplateDecision:
        if self.abstention_code is None and not self.slot_codes:
            raise ValueError("known prompt templates require content-free slot codes")
        if self.abstention_code is None and self.template_version is None:
            raise ValueError("known prompt templates require a template version")
        if self.abstention_code is not None and (
            self.slot_codes or self.template_version is not None
        ):
            raise ValueError("abstained prompt templates cannot recommend a template")
        return self


class CoachingSummary(StrictModel):
    """The complete Coaching Loop v1 decision surface: exactly five items."""

    outcome: CoachingOutcomeDecision
    strength: CoachingDecisionBasis
    friction: CoachingDecisionBasis
    next_experiment: CoachingDecisionBasis
    prompt_template: CoachingPromptTemplateDecision


@dataclass(frozen=True, slots=True)
class _CoachingRule:
    metric_code: str
    strength_code: str
    friction_code: str
    experiment_code: str
    template_code: str
    template_slots: tuple[str, ...]
    task_types: frozenset[CoachingTaskType]
    denominator_kind: CoachingDenominatorKind


_GENERAL_TASKS = frozenset(
    {
        CoachingTaskType.IMPLEMENTATION,
        CoachingTaskType.DIAGNOSIS,
        CoachingTaskType.RESEARCH,
        CoachingTaskType.REVIEW,
        CoachingTaskType.PLANNING,
    }
)
_EXECUTION_TASKS = frozenset(
    {
        CoachingTaskType.IMPLEMENTATION,
        CoachingTaskType.DIAGNOSIS,
        CoachingTaskType.RESEARCH,
    }
)


_RULES = (
    _CoachingRule(
        "prompt.acceptance_testability",
        "strength.testable_acceptance",
        "friction.acceptance_before_implementation_unclear",
        "experiment.define_acceptance_before_implementation",
        "prompt_template.acceptance_first",
        ("goal", "observable_acceptance", "verification", "deliverable"),
        frozenset({CoachingTaskType.IMPLEMENTATION}),
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "prompt.task_definition_coverage",
        "strength.task_contract",
        "friction.task_contract_incomplete",
        "experiment.state_goal_target_and_end_state",
        "prompt_template.task_contract",
        ("goal", "target", "current_state", "desired_end_state"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.RUBRIC_FACTOR,
    ),
    _CoachingRule(
        "prompt.context_sufficiency",
        "strength.operating_context",
        "friction.operating_context_missing",
        "experiment.add_minimum_operating_context",
        "prompt_template.context_anchor",
        ("artifact", "current_state", "environment", "boundary"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.RUBRIC_FACTOR,
    ),
    _CoachingRule(
        "prompt.constraint_precision",
        "strength.precise_constraints",
        "friction.constraints_not_operational",
        "experiment.convert_constraint_to_boundary",
        "prompt_template.bounded_task",
        ("goal", "constraint", "boundary", "verification"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "prompt.deliverable_contract",
        "strength.deliverable_contract",
        "friction.deliverable_contract_missing",
        "experiment.define_deliverable_contract",
        "prompt_template.deliverable_contract",
        ("artifact", "format", "interface", "acceptance"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "logic.decomposition_coverage",
        "strength.requirement_plan_trace",
        "friction.requirements_not_traced_to_plan",
        "experiment.map_requirements_to_plan_items",
        "prompt_template.requirement_plan_map",
        ("requirements", "plan_items", "verification"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "logic.hypothesis_test_linkage",
        "strength.hypothesis_test_loop",
        "friction.hypotheses_not_linked_to_tests",
        "experiment.pair_each_hypothesis_with_test",
        "prompt_template.hypothesis_test_loop",
        ("observation", "hypothesis", "test", "decision_rule"),
        frozenset({CoachingTaskType.DIAGNOSIS, CoachingTaskType.RESEARCH}),
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "collaboration.scope_change_discipline",
        "strength.scope_change_control",
        "friction.scope_changes_not_replanned",
        "experiment.restate_scope_after_change",
        "prompt_template.scope_change",
        ("previous_scope", "new_scope", "impact", "revised_plan"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "collaboration.clarification_yield",
        "strength.productive_clarification",
        "friction.clarification_not_converging",
        "experiment.answer_clarification_with_decision",
        "prompt_template.clarification_decision",
        ("question", "decision", "constraint", "next_action"),
        _GENERAL_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
    _CoachingRule(
        "collaboration.rework_candidate_rate",
        "strength.low_rework_signal",
        "friction.rework_signal_high",
        "experiment.confirm_contract_before_execution",
        "prompt_template.preflight_contract",
        ("goal", "scope", "acceptance", "confirmation"),
        _EXECUTION_TASKS,
        CoachingDenominatorKind.EVENT_COUNT,
    ),
)
_RULE_BY_METRIC = {rule.metric_code: rule for rule in _RULES}
_RULE_PRIORITY = {rule.metric_code: index for index, rule in enumerate(_RULES)}
_DENOMINATOR_KIND_PRIORITY = (
    CoachingDenominatorKind.EVENT_COUNT,
    CoachingDenominatorKind.RUBRIC_FACTOR,
)
_IGNORED_EVIDENCE_KINDS = frozenset({CoachingEvidenceKind.ASSISTANT_CLAIM})


def _metric_basis(signal: CoachingSignalReceipt) -> tuple[str, ...]:
    return (f"{signal.metric_code}.v{signal.metric_version}",)


def _polarity_successes(signal: CoachingSignalReceipt) -> int:
    assert signal.numerator is not None and signal.denominator is not None
    if signal.direction is CoachingSignalDirection.HIGHER_IS_BETTER:
        return signal.numerator
    return signal.denominator - signal.numerator


def _wilson_bounds(successes: int, total: int) -> tuple[float, float]:
    """Two-sided Wilson score interval for a bounded Bernoulli proportion."""

    proportion = successes / total
    z_squared = COACHING_CANDIDATE_WILSON_Z**2
    denominator = 1.0 + z_squared / total
    center = (proportion + z_squared / (2.0 * total)) / denominator
    margin = (
        COACHING_CANDIDATE_WILSON_Z
        * math.sqrt(
            proportion * (1.0 - proportion) / total
            + z_squared / (4.0 * total**2)
        )
        / denominator
    )
    return max(0.0, center - margin), min(1.0, center + margin)


def _known_decision(
    code: str,
    signal: CoachingSignalReceipt,
    task_type: CoachingTaskType,
) -> CoachingDecisionBasis:
    decision_state = (
        CoachingDecisionState.CANDIDATE
        if signal.evidence_kind is CoachingEvidenceKind.DETERMINISTIC_CANDIDATE
        else CoachingDecisionState.SUPPORTED
    )
    assert signal.denominator is not None
    polarity_successes = _polarity_successes(signal)
    lower_bound, upper_bound = _wilson_bounds(
        polarity_successes, signal.denominator
    )
    return CoachingDecisionBasis(
        code=code,
        decision_state=decision_state,
        metric_basis=_metric_basis(signal),
        evidence_basis=signal.evidence_basis,
        evidence_kind=signal.evidence_kind,
        evidence_tier=signal.evidence_tier,
        construct_version=signal.metric_version,
        denominator=signal.denominator,
        denominator_kind=signal.denominator_kind,
        polarity_successes=polarity_successes,
        evidence_lower_bound=lower_bound,
        evidence_upper_bound=upper_bound,
        confidence=signal.confidence,
        coverage=signal.coverage,
        source_provenance=signal.provenance,
        task_type=task_type,
    )


def _abstained(
    code: str,
    abstention_code: str,
    task_type: CoachingTaskType,
) -> CoachingDecisionBasis:
    return CoachingDecisionBasis(
        code=code,
        decision_state=CoachingDecisionState.ABSTAINED,
        metric_basis=(),
        evidence_basis=(),
        confidence=None,
        coverage=None,
        abstention_code=abstention_code,
        task_type=task_type,
    )


def _is_complete_outcome_authority(signal: CoachingSignalReceipt | None) -> bool:
    return bool(
        signal is not None
        and signal.task_terminal
        and signal.outcome_eligible
        and signal.evidence_relevant
        and signal.evidence_complete
        and signal.coverage == 1.0
    )


def _outcome(
    signals: tuple[CoachingSignalReceipt, ...],
    task_type: CoachingTaskType,
) -> CoachingOutcomeDecision:
    objective = next(
        (
            signal
            for signal in signals
            if signal.metric_code == _OBJECTIVE_OUTCOME_METRIC
            and signal.evidence_kind is CoachingEvidenceKind.OBJECTIVE_VERIFICATION
            and signal.state is CoachingSignalState.KNOWN
        ),
        None,
    )
    human = next(
        (
            signal
            for signal in signals
            if signal.metric_code == _HUMAN_OUTCOME_METRIC
            and signal.evidence_kind is CoachingEvidenceKind.HUMAN_REVIEW
            and signal.state is CoachingSignalState.KNOWN
        ),
        None,
    )
    human_acceptance_status = CoachingHumanAcceptanceStatus.UNKNOWN
    if _is_complete_outcome_authority(human):
        assert human is not None
        assert human.numerator is not None
        human_acceptance_status = (
            CoachingHumanAcceptanceStatus.ACCEPTED
            if human.numerator == 1
            else CoachingHumanAcceptanceStatus.REJECTED
        )
    objective_observed = objective is not None
    authority = objective if _is_complete_outcome_authority(objective) else None
    if authority is None:
        return CoachingOutcomeDecision(
            **_abstained(
                "outcome.unknown",
                "outcome_authority_incomplete"
                if objective_observed
                else "objective_evidence_missing",
                task_type,
            ).model_dump(),
            status=CoachingOutcomeStatus.UNKNOWN,
            human_acceptance_status=human_acceptance_status,
            evidence_disagreement=False,
        )
    assert authority.numerator is not None and authority.denominator is not None
    if authority.numerator == authority.denominator:
        status = CoachingOutcomeStatus.VERIFIED
    elif authority.numerator == 0:
        status = CoachingOutcomeStatus.FAILED
    else:
        status = CoachingOutcomeStatus.MIXED
    evidence_disagreement = (
        status is CoachingOutcomeStatus.VERIFIED
        and human_acceptance_status is CoachingHumanAcceptanceStatus.REJECTED
    ) or (
        status is CoachingOutcomeStatus.FAILED
        and human_acceptance_status is CoachingHumanAcceptanceStatus.ACCEPTED
    )
    return CoachingOutcomeDecision(
        **_known_decision(
            f"outcome.{status.value}", authority, task_type
        ).model_dump(),
        status=status,
        human_acceptance_status=human_acceptance_status,
        evidence_disagreement=evidence_disagreement,
    )


def _candidate_bounds(signal: CoachingSignalReceipt) -> tuple[float, float]:
    assert signal.denominator is not None
    return _wilson_bounds(_polarity_successes(signal), signal.denominator)


def _eligible_coaching_signals(
    signals: tuple[CoachingSignalReceipt, ...],
    task_type: CoachingTaskType,
) -> tuple[CoachingSignalReceipt, ...]:
    return tuple(
        signal
        for signal in signals
        if signal.metric_code in _RULE_BY_METRIC
        and task_type in _RULE_BY_METRIC[signal.metric_code].task_types
        and signal.state is CoachingSignalState.KNOWN
        and signal.applicability is CoachingApplicabilityState.APPLICABLE
        and signal.evidence_kind is CoachingEvidenceKind.DETERMINISTIC_CANDIDATE
        and signal.denominator_kind
        is _RULE_BY_METRIC[signal.metric_code].denominator_kind
        and signal.denominator is not None
        and signal.denominator >= COACHING_CANDIDATE_MIN_DENOMINATOR
        and signal.coverage is not None
        and signal.coverage >= COACHING_CANDIDATE_MIN_COVERAGE
        and signal.evidence_kind not in _IGNORED_EVIDENCE_KINDS
    )


def _preferred_denominator_kind(
    signals: tuple[CoachingSignalReceipt, ...],
) -> tuple[CoachingSignalReceipt, ...]:
    """Choose a kind by versioned policy before comparing evidence bounds."""

    for kind in _DENOMINATOR_KIND_PRIORITY:
        matching = tuple(signal for signal in signals if signal.denominator_kind is kind)
        if matching:
            return matching
    return ()


def build_coaching_summary(source: CoachingSummaryInput) -> CoachingSummary:
    """Select five deterministic, evidence-bounded coaching decisions.

    Selection is invariant to input ordering.  A value is never imputed for an
    unknown, abstained, or not-applicable receipt.  Rule-derived strengths,
    frictions, experiments, and templates are candidate decisions only—not
    calibrated skill estimates—and retain unknown confidence.
    """

    eligible = _eligible_coaching_signals(source.signals, source.task_type)
    source_provenance = {
        (
            signal.provenance.pack_key,
            signal.provenance.pack_version,
            signal.provenance.algorithm_id,
            signal.provenance.algorithm_version,
        )
        for signal in eligible
    }
    task_type_unknown = source.task_type is CoachingTaskType.UNKNOWN
    mixed_source_provenance = len(source_provenance) > 1
    if mixed_source_provenance:
        eligible = ()
    strength_candidates = tuple(
        signal
        for signal in eligible
        if _candidate_bounds(signal)[0] >= COACHING_CANDIDATE_STRENGTH_FLOOR
    )
    friction_candidates = tuple(
        signal
        for signal in eligible
        if _candidate_bounds(signal)[1] <= COACHING_CANDIDATE_FRICTION_CEILING
    )
    strengths = _preferred_denominator_kind(strength_candidates)
    frictions = _preferred_denominator_kind(friction_candidates)

    strength_signal = (
        max(
            strengths,
            key=lambda signal: (
                _candidate_bounds(signal)[0],
                signal.coverage,
                -_RULE_PRIORITY[signal.metric_code],
                signal.metric_code,
            ),
        )
        if strengths
        else None
    )
    friction_signal = (
        min(
            frictions,
            key=lambda signal: (
                _candidate_bounds(signal)[1],
                -signal.coverage,
                _RULE_PRIORITY[signal.metric_code],
                signal.metric_code,
            ),
        )
        if frictions
        else None
    )

    if strength_signal is None:
        strength = _abstained(
            "strength.unknown",
            "mixed_source_provenance"
            if mixed_source_provenance
            else "task_type_unknown"
            if task_type_unknown
            else "supported_strength_missing",
            source.task_type,
        )
    else:
        strength = _known_decision(
            _RULE_BY_METRIC[strength_signal.metric_code].strength_code,
            strength_signal,
            source.task_type,
        )

    if friction_signal is None:
        friction_reason = (
            "mixed_source_provenance"
            if mixed_source_provenance
            else "task_type_unknown"
            if task_type_unknown
            else "supported_friction_missing"
        )
        friction = _abstained(
            "friction.unknown", friction_reason, source.task_type
        )
        next_experiment = _abstained(
            "experiment.unknown",
            "mixed_source_provenance"
            if mixed_source_provenance
            else "task_type_unknown"
            if task_type_unknown
            else "evidence_backed_friction_missing",
            source.task_type,
        )
        prompt_template = CoachingPromptTemplateDecision(
            **_abstained(
                "prompt_template.unknown",
                "mixed_source_provenance"
                if mixed_source_provenance
                else "task_type_unknown"
                if task_type_unknown
                else "evidence_backed_friction_missing",
                source.task_type,
            ).model_dump(),
            slot_codes=(),
            template_version=None,
        )
    else:
        rule = _RULE_BY_METRIC[friction_signal.metric_code]
        friction = _known_decision(
            rule.friction_code, friction_signal, source.task_type
        )
        next_experiment = _known_decision(
            rule.experiment_code, friction_signal, source.task_type
        )
        prompt_template = CoachingPromptTemplateDecision(
            **_known_decision(
                rule.template_code, friction_signal, source.task_type
            ).model_dump(),
            slot_codes=rule.template_slots,
            template_version=1,
        )

    return CoachingSummary(
        outcome=_outcome(source.signals, source.task_type),
        strength=strength,
        friction=friction,
        next_experiment=next_experiment,
        prompt_template=prompt_template,
    )


__all__ = [
    "COACHING_CANDIDATE_FRICTION_CEILING",
    "COACHING_CANDIDATE_MIN_COVERAGE",
    "COACHING_CANDIDATE_MIN_DENOMINATOR",
    "COACHING_CANDIDATE_POLICY_VERSION",
    "COACHING_CANDIDATE_STRENGTH_FLOOR",
    "COACHING_CANDIDATE_WILSON_Z",
    "COACHING_DENOMINATOR_KIND_PRIORITY_VERSION",
    "COACHING_SUMMARY_ALGORITHM_ID",
    "COACHING_SUMMARY_ALGORITHM_VERSION",
    "COACHING_SUMMARY_PACK_KEY",
    "COACHING_SUMMARY_PACK_VERSION",
    "COACHING_RECOMMENDATION_POLICY_VERSION",
    "COACHING_RULE_PRIORITY_VERSION",
    "CoachingApplicabilityState",
    "CoachingDecisionBasis",
    "CoachingDecisionState",
    "CoachingDenominatorKind",
    "CoachingEvidenceBasisCode",
    "CoachingEvidenceKind",
    "CoachingEvidenceTier",
    "CoachingHumanAcceptanceStatus",
    "CoachingOutcomeDecision",
    "CoachingOutcomeStatus",
    "CoachingPromptTemplateDecision",
    "CoachingSignalDirection",
    "CoachingSignalReceipt",
    "CoachingSignalState",
    "CoachingSourceProvenance",
    "CoachingSummary",
    "CoachingSummaryInput",
    "CoachingTaskType",
    "build_coaching_summary",
]
