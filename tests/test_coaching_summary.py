from __future__ import annotations

from itertools import chain

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_summary import (
    COACHING_CANDIDATE_FRICTION_CEILING,
    COACHING_CANDIDATE_MIN_COVERAGE,
    COACHING_CANDIDATE_MIN_DENOMINATOR,
    COACHING_CANDIDATE_POLICY_VERSION,
    COACHING_CANDIDATE_STRENGTH_FLOOR,
    COACHING_DENOMINATOR_KIND_PRIORITY_VERSION,
    COACHING_RECOMMENDATION_POLICY_VERSION,
    COACHING_RULE_PRIORITY_VERSION,
    COACHING_SUMMARY_ALGORITHM_ID,
    COACHING_SUMMARY_ALGORITHM_VERSION,
    COACHING_SUMMARY_PACK_KEY,
    COACHING_SUMMARY_PACK_VERSION,
    CoachingApplicabilityState,
    CoachingDecisionState,
    CoachingDenominatorKind,
    CoachingEvidenceBasisCode,
    CoachingEvidenceKind,
    CoachingEvidenceTier,
    CoachingHumanAcceptanceStatus,
    CoachingOutcomeStatus,
    CoachingSignalDirection,
    CoachingSignalReceipt,
    CoachingSignalState,
    CoachingSourceProvenance,
    CoachingSummaryInput,
    CoachingTaskType,
    build_coaching_summary,
)


def _provenance(*, variant: str = "a") -> CoachingSourceProvenance:
    return CoachingSourceProvenance(
        pack_key=f"synthetic.coaching.{variant}",
        pack_version=1,
        algorithm_id=f"rules.synthetic.{variant}",
        algorithm_version="1",
    )


def _candidate(
    metric_code: str,
    numerator: int,
    denominator: int,
    *,
    direction: CoachingSignalDirection = CoachingSignalDirection.HIGHER_IS_BETTER,
    coverage: float = 1.0,
    basis: CoachingEvidenceBasisCode = CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,
    provenance: CoachingSourceProvenance | None = None,
    denominator_kind: CoachingDenominatorKind | None = None,
) -> CoachingSignalReceipt:
    if denominator_kind is None:
        denominator_kind = (
            CoachingDenominatorKind.RUBRIC_FACTOR
            if metric_code
            in {
                "prompt.task_definition_coverage",
                "prompt.context_sufficiency",
            }
            else CoachingDenominatorKind.EVENT_COUNT
        )
    return CoachingSignalReceipt(
        metric_code=metric_code,
        metric_version=1,
        state=CoachingSignalState.KNOWN,
        applicability=CoachingApplicabilityState.APPLICABLE,
        direction=direction,
        denominator_kind=denominator_kind,
        evidence_kind=CoachingEvidenceKind.DETERMINISTIC_CANDIDATE,
        evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
        evidence_basis=(basis,),
        numerator=numerator,
        denominator=denominator,
        coverage=coverage,
        confidence=None,
        provenance=provenance or _provenance(),
    )


def _objective(
    passed: int,
    total: int,
    *,
    terminal: bool = True,
    eligible: bool = True,
    relevant: bool = True,
    complete: bool = True,
    coverage: float = 1.0,
) -> CoachingSignalReceipt:
    return CoachingSignalReceipt(
        metric_code="outcome.objective_verification",
        metric_version=1,
        state=CoachingSignalState.KNOWN,
        applicability=CoachingApplicabilityState.APPLICABLE,
        direction=CoachingSignalDirection.HIGHER_IS_BETTER,
        denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
        evidence_kind=CoachingEvidenceKind.OBJECTIVE_VERIFICATION,
        evidence_tier=CoachingEvidenceTier.OBJECTIVE_EVENT,
        evidence_basis=(
            CoachingEvidenceBasisCode.OBJECTIVE_VERIFICATION_RESULTS,
        ),
        numerator=passed,
        denominator=total,
        coverage=coverage,
        confidence=1.0 if complete and coverage == 1.0 else None,
        task_terminal=terminal,
        outcome_eligible=eligible,
        evidence_relevant=relevant,
        evidence_complete=complete,
        provenance=CoachingSourceProvenance(
            pack_key="synthetic.verification",
            pack_version=1,
            algorithm_id="rules.synthetic.verification",
            algorithm_version="1",
        ),
    )


