from __future__ import annotations

from dataclasses import replace
import hashlib
import json
from pathlib import Path

from pydantic import ValidationError
import pytest

from prompt_enhancer.application.analysis.scope_router_contracts import (
    EvidenceCoverageState,
    MetricApplicability,
    ScopeCompatibilityState,
    ScopeEvidenceAvailability,
    ScopeEvidenceAvailabilityReceipt,
    ScopeEvidenceKind,
    ScopeExtractionState,
    ScopeEvidenceCoverage,
    ScopeRequirementEvidenceLink,
    ScopeRouterInput,
    ScopeRouterOutput,
    ScopeRouterReason,
)
from prompt_enhancer.infrastructure.scope_router.deterministic import (
    DETERMINISTIC_SCOPE_ROUTER_VERSION,
    DeterministicScopeRouter,
)
from prompt_enhancer.infrastructure.scope_router.evaluator import (
    SCOPE_ROUTER_CORPUS_SHA256,
    SCOPE_ROUTER_EVALUATOR_VERSION,
    SCOPE_ROUTER_GENERATOR_VERSION,
    SCOPE_ROUTER_METRIC_DEFINITION_VERSION,
    ScopeRouterCorpusError,
    corpus_public_summary,
    evaluate_scope_router_corpus,
    load_scope_router_corpus,
)
from scripts.privacy_scan import scan_repository


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "synthetic"
    / "scope_router"
    / "scope_router_metadata_v1.json"
)


def _id(value: str) -> str:
    return hashlib.sha256(f"reserved-synthetic:{value}".encode("ascii")).hexdigest()


def _receipt(
    kind: ScopeEvidenceKind,
    availability: ScopeEvidenceAvailability = ScopeEvidenceAvailability.AVAILABLE,
) -> ScopeEvidenceAvailabilityReceipt:
    return ScopeEvidenceAvailabilityReceipt(
        kind=kind,
        availability=availability,
        evidence_reference_ids=(
            (_id(f"evidence:{kind.value}"),)
            if availability is ScopeEvidenceAvailability.AVAILABLE
            else ()
        ),
    )


def _input(**updates: object) -> ScopeRouterInput:
    target_project = _id("target-project")
    target_session = _id("target-session")
    target_revision = _id("target-revision")
    target_requirement = _id("target-requirement")
    target_requirement_version = _id("target-requirement-version")
    values: dict[str, object] = {
        "metric_applicability": MetricApplicability.APPLICABLE,
        "target_project_id": target_project,
        "target_session_id": target_session,
        "target_revision_id": target_revision,
        "target_revision_ordinal": 2,
        "target_requirement_id": target_requirement,
        "target_requirement_version_id": target_requirement_version,
        "requirement_observed_sequence": 20,
        "comparison_project_id": target_project,
        "comparison_session_id": target_session,
        "comparison_revision_id": target_revision,
        "comparison_revision_ordinal": 2,
        "evidence_observed_sequence": 30,
        "evidence_requirement_links": (
            ScopeRequirementEvidenceLink(
                requirement_id=target_requirement,
                requirement_version_id=target_requirement_version,
            ),
        ),
        "extraction_state": ScopeExtractionState.COMPLETE,
        "required_evidence_kinds": (ScopeEvidenceKind.VERIFICATION,),
        "evidence_receipts": (_receipt(ScopeEvidenceKind.VERIFICATION),),
    }
    values.update(updates)
    return ScopeRouterInput(**values)


def test_frozen_scope_router_corpus_is_large_balanced_and_language_independent() -> None:
    corpus = load_scope_router_corpus(
        FIXTURE,
        expected_sha256=SCOPE_ROUTER_CORPUS_SHA256,
    )
    assert corpus_public_summary(corpus) == {
        "schema_version": 1,
        "benchmark_id": "scope_router_metadata_screen_v1",
        "synthetic_only": True,
        "source_fixture_sha256": SCOPE_ROUTER_CORPUS_SHA256,
        "generator_version": SCOPE_ROUTER_GENERATOR_VERSION,
        "case_count": 120,
        "effective_unique_input_count": 30,
        "template_count": 30,
        "language_mode": "language_independent_objective_metadata",
        "task_stratum_counts": {
            "bug_fix": 30,
            "code_review": 30,
            "feature": 30,
            "research_design": 30,
        },
        "expected_state_counts": {
            "compatible": 24,
            "different_scope": 24,
            "insufficient_evidence": 24,
            "not_applicable": 24,
            "superseded": 24,
        },
        "screen_size_gate": {
            "target_minimum_effective_scenarios": 96,
            "effective_scenario_count": 30,
            "met": False,
        },
    }


