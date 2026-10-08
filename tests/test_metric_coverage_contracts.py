from __future__ import annotations

from datetime import UTC, datetime
import json

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.metric_coverage import (
    LatestProfileRunCounts,
    MetricCoverageScope,
    MetricCoverageSelection,
    MetricCoverageService,
    MetricCoverageSnapshot,
    MetricResultStateCounts,
    MetricStructuralSupportState,
    StoredMetricCoverage,
)
from prompt_enhancer.application.analysis.metric_readiness import (
    MetricEvidenceCapability,
    ProviderCapabilityReport,
    ProviderMetricCapability,
    ProviderMetricCapabilityReason,
    ProviderMetricCapabilityState,
)
from prompt_enhancer.application.providers import CompatibilityState
from prompt_enhancer.domain import Provider


NOW = datetime(2048, 3, 4, 5, 6, tzinfo=UTC)
PROJECT_ID = "1" * 64


def _capabilities() -> ProviderCapabilityReport:
    declared = {
        MetricEvidenceCapability.REQUEST_TEXT,
        MetricEvidenceCapability.RESPONSE_TEXT,
        MetricEvidenceCapability.PLAN_TEXT,
    }
    return ProviderCapabilityReport(
        provider=Provider.CODEX,
        compatibility_state=CompatibilityState.EXACT,
        provider_version="0.144.5",
        decoder_key="codex.app-server.text-window",
        decoder_version="1",
        checked_at=NOW,
        capabilities=tuple(
            ProviderMetricCapability(
                capability=capability,
                state=(
                    ProviderMetricCapabilityState.SUPPORTED
                    if capability in declared
                    else ProviderMetricCapabilityState.UNSUPPORTED
                ),
                reason_code=(
                    ProviderMetricCapabilityReason.VERIFIED_BY_COMPATIBLE_DECODER
                    if capability in declared
                    else ProviderMetricCapabilityReason.NOT_DECLARED_BY_DECODER
                ),
            )
            for capability in MetricEvidenceCapability
        ),
        structurally_attemptable_metric_count=13,
        structurally_unsupported_metric_count=7,
        structurally_unknown_metric_count=0,
    )


def _stored(
    *,
    latest: int = 0,
    selected: int = 0,
    not_selected: int = 0,
    unknown_scope: int = 0,
    completed_selected: int = 0,
    states: MetricResultStateCounts | None = None,
    absent: int = 0,
    incompatible: int = 0,
    compatible_cohorts: int = 0,
) -> tuple[StoredMetricCoverage, ...]:
    return tuple(
        StoredMetricCoverage(
            metric_key=definition.key,
            metric_version=definition.version,
            latest_completed_run_count=latest,
            selected_run_count=selected,
            not_selected_run_count=not_selected,
            unknown_scope_run_count=unknown_scope,
            completed_selected_run_count=completed_selected,
            contract_compatible_result_states=states or MetricResultStateCounts(
                known=0,
                unknown=0,
                not_applicable=0,
                abstained=0,
                execution_error=0,
            ),
            contract_incompatible_result_count=incompatible,
            expected_result_absent_count=absent,
            compatible_provenance_cohort_count=compatible_cohorts,
            effective_automation_selected_project_count=0,
        )
        for definition in COACHING_METRIC_DEFINITIONS
    )


class _Repository:
    def __init__(self, snapshot: MetricCoverageSnapshot) -> None:
        self.snapshot_value = snapshot
        self.selections: list[MetricCoverageSelection] = []

    def snapshot(self, selection, *, generated_at):
        self.selections.append(selection)
        assert generated_at == NOW
        return self.snapshot_value


class _Capabilities:
    def __init__(self) -> None:
        self.calls = 0

    def provider_capabilities(self, provider):
        self.calls += 1
        assert provider is Provider.CODEX
        return _capabilities()


def _snapshot(
    *,
    scope: MetricCoverageScope = MetricCoverageScope.PROVIDER_CATALOG,
    indexed_sessions: int = 2,
    latest: LatestProfileRunCounts | None = None,
    metrics: tuple[StoredMetricCoverage, ...] | None = None,
) -> MetricCoverageSnapshot:
    resolved_metrics = metrics or _stored()
    return MetricCoverageSnapshot(
        scope=scope,
        provider=Provider.CODEX,
        generated_at=NOW,
        indexed_project_count=1,
        indexed_session_count=indexed_sessions,
        latest_profile_runs=latest
        or LatestProfileRunCounts(completed=0, running=0, failed=0, never_run=2),
        latest_completed_snapshot_count=(
            resolved_metrics[0].latest_completed_run_count
        ),
        effective_automation_grant_count=0,
        effective_automation_project_count=0,
        unrecognized_result_record_count=0,
        metrics=resolved_metrics,
    )