def _human_acceptance(
    accepted: bool,
    *,
    terminal: bool = True,
    eligible: bool = True,
    relevant: bool = True,
    complete: bool = True,
    coverage: float = 1.0,
) -> CoachingSignalReceipt:
    return CoachingSignalReceipt(
        metric_code="outcome.human_acceptance",
        metric_version=1,
        state=CoachingSignalState.KNOWN,
        applicability=CoachingApplicabilityState.APPLICABLE,
        direction=CoachingSignalDirection.HIGHER_IS_BETTER,
        denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
        evidence_kind=CoachingEvidenceKind.HUMAN_REVIEW,
        evidence_tier=CoachingEvidenceTier.HUMAN_REVIEW,
        evidence_basis=(CoachingEvidenceBasisCode.HUMAN_ACCEPTANCE_DECISION,),
        numerator=int(accepted),
        denominator=1,
        coverage=coverage,
        confidence=1.0 if complete and coverage == 1.0 else None,
        task_terminal=terminal,
        outcome_eligible=eligible,
        evidence_relevant=relevant,
        evidence_complete=complete,
        provenance=CoachingSourceProvenance(
            pack_key="synthetic.acceptance",
            pack_version=1,
            algorithm_id="human.synthetic.acceptance",
            algorithm_version="1",
        ),
    )


def _assistant_claim(claimed_complete: bool) -> CoachingSignalReceipt:
    return CoachingSignalReceipt(
        metric_code="outcome.assistant_completion_claim",
        metric_version=1,
        state=CoachingSignalState.KNOWN,
        applicability=CoachingApplicabilityState.APPLICABLE,
        direction=CoachingSignalDirection.HIGHER_IS_BETTER,
        denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
        evidence_kind=CoachingEvidenceKind.ASSISTANT_CLAIM,
        evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
        evidence_basis=(CoachingEvidenceBasisCode.ASSISTANT_COMPLETION_CLAIM,),
        numerator=int(claimed_complete),
        denominator=1,
        coverage=1.0,
        confidence=None,
        provenance=_provenance(variant="claim"),
    )


def _source(*signals: CoachingSignalReceipt) -> CoachingSummaryInput:
    return CoachingSummaryInput(
        task_type=CoachingTaskType.IMPLEMENTATION,
        signals=signals,
    )


