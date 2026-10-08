"""Content-free evaluation math for estimator screening and activation.

The contracts in this module deliberately accept only opaque identifiers, labels,
scores, ranks, and resource measurements.  They do not accept prompts, excerpts,
model commentary, or generated rationales.  Objective checks and independently
adjudicated human labels are the only supported truth sources; model consensus is
not a truth source.

Missing or statistically unusable inputs produce ``insufficient_data`` receipts.
They are never silently converted to zero performance.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from enum import Enum
import math
import re
from typing import Iterable, Sequence


_OPAQUE_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$")
_PROBABILITY_TOLERANCE = 1e-9
_LOG_EPSILON = 1e-15


class EvaluationState(str, Enum):
    """Whether an estimate is supported by the supplied observations."""

    READY = "ready"
    INSUFFICIENT_DATA = "insufficient_data"


class TruthSource(str, Enum):
    """Permitted, non-consensus sources of reference labels or utilities."""

    OBJECTIVE_CHECK = "objective_check"
    HUMAN_ADJUDICATED = "human_adjudicated"
    INDEPENDENT_HUMAN = "independent_human"


class GateOutcome(str, Enum):
    """Overall outcome of the estimator activation gate."""

    ELIGIBLE = "eligible"
    REJECTED = "rejected"
    INSUFFICIENT_DATA = "insufficient_data"


class CheckOutcome(str, Enum):
    """Outcome of one preregistered activation check."""

    PASS = "pass"
    FAIL = "fail"
    INSUFFICIENT_DATA = "insufficient_data"


class CalibrationTaskStratum(str, Enum):
    """The four preregistered task families used by the first release wave."""

    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    CODE_REVIEW = "code_review"
    RESEARCH_DESIGN = "research_design"


REQUIRED_CALIBRATION_STRATA: tuple[CalibrationTaskStratum, ...] = tuple(
    CalibrationTaskStratum
)


class EvidenceAvailability(str, Enum):
    """Whether objective or human reference evidence exists for a slice."""

    AVAILABLE = "available"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class StabilityCondition(str, Enum):
    """Perturbations that must remain separate in stability reporting."""

    REPEAT = "repeat"
    ORDER = "order"
    FORMAT = "format"
    INJECTION = "injection"


def _validate_key(value: str, *, field: str) -> None:
    if not isinstance(value, str) or _OPAQUE_KEY.fullmatch(value) is None:
        raise ValueError(f"{field} must be an opaque identifier")


def _finite(value: float, *, field: str) -> float:
    if isinstance(value, (bool, str, bytes)):
        raise ValueError(f"{field} must be numeric")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field} must be finite")
    return number


def _bounded(value: float, *, field: str, low: float, high: float) -> float:
    number = _finite(value, field=field)
    if number < low or number > high:
        raise ValueError(f"{field} must be between {low} and {high}")
    return number


def _nonnegative_int(value: int, *, field: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field} must be a non-negative integer")
    return value


@dataclass(frozen=True, slots=True)
class ScalarEstimate:
    """A scalar and its usable sample count, or an explicit missing state."""

    state: EvaluationState
    value: float | None
    sample_count: int
    reason: str | None = None

    @classmethod
    def ready(cls, value: float, sample_count: int) -> ScalarEstimate:
        _nonnegative_int(sample_count, field="sample_count")
        if sample_count == 0:
            raise ValueError("a ready estimate requires at least one sample")
        return cls(
            state=EvaluationState.READY,
            value=_finite(value, field="estimate"),
            sample_count=sample_count,
        )

    @classmethod
    def insufficient(cls, reason: str, sample_count: int = 0) -> ScalarEstimate:
        _validate_key(reason, field="reason")
        _nonnegative_int(sample_count, field="sample_count")
        return cls(
            state=EvaluationState.INSUFFICIENT_DATA,
            value=None,
            sample_count=sample_count,
            reason=reason,
        )


@dataclass(frozen=True, slots=True)
class RateEstimate:
    """A rate retaining its numerator and denominator."""

    state: EvaluationState
    value: float | None
    numerator: int
    denominator: int
    reason: str | None = None

    @classmethod
    def from_counts(cls, numerator: int, denominator: int) -> RateEstimate:
        _nonnegative_int(numerator, field="numerator")
        _nonnegative_int(denominator, field="denominator")
        if numerator > denominator:
            raise ValueError("rate counts are inconsistent")
        if denominator == 0:
            return cls(
                state=EvaluationState.INSUFFICIENT_DATA,
                value=None,
                numerator=numerator,
                denominator=denominator,
                reason="zero_denominator",
            )
        return cls(
            state=EvaluationState.READY,
            value=numerator / denominator,
            numerator=numerator,
            denominator=denominator,
        )


@dataclass(frozen=True, slots=True)
class ClassificationObservation:
    """One prediction against an independently supplied reference label."""

    truth: str
    prediction: str
    truth_source: TruthSource
    probabilities: tuple[tuple[str, float], ...] = ()

    def __post_init__(self) -> None:
        _validate_key(self.truth, field="truth")
        _validate_key(self.prediction, field="prediction")
        if not isinstance(self.truth_source, TruthSource):
            raise ValueError("truth_source must be an allowed non-consensus source")
        seen: set[str] = set()
        total = 0.0
        for label, probability in self.probabilities:
            _validate_key(label, field="probability label")
            if label in seen:
                raise ValueError("probability labels must be unique")
            seen.add(label)
            total += _bounded(
                probability,
                field="probability",
                low=0.0,
                high=1.0,
            )
        if self.probabilities and not math.isclose(
            total,
            1.0,
            rel_tol=0.0,
            abs_tol=_PROBABILITY_TOLERANCE,
        ):
            raise ValueError("probabilities must sum to one")
        if self.probabilities and (
            self.truth not in seen or self.prediction not in seen
        ):
            raise ValueError("probabilities must include truth and prediction labels")

    def probability_map(self) -> dict[str, float]:
        return dict(self.probabilities)


@dataclass(frozen=True, slots=True)
class ClassMetrics:
    label: str
    support: int
    predicted_count: int
    true_positive: int
    false_positive: int
    false_negative: int
    precision: float
    recall: float
    f1: float


@dataclass(frozen=True, slots=True)
class CalibrationBin:
    index: int
    lower_bound: float
    upper_bound: float
    count: int
    mean_confidence: float | None
    accuracy: float | None
    absolute_gap: float | None


@dataclass(frozen=True, slots=True)
class CalibrationSlope:
    state: EvaluationState
    slope: float | None
    intercept: float | None
    sample_count: int
    iterations: int
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class SelectiveRiskPoint:
    threshold: float
    coverage: RateEstimate
    risk: RateEstimate


@dataclass(frozen=True, slots=True)
class ClassificationReport:
    state: EvaluationState
    sample_count: int
    probability_sample_count: int
    labels: tuple[str, ...]
    confusion_matrix: tuple[tuple[int, ...], ...]
    per_class: tuple[ClassMetrics, ...]
    accuracy: RateEstimate
    macro_precision: ScalarEstimate
    macro_recall: ScalarEstimate
    macro_f1: ScalarEstimate
    brier_score: ScalarEstimate
    log_loss: ScalarEstimate
    reliability: tuple[CalibrationBin, ...]
    expected_calibration_error: ScalarEstimate
    calibration_slope: CalibrationSlope
    false_confident_errors: RateEstimate
    selective_risk: tuple[SelectiveRiskPoint, ...]
    reason: str | None = None


def _insufficient_slope(reason: str, count: int = 0) -> CalibrationSlope:
    return CalibrationSlope(
        state=EvaluationState.INSUFFICIENT_DATA,
        slope=None,
        intercept=None,
        sample_count=count,
        iterations=0,
        reason=reason,
    )


def _binary_calibration_slope(
    observations: Sequence[ClassificationObservation],
    *,
    labels: tuple[str, ...],
    minimum_cases: int,
) -> CalibrationSlope:
    if len(labels) != 2:
        return _insufficient_slope("requires_binary_labels", len(observations))
    if len(observations) < minimum_cases:
        return _insufficient_slope("too_few_cases", len(observations))
    if any(not observation.probabilities for observation in observations):
        return _insufficient_slope("probabilities_missing", len(observations))

    positive = labels[-1]
    outcomes = [1.0 if observation.truth == positive else 0.0 for observation in observations]
    if len(set(outcomes)) < 2:
        return _insufficient_slope("single_outcome", len(observations))
    probabilities = [
        min(max(observation.probability_map()[positive], 1e-6), 1.0 - 1e-6)
        for observation in observations
    ]
    if len({round(probability, 12) for probability in probabilities}) < 3:
        return _insufficient_slope("insufficient_probability_variation", len(observations))
    logits = [math.log(probability / (1.0 - probability)) for probability in probabilities]

    intercept = math.log(sum(outcomes) / (len(outcomes) - sum(outcomes)))
    slope = 1.0
    ridge = 1e-9
    for iteration in range(1, 101):
        fitted = []
        for logit in logits:
            linear = max(min(intercept + slope * logit, 35.0), -35.0)
            fitted.append(1.0 / (1.0 + math.exp(-linear)))
        gradient_intercept = sum(y - p for y, p in zip(outcomes, fitted, strict=True))
        gradient_slope = sum(
            (y - p) * x
            for y, p, x in zip(outcomes, fitted, logits, strict=True)
        )
        weight = [p * (1.0 - p) for p in fitted]
        h00 = sum(weight) + ridge
        h01 = sum(w * x for w, x in zip(weight, logits, strict=True))
        h11 = sum(w * x * x for w, x in zip(weight, logits, strict=True)) + ridge
        determinant = h00 * h11 - h01 * h01
        if determinant <= 1e-14 or not math.isfinite(determinant):
            return _insufficient_slope("singular_fit", len(observations))
        delta_intercept = (
            gradient_intercept * h11 - gradient_slope * h01
        ) / determinant
        delta_slope = (
            gradient_slope * h00 - gradient_intercept * h01
        ) / determinant
        intercept += delta_intercept
        slope += delta_slope
        if not math.isfinite(intercept) or not math.isfinite(slope):
            return _insufficient_slope("non_finite_fit", len(observations))
        if max(abs(delta_intercept), abs(delta_slope)) < 1e-8:
            return CalibrationSlope(
                state=EvaluationState.READY,
                slope=slope,
                intercept=intercept,
                sample_count=len(observations),
                iterations=iteration,
            )
    return _insufficient_slope("fit_did_not_converge", len(observations))


def evaluate_classification(
    observations: Iterable[ClassificationObservation],
    *,
    reliability_bins: int = 10,
    false_confidence_threshold: float = 0.9,
    selective_thresholds: tuple[float, ...] = (0.0, 0.5, 0.75, 0.9, 0.95),
    slope_minimum_cases: int = 10,
) -> ClassificationReport:
    """Evaluate labels and calibrated probabilities without retaining content."""

    cases = tuple(observations)
    if reliability_bins < 2 or reliability_bins > 100:
        raise ValueError("reliability_bins must be between 2 and 100")
    confidence_threshold = _bounded(
        false_confidence_threshold,
        field="false_confidence_threshold",
        low=0.0,
        high=1.0,
    )
    thresholds = tuple(
        _bounded(threshold, field="selective_threshold", low=0.0, high=1.0)
        for threshold in selective_thresholds
    )
    if tuple(sorted(set(thresholds))) != thresholds:
        raise ValueError("selective_thresholds must be unique and increasing")
    if slope_minimum_cases < 3:
        raise ValueError("slope_minimum_cases must be at least three")

    if not cases:
        missing = ScalarEstimate.insufficient("no_cases")
        missing_rate = RateEstimate.from_counts(0, 0)
        return ClassificationReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            sample_count=0,
            probability_sample_count=0,
            labels=(),
            confusion_matrix=(),
            per_class=(),
            accuracy=missing_rate,
            macro_precision=missing,
            macro_recall=missing,
            macro_f1=missing,
            brier_score=missing,
            log_loss=missing,
            reliability=(),
            expected_calibration_error=missing,
            calibration_slope=_insufficient_slope("no_cases"),
            false_confident_errors=missing_rate,
            selective_risk=(),
            reason="no_cases",
        )

    labels = tuple(
        sorted(
            {case.truth for case in cases}
            | {case.prediction for case in cases}
            | {
                label
                for case in cases
                for label, _probability in case.probabilities
            }
        )
    )
    label_index = {label: index for index, label in enumerate(labels)}
    matrix = [[0 for _ in labels] for _ in labels]
    for case in cases:
        matrix[label_index[case.truth]][label_index[case.prediction]] += 1

    class_metrics: list[ClassMetrics] = []
    for index, label in enumerate(labels):
        true_positive = matrix[index][index]
        support = sum(matrix[index])
        predicted_count = sum(row[index] for row in matrix)
        false_positive = predicted_count - true_positive
        false_negative = support - true_positive
        # Macro metrics use the preregistered zero-division convention.  A class
        # that is never predicted (or never appears in the reference labels) is
        # not silently removed from the macro denominator.
        precision = true_positive / predicted_count if predicted_count else 0.0
        recall = true_positive / support if support else 0.0
        f1 = (
            2.0 * true_positive / (2.0 * true_positive + false_positive + false_negative)
            if 2 * true_positive + false_positive + false_negative
            else 0.0
        )
        class_metrics.append(
            ClassMetrics(
                label=label,
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

    correct = sum(matrix[index][index] for index in range(len(labels)))
    probability_cases = tuple(case for case in cases if case.probabilities)
    probability_case_count = len(probability_cases)

    if probability_cases:
        expected_labels = set(labels)
        for case in probability_cases:
            if set(case.probability_map()) != expected_labels:
                raise ValueError("each probability vector must cover every observed label")
        brier_values = []
        log_losses = []
        confidence_correctness: list[tuple[float, bool]] = []
        for case in probability_cases:
            probabilities = case.probability_map()
            brier_values.append(
                sum(
                    (probabilities[label] - (1.0 if case.truth == label else 0.0)) ** 2
                    for label in labels
                )
            )
            log_losses.append(-math.log(max(probabilities[case.truth], _LOG_EPSILON)))
            # Use the confidence assigned to the returned label.  Taking the
            # vector maximum would misstate calibration when a reviewed adapter
            # returns a non-argmax label (for example after a policy threshold).
            confidence = probabilities[case.prediction]
            confidence_correctness.append((confidence, case.prediction == case.truth))

        bins: list[CalibrationBin] = []
        weighted_gap = 0.0
        for index in range(reliability_bins):
            lower = index / reliability_bins
            upper = (index + 1) / reliability_bins
            members = [
                (confidence, correct_prediction)
                for confidence, correct_prediction in confidence_correctness
                if (lower <= confidence < upper)
                or (index == reliability_bins - 1 and confidence == 1.0)
            ]
            if members:
                mean_confidence = sum(item[0] for item in members) / len(members)
                accuracy = sum(1 for _, is_correct in members if is_correct) / len(members)
                gap = abs(mean_confidence - accuracy)
                weighted_gap += len(members) * gap
            else:
                mean_confidence = None
                accuracy = None
                gap = None
            bins.append(
                CalibrationBin(
                    index=index,
                    lower_bound=lower,
                    upper_bound=upper,
                    count=len(members),
                    mean_confidence=mean_confidence,
                    accuracy=accuracy,
                    absolute_gap=gap,
                )
            )
        brier = ScalarEstimate.ready(
            sum(brier_values) / probability_case_count,
            probability_case_count,
        )
        log_loss = ScalarEstimate.ready(
            sum(log_losses) / probability_case_count,
            probability_case_count,
        )
        ece = ScalarEstimate.ready(weighted_gap / probability_case_count, probability_case_count)
        false_confident_count = sum(
            1
            for confidence, is_correct in confidence_correctness
            if confidence >= confidence_threshold and not is_correct
        )
        false_confident = RateEstimate.from_counts(
            false_confident_count,
            probability_case_count,
        )
        selective = tuple(
            SelectiveRiskPoint(
                threshold=threshold,
                coverage=RateEstimate.from_counts(
                    sum(1 for confidence, _ in confidence_correctness if confidence >= threshold),
                    probability_case_count,
                ),
                risk=RateEstimate.from_counts(
                    sum(
                        1
                        for confidence, is_correct in confidence_correctness
                        if confidence >= threshold and not is_correct
                    ),
                    sum(1 for confidence, _ in confidence_correctness if confidence >= threshold),
                ),
            )
            for threshold in thresholds
        )
        reliability = tuple(bins)
    else:
        brier = ScalarEstimate.insufficient("probabilities_missing")
        log_loss = ScalarEstimate.insufficient("probabilities_missing")
        ece = ScalarEstimate.insufficient("probabilities_missing")
        false_confident = RateEstimate(
            state=EvaluationState.INSUFFICIENT_DATA,
            value=None,
            numerator=0,
            denominator=0,
            reason="probabilities_missing",
        )
        selective = ()
        reliability = ()

    return ClassificationReport(
        state=EvaluationState.READY,
        sample_count=len(cases),
        probability_sample_count=probability_case_count,
        labels=labels,
        confusion_matrix=tuple(tuple(row) for row in matrix),
        per_class=tuple(class_metrics),
        accuracy=RateEstimate.from_counts(correct, len(cases)),
        macro_precision=ScalarEstimate.ready(
            sum(item.precision for item in class_metrics) / len(class_metrics),
            len(class_metrics),
        ),
        macro_recall=ScalarEstimate.ready(
            sum(item.recall for item in class_metrics) / len(class_metrics),
            len(class_metrics),
        ),
        macro_f1=ScalarEstimate.ready(
            sum(item.f1 for item in class_metrics) / len(class_metrics),
            len(class_metrics),
        ),
        brier_score=brier,
        log_loss=log_loss,
        reliability=reliability,
        expected_calibration_error=ece,
        calibration_slope=_binary_calibration_slope(
            probability_cases,
            labels=labels,
            minimum_cases=slope_minimum_cases,
        ),
        false_confident_errors=false_confident,
        selective_risk=selective,
    )


@dataclass(frozen=True, slots=True)
class CalibrationSliceDimensions:
    """Content-free dimensions required for release-slice reporting.

    Project and time values are opaque buckets.  They must not be source paths,
    project names, transcript excerpts, or timestamps that identify a person.
    """

    task_stratum: CalibrationTaskStratum
    language: str
    provider: str
    project_bucket: str
    time_bucket: str
    evidence_availability: EvidenceAvailability

    def __post_init__(self) -> None:
        if not isinstance(self.task_stratum, CalibrationTaskStratum):
            raise ValueError("task_stratum must be a registered calibration stratum")
        if not isinstance(self.evidence_availability, EvidenceAvailability):
            raise ValueError("evidence_availability must be explicit")
        for field in ("language", "provider", "project_bucket", "time_bucket"):
            _validate_key(getattr(self, field), field=field)

    def items(self) -> tuple[tuple[str, str], ...]:
        return (
            ("task", self.task_stratum.value),
            ("language", self.language),
            ("provider", self.provider),
            ("project", self.project_bucket),
            ("time", self.time_bucket),
            ("evidence_availability", self.evidence_availability.value),
        )


@dataclass(frozen=True, slots=True)
class SlicedClassificationObservation:
    """A classification receipt plus only opaque release-slice dimensions."""

    case_key: str
    classification: ClassificationObservation
    dimensions: CalibrationSliceDimensions

    def __post_init__(self) -> None:
        _validate_key(self.case_key, field="case_key")
        if not isinstance(self.classification, ClassificationObservation):
            raise ValueError("classification must be a classification observation")
        if not isinstance(self.dimensions, CalibrationSliceDimensions):
            raise ValueError("dimensions must be calibration slice dimensions")


@dataclass(frozen=True, slots=True)
class ClassificationSlice:
    dimension: str
    value: str
    state: EvaluationState
    sample_count: int
    report: ClassificationReport | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ClassificationSliceReport:
    state: EvaluationState
    case_count: int
    strata_present: tuple[CalibrationTaskStratum, ...]
    missing_strata: tuple[CalibrationTaskStratum, ...]
    slices: tuple[ClassificationSlice, ...]
    reason: str | None = None

    def get(self, dimension: str, value: str) -> ClassificationSlice:
        _validate_key(dimension, field="slice dimension")
        _validate_key(value, field="slice value")
        for item in self.slices:
            if item.dimension == dimension and item.value == value:
                return item
        raise KeyError((dimension, value))


def evaluate_classification_slices(
    observations: Iterable[SlicedClassificationObservation],
    *,
    minimum_cases_per_slice: int = 1,
    reliability_bins: int = 10,
    false_confidence_threshold: float = 0.9,
    selective_thresholds: tuple[float, ...] = (0.0, 0.5, 0.75, 0.9, 0.95),
    slope_minimum_cases: int = 10,
) -> ClassificationSliceReport:
    """Report task, language, provider, project, time, and evidence slices.

    Small groups remain explicit ``insufficient_data`` slices.  The function
    never pools them into an apparent complete stratum.  It also rejects
    duplicate case identifiers so one judgment cannot be counted twice.
    """

    if type(minimum_cases_per_slice) is not int or minimum_cases_per_slice < 1:
        raise ValueError("minimum_cases_per_slice must be a positive integer")
    cases = tuple(observations)
    case_keys = tuple(case.case_key for case in cases)
    if len(set(case_keys)) != len(case_keys):
        raise ValueError("case_key values must be unique")
    if not cases:
        return ClassificationSliceReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            case_count=0,
            strata_present=(),
            missing_strata=REQUIRED_CALIBRATION_STRATA,
            slices=(),
            reason="no_cases",
        )

    groups: dict[tuple[str, str], list[ClassificationObservation]] = {}
    for case in cases:
        for dimension, value in case.dimensions.items():
            groups.setdefault((dimension, value), []).append(case.classification)

    slices: list[ClassificationSlice] = []
    for (dimension, value), classifications in sorted(groups.items()):
        if len(classifications) < minimum_cases_per_slice:
            slices.append(
                ClassificationSlice(
                    dimension=dimension,
                    value=value,
                    state=EvaluationState.INSUFFICIENT_DATA,
                    sample_count=len(classifications),
                    report=None,
                    reason="too_few_cases",
                )
            )
            continue
        slices.append(
            ClassificationSlice(
                dimension=dimension,
                value=value,
                state=EvaluationState.READY,
                sample_count=len(classifications),
                report=evaluate_classification(
                    classifications,
                    reliability_bins=reliability_bins,
                    false_confidence_threshold=false_confidence_threshold,
                    selective_thresholds=selective_thresholds,
                    slope_minimum_cases=slope_minimum_cases,
                ),
            )
        )

    present_set = {case.dimensions.task_stratum for case in cases}
    present = tuple(item for item in REQUIRED_CALIBRATION_STRATA if item in present_set)
    missing = tuple(item for item in REQUIRED_CALIBRATION_STRATA if item not in present_set)
    return ClassificationSliceReport(
        state=EvaluationState.READY
        if any(item.state is EvaluationState.READY for item in slices)
        else EvaluationState.INSUFFICIENT_DATA,
        case_count=len(cases),
        strata_present=present,
        missing_strata=missing,
        slices=tuple(slices),
        reason=None
        if any(item.state is EvaluationState.READY for item in slices)
        else "all_slices_too_small",
    )


@dataclass(frozen=True, slots=True)
class RetrievalObservation:
    """One ranked retrieval result with opaque evidence identifiers."""

    case_key: str
    relevant_ids: tuple[str, ...]
    ranked_ids: tuple[str, ...]
    linked_ids: tuple[str, ...] = ()
    judgment_available: bool = True
    truth_source: TruthSource = TruthSource.HUMAN_ADJUDICATED

    def __post_init__(self) -> None:
        _validate_key(self.case_key, field="case_key")
        if not isinstance(self.truth_source, TruthSource):
            raise ValueError("truth_source must be an allowed non-consensus source")
        if not isinstance(self.judgment_available, bool):
            raise ValueError("judgment_available must be boolean")
        if not self.judgment_available and self.relevant_ids:
            raise ValueError("unjudged cases cannot carry relevant identifiers")
        for field, values in (
            ("relevant_id", self.relevant_ids),
            ("ranked_id", self.ranked_ids),
            ("linked_id", self.linked_ids),
        ):
            for value in values:
                _validate_key(value, field=field)
            if len(set(values)) != len(values):
                raise ValueError(f"{field}s must be unique")


@dataclass(frozen=True, slots=True)
class RetrievalAtK:
    k: int
    recall: ScalarEstimate
    ndcg: ScalarEstimate


@dataclass(frozen=True, slots=True)
class RetrievalReport:
    state: EvaluationState
    case_count: int
    judged_case_count: int
    eligible_case_count: int
    zero_relevant_case_count: int
    at_k: tuple[RetrievalAtK, ...]
    mean_reciprocal_rank: ScalarEstimate
    link_precision: RateEstimate
    reason: str | None = None


def evaluate_retrieval(
    observations: Iterable[RetrievalObservation],
    *,
    ks: tuple[int, ...] = (1, 3, 5, 10),
) -> RetrievalReport:
    """Compute binary-relevance Recall@k, MRR, nDCG@k, and link precision."""

    cases = tuple(observations)
    if not ks or any(k <= 0 for k in ks) or tuple(sorted(set(ks))) != ks:
        raise ValueError("ks must be unique, positive, and increasing")
    case_keys = tuple(case.case_key for case in cases)
    if len(set(case_keys)) != len(case_keys):
        raise ValueError("case_key values must be unique")
    judged = tuple(case for case in cases if case.judgment_available)
    eligible = tuple(case for case in judged if case.relevant_ids)
    linked_total = sum(len(case.linked_ids) for case in judged)
    linked_correct = sum(
        len(set(case.linked_ids) & set(case.relevant_ids)) for case in judged
    )
    link_precision = RateEstimate.from_counts(linked_correct, linked_total)
    if not eligible:
        return RetrievalReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            case_count=len(cases),
            judged_case_count=len(judged),
            eligible_case_count=0,
            zero_relevant_case_count=len(judged),
            at_k=tuple(
                RetrievalAtK(
                    k=k,
                    recall=ScalarEstimate.insufficient("no_relevance_judgments"),
                    ndcg=ScalarEstimate.insufficient("no_relevance_judgments"),
                )
                for k in ks
            ),
            mean_reciprocal_rank=ScalarEstimate.insufficient("no_relevance_judgments"),
            link_precision=link_precision,
            reason="no_relevance_judgments" if not judged else "no_positive_relevance_cases",
        )

    at_k: list[RetrievalAtK] = []
    for k in ks:
        recalls = []
        ndcgs = []
        for case in eligible:
            relevant = set(case.relevant_ids)
            ranked = case.ranked_ids[:k]
            recalls.append(len(relevant & set(ranked)) / len(relevant))
            dcg = sum(
                1.0 / math.log2(index + 2)
                for index, evidence_id in enumerate(ranked)
                if evidence_id in relevant
            )
            ideal_count = min(k, len(relevant))
            ideal_dcg = sum(1.0 / math.log2(index + 2) for index in range(ideal_count))
            ndcgs.append(dcg / ideal_dcg)
        at_k.append(
            RetrievalAtK(
                k=k,
                recall=ScalarEstimate.ready(sum(recalls) / len(recalls), len(recalls)),
                ndcg=ScalarEstimate.ready(sum(ndcgs) / len(ndcgs), len(ndcgs)),
            )
        )

    reciprocal_ranks = []
    for case in eligible:
        relevant = set(case.relevant_ids)
        rank = next(
            (index for index, evidence_id in enumerate(case.ranked_ids, start=1) if evidence_id in relevant),
            None,
        )
        reciprocal_ranks.append(1.0 / rank if rank is not None else 0.0)
    return RetrievalReport(
        state=EvaluationState.READY,
        case_count=len(cases),
        judged_case_count=len(judged),
        eligible_case_count=len(eligible),
        zero_relevant_case_count=len(judged) - len(eligible),
        at_k=tuple(at_k),
        mean_reciprocal_rank=ScalarEstimate.ready(
            sum(reciprocal_ranks) / len(reciprocal_ranks),
            len(reciprocal_ranks),
        ),
        link_precision=link_precision,
    )


@dataclass(frozen=True, slots=True)
class AgreementObservation:
    first_label: str
    second_label: str

    def __post_init__(self) -> None:
        _validate_key(self.first_label, field="first_label")
        _validate_key(self.second_label, field="second_label")


@dataclass(frozen=True, slots=True)
class AgreementReport:
    state: EvaluationState
    kind: str
    sample_count: int
    observed_agreement: RateEstimate
    cohen_kappa: ScalarEstimate
    reason: str | None = None


def evaluate_agreement(
    observations: Iterable[AgreementObservation],
    *,
    kind: str,
) -> AgreementReport:
    """Compute observed agreement and Cohen's kappa for paired labels."""

    if kind not in {"human_human", "model_human"}:
        raise ValueError("kind must be human_human or model_human")
    pairs = tuple(observations)
    if not pairs:
        return AgreementReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            kind=kind,
            sample_count=0,
            observed_agreement=RateEstimate.from_counts(0, 0),
            cohen_kappa=ScalarEstimate.insufficient("no_pairs"),
            reason="no_pairs",
        )
    matches = sum(pair.first_label == pair.second_label for pair in pairs)
    labels = {pair.first_label for pair in pairs} | {pair.second_label for pair in pairs}
    first_counts = Counter(pair.first_label for pair in pairs)
    second_counts = Counter(pair.second_label for pair in pairs)
    expected = sum(
        (first_counts[label] / len(pairs)) * (second_counts[label] / len(pairs))
        for label in labels
    )
    observed = matches / len(pairs)
    kappa = (
        ScalarEstimate.ready((observed - expected) / (1.0 - expected), len(pairs))
        if expected < 1.0 - 1e-12
        else ScalarEstimate.insufficient("degenerate_marginals", len(pairs))
    )
    return AgreementReport(
        state=EvaluationState.READY,
        kind=kind,
        sample_count=len(pairs),
        observed_agreement=RateEstimate.from_counts(matches, len(pairs)),
        cohen_kappa=kappa,
    )