def test_canonical_scope_router_fixture_requires_exact_digest(tmp_path: Path) -> None:
    corpus = load_scope_router_corpus(
        FIXTURE,
        expected_sha256=SCOPE_ROUTER_CORPUS_SHA256,
    )
    assert corpus.source_fixture_sha256 == SCOPE_ROUTER_CORPUS_SHA256

    changed = tmp_path / "changed.json"
    changed.write_bytes(FIXTURE.read_bytes() + b"\n")
    with pytest.raises(ScopeRouterCorpusError, match="sha256_mismatch"):
        load_scope_router_corpus(
            changed,
            expected_sha256=SCOPE_ROUTER_CORPUS_SHA256,
        )


def test_scope_router_fixture_rejects_extensions_and_non_synthetic_data(
    tmp_path: Path,
) -> None:
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    payload["private_source"] = "forbidden"
    extended = tmp_path / "extended.json"
    extended.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeRouterCorpusError, match="invalid_fields"):
        load_scope_router_corpus(extended)

    payload.pop("private_source")
    payload["synthetic_only"] = False
    non_synthetic = tmp_path / "non_synthetic.json"
    non_synthetic.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ScopeRouterCorpusError, match="contract_failed"):
        load_scope_router_corpus(non_synthetic)


def test_router_input_has_no_oracle_label_or_authored_text_field() -> None:
    field_names = set(ScopeRouterInput.model_fields)
    assert not any(
        token in field_name
        for field_name in field_names
        for token in ("expected", "label", "outcome", "text", "prompt", "body")
    )
    assert field_names == {
        "contract_version",
        "metric_applicability",
        "target_project_id",
        "target_session_id",
        "target_revision_id",
        "target_revision_ordinal",
        "target_requirement_id",
        "target_requirement_version_id",
        "requirement_observed_sequence",
        "comparison_project_id",
        "comparison_session_id",
        "comparison_revision_id",
        "comparison_revision_ordinal",
        "evidence_observed_sequence",
        "evidence_requirement_links",
        "extraction_state",
        "required_evidence_kinds",
        "evidence_receipts",
        "superseding_revision_id",
        "superseding_revision_ordinal",
    }
    payload = _input().model_dump(mode="python")
    with pytest.raises(ValidationError):
        ScopeRouterInput.model_validate({**payload, "expected_state": "compatible"})


def test_changing_expected_labels_cannot_change_router_predictions() -> None:
    corpus = load_scope_router_corpus(FIXTURE)
    router = DeterministicScopeRouter()
    original = tuple(router.route(case.router_input()) for case in corpus.cases)
    states = tuple(ScopeCompatibilityState)
    mutated = tuple(
        replace(
            case,
            expected_state=states[(states.index(case.expected_state) + 1) % len(states)],
            expected_reason=ScopeRouterReason.APPLICABILITY_UNKNOWN,
        )
        for case in corpus.cases
    )
    changed = tuple(router.route(case.router_input()) for case in mutated)
    assert changed == original
    with pytest.raises(TypeError, match="ScopeRouterInput only"):
        router.route(corpus.cases[0])  # type: ignore[arg-type]


def test_router_precedence_is_closed_and_truthful() -> None:
    router = DeterministicScopeRouter()
    superseding_id = _id("superseding-revision")
    assert router.route(
        _input(
            metric_applicability=MetricApplicability.NOT_APPLICABLE,
            comparison_project_id=_id("other-project"),
            superseding_revision_id=superseding_id,
            superseding_revision_ordinal=3,
        )
    ).state is ScopeCompatibilityState.NOT_APPLICABLE
    superseded = router.route(
        _input(
            metric_applicability=MetricApplicability.UNKNOWN,
            superseding_revision_id=superseding_id,
            superseding_revision_ordinal=3,
        )
    )
    assert (superseded.state, superseded.reason) == (
        ScopeCompatibilityState.SUPERSEDED,
        ScopeRouterReason.TARGET_REVISION_SUPERSEDED,
    )
    assert superseded.evidence_coverage.state is EvidenceCoverageState.NOT_APPLICABLE
    assert superseded.evidence_coverage.ratio is None