def test_golden_summary_is_small_actionable_versioned_and_content_free() -> None:
    summary = build_coaching_summary(
        _source(
            _objective(2, 2),
            _candidate("prompt.task_definition_coverage", 3, 3),
            _candidate("prompt.deliverable_contract", 12, 12),
            _candidate("prompt.acceptance_testability", 0, 12),
        )
    )

    assert tuple(summary.model_dump()) == (
        "outcome",
        "strength",
        "friction",
        "next_experiment",
        "prompt_template",
    )
    assert summary.outcome.status is CoachingOutcomeStatus.VERIFIED
    assert summary.outcome.decision_state is CoachingDecisionState.SUPPORTED
    assert (
        summary.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.UNKNOWN
    )
    assert summary.outcome.evidence_disagreement is False
    assert summary.strength.code == "strength.deliverable_contract"
    assert summary.strength.decision_state is CoachingDecisionState.CANDIDATE
    assert summary.friction.code == "friction.acceptance_before_implementation_unclear"
    assert summary.next_experiment.code == (
        "experiment.define_acceptance_before_implementation"
    )
    assert summary.prompt_template.code == "prompt_template.acceptance_first"
    assert summary.prompt_template.slot_codes == (
        "goal",
        "observable_acceptance",
        "verification",
        "deliverable",
    )
    assert summary.prompt_template.template_version == 1

    for item in (
        summary.outcome,
        summary.strength,
        summary.friction,
        summary.next_experiment,
        summary.prompt_template,
    ):
        assert item.pack_key == COACHING_SUMMARY_PACK_KEY
        assert item.pack_version == COACHING_SUMMARY_PACK_VERSION
        assert item.algorithm_id == COACHING_SUMMARY_ALGORITHM_ID
        assert item.algorithm_version == COACHING_SUMMARY_ALGORITHM_VERSION
        assert (
            item.recommendation_policy_version
            == COACHING_RECOMMENDATION_POLICY_VERSION
        )
        assert item.candidate_policy_version == COACHING_CANDIDATE_POLICY_VERSION
        assert (
            item.denominator_kind_priority_version
            == COACHING_DENOMINATOR_KIND_PRIORITY_VERSION
        )
        assert item.rule_priority_version == COACHING_RULE_PRIORITY_VERSION
        assert item.task_type is CoachingTaskType.IMPLEMENTATION
        assert item.construct_version == 1
        assert item.denominator is not None
        assert item.coverage == 1.0
        assert item.abstention_code is None


def test_missing_unknown_and_small_or_incomplete_evidence_never_become_zero() -> None:
    unknown = CoachingSignalReceipt(
        metric_code="prompt.acceptance_testability",
        metric_version=1,
        state=CoachingSignalState.UNKNOWN,
        applicability=CoachingApplicabilityState.UNKNOWN,
        direction=CoachingSignalDirection.HIGHER_IS_BETTER,
        denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
        evidence_kind=CoachingEvidenceKind.DETERMINISTIC_CANDIDATE,
        evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
        evidence_basis=(CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,),
        coverage=None,
        provenance=_provenance(),
    )
    summary = build_coaching_summary(
        _source(
            unknown,
            _candidate("prompt.task_definition_coverage", 0, 1),
            _candidate("prompt.context_sufficiency", 0, 4, coverage=0.5),
        )
    )

    assert summary.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert summary.strength.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.friction.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.friction.coverage is None
    assert summary.next_experiment.abstention_code == (
        "evidence_backed_friction_missing"
    )
    assert summary.prompt_template.slot_codes == ()
    assert COACHING_CANDIDATE_MIN_DENOMINATOR == 2
    assert COACHING_CANDIDATE_MIN_COVERAGE == 0.75
    assert COACHING_CANDIDATE_STRENGTH_FLOOR == 0.75
    assert COACHING_CANDIDATE_FRICTION_CEILING == 0.25


@pytest.mark.parametrize("total", (2, 4))
def test_small_extreme_event_samples_abstain_under_wilson_policy(total: int) -> None:
    summary = build_coaching_summary(
        _source(
            _candidate("prompt.deliverable_contract", total, total),
            _candidate("prompt.acceptance_testability", 0, total),
        )
    )

    assert summary.strength.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.friction.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.next_experiment.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.prompt_template.decision_state is CoachingDecisionState.ABSTAINED


def test_denominator_kind_priority_precedes_bound_ranking() -> None:
    summary = build_coaching_summary(
        _source(
            _candidate(
                "prompt.task_definition_coverage",
                100,
                100,
                denominator_kind=CoachingDenominatorKind.RUBRIC_FACTOR,
            ),
            _candidate("prompt.deliverable_contract", 12, 12),
            _candidate(
                "prompt.context_sufficiency",
                0,
                100,
                denominator_kind=CoachingDenominatorKind.RUBRIC_FACTOR,
            ),
            _candidate("prompt.acceptance_testability", 0, 12),
        )
    )

    assert summary.strength.code == "strength.deliverable_contract"
    assert summary.strength.denominator_kind is CoachingDenominatorKind.EVENT_COUNT
    assert summary.friction.code == (
        "friction.acceptance_before_implementation_unclear"
    )
    assert summary.friction.denominator_kind is CoachingDenominatorKind.EVENT_COUNT
    assert summary.strength.evidence_lower_bound is not None
    assert summary.friction.evidence_upper_bound is not None