def human_human_agreement(
    observations: Iterable[AgreementObservation],
) -> AgreementReport:
    return evaluate_agreement(observations, kind="human_human")


def model_human_agreement(
    observations: Iterable[AgreementObservation],
) -> AgreementReport:
    return evaluate_agreement(observations, kind="model_human")


@dataclass(frozen=True, slots=True)
class RepeatObservation:
    case_key: str
    labels: tuple[str, ...]

    def __post_init__(self) -> None:
        _validate_key(self.case_key, field="case_key")
        for label in self.labels:
            _validate_key(label, field="repeat_label")


@dataclass(frozen=True, slots=True)
class RepeatStabilityReport:
    state: EvaluationState
    case_count: int
    repeat_pair_count: int
    pairwise_stability: RateEstimate
    fully_stable_cases: RateEstimate
    reason: str | None = None


def evaluate_repeat_stability(
    observations: Iterable[RepeatObservation],
) -> RepeatStabilityReport:
    """Measure exact-label stability over independent repeated runs."""

    observations_tuple = tuple(observations)
    all_case_keys = tuple(case.case_key for case in observations_tuple)
    if len(set(all_case_keys)) != len(all_case_keys):
        raise ValueError("case_key values must be unique")
    cases = tuple(case for case in observations_tuple if len(case.labels) >= 2)
    pair_count = 0
    pair_matches = 0
    for case in cases:
        for left in range(len(case.labels)):
            for right in range(left + 1, len(case.labels)):
                pair_count += 1
                pair_matches += case.labels[left] == case.labels[right]
    if not cases:
        return RepeatStabilityReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            case_count=0,
            repeat_pair_count=0,
            pairwise_stability=RateEstimate.from_counts(0, 0),
            fully_stable_cases=RateEstimate.from_counts(0, 0),
            reason="no_repeated_cases",
        )
    stable_cases = sum(len(set(case.labels)) == 1 for case in cases)
    return RepeatStabilityReport(
        state=EvaluationState.READY,
        case_count=len(cases),
        repeat_pair_count=pair_count,
        pairwise_stability=RateEstimate.from_counts(pair_matches, pair_count),
        fully_stable_cases=RateEstimate.from_counts(stable_cases, len(cases)),
    )