@pytest.mark.parametrize(
    ("updates", "reason"),
    [
        ({"comparison_project_id": _id("other-project")}, ScopeRouterReason.PROJECT_MISMATCH),
        ({"comparison_session_id": _id("other-session")}, ScopeRouterReason.SESSION_MISMATCH),
        (
            {
                "comparison_revision_id": _id("future-revision"),
                "comparison_revision_ordinal": 3,
            },
            ScopeRouterReason.FUTURE_REVISION_EVIDENCE,
        ),
        (
            {"comparison_revision_id": _id("parallel-revision")},
            ScopeRouterReason.REVISION_IDENTITY_MISMATCH,
        ),
        (
            {
                "evidence_requirement_links": (
                    ScopeRequirementEvidenceLink(
                        requirement_id=_id("other-requirement"),
                        requirement_version_id=_id("other-requirement-version"),
                    ),
                )
            },
            ScopeRouterReason.REQUIREMENT_MISMATCH,
        ),
        (
            {
                "evidence_requirement_links": (
                    ScopeRequirementEvidenceLink(
                        requirement_id=_id("target-requirement"),
                        requirement_version_id=_id("changed-requirement-version"),
                    ),
                )
            },
            ScopeRouterReason.REQUIREMENT_VERSION_MISMATCH,
        ),
        (
            {"evidence_observed_sequence": 19},
            ScopeRouterReason.EVIDENCE_PRECEDES_REQUIREMENT,
        ),
    ],
)
def test_router_detects_scope_and_temporal_incompatibility(
    updates: dict[str, object],
    reason: ScopeRouterReason,
) -> None:
    output = DeterministicScopeRouter().route(_input(**updates))
    assert output.state is ScopeCompatibilityState.DIFFERENT_SCOPE
    assert output.reason is reason
    assert output.evidence_coverage.state is EvidenceCoverageState.INCOMPATIBLE
    assert output.evidence_coverage.available_kind_count is None
    assert output.evidence_coverage.ratio is None


@pytest.mark.parametrize(
    ("availability", "reason"),
    [
        (
            ScopeEvidenceAvailability.UNKNOWN,
            ScopeRouterReason.EVIDENCE_AVAILABILITY_UNKNOWN,
        ),
        (
            ScopeEvidenceAvailability.UNSUPPORTED,
            ScopeRouterReason.REQUIRED_EVIDENCE_UNSUPPORTED,
        ),
        (
            ScopeEvidenceAvailability.FAILED,
            ScopeRouterReason.EVIDENCE_EXTRACTION_FAILED,
        ),
    ],
)
def test_unknown_unsupported_and_failed_evidence_never_become_zero(
    availability: ScopeEvidenceAvailability,
    reason: ScopeRouterReason,
) -> None:
    output = DeterministicScopeRouter().route(
        _input(evidence_receipts=(_receipt(ScopeEvidenceKind.VERIFICATION, availability),))
    )
    assert output.state is ScopeCompatibilityState.INSUFFICIENT_EVIDENCE
    assert output.reason is reason
    assert output.evidence_coverage.state is EvidenceCoverageState.UNKNOWN
    assert output.evidence_coverage.available_kind_count is None
    assert output.evidence_coverage.ratio is None


def test_known_absence_and_compatible_coverage_are_exact() -> None:
    router = DeterministicScopeRouter()
    absent = router.route(
        _input(
            required_evidence_kinds=(
                ScopeEvidenceKind.ACTION,
                ScopeEvidenceKind.VERIFICATION,
            ),
            evidence_receipts=(
                _receipt(ScopeEvidenceKind.ACTION),
                _receipt(
                    ScopeEvidenceKind.VERIFICATION,
                    ScopeEvidenceAvailability.ABSENT,
                ),
            ),
        )
    )
    assert absent.state is ScopeCompatibilityState.INSUFFICIENT_EVIDENCE
    assert absent.reason is ScopeRouterReason.REQUIRED_EVIDENCE_ABSENT
    assert absent.evidence_coverage.available_kind_count == 1
    assert absent.evidence_coverage.ratio == 0.5

    compatible = router.route(_input())
    assert compatible.state is ScopeCompatibilityState.COMPATIBLE
    assert compatible.reason is ScopeRouterReason.EXACT_SCOPE_EVIDENCE_READY
    assert compatible.evidence_coverage.available_kind_count == 1
    assert compatible.evidence_coverage.ratio == 1.0