def test_wilson_bounds_normalize_lower_is_better_polarity() -> None:
    low_rework = build_coaching_summary(
        _source(
            _candidate(
                "collaboration.rework_candidate_rate",
                0,
                12,
                direction=CoachingSignalDirection.LOWER_IS_BETTER,
                basis=CoachingEvidenceBasisCode.RULE_CORRECTION_COUNTS,
            )
        )
    )
    assert low_rework.strength.code == "strength.low_rework_signal"
    assert low_rework.strength.polarity_successes == 12

    high_rework = build_coaching_summary(
        _source(
            _candidate(
                "collaboration.rework_candidate_rate",
                12,
                12,
                direction=CoachingSignalDirection.LOWER_IS_BETTER,
                basis=CoachingEvidenceBasisCode.RULE_CORRECTION_COUNTS,
            )
        )
    )
    assert high_rework.friction.code == "friction.rework_signal_high"
    assert high_rework.friction.polarity_successes == 0


def test_task_type_is_explicit_and_blocks_task_confounded_rules() -> None:
    signal = _candidate("prompt.acceptance_testability", 0, 4)
    summary = build_coaching_summary(
        CoachingSummaryInput(task_type=CoachingTaskType.RESEARCH, signals=(signal,))
    )

    assert summary.friction.decision_state is CoachingDecisionState.ABSTAINED
    assert summary.next_experiment.decision_state is CoachingDecisionState.ABSTAINED

    unknown_task = build_coaching_summary(
        CoachingSummaryInput(
            task_type=CoachingTaskType.UNKNOWN,
            signals=(
                _candidate("prompt.task_definition_coverage", 0, 4),
            ),
        )
    )
    for item in (
        unknown_task.strength,
        unknown_task.friction,
        unknown_task.next_experiment,
        unknown_task.prompt_template,
    ):
        assert item.decision_state is CoachingDecisionState.ABSTAINED
        assert item.abstention_code == "task_type_unknown"


def test_order_and_irrelevant_unknown_signals_are_metamorphically_invariant() -> None:
    signals = (
        _objective(1, 2),
        _candidate("prompt.task_definition_coverage", 4, 4),
        _candidate("prompt.acceptance_testability", 1, 4),
    )
    first = build_coaching_summary(_source(*signals))
    second = build_coaching_summary(_source(*reversed(signals)))
    irrelevant = CoachingSignalReceipt(
        metric_code="synthetic.unsupported_metric",
        metric_version=1,
        state=CoachingSignalState.UNKNOWN,
        applicability=CoachingApplicabilityState.UNKNOWN,
        direction=CoachingSignalDirection.HIGHER_IS_BETTER,
        denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
        evidence_kind=CoachingEvidenceKind.DETERMINISTIC_CANDIDATE,
        evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
        evidence_basis=(CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,),
        provenance=_provenance(),
    )
    third = build_coaching_summary(_source(*signals, irrelevant))

    assert first == second == third
    assert build_coaching_summary(_source(*signals)) == first