@dataclass(frozen=True, slots=True)
class PerturbationStabilityObservation:
    """One reference/perturbed label pair with no retained model content."""

    case_key: str
    condition: StabilityCondition
    reference_label: str
    perturbed_label: str

    def __post_init__(self) -> None:
        _validate_key(self.case_key, field="case_key")
        if not isinstance(self.condition, StabilityCondition):
            raise ValueError("condition must be a registered stability condition")
        _validate_key(self.reference_label, field="reference_label")
        _validate_key(self.perturbed_label, field="perturbed_label")


@dataclass(frozen=True, slots=True)
class StabilityConditionReceipt:
    condition: StabilityCondition
    case_count: int
    stability: RateEstimate


@dataclass(frozen=True, slots=True)
class StabilitySuiteReport:
    state: EvaluationState
    pair_count: int
    conditions: tuple[StabilityConditionReceipt, ...]
    missing_conditions: tuple[StabilityCondition, ...]
    reason: str | None = None


def evaluate_stability_suite(
    observations: Iterable[PerturbationStabilityObservation],
) -> StabilitySuiteReport:
    """Keep repeat, order, format, and injection stability distinguishable."""

    pairs = tuple(observations)
    pair_keys = tuple((pair.case_key, pair.condition) for pair in pairs)
    if len(set(pair_keys)) != len(pair_keys):
        raise ValueError("case_key and condition pairs must be unique")
    if not pairs:
        return StabilitySuiteReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            pair_count=0,
            conditions=tuple(
                StabilityConditionReceipt(
                    condition=condition,
                    case_count=0,
                    stability=RateEstimate.from_counts(0, 0),
                )
                for condition in StabilityCondition
            ),
            missing_conditions=tuple(StabilityCondition),
            reason="no_pairs",
        )

    receipts: list[StabilityConditionReceipt] = []
    missing: list[StabilityCondition] = []
    for condition in StabilityCondition:
        members = tuple(pair for pair in pairs if pair.condition is condition)
        if not members:
            missing.append(condition)
        receipts.append(
            StabilityConditionReceipt(
                condition=condition,
                case_count=len(members),
                stability=RateEstimate.from_counts(
                    sum(pair.reference_label == pair.perturbed_label for pair in members),
                    len(members),
                ),
            )
        )
    return StabilitySuiteReport(
        state=EvaluationState.READY,
        pair_count=len(pairs),
        conditions=tuple(receipts),
        missing_conditions=tuple(missing),
    )


