from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import math

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.estimators.calibration_report_contracts import (
    CalibrationMeasurementFamily,
    CalibrationMeasurementShape,
    CalibrationMeasurementState,
    CalibrationMeasurementV1,
)
from prompt_enhancer.application.estimators.gate_decision_contracts import (
    FIXED_GATE_DECISION_DEFINITION,
    GateDecisionCheckCategory,
    GateDecisionCheckOutcome,
    GateDecisionCheckV1,
    GateDecisionOperator,
    GateDecisionOutcome,
    GateDecisionValueShape,
    GateDecisionValueV1,
    NONE_GATE_VALUE,
    RepositorySealedGateDecisionV1,
    canonical_payload_digest,
    repository_gate_decision_id,
)
from prompt_enhancer.application.estimators.gate_decision_evaluation import (
    _count,
    _known,
    _operational_latency_checks,
    _rate,
    _scalar,
)


BASE = datetime(2026, 5, 1, tzinfo=UTC)


def _id(label: str) -> str:
    return hashlib.sha256(f"reserved-example:{label}".encode()).hexdigest()


def test_v20_outcomes_and_operators_are_closed_nonactivating_vocabularies() -> None:
    assert tuple(item.value for item in GateDecisionOutcome) == (
        "rejected",
        "insufficient_data",
    )
    assert "ELIGIBLE" not in GateDecisionOutcome.__members__
    assert tuple(item.value for item in GateDecisionCheckOutcome) == (
        "pass",
        "fail",
        "insufficient_data",
        "unsupported",
    )
    assert tuple(item.value for item in GateDecisionOperator) == (
        "eq",
        "gte",
        "gt",
        "lte",
        "lt",
    )
    assert FIXED_GATE_DECISION_DEFINITION.activation_allowed is False


@pytest.mark.parametrize(
    ("operator", "actual", "threshold", "expected"),
    (
        (GateDecisionOperator.EQ, 2, 2, GateDecisionCheckOutcome.PASS),
        (GateDecisionOperator.EQ, 1, 2, GateDecisionCheckOutcome.FAIL),
        (GateDecisionOperator.GTE, 2, 2, GateDecisionCheckOutcome.PASS),
        (GateDecisionOperator.GTE, 1, 2, GateDecisionCheckOutcome.FAIL),
        (GateDecisionOperator.GT, 2, 2, GateDecisionCheckOutcome.FAIL),
        (GateDecisionOperator.GT, 3, 2, GateDecisionCheckOutcome.PASS),
        (GateDecisionOperator.LTE, 2, 2, GateDecisionCheckOutcome.PASS),
        (GateDecisionOperator.LTE, 3, 2, GateDecisionCheckOutcome.FAIL),
        (GateDecisionOperator.LT, 2, 2, GateDecisionCheckOutcome.FAIL),
        (GateDecisionOperator.LT, 1, 2, GateDecisionCheckOutcome.PASS),
    ),
)
def test_exact_operator_boundary_semantics(
    operator: GateDecisionOperator,
    actual: int,
    threshold: int,
    expected: GateDecisionCheckOutcome,
) -> None:
    check = _known(
        "policy.boundary",
        _count(actual, "cases"),
        operator,
        _count(threshold, "cases"),
    )
    assert check.outcome is expected
    assert check.operator is operator
    assert check.actual.numeric_value == actual
    assert check.threshold.numeric_value == threshold


def test_typed_values_and_missingness_never_fabricate_an_actual() -> None:
    assert _count(2, "cases").shape is GateDecisionValueShape.COUNT
    assert _scalar(-0.25, "score").shape is GateDecisionValueShape.SCALAR
    assert _rate(0.25).shape is GateDecisionValueShape.RATE
    unsupported = GateDecisionCheckV1(
        check_key="policy.unthresholded",
        category=GateDecisionCheckCategory.POLICY,
        outcome=GateDecisionCheckOutcome.UNSUPPORTED,
        operator=GateDecisionOperator.EQ,
        actual=NONE_GATE_VALUE,
        threshold=NONE_GATE_VALUE,
        reason_code="threshold_not_preregistered",
    )
    insufficient = GateDecisionCheckV1(
        check_key="policy.missing",
        category=GateDecisionCheckCategory.POLICY,
        outcome=GateDecisionCheckOutcome.INSUFFICIENT_DATA,
        operator=GateDecisionOperator.GTE,
        actual=NONE_GATE_VALUE,
        threshold=_rate(0.9),
        reason_code="measurement_unavailable",
    )
    assert unsupported.actual == insufficient.actual == NONE_GATE_VALUE
    assert unsupported.threshold == NONE_GATE_VALUE
    assert insufficient.threshold == _rate(0.9)


