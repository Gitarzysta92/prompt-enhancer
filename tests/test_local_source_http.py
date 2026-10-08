from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient

from prompt_enhancer.adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.local_sources import (
    CodexLocalSourceService,
    LocalSourceSelectionError,
)
from prompt_enhancer.application.verification import (
    VerificationCapability,
    VerificationCapabilityState,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import (
    DataTier,
    Provider,
    SafeSession,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
)
from prompt_enhancer.ingestion import (
    ConsentRequiredError,
    IngestionReport,
    IngestionSelection,
)
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER


API_TOKEN = "synthetic-local-api-token-" + "x" * 32
ORIGIN = "http://127.0.0.1:8766"
PROJECT_ID = "a" * 64
SESSION_ID = "b" * 64


VERIFICATION_CAPABILITY = VerificationCapability(
    state=VerificationCapabilityState.UNSUPPORTED,
    live_classification_enabled=False,
    reason_code="synthetic_not_composed",
)


class FakeReadStore:
    def __init__(self, rows: list[dict[str, Any]] | None = None) -> None:
        self.rows = list(rows or [])
        self.initialized = 0
        self.provider_queries: list[Provider | None] = []

    def initialize(self) -> None:
        self.initialized += 1

    def list_metric_definitions(self) -> list[dict[str, Any]]:
        return []

    def list_sessions(
        self,
        *,
        limit: int = 100,
        offset: int = 0,
        provider: Provider | None = None,
    ) -> list[dict[str, Any]]:
        self.provider_queries.append(provider)
        filtered = self.rows
        if provider is not None:
            filtered = [row for row in filtered if row["provider"] == provider.value]
        return filtered[offset : offset + limit]

    def get_session_metrics(self, session_id: str) -> list[dict[str, Any]]:
        return []


class FakeSourceRepository:
    def __init__(self) -> None:
        self.active = False
        self.sessions = 2
        self.projects = 1
        self.indexed_project_ids = frozenset({PROJECT_ID})
        self.indexed_session_ids = frozenset({SESSION_ID})

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        assert provider is Provider.CODEX
        assert tier is DataTier.REDACTED_CONTENT
        return self.active

    def grant_consent(self, provider: Provider, tier: DataTier) -> None:
        assert provider is Provider.CODEX
        assert tier is DataTier.REDACTED_CONTENT
        self.active = True

    def revoke_consent(self, provider: Provider, tier: DataTier) -> None:
        assert provider is Provider.CODEX
        assert tier is DataTier.REDACTED_CONTENT
        self.active = False

    def provider_catalog_summary(self, provider: Provider) -> dict[str, int]:
        assert provider is Provider.CODEX
        return {"sessions": self.sessions, "projects": self.projects}

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool:
        assert provider is Provider.CODEX
        return (
            project_ids <= self.indexed_project_ids
            and session_ids <= self.indexed_session_ids
        )


class NeverReadAdapter(ProviderAdapter):
    """Synthetic boundary sentinel: the fake runner must never open a provider."""

    def __init__(self, operational_history: bool) -> None:
        self.operational_history = operational_history

    @property
    def provider(self) -> Provider:
        return Provider.CODEX

    def probe(self) -> AdapterProbe:
        raise AssertionError("the synthetic HTTP test must not probe a provider")

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        raise AssertionError("the synthetic HTTP test must not list provider sessions")

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        raise AssertionError("the synthetic HTTP test must not read provider events")

    def health(self) -> AdapterHealth:
        raise AssertionError("the synthetic HTTP test must not inspect provider health")


class RecordingIngestionRunner:
    def __init__(self) -> None:
        self.calls: list[tuple[NeverReadAdapter, IngestionSelection | None]] = []

    def ingest(
        self,
        adapter: ProviderAdapter,
        *,
        page_limit: int = 100,
        selection: IngestionSelection | None = None,
    ) -> IngestionReport:
        assert isinstance(adapter, NeverReadAdapter)
        assert page_limit == 100
        self.calls.append((adapter, selection))
        return IngestionReport(
            provider=Provider.CODEX,
            sessions_seen=2,
            sessions_selected=1,
            metrics_written=3 if adapter.operational_history else 0,
        )


def build_source_app(tmp_path: Path):
    store = FakeReadStore()
    repository = FakeSourceRepository()
    runner = RecordingIngestionRunner()
    factory_calls: list[bool] = []

    def adapter_factory(operational_history: bool) -> NeverReadAdapter:
        factory_calls.append(operational_history)
        return NeverReadAdapter(operational_history)

    service = CodexLocalSourceService(
        repository, runner, adapter_factory, VERIFICATION_CAPABILITY
    )
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=store,
        api_token=API_TOKEN,
        codex_source_service=service,
    )
    return app, store, repository, runner, factory_calls


