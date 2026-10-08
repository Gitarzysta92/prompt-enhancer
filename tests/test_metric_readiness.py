from __future__ import annotations

from datetime import UTC, datetime
import json
from types import SimpleNamespace

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
    COACHING_METRIC_DEFINITIONS,
    DEFAULT_COACHING_METRIC_ENGINE,
)
from prompt_enhancer.application.analysis.metric_readiness import (
    COACHING_METRIC_REQUIREMENTS,
    METRIC_READINESS_CATALOG_VERSION,
    MetricRadarPolicy,
    MetricReadinessService,
    MetricReadinessState,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    TextAnalysisPresetId,
)
from prompt_enhancer.application.persistence import (
    AnalysisRunStatus,
    MetricValueState,
    SessionMetricScopeState,
)
from prompt_enhancer.application.providers import (
    CapabilityObservation,
    CapabilityState,
    CompatibilityReason,
    CompatibilityReasonCode,
    CompatibilityState,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderSurface,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider, SafeSession, SessionState
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR,
)


NOW = datetime(2044, 5, 6, 7, 8, tzinfo=UTC)
SESSION_ID = "1" * 64


def _session() -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id="2" * 64,
        project_id="3" * 64,
        session_id=SESSION_ID,
        provider_version="0.144.5",
        adapter_version="0.3.0",
        source_schema_version="codex-consumed-schema-v1",
        started_at=NOW,
        terminal_state=SessionState.COMPLETED,
        events_complete=True,
    )


def _compatibility_report(
    state: CompatibilityState = CompatibilityState.EXACT,
) -> ProviderCompatibilityReport:
    descriptor = CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR
    if state is CompatibilityState.EXACT:
        return ProviderCompatibilityReport(
            descriptor=descriptor,
            provider_version="0.144.5",
            state=state,
            capabilities=tuple(
                CapabilityObservation(key=key, state=CapabilityState.SUPPORTED)
                for key in descriptor.capabilities
            ),
            extraction=ExtractionCompleteness(
                state=ExtractionCompletenessState.COMPLETE,
                observed_units=len(descriptor.capabilities),
                eligible_units=len(descriptor.capabilities),
                coverage=1,
            ),
            checked_at=NOW,
        )
    return ProviderCompatibilityReport(
        descriptor=descriptor,
        provider_version="0.145.0",
        state=CompatibilityState.DEGRADED,
        capabilities=tuple(
            CapabilityObservation(key=key, state=CapabilityState.SUPPORTED)
            for key in descriptor.capabilities
        ),
        extraction=ExtractionCompleteness(
            state=ExtractionCompletenessState.UNKNOWN,
            observed_units=0,
        ),
        reasons=(
            CompatibilityReason(
                code=CompatibilityReasonCode.UNKNOWN_UNION_VARIANT
            ),
        ),
        checked_at=NOW,
    )


class _Store:
    def get_session(self, session_id: str) -> SafeSession | None:
        return _session() if session_id == SESSION_ID else None


class _Runs:
    def __init__(self) -> None:
        self.latest = None
        self.results = ()
        self.result_reads = 0

    def get_latest_for_profile(self, session_id: str, **selection):
        assert session_id == SESSION_ID
        assert selection == {
            "analysis_profile_key": "coaching_profile",
            "analysis_profile_version": 1,
            "metric_pack_key": "experimental.redacted-text.coaching",
            "metric_pack_version": 3,
        }
        return self.latest

    def get_results(self, run_id: str):
        self.result_reads += 1
        assert run_id == "4" * 64
        return self.results


class _Catalog:
    def __init__(self, report: ProviderCompatibilityReport | None) -> None:
        self.report = report
        self.refresh_calls = 0

    def descriptor(self, provider: str, surface: ProviderSurface):
        assert provider == "codex"
        assert surface is ProviderSurface.TEXT_WINDOW
        return CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR

    def get_cached(self, provider: str, surface: ProviderSurface):
        assert provider == "codex"
        assert surface is ProviderSurface.TEXT_WINDOW
        return self.report

    def refresh(self, provider: str, surface: ProviderSurface):
        self.refresh_calls += 1
        raise AssertionError("readiness queries must not refresh providers")


