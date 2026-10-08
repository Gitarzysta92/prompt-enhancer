from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
import socket
from threading import Thread
import time

import httpx
from pydantic import SecretStr
import uvicorn

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis import (
    MetricReadinessService,
    SessionTextAnalysisService,
)
from prompt_enhancer.application.analysis.text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.application.analysis.text_source import (
    TextAnalysisPurpose,
    TextAnalysisSelection,
    TextSourceAccessGrant,
)
from prompt_enhancer.application.automation import (
    AutomationGrantService,
    AutomationJobGuard,
    AutomationSessionCandidate,
    SessionQualityAutomationHandler,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobExecutionResult,
    AnalysisJobKind,
    AnalysisJobService,
    AnalysisJobState,
    AnalysisJobWorker,
    PowerSourceState,
)
from prompt_enhancer.application.local_sources import CodexLocalSourceService
from prompt_enhancer.application.persistence import SESSION_ANALYSIS_RUN_SCHEMA_VERSION
from prompt_enhancer.application.providers import (
    CapabilityObservation,
    CapabilityState,
    CompatibilityState,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityCatalog,
    ProviderCompatibilityReport,
    ProviderCompatibilityService,
    ProviderSurface,
    ProviderSurfaceCompatibilityPolicy,
    TrustedProviderRegistry,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    EventKind,
    Provider,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
)
from prompt_enhancer.infrastructure.automation import (
    LocalAutomationAccessPolicy,
    QueueAutomationJobSink,
)
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.infrastructure.verification import validation_only_capability
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR,
)
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_loopback_e2e_token_1234567890"
PRIVATE_CANARY = "SYNTHETIC-REDACTED-LOOPBACK-CANARY"
BASE_TIME = datetime(2047, 3, 4, 5, 6, tzinfo=UTC)


class MutableClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value

    def advance(self, **values: float) -> None:
        self.value += timedelta(**values)


class SyntheticCodexAdapter(ProviderAdapter):
    """Fictional metadata shaped like the reviewed Codex adapter contract."""

    provider = Provider.CODEX

    def __init__(self) -> None:
        self.list_calls = 0
        self.read_calls = 0
        self.session = SourceSession(
            provider=Provider.CODEX,
            source_installation_id=SecretStr("example-loopback-installation"),
            source_project_id=SecretStr("example-loopback-project"),
            source_session_id=SecretStr("example-loopback-session"),
            provider_version="0.144.5",
            adapter_version="0.3.0",
            source_schema_version="codex-consumed-schema-v1",
            started_at=BASE_TIME,
            ended_at=BASE_TIME + timedelta(minutes=8),
            terminal_state=SessionState.COMPLETED,
            events_complete=True,
        )

    @property
    def required_consent_tier(self) -> DataTier:
        return DataTier.REDACTED_CONTENT

    def probe(self) -> AdapterProbe:
        return AdapterProbe(
            provider=Provider.CODEX,
            provider_version="0.144.5",
            adapter_version="0.3.0",
            source_schema_version="codex-consumed-schema-v1",
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=AdapterHealth.READY,
        )

    def list_sessions(
        self,
        *,
        cursor: str | None = None,
        limit: int = 100,
    ) -> SourceSessionPage:
        self.list_calls += 1
        if cursor is not None:
            return SourceSessionPage(sessions=())
        return SourceSessionPage(sessions=(self.session,))

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        assert session == self.session
        self.read_calls += 1
        yield SourceEvent(
            source_event_id=SecretStr("example-loopback-event-start"),
            kind=EventKind.SESSION_START,
            sequence=0,
            occurred_at=session.started_at,
        )
        yield SourceEvent(
            source_event_id=SecretStr("example-loopback-event-plan"),
            kind=EventKind.PLAN,
            sequence=1,
            occurred_at=session.started_at + timedelta(minutes=1),
        )
        yield SourceEvent(
            source_event_id=SecretStr("example-loopback-event-end"),
            kind=EventKind.SESSION_END,
            sequence=2,
            occurred_at=session.ended_at,
        )

    def health(self) -> AdapterHealth:
        return AdapterHealth.READY