@dataclass(frozen=True, slots=True)
class RunTelemetry:
    """Content-free timing, resource, reliability, and cost measurements."""

    latency_ms: float
    cold: bool
    queue_ms: float | None = None
    throughput_per_second: float | None = None
    peak_ram_mb: float | None = None
    peak_vram_mb: float | None = None
    disk_mb: float | None = None
    energy_wh: float | None = None
    api_cost_usd: float | None = None
    oom: bool = False
    error: bool = False
    refused: bool = False

    def __post_init__(self) -> None:
        if _finite(self.latency_ms, field="latency_ms") < 0:
            raise ValueError("latency_ms cannot be negative")
        if not isinstance(self.cold, bool):
            raise ValueError("cold must be boolean")
        for field in (
            "queue_ms",
            "throughput_per_second",
            "peak_ram_mb",
            "peak_vram_mb",
            "disk_mb",
            "energy_wh",
            "api_cost_usd",
        ):
            value = getattr(self, field)
            if value is not None and _finite(value, field=field) < 0:
                raise ValueError(f"{field} cannot be negative")
        for field in ("oom", "error", "refused"):
            if not isinstance(getattr(self, field), bool):
                raise ValueError(f"{field} must be boolean")


@dataclass(frozen=True, slots=True)
class DistributionEstimate:
    state: EvaluationState
    count: int
    mean: float | None
    p50: float | None
    p95: float | None
    maximum: float | None
    total: float | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class NamedDistribution:
    key: str
    estimate: DistributionEstimate