def test_consent_revocation_stops_bound_local_workers_without_provider_read() -> None:
    repository = FakeSourceRepository()
    repository.active = True
    runner = RecordingIngestionRunner()
    revoked: list[Provider] = []
    service = CodexLocalSourceService(
        repository,
        runner,
        lambda operational_history: NeverReadAdapter(operational_history),
        VERIFICATION_CAPABILITY,
        automation_revoker=lambda provider: revoked.append(provider) or 1,
    )

    status = service.revoke_local_history()

    assert status.consent_active is False
    assert revoked == [Provider.CODEX]
    assert runner.calls == []


def bootstrap_browser(client: TestClient) -> str:
    response = client.get(
        "/auth/session",
        headers={"Sec-Fetch-Site": "same-origin"},
    )
    assert response.status_code == 200
    return response.json()["csrf_token"]


def mutation_headers(csrf_token: str) -> dict[str, str]:
    return {"Origin": ORIGIN, CSRF_HEADER: csrf_token}


def test_browser_cookie_auth_requires_same_origin_csrf_for_mutations(tmp_path) -> None:
    app, _, _, _, _ = build_source_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        assert client.get("/v1/local-sources/codex").status_code == 401
        rejected_bootstrap = client.get(
            "/auth/session", headers={"Sec-Fetch-Site": "cross-site"}
        )
        assert rejected_bootstrap.status_code == 403

        session = client.get(
            "/auth/session", headers={"Sec-Fetch-Site": "same-origin"}
        )
        csrf_token = session.json()["csrf_token"]
        set_cookie = session.headers["set-cookie"].casefold()

        assert session.status_code == 200
        assert session.json()["user_presence_confirmation_available"] is False
        assert session.json()["user_presence_confirmation_mode"] == "unavailable"
        assert "httponly" in set_cookie
        assert "samesite=strict" in set_cookie
        assert "path=/" in set_cookie
        assert "domain=" not in set_cookie
        assert client.get("/v1/local-sources/codex").status_code == 200

        no_origin = client.post(
            "/v1/local-sources/codex/consents/local-history"
        )
        wrong_csrf = client.post(
            "/v1/local-sources/codex/consents/local-history",
            headers={"Origin": ORIGIN, CSRF_HEADER: "synthetic-wrong-token"},
        )
        accepted = client.post(
            "/v1/local-sources/codex/consents/local-history",
            headers=mutation_headers(csrf_token),
        )

    assert no_origin.status_code == 403
    assert no_origin.json() == {"detail": "same-origin mutation required"}
    assert wrong_csrf.status_code == 403
    assert wrong_csrf.json() == {"detail": "CSRF validation failed"}
    assert accepted.status_code == 200
    assert accepted.json()["consent_active"] is True


def test_persistent_api_token_bypasses_browser_cookie_and_csrf(tmp_path) -> None:
    app, _, _, _, _ = build_source_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.post(
            "/v1/local-sources/codex/consents/local-history",
            headers={API_TOKEN_HEADER: API_TOKEN},
        )

    assert response.status_code == 200
    assert response.json()["consent_active"] is True


def test_local_source_endpoint_flow_is_explicit_bounded_and_selected(tmp_path) -> None:
    app, _, _, runner, factory_calls = build_source_app(tmp_path)

    with TestClient(app, base_url=ORIGIN) as client:
        csrf_token = bootstrap_browser(client)
        headers = mutation_headers(csrf_token)

        initial = client.get("/v1/local-sources/codex")
        granted = client.post(
            "/v1/local-sources/codex/consents/local-history", headers=headers
        )
        indexed = client.post(
            "/v1/local-sources/codex/index",
            headers=headers,
            json={"max_sessions": 5},
        )
        analyzed = client.post(
            "/v1/local-sources/codex/analysis",
            headers=headers,
            json={
                "project_ids": [PROJECT_ID],
                "session_ids": [SESSION_ID],
                "max_sessions": 3,
            },
        )
        calls_before_empty_request = list(factory_calls)
        empty_selection = client.post(
            "/v1/local-sources/codex/analysis",
            headers=headers,
            json={"project_ids": [], "session_ids": [], "max_sessions": 3},
        )
        revoked = client.delete(
            "/v1/local-sources/codex/consents/local-history", headers=headers
        )
        calls_before_denied_index = list(factory_calls)
        denied_index = client.post(
            "/v1/local-sources/codex/index",
            headers=headers,
            json={"max_sessions": 5},
        )

    assert initial.json() == {
        "consent_active": False,
        "indexed_sessions": 2,
        "indexed_projects": 1,
        "verification_capability": {
            "state": "unsupported",
            "live_classification_enabled": False,
            "classifier_version": None,
            "normalizer_version": None,
            "candidate_schema_version": None,
            "supported_kinds": [],
            "reason_code": "synthetic_not_composed",
        },
    }
    assert granted.json()["consent_active"] is True
    assert indexed.status_code == 200
    assert indexed.json()["sessions_selected"] == 1
    assert analyzed.status_code == 200
    assert analyzed.json()["metrics_written"] == 3
    assert empty_selection.status_code == 422
    assert factory_calls[:2] == [False, True]
    assert calls_before_empty_request == [False, True]
    assert revoked.json()["consent_active"] is False
    assert denied_index.status_code == 403
    assert factory_calls == calls_before_denied_index

    index_selection = runner.calls[0][1]
    analysis_selection = runner.calls[1][1]
    assert index_selection is not None
    assert index_selection.max_sessions == 5
    assert index_selection.has_selector is False
    assert analysis_selection is not None
    assert analysis_selection.project_ids == frozenset({PROJECT_ID})
    assert analysis_selection.session_ids == frozenset({SESSION_ID})
    assert analysis_selection.max_sessions == 3