class ExactCompatibilityProbe:
    descriptor = CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR

    def __init__(self, clock: MutableClock) -> None:
        self._clock = clock
        self.calls = 0

    def check(self) -> ProviderCompatibilityReport:
        self.calls += 1
        descriptor = self.descriptor
        return ProviderCompatibilityReport(
            descriptor=descriptor,
            provider_version="0.144.5",
            state=CompatibilityState.EXACT,
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
            checked_at=self._clock(),
        )


class SyntheticCodexTextSource:
    provider = Provider.CODEX
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def __init__(self) -> None:
        self.read_count = 0

    def read(
        self,
        *,
        selection: TextAnalysisSelection,
        grant: TextSourceAccessGrant,
        task_profile,
    ) -> P1TextAnalysisInput:  # type: ignore[no-untyped-def]
        assert selection.provider is Provider.CODEX
        assert grant.session_id == selection.session_id
        assert grant.content_persistence_allowed is False
        self.read_count += 1
        messages = (
            EphemeralRedactedMessage(
                message_id="1" * 64,
                sequence=0,
                role=TextRole.USER,
                kind=TextMessageKind.REQUEST,
                language=TextLanguage.ENGLISH,
                text=SecretStr(
                    PRIVATE_CANARY
                    + " Build an example dashboard so engineers can review results. "
                    "Processing must remain local, and synthetic tests must pass."
                ),
            ),
            EphemeralRedactedMessage(
                message_id="2" * 64,
                sequence=1,
                role=TextRole.AGENT,
                kind=TextMessageKind.PLAN,
                language=TextLanguage.ENGLISH,
                text=SecretStr(
                    "Build the fictional dashboard and run the synthetic checks."
                ),
            ),
            EphemeralRedactedMessage(
                message_id="3" * 64,
                sequence=2,
                role=TextRole.AGENT,
                kind=TextMessageKind.RESPONSE,
                language=TextLanguage.ENGLISH,
                text=SecretStr("The fictional dashboard is ready for review."),
            ),
        )
        return P1TextAnalysisInput(
            provider=Provider.CODEX,
            session_id=selection.session_id,
            provider_version="0.144.5",
            adapter_version="0.3.0",
            source_schema_version="codex-consumed-schema-v1",
            content_schema_version="codex-thread-item-text-v4",
            redactor_version="synthetic-loopback-redactor-v1",
            text_extraction_complete=True,
            available_message_kinds=frozenset(
                {
                    TextMessageKind.REQUEST,
                    TextMessageKind.PLAN,
                    TextMessageKind.RESPONSE,
                }
            ),
            analysis_window_fingerprint="4" * 64,
            focus_message_id="1" * 64,
            observed_message_count=len(messages),
            eligible_message_count=len(messages),
            messages=messages,
            task_profile=task_profile,
        )


class NoopCatalogRefresher:
    def refresh(self, provider: Provider, *, max_sessions: int) -> None:
        assert provider is Provider.CODEX
        assert 1 <= max_sessions <= 100


class MutableAutomationCandidates:
    def __init__(
        self,
        project_id: str,
        session_id: str,
        clock: MutableClock,
    ) -> None:
        self.project_id = project_id
        self.session_id = session_id
        self.clock = clock
        self.input_fingerprint = "5" * 64
        self.provenance_fingerprint = "6" * 64

    def newest_changed(self, scope, *, limit):  # type: ignore[no-untyped-def]
        assert scope.project_id == self.project_id
        assert limit == scope.newest_session_limit
        return (
            AutomationSessionCandidate(
                provider=Provider.CODEX,
                project_id=self.project_id,
                session_id=self.session_id,
                input_fingerprint=self.input_fingerprint,
                provenance_fingerprint=self.provenance_fingerprint,
                provider_schema_version="codex-consumed-schema-v1",
                updated_at=self.clock(),
            ),
        )


class FixedIds:
    def __init__(self) -> None:
        self.calls = 0

    def new_id(self) -> str:
        value = f"{9 + self.calls:x}"
        self.calls += 1
        return value * 64