@dataclass(frozen=True, slots=True)
class TelemetryReport:
    state: EvaluationState
    run_count: int
    distributions: tuple[NamedDistribution, ...]
    oom_rate: RateEstimate
    error_rate: RateEstimate
    refusal_rate: RateEstimate
    reason: str | None = None

    def distribution(self, key: str) -> DistributionEstimate:
        _validate_key(key, field="distribution key")
        for item in self.distributions:
            if item.key == key:
                return item.estimate
        raise KeyError(key)


def _quantile(values: Sequence[float], probability: float) -> float:
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = (len(ordered) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    if lower == upper:
        return ordered[lower]
    weight = position - lower
    return ordered[lower] * (1.0 - weight) + ordered[upper] * weight


def _distribution(values: Iterable[float]) -> DistributionEstimate:
    samples = tuple(values)
    if not samples:
        return DistributionEstimate(
            state=EvaluationState.INSUFFICIENT_DATA,
            count=0,
            mean=None,
            p50=None,
            p95=None,
            maximum=None,
            total=None,
            reason="no_measurements",
        )
    return DistributionEstimate(
        state=EvaluationState.READY,
        count=len(samples),
        mean=sum(samples) / len(samples),
        p50=_quantile(samples, 0.5),
        p95=_quantile(samples, 0.95),
        maximum=max(samples),
        total=sum(samples),
    )


def summarize_telemetry(observations: Iterable[RunTelemetry]) -> TelemetryReport:
    """Summarize cold/warm latency, queue, throughput, resources, and failures."""

    runs = tuple(observations)
    fields: tuple[tuple[str, tuple[float, ...]], ...] = (
        ("latency_ms", tuple(run.latency_ms for run in runs)),
        ("cold_latency_ms", tuple(run.latency_ms for run in runs if run.cold)),
        ("warm_latency_ms", tuple(run.latency_ms for run in runs if not run.cold)),
        ("queue_ms", tuple(run.queue_ms for run in runs if run.queue_ms is not None)),
        (
            "throughput_per_second",
            tuple(
                run.throughput_per_second
                for run in runs
                if run.throughput_per_second is not None
            ),
        ),
        ("peak_ram_mb", tuple(run.peak_ram_mb for run in runs if run.peak_ram_mb is not None)),
        (
            "peak_vram_mb",
            tuple(run.peak_vram_mb for run in runs if run.peak_vram_mb is not None),
        ),
        ("disk_mb", tuple(run.disk_mb for run in runs if run.disk_mb is not None)),
        ("energy_wh", tuple(run.energy_wh for run in runs if run.energy_wh is not None)),
        (
            "api_cost_usd",
            tuple(run.api_cost_usd for run in runs if run.api_cost_usd is not None),
        ),
    )
    if not runs:
        return TelemetryReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            run_count=0,
            distributions=tuple(
                NamedDistribution(key=key, estimate=_distribution(values))
                for key, values in fields
            ),
            oom_rate=RateEstimate.from_counts(0, 0),
            error_rate=RateEstimate.from_counts(0, 0),
            refusal_rate=RateEstimate.from_counts(0, 0),
            reason="no_runs",
        )
    return TelemetryReport(
        state=EvaluationState.READY,
        run_count=len(runs),
        distributions=tuple(
            NamedDistribution(key=key, estimate=_distribution(values))
            for key, values in fields
        ),
        oom_rate=RateEstimate.from_counts(sum(run.oom for run in runs), len(runs)),
        error_rate=RateEstimate.from_counts(sum(run.error for run in runs), len(runs)),
        refusal_rate=RateEstimate.from_counts(sum(run.refused for run in runs), len(runs)),
    )