class _MissingAdapterCatalog:
    def descriptor(self, provider: str, surface: ProviderSurface):
        del provider, surface
        raise LookupError("synthetic adapter is not registered")

    def get_cached(self, provider: str, surface: ProviderSurface):
        del provider, surface
        raise AssertionError("missing adapters cannot have cached reports")


def _service(
    *,
    report: ProviderCompatibilityReport | None = None,
    runs: _Runs | None = None,
) -> tuple[MetricReadinessService, _Catalog, _Runs]:
    catalog = _Catalog(
        _compatibility_report() if report is None else report
    )
    resolved_runs = runs or _Runs()
    return (
        MetricReadinessService(_Store(), resolved_runs, catalog),
        catalog,
        resolved_runs,
    )


def test_catalog_covers_all_metrics_and_codex_is_exactly_13_of_20() -> None:
    service, catalog, _runs = _service()

    capability_report = service.provider_capabilities(Provider.CODEX)

    expected = {
        (definition.key, definition.version)
        for definition in COACHING_METRIC_DEFINITIONS
    }
    actual = {
        (requirement.metric_key, requirement.metric_version)
        for requirement in COACHING_METRIC_REQUIREMENTS
    }
    assert actual == expected
    assert len(actual) == 20
    assert capability_report.structurally_attemptable_metric_count == 13
    assert capability_report.structurally_unsupported_metric_count == 7
    assert capability_report.structurally_unknown_metric_count == 0
    assert capability_report.catalog_version == METRIC_READINESS_CATALOG_VERSION
    assert catalog.refresh_calls == 0


def test_exact_session_readiness_never_zero_fills_and_owns_radar_policy() -> None:
    service, catalog, _runs = _service()

    report = service.session_readiness(SESSION_ID)

    states = [item.state for item in report.metrics]
    assert states.count(MetricReadinessState.UNKNOWN) == 13
    assert states.count(MetricReadinessState.UNSUPPORTED) == 7
    assert all(item.evidence_tier.value == "redacted_content" for item in report.metrics)
    assert all(item.available_capabilities for item in report.metrics[:6])
    rework = next(
        item
        for item in report.metrics
        if item.metric_key == "collaboration.rework_candidate_rate"
    )
    assert rework.radar_policy is (
        MetricRadarPolicy.EXACT_VALUE_ONLY_UNNORMALIZED_LOWER_IS_BETTER
    )
    assert all(
        item.radar_policy is MetricRadarPolicy.DIRECT_BOUNDED_RATIO
        for item in report.metrics
        if item is not rework
    )
    payload = report.model_dump(mode="json")
    assert "numeric_value" not in json.dumps(payload)
    assert "fraction_numerator" not in json.dumps(payload)
    assert catalog.refresh_calls == 0


def test_persisted_closed_states_remain_distinct() -> None:
    runs = _Runs()
    runs.latest = SimpleNamespace(
        status=AnalysisRunStatus.COMPLETED,
        draft=SimpleNamespace(
            run_id="4" * 64,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=tuple(
                sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
            ),
        ),
    )
    stored_states = (
        MetricValueState.KNOWN,
        MetricValueState.UNKNOWN,
        MetricValueState.ABSTAINED,
        MetricValueState.NOT_APPLICABLE,
        MetricValueState.EXECUTION_ERROR,
    )
    runs.results = tuple(
        SimpleNamespace(
            observation=SimpleNamespace(
                key=definition.key,
                version=definition.version,
            ),
            value_state=value_state,
        )
        for definition, value_state in zip(
            COACHING_METRIC_DEFINITIONS[: len(stored_states)],
            stored_states,
            strict=True,
        )
    )
    service, _catalog, _runs = _service(runs=runs)

    report = service.session_readiness(SESSION_ID)

    assert tuple(item.state for item in report.metrics[:5]) == (
        MetricReadinessState.KNOWN,
        MetricReadinessState.UNKNOWN,
        MetricReadinessState.ABSTAINED,
        MetricReadinessState.NOT_APPLICABLE,
        MetricReadinessState.FAILED,
    )
    assert runs.result_reads == 1


