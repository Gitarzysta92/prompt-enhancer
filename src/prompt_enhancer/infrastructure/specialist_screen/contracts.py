"""Closed, content-bounded contracts for the synthetic specialist screen."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import math
import re


_SAFE_KEY = re.compile(r"[a-z][a-z0-9_]{2,63}\Z")
_LOWER_HEX_64 = re.compile(r"[0-9a-f]{64}\Z")
_CONTROL_CHARACTER = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")


class SpecialistLabel(str, Enum):
    ENTAILMENT = "entailment"
    NEUTRAL = "neutral"
    CONTRADICTION = "contradiction"


SPECIALIST_LABEL_ORDER = (
    SpecialistLabel.ENTAILMENT,
    SpecialistLabel.NEUTRAL,
    SpecialistLabel.CONTRADICTION,
)


class SpecialistOutcome(str, Enum):
    ENTAILMENT = "entailment"
    NEUTRAL = "neutral"
    CONTRADICTION = "contradiction"
    ABSTAIN = "abstain"


class SpecialistCompatibility(str, Enum):
    COMPATIBLE = "compatible"
    DIFFERENT_SCOPE = "different_scope"
    SUPERSEDED = "superseded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class SpecialistTaskStratum(str, Enum):
    BUG_FIX = "bug_fix"
    FEATURE = "feature"
    CODE_REVIEW = "code_review"
    RESEARCH_DESIGN = "research_design"


class SpecialistPredictionState(str, Enum):
    KNOWN = "known"
    ABSTAINED = "abstained"


class SpecialistAbstentionReason(str, Enum):
    BASELINE_REQUIRES_OBJECTIVE_EVIDENCE = "baseline_requires_objective_evidence"
    DIFFERENT_SCOPE = "different_scope"
    SUPERSEDED = "superseded"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"
    LOW_CONFIDENCE = "low_confidence"


@dataclass(frozen=True, slots=True)
class SpecialistCase:
    """One fictional, typed claim comparison.

    The compatibility field is explicit test metadata.  It represents the
    deterministic scope/temporal router that must run before an NLI model; the
    model never gets permission to reinterpret an incompatible comparison.
    """

    language: str
    task_stratum: SpecialistTaskStratum
    premise: str
    hypothesis: str
    compatibility: SpecialistCompatibility
    expected_outcome: SpecialistOutcome
    critical_claim: bool

    def __post_init__(self) -> None:
        if self.language not in {"en", "pl"}:
            raise ValueError("specialist language must be en or pl")
        for value in (self.premise, self.hypothesis):
            if not value or value != value.strip() or len(value) > 768:
                raise ValueError("specialist text must be non-empty, trimmed, and bounded")
            if _CONTROL_CHARACTER.search(value):
                raise ValueError("specialist text contains a control character")
        if self.compatibility is SpecialistCompatibility.COMPATIBLE:
            if self.expected_outcome is SpecialistOutcome.ABSTAIN:
                raise ValueError("compatible specialist cases require an NLI label")
        elif self.expected_outcome is not SpecialistOutcome.ABSTAIN:
            raise ValueError("incompatible specialist cases must expect abstention")
        if not isinstance(self.critical_claim, bool):
            raise ValueError("critical_claim must be boolean")


@dataclass(frozen=True, slots=True)
class SpecialistCorpus:
    schema_version: int
    benchmark_id: str
    synthetic_only: bool
    source_fixture_sha256: str
    cases: tuple[SpecialistCase, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported specialist corpus schema")
        if _SAFE_KEY.fullmatch(self.benchmark_id) is None:
            raise ValueError("specialist benchmark id must be a safe stable key")
        if self.synthetic_only is not True:
            raise ValueError("specialist corpus must be explicitly synthetic")
        if _LOWER_HEX_64.fullmatch(self.source_fixture_sha256) is None:
            raise ValueError("specialist corpus fixture digest must be immutable")
        if not 8 <= len(self.cases) <= 200:
            raise ValueError("specialist corpus size is outside the reviewed bound")
        if {case.language for case in self.cases} != {"en", "pl"}:
            raise ValueError("specialist corpus must contain English and Polish")
        if {
            case.task_stratum for case in self.cases
        } != set(SpecialistTaskStratum):
            raise ValueError("specialist corpus must cover all calibration strata")
        if {
            case.expected_outcome for case in self.cases
        } != set(SpecialistOutcome):
            raise ValueError("specialist corpus must cover all typed outcomes")

    def smoke_subset(self) -> "SpecialistCorpus":
        """Select one case for every language/outcome cell and all strata."""

        selected: list[SpecialistCase] = []
        stratum_by_outcome = {
            SpecialistOutcome.ENTAILMENT: SpecialistTaskStratum.FEATURE,
            SpecialistOutcome.NEUTRAL: SpecialistTaskStratum.CODE_REVIEW,
            SpecialistOutcome.CONTRADICTION: SpecialistTaskStratum.BUG_FIX,
            SpecialistOutcome.ABSTAIN: SpecialistTaskStratum.RESEARCH_DESIGN,
        }
        for language in ("en", "pl"):
            for outcome in SpecialistOutcome:
                selected.append(
                    next(
                        case
                        for case in self.cases
                        if case.language == language
                        and case.expected_outcome is outcome
                        and case.task_stratum is stratum_by_outcome[outcome]
                    )
                )
        return SpecialistCorpus(
            schema_version=self.schema_version,
            benchmark_id=self.benchmark_id,
            synthetic_only=True,
            source_fixture_sha256=self.source_fixture_sha256,
            cases=tuple(selected),
        )


@dataclass(frozen=True, slots=True)
class SpecialistPrediction:
    state: SpecialistPredictionState
    label: SpecialistLabel | None = None
    probabilities: tuple[tuple[SpecialistLabel, float], ...] = ()
    abstention_reason: SpecialistAbstentionReason | None = None

    def __post_init__(self) -> None:
        probability_map = dict(self.probabilities)
        if len(probability_map) != len(self.probabilities):
            raise ValueError("specialist probability labels must be unique")
        if self.probabilities:
            if tuple(label for label, _ in self.probabilities) != SPECIALIST_LABEL_ORDER:
                raise ValueError("specialist probabilities must use canonical label order")
            if any(
                not math.isfinite(value) or not 0.0 <= value <= 1.0
                for value in probability_map.values()
            ):
                raise ValueError("specialist probabilities must be finite unit values")
            if not math.isclose(
                sum(probability_map.values()),
                1.0,
                rel_tol=0.0,
                abs_tol=1e-5,
            ):
                raise ValueError("specialist probabilities must sum to one")

        if self.state is SpecialistPredictionState.KNOWN:
            if self.label is None or not self.probabilities:
                raise ValueError("known specialist predictions require label probabilities")
            if self.abstention_reason is not None:
                raise ValueError("known specialist predictions cannot carry abstention")
            maximum = max(probability_map.values())
            if not math.isclose(probability_map[self.label], maximum, abs_tol=1e-12):
                raise ValueError("known specialist label must match maximum probability")
        else:
            if self.label is not None or self.abstention_reason is None:
                raise ValueError("abstained specialist predictions require a typed reason")
            if (
                self.probabilities
                and self.abstention_reason is not SpecialistAbstentionReason.LOW_CONFIDENCE
            ):
                raise ValueError("only low-confidence abstention may retain probabilities")

    @property
    def raw_label(self) -> SpecialistLabel | None:
        if not self.probabilities:
            return None
        return max(self.probabilities, key=lambda item: item[1])[0]

    @property
    def confidence(self) -> float | None:
        if not self.probabilities:
            return None
        return max(value for _, value in self.probabilities)