@dataclass(frozen=True, slots=True)
class CascadeObservation:
    """Per-case stage utility receipts from objective or human evaluation."""

    case_key: str
    stage_values: tuple[tuple[str, float], ...]
    stop_stage: str
    value_source: TruthSource

    def __post_init__(self) -> None:
        _validate_key(self.case_key, field="case_key")
        _validate_key(self.stop_stage, field="stop_stage")
        if not isinstance(self.value_source, TruthSource):
            raise ValueError("value_source must be an allowed non-consensus source")
        stages: set[str] = set()
        for stage, value in self.stage_values:
            _validate_key(stage, field="stage")
            if stage in stages:
                raise ValueError("stages must be unique")
            stages.add(stage)
            _bounded(value, field="stage_value", low=0.0, high=1.0)
        if self.stop_stage not in stages:
            raise ValueError("stop_stage must have a stage value")


@dataclass(frozen=True, slots=True)
class CascadeStageReceipt:
    stage: str
    reached_count: int
    stop_count: int
    stop_rate: RateEstimate
    mean_value: ScalarEstimate
    incremental_value: ScalarEstimate


@dataclass(frozen=True, slots=True)
class CascadeReport:
    state: EvaluationState
    case_count: int
    stages: tuple[CascadeStageReceipt, ...]
    reason: str | None = None