def test_prior_revision_evidence_requires_exact_immutable_requirement_version() -> None:
    router = DeterministicScopeRouter()
    exact = router.route(
        _input(
            comparison_revision_id=_id("prior-revision"),
            comparison_revision_ordinal=1,
        )
    )
    assert exact.state is ScopeCompatibilityState.COMPATIBLE

    missing = router.route(
        _input(
            comparison_revision_id=_id("prior-revision"),
            comparison_revision_ordinal=1,
            evidence_requirement_links=(
                ScopeRequirementEvidenceLink(
                    requirement_id=_id("target-requirement"),
                    requirement_version_id=None,
                ),
            ),
        )
    )
    assert (missing.state, missing.reason) == (
        ScopeCompatibilityState.INSUFFICIENT_EVIDENCE,
        ScopeRouterReason.REQUIREMENT_VERSION_LINK_MISSING,
    )

    changed = router.route(
        _input(
            comparison_revision_id=_id("prior-revision"),
            comparison_revision_ordinal=1,
            evidence_requirement_links=(
                ScopeRequirementEvidenceLink(
                    requirement_id=_id("target-requirement"),
                    requirement_version_id=_id("changed-requirement-version"),
                ),
            ),
        )
    )
    assert (changed.state, changed.reason) == (
        ScopeCompatibilityState.DIFFERENT_SCOPE,
        ScopeRouterReason.REQUIREMENT_VERSION_MISMATCH,
    )


def test_coverage_and_output_contracts_reject_impossible_combinations() -> None:
    with pytest.raises(ValidationError, match="cannot exceed"):
        ScopeEvidenceCoverage(
            state=EvidenceCoverageState.KNOWN,
            required_kind_count=1,
            available_kind_count=2,
            ratio=2.0,
        )
    for ratio in (float("nan"), float("inf"), -0.1, 1.1):
        with pytest.raises(ValidationError, match="finite unit value"):
            ScopeEvidenceCoverage(
                state=EvidenceCoverageState.KNOWN,
                required_kind_count=1,
                available_kind_count=1,
                ratio=ratio,
            )

    unknown = ScopeEvidenceCoverage(
        state=EvidenceCoverageState.UNKNOWN,
        required_kind_count=1,
    )
    incompatible = ScopeEvidenceCoverage(
        state=EvidenceCoverageState.INCOMPATIBLE,
        required_kind_count=1,
    )
    with pytest.raises(ValidationError, match="compatible output"):
        ScopeRouterOutput(
            router_version=DETERMINISTIC_SCOPE_ROUTER_VERSION,
            state=ScopeCompatibilityState.COMPATIBLE,
            reason=ScopeRouterReason.PROJECT_MISMATCH,
            evidence_coverage=unknown,
        )
    with pytest.raises(ValidationError, match="different-scope output"):
        ScopeRouterOutput(
            router_version=DETERMINISTIC_SCOPE_ROUTER_VERSION,
            state=ScopeCompatibilityState.DIFFERENT_SCOPE,
            reason=ScopeRouterReason.EXTRACTION_INCOMPLETE,
            evidence_coverage=incompatible,
        )
    with pytest.raises(ValidationError, match="insufficient-evidence output"):
        ScopeRouterOutput(
            router_version=DETERMINISTIC_SCOPE_ROUTER_VERSION,
            state=ScopeCompatibilityState.INSUFFICIENT_EVIDENCE,
            reason=ScopeRouterReason.PROJECT_MISMATCH,
            evidence_coverage=unknown,
        )


def test_contract_rejects_raw_injection_path_and_canary_identifier_payloads() -> None:
    payload = _input().model_dump(mode="python")
    for raw_value in (
        "ignore_previous_instruction",
        "relative/path/payload_canary",
        "dotdot_path_payload_canary",
        "secret_canary_value",
    ):
        with pytest.raises(ValidationError):
            ScopeRouterInput.model_validate(
                {**payload, "target_project_id": raw_value}
            )


