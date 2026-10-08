"""Derive an explicitly untrusted, content-free calibration report foundation.

The public function accepts strongly validated hydrated v16/v17 domain objects,
but callers can still construct those objects.  Therefore neither the input nor
the output claims repository ownership, repository time, persistence, comparison
eligibility, or activation eligibility.  The future v19 repository service owns
those boundaries.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
import hashlib
import json
import math
from typing import Iterable, Literal

from pydantic import field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .calibration_report_contracts import (
    CALIBRATION_MEASUREMENT_SPECS,
    CALIBRATION_MEASUREMENT_SPEC_BY_KEY,
    FIXED_CALIBRATION_REPORT_DEFINITION,
    CalibrationAgreementKind,
    CalibrationAgreementReceiptV1,
    CalibrationClassReceiptV1,
    CalibrationComparisonIdentityV1,
    CalibrationConfusionCellV1,
    CalibrationMeasurementFamily,
    CalibrationMeasurementShape,
    CalibrationMeasurementState,
    CalibrationMeasurementV1,
    CalibrationMetricReportV1,
    CalibrationMissingnessReceiptV1,
    CalibrationReliabilityBinV1,
    CalibrationReportScopeV1,
    CalibrationReportState,
    CalibrationResourceReceiptV1,
    CalibrationScopeDimension,
    CalibrationSelectivePointV1,
    CalibrationStabilityCondition,
    CalibrationStabilityReceiptV1,
    CalibrationTruthSource,
    ModelLabCalibrationMetricSummaryV1,
    ModelLabCalibrationReportSummaryV1,
    UntrustedCalibrationReportV1,
)
from .contracts import MetricValueKind
from .evidence_contracts import (
    AttemptTerminalState,
    BlindAdjudicationResolution,
    CalibrationEvidenceSubmissionV1,
    CalibrationValueState,
    HumanParticipantKind,
    MeasurementState,
)
from .gate_contracts import CaseOrigin, EvidenceTier
from .persistence import PreregisteredEstimatorCampaign


REPORT_IDENTIFIER_DOMAIN = "untrusted-calibration-report-v1"


def _canonical_payload_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _identifier(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("ascii")).hexdigest()


class UntrustedCalibrationProjectionV1(StrictModel):
    """Hydrated domain inputs whose origin and clock are explicitly untrusted."""

    contract_version: Literal["untrusted-calibration-projection-v1"] = (
        "untrusted-calibration-projection-v1"
    )
    campaign: PreregisteredEstimatorCampaign
    submission: CalibrationEvidenceSubmissionV1
    source_observed_at: datetime
    repository_owned: Literal[False] = False

    @model_validator(mode="after")
    def validate_exact_hydrated_lineage(self) -> UntrustedCalibrationProjectionV1:
        if self.source_observed_at.tzinfo is None or (
            self.source_observed_at.utcoffset() is None
            or self.source_observed_at.utcoffset().total_seconds() != 0
        ):
            raise ValueError("repository observation time must be UTC")
        if self.submission.campaign_id != self.campaign.campaign_id:
            raise ValueError("submission does not bind the hydrated campaign")
        if (
            self.submission.campaign_holdout_case_ids
            != self.campaign.split.holdout_case_ids
        ):
            raise ValueError("submission holdout differs from the sealed campaign")
        if self.submission.expected_attempt_manifest.plan_fingerprint != (
            self.campaign.stored_plan.canonical_fingerprint
        ):
            raise ValueError("submission attempts do not bind the sealed plan")
        question_kinds = {
            item.canonical_fingerprint: item.value_kind
            for item in self.campaign.stored_plan.question_specs
        }
        value_groups = (
            self.submission.structured_estimate_receipts,
            self.submission.deterministic_baseline_projections,
            self.submission.objective_truth_projections,
            self.submission.blind_human_judgments,
            self.submission.blind_human_adjudications,
        )
        if any(
            question_kinds.get(item.metric_question_fingerprint)
            is not item.value_kind
            for group in value_groups
            for item in group
        ):
            raise ValueError("evidence value kind differs from the metric question")
        if self.source_observed_at < self.submission.submitted_at:
            raise ValueError("source observation cannot precede submission")
        participant_case_keys = tuple(
            (item.case_id, item.participant_id)
            for item in self.submission.blind_human_judgments
        )
        if len(participant_case_keys) != len(set(participant_case_keys)):
            raise ValueError("one participant may submit only one judgment per case")
        return self


class _HumanLabelProjection(StrictModel):
    participant_id: str
    label_code: str

    _participant = field_validator("participant_id")(_digest)


class _CaseProjection(StrictModel):
    case_id: str
    metric_key: str
    value_kind: MetricValueKind
    truth_source: CalibrationTruthSource
    truth_receipt_fingerprint: str | None = None
    truth_label: str | None = None
    truth_numeric_value: float | None = None
    candidate_state: CalibrationValueState | None = None
    candidate_label: str | None = None
    candidate_numeric_value: float | None = None
    candidate_confidence: float | None = None
    baseline_state: CalibrationValueState | None = None
    baseline_label: str | None = None
    baseline_numeric_value: float | None = None
    adjudicated_state: CalibrationValueState | None = None
    adjudicated_label: str | None = None
    adjudicated_numeric_value: float | None = None
    human_labels: tuple[_HumanLabelProjection, ...] = ()

    _case = field_validator("case_id")(_digest)
    _truth_receipt = field_validator("truth_receipt_fingerprint")(
        lambda value: None if value is None else _digest(value)
    )


def _make_measurement(
    scope_id: str,
    key: str,
    state: CalibrationMeasurementState,
    *,
    scalar: float | None = None,
    integer: int | None = None,
    numerator: int | None = None,
    denominator: int | None = None,
    sample_count: int = 0,
    reason: str | None = None,
) -> CalibrationMeasurementV1:
    spec = CALIBRATION_MEASUREMENT_SPEC_BY_KEY[key]
    return CalibrationMeasurementV1(
        scope_id=scope_id,
        measurement_key=key,
        family=spec.family,
        shape=spec.shape,
        unit_code=spec.unit_code,
        state=state,
        scalar_value=scalar,
        integer_value=integer,
        numerator=numerator,
        denominator=denominator,
        sample_count=sample_count,
        reason_code=reason,
    )


def _known_count(scope_id: str, key: str, value: int) -> CalibrationMeasurementV1:
    return _make_measurement(
        scope_id,
        key,
        CalibrationMeasurementState.KNOWN,
        integer=value,
        sample_count=value,
    )


def _known_scalar(
    scope_id: str, key: str, value: float, sample_count: int
) -> CalibrationMeasurementV1:
    return _make_measurement(
        scope_id,
        key,
        CalibrationMeasurementState.KNOWN,
        scalar=value,
        sample_count=sample_count,
    )


def _known_rate(
    scope_id: str, key: str, numerator: int, denominator: int
) -> CalibrationMeasurementV1:
    if denominator == 0:
        return _make_measurement(
            scope_id,
            key,
            CalibrationMeasurementState.INSUFFICIENT_DATA,
            numerator=numerator,
            denominator=denominator,
            reason="zero_denominator",
        )
    return _make_measurement(
        scope_id,
        key,
        CalibrationMeasurementState.KNOWN,
        scalar=numerator / denominator,
        numerator=numerator,
        denominator=denominator,
        sample_count=denominator,
    )


def _missing(
    scope_id: str,
    key: str,
    state: CalibrationMeasurementState,
    reason: str,
    *,
    sample_count: int = 0,
    numerator: int | None = None,
    denominator: int | None = None,
) -> CalibrationMeasurementV1:
    return _make_measurement(
        scope_id,
        key,
        state,
        sample_count=sample_count,
        numerator=numerator,
        denominator=denominator,
        reason=reason,
    )


def _quantile(values: Iterable[float], probability: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("quantile requires a non-empty sequence")
    if len(ordered) == 1:
        return float(ordered[0])
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return float(ordered[lower])
    weight = position - lower
    return float(ordered[lower] * (1.0 - weight) + ordered[upper] * weight)


def _cohen_kappa(pairs: tuple[tuple[str, str], ...]) -> tuple[float | None, str | None]:
    if not pairs:
        return None, "no_pairs"
    labels = {label for pair in pairs for label in pair}
    first = Counter(left for left, _right in pairs)
    second = Counter(right for _left, right in pairs)
    expected = sum(
        (first[label] / len(pairs)) * (second[label] / len(pairs))
        for label in labels
    )
    if expected >= 1.0 - 1e-12:
        return None, "degenerate_marginals"
    observed = sum(left == right for left, right in pairs) / len(pairs)
    return (observed - expected) / (1.0 - expected), None


def _assignment_bucket_pairs(assignment) -> tuple[tuple[CalibrationScopeDimension, str], ...]:
    return (
        (CalibrationScopeDimension.OVERALL, "overall"),
        (CalibrationScopeDimension.TASK, assignment.task_stratum.value),
        (CalibrationScopeDimension.LANGUAGE, assignment.language.value),
        (CalibrationScopeDimension.PROVIDER, assignment.provider.value),
        (
            CalibrationScopeDimension.PROJECT,
            f"project.{_identifier('calibration-project-slice-v1', assignment.project_id)}",
        ),
        (
            CalibrationScopeDimension.TIME,
            f"utc.{assignment.observed_at.year:04d}.{assignment.observed_at.month:02d}",
        ),
        (
            CalibrationScopeDimension.EVIDENCE_AVAILABILITY,
            "available"
            if assignment.evidence_tier
            in {EvidenceTier.OBJECTIVE, EvidenceTier.HUMAN}
            else "partial",
        ),
    )


def _resolve_cases(
    campaign: PreregisteredEstimatorCampaign,
    submission: CalibrationEvidenceSubmissionV1,
) -> dict[str, _CaseProjection]:
    assignments = {
        item.case_id: item for item in campaign.assignment_manifest.assignments
    }
    question_by_fingerprint = {
        item.canonical_fingerprint: item for item in campaign.stored_plan.question_specs
    }
    estimate_by_id = {
        item.receipt_id: item for item in submission.structured_estimate_receipts
    }
    candidate_by_case = {item.case_id: item for item in submission.candidate_projections}
    baseline_by_case = {
        item.case_id: item for item in submission.deterministic_baseline_projections
    }
    objective_by_case = {
        item.case_id: item for item in submission.objective_truth_projections
    }
    adjudication_by_case = {
        item.case_id: item for item in submission.blind_human_adjudications
    }
    judgments_by_case: dict[str, list] = defaultdict(list)
    for judgment in submission.blind_human_judgments:
        if judgment.participant_kind in {
            HumanParticipantKind.INDEPENDENT_ANNOTATOR,
            HumanParticipantKind.DOMAIN_EXPERT,
        }:
            judgments_by_case[judgment.case_id].append(judgment)

    cases: dict[str, _CaseProjection] = {}
    for case_id in campaign.split.holdout_case_ids:
        assignment = assignments[case_id]
        question = question_by_fingerprint[assignment.metric_question_fingerprint]
        candidate_projection = candidate_by_case.get(case_id)
        candidate = (
            estimate_by_id.get(candidate_projection.estimate_receipt_id)
            if candidate_projection is not None
            else None
        )
        baseline = baseline_by_case.get(case_id)
        objective = objective_by_case.get(case_id)
        adjudication = adjudication_by_case.get(case_id)

        truth_source = CalibrationTruthSource.UNAVAILABLE
        truth_label = None
        truth_numeric_value = None
        truth_receipt_fingerprint = None
        if (
            objective is not None
            and objective.state is CalibrationValueState.KNOWN
        ):
            truth_source = CalibrationTruthSource.OBJECTIVE
            truth_label = objective.label_code
            truth_numeric_value = objective.numeric_value
            truth_receipt_fingerprint = objective.fingerprint
        elif (
            adjudication is not None
            and adjudication.resolution is BlindAdjudicationResolution.RESOLVED
            and adjudication.state is CalibrationValueState.KNOWN
        ):
            truth_source = CalibrationTruthSource.RESOLVED_INDEPENDENT_HUMAN
            truth_label = adjudication.label_code
            truth_numeric_value = adjudication.numeric_value
            truth_receipt_fingerprint = adjudication.fingerprint

        human_labels = tuple(
            _HumanLabelProjection(
                participant_id=item.participant_id,
                label_code=item.label_code,
            )
            for item in sorted(
                judgments_by_case.get(case_id, []),
                key=lambda value: (value.created_at, value.judgment_id),
            )
            if item.state is CalibrationValueState.KNOWN
            and item.label_code is not None
            and item.value_kind in {MetricValueKind.BINARY, MetricValueKind.CATEGORICAL}
        )
        cases[case_id] = _CaseProjection(
            case_id=case_id,
            metric_key=assignment.metric_key,
            value_kind=question.value_kind,
            truth_source=truth_source,
            truth_receipt_fingerprint=truth_receipt_fingerprint,
            truth_label=truth_label,
            truth_numeric_value=truth_numeric_value,
            candidate_state=None if candidate is None else candidate.state,
            candidate_label=None if candidate is None else candidate.label_code,
            candidate_numeric_value=(
                None if candidate is None else candidate.numeric_value
            ),
            candidate_confidence=None if candidate is None else candidate.confidence,
            baseline_state=None if baseline is None else baseline.state,
            baseline_label=None if baseline is None else baseline.label_code,
            baseline_numeric_value=None if baseline is None else baseline.numeric_value,
            adjudicated_state=None if adjudication is None else adjudication.state,
            adjudicated_label=None if adjudication is None else adjudication.label_code,
            adjudicated_numeric_value=(
                None if adjudication is None else adjudication.numeric_value
            ),
            human_labels=human_labels,
        )
    return cases


def _classification_rows(
    *,
    scope_id: str,
    cases: tuple[_CaseProjection, ...],
    vocabulary: tuple[str, ...],
    false_confidence_threshold: float,
    minimum_count: int,
) -> tuple[
    list[CalibrationMeasurementV1],
    tuple[CalibrationConfusionCellV1, ...],
    tuple[CalibrationClassReceiptV1, ...],
    tuple[CalibrationReliabilityBinV1, ...],
    tuple[CalibrationSelectivePointV1, ...],
]:
    eligible_truth = tuple(
        case for case in cases if case.truth_label in vocabulary
    )
    usable = tuple(
        case
        for case in eligible_truth
        if case.candidate_label in vocabulary
    )
    confidence_cases = tuple(
        case for case in usable if case.candidate_confidence is not None
    )
    selective: list[CalibrationSelectivePointV1] = []
    if len(cases) >= minimum_count and len(eligible_truth) >= minimum_count:
        for threshold in FIXED_CALIBRATION_REPORT_DEFINITION.selective_thresholds:
            answered = tuple(
                case
                for case in confidence_cases
                if (case.candidate_confidence or 0.0) >= threshold
            )
            ready = bool(answered)
            selective.append(
                CalibrationSelectivePointV1(
                    scope_id=scope_id,
                    threshold=threshold,
                    state=(
                        CalibrationMeasurementState.KNOWN
                        if ready
                        else CalibrationMeasurementState.INSUFFICIENT_DATA
                    ),
                    coverage_numerator=len(answered),
                    coverage_denominator=len(eligible_truth),
                    risk_numerator=sum(
                        case.candidate_label != case.truth_label for case in answered
                    ),
                    risk_denominator=len(answered),
                    reason_code=(
                        None if ready else "selected_predictions_unavailable"
                    ),
                )
            )
    measurements: list[CalibrationMeasurementV1] = []
    scope_ready = len(cases) >= minimum_count
    enough = len(usable) >= minimum_count
    if not enough:
        correct = sum(case.truth_label == case.candidate_label for case in usable)
        for key in (
            "classification.accuracy",
            "classification.macro_precision",
            "classification.macro_recall",
            "classification.macro_f1",
        ):
            spec = CALIBRATION_MEASUREMENT_SPEC_BY_KEY[key]
            measurements.append(
                _missing(
                    scope_id,
                    key,
                    CalibrationMeasurementState.INSUFFICIENT_DATA,
                    "classification_cases_below_minimum",
                    sample_count=len(usable),
                    **(
                        {"numerator": correct, "denominator": len(usable)}
                        if scope_ready
                        and spec.shape is CalibrationMeasurementShape.RATE
                        else {}
                    ),
                )
            )
        for key in (
            "calibration.selected_confidence_ece",
            "calibration.false_confident_error_rate",
        ):
            spec = CALIBRATION_MEASUREMENT_SPEC_BY_KEY[key]
            measurements.append(
                _missing(
                    scope_id,
                    key,
                    CalibrationMeasurementState.INSUFFICIENT_DATA,
                    "selected_confidence_cases_below_minimum",
                    sample_count=sum(
                        case.candidate_confidence is not None for case in usable
                    ),
                    **(
                        {"numerator": 0, "denominator": len(usable)}
                        if scope_ready
                        and spec.shape is CalibrationMeasurementShape.RATE
                        else {}
                    ),
                )
            )
        return measurements, (), (), (), tuple(selective)

    matrix = {
        (truth, prediction): sum(
            case.truth_label == truth and case.candidate_label == prediction
            for case in usable
        )
        for truth in vocabulary
        for prediction in vocabulary
    }
    cells = tuple(
        CalibrationConfusionCellV1(
            scope_id=scope_id,
            truth_label=truth,
            predicted_label=prediction,
            count=matrix[(truth, prediction)],
        )
        for truth in vocabulary
        for prediction in vocabulary
    )
    class_rows = []
    for label in vocabulary:
        true_positive = matrix[(label, label)]
        support = sum(matrix[(label, predicted)] for predicted in vocabulary)
        predicted_count = sum(matrix[(truth, label)] for truth in vocabulary)
        false_positive = predicted_count - true_positive
        false_negative = support - true_positive
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        denominator = 2 * true_positive + false_positive + false_negative
        f1 = 2 * true_positive / denominator if denominator else 0.0
        class_rows.append(
            CalibrationClassReceiptV1(
                scope_id=scope_id,
                label_code=label,
                support=support,
                predicted_count=predicted_count,
                true_positive=true_positive,
                false_positive=false_positive,
                false_negative=false_negative,
                precision=precision,
                recall=recall,
                f1=f1,
            )
        )
    class_receipts = tuple(class_rows)

    correct = sum(case.truth_label == case.candidate_label for case in usable)
    measurements.extend(
        (
            _known_rate(scope_id, "classification.accuracy", correct, len(usable)),
            _known_scalar(
                scope_id,
                "classification.macro_precision",
                sum(item.precision for item in class_receipts) / len(vocabulary),
                len(usable),
            ),
            _known_scalar(
                scope_id,
                "classification.macro_recall",
                sum(item.recall for item in class_receipts) / len(vocabulary),
                len(usable),
            ),
            _known_scalar(
                scope_id,
                "classification.macro_f1",
                sum(item.f1 for item in class_receipts) / len(vocabulary),
                len(usable),
            ),
        )
    )

    bins: list[CalibrationReliabilityBinV1] = []
    if len(confidence_cases) >= minimum_count:
        weighted_gap = 0.0
        for index in range(FIXED_CALIBRATION_REPORT_DEFINITION.reliability_bin_count):
            lower = index / FIXED_CALIBRATION_REPORT_DEFINITION.reliability_bin_count
            upper = (index + 1) / FIXED_CALIBRATION_REPORT_DEFINITION.reliability_bin_count
            members = tuple(
                case
                for case in confidence_cases
                if (
                    lower <= (case.candidate_confidence or 0.0) < upper
                    or (
                        index
                        == FIXED_CALIBRATION_REPORT_DEFINITION.reliability_bin_count - 1
                        and case.candidate_confidence == 1.0
                    )
                )
            )
            if members:
                mean_confidence = sum(
                    case.candidate_confidence or 0.0 for case in members
                ) / len(members)
                accuracy = sum(
                    case.candidate_label == case.truth_label for case in members
                ) / len(members)
                gap = abs(mean_confidence - accuracy)
                weighted_gap += len(members) * gap
            else:
                mean_confidence = accuracy = gap = None
            bins.append(
                CalibrationReliabilityBinV1(
                    scope_id=scope_id,
                    bin_index=index,
                    lower_bound=lower,
                    upper_bound=upper,
                    count=len(members),
                    mean_confidence=mean_confidence,
                    accuracy=accuracy,
                    absolute_gap=gap,
                )
            )
        measurements.extend(
            (
                _known_scalar(
                    scope_id,
                    "calibration.selected_confidence_ece",
                    weighted_gap / len(confidence_cases),
                    len(confidence_cases),
                ),
                _known_rate(
                    scope_id,
                    "calibration.false_confident_error_rate",
                    sum(
                        (case.candidate_confidence or 0.0)
                        >= false_confidence_threshold
                        and case.candidate_label != case.truth_label
                        for case in confidence_cases
                    ),
                    len(confidence_cases),
                ),
            )
        )
    else:
        for key in (
            "calibration.selected_confidence_ece",
            "calibration.false_confident_error_rate",
        ):
            spec = CALIBRATION_MEASUREMENT_SPEC_BY_KEY[key]
            measurements.append(
                _missing(
                    scope_id,
                    key,
                    CalibrationMeasurementState.INSUFFICIENT_DATA,
                    "selected_confidence_cases_below_minimum",
                    sample_count=len(confidence_cases),
                    **(
                        {"numerator": 0, "denominator": len(confidence_cases)}
                        if spec.shape is CalibrationMeasurementShape.RATE
                        else {}
                    ),
                )
            )

    return measurements, cells, class_receipts, tuple(bins), tuple(selective)


def _agreement_receipt(
    metric_key: str,
    kind: CalibrationAgreementKind,
    pairs: tuple[tuple[str, str], ...],
    case_count: int,
) -> CalibrationAgreementReceiptV1:
    if not pairs:
        return CalibrationAgreementReceiptV1(
            metric_key=metric_key,
            kind=kind,
            state=CalibrationMeasurementState.INSUFFICIENT_DATA,
            case_count=case_count,
            pair_count=0,
            match_count=0,
            reason_code="no_pairs",
        )
    match_count = sum(left == right for left, right in pairs)
    kappa, reason = _cohen_kappa(pairs)
    return CalibrationAgreementReceiptV1(
        metric_key=metric_key,
        kind=kind,
        state=CalibrationMeasurementState.KNOWN,
        case_count=case_count,
        pair_count=len(pairs),
        match_count=match_count,
        observed_agreement=match_count / len(pairs),
        cohen_kappa=kappa,
        reason_code=None,
    )


def _stability_receipts(
    metric_key: str,
    question_fingerprint: str,
    submission: CalibrationEvidenceSubmissionV1,
) -> tuple[CalibrationStabilityReceiptV1, ...]:
    estimate_by_id = {
        item.receipt_id: item for item in submission.structured_estimate_receipts
    }
    grouped: dict[str, list[tuple[object, tuple[str, ...]]]] = defaultdict(list)
    for series in submission.stability_series:
        if series.metric_question_fingerprint != question_fingerprint:
            continue
        labels: list[str] = []
        unsupported_numeric = False
        for trial in series.trials:
            estimate = estimate_by_id[trial.estimate_receipt_id]
            if estimate.value_kind in {MetricValueKind.CONTINUOUS, MetricValueKind.FRACTION}:
                unsupported_numeric = True
                break
            if estimate.state is not CalibrationValueState.KNOWN or estimate.label_code is None:
                labels = []
                break
            labels.append(estimate.label_code)
        grouped[series.condition.value].append(
            (series, ("__numeric__",) if unsupported_numeric else tuple(labels))
        )

    receipts: list[CalibrationStabilityReceiptV1] = []
    for condition in CalibrationStabilityCondition:
        items = grouped.get(condition.value, [])
        if any(labels == ("__numeric__",) for _series, labels in items):
            receipts.append(
                CalibrationStabilityReceiptV1(
                    metric_key=metric_key,
                    condition=condition,
                    state=CalibrationMeasurementState.UNSUPPORTED,
                    case_count=len(items),
                    pair_count=0,
                    match_count=0,
                    reason_code="numeric_tolerance_not_preregistered",
                )
            )
            continue
        usable = [(series, labels) for series, labels in items if len(labels) >= 2]
        pair_count = sum(len(labels) - 1 for _series, labels in usable)
        match_count = sum(
            labels[index] == labels[0]
            for _series, labels in usable
            for index in range(1, len(labels))
        )
        receipts.append(
            CalibrationStabilityReceiptV1(
                metric_key=metric_key,
                condition=condition,
                state=(
                    CalibrationMeasurementState.KNOWN
                    if pair_count
                    else CalibrationMeasurementState.INSUFFICIENT_DATA
                ),
                case_count=len(usable),
                pair_count=pair_count,
                match_count=match_count,
                stability=match_count / pair_count if pair_count else None,
                reason_code=None if pair_count else "stability_series_missing",
            )
        )
    return tuple(sorted(receipts, key=lambda item: item.condition.value))


def _resource_measurements(
    scope_id: str,
    metric_key: str,
    case_ids: set[str],
    submission: CalibrationEvidenceSubmissionV1,
) -> tuple[list[CalibrationMeasurementV1], CalibrationResourceReceiptV1]:
    outcomes = tuple(
        item for item in submission.attempt_outcomes if item.case_id in case_ids
    )
    eligible_count = len(outcomes)
    measurements: list[CalibrationMeasurementV1] = [
        _known_count(scope_id, "resource.attempt_count", eligible_count)
    ]
    if outcomes:
        latencies = tuple(float(item.latency_ms) for item in outcomes)
        queues = tuple(float(item.queue.wait_ms) for item in outcomes)
        measurements.extend(
            (
                _known_scalar(scope_id, "resource.latency_p50_ms", _quantile(latencies, 0.5), len(latencies)),
                _known_scalar(scope_id, "resource.latency_p95_ms", _quantile(latencies, 0.95), len(latencies)),
                _known_scalar(scope_id, "resource.queue_p50_ms", _quantile(queues, 0.5), len(queues)),
                _known_scalar(scope_id, "resource.queue_p95_ms", _quantile(queues, 0.95), len(queues)),
            )
        )
    else:
        measurements.extend(
            _missing(
                scope_id,
                key,
                CalibrationMeasurementState.INSUFFICIENT_DATA,
                "no_attempts",
                numerator=0,
                denominator=0,
            )
            for key in (
                "resource.latency_p50_ms",
                "resource.latency_p95_ms",
                "resource.queue_p50_ms",
                "resource.queue_p95_ms",
            )
        )

    def complete_scalar(
        key: str,
        observations: tuple[tuple[MeasurementState, float | None], ...],
        *,
        aggregator,
        unavailable_reason: str,
        not_applicable_reason: str,
    ) -> CalibrationMeasurementV1:
        observed = tuple(
            value
            for state, value in observations
            if state is MeasurementState.OBSERVED and value is not None
        )
        not_applicable_count = sum(
            state is MeasurementState.NOT_APPLICABLE
            for state, _value in observations
        )
        if eligible_count == 0:
            return _missing(
                scope_id,
                key,
                CalibrationMeasurementState.INSUFFICIENT_DATA,
                "no_attempts",
                numerator=0,
                denominator=0,
            )
        if eligible_count and len(observed) == eligible_count:
            return _known_scalar(
                scope_id,
                key,
                float(aggregator(observed)),
                eligible_count,
            )
        if eligible_count and not_applicable_count == eligible_count:
            return _missing(
                scope_id,
                key,
                CalibrationMeasurementState.NOT_APPLICABLE,
                not_applicable_reason,
                sample_count=0,
                numerator=0,
                denominator=eligible_count,
            )
        return _missing(
            scope_id,
            key,
            CalibrationMeasurementState.INSUFFICIENT_DATA,
            unavailable_reason,
            sample_count=len(observed),
            numerator=len(observed),
            denominator=eligible_count,
        )

    ram = tuple(
        (
            item.resources.state,
            None
            if item.resources.peak_ram_bytes is None
            else float(item.resources.peak_ram_bytes),
        )
        for item in outcomes
    )
    vram = tuple(
        (
            item.resources.state,
            None
            if item.resources.peak_vram_bytes is None
            else float(item.resources.peak_vram_bytes),
        )
        for item in outcomes
    )
    energy = tuple(
        (
            item.resources.state,
            None
            if item.resources.energy_millijoules is None
            else float(item.resources.energy_millijoules),
        )
        for item in outcomes
    )
    costs = tuple(
        (
            item.cost.state,
            None
            if item.cost.amount_microusd is None
            else float(item.cost.amount_microusd),
        )
        for item in outcomes
    )
    tokens = tuple(
        (
            item.usage.state,
            None
            if item.usage.total_tokens is None
            else float(item.usage.total_tokens),
        )
        for item in outcomes
    )
    measurements.extend(
        (
            complete_scalar(
                "resource.peak_ram_bytes",
                ram,
                aggregator=max,
                unavailable_reason="ram_measurement_partially_observed",
                not_applicable_reason="ram_measurement_not_applicable",
            ),
            complete_scalar(
                "resource.peak_vram_bytes",
                vram,
                aggregator=max,
                unavailable_reason="vram_measurement_partially_observed",
                not_applicable_reason="vram_measurement_not_applicable",
            ),
            complete_scalar(
                "resource.energy_total_millijoules",
                energy,
                aggregator=sum,
                unavailable_reason="energy_measurement_partially_observed",
                not_applicable_reason="energy_measurement_not_applicable",
            ),
            complete_scalar(
                "resource.cost_total_microusd",
                costs,
                aggregator=sum,
                unavailable_reason="cost_measurement_partially_observed",
                not_applicable_reason="cost_measurement_not_applicable",
            ),
            complete_scalar(
                "resource.token_total",
                tokens,
                aggregator=sum,
                unavailable_reason="token_measurement_partially_observed",
                not_applicable_reason="token_measurement_not_applicable",
            ),
        )
    )
    for state, key in (
        (AttemptTerminalState.OOM, "resource.oom_rate"),
        (AttemptTerminalState.ERROR, "resource.error_rate"),
        (AttemptTerminalState.REFUSAL, "resource.refusal_rate"),
        (AttemptTerminalState.TIMEOUT, "resource.timeout_rate"),
        (AttemptTerminalState.CANCELLED, "resource.cancelled_rate"),
        (AttemptTerminalState.WORKER_LOST, "resource.worker_lost_rate"),
    ):
        measurements.append(
            _known_rate(
                scope_id,
                key,
                sum(item.state is state for item in outcomes),
                len(outcomes),
            )
        )
    for key, reason in (
        ("resource.cold_latency_p95_ms", "cold_warm_marker_not_recorded"),
        ("resource.warm_latency_p95_ms", "cold_warm_marker_not_recorded"),
        ("resource.throughput_per_second", "throughput_not_recorded"),
        ("resource.disk_bytes", "disk_measurement_not_recorded"),
    ):
        measurements.append(
            _missing(
                scope_id,
                key,
                CalibrationMeasurementState.UNSUPPORTED,
                reason,
                numerator=0,
                denominator=eligible_count,
            )
        )
    receipt = CalibrationResourceReceiptV1(
        metric_key=metric_key,
        attempt_count=eligible_count,
        observed_usage_count=sum(
            item.usage.state is MeasurementState.OBSERVED for item in outcomes
        ),
        observed_resource_count=sum(
            item.resources.state is MeasurementState.OBSERVED for item in outcomes
        ),
        observed_cost_count=sum(
            item.cost.state is MeasurementState.OBSERVED for item in outcomes
        ),
        terminal_state_count=len(outcomes),
        measurement_keys=tuple(
            sorted(item.measurement_key for item in measurements)
        ),
    )
    return measurements, receipt


def _pipeline_fingerprint(campaign: PreregisteredEstimatorCampaign) -> str:
    plan = campaign.stored_plan
    return _canonical_payload_digest(
        {
            "evidence_packet_schema_version": plan.evidence_packet_schema_version,
            "provider_schemas": [item.model_dump(mode="json") for item in plan.provider_schemas],
            "preprocessing_version": plan.preprocessing_version,
            "preprocessing_sha256": plan.preprocessing_sha256,
            "router_version": plan.router_version,
            "router_sha256": plan.router_sha256,
            "redactor_version": plan.redactor_version,
            "redactor_sha256": plan.redactor_sha256,
        }
    )


def _threshold_policy_fingerprint(
    campaign: PreregisteredEstimatorCampaign,
) -> str:
    policy = campaign.policy
    return _canonical_payload_digest(
        {
            "minimum_active_learning_count": policy.minimum_active_learning_count,
            "maximum_active_learning_count": policy.maximum_active_learning_count,
            "minimum_holdout_count": policy.minimum_holdout_count,
            "minimum_holdout_per_metric": policy.minimum_holdout_per_metric,
            "minimum_holdout_per_stratum": policy.minimum_holdout_per_stratum,
            "minimum_holdout_per_language": policy.minimum_holdout_per_language,
            "minimum_operational_samples_per_latency_class": (
                policy.minimum_operational_samples_per_latency_class
            ),
            "minimum_subgroup_size": policy.minimum_subgroup_size,
            "minimum_baseline_margin": policy.minimum_baseline_margin,
            "maximum_human_gap": policy.maximum_human_gap,
            "maximum_ece": policy.maximum_ece,
            "minimum_repeat_stability": policy.minimum_repeat_stability,
            "minimum_selective_coverage": policy.minimum_selective_coverage,
            "maximum_selective_risk": policy.maximum_selective_risk,
            "false_confidence_threshold": policy.false_confidence_threshold,
            "maximum_false_confident_error_rate": (
                policy.maximum_false_confident_error_rate
            ),
            "maximum_cold_p95_latency_ms": policy.maximum_cold_p95_latency_ms,
            "maximum_warm_p95_latency_ms": policy.maximum_warm_p95_latency_ms,
            "maximum_oom_rate": policy.maximum_oom_rate,
            "maximum_error_rate": policy.maximum_error_rate,
            "maximum_refusal_rate": policy.maximum_refusal_rate,
            "maximum_material_subgroup_regression": (
                policy.maximum_material_subgroup_regression
            ),
            "high_risk_precision_rules": [
                item.model_dump(mode="json")
                for item in policy.high_risk_precision_rules
            ],
            "report_selective_thresholds": (
                FIXED_CALIBRATION_REPORT_DEFINITION.selective_thresholds
            ),
            "report_reliability_bin_count": (
                FIXED_CALIBRATION_REPORT_DEFINITION.reliability_bin_count
            ),
        }
    )


def _served_runtime_identity_fingerprint(
    submission: CalibrationEvidenceSubmissionV1,
    case_ids: set[str],
) -> str:
    launches = {
        item.attempt_id: item
        for item in submission.attempt_launches
        if item.case_id in case_ids
    }
    outcomes = {
        item.attempt_id: item
        for item in submission.attempt_outcomes
        if item.case_id in case_ids
    }
    return _canonical_payload_digest(
        [
            {
                "attempt_id": attempt_id,
                "execution_id": launch.execution_id,
                "constellation_stage_fingerprint": (
                    launch.constellation_stage_fingerprint
                ),
                "stage_configuration_sha256": launch.stage_configuration_sha256,
                "stage_ordinal": launch.stage_ordinal,
                "stage_kind": launch.stage_kind.value,
                "runner_adapter_version": launch.runner_adapter_version,
                "runner_configuration_sha256": launch.runner_configuration_sha256,
                "response_schema_version": launch.response_schema_version,
                "requested_source": launch.requested_source.value,
                "requested_model_id": launch.requested_model_id,
                "requested_revision": launch.requested_revision,
                "requested_execution_mode": launch.requested_execution_mode.value,
                "destination": launch.destination.value,
                "retention_class": launch.retention_class.value,
                "served_identity": outcomes[attempt_id].served_identity.model_dump(
                    mode="json"
                ),
            }
            for attempt_id, launch in sorted(launches.items())
        ]
    )


def _measurement_provenance_fingerprint(
    submission: CalibrationEvidenceSubmissionV1,
    case_ids: set[str],
) -> str:
    return _canonical_payload_digest(
        [
            {
                "attempt_id": item.attempt_id,
                "terminal_contract_version": item.contract_version,
                "usage": {
                    "contract_version": item.usage.contract_version,
                    "state": item.usage.state.value,
                    "collector_version": item.usage.collector_version,
                    "reason_code": item.usage.reason_code,
                },
                "resources": {
                    "contract_version": item.resources.contract_version,
                    "state": item.resources.state.value,
                    "collector_version": item.resources.collector_version,
                    "reason_code": item.resources.reason_code,
                    "fields_present": {
                        "peak_ram_bytes": item.resources.peak_ram_bytes is not None,
                        "peak_vram_bytes": item.resources.peak_vram_bytes is not None,
                        "energy_millijoules": (
                            item.resources.energy_millijoules is not None
                        ),
                    },
                },
                "cost": {
                    "contract_version": item.cost.contract_version,
                    "state": item.cost.state.value,
                    "collector_version": item.cost.collector_version,
                    "reason_code": item.cost.reason_code,
                },
                "queue": {
                    "contract_version": item.queue.contract_version,
                    "queue_key": item.queue.queue_key,
                    "queue_version": item.queue.queue_version,
                },
            }
            for item in sorted(submission.attempt_outcomes, key=lambda value: value.attempt_id)
            if item.case_id in case_ids
        ]
    )


def _derive_metric_report(
    metric_key: str,
    campaign: PreregisteredEstimatorCampaign,
    submission: CalibrationEvidenceSubmissionV1,
    cases_by_id: dict[str, _CaseProjection],
) -> CalibrationMetricReportV1:
    assignment_by_id = {
        item.case_id: item for item in campaign.assignment_manifest.assignments
    }
    assignments = tuple(
        assignment_by_id[case_id]
        for case_id in campaign.split.holdout_case_ids
        if assignment_by_id[case_id].metric_key == metric_key
    )
    case_ids = tuple(item.case_id for item in assignments)
    cases = tuple(cases_by_id[item] for item in case_ids)
    question = next(
        item for item in campaign.stored_plan.question_specs if item.metric_key == metric_key
    )
    metric_spec = next(
        item
        for item in campaign.legacy_preregistration.metric_specs
        if item.metric_key == metric_key
    )
    vocabulary = metric_spec.label_vocabulary

    grouped: dict[tuple[CalibrationScopeDimension, str], list[_CaseProjection]] = defaultdict(list)
    for assignment in assignments:
        for dimension, bucket in _assignment_bucket_pairs(assignment):
            grouped[(dimension, bucket)].append(cases_by_id[assignment.case_id])

    scopes: list[CalibrationReportScopeV1] = []
    measurements: list[CalibrationMeasurementV1] = []
    cells: list[CalibrationConfusionCellV1] = []
    class_rows: list[CalibrationClassReceiptV1] = []
    bins: list[CalibrationReliabilityBinV1] = []
    selective: list[CalibrationSelectivePointV1] = []
    scope_id_by_key: dict[tuple[CalibrationScopeDimension, str], str] = {}
    for (dimension, bucket), members in sorted(
        grouped.items(), key=lambda item: (item[0][0].value, item[0][1])
    ):
        scope_id = _identifier(
            "calibration-report-scope-v1", metric_key, dimension.value, bucket
        )
        scope_id_by_key[(dimension, bucket)] = scope_id
        minimum = {
            CalibrationScopeDimension.OVERALL: campaign.policy.minimum_holdout_per_metric,
            CalibrationScopeDimension.TASK: campaign.policy.minimum_holdout_per_stratum,
            CalibrationScopeDimension.LANGUAGE: campaign.policy.minimum_holdout_per_language,
        }.get(dimension, campaign.policy.minimum_subgroup_size)
        enough = len(members) >= minimum
        scopes.append(
            CalibrationReportScopeV1(
                scope_id=scope_id,
                metric_key=metric_key,
                dimension=dimension,
                bucket_code=bucket,
                case_count=len(members),
                minimum_required_count=minimum,
                state=(
                    CalibrationMeasurementState.KNOWN
                    if enough
                    else CalibrationMeasurementState.INSUFFICIENT_DATA
                ),
                reason_code=None if enough else "slice_below_minimum",
            )
        )
        if question.value_kind in {MetricValueKind.BINARY, MetricValueKind.CATEGORICAL}:
            derived = _classification_rows(
                scope_id=scope_id,
                cases=tuple(members),
                vocabulary=vocabulary,
                false_confidence_threshold=campaign.policy.false_confidence_threshold,
                minimum_count=minimum,
            )
            measurements.extend(derived[0])
            cells.extend(derived[1])
            class_rows.extend(derived[2])
            bins.extend(derived[3])
            selective.extend(derived[4])
            for key in (
                "numeric.mean_absolute_error",
                "numeric.root_mean_squared_error",
                "numeric.within_tolerance_rate",
            ):
                measurements.append(
                    _missing(
                        scope_id,
                        key,
                        CalibrationMeasurementState.NOT_APPLICABLE,
                        "numeric_performance_not_applicable_to_classification",
                        sample_count=len(members),
                    )
                )
        else:
            for key in (
                "classification.accuracy",
                "classification.macro_precision",
                "classification.macro_recall",
                "classification.macro_f1",
                "calibration.selected_confidence_ece",
                "calibration.false_confident_error_rate",
            ):
                measurements.append(
                    _missing(
                        scope_id,
                        key,
                        CalibrationMeasurementState.NOT_APPLICABLE,
                        "classification_not_applicable_to_numeric_metric",
                        sample_count=len(members),
                    )
                )
            for key, reason in (
                (
                    "numeric.mean_absolute_error",
                    "numeric_performance_contract_not_registered",
                ),
                (
                    "numeric.root_mean_squared_error",
                    "numeric_performance_contract_not_registered",
                ),
                (
                    "numeric.within_tolerance_rate",
                    "numeric_tolerance_not_preregistered",
                ),
            ):
                measurements.append(
                    _missing(
                        scope_id,
                        key,
                        CalibrationMeasurementState.UNSUPPORTED,
                        reason,
                        sample_count=sum(
                            item.truth_source is not CalibrationTruthSource.UNAVAILABLE
                            for item in members
                        ),
                    )
                )

    overall_scope_id = scope_id_by_key[(CalibrationScopeDimension.OVERALL, "overall")]
    measurements.extend(
        (
            _known_count(overall_scope_id, "coverage.holdout_cases", len(cases)),
            _known_count(
                overall_scope_id,
                "coverage.private_holdout_cases",
                sum(
                    assignment_by_id[item].origin
                    is CaseOrigin.PRIVATE_REPRESENTATIVE
                    for item in case_ids
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.truth_known",
                sum(
                    item.truth_source is not CalibrationTruthSource.UNAVAILABLE
                    for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.objective_truth",
                sum(
                    item.truth_source is CalibrationTruthSource.OBJECTIVE
                    for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.resolved_human_truth",
                sum(
                    item.truth_source
                    is CalibrationTruthSource.RESOLVED_INDEPENDENT_HUMAN
                    for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.candidate_known",
                sum(
                    item.candidate_state is CalibrationValueState.KNOWN
                    for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.baseline_known",
                sum(
                    item.baseline_state is CalibrationValueState.KNOWN for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.human_adjudicated",
                sum(
                    item.adjudicated_state is CalibrationValueState.KNOWN
                    for item in cases
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.privacy_findings",
                submission.privacy_scan.finding_count,
            ),
            _known_count(
                overall_scope_id,
                "coverage.unscanned_artifacts",
                submission.privacy_scan.manifest.unscanned_artifact_count,
            ),
            _known_count(
                overall_scope_id,
                "coverage.access_gaps",
                len(submission.holdout_access_audit.manifest.gaps),
            ),
            _known_count(
                overall_scope_id,
                "coverage.unauthorized_access",
                submission.holdout_access_audit.unauthorized_access_count,
            ),
            _known_count(
                overall_scope_id,
                "coverage.fallback_attempts",
                sum(
                    item.case_id in set(case_ids)
                    and item.served_identity.fallback_used is True
                    for item in submission.attempt_outcomes
                ),
            ),
            _known_count(
                overall_scope_id,
                "coverage.served_identity_unavailable",
                sum(
                    item.case_id in set(case_ids)
                    and item.served_identity.state.value == "unavailable"
                    for item in submission.attempt_outcomes
                ),
            ),
        )
    )

    human_pairs: list[tuple[str, str]] = []
    human_pair_cases = 0
    model_human_pairs: list[tuple[str, str]] = []
    model_human_cases = 0
    for case in cases:
        pairs = tuple(
            (left.label_code, right.label_code)
            for left, right in combinations(case.human_labels, 2)
            if left.participant_id != right.participant_id
        )
        if pairs:
            human_pair_cases += 1
            human_pairs.extend(pairs)
        if case.candidate_label is not None and case.adjudicated_label is not None:
            model_human_cases += 1
            model_human_pairs.append((case.candidate_label, case.adjudicated_label))
    if question.value_kind in {MetricValueKind.CONTINUOUS, MetricValueKind.FRACTION}:
        agreement = tuple(
            CalibrationAgreementReceiptV1(
                metric_key=metric_key,
                kind=kind,
                state=CalibrationMeasurementState.UNSUPPORTED,
                case_count=len(cases),
                pair_count=0,
                match_count=0,
                reason_code="numeric_tolerance_not_preregistered",
            )
            for kind in sorted(CalibrationAgreementKind, key=lambda item: item.value)
        )
    else:
        agreement = tuple(
            sorted(
                (
                    _agreement_receipt(
                        metric_key,
                        CalibrationAgreementKind.HUMAN_HUMAN,
                        tuple(human_pairs),
                        human_pair_cases,
                    ),
                    _agreement_receipt(
                        metric_key,
                        CalibrationAgreementKind.MODEL_HUMAN,
                        tuple(model_human_pairs),
                        model_human_cases,
                    ),
                ),
                key=lambda item: item.kind.value,
            )
        )
    agreement_by_kind = {item.kind: item for item in agreement}
    for kind, observed_key, kappa_key in (
        (
            CalibrationAgreementKind.HUMAN_HUMAN,
            "agreement.human_human_observed",
            "agreement.human_human_kappa",
        ),
        (
            CalibrationAgreementKind.MODEL_HUMAN,
            "agreement.model_human_observed",
            "agreement.model_human_kappa",
        ),
    ):
        receipt = agreement_by_kind[kind]
        measurements.append(
            _known_rate(
                overall_scope_id,
                observed_key,
                receipt.match_count,
                receipt.pair_count,
            )
            if receipt.pair_count
            else _missing(
                overall_scope_id,
                observed_key,
                receipt.state,
                receipt.reason_code or "no_pairs",
                sample_count=receipt.case_count,
                numerator=0,
                denominator=0,
            )
        )
        measurements.append(
            _known_scalar(
                overall_scope_id,
                kappa_key,
                receipt.cohen_kappa,
                receipt.pair_count,
            )
            if receipt.cohen_kappa is not None
            else _missing(
                overall_scope_id,
                kappa_key,
                (
                    receipt.state
                    if receipt.state is not CalibrationMeasurementState.KNOWN
                    else CalibrationMeasurementState.INSUFFICIENT_DATA
                ),
                receipt.reason_code
                or (
                    "no_pairs"
                    if receipt.pair_count == 0
                    else "degenerate_marginals"
                ),
                sample_count=receipt.pair_count,
            )
        )

    stability = _stability_receipts(
        metric_key, question.canonical_fingerprint, submission
    )
    for receipt in stability:
        measurements.append(
            _known_rate(
                overall_scope_id,
                f"stability.{receipt.condition.value}",
                receipt.match_count,
                receipt.pair_count,
            )
            if receipt.state is CalibrationMeasurementState.KNOWN
            else _missing(
                overall_scope_id,
                f"stability.{receipt.condition.value}",
                receipt.state,
                receipt.reason_code or "stability_unavailable",
                sample_count=receipt.case_count,
                numerator=receipt.match_count,
                denominator=receipt.pair_count,
            )
        )

    resource_measurements, resource_receipt = _resource_measurements(
        overall_scope_id, metric_key, set(case_ids), submission
    )
    measurements.extend(resource_measurements)

    probability_state = (
        CalibrationMeasurementState.UNSUPPORTED
        if question.value_kind in {MetricValueKind.BINARY, MetricValueKind.CATEGORICAL}
        else CalibrationMeasurementState.NOT_APPLICABLE
    )
    probability_reason = (
        "full_probability_vector_not_recorded"
        if probability_state is CalibrationMeasurementState.UNSUPPORTED
        else "probability_calibration_not_applicable_to_numeric_metric"
    )
    for key, state, reason, affected_count in (
        ("calibration.brier_score", probability_state, probability_reason, len(cases)),
        ("calibration.log_loss", probability_state, probability_reason, len(cases)),
        ("calibration.slope", probability_state, probability_reason, len(cases)),
        ("retrieval.mean_reciprocal_rank", CalibrationMeasurementState.UNSUPPORTED, "ranked_relevance_receipts_not_recorded", len(cases)),
        ("retrieval.link_precision", CalibrationMeasurementState.UNSUPPORTED, "ranked_relevance_receipts_not_recorded", len(cases)),
        ("retrieval.recall_at_k", CalibrationMeasurementState.UNSUPPORTED, "ranked_relevance_receipts_not_recorded", len(cases)),
        ("retrieval.ndcg_at_k", CalibrationMeasurementState.UNSUPPORTED, "ranked_relevance_receipts_not_recorded", len(cases)),
        ("cascade.stop_rate", CalibrationMeasurementState.UNSUPPORTED, "cascade_stop_receipts_not_recorded", len(cases)),
        ("cascade.incremental_value", CalibrationMeasurementState.UNSUPPORTED, "paired_stage_utility_not_recorded", len(cases)),
    ):
        measurements.append(
            _missing(
                overall_scope_id,
                key,
                state,
                reason,
                sample_count=affected_count,
            )
        )

    # Every non-overall scope receives explicit states for all remaining fixed
    # measurements. Operational, agreement, stability, retrieval, and coverage
    # slices are not silently inferred from the classification subset.
    by_scope: dict[str, set[str]] = defaultdict(set)
    for item in measurements:
        by_scope[item.scope_id].add(item.measurement_key)
    for scope in scopes:
        if scope.scope_id == overall_scope_id:
            continue
        for spec in CALIBRATION_MEASUREMENT_SPECS:
            if spec.measurement_key in by_scope[scope.scope_id]:
                continue
            measurements.append(
                _missing(
                    scope.scope_id,
                    spec.measurement_key,
                    CalibrationMeasurementState.UNSUPPORTED,
                    "measurement_not_derived_for_slice_v1",
                )
            )

    measurements = sorted(
        measurements, key=lambda item: (item.scope_id, item.measurement_key)
    )
    overall_nonknown = tuple(
        item
        for item in measurements
        if item.scope_id == overall_scope_id
        and item.state is not CalibrationMeasurementState.KNOWN
    )
    missingness = tuple(
        sorted(
            (
                CalibrationMissingnessReceiptV1(
                    metric_key=metric_key,
                    measurement_key=item.measurement_key,
                    state=item.state,
                    affected_count=(
                        item.denominator - item.numerator
                        if item.family is CalibrationMeasurementFamily.RESOURCE
                        and item.numerator is not None
                        and item.denominator is not None
                        else item.sample_count
                    ),
                    reason_code=item.reason_code or "measurement_unavailable",
                )
                for item in overall_nonknown
            ),
            key=lambda item: (
                item.measurement_key,
                item.state.value,
                item.reason_code,
            ),
        )
    )
    known = sum(
        item.state is CalibrationMeasurementState.KNOWN
        for item in measurements
        if item.scope_id == overall_scope_id
    )
    state = (
        CalibrationReportState.INSUFFICIENT_DATA
        if known == 0
        else CalibrationReportState.READY
        if known == len(CALIBRATION_MEASUREMENT_SPECS)
        else CalibrationReportState.PARTIAL
    )

    comparison = CalibrationComparisonIdentityV1(
        metric_key=metric_key,
        metric_semantics_fingerprint=_canonical_payload_digest(
            {
                "metric_key": question.metric_key,
                "metric_definition_version": question.metric_definition_version,
                "question_id": question.question_id,
                "question_version": question.question_version,
                "question_sha256": question.question_sha256,
                "rubric_id": question.rubric_id,
                "rubric_version": question.rubric_version,
                "rubric_sha256": question.rubric_sha256,
                "prompt_template_id": question.prompt_template_id,
                "prompt_template_version": question.prompt_template_version,
                "prompt_template_sha256": question.prompt_template_sha256,
                "output_schema_version": question.output_schema_version,
                "value_kind": question.value_kind.value,
                "unit_code": question.unit_code,
                "direction": question.direction.value,
                "lower_bound": question.lower_bound,
                "upper_bound": question.upper_bound,
                "metric_spec": metric_spec.model_dump(mode="json"),
            }
        ),
        evidence_scope_fingerprint=_canonical_payload_digest(
            [
                {
                    "case_id": assignment.case_id,
                    "project_id": assignment.project_id,
                    "session_revision_id": assignment.session_revision_id,
                    "metric_key": assignment.metric_key,
                    "metric_question_fingerprint": (
                        assignment.metric_question_fingerprint
                    ),
                    "evidence_packet_fingerprint": (
                        assignment.evidence_packet_fingerprint
                    ),
                    "provider": assignment.provider.value,
                    "origin": assignment.origin.value,
                    "task_stratum": assignment.task_stratum.value,
                    "language": assignment.language.value,
                    "evidence_tier": assignment.evidence_tier.value,
                    "observed_at": assignment.observed_at.isoformat(
                        timespec="microseconds"
                    ),
                    "truth_source": cases_by_id[
                        assignment.case_id
                    ].truth_source.value,
                    "truth_receipt_fingerprint": cases_by_id[
                        assignment.case_id
                    ].truth_receipt_fingerprint,
                    "truth_label": cases_by_id[assignment.case_id].truth_label,
                    "truth_numeric_value": cases_by_id[
                        assignment.case_id
                    ].truth_numeric_value,
                }
                for assignment in assignments
            ]
        ),
        pipeline_fingerprint=_pipeline_fingerprint(campaign),
        gate_policy_fingerprint=campaign.policy.fingerprint,
        threshold_policy_fingerprint=_threshold_policy_fingerprint(campaign),
        split_fingerprint=campaign.split.fingerprint,
        submission_fingerprint=submission.fingerprint,
        served_runtime_identity_fingerprint=_served_runtime_identity_fingerprint(
            submission, set(case_ids)
        ),
        measurement_provenance_fingerprint=_measurement_provenance_fingerprint(
            submission, set(case_ids)
        ),
        report_definition_fingerprint=FIXED_CALIBRATION_REPORT_DEFINITION.fingerprint,
        estimator_configuration_fingerprint=campaign.stored_plan.canonical_fingerprint,
        constellation_fingerprint=campaign.constellation_identity.fingerprint,
    )
    return CalibrationMetricReportV1(
        metric_key=metric_key,
        value_kind=question.value_kind.value,
        label_vocabulary=(
            vocabulary
            if question.value_kind in {MetricValueKind.BINARY, MetricValueKind.CATEGORICAL}
            else ()
        ),
        comparison_identity=comparison,
        state=state,
        scopes=tuple(
            sorted(
                scopes,
                key=lambda item: (
                    item.dimension.value,
                    item.bucket_code,
                    item.scope_id,
                ),
            )
        ),
        measurements=tuple(measurements),
        confusion_cells=tuple(
            sorted(
                cells,
                key=lambda item: (
                    item.scope_id,
                    item.truth_label,
                    item.predicted_label,
                ),
            )
        ),
        class_receipts=tuple(
            sorted(class_rows, key=lambda item: (item.scope_id, item.label_code))
        ),
        reliability_bins=tuple(
            sorted(bins, key=lambda item: (item.scope_id, item.bin_index))
        ),
        selective_points=tuple(
            sorted(selective, key=lambda item: (item.scope_id, item.threshold))
        ),
        agreement_receipts=agreement,
        stability_receipts=stability,
        resource_receipt=resource_receipt,
        missingness=missingness,
    )


def derive_untrusted_calibration_report(
    projection: UntrustedCalibrationProjectionV1,
) -> UntrustedCalibrationReportV1:
    """Derive one non-activating report without claiming repository ownership."""

    # Reconstruct nested contracts from plain values so model_copy cannot skip
    # validators at this public boundary.
    projection = UntrustedCalibrationProjectionV1.model_validate(
        projection.model_dump(mode="python")
    )
    campaign = PreregisteredEstimatorCampaign.model_validate(
        projection.campaign.model_dump(mode="python")
    )
    submission = CalibrationEvidenceSubmissionV1.model_validate(
        projection.submission.model_dump(mode="python")
    )
    cases = _resolve_cases(campaign, submission)
    metric_keys = tuple(
        sorted(item.metric_key for item in campaign.legacy_preregistration.metric_specs)
    )
    metric_reports = tuple(
        _derive_metric_report(metric_key, campaign, submission, cases)
        for metric_key in metric_keys
    )
    states = {item.state for item in metric_reports}
    state = (
        CalibrationReportState.INSUFFICIENT_DATA
        if states == {CalibrationReportState.INSUFFICIENT_DATA}
        else CalibrationReportState.READY
        if states == {CalibrationReportState.READY}
        else CalibrationReportState.PARTIAL
    )
    report_id = _identifier(
        REPORT_IDENTIFIER_DOMAIN,
        campaign.campaign_id,
        submission.submission_id,
        submission.fingerprint,
        FIXED_CALIBRATION_REPORT_DEFINITION.fingerprint,
        projection.source_observed_at.isoformat(timespec="microseconds"),
    )
    source_bundle_fingerprint = _canonical_payload_digest(
        {
            "split_fingerprint": campaign.split.fingerprint,
            "submission_fingerprint": submission.fingerprint,
            "metric_observation_identities": [
                item.comparison_identity.observation_identity_fingerprint
                for item in metric_reports
            ],
        }
    )
    return UntrustedCalibrationReportV1(
        report_id=report_id,
        campaign_id=campaign.campaign_id,
        campaign_fingerprint=campaign.fingerprint,
        submission_id=submission.submission_id,
        submission_fingerprint=submission.fingerprint,
        stored_plan_fingerprint=campaign.stored_plan.canonical_fingerprint,
        policy_fingerprint=campaign.policy.fingerprint,
        assignment_manifest_fingerprint=campaign.assignment_manifest.fingerprint,
        split_fingerprint=campaign.split.fingerprint,
        preregistration_fingerprint=campaign.legacy_preregistration.fingerprint,
        preregistration_v2_fingerprint=campaign.preregistration_v2.fingerprint,
        constellation_fingerprint=campaign.constellation_identity.fingerprint,
        source_bundle_fingerprint=source_bundle_fingerprint,
        definition=FIXED_CALIBRATION_REPORT_DEFINITION,
        state=state,
        metric_reports=metric_reports,
        source_observed_at=projection.source_observed_at,
    )


def summarize_untrusted_calibration_report(
    report: UntrustedCalibrationReportV1,
) -> ModelLabCalibrationReportSummaryV1:
    """Build a safe local summary without returning campaign or case identities."""

    report = UntrustedCalibrationReportV1.model_validate(
        report.model_dump(mode="python")
    )
    metrics: list[ModelLabCalibrationMetricSummaryV1] = []
    for metric in report.metric_reports:
        overall = next(
            item
            for item in metric.scopes
            if item.dimension is CalibrationScopeDimension.OVERALL
        )
        overall_measurements = tuple(
            item for item in metric.measurements if item.scope_id == overall.scope_id
        )
        metrics.append(
            ModelLabCalibrationMetricSummaryV1(
                metric_key=metric.metric_key,
                state=metric.state,
                comparison_family_fingerprint=(
                    metric.comparison_identity.comparison_family_fingerprint
                ),
                holdout_case_count=overall.case_count,
                known_measurement_count=sum(
                    item.state is CalibrationMeasurementState.KNOWN
                    for item in overall_measurements
                ),
                missing_measurement_count=sum(
                    item.state is not CalibrationMeasurementState.KNOWN
                    for item in overall_measurements
                ),
            )
        )
    return ModelLabCalibrationReportSummaryV1(
        report_id=report.report_id,
        report_fingerprint=report.fingerprint,
        stored_plan_fingerprint=report.stored_plan_fingerprint,
        definition_fingerprint=report.definition.fingerprint,
        state=report.state,
        source_observed_at=report.source_observed_at,
        metrics=tuple(sorted(metrics, key=lambda item: item.metric_key)),
    )


__all__ = [
    "UntrustedCalibrationProjectionV1",
    "derive_untrusted_calibration_report",
    "summarize_untrusted_calibration_report",
]