def evaluate_cascade(
    observations: Iterable[CascadeObservation],
    *,
    stage_order: tuple[str, ...],
) -> CascadeReport:
    """Aggregate stop rates and paired incremental value for a serial cascade."""

    if not stage_order or len(set(stage_order)) != len(stage_order):
        raise ValueError("stage_order must be non-empty and unique")
    for stage in stage_order:
        _validate_key(stage, field="stage_order")
    cases = tuple(observations)
    case_keys = tuple(case.case_key for case in cases)
    if len(set(case_keys)) != len(case_keys):
        raise ValueError("case_key values must be unique")
    order_index = {stage: index for index, stage in enumerate(stage_order)}
    for case in cases:
        stages = tuple(stage for stage, _ in case.stage_values)
        if any(stage not in order_index for stage in stages):
            raise ValueError("observation contains an unknown stage")
        expected_prefix = stage_order[: len(stages)]
        if stages != expected_prefix:
            raise ValueError("stage values must be a contiguous ordered prefix")
        if case.stop_stage != stages[-1]:
            raise ValueError("stop_stage must be the final reached stage")
    if not cases:
        return CascadeReport(
            state=EvaluationState.INSUFFICIENT_DATA,
            case_count=0,
            stages=(),
            reason="no_cases",
        )

    receipts: list[CascadeStageReceipt] = []
    for index, stage in enumerate(stage_order):
        reached = [case for case in cases if stage in dict(case.stage_values)]
        stopped = sum(case.stop_stage == stage for case in reached)
        values = [dict(case.stage_values)[stage] for case in reached]
        if index == 0:
            incremental = ScalarEstimate.insufficient(
                "no_prior_stage",
                len(reached),
            )
        else:
            prior = stage_order[index - 1]
            paired_differences = [
                dict(case.stage_values)[stage] - dict(case.stage_values)[prior]
                for case in reached
            ]
            incremental = (
                ScalarEstimate.ready(
                    sum(paired_differences) / len(paired_differences),
                    len(paired_differences),
                )
                if paired_differences
                else ScalarEstimate.insufficient("stage_not_reached")
            )
        receipts.append(
            CascadeStageReceipt(
                stage=stage,
                reached_count=len(reached),
                stop_count=stopped,
                stop_rate=RateEstimate.from_counts(stopped, len(reached)),
                mean_value=ScalarEstimate.ready(sum(values) / len(values), len(values))
                if values
                else ScalarEstimate.insufficient("stage_not_reached"),
                incremental_value=incremental,
            )
        )
    return CascadeReport(
        state=EvaluationState.READY,
        case_count=len(cases),
        stages=tuple(receipts),
    )


@dataclass(frozen=True, slots=True)
class SubgroupDelta:
    key: str
    candidate_minus_baseline: float

    def __post_init__(self) -> None:
        _validate_key(self.key, field="subgroup key")
        _bounded(
            self.candidate_minus_baseline,
            field="candidate_minus_baseline",
            low=-1.0,
            high=1.0,
        )


@dataclass(frozen=True, slots=True)
class ActivationGateEvidence:
    """Preregistered holdout evidence used to consider an estimator active."""

    candidate_performance: float | None
    baseline_performance: float | None
    adjudicated_human_performance: float | None
    expected_calibration_error: float | None
    repeat_stability: float | None
    subgroup_deltas: tuple[SubgroupDelta, ...] | None
    holdout_untouched: bool | None
    human_baseline_adjudicated: bool | None
    synthetic_only: bool | None
    truth_sources: frozenset[TruthSource]
    calibration_strata: frozenset[CalibrationTaskStratum] | None = None

    def __post_init__(self) -> None:
        for field in (
            "candidate_performance",
            "baseline_performance",
            "adjudicated_human_performance",
            "expected_calibration_error",
            "repeat_stability",
        ):
            value = getattr(self, field)
            if value is not None:
                _bounded(value, field=field, low=0.0, high=1.0)
        for field in (
            "holdout_untouched",
            "human_baseline_adjudicated",
            "synthetic_only",
        ):
            value = getattr(self, field)
            if value is not None and not isinstance(value, bool):
                raise ValueError(f"{field} must be boolean or unknown")
        if any(not isinstance(source, TruthSource) for source in self.truth_sources):
            raise ValueError("truth_sources may contain only supported non-consensus sources")
        if self.calibration_strata is not None and any(
            not isinstance(stratum, CalibrationTaskStratum)
            for stratum in self.calibration_strata
        ):
            raise ValueError("calibration_strata contains an unsupported task family")
        if self.subgroup_deltas is not None:
            subgroup_keys = tuple(item.key for item in self.subgroup_deltas)
            if len(set(subgroup_keys)) != len(subgroup_keys):
                raise ValueError("subgroup delta keys must be unique")


@dataclass(frozen=True, slots=True)
class GateCheck:
    key: str
    outcome: CheckOutcome
    actual: float | bool | None
    threshold: float | bool | None
    reason: str | None = None


@dataclass(frozen=True, slots=True)
class ActivationGateReport:
    outcome: GateOutcome
    checks: tuple[GateCheck, ...]