def test_subset_scope_marks_only_supported_omissions_not_selected() -> None:
    selected = next(
        definition
        for definition in COACHING_METRIC_DEFINITIONS
        if definition.key == "prompt.context_sufficiency"
    )
    runs = _Runs()
    runs.latest = SimpleNamespace(
        status=AnalysisRunStatus.COMPLETED,
        draft=SimpleNamespace(
            run_id="4" * 64,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=(selected.key,),
        ),
    )
    runs.results = (
        SimpleNamespace(
            observation=SimpleNamespace(
                key=selected.key,
                version=selected.version,
            ),
            value_state=MetricValueState.KNOWN,
        ),
    )
    service, _catalog, _runs = _service(runs=runs)

    report = service.session_readiness(SESSION_ID)
    by_key = {item.metric_key: item for item in report.metrics}
    assert by_key[selected.key].state is MetricReadinessState.KNOWN
    not_selected = tuple(
        item
        for item in report.metrics
        if item.reason_code.value == "metric_not_selected"
    )
    unsupported = tuple(
        item
        for item in report.metrics
        if item.reason_code.value == "provider_capability_missing"
    )
    assert len(not_selected) == 12
    assert len(unsupported) == 7
    assert all(item.state is MetricReadinessState.UNKNOWN for item in not_selected)
    assert all(
        item.next_actions[0].value == "select_metric_for_analysis"
        for item in not_selected
    )
    assert all(item.state is MetricReadinessState.UNSUPPORTED for item in unsupported)
    assert runs.result_reads == 1


def test_unknown_legacy_scope_never_guesses_an_omission_is_failure() -> None:
    runs = _Runs()
    runs.latest = SimpleNamespace(
        status=AnalysisRunStatus.COMPLETED,
        draft=SimpleNamespace(
            run_id="4" * 64,
            metric_scope_state=SessionMetricScopeState.LEGACY_UNKNOWN,
            selected_metric_keys=(),
        ),
    )
    service, _catalog, _runs = _service(runs=runs)

    report = service.session_readiness(SESSION_ID)

    compatible = tuple(
        item
        for item in report.metrics
        if item.reason_code.value == "metric_scope_unknown"
    )
    assert len(compatible) == 13
    assert all(item.state is MetricReadinessState.UNKNOWN for item in compatible)
    assert all(item.reason_code.value != "result_missing" for item in report.metrics)


def test_explicit_result_precedes_capability_and_failed_run_preserves_it() -> None:
    rework = next(
        definition
        for definition in COACHING_METRIC_DEFINITIONS
        if definition.key == "collaboration.rework_candidate_rate"
    )
    completed = _Runs()
    completed.latest = SimpleNamespace(
        status=AnalysisRunStatus.COMPLETED,
        draft=SimpleNamespace(
            run_id="4" * 64,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=tuple(
                sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
            ),
        ),
    )
    completed.results = (
        SimpleNamespace(
            observation=SimpleNamespace(
                key=rework.key,
                version=rework.version,
            ),
            value_state=MetricValueState.NOT_APPLICABLE,
        ),
    )
    completed_service, _catalog, _runs = _service(runs=completed)

    completed_report = completed_service.session_readiness(SESSION_ID)
    completed_rework = next(
        item for item in completed_report.metrics if item.metric_key == rework.key
    )
    assert completed_rework.state is MetricReadinessState.NOT_APPLICABLE

    failed = _Runs()
    failed.latest = SimpleNamespace(
        status=AnalysisRunStatus.FAILED,
        draft=SimpleNamespace(
            run_id="4" * 64,
            metric_scope_state=SessionMetricScopeState.EXACT,
            selected_metric_keys=tuple(
                sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS)
            ),
        ),
    )
    failed_service, _catalog, _runs = _service(runs=failed)

    failed_report = failed_service.session_readiness(SESSION_ID)
    assert sum(
        item.state is MetricReadinessState.FAILED
        for item in failed_report.metrics
    ) == 13
    assert sum(
        item.state is MetricReadinessState.UNSUPPORTED
        for item in failed_report.metrics
    ) == 7
    assert failed.result_reads == 0