def test_report_separates_structural_support_from_measurement() -> None:
    repository = _Repository(_snapshot())
    capabilities = _Capabilities()
    service = MetricCoverageService(repository, capabilities, clock=lambda: NOW)

    report = service.report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )

    assert len(report.metrics) == 20
    assert sum(
        item.structural_support is MetricStructuralSupportState.ATTEMPTABLE
        for item in report.metrics
    ) == 13
    assert sum(
        item.structural_support is MetricStructuralSupportState.UNSUPPORTED
        for item in report.metrics
    ) == 7
    assert all(
        item.contract_compatible_result_states.known == 0
        for item in report.metrics
    )
    assert report.latest_profile_runs.never_run == 2
    assert report.local_index_snapshot_exact is True
    assert report.provider_history_completeness.value == "unknown"
    assert report.provider_snapshot_authority.value == "unavailable"
    assert report.metric_values_included is False
    assert report.product_source_authority is False
    assert capabilities.calls == 1


def test_result_states_remain_distinct_and_never_zero_fill_absent() -> None:
    states = MetricResultStateCounts(
        known=1,
        unknown=1,
        not_applicable=1,
        abstained=1,
        execution_error=1,
    )
    snapshot = _snapshot(
        indexed_sessions=7,
        latest=LatestProfileRunCounts(
            completed=6,
            running=0,
            failed=0,
            never_run=1,
        ),
        metrics=_stored(
            latest=6,
            selected=6,
            completed_selected=6,
            states=states,
            absent=1,
            compatible_cohorts=1,
        ),
    )
    report = MetricCoverageService(
        _Repository(snapshot), _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )

    first = report.metrics[0]
    assert first.contract_compatible_result_states == states
    assert first.contract_incompatible_result_count == 0
    assert first.expected_result_absent_count == 1
    assert first.completed_selected_run_count == 6
    assert (
        first.contract_compatible_result_states.known
        != first.completed_selected_run_count
    )


def test_project_selector_is_input_only_and_serialization_is_content_free() -> None:
    repository = _Repository(
        _snapshot(scope=MetricCoverageScope.ONE_PROJECT)
    )
    report = MetricCoverageService(
        repository, _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.ONE_PROJECT,
            project_id=PROJECT_ID,
        )
    )

    payload = json.dumps(report.model_dump(mode="json"), sort_keys=True)
    assert PROJECT_ID not in payload
    for forbidden in (
        "session_id",
        "project_id",
        "run_id",
        "grant_id",
        "transcript",
        "path",
        "uri",
    ):
        assert forbidden not in payload.lower()


def test_selection_and_snapshot_invariants_fail_closed() -> None:
    with pytest.raises(ValidationError):
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.ONE_PROJECT,
        )
    with pytest.raises(ValidationError):
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
            project_id=PROJECT_ID,
        )
    with pytest.raises(ValidationError):
        StoredMetricCoverage(
            **_stored()[0].model_dump(
                mode="python", exclude={"selected_run_count"}
            ),
            selected_run_count=1,
        )
    with pytest.raises(ValidationError):
        MetricCoverageSnapshot(
            **_snapshot().model_dump(mode="python", exclude={"metrics"}),
            metrics=tuple(reversed(_stored())),
        )


def test_capability_promotion_and_provenance_mismatch_are_rejected() -> None:
    report = MetricCoverageService(
        _Repository(_snapshot()), _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )
    with pytest.raises(ValidationError):
        type(report).model_validate(
            {
                **report.model_dump(mode="python"),
                "product_source_authority": True,
            }
        )
    impossible = report.model_dump(mode="python")
    impossible_metrics = list(impossible["metrics"])
    impossible_metrics[0] = {
        **impossible_metrics[0],
        "latest_completed_run_count": 0,
        "selected_run_count": 1,
    }
    impossible["metrics"] = tuple(impossible_metrics)
    with pytest.raises(ValidationError):
        type(report).model_validate(impossible)

    wrong_catalog = report.model_dump(mode="python")
    wrong_catalog["capability_report"] = {
        **wrong_catalog["capability_report"],
        "catalog_version": "fabricated-v99",
    }
    with pytest.raises(ValidationError):
        type(report).model_validate(wrong_catalog)

    wrong_scope = _Repository(_snapshot(scope=MetricCoverageScope.ONE_PROJECT))
    with pytest.raises(RuntimeError, match="provenance mismatch"):
        MetricCoverageService(
            wrong_scope, _Capabilities(), clock=lambda: NOW
        ).report(
            MetricCoverageSelection(
                provider=Provider.CODEX,
                scope=MetricCoverageScope.PROVIDER_CATALOG,
            )
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("latest_completed_snapshot_count", 0),
        ("effective_automation_grant_count", 0),
    ),
)
def test_report_rejects_cross_axis_count_promotion(
    field: str,
    value: int,
) -> None:
    measured = _stored(
        latest=1,
        selected=1,
        completed_selected=1,
        absent=1,
    )
    base = _snapshot(
        latest=LatestProfileRunCounts(
            completed=1,
            running=0,
            failed=0,
            never_run=1,
        ),
        metrics=measured,
    )
    report = MetricCoverageService(
        _Repository(
            MetricCoverageSnapshot(
                **base.model_dump(
                    mode="python",
                    exclude={
                        "effective_automation_grant_count",
                        "effective_automation_project_count",
                    },
                ),
                effective_automation_grant_count=1,
                effective_automation_project_count=1,
            )
        ),
        _Capabilities(),
        clock=lambda: NOW,
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )
    payload = report.model_dump(mode="python")
    payload[field] = value
    if field == "latest_completed_snapshot_count":
        payload["metrics"] = tuple(
            {
                **metric,
                "latest_completed_run_count": 0,
                "selected_run_count": 0,
                "completed_selected_run_count": 0,
                "expected_result_absent_count": 0,
            }
            for metric in payload["metrics"]
        )
    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


