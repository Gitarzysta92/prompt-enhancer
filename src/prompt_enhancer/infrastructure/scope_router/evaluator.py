"""Frozen synthetic evaluation for the deterministic metadata scope router."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any

from pydantic import ValidationError

from prompt_enhancer.application.analysis.scope_router_contracts import (
    MetricApplicability,
    ScopeCompatibilityState,
    ScopeEvidenceAvailability,
    ScopeEvidenceAvailabilityReceipt,
    ScopeEvidenceKind,
    ScopeExtractionState,
    ScopeRequirementEvidenceLink,
    ScopeRouterInput,
    ScopeRouterOutput,
    ScopeRouterReason,
)
from prompt_enhancer.domain import PSEUDONYM_PATTERN

from .deterministic import DeterministicScopeRouter


SCOPE_ROUTER_CORPUS_SHA256 = (
    "04eae107e476c0e00dcada8f9445daaafeed60e91e03d2a7da873a75ffd6383c"
)
SCOPE_ROUTER_EVALUATOR_VERSION = "scope-router-evaluator-v1"
SCOPE_ROUTER_METRIC_DEFINITION_VERSION = "scope-router-metrics-v1"
SCOPE_ROUTER_GENERATOR_VERSION = "scope-router-corpus-generator-v1"

_CORPUS_FIELDS = frozenset(
    {
        "schema_version",
        "benchmark_id",
        "synthetic_only",
        "expansion_strata",
        "defaults",
        "templates",
    }
)
_INPUT_SPEC_FIELDS = frozenset(
    {
        "metric_applicability",
        "target_revision_ordinal",
        "requirement_observed_sequence",
        "comparison_project_relation",
        "comparison_session_relation",
        "comparison_revision_identity",
        "comparison_revision_offset",
        "evidence_sequence_offset",
        "requirement_link_relation",
        "requirement_version_relation",
        "extraction_state",
        "required_evidence_kinds",
        "evidence_availability",
        "superseding_revision_offset",
    }
)
_TEMPLATE_FIELDS = frozenset(
    {"template_id", "expected_state", "expected_reason", "overrides"}
)
_AVAILABILITY_FIELDS = frozenset({"kind", "availability"})
_SAFE_KEY_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyz0123456789_")


class ScopeRouterCorpusError(ValueError):
    pass


class ScopeRouterTaskStratum(StrEnum):
    BUG_FIX = "bug_fix"
    CODE_REVIEW = "code_review"
    FEATURE = "feature"
    RESEARCH_DESIGN = "research_design"


@dataclass(frozen=True, slots=True)
class ScopeRouterCase:
    """Evaluator-only wrapper; expected values never cross into the router."""

    case_id: str
    task_stratum: ScopeRouterTaskStratum
    expected_state: ScopeCompatibilityState
    expected_reason: ScopeRouterReason
    input_metadata: ScopeRouterInput

    def router_input(self) -> ScopeRouterInput:
        return self.input_metadata


@dataclass(frozen=True, slots=True)
class ScopeRouterCorpus:
    schema_version: int
    benchmark_id: str
    synthetic_only: bool
    source_fixture_sha256: str
    template_count: int
    cases: tuple[ScopeRouterCase, ...]

    def __post_init__(self) -> None:
        if self.schema_version != 1:
            raise ValueError("unsupported scope-router corpus schema")
        if not _safe_key(self.benchmark_id):
            raise ValueError("scope-router benchmark id must be a safe key")
        if self.synthetic_only is not True:
            raise ValueError("scope-router corpus must be synthetic")
        if PSEUDONYM_PATTERN.fullmatch(self.source_fixture_sha256) is None:
            raise ValueError("scope-router fixture digest must be immutable")
        if self.template_count < 25:
            raise ValueError("scope-router corpus is below the foundation size")
        if len(self.cases) != self.template_count * len(ScopeRouterTaskStratum):
            raise ValueError("scope-router reporting rows do not match expansion")
        if len({case.case_id for case in self.cases}) != len(self.cases):
            raise ValueError("scope-router case identifiers must be unique")
        states = Counter(case.expected_state for case in self.cases)
        if set(states) != set(ScopeCompatibilityState):
            raise ValueError("scope-router corpus must cover every output state")
        if len(set(states.values())) != 1:
            raise ValueError("scope-router corpus output states must be balanced")
        if {case.task_stratum for case in self.cases} != set(
            ScopeRouterTaskStratum
        ):
            raise ValueError("scope-router corpus must cover all task strata")


def _safe_key(value: object) -> bool:
    return (
        isinstance(value, str)
        and 3 <= len(value) <= 95
        and value[0].islower()
        and set(value) <= _SAFE_KEY_CHARACTERS
    )


def _opaque_id(*parts: str) -> str:
    source = "reserved-synthetic-scope-router:" + ":".join(parts)
    return hashlib.sha256(source.encode("ascii")).hexdigest()


def _read_fixture(path: Path, expected_sha256: str | None) -> tuple[dict[str, Any], str]:
    try:
        payload = path.read_bytes()
        digest = hashlib.sha256(payload).hexdigest()
        if expected_sha256 is not None and digest != expected_sha256:
            raise ScopeRouterCorpusError("scope_router_corpus_sha256_mismatch")
        raw = json.loads(payload.decode("utf-8"))
    except ScopeRouterCorpusError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError):
        raise ScopeRouterCorpusError("scope_router_corpus_unreadable") from None
    if not isinstance(raw, dict) or set(raw) != _CORPUS_FIELDS:
        raise ScopeRouterCorpusError("scope_router_corpus_invalid_fields")
    return raw, digest


def load_scope_router_corpus(
    path: Path,
    *,
    expected_sha256: str | None = None,
) -> ScopeRouterCorpus:
    """Strictly load and expand the content-free fictional metadata corpus."""

    raw, digest = _read_fixture(path, expected_sha256)
    try:
        if raw["schema_version"] != 1 or raw["synthetic_only"] is not True:
            raise ScopeRouterCorpusError("scope_router_corpus_contract_failed")
        if not _safe_key(raw["benchmark_id"]):
            raise ScopeRouterCorpusError("scope_router_corpus_contract_failed")

        raw_strata = raw["expansion_strata"]
        expected_strata = tuple(item.value for item in ScopeRouterTaskStratum)
        if not isinstance(raw_strata, list) or tuple(raw_strata) != expected_strata:
            raise ScopeRouterCorpusError("scope_router_strata_not_canonical")

        defaults = raw["defaults"]
        if not isinstance(defaults, dict) or set(defaults) != _INPUT_SPEC_FIELDS:
            raise ScopeRouterCorpusError("scope_router_defaults_invalid_fields")

        raw_templates = raw["templates"]
        if not isinstance(raw_templates, list) or len(raw_templates) < 25:
            raise ScopeRouterCorpusError("scope_router_templates_invalid")

        seen_template_ids: set[str] = set()
        cases: list[ScopeRouterCase] = []
        for raw_template in raw_templates:
            if not isinstance(raw_template, dict) or set(raw_template) != _TEMPLATE_FIELDS:
                raise ScopeRouterCorpusError("scope_router_template_invalid_fields")
            template_id = raw_template["template_id"]
            if not _safe_key(template_id) or template_id in seen_template_ids:
                raise ScopeRouterCorpusError("scope_router_template_id_invalid")
            seen_template_ids.add(template_id)
            overrides = raw_template["overrides"]
            if not isinstance(overrides, dict) or not set(overrides).issubset(
                _INPUT_SPEC_FIELDS
            ):
                raise ScopeRouterCorpusError("scope_router_overrides_invalid_fields")
            input_spec = {**defaults, **overrides}
            expected_state = ScopeCompatibilityState(raw_template["expected_state"])
            expected_reason = ScopeRouterReason(raw_template["expected_reason"])
            for raw_stratum in raw_strata:
                stratum = ScopeRouterTaskStratum(raw_stratum)
                case_key = f"{template_id}:{stratum.value}"
                cases.append(
                    ScopeRouterCase(
                        case_id=_opaque_id(case_key, "case"),
                        task_stratum=stratum,
                        expected_state=expected_state,
                        expected_reason=expected_reason,
                        input_metadata=_build_router_input(case_key, input_spec),
                    )
                )

        return ScopeRouterCorpus(
            schema_version=raw["schema_version"],
            benchmark_id=raw["benchmark_id"],
            synthetic_only=True,
            source_fixture_sha256=digest,
            template_count=len(raw_templates),
            cases=tuple(cases),
        )
    except ScopeRouterCorpusError:
        raise
    except (KeyError, TypeError, ValueError, ValidationError):
        raise ScopeRouterCorpusError("scope_router_corpus_contract_failed") from None


def _relation_id(case_key: str, family: str, relation: object) -> str | None:
    if relation == "target":
        return _opaque_id(case_key, f"target_{family}")
    if relation == "distinct":
        return _opaque_id(case_key, f"comparison_{family}")
    if relation == "missing":
        return None
    raise ScopeRouterCorpusError("scope_router_relation_invalid")


def _build_router_input(case_key: str, spec: dict[str, Any]) -> ScopeRouterInput:
    target_project_id = _opaque_id(case_key, "target_project")
    target_session_id = _opaque_id(case_key, "target_session")
    target_revision_id = _opaque_id(case_key, "target_revision")
    target_requirement_id = _opaque_id(case_key, "target_requirement")
    target_requirement_version_id = _opaque_id(
        case_key,
        "target_requirement_version",
    )

    target_ordinal = spec["target_revision_ordinal"]
    requirement_sequence = spec["requirement_observed_sequence"]
    revision_offset = spec["comparison_revision_offset"]
    evidence_offset = spec["evidence_sequence_offset"]
    superseding_offset = spec["superseding_revision_offset"]
    if not isinstance(target_ordinal, int) or isinstance(target_ordinal, bool):
        raise ScopeRouterCorpusError("scope_router_ordinal_invalid")
    if not isinstance(requirement_sequence, int) or isinstance(
        requirement_sequence, bool
    ):
        raise ScopeRouterCorpusError("scope_router_sequence_invalid")

    comparison_project_id = _relation_id(
        case_key,
        "project",
        spec["comparison_project_relation"],
    )
    comparison_session_id = _relation_id(
        case_key,
        "session",
        spec["comparison_session_relation"],
    )

    revision_identity = spec["comparison_revision_identity"]
    if revision_identity == "target":
        comparison_revision_id = target_revision_id
    elif revision_identity == "distinct":
        comparison_revision_id = _opaque_id(case_key, "comparison_revision")
    elif revision_identity == "missing":
        comparison_revision_id = None
    else:
        raise ScopeRouterCorpusError("scope_router_revision_relation_invalid")

    if revision_offset is None:
        comparison_revision_ordinal = None
    elif isinstance(revision_offset, int) and not isinstance(revision_offset, bool):
        comparison_revision_ordinal = target_ordinal + revision_offset
        if comparison_revision_ordinal < 0:
            raise ScopeRouterCorpusError("scope_router_revision_ordinal_invalid")
    else:
        raise ScopeRouterCorpusError("scope_router_revision_offset_invalid")

    if evidence_offset is None:
        evidence_observed_sequence = None
    elif isinstance(evidence_offset, int) and not isinstance(evidence_offset, bool):
        evidence_observed_sequence = requirement_sequence + evidence_offset
        if evidence_observed_sequence < 0:
            raise ScopeRouterCorpusError("scope_router_evidence_sequence_invalid")
    else:
        raise ScopeRouterCorpusError("scope_router_evidence_offset_invalid")

    link_relation = spec["requirement_link_relation"]
    version_relation = spec["requirement_version_relation"]
    if version_relation == "target":
        linked_target_version = target_requirement_version_id
    elif version_relation == "distinct":
        linked_target_version = _opaque_id(
            case_key,
            "different_requirement_version",
        )
    elif version_relation == "missing":
        linked_target_version = None
    else:
        raise ScopeRouterCorpusError("scope_router_requirement_version_invalid")

    if link_relation == "target":
        evidence_requirement_links = (
            ScopeRequirementEvidenceLink(
                requirement_id=target_requirement_id,
                requirement_version_id=linked_target_version,
            ),
        )
    elif link_relation == "target_and_other":
        evidence_requirement_links = tuple(
            sorted(
                (
                    ScopeRequirementEvidenceLink(
                        requirement_id=target_requirement_id,
                        requirement_version_id=linked_target_version,
                    ),
                    ScopeRequirementEvidenceLink(
                        requirement_id=_opaque_id(case_key, "other_requirement"),
                        requirement_version_id=_opaque_id(
                            case_key,
                            "other_requirement_version",
                        ),
                    ),
                ),
                key=lambda link: link.requirement_id,
            )
        )
    elif link_relation == "different":
        evidence_requirement_links = (
            ScopeRequirementEvidenceLink(
                requirement_id=_opaque_id(case_key, "other_requirement"),
                requirement_version_id=_opaque_id(
                    case_key,
                    "other_requirement_version",
                ),
            ),
        )
    elif link_relation == "missing":
        evidence_requirement_links = ()
    else:
        raise ScopeRouterCorpusError("scope_router_requirement_relation_invalid")

    raw_required = spec["required_evidence_kinds"]
    if not isinstance(raw_required, list):
        raise ScopeRouterCorpusError("scope_router_required_evidence_invalid")
    required_kinds = tuple(ScopeEvidenceKind(value) for value in raw_required)

    raw_availabilities = spec["evidence_availability"]
    if not isinstance(raw_availabilities, list):
        raise ScopeRouterCorpusError("scope_router_availability_invalid")
    receipts: list[ScopeEvidenceAvailabilityReceipt] = []
    for raw_receipt in raw_availabilities:
        if not isinstance(raw_receipt, dict) or set(raw_receipt) != _AVAILABILITY_FIELDS:
            raise ScopeRouterCorpusError("scope_router_availability_invalid_fields")
        kind = ScopeEvidenceKind(raw_receipt["kind"])
        availability = ScopeEvidenceAvailability(raw_receipt["availability"])
        references = (
            (_opaque_id(case_key, f"evidence_{kind.value}"),)
            if availability is ScopeEvidenceAvailability.AVAILABLE
            else ()
        )
        receipts.append(
            ScopeEvidenceAvailabilityReceipt(
                kind=kind,
                availability=availability,
                evidence_reference_ids=references,
            )
        )

    if superseding_offset is None:
        superseding_revision_id = None
        superseding_revision_ordinal = None
    elif isinstance(superseding_offset, int) and not isinstance(
        superseding_offset, bool
    ):
        superseding_revision_id = _opaque_id(case_key, "superseding_revision")
        superseding_revision_ordinal = target_ordinal + superseding_offset
    else:
        raise ScopeRouterCorpusError("scope_router_superseding_offset_invalid")

    return ScopeRouterInput(
        metric_applicability=MetricApplicability(spec["metric_applicability"]),
        target_project_id=target_project_id,
        target_session_id=target_session_id,
        target_revision_id=target_revision_id,
        target_revision_ordinal=target_ordinal,
        target_requirement_id=target_requirement_id,
        target_requirement_version_id=target_requirement_version_id,
        requirement_observed_sequence=requirement_sequence,
        comparison_project_id=comparison_project_id,
        comparison_session_id=comparison_session_id,
        comparison_revision_id=comparison_revision_id,
        comparison_revision_ordinal=comparison_revision_ordinal,
        evidence_observed_sequence=evidence_observed_sequence,
        evidence_requirement_links=evidence_requirement_links,
        extraction_state=ScopeExtractionState(spec["extraction_state"]),
        required_evidence_kinds=required_kinds,
        evidence_receipts=tuple(receipts),
        superseding_revision_id=superseding_revision_id,
        superseding_revision_ordinal=superseding_revision_ordinal,
    )


def corpus_public_summary(corpus: ScopeRouterCorpus) -> dict[str, object]:
    return {
        "schema_version": corpus.schema_version,
        "benchmark_id": corpus.benchmark_id,
        "synthetic_only": True,
        "source_fixture_sha256": corpus.source_fixture_sha256,
        "generator_version": SCOPE_ROUTER_GENERATOR_VERSION,
        "case_count": len(corpus.cases),
        "effective_unique_input_count": corpus.template_count,
        "template_count": corpus.template_count,
        "language_mode": "language_independent_objective_metadata",
        "task_stratum_counts": dict(
            sorted(Counter(case.task_stratum.value for case in corpus.cases).items())
        ),
        "expected_state_counts": dict(
            sorted(Counter(case.expected_state.value for case in corpus.cases).items())
        ),
        "screen_size_gate": {
            "target_minimum_effective_scenarios": 96,
            "effective_scenario_count": corpus.template_count,
            "met": False,
        },
    }


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _metric_rows(
    corpus: ScopeRouterCorpus,
    predictions: tuple[ScopeRouterOutput, ...],
) -> dict[str, object]:
    states = tuple(ScopeCompatibilityState)
    expected = tuple(case.expected_state for case in corpus.cases)
    predicted = tuple(output.state for output in predictions)
    confusion = {
        expected_state.value: {
            predicted_state.value: sum(
                truth is expected_state and guess is predicted_state
                for truth, guess in zip(expected, predicted, strict=True)
            )
            for predicted_state in states
        }
        for expected_state in states
    }

    per_class: dict[str, dict[str, float | int | None]] = {}
    precision_values: list[float] = []
    recall_values: list[float] = []
    f1_values: list[float] = []
    for state in states:
        true_positive = sum(
            truth is state and guess is state
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_positive = sum(
            truth is not state and guess is state
            for truth, guess in zip(expected, predicted, strict=True)
        )
        false_negative = sum(
            truth is state and guess is not state
            for truth, guess in zip(expected, predicted, strict=True)
        )
        support = true_positive + false_negative
        predicted_count = true_positive + false_positive
        precision = _ratio(true_positive, predicted_count)
        recall = _ratio(true_positive, support)
        f1 = (
            round(
                2 * true_positive
                / (2 * true_positive + false_positive + false_negative),
                6,
            )
            if true_positive
            else 0.0
        )
        precision_values.append(precision or 0.0)
        recall_values.append(recall or 0.0)
        f1_values.append(f1)
        per_class[state.value] = {
            "support": support,
            "predicted_count": predicted_count,
            "precision": precision,
            "recall": recall,
            "f1": f1,
        }

    correct = sum(
        truth is guess for truth, guess in zip(expected, predicted, strict=True)
    )
    insufficient = ScopeCompatibilityState.INSUFFICIENT_EVIDENCE
    predicted_abstentions = sum(guess is insufficient for guess in predicted)
    expected_abstentions = sum(truth is insufficient for truth in expected)
    correct_abstentions = sum(
        truth is insufficient and guess is insufficient
        for truth, guess in zip(expected, predicted, strict=True)
    )
    selected = tuple(
        (truth, guess)
        for truth, guess in zip(expected, predicted, strict=True)
        if guess is not insufficient
    )
    selected_correct = sum(truth is guess for truth, guess in selected)
    reason_correct = sum(
        case.expected_reason is output.reason
        for case, output in zip(corpus.cases, predictions, strict=True)
    )
    return {
        "accuracy": _ratio(correct, len(corpus.cases)),
        "macro_precision": round(sum(precision_values) / len(states), 6),
        "macro_recall": round(sum(recall_values) / len(states), 6),
        "macro_f1": round(sum(f1_values) / len(states), 6),
        "reason_accuracy": _ratio(reason_correct, len(corpus.cases)),
        "confusion_matrix": confusion,
        "per_class": per_class,
        "abstention_state": insufficient.value,
        "abstention_rate": _ratio(predicted_abstentions, len(corpus.cases)),
        "abstention_precision": _ratio(correct_abstentions, predicted_abstentions),
        "abstention_recall": _ratio(correct_abstentions, expected_abstentions),
        "selective_coverage": _ratio(len(selected), len(corpus.cases)),
        "selective_accuracy": _ratio(selected_correct, len(selected)),
        "selective_risk": (
            round(1.0 - selected_correct / len(selected), 6)
            if selected
            else None
        ),
        "predicted_state_counts": dict(sorted(Counter(item.value for item in predicted).items())),
    }


def _prediction_signature(output: ScopeRouterOutput) -> tuple[object, ...]:
    coverage = output.evidence_coverage
    return (
        output.state,
        output.reason,
        coverage.state,
        coverage.required_kind_count,
        coverage.available_kind_count,
        coverage.ratio,
    )


def _remap_opaque_identifiers(item: ScopeRouterInput, salt: str) -> ScopeRouterInput:
    def remap(value: object) -> object:
        if isinstance(value, str) and PSEUDONYM_PATTERN.fullmatch(value):
            return hashlib.sha256(f"{salt}:{value}".encode("ascii")).hexdigest()
        if isinstance(value, tuple):
            remapped = tuple(remap(member) for member in value)
            if remapped and all(
                isinstance(member, str)
                and PSEUDONYM_PATTERN.fullmatch(member) is not None
                for member in remapped
            ):
                return tuple(sorted(remapped))
            return remapped
        if isinstance(value, list):
            remapped = [remap(member) for member in value]
            if remapped and all(
                isinstance(member, str)
                and PSEUDONYM_PATTERN.fullmatch(member) is not None
                for member in remapped
            ):
                return sorted(remapped)
            return remapped
        if isinstance(value, dict):
            return {key: remap(member) for key, member in value.items()}
        return value

    remapped_payload = remap(item.model_dump(mode="python"))
    assert isinstance(remapped_payload, dict)
    links = remapped_payload["evidence_requirement_links"]
    assert isinstance(links, tuple)
    remapped_payload["evidence_requirement_links"] = tuple(
        sorted(links, key=lambda link: link["requirement_id"])
    )
    return ScopeRouterInput.model_validate(remapped_payload)


def _stability_metrics(
    corpus: ScopeRouterCorpus,
    router: DeterministicScopeRouter,
    predictions: tuple[ScopeRouterOutput, ...],
) -> dict[str, object]:
    signatures = tuple(_prediction_signature(output) for output in predictions)
    repeated = tuple(
        _prediction_signature(router.route(case.router_input()))
        for case in corpus.cases
    )
    reversed_outputs = tuple(
        _prediction_signature(router.route(case.router_input()))
        for case in reversed(corpus.cases)
    )[::-1]

    rotated_states = tuple(ScopeCompatibilityState)
    label_mutated_cases = tuple(
        replace(
            case,
            expected_state=rotated_states[
                (rotated_states.index(case.expected_state) + 1) % len(rotated_states)
            ],
            expected_reason=ScopeRouterReason.APPLICABILITY_UNKNOWN,
        )
        for case in corpus.cases
    )
    label_blind_outputs = tuple(
        _prediction_signature(router.route(case.router_input()))
        for case in label_mutated_cases
    )

    perturbation_salts = (
        "instruction_canary",
        "path_canary",
        "secret_canary",
    )
    perturbation_matches = 0
    perturbation_count = 0
    for salt in perturbation_salts:
        for index, case in enumerate(corpus.cases):
            perturbed = _remap_opaque_identifiers(case.router_input(), f"{salt}:{index}")
            perturbed_signature = _prediction_signature(router.route(perturbed))
            perturbation_count += 1
            perturbation_matches += perturbed_signature == signatures[index]

    sample_payload = corpus.cases[0].router_input().model_dump(mode="python")
    raw_identifier_rejected = False
    extra_label_field_rejected = False
    try:
        ScopeRouterInput.model_validate(
            {**sample_payload, "target_project_id": "raw_identifier_canary"}
        )
    except ValidationError:
        raw_identifier_rejected = True
    try:
        ScopeRouterInput.model_validate(
            {**sample_payload, "expected_state": "compatible"}
        )
    except ValidationError:
        extra_label_field_rejected = True

    return {
        "repeat_stability": _ratio(
            sum(left == right for left, right in zip(signatures, repeated, strict=True)),
            len(signatures),
        ),
        "reverse_order_stability": _ratio(
            sum(
                left == right
                for left, right in zip(signatures, reversed_outputs, strict=True)
            ),
            len(signatures),
        ),
        "label_blind_stability": _ratio(
            sum(
                left == right
                for left, right in zip(signatures, label_blind_outputs, strict=True)
            ),
            len(signatures),
        ),
        "opaque_identifier_perturbation_stability": _ratio(
            perturbation_matches,
            perturbation_count,
        ),
        "opaque_identifier_perturbation_count": perturbation_count,
        "raw_identifier_payloads_rejected": raw_identifier_rejected,
        "authored_label_fields_rejected": extra_label_field_rejected,
    }


def evaluate_scope_router_corpus(
    corpus: ScopeRouterCorpus,
    router: DeterministicScopeRouter | None = None,
) -> dict[str, object]:
    """Return aggregate metrics only; never return cases, IDs, or fixture paths."""

    active_router = router or DeterministicScopeRouter()
    predictions = tuple(
        active_router.route(case.router_input()) for case in corpus.cases
    )
    return {
        **corpus_public_summary(corpus),
        "router_version": active_router.version,
        "evaluator_version": SCOPE_ROUTER_EVALUATOR_VERSION,
        "metric_definition_version": SCOPE_ROUTER_METRIC_DEFINITION_VERSION,
        "metrics": _metric_rows(corpus, predictions),
        "stability_and_resistance": _stability_metrics(
            corpus,
            active_router,
            predictions,
        ),
        "activation_allowed": False,
        "promotion_allowed": False,
        "limitations": (
            "synthetic_metadata_foundation_only",
            "effective_scenario_target_unmet",
            "no_private_holdout",
            "no_human_calibration",
            "no_model_quality_claim",
        ),
    }


__all__ = [
    "SCOPE_ROUTER_CORPUS_SHA256",
    "SCOPE_ROUTER_EVALUATOR_VERSION",
    "SCOPE_ROUTER_GENERATOR_VERSION",
    "SCOPE_ROUTER_METRIC_DEFINITION_VERSION",
    "ScopeRouterCase",
    "ScopeRouterCorpus",
    "ScopeRouterCorpusError",
    "ScopeRouterTaskStratum",
    "corpus_public_summary",
    "evaluate_scope_router_corpus",
    "load_scope_router_corpus",
]