def test_objective_evidence_precedes_contradictory_claims_and_human_review() -> None:
    failed = build_coaching_summary(
        _source(_assistant_claim(True), _human_acceptance(True), _objective(0, 2))
    )
    assert failed.outcome.status is CoachingOutcomeStatus.FAILED
    assert failed.outcome.evidence_kind is CoachingEvidenceKind.OBJECTIVE_VERIFICATION
    assert (
        failed.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.ACCEPTED
    )
    assert failed.outcome.evidence_disagreement is True

    mixed = build_coaching_summary(_source(_objective(1, 2)))
    assert mixed.outcome.status is CoachingOutcomeStatus.MIXED

    claim_only = build_coaching_summary(_source(_assistant_claim(True)))
    assert claim_only.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert claim_only.outcome.evidence_disagreement is False

    accepted = build_coaching_summary(_source(_human_acceptance(True)))
    assert accepted.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert accepted.outcome.abstention_code == "objective_evidence_missing"
    assert (
        accepted.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.ACCEPTED
    )
    assert accepted.outcome.evidence_disagreement is False

    rejected = build_coaching_summary(_source(_human_acceptance(False)))
    assert rejected.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert (
        rejected.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.REJECTED
    )
    assert rejected.outcome.evidence_disagreement is False

    objective_pass_human_reject = build_coaching_summary(
        _source(_objective(2, 2), _human_acceptance(False))
    )
    assert objective_pass_human_reject.outcome.status is CoachingOutcomeStatus.VERIFIED
    assert (
        objective_pass_human_reject.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.REJECTED
    )
    assert objective_pass_human_reject.outcome.evidence_disagreement is True

    objective_pass_human_accept = build_coaching_summary(
        _source(_objective(2, 2), _human_acceptance(True))
    )
    assert objective_pass_human_accept.outcome.status is CoachingOutcomeStatus.VERIFIED
    assert objective_pass_human_accept.outcome.evidence_disagreement is False

    incomplete_human = build_coaching_summary(
        _source(_objective(0, 2), _human_acceptance(True, complete=False))
    )
    assert incomplete_human.outcome.status is CoachingOutcomeStatus.FAILED
    assert (
        incomplete_human.outcome.human_acceptance_status
        is CoachingHumanAcceptanceStatus.UNKNOWN
    )
    assert incomplete_human.outcome.evidence_disagreement is False


@pytest.mark.parametrize(
    "override",
    (
        {"terminal": False},
        {"eligible": False},
        {"relevant": False},
        {"complete": False},
        {"coverage": 0.5, "complete": False},
    ),
)
def test_incomplete_objective_authority_abstains(override: dict[str, object]) -> None:
    summary = build_coaching_summary(_source(_objective(0, 2, **override)))
    assert summary.outcome.status is CoachingOutcomeStatus.UNKNOWN
    assert summary.outcome.abstention_code == "outcome_authority_incomplete"
    assert summary.outcome.denominator is None


def test_mixed_coaching_provenance_blocks_synthesis_without_blocking_outcome() -> None:
    summary = build_coaching_summary(
        _source(
            _objective(1, 1),
            _candidate(
                "prompt.task_definition_coverage",
                4,
                4,
                provenance=_provenance(variant="a"),
            ),
            _candidate(
                "prompt.acceptance_testability",
                0,
                4,
                provenance=_provenance(variant="b"),
            ),
        )
    )

    assert summary.outcome.status is CoachingOutcomeStatus.VERIFIED
    for item in (
        summary.strength,
        summary.friction,
        summary.next_experiment,
        summary.prompt_template,
    ):
        assert item.decision_state is CoachingDecisionState.ABSTAINED
        assert item.abstention_code == "mixed_source_provenance"


def test_contract_rejects_identifier_and_text_canaries_and_output_has_no_person_score() -> None:
    pseudonym_canary = "a" * 64
    with pytest.raises(ValidationError):
        CoachingSourceProvenance(
            pack_key=pseudonym_canary,
            pack_version=1,
            algorithm_id="rules.synthetic",
            algorithm_version="1",
        )
    with pytest.raises(ValidationError):
        CoachingSignalReceipt.model_validate(
            {
                **_candidate("prompt.task_definition_coverage", 4, 4).model_dump(),
                "evidence_basis": (pseudonym_canary,),
            }
        )
    with pytest.raises(ValidationError):
        CoachingSourceProvenance(
            pack_key="fictional.person@example.invalid",
            pack_version=1,
            algorithm_id="rules.synthetic",
            algorithm_version="1",
        )

    rendered = str(build_coaching_summary(_source()).model_dump())
    forbidden = (
        "transcript",
        "excerpt",
        "session_id",
        "user_id",
        "intelligence",
        "cognitive_score",
        "developer_rank",
        pseudonym_canary,
    )
    assert not any(value in rendered for value in forbidden)