def test_analysis_rejects_unindexed_and_excessive_selectors_before_adapter(
    tmp_path,
) -> None:
    app, _, repository, runner, factory_calls = build_source_app(tmp_path)
    repository.active = True
    headers = {API_TOKEN_HEADER: API_TOKEN}
    unknown_project_id = "f" * 64
    excessive_project_ids = [f"{value:064x}" for value in range(101)]

    with TestClient(app, base_url=ORIGIN) as client:
        unknown = client.post(
            "/v1/local-sources/codex/analysis",
            headers=headers,
            json={
                "project_ids": [unknown_project_id],
                "session_ids": [],
                "max_sessions": 10,
            },
        )
        excessive = client.post(
            "/v1/local-sources/codex/analysis",
            headers=headers,
            json={
                "project_ids": excessive_project_ids,
                "session_ids": [],
                "max_sessions": 10,
            },
        )

    assert unknown.status_code == 404
    assert unknown.json() == {"detail": "selected local source is not indexed"}
    assert unknown_project_id not in unknown.text
    assert excessive.status_code == 422
    assert unknown_project_id not in excessive.text
    assert factory_calls == []
    assert runner.calls == []


def test_service_denials_do_not_construct_an_adapter() -> None:
    repository = FakeSourceRepository()
    runner = RecordingIngestionRunner()
    factory_calls: list[bool] = []

    def adapter_factory(operational_history: bool) -> NeverReadAdapter:
        factory_calls.append(operational_history)
        return NeverReadAdapter(operational_history)

    service = CodexLocalSourceService(
        repository, runner, adapter_factory, VERIFICATION_CAPABILITY
    )

    with pytest.raises(ConsentRequiredError):
        service.index(max_sessions=10)
    assert factory_calls == []

    repository.active = True
    with pytest.raises(LocalSourceSelectionError):
        service.analyze(
            project_ids=frozenset(),
            session_ids=frozenset(),
            max_sessions=10,
        )
    assert factory_calls == []
    assert runner.calls == []


def test_provider_filter_reaches_the_narrow_database_query(tmp_path) -> None:
    rows = [
        {
            "session_id": "c" * 64,
            "installation_id": "e" * 64,
            "project_id": "f" * 64,
            "provider": "codex",
            "provider_version": "example-provider-1",
            "adapter_version": "example-adapter-1",
            "source_schema_version": "example-schema-1",
            "started_at": "2040-01-01T00:00:00+00:00",
            "ended_at": None,
            "terminal_state": "unknown",
            "events_complete": False,
            "project_display_name": "Example Project",
            "session_display_name": "Example Session",
            "project_display_name_origin": "provider",
            "session_display_name_origin": "provider",
            "project_manual_label_revision": 0,
            "session_manual_label_revision": 0,
            # The API must never forward unallowlisted repository fields.
            "transcript": "synthetic-canary-must-not-cross-http",
        },
        {
            "session_id": "d" * 64,
            "installation_id": "1" * 64,
            "project_id": "2" * 64,
            "provider": "synthetic",
            "provider_version": "example-provider-1",
            "adapter_version": "example-adapter-1",
            "source_schema_version": "example-schema-1",
            "started_at": "2040-01-02T00:00:00+00:00",
            "ended_at": None,
            "terminal_state": "unknown",
            "events_complete": False,
            "project_display_name": None,
            "session_display_name": None,
            "project_display_name_origin": "unknown",
            "session_display_name_origin": "unknown",
            "project_manual_label_revision": 0,
            "session_manual_label_revision": 0,
        },
    ]
    store = FakeReadStore(rows)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=store,
        api_token=API_TOKEN,
    )

    with TestClient(app, base_url=ORIGIN) as client:
        response = client.get(
            "/v1/sessions?provider=codex",
            headers={API_TOKEN_HEADER: API_TOKEN},
        )
        invalid = client.get(
            "/v1/sessions?provider=not-a-provider",
            headers={API_TOKEN_HEADER: API_TOKEN},
        )

    assert response.status_code == 200
    returned = response.json()["sessions"]
    assert len(returned) == 1
    expected = {
        key: value for key, value in rows[0].items() if key != "transcript"
    }
    expected["started_at"] = "2040-01-01T00:00:00Z"
    assert returned[0] == expected
    assert "synthetic-canary-must-not-cross-http" not in response.text
    assert store.provider_queries == [Provider.CODEX]
    assert invalid.status_code == 422


