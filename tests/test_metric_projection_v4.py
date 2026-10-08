"""Projection r4 consumes only explicit, content-free confirmation receipts."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib

import pytest

from prompt_enhancer.application.analysis.metric_contract_v2 import (
    MetricValueStateV2,
    metric_contract_v2,
)
from prompt_enhancer.application.analysis.metric_lifecycle_evidence import (
    FAMILY_LINK_KIND,
    FAMILY_OPPORTUNITY_KIND,
    ConfirmedMetricLifecycleOpportunity,
    ConfirmedMetricLifecycleOutcome,
    MetricLifecycleFamily,
    MetricLifecycleFamilyEvidence,
    MetricLifecycleOutcomeKind,
)
from prompt_enhancer.application.analysis.metric_evidence_readiness_v2 import (
    METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION,
    MetricEvidenceAvailabilityState,
    MetricEvidenceContributor,
    MetricEvidenceReadinessReason,
    metric_evidence_readiness_row,
)
from prompt_enhancer.application.analysis.metric_projection_v4 import (
    METRIC_PROJECTION_V4_VERSION,
    REASON_CONFIRMED_LIFECYCLE_EVIDENCE,
    REASON_LIFECYCLE_ENUMERATION_REQUIRED,
    REASON_LIFECYCLE_SERVICE_UNAVAILABLE,
    lifecycle_metric_state_v4,
)


NOW = datetime(2042, 4, 5, 12, 0, tzinfo=UTC)


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-r4:{label}".encode()).hexdigest()


OUTCOMES = {
    MetricLifecycleFamily.AMBIGUITY_RESOLUTION: (
        MetricLifecycleOutcomeKind.AMBIGUITY_RESOLVED,
        MetricLifecycleOutcomeKind.AMBIGUITY_CLOSED_UNRESOLVED,
    ),
    MetricLifecycleFamily.CLARIFICATION_YIELD: (
        MetricLifecycleOutcomeKind.CLARIFICATION_INCORPORATED,
        MetricLifecycleOutcomeKind.CLARIFICATION_NOT_INCORPORATED,
    ),
    MetricLifecycleFamily.EXPLORATION_CONVERSION: (
        MetricLifecycleOutcomeKind.EXPLORATION_CONVERTED,
        MetricLifecycleOutcomeKind.EXPLORATION_NOT_CONVERTED,
    ),
    MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE: (
        MetricLifecycleOutcomeKind.SCOPE_CHANGE_DISCIPLINED,
        MetricLifecycleOutcomeKind.SCOPE_CHANGE_UNDISCIPLINED,
    ),
    MetricLifecycleFamily.REWORK_CANDIDATE_RATE: (
        MetricLifecycleOutcomeKind.REWORK_REQUIRED,
        MetricLifecycleOutcomeKind.REWORK_NOT_REQUIRED,
    ),
}


def _evidence(
    family: MetricLifecycleFamily,
    outcomes: tuple[MetricLifecycleOutcomeKind | None, ...],
    *,
    enumerated: bool,
) -> MetricLifecycleFamilyEvidence:
    opportunities = tuple(
        ConfirmedMetricLifecycleOpportunity(
            opportunity_id=_id(f"{family.value}:opportunity:{ordinal}"),
            opportunity_kind=FAMILY_OPPORTUNITY_KIND[family],
            confirmation_id=_id(f"{family.value}:confirmation:{ordinal}"),
            confirmed_at=NOW,
            outcome=(
                None
                if outcome is None
                else ConfirmedMetricLifecycleOutcome(
                    decision_id=_id(f"{family.value}:outcome:{ordinal}"),
                    link_kind=FAMILY_LINK_KIND[family],
                    outcome_kind=outcome,
                    decided_at=NOW,
                )
            ),
        )
        for ordinal, outcome in enumerate(outcomes)
    )
    opportunities = tuple(sorted(opportunities, key=lambda item: item.opportunity_id))
    return MetricLifecycleFamilyEvidence(
        family=family,
        opportunity_kind=FAMILY_OPPORTUNITY_KIND[family],
        enumeration_confirmed=enumerated,
        enumeration_confirmation_id=(
            _id(f"{family.value}:enumeration") if enumerated else None
        ),
        enumerated_opportunity_ids=(
            tuple(item.opportunity_id for item in opportunities)
            if enumerated
            else ()
        ),
        opportunities=opportunities,
    )


@pytest.mark.parametrize("family", tuple(MetricLifecycleFamily))
def test_each_confirmed_lifecycle_family_is_truthfully_numeric(
    family: MetricLifecycleFamily,
) -> None:
    positive, negative = OUTCOMES[family]

    state = lifecycle_metric_state_v4(
        metric_contract_v2(family.value),
        _evidence(family, (positive, negative), enumerated=True),
    )

    assert state.projection_version == METRIC_PROJECTION_V4_VERSION
    assert state.value_state is MetricValueStateV2.KNOWN
    assert (state.numerator, state.denominator, state.numeric_value) == (1, 2, 0.5)
    assert state.explanation_code == REASON_CONFIRMED_LIFECYCLE_EVIDENCE
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.5, 0.5)
    assert state.product_metric_eligible is False


def test_rework_required_is_the_lower_is_better_rate_numerator() -> None:
    family = MetricLifecycleFamily.REWORK_CANDIDATE_RATE
    state = lifecycle_metric_state_v4(
        metric_contract_v2(family.value),
        _evidence(
            family,
            (
                MetricLifecycleOutcomeKind.REWORK_REQUIRED,
                MetricLifecycleOutcomeKind.REWORK_NOT_REQUIRED,
                MetricLifecycleOutcomeKind.REWORK_NOT_REQUIRED,
            ),
            enumerated=True,
        ),
    )

    assert (state.numerator, state.denominator, state.numeric_value) == (
        1,
        3,
        pytest.approx(1 / 3),
    )


def test_missing_service_is_unknown_not_an_invented_empty_set() -> None:
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION

    state = lifecycle_metric_state_v4(metric_contract_v2(family.value), None)

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_LIFECYCLE_SERVICE_UNAVAILABLE
    assert state.statistics.capability_available is False
    assert state.statistics.source_complete is False
    assert state.statistics.eligible_count == 0


def test_confirmed_partial_set_stays_unknown_until_exact_enumeration() -> None:
    family = MetricLifecycleFamily.CLARIFICATION_YIELD

    state = lifecycle_metric_state_v4(
        metric_contract_v2(family.value),
        _evidence(family, (None,), enumerated=False),
    )

    assert state.value_state is MetricValueStateV2.UNKNOWN
    assert state.explanation_code == REASON_LIFECYCLE_ENUMERATION_REQUIRED
    assert state.statistics.capability_available is True
    assert state.statistics.source_complete is False
    assert (state.statistics.eligible_count, state.statistics.pending_count) == (1, 1)
    assert state.numeric_value is None


def test_open_enumerated_episode_is_pending_with_right_censoring_bounds() -> None:
    family = MetricLifecycleFamily.EXPLORATION_CONVERSION
    positive, _negative = OUTCOMES[family]

    state = lifecycle_metric_state_v4(
        metric_contract_v2(family.value),
        _evidence(family, (positive, None), enumerated=True),
    )

    assert state.value_state is MetricValueStateV2.PENDING
    assert (state.statistics.met_count, state.statistics.pending_count) == (1, 1)
    assert state.numeric_value is None
    assert (state.censoring_lower_bound, state.censoring_upper_bound) == (0.5, 1.0)


def test_confirmed_empty_enumeration_is_the_only_no_opportunity_authority() -> None:
    family = MetricLifecycleFamily.SCOPE_CHANGE_DISCIPLINE

    state = lifecycle_metric_state_v4(
        metric_contract_v2(family.value),
        _evidence(family, (), enumerated=True),
    )

    assert state.value_state is MetricValueStateV2.NOT_APPLICABLE
    assert state.statistics.capability_available is True
    assert state.statistics.source_complete is True
    assert state.statistics.eligible_count == 0
    assert state.numeric_value is None


def test_family_receipt_cannot_be_borrowed_by_another_metric() -> None:
    with pytest.raises(ValueError, match="another metric family"):
        lifecycle_metric_state_v4(
            metric_contract_v2(
                MetricLifecycleFamily.AMBIGUITY_RESOLUTION.value
            ),
            _evidence(
                MetricLifecycleFamily.CLARIFICATION_YIELD,
                (),
                enumerated=True,
            ),
        )


def test_current_readiness_preserves_r4_service_and_enumeration_actions() -> None:
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    contract = metric_contract_v2(family.value)

    absent = metric_evidence_readiness_row(
        lifecycle_metric_state_v4(contract, None)
    )
    partial = metric_evidence_readiness_row(
        lifecycle_metric_state_v4(
            contract,
            _evidence(family, (None,), enumerated=False),
        )
    )

    assert METRIC_EVIDENCE_READINESS_V2_CATALOG_VERSION == (
        "metric-evidence-readiness-v2-7"
    )
    assert absent.availability_state is (
        MetricEvidenceAvailabilityState.CAPABILITY_MISSING
    )
    assert absent.reason_code is (
        MetricEvidenceReadinessReason.CONFIRMED_LIFECYCLE_SERVICE_REQUIRED
    )
    assert absent.observed_contributors == ()
    assert partial.availability_state is (
        MetricEvidenceAvailabilityState.SOURCE_INCOMPLETE
    )
    assert partial.reason_code is (
        MetricEvidenceReadinessReason.CONFIRMED_LIFECYCLE_ENUMERATION_REQUIRED
    )
    assert partial.observed_contributors == (
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OPPORTUNITY,
    )


def test_r4_readiness_proves_only_observed_receipt_families() -> None:
    family = MetricLifecycleFamily.EXPLORATION_CONVERSION
    positive, _negative = OUTCOMES[family]
    contract = metric_contract_v2(family.value)

    pending = metric_evidence_readiness_row(
        lifecycle_metric_state_v4(
            contract,
            _evidence(family, (positive, None), enumerated=True),
        )
    )
    empty = metric_evidence_readiness_row(
        lifecycle_metric_state_v4(
            contract,
            _evidence(family, (), enumerated=True),
        )
    )

    assert pending.availability_state is (
        MetricEvidenceAvailabilityState.PENDING_RIGHT_CENSORED
    )
    assert pending.observed_contributors == (
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION,
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OPPORTUNITY,
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_OUTCOME_LINK,
    )
    assert pending.missing_contributors == ()
    assert empty.availability_state is MetricEvidenceAvailabilityState.NO_OPPORTUNITY
    assert empty.observed_contributors == (
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION,
    )
    assert empty.required_contributors == (
        MetricEvidenceContributor.CONFIRMED_LIFECYCLE_ENUMERATION,
    )
    assert empty.missing_contributors == ()