def test_latency_percentile_is_not_evaluated_before_sample_gate() -> None:
    def measurement(sample_count: int) -> CalibrationMeasurementV1:
        return CalibrationMeasurementV1(
            scope_id=_id("overall-scope"),
            measurement_key="resource.cold_latency_p95_ms",
            family=CalibrationMeasurementFamily.RESOURCE,
            shape=CalibrationMeasurementShape.SCALAR,
            unit_code="milliseconds",
            state=CalibrationMeasurementState.KNOWN,
            scalar_value=10.0,
            sample_count=sample_count,
        )

    sample, percentile = _operational_latency_checks(
        sample_key="policy.cold_latency_samples.example.metric",
        value_key="policy.cold_latency_p95.example.metric",
        item=measurement(2),
        required_samples=3,
        maximum_latency_ms=100.0,
    )
    assert sample.outcome is GateDecisionCheckOutcome.INSUFFICIENT_DATA
    assert percentile.outcome is GateDecisionCheckOutcome.INSUFFICIENT_DATA
    assert sample.actual == percentile.actual == NONE_GATE_VALUE
    assert percentile.reason_code == "latency_samples_incomplete"

    sample, percentile = _operational_latency_checks(
        sample_key="policy.cold_latency_samples.example.metric",
        value_key="policy.cold_latency_p95.example.metric",
        item=measurement(3),
        required_samples=3,
        maximum_latency_ms=100.0,
    )
    assert sample.outcome is GateDecisionCheckOutcome.PASS
    assert sample.actual.integer_value == 3
    assert percentile.outcome is GateDecisionCheckOutcome.PASS
    assert percentile.actual.scalar_value == 10.0


@pytest.mark.parametrize("value", (math.nan, math.inf, -math.inf, -0.0))
def test_noncanonical_scalars_are_rejected(value: float) -> None:
    with pytest.raises(ValidationError):
        GateDecisionValueV1(
            shape=GateDecisionValueShape.SCALAR,
            unit_code="score",
            scalar_value=value,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("check_key", "file:///reserved/private"),
        ("check_key", "https://example.invalid/gate"),
        ("check_key", "policy.bad\ncontrol"),
        ("unit_code", "cases/path"),
    ),
)
def test_codes_cannot_store_paths_uris_or_controls(field: str, value: str) -> None:
    if field == "unit_code":
        with pytest.raises(ValidationError):
            GateDecisionValueV1(
                shape=GateDecisionValueShape.COUNT,
                unit_code=value,
                integer_value=1,
            )
        return
    with pytest.raises(ValidationError):
        GateDecisionCheckV1(
            check_key=value,
            category=GateDecisionCheckCategory.POLICY,
            outcome=GateDecisionCheckOutcome.PASS,
            operator=GateDecisionOperator.EQ,
            actual=_count(0, "cases"),
            threshold=_count(0, "cases"),
        )


def test_recursive_revalidation_rejects_model_copy_bypass() -> None:
    valid = _known(
        "policy.scalar",
        _scalar(0.5),
        GateDecisionOperator.GTE,
        _scalar(0.5),
    )
    forged = valid.model_copy(
        update={
            "actual": valid.actual.model_copy(update={"scalar_value": -0.0})
        }
    )
    with pytest.raises(ValidationError):
        GateDecisionCheckV1.model_validate(forged.model_dump(mode="python"))


def test_all_pass_structural_root_is_rejected_as_inexpressible_eligibility() -> None:
    check = _known(
        "integrity.example",
        _count(0, "mismatches"),
        GateDecisionOperator.EQ,
        _count(0, "mismatches"),
        category=GateDecisionCheckCategory.INTEGRITY,
    )
    checks = (check,)
    check_set_fingerprint = canonical_payload_digest(
        [item.model_dump(mode="json") for item in checks]
    )
    report_id = _id("report")
    report_receipt_fingerprint = _id("report-receipt-fingerprint")
    derived_at = BASE + timedelta(minutes=3)
    with pytest.raises(ValidationError, match="all-pass eligible"):
        RepositorySealedGateDecisionV1(
            decision_id=repository_gate_decision_id(
                report_id,
                report_receipt_fingerprint,
                FIXED_GATE_DECISION_DEFINITION.fingerprint,
                derived_at,
            ),
            campaign_id=_id("campaign"),
            campaign_fingerprint=_id("campaign-fingerprint"),
            stored_plan_fingerprint=_id("plan-fingerprint"),
            policy_fingerprint=_id("policy-fingerprint"),
            assignment_manifest_fingerprint=_id("manifest-fingerprint"),
            split_fingerprint=_id("split-fingerprint"),
            preregistration_fingerprint=_id("preregistration-fingerprint"),
            preregistration_v2_fingerprint=_id("preregistration-v2-fingerprint"),
            constellation_fingerprint=_id("constellation-fingerprint"),
            submission_id=_id("submission"),
            submission_fingerprint=_id("submission-fingerprint"),
            report_id=report_id,
            report_receipt_id=_id("report-receipt"),
            report_fingerprint=_id("report-fingerprint"),
            report_receipt_fingerprint=report_receipt_fingerprint,
            report_definition_fingerprint=_id("report-definition"),
            report_source_bundle_fingerprint=_id("source-bundle"),
            definition=FIXED_GATE_DECISION_DEFINITION,
            definition_fingerprint=FIXED_GATE_DECISION_DEFINITION.fingerprint,
            checks=checks,
            check_set_fingerprint=check_set_fingerprint,
            outcome=GateDecisionOutcome.INSUFFICIENT_DATA,
            campaign_registered_at=BASE,
            submission_submitted_at=BASE + timedelta(minutes=1),
            report_derived_at=BASE + timedelta(minutes=2),
            derived_at=derived_at,
        )