def test_signal_bound_and_duplicate_identity_are_rejected() -> None:
    signals = tuple(
        CoachingSignalReceipt(
            metric_code=f"synthetic.metric_{index}",
            metric_version=1,
            state=CoachingSignalState.UNKNOWN,
            applicability=CoachingApplicabilityState.UNKNOWN,
            direction=CoachingSignalDirection.HIGHER_IS_BETTER,
            denominator_kind=CoachingDenominatorKind.EVENT_COUNT,
            evidence_kind=CoachingEvidenceKind.DETERMINISTIC_CANDIDATE,
            evidence_tier=CoachingEvidenceTier.REDACTED_CONTENT,
            evidence_basis=(CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,),
            provenance=_provenance(),
        )
        for index in range(65)
    )
    with pytest.raises(ValidationError):
        CoachingSummaryInput(task_type=CoachingTaskType.IMPLEMENTATION, signals=signals)
    with pytest.raises(ValidationError):
        CoachingSummaryInput(
            task_type=CoachingTaskType.IMPLEMENTATION,
            signals=tuple(chain(signals[:1], signals[:1])),
        )

    objective_v1 = _objective(1, 1)
    objective_v2 = objective_v1.model_copy(update={"metric_version": 2})
    with pytest.raises(ValidationError, match="duplicate metric codes"):
        CoachingSummaryInput(
            task_type=CoachingTaskType.IMPLEMENTATION,
            signals=(objective_v2, objective_v1),
        )
    with pytest.raises(ValidationError, match="duplicate metric codes"):
        CoachingSummaryInput(
            task_type=CoachingTaskType.IMPLEMENTATION,
            signals=(objective_v1, objective_v2),
        )


def test_evidence_kind_rejects_cross_family_basis_codes() -> None:
    candidate = _candidate("prompt.task_definition_coverage", 4, 4)
    with pytest.raises(
        ValidationError,
        match="deterministic candidates require rule-count evidence basis",
    ):
        CoachingSignalReceipt.model_validate(
            {
                **candidate.model_dump(),
                "evidence_basis": (
                    CoachingEvidenceBasisCode.HUMAN_ACCEPTANCE_DECISION,
                ),
            }
        )

    claim = _assistant_claim(True)
    with pytest.raises(
        ValidationError,
        match="assistant claims require their typed evidence basis",
    ):
        CoachingSignalReceipt.model_validate(
            {
                **claim.model_dump(),
                "evidence_basis": (CoachingEvidenceBasisCode.RULE_FACTOR_COUNTS,),
            }
        )


@pytest.mark.parametrize(
    ("state", "applicability"),
    (
        (
            CoachingSignalState.NOT_APPLICABLE,
            CoachingApplicabilityState.APPLICABLE,
        ),
        (
            CoachingSignalState.UNKNOWN,
            CoachingApplicabilityState.NOT_APPLICABLE,
        ),
    ),
)
def test_not_applicable_state_and_applicability_must_agree_exactly(
    state: CoachingSignalState,
    applicability: CoachingApplicabilityState,
) -> None:
    base = _candidate("prompt.task_definition_coverage", 4, 4).model_dump()
    with pytest.raises(
        ValidationError,
        match="not-applicable signal state and applicability must agree",
    ):
        CoachingSignalReceipt.model_validate(
            {
                **base,
                "state": state,
                "applicability": applicability,
                "numerator": None,
                "denominator": None,
                "confidence": None,
            }
        )