def test_unchecked_is_unknown_and_degraded_is_incompatible() -> None:
    unchecked_catalog = _Catalog(None)
    unchecked = MetricReadinessService(_Store(), _Runs(), unchecked_catalog)
    unchecked_report = unchecked.session_readiness(SESSION_ID)
    assert {item.state for item in unchecked_report.metrics} == {
        MetricReadinessState.UNKNOWN
    }

    degraded, catalog, runs = _service(
        report=_compatibility_report(CompatibilityState.DEGRADED)
    )
    degraded_report = degraded.session_readiness(SESSION_ID)
    assert {item.state for item in degraded_report.metrics} == {
        MetricReadinessState.INCOMPATIBLE
    }
    assert runs.result_reads == 0
    assert catalog.refresh_calls == 0


def test_missing_provider_adapter_is_unsupported_without_guessing() -> None:
    service = MetricReadinessService(_Store(), _Runs(), _MissingAdapterCatalog())

    capability_report = service.provider_capabilities(Provider.CODEX)
    readiness = service.session_readiness(SESSION_ID)

    assert capability_report.structurally_attemptable_metric_count == 0
    assert capability_report.structurally_unsupported_metric_count == 0
    assert capability_report.structurally_unknown_metric_count == 20
    assert {item.state for item in readiness.metrics} == {
        MetricReadinessState.UNSUPPORTED
    }
    assert {
        item.reason_code.value for item in readiness.metrics
    } == {"provider_adapter_unavailable"}


def test_catalog_version_is_part_of_coaching_model_plan_identity() -> None:
    identity = DEFAULT_COACHING_METRIC_ENGINE.model_plan_identity
    marker = identity.index("evidence-capability-catalog")
    assert identity[marker + 1] == COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION


def test_authenticated_http_routes_are_content_free_and_do_not_refresh(
    tmp_path,
) -> None:
    service, catalog, _runs = _service()
    database = Database(tmp_path / "metrics.sqlite3")
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token="example_metric_readiness_token_12345",
        metric_readiness_service=service,
    )
    client = TestClient(app, base_url="http://127.0.0.1")
    headers = {API_TOKEN_HEADER: "example_metric_readiness_token_12345"}

    with client:
        unauthorized = client.get("/v1/providers/codex/capabilities")
        capabilities = client.get(
            "/v1/providers/codex/capabilities", headers=headers
        )
        readiness = client.get(
            f"/v1/sessions/{SESSION_ID}/metric-readiness", headers=headers
        )
        unsupported_preset = client.get(
            f"/v1/sessions/{SESSION_ID}/metric-readiness",
            params={"preset_id": TextAnalysisPresetId.STANDARD_ENGINEERING_V1},
            headers=headers,
        )
        missing = client.get(
            f"/v1/sessions/{'f' * 64}/metric-readiness", headers=headers
        )

    assert unauthorized.status_code == 401
    assert capabilities.status_code == 200
    assert capabilities.json()["structurally_attemptable_metric_count"] == 13
    assert capabilities.json()["structurally_unsupported_metric_count"] == 7
    assert readiness.status_code == 200
    assert len(readiness.json()["metrics"]) == 20
    assert unsupported_preset.status_code == 409
    assert missing.status_code == 404
    assert catalog.refresh_calls == 0