@contextmanager
def real_loopback_server(app):  # type: ignore[no-untyped-def]
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    port = int(listener.getsockname()[1])
    config = uvicorn.Config(
        app,
        host="127.0.0.1",
        port=port,
        log_level="critical",
        access_log=False,
        lifespan="on",
        ws="none",
    )
    server = uvicorn.Server(config)
    thread = Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started and thread.is_alive() and time.monotonic() < deadline:
        time.sleep(0.01)
    if not server.started:
        server.should_exit = True
        thread.join(timeout=5)
        listener.close()
        raise AssertionError("synthetic loopback server did not start")
    try:
        with httpx.Client(
            base_url=f"http://127.0.0.1:{port}",
            headers={API_TOKEN_HEADER: TOKEN},
            timeout=10,
            trust_env=False,
        ) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(timeout=10)
        listener.close()
        if thread.is_alive():
            raise AssertionError("synthetic loopback server did not stop")


def _wait_for_job(
    client: httpx.Client,
    job_id: str,
    expected: set[str],
) -> dict[str, object]:
    deadline = time.monotonic() + 10
    payload: dict[str, object] = {}
    while time.monotonic() < deadline:
        response = client.get(f"/v1/analysis-jobs/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        if payload["state"] in expected:
            return payload
        time.sleep(0.02)
    raise AssertionError(f"analysis job did not reach {sorted(expected)}: {payload}")


def _assert_canary_not_persisted(root) -> None:  # type: ignore[no-untyped-def]
    needle = PRIVATE_CANARY.encode("utf-8")
    for path in root.rglob("*"):
        if path.is_file():
            assert needle not in path.read_bytes(), path.name


def test_real_loopback_p0_vertical_survives_restart_and_keeps_text_ephemeral(
    tmp_path,
    caplog,
) -> None:
    database = Database(tmp_path / "loopback.sqlite3")
    database.initialize()
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    adapter = SyntheticCodexAdapter()
    source_service = CodexLocalSourceService(
        database,
        IngestionService(database, pseudonymizer),
        lambda _operational_history: adapter,
        validation_only_capability(),
    )
    compatibility_clock = MutableClock(BASE_TIME)
    compatibility_probe = ExactCompatibilityProbe(compatibility_clock)
    descriptor = CODEX_TEXT_WINDOW_DECODER_DESCRIPTOR
    compatibility_catalog = ProviderCompatibilityCatalog(
        ProviderCompatibilityService(
            TrustedProviderRegistry((descriptor,)),
            (compatibility_probe,),
            clock=compatibility_clock,
        ),
        (descriptor,),
    )
    compatibility_policy = ProviderSurfaceCompatibilityPolicy(
        compatibility_catalog,
        surface=ProviderSurface.TEXT_WINDOW,
        required_capabilities=descriptor.capabilities,
    )
    job_clock = MutableClock(datetime.now(UTC))
    text_source = SyntheticCodexTextSource()
    run_repository = database.session_analysis_run_repository()
    text_service = SessionTextAnalysisService(
        database,
        run_repository,
        lambda provider: text_source
        if provider is Provider.CODEX
        else (_ for _ in ()).throw(ValueError("unsupported synthetic provider")),
        compatibility_policy,
        LocalArtifactIdFactory(pseudonymizer),
        schema_version=SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
        clock=job_clock,
    )
    readiness_service = MetricReadinessService(
        database,
        run_repository,
        compatibility_catalog,
    )
    job_repository = database.analysis_job_repository()
    job_service = AnalysisJobService(job_repository, clock=job_clock)

    first_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_text_analysis_service=text_service,
        provider_compatibility_catalog=compatibility_catalog,
        metric_readiness_service=readiness_service,
        codex_source_service=source_service,
        analysis_job_service=job_service,
    )

    with real_loopback_server(first_app) as client:
        denied_index = client.post("/v1/local-sources/codex/index", json={"max_sessions": 1})
        assert denied_index.status_code == 403
        assert adapter.list_calls == 0

        consent = client.post("/v1/local-sources/codex/consents/local-history")
        assert consent.status_code == 200
        assert consent.json()["consent_active"] is True
        indexed = client.post(
            "/v1/local-sources/codex/index",
            json={"max_sessions": 1},
        )
        assert indexed.status_code == 200, indexed.text
        assert indexed.json()["sessions_selected"] == 1
        assert adapter.list_calls == adapter.read_calls == 1

        sessions = client.get("/v1/sessions?provider=codex")
        assert sessions.status_code == 200
        session = sessions.json()["sessions"][0]
        session_id = str(session["session_id"])
        project_id = str(session["project_id"])

        before = client.get("/v1/providers/codex/compatibility")
        assert before.json()["state"] == "untested"
        checked = client.post("/v1/providers/codex/compatibility/check")
        assert checked.status_code == 200
        assert checked.json()["state"] == "exact"
        cached = client.get("/v1/providers/codex/compatibility")
        assert cached.json() == checked.json()
        assert compatibility_probe.calls == 1

        preview = client.post(
            f"/v1/sessions/{session_id}/quality-analysis-previews",
            json={"preset_id": "coaching_profile_v1"},
        )
        assert preview.status_code == 200
        assert preview.headers["cache-control"] == "no-store, private"
        preview_payload = preview.json()
        assert PRIVATE_CANARY in preview_payload["messages"][0]["text"]
        assert text_source.read_count == 1
        _assert_canary_not_persisted(tmp_path)

        approval_path = (
            f"/v1/quality-analysis-previews/{preview_payload['preview_id']}/approval"
        )
        approval_body = {
            "confirmation": "approve_exact_redacted_preview",
            "expected_binding": preview_payload["binding"],
        }
        approved = client.post(
            approval_path,
            json=approval_body,
            headers={"Idempotency-Key": "loopback-preview-run-1"},
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "completed"
        assert approved.json()["result_count"] == 20
        approved_detail = client.get(
            f"/v1/quality-analysis/runs/{approved.json()['run_id']}"
        )
        assert approved_detail.status_code == 200
        assert approved_detail.json()["run"]["metric_scope_state"] == "exact"
        assert len(approved_detail.json()["run"]["selected_metric_keys"]) == 20
        assert text_source.read_count == 1
        consumed = client.post(
            approval_path,
            json=approval_body,
            headers={"Idempotency-Key": "loopback-preview-run-1"},
        )
        assert consumed.status_code == 409
        assert consumed.json()["detail"]["code"] == "redaction_preview_consumed"
        calls_before_cached_readiness = compatibility_probe.calls
        assert calls_before_cached_readiness == 3

        capabilities = client.get("/v1/providers/codex/capabilities")
        assert capabilities.status_code == 200
        capability_payload = capabilities.json()
        assert capability_payload["structurally_attemptable_metric_count"] == 13
        assert capability_payload["structurally_unsupported_metric_count"] == 7
        readiness = client.get(
            f"/v1/sessions/{session_id}/metric-readiness",
            params={"preset_id": "coaching_profile_v1"},
        )
        assert readiness.status_code == 200
        readiness_payload = readiness.json()
        assert len(readiness_payload["metrics"]) == 20
        readiness_states = {item["state"] for item in readiness_payload["metrics"]}
        assert "known" in readiness_states
        assert "abstained" in readiness_states
        assert compatibility_probe.calls == calls_before_cached_readiness

    # Recompose with the actual automation application boundary over the same DB.
    automation_clock = MutableClock(job_clock())
    candidates = MutableAutomationCandidates(project_id, session_id, automation_clock)
    automation_ids = FixedIds()
    external_power = type(
        "ExternalPower",
        (),
        {"current": lambda _self: PowerSourceState.EXTERNAL_POWER},
    )()
    automation_service = AutomationGrantService(
        database.automation_grant_repository(),
        LocalAutomationAccessPolicy(database),
        NoopCatalogRefresher(),
        candidates,
        QueueAutomationJobSink(
            job_service,
            estimator_plan_version="synthetic-loopback-plan-v1",
            redactor_version="synthetic-loopback-redactor-v1",
        ),
        automation_ids,
        external_power,
        clock=automation_clock,
    )
    automation_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        automation_grant_service=automation_service,
    )
    with real_loopback_server(automation_app) as client:
        grant = client.post(
            "/v1/automation-grants",
            json={
                "provider": "codex",
                "project_id": project_id,
                "metric_keys": ["prompt.context_sufficiency"],
                "newest_session_limit": 1,
                "check_interval_seconds": 900,
                "resource_policy": {
                    "route": "balanced",
                    "max_gpu_workers": 1,
                    "max_cpu_workers": 1,
                    "pause_on_battery": True,
                    "maximum_session_seconds": 1800,
                },
            },
        )
        assert grant.status_code == 201, grant.text
        grant_id = str(grant.json()["grant_id"])
        first_poll = client.post("/v1/automation-grants/poll")
        assert first_poll.status_code == 200
        assert first_poll.json()["jobs_created"] == 1
        first_jobs = client.get("/v1/analysis-jobs").json()["jobs"]
        first_automation_job = next(
            item
            for item in first_jobs
            if item["identity"]["automation_grant_id"] == grant_id
        )
        assert first_automation_job["state"] == "queued"
        first_automation_job_id = str(first_automation_job["job_id"])

    guard = AutomationJobGuard(
        database.automation_grant_repository(),
        LocalAutomationAccessPolicy(database),
        candidates,
        clock=automation_clock,
    )
    scoped_worker = AnalysisJobWorker(
        job_repository,
        {
            (AnalysisJobKind.SESSION_QUALITY, Provider.CODEX): (
                SessionQualityAutomationHandler(text_service)
            )
        },
        authorization_check=guard.authorized,
        fingerprint_resolver=guard.fingerprints,
        power_source=external_power,
        clock=job_clock,
        lease_duration=timedelta(seconds=5),
        poll_seconds=0.05,
        worker_id="f" * 64,
    )
    scoped_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        analysis_job_worker=scoped_worker,
    )
    with real_loopback_server(scoped_app) as client:
        completed_scope = _wait_for_job(
            client,
            first_automation_job_id,
            {"completed"},
        )
        assert completed_scope["terminal_reason_code"] == "local_analysis_completed"

    scoped_runs = [
        run
        for run in run_repository.list_for_session(session_id)
        if len(run_repository.get_results(run.draft.run_id)) == 1
    ]
    scoped_results = [
        run_repository.get_results(run.draft.run_id) for run in scoped_runs
    ]
    assert len(scoped_results) == 1
    assert scoped_runs[0].draft.selected_metric_keys == (
        "prompt.context_sufficiency",
    )
    assert tuple(
        result.observation.key for result in scoped_results[0]
    ) == ("prompt.context_sufficiency",)
    assert text_source.read_count == 2
    assert compatibility_probe.calls == calls_before_cached_readiness + 1
    _assert_canary_not_persisted(tmp_path)
    job_clock.advance(seconds=1)

    changed_scope_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        automation_grant_service=automation_service,
    )
    with real_loopback_server(changed_scope_app) as client:
        first_revoked = client.post(
            f"/v1/automation-grants/{grant_id}/revocation"
        )
        assert first_revoked.status_code == 200
        changed_grant = client.post(
            "/v1/automation-grants",
            json={
                "provider": "codex",
                "project_id": project_id,
                "metric_keys": [
                    "collaboration.rework_candidate_rate",
                    "logic.decomposition_coverage",
                    "prompt.context_sufficiency",
                ],
                "newest_session_limit": 1,
                "check_interval_seconds": 900,
                "resource_policy": {
                    "route": "balanced",
                    "max_gpu_workers": 1,
                    "max_cpu_workers": 1,
                    "pause_on_battery": True,
                    "maximum_session_seconds": 1800,
                },
            },
        )
        assert changed_grant.status_code == 201, changed_grant.text
        changed_grant_id = str(changed_grant.json()["grant_id"])
        changed_scope_poll = client.post("/v1/automation-grants/poll")
        assert changed_scope_poll.status_code == 200
        assert changed_scope_poll.json()["jobs_created"] == 1
        changed_scope_jobs = client.get("/v1/analysis-jobs").json()["jobs"]
        selected_job = next(
            item
            for item in changed_scope_jobs
            if item["identity"]["automation_grant_id"] == changed_grant_id
        )
        assert selected_job["identity"]["metric_keys"] == [
            "collaboration.rework_candidate_rate",
            "logic.decomposition_coverage",
            "prompt.context_sufficiency",
        ]
        selected_job_id = str(selected_job["job_id"])

    multi_scope_worker_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        analysis_job_worker=scoped_worker,
    )
    with real_loopback_server(multi_scope_worker_app) as client:
        completed_multi_scope = _wait_for_job(
            client,
            selected_job_id,
            {"completed"},
        )
        assert (
            completed_multi_scope["terminal_reason_code"]
            == "local_analysis_completed"
        )

    expected_scopes = {
        ("prompt.context_sufficiency",),
        (
            "collaboration.rework_candidate_rate",
            "logic.decomposition_coverage",
            "prompt.context_sufficiency",
        ),
    }
    persisted_scopes = {
        tuple(result.observation.key for result in results)
        for run in run_repository.list_for_session(session_id)
        if len(results := run_repository.get_results(run.draft.run_id))
        in {1, 3}
    }
    assert persisted_scopes == expected_scopes
    assert {
        run.draft.selected_metric_keys
        for run in run_repository.list_for_session(session_id)
        if len(run_repository.get_results(run.draft.run_id)) in {1, 3}
    } == expected_scopes

    scope_truth_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        metric_readiness_service=readiness_service,
    )
    with real_loopback_server(scope_truth_app) as client:
        latest_scope = client.get(
            f"/v1/sessions/{session_id}/quality-analysis-runs/latest"
        )
        assert latest_scope.status_code == 200
        assert latest_scope.json()["run"]["metric_scope_state"] == "exact"
        assert tuple(latest_scope.json()["run"]["selected_metric_keys"]) == (
            "collaboration.rework_candidate_rate",
            "logic.decomposition_coverage",
            "prompt.context_sufficiency",
        )
        scoped_readiness = client.get(
            f"/v1/sessions/{session_id}/metric-readiness",
            params={"preset_id": "coaching_profile_v1"},
        )
        assert scoped_readiness.status_code == 200
        readiness_metrics = scoped_readiness.json()["metrics"]
        assert any(
            item["reason_code"] == "metric_not_selected"
            for item in readiness_metrics
        )
        assert all(
            item["reason_code"] != "result_missing"
            for item in readiness_metrics
        )
        aggregate = client.post(
            "/v1/quality-analysis/aggregate",
            json={"session_ids": [session_id]},
        )
        assert aggregate.status_code == 200
        selected_scope = expected_scopes.copy()
        selected_keys = max(selected_scope, key=len)
        aggregate_by_key = {
            item["metric_key"]: item for item in aggregate.json()["metrics"]
        }
        assert all(
            aggregate_by_key[key]["present_result_count"] == 1
            for key in selected_keys
        )
        assert all(
            item["not_selected_run_count"] == 1
            and item["missing_result_count"] == 0
            for key, item in aggregate_by_key.items()
            if key not in selected_keys
        )
    assert text_source.read_count == 3
    assert compatibility_probe.calls == calls_before_cached_readiness + 2
    _assert_canary_not_persisted(tmp_path)
    job_clock.advance(seconds=1)

    supersession_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        automation_grant_service=automation_service,
    )
    with real_loopback_server(supersession_app) as client:
        changed_revoked = client.post(
            f"/v1/automation-grants/{changed_grant_id}/revocation"
        )
        assert changed_revoked.status_code == 200
        drift_grant = client.post(
            "/v1/automation-grants",
            json={
                "provider": "codex",
                "project_id": project_id,
                "metric_keys": ["logic.open_loop_closure"],
                "newest_session_limit": 1,
                "check_interval_seconds": 900,
                "resource_policy": {
                    "route": "balanced",
                    "max_gpu_workers": 1,
                    "max_cpu_workers": 1,
                    "pause_on_battery": True,
                    "maximum_session_seconds": 1800,
                },
            },
        )
        assert drift_grant.status_code == 201, drift_grant.text
        drift_grant_id = str(drift_grant.json()["grant_id"])
        drift_poll = client.post("/v1/automation-grants/poll")
        assert drift_poll.status_code == 200
        assert drift_poll.json()["jobs_created"] == 1

        candidates.input_fingerprint = "7" * 64
        automation_clock.advance(seconds=901)
        second_poll = client.post("/v1/automation-grants/poll")
        assert second_poll.status_code == 200
        assert second_poll.json()["jobs_created"] == 1
        assert second_poll.json()["jobs_superseded"] == 1
        after_change = client.get("/v1/analysis-jobs").json()["jobs"]
        grant_jobs = [
            item
            for item in after_change
            if item["identity"]["automation_grant_id"] == drift_grant_id
        ]
        assert {item["state"] for item in grant_jobs} == {"queued", "superseded"}

        revoked = client.post(
            f"/v1/automation-grants/{drift_grant_id}/revocation"
        )
        assert revoked.status_code == 200
        assert revoked.json()["state"] == "revoked"
        after_revoke = client.get("/v1/analysis-jobs").json()["jobs"]
        grant_states = {
            item["state"]
            for item in after_revoke
            if item["identity"]["automation_grant_id"] == drift_grant_id
        }
        assert grant_states == {"cancelled", "superseded"}

        manual = client.post(
            "/v1/analysis-jobs",
            json={
                "kind": "session_quality",
                "provider": "codex",
                "project_id": project_id,
                "session_id": session_id,
                "input_fingerprint": "a" * 64,
                "provenance_fingerprint": "b" * 64,
                "metric_keys": ["prompt.goal_cue_coverage"],
                "estimator_plan_version": "synthetic-loopback-plan-v1",
                "redactor_version": "synthetic-loopback-redactor-v1",
                "provider_schema_version": "codex-consumed-schema-v1",
                "max_attempts": 3,
            },
        )
        assert manual.status_code == 202
        manual_job_id = str(manual.json()["job"]["job_id"])
        assert manual.json()["job"]["state"] == "queued"

    crashed = job_repository.claim_next(
        owner="c" * 64,
        token="d" * 64,
        now=job_clock(),
        lease_duration=timedelta(seconds=5),
    )
    assert crashed is not None
    assert crashed.job_id == manual_job_id
    assert crashed.state is AnalysisJobState.PREPROCESSING
    job_clock.advance(seconds=6)

    def complete_job(_job, context):  # type: ignore[no-untyped-def]
        context.enter_stage(2, progress_completed=1, progress_total=2)
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.COMPLETED,
            reason_code="synthetic_loopback_completed",
            progress_completed=2,
            progress_total=2,
        )

    restart_worker = AnalysisJobWorker(
        job_repository,
        {(AnalysisJobKind.SESSION_QUALITY, Provider.CODEX): complete_job},
        authorization_check=lambda job: database.has_active_consent(
            job.identity.provider,
            DataTier.REDACTED_CONTENT,
        ),
        fingerprint_resolver=lambda job: (
            job.identity.input_fingerprint,
            job.identity.provenance_fingerprint,
        ),
        clock=job_clock,
        lease_duration=timedelta(seconds=5),
        poll_seconds=0.05,
        worker_id="e" * 64,
    )
    restart_app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        analysis_job_service=job_service,
        analysis_job_worker=restart_worker,
    )
    with real_loopback_server(restart_app) as client:
        recovered = _wait_for_job(client, manual_job_id, {"queued"})
        assert recovered["last_error_code"] == "lease_expired"
        job_clock.advance(seconds=5)
        completed = _wait_for_job(client, manual_job_id, {"completed"})
        assert completed["attempt_count"] == 2
        assert completed["progress_completed"] == 2
        assert completed["progress_total"] == 2

    assert text_source.read_count == 3
    assert compatibility_probe.calls == calls_before_cached_readiness + 2
    assert PRIVATE_CANARY not in caplog.text
    _assert_canary_not_persisted(tmp_path)