def test_sqlite_session_query_filters_provider(tmp_path) -> None:
    database = Database(tmp_path / "synthetic-metrics.sqlite3")
    database.initialize()
    codex_session = SafeSession(
        provider=Provider.CODEX,
        installation_id="1" * 64,
        project_id="2" * 64,
        session_id="3" * 64,
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        started_at=datetime(2040, 1, 1, tzinfo=UTC),
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
    )
    synthetic_session = SafeSession(
        provider=Provider.SYNTHETIC,
        installation_id="4" * 64,
        project_id="5" * 64,
        session_id="6" * 64,
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        started_at=datetime(2040, 1, 2, tzinfo=UTC),
        terminal_state=SessionState.COMPLETED,
        events_complete=True,
    )
    database.persist_session(codex_session, ())
    database.persist_session(synthetic_session, ())

    codex_rows = database.list_sessions(provider=Provider.CODEX)
    synthetic_rows = database.list_sessions(provider=Provider.SYNTHETIC)

    assert [row["session_id"] for row in codex_rows] == [codex_session.session_id]
    assert [row["session_id"] for row in synthetic_rows] == [
        synthetic_session.session_id
    ]
    assert database.selection_is_indexed(
        Provider.CODEX,
        project_ids=frozenset({codex_session.project_id}),
        session_ids=frozenset({codex_session.session_id}),
    )
    assert not database.selection_is_indexed(
        Provider.CODEX,
        project_ids=frozenset({"7" * 64}),
        session_ids=frozenset({codex_session.session_id}),
    )
    assert not database.selection_is_indexed(
        Provider.CODEX,
        project_ids=frozenset({synthetic_session.project_id}),
        session_ids=frozenset(),
    )
    assert not database.selection_is_indexed(
        Provider.CODEX,
        project_ids=frozenset(),
        session_ids=frozenset(),
    )


def test_integrated_static_hosting_uses_spa_fallback_but_reserves_api_paths(
    tmp_path,
) -> None:
    static_root = tmp_path / "synthetic-dashboard"
    static_root.mkdir()
    assets = static_root / "assets"
    assets.mkdir()
    (assets / "index-synthetic1.js").write_text(
        "globalThis.syntheticDashboard = true;",
        encoding="utf-8",
    )
    (static_root / "index.html").write_text(
        "<!doctype html><div id='root'>Synthetic dashboard</div>"
        "<script type='module' src='/assets/index-synthetic1.js'></script>",
        encoding="utf-8",
    )
    (static_root / "style.css").write_text("body { color: #123456; }", encoding="utf-8")
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=FakeReadStore(),
        api_token=API_TOKEN,
        static_directory=static_root,
    )

    with TestClient(app, base_url=ORIGIN) as client:
        root = client.get("/")
        asset = client.get("/style.css")
        fallback = client.get("/local-sources", headers={"Accept": "text/html"})
        missing_asset = client.get(
            "/missing.js", headers={"Accept": "application/javascript"}
        )
        reserved = [
            client.get(path, headers={"Accept": "text/html"})
            for path in ("/v1/missing", "/auth/missing", "/health/missing")
        ]

    assert root.status_code == 200
    assert "Synthetic dashboard" in root.text
    assert asset.status_code == 200
    assert "#123456" in asset.text
    assert fallback.status_code == 200
    assert "Synthetic dashboard" in fallback.text
    assert missing_asset.status_code == 404
    assert all(response.status_code == 404 for response in reserved)
    assert root.headers["cache-control"] == "no-store"
    assert "default-src 'self'" in root.headers["content-security-policy"]
    assert "img-src 'self' data: blob:" in root.headers["content-security-policy"]