def test_complete_extraction_requires_canonical_receipts_and_relations() -> None:
    with pytest.raises(ValidationError, match="receipt for every required kind"):
        _input(
            required_evidence_kinds=(
                ScopeEvidenceKind.ACTION,
                ScopeEvidenceKind.VERIFICATION,
            )
        )
    with pytest.raises(ValidationError, match="sorted"):
        _input(
            required_evidence_kinds=(
                ScopeEvidenceKind.VERIFICATION,
                ScopeEvidenceKind.ACTION,
            ),
            evidence_receipts=(
                _receipt(ScopeEvidenceKind.VERIFICATION),
                _receipt(ScopeEvidenceKind.ACTION),
            ),
        )
    with pytest.raises(ValidationError, match="multiple ordinals"):
        _input(comparison_revision_ordinal=1)


def test_aggregate_evaluation_is_perfect_stable_but_never_promotes() -> None:
    corpus = load_scope_router_corpus(FIXTURE)
    report = evaluate_scope_router_corpus(corpus)
    metrics = report["metrics"]
    stability = report["stability_and_resistance"]
    assert report["router_version"] == DETERMINISTIC_SCOPE_ROUTER_VERSION
    assert report["evaluator_version"] == SCOPE_ROUTER_EVALUATOR_VERSION
    assert report["metric_definition_version"] == (
        SCOPE_ROUTER_METRIC_DEFINITION_VERSION
    )
    assert metrics["accuracy"] == 1.0
    assert metrics["macro_precision"] == 1.0
    assert metrics["macro_recall"] == 1.0
    assert metrics["macro_f1"] == 1.0
    assert metrics["reason_accuracy"] == 1.0
    assert metrics["abstention_precision"] == 1.0
    assert metrics["abstention_recall"] == 1.0
    assert metrics["selective_coverage"] == 0.8
    assert metrics["selective_accuracy"] == 1.0
    assert metrics["selective_risk"] == 0.0
    assert stability == {
        "repeat_stability": 1.0,
        "reverse_order_stability": 1.0,
        "label_blind_stability": 1.0,
        "opaque_identifier_perturbation_stability": 1.0,
        "opaque_identifier_perturbation_count": 360,
        "raw_identifier_payloads_rejected": True,
        "authored_label_fields_rejected": True,
    }
    assert report["activation_allowed"] is False
    assert report["promotion_allowed"] is False
    assert report["screen_size_gate"] == {
        "target_minimum_effective_scenarios": 96,
        "effective_scenario_count": 30,
        "met": False,
    }
    assert "effective_scenario_target_unmet" in report["limitations"]


def test_public_report_is_aggregate_only() -> None:
    corpus = load_scope_router_corpus(FIXTURE)
    report = evaluate_scope_router_corpus(corpus)
    rendered = json.dumps(report, sort_keys=True)
    for case in corpus.cases:
        assert case.case_id not in rendered
        assert case.input_metadata.target_project_id not in rendered
        assert case.input_metadata.target_session_id not in rendered
        assert case.input_metadata.target_revision_id not in rendered
        assert case.input_metadata.target_requirement_id not in rendered
    for forbidden in (
        str(FIXTURE),
        "compatible_exact_verification",
        "target_project_id",
        "target_session_id",
        "target_requirement_version_id",
        "evidence_requirement_links",
        "evidence_reference_ids",
        "input_metadata",
    ):
        assert forbidden not in rendered


def test_scope_router_owned_files_pass_privacy_scan() -> None:
    paths = (
        Path("src/prompt_enhancer/application/analysis/scope_router_contracts.py"),
        Path("src/prompt_enhancer/infrastructure/scope_router/__init__.py"),
        Path("src/prompt_enhancer/infrastructure/scope_router/deterministic.py"),
        Path("src/prompt_enhancer/infrastructure/scope_router/evaluator.py"),
        Path("tests/fixtures/synthetic/scope_router/scope_router_metadata_v1.json"),
        Path("tests/test_scope_router.py"),
        Path("docs/model-manifests/p1-scope-router.md"),
    )
    existing = tuple(path for path in paths if (REPOSITORY_ROOT / path).exists())
    assert scan_repository(REPOSITORY_ROOT, existing) == []