def _numeric_gate(
    key: str,
    actual: float | None,
    threshold: float,
    predicate: bool | None,
    *,
    missing_reason: str,
) -> GateCheck:
    if actual is None or predicate is None:
        return GateCheck(
            key=key,
            outcome=CheckOutcome.INSUFFICIENT_DATA,
            actual=actual,
            threshold=threshold,
            reason=missing_reason,
        )
    return GateCheck(
        key=key,
        outcome=CheckOutcome.PASS if predicate else CheckOutcome.FAIL,
        actual=actual,
        threshold=threshold,
    )


def evaluate_activation_gate(
    evidence: ActivationGateEvidence,
    *,
    maximum_human_gap: float = 0.05,
    maximum_ece: float = 0.05,
    minimum_stability: float = 0.95,
    maximum_material_subgroup_regression: float = 0.02,
    minimum_baseline_margin: float = 0.0,
    required_strata: tuple[CalibrationTaskStratum, ...] = REQUIRED_CALIBRATION_STRATA,
) -> ActivationGateReport:
    """Apply the default private-holdout activation predicates.

    A failure rejects activation.  If no check fails but at least one required
    observation is missing, the result remains ``insufficient_data``.
    """

    maximum_human_gap = _bounded(
        maximum_human_gap,
        field="maximum_human_gap",
        low=0.0,
        high=1.0,
    )
    maximum_ece = _bounded(maximum_ece, field="maximum_ece", low=0.0, high=1.0)
    minimum_stability = _bounded(
        minimum_stability,
        field="minimum_stability",
        low=0.0,
        high=1.0,
    )
    maximum_material_subgroup_regression = _bounded(
        maximum_material_subgroup_regression,
        field="maximum_material_subgroup_regression",
        low=0.0,
        high=1.0,
    )
    minimum_baseline_margin = _bounded(
        minimum_baseline_margin,
        field="minimum_baseline_margin",
        low=0.0,
        high=1.0,
    )
    if (
        not required_strata
        or len(set(required_strata)) != len(required_strata)
        or any(not isinstance(item, CalibrationTaskStratum) for item in required_strata)
    ):
        raise ValueError("required_strata must be unique registered task families")

    candidate = evidence.candidate_performance
    baseline = evidence.baseline_performance
    human = evidence.adjudicated_human_performance
    checks: list[GateCheck] = []
    if candidate is None or baseline is None:
        checks.append(
            GateCheck(
                key="beats_baseline",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=minimum_baseline_margin,
                reason="performance_missing",
            )
        )
    else:
        margin = candidate - baseline
        checks.append(
            GateCheck(
                key="beats_baseline",
                outcome=CheckOutcome.PASS
                if margin > minimum_baseline_margin
                else CheckOutcome.FAIL,
                actual=margin,
                threshold=minimum_baseline_margin,
            )
        )

    if candidate is None or human is None:
        checks.append(
            GateCheck(
                key="within_human_baseline",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=maximum_human_gap,
                reason="human_comparison_missing",
            )
        )
    else:
        gap = abs(human - candidate)
        checks.append(
            GateCheck(
                key="within_human_baseline",
                outcome=CheckOutcome.PASS if gap <= maximum_human_gap else CheckOutcome.FAIL,
                actual=gap,
                threshold=maximum_human_gap,
            )
        )

    ece = evidence.expected_calibration_error
    checks.append(
        _numeric_gate(
            "ece",
            ece,
            maximum_ece,
            None if ece is None else ece <= maximum_ece,
            missing_reason="ece_missing",
        )
    )
    stability = evidence.repeat_stability
    checks.append(
        _numeric_gate(
            "repeat_stability",
            stability,
            minimum_stability,
            None if stability is None else stability >= minimum_stability,
            missing_reason="stability_missing",
        )
    )

    subgroup_deltas = evidence.subgroup_deltas
    if not subgroup_deltas:
        checks.append(
            GateCheck(
                key="subgroup_regression",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=-maximum_material_subgroup_regression,
                reason="subgroup_evaluation_missing",
            )
        )
    else:
        worst_delta = min(item.candidate_minus_baseline for item in subgroup_deltas)
        checks.append(
            GateCheck(
                key="subgroup_regression",
                outcome=CheckOutcome.PASS
                if worst_delta >= -maximum_material_subgroup_regression
                else CheckOutcome.FAIL,
                actual=worst_delta,
                threshold=-maximum_material_subgroup_regression,
            )
        )

    if evidence.calibration_strata is None:
        checks.append(
            GateCheck(
                key="calibration_strata",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=True,
                reason="strata_status_missing",
            )
        )
    else:
        all_strata_present = set(required_strata).issubset(evidence.calibration_strata)
        checks.append(
            GateCheck(
                key="calibration_strata",
                outcome=CheckOutcome.PASS if all_strata_present else CheckOutcome.FAIL,
                actual=all_strata_present,
                threshold=True,
                reason=None if all_strata_present else "required_strata_missing",
            )
        )

    for key, actual, required, missing_reason in (
        ("holdout_untouched", evidence.holdout_untouched, True, "holdout_status_missing"),
        (
            "human_baseline_adjudicated",
            evidence.human_baseline_adjudicated,
            True,
            "adjudication_status_missing",
        ),
    ):
        checks.append(
            GateCheck(
                key=key,
                outcome=CheckOutcome.INSUFFICIENT_DATA
                if actual is None
                else (CheckOutcome.PASS if actual is required else CheckOutcome.FAIL),
                actual=actual,
                threshold=required,
                reason=missing_reason if actual is None else None,
            )
        )

    if evidence.synthetic_only is None:
        checks.append(
            GateCheck(
                key="representative_private_holdout",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=False,
                reason="holdout_origin_missing",
            )
        )
    else:
        checks.append(
            GateCheck(
                key="representative_private_holdout",
                outcome=CheckOutcome.FAIL if evidence.synthetic_only else CheckOutcome.PASS,
                actual=evidence.synthetic_only,
                threshold=False,
            )
        )

    if evidence.truth_sources:
        checks.append(
            GateCheck(
                key="non_consensus_truth",
                outcome=CheckOutcome.PASS,
                actual=True,
                threshold=True,
            )
        )
    else:
        checks.append(
            GateCheck(
                key="non_consensus_truth",
                outcome=CheckOutcome.INSUFFICIENT_DATA,
                actual=None,
                threshold=True,
                reason="truth_source_missing",
            )
        )

    outcomes = {check.outcome for check in checks}
    if CheckOutcome.FAIL in outcomes:
        outcome = GateOutcome.REJECTED
    elif CheckOutcome.INSUFFICIENT_DATA in outcomes:
        outcome = GateOutcome.INSUFFICIENT_DATA
    else:
        outcome = GateOutcome.ELIGIBLE
    return ActivationGateReport(outcome=outcome, checks=tuple(checks))