def test_public_models_reject_selected_and_one_project_count_tampering() -> None:
    selected = _stored(
        latest=1,
        selected=1,
        completed_selected=1,
        absent=1,
    )
    snapshot = _snapshot(
        scope=MetricCoverageScope.ONE_PROJECT,
        indexed_sessions=1,
        latest=LatestProfileRunCounts(
            completed=1,
            running=0,
            failed=0,
            never_run=0,
        ),
        metrics=selected,
    )
    report = MetricCoverageService(
        _Repository(snapshot), _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.ONE_PROJECT,
            project_id=PROJECT_ID,
        )
    )

    selected_mismatch = report.model_dump(mode="python")
    metrics = list(selected_mismatch["metrics"])
    metrics[0] = {
        **metrics[0],
        "completed_selected_run_count": 0,
        "expected_result_absent_count": 0,
    }
    selected_mismatch["metrics"] = tuple(metrics)
    with pytest.raises(ValidationError):
        type(report).model_validate(selected_mismatch)

    wrong_project_count = report.model_dump(mode="python")
    wrong_project_count["indexed_project_count"] = 2
    with pytest.raises(ValidationError):
        type(report).model_validate(wrong_project_count)


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("dimension", "synthetic_dimension"),
        ("display_name", "Synthetic altered metric"),
        (
            "required_evidence",
            ((MetricEvidenceCapability.OBJECTIVE_VERIFICATION,),),
        ),
    ),
)
def test_report_rejects_per_metric_catalog_metadata_tampering(
    field: str,
    value: object,
) -> None:
    report = MetricCoverageService(
        _Repository(_snapshot()), _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )
    payload = report.model_dump(mode="python")
    metrics = list(payload["metrics"])
    metrics[0] = {**metrics[0], field: value}
    payload["metrics"] = tuple(metrics)

    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


def test_report_rejects_per_metric_structural_support_swap() -> None:
    report = MetricCoverageService(
        _Repository(_snapshot()), _Capabilities(), clock=lambda: NOW
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )
    payload = report.model_dump(mode="python")
    metrics = list(payload["metrics"])
    attemptable_index = next(
        index
        for index, metric in enumerate(metrics)
        if metric["structural_support"]
        is MetricStructuralSupportState.ATTEMPTABLE
    )
    unsupported_index = next(
        index
        for index, metric in enumerate(metrics)
        if metric["structural_support"]
        is MetricStructuralSupportState.UNSUPPORTED
    )
    metrics[attemptable_index] = {
        **metrics[attemptable_index],
        "structural_support": MetricStructuralSupportState.UNSUPPORTED,
    }
    metrics[unsupported_index] = {
        **metrics[unsupported_index],
        "structural_support": MetricStructuralSupportState.ATTEMPTABLE,
    }
    payload["metrics"] = tuple(metrics)
    assert sum(
        metric["structural_support"]
        is MetricStructuralSupportState.ATTEMPTABLE
        for metric in metrics
    ) == 13
    assert sum(
        metric["structural_support"]
        is MetricStructuralSupportState.UNSUPPORTED
        for metric in metrics
    ) == 7

    with pytest.raises(ValidationError):
        type(report).model_validate(payload)


def test_report_rejects_completed_snapshots_without_latest_profile_attempts() -> None:
    report = MetricCoverageService(
        _Repository(
            _snapshot(
                latest=LatestProfileRunCounts(
                    completed=0,
                    running=0,
                    failed=1,
                    never_run=1,
                ),
                metrics=_stored(
                    latest=1,
                    selected=1,
                    completed_selected=1,
                    absent=1,
                ),
            )
        ),
        _Capabilities(),
        clock=lambda: NOW,
    ).report(
        MetricCoverageSelection(
            provider=Provider.CODEX,
            scope=MetricCoverageScope.PROVIDER_CATALOG,
        )
    )
    payload = report.model_dump(mode="python")
    payload["latest_profile_runs"] = {
        "completed": 0,
        "running": 0,
        "failed": 0,
        "never_run": 2,
    }
    assert payload["latest_completed_snapshot_count"] == 1

    with pytest.raises(ValidationError):
        type(report).model_validate(payload)
