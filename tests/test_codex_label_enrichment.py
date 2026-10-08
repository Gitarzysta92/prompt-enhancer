from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.display_labels import (
    DisplayLabelError,
    LabelEnrichmentReport,
    LabelEntityKind,
    LabelObservationMethod,
    ManualDisplayLabelService,
    ProviderDisplayLabelEnrichmentService,
    ProviderDisplayLabelPolicy,
    ProviderLabelSource,
)
from prompt_enhancer.database import Database
from prompt_enhancer.domain import DataTier, Provider, SafeSession, SessionState
from prompt_enhancer.config import AppSettings
from prompt_enhancer.ingestion import IngestionSelection, IngestionService
from prompt_enhancer.infrastructure.providers.codex_app_server import (
    LABEL_EXTRACTOR_VERSION,
    CodexAppServerAdapter,
    CodexReadMode,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.client import (
    CodexAppServerClient,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.contracts import (
    parse_thread_label_summary,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.errors import (
    CodexCompatibilityError,
    CodexProtocolViolation,
)
from prompt_enhancer.infrastructure.providers.codex_app_server.transports.stdio_jsonl import (
    StdioJsonRpcTransport,
    ThreadReadPolicy,
)
from prompt_enhancer.privacy import Pseudonymizer


RAW_SESSION_ID = "example-label-session"
FULL_PATH_CANARY = "SYNTHETIC-LABEL-PARENT-CANARY"
PREVIEW_CANARY = "SYNTHETIC-LABEL-PREVIEW-CANARY"
API_TOKEN = "synthetic-label-api-token-" + "x" * 32
ORIGIN = "http://127.0.0.1:8766"
INSTALLATION_ID = "1" * 64
PROJECT_ID = "2" * 64
SESSION_ID = "3" * 64
CODEX_LABEL_POLICY = ProviderDisplayLabelPolicy(
    provider=Provider.CODEX,
    consent_tier=DataTier.REDACTED_CONTENT,
    observation_method=LabelObservationMethod.THREAD_READ_SUMMARY,
    extractor_version=LABEL_EXTRACTOR_VERSION,
    project_label_source=ProviderLabelSource.PATH_BASENAME,
    session_label_source=ProviderLabelSource.EXPLICIT_TITLE,
)


class RecordingTransport:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.notifications: list[tuple[str, dict[str, object] | None]] = []
        self.closed = False

    def _request(self, method: str, params: dict[str, object]) -> object:
        self.requests.append((method, params))
        return self.responses.pop(0)

    def _notify(self, method: str, params: dict[str, object] | None = None) -> None:
        self.notifications.append((method, params))

    def close(self) -> None:
        self.closed = True


def _listed_without_labels() -> dict[str, object]:
    return {
        "data": [
            {
                "id": RAW_SESSION_ID,
                "createdAt": 2_208_988_800,
                "status": "idle",
                "preview": PREVIEW_CANARY,
            }
        ],
        "nextCursor": None,
    }


def _safe_session(
    *,
    project_label: str | None,
    session_label: str | None,
) -> SafeSession:
    return SafeSession(
        provider=Provider.CODEX,
        installation_id=INSTALLATION_ID,
        project_id=PROJECT_ID,
        session_id=SESSION_ID,
        provider_version="example-1",
        adapter_version="example-adapter-1",
        source_schema_version="example-schema-1",
        started_at=datetime(2040, 1, 2, tzinfo=UTC),
        terminal_state=SessionState.UNKNOWN,
        events_complete=False,
        project_display_name=project_label,
        session_display_name=session_label,
    )


def test_selected_summary_enrichment_fills_labels_without_changing_identity(
    tmp_path,
    caplog,
    capsys,
) -> None:
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    database = Database(tmp_path / "metrics.sqlite3")
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)

    index_transport = RecordingTransport(
        [{"version": "example-1"}, _listed_without_labels()]
    )
    IngestionService(database, pseudonymizer).ingest(
        CodexAppServerAdapter(
            mode=CodexReadMode.METADATA_INDEX,
            client_factory=lambda: CodexAppServerClient(index_transport),
        ),
        selection=IngestionSelection(max_sessions=1),
    )
    [before] = database.list_sessions(provider=Provider.CODEX)
    assert before["project_display_name"] is None
    assert before["session_display_name"] is None

    summary_transport = RecordingTransport(
        [
            {"version": "example-1"},
            _listed_without_labels(),
            {
                "thread": {
                    "id": RAW_SESSION_ID,
                    "cwd": f"/example/{FULL_PATH_CANARY}/example-project",
                    "name": "Example imported task title",
                    "preview": PREVIEW_CANARY,
                }
            },
        ]
    )
    service = ProviderDisplayLabelEnrichmentService(
        database,
        pseudonymizer,
        lambda: CodexAppServerAdapter(
            mode=CodexReadMode.LABEL_ENRICHMENT,
            client_factory=lambda: CodexAppServerClient(summary_transport),
        ),
        CODEX_LABEL_POLICY,
    )

    report = service.enrich(
        project_ids=frozenset(),
        session_ids=frozenset({before["session_id"]}),
        max_sessions=10,
    )

    assert report.requested_sessions == 1
    assert report.matched_sessions == 1
    assert report.summary_reads == 1
    assert report.project_labels_filled == 1
    assert report.session_labels_filled == 1
    [after] = database.list_sessions(provider=Provider.CODEX)
    assert after["installation_id"] == before["installation_id"]
    assert after["project_id"] == before["project_id"]
    assert after["session_id"] == before["session_id"]
    assert after["project_display_name"] == "example-project"
    assert after["session_display_name"] == "Example imported task title"
    assert after["project_display_name_origin"] == "provider"
    assert after["session_display_name_origin"] == "provider"
    assert summary_transport.requests[-1] == (
        "thread/read",
        {"threadId": RAW_SESSION_ID, "includeTurns": False},
    )
    assert all(
        params.get("useStateDbOnly") is True
        for method, params in summary_transport.requests
        if method == "thread/list"
    )
    assert summary_transport.closed is True

    sqlite_payload = b"".join(
        candidate.read_bytes()
        for candidate in tmp_path.glob("metrics.sqlite3*")
        if candidate.is_file()
    )
    captured = capsys.readouterr()
    rendered = "\n".join(
        (
            caplog.text,
            captured.out,
            captured.err,
            repr(report),
        )
    )
    for canary in (RAW_SESSION_ID, FULL_PATH_CANARY, PREVIEW_CANARY):
        assert canary.encode("utf-8") not in sqlite_payload
        assert canary not in rendered


@pytest.mark.parametrize("turns", (None, []))
def test_summary_parser_accepts_only_content_free_turn_shapes(turns: object) -> None:
    payload: dict[str, object] = {
        "thread": {
            "id": "example-summary",
            "cwd": "/example/project",
            "name": "Example task",
            "preview": PREVIEW_CANARY,
        }
    }
    if turns is not None:
        payload["thread"]["turns"] = turns  # type: ignore[index]

    summary = parse_thread_label_summary(payload)

    assert summary.thread_id.get_secret_value() == "example-summary"
    assert "preview" not in type(summary).model_fields
    assert PREVIEW_CANARY not in repr(summary)
    assert PREVIEW_CANARY not in summary.model_dump_json()


@pytest.mark.parametrize(
    "turns",
    (
        [{"id": "example-turn", "items": []}],
        {},
        "unexpected",
        0,
    ),
)
def test_summary_parser_rejects_content_or_wrong_turn_shapes_without_echo(
    turns: object,
) -> None:
    with pytest.raises(CodexCompatibilityError) as error:
        parse_thread_label_summary(
            {
                "thread": {
                    "id": "example-summary",
                    "turns": turns,
                    "preview": PREVIEW_CANARY,
                }
            }
        )

    assert PREVIEW_CANARY not in str(error.value)


@pytest.mark.parametrize(
    "params",
    (
        {"threadId": "example-summary"},
        {"threadId": "example-summary", "includeTurns": True},
        {"threadId": "example-summary", "includeTurns": 0},
        {"threadId": "example-summary", "includeTurns": None},
        {"threadId": "example-summary", "includeTurns": "false"},
        {
            "threadId": "example-summary",
            "includeTurns": False,
            "extra": "not-allowed",
        },
    ),
)
def test_summary_transport_rejects_nonexact_read_before_process_start(
    params: dict[str, object],
) -> None:
    transport = StdioJsonRpcTransport(
        thread_read_policy=ThreadReadPolicy.SUMMARY_ONLY
    )
    started = False

    def fail_if_started() -> None:
        nonlocal started
        started = True
        raise AssertionError("invalid request reached process startup")

    transport._start = fail_if_started  # type: ignore[method-assign]
    with pytest.raises(CodexProtocolViolation):
        transport._request("thread/read", params)

    assert started is False


def test_all_visible_labels_skip_provider_construction(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(
        _safe_session(
            project_label="Example project",
            session_label="Example task",
        ),
        (),
    )
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    constructed = False

    def forbidden_factory() -> CodexAppServerAdapter:
        nonlocal constructed
        constructed = True
        raise AssertionError("provider must not be constructed")

    report = ProviderDisplayLabelEnrichmentService(
        database,
        Pseudonymizer(bytes(range(32))),
        forbidden_factory,
        CODEX_LABEL_POLICY,
    ).enrich(
        project_ids=frozenset(),
        session_ids=frozenset({SESSION_ID}),
        max_sessions=10,
    )

    assert report.requested_sessions == 0
    assert report.summary_reads == 0
    assert constructed is False


def test_manual_override_wins_and_clear_reveals_latest_provider_label(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(
        _safe_session(
            project_label="Provider project",
            session_label="Provider task",
        ),
        (),
    )
    service = ManualDisplayLabelService(database)

    project_result = service.set(
        entity_kind=LabelEntityKind.PROJECT,
        entity_id=PROJECT_ID,
        value=SecretStr("My local project"),
        expected_revision=0,
    )
    session_result = service.set(
        entity_kind=LabelEntityKind.SESSION,
        entity_id=SESSION_ID,
        value=SecretStr("My local task"),
        expected_revision=0,
    )
    assert project_result.revision == 1
    assert session_result.revision == 1

    database.persist_session(
        _safe_session(
            project_label="Updated provider project",
            session_label="Updated provider task",
        ),
        (),
    )
    [overridden] = database.list_sessions(provider=Provider.CODEX)
    assert overridden["project_display_name"] == "My local project"
    assert overridden["session_display_name"] == "My local task"
    assert overridden["project_display_name_origin"] == "manual"
    assert overridden["session_display_name_origin"] == "manual"

    service.clear(
        entity_kind=LabelEntityKind.PROJECT,
        entity_id=PROJECT_ID,
        expected_revision=1,
    )
    service.clear(
        entity_kind=LabelEntityKind.SESSION,
        entity_id=SESSION_ID,
        expected_revision=1,
    )
    [revealed] = database.list_sessions(provider=Provider.CODEX)
    assert revealed["project_display_name"] == "Updated provider project"
    assert revealed["session_display_name"] == "Updated provider task"
    assert revealed["project_display_name_origin"] == "provider"
    assert revealed["session_display_name_origin"] == "provider"
    assert revealed["project_manual_label_revision"] == 2
    assert revealed["session_manual_label_revision"] == 2


def test_operational_adapter_cannot_be_used_as_a_label_source(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(_safe_session(project_label=None, session_label=None), ())
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    transport = RecordingTransport([{"version": "example-1"}])

    service = ProviderDisplayLabelEnrichmentService(
        database,
        Pseudonymizer(bytes(range(32))),
        lambda: CodexAppServerAdapter(
            mode=CodexReadMode.OPERATIONAL_HISTORY,
            client_factory=lambda: CodexAppServerClient(transport),
        ),
        CODEX_LABEL_POLICY,
    )

    with pytest.raises(DisplayLabelError):
        service.enrich(
            project_ids=frozenset(),
            session_ids=frozenset({SESSION_ID}),
            max_sessions=1,
        )

    assert [method for method, _params in transport.requests] == ["initialize"]
    assert transport.closed is True


def test_consent_tier_mismatch_is_rejected_before_provider_rpc(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(_safe_session(project_label=None, session_label=None), ())
    database.grant_consent(Provider.CODEX, DataTier.METADATA)
    transport = RecordingTransport([{"version": "example-1"}])
    weaker_policy = ProviderDisplayLabelPolicy(
        provider=Provider.CODEX,
        consent_tier=DataTier.METADATA,
        observation_method=LabelObservationMethod.THREAD_READ_SUMMARY,
        extractor_version=LABEL_EXTRACTOR_VERSION,
        project_label_source=ProviderLabelSource.PATH_BASENAME,
        session_label_source=ProviderLabelSource.EXPLICIT_TITLE,
    )
    service = ProviderDisplayLabelEnrichmentService(
        database,
        Pseudonymizer(bytes(range(32))),
        lambda: CodexAppServerAdapter(
            mode=CodexReadMode.LABEL_ENRICHMENT,
            client_factory=lambda: CodexAppServerClient(transport),
        ),
        weaker_policy,
    )

    with pytest.raises(DisplayLabelError):
        service.enrich(
            project_ids=frozenset(),
            session_ids=frozenset({SESSION_ID}),
            max_sessions=1,
        )

    assert transport.requests == []
    assert transport.notifications == []


def test_label_source_factory_failure_is_sanitized(tmp_path) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(_safe_session(project_label=None, session_label=None), ())
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    factory_canary = "SYNTHETIC-LABEL-FACTORY-CANARY"

    def unavailable_source() -> CodexAppServerAdapter:
        raise RuntimeError(factory_canary)

    service = ProviderDisplayLabelEnrichmentService(
        database,
        Pseudonymizer(bytes(range(32))),
        unavailable_source,
        CODEX_LABEL_POLICY,
    )

    with pytest.raises(DisplayLabelError) as error:
        service.enrich(
            project_ids=frozenset(),
            session_ids=frozenset({SESSION_ID}),
            max_sessions=1,
        )

    assert factory_canary not in str(error.value)


def test_changed_project_identity_is_rejected_before_summary_read(tmp_path) -> None:
    pseudonymizer = Pseudonymizer(bytes(range(32)))
    database = Database(tmp_path / "metrics.sqlite3")
    database.grant_consent(Provider.CODEX, DataTier.REDACTED_CONTENT)
    index_transport = RecordingTransport(
        [{"version": "example-1"}, _listed_without_labels()]
    )
    IngestionService(database, pseudonymizer).ingest(
        CodexAppServerAdapter(
            mode=CodexReadMode.METADATA_INDEX,
            client_factory=lambda: CodexAppServerClient(index_transport),
        ),
        selection=IngestionSelection(max_sessions=1),
    )
    [before] = database.list_sessions(provider=Provider.CODEX)
    changed_listing = _listed_without_labels()
    changed_listing["data"][0]["cwd"] = "/example/changed-project"  # type: ignore[index]
    transport = RecordingTransport([{"version": "example-1"}, changed_listing])
    service = ProviderDisplayLabelEnrichmentService(
        database,
        pseudonymizer,
        lambda: CodexAppServerAdapter(
            mode=CodexReadMode.LABEL_ENRICHMENT,
            client_factory=lambda: CodexAppServerClient(transport),
        ),
        CODEX_LABEL_POLICY,
    )

    with pytest.raises(DisplayLabelError):
        service.enrich(
            project_ids=frozenset(),
            session_ids=frozenset({before["session_id"]}),
            max_sessions=1,
        )

    assert [method for method, _params in transport.requests] == [
        "initialize",
        "thread/list",
    ]
    [after] = database.list_sessions(provider=Provider.CODEX)
    assert after["project_display_name"] is None
    assert after["session_display_name"] is None
    assert transport.closed is True


class RecordingLabelSourceService:
    def __init__(self) -> None:
        self.calls: list[tuple[frozenset[str], frozenset[str], int]] = []

    def enrich_labels(
        self,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
        max_sessions: int,
    ) -> LabelEnrichmentReport:
        self.calls.append((project_ids, session_ids, max_sessions))
        return LabelEnrichmentReport(
            provider=Provider.CODEX,
            requested_sessions=1,
            matched_sessions=1,
            summary_reads=1,
            session_labels_filled=1,
        )


def test_label_enrichment_http_command_is_authenticated_selected_and_bounded(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    service = RecordingLabelSourceService()
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=database,
        api_token=API_TOKEN,
        codex_source_service=service,  # type: ignore[arg-type]
    )
    validation_canary = "SYNTHETIC-INVALID-SELECTOR-CANARY"


    with TestClient(app, base_url=ORIGIN) as client:
        denied = client.post(
            "/v1/local-sources/codex/display-labels/enrich",
            json={
                "project_ids": [],
                "session_ids": [SESSION_ID],
                "max_sessions": 10,
            },
        )
        accepted = client.post(
            "/v1/local-sources/codex/display-labels/enrich",
            headers={API_TOKEN_HEADER: API_TOKEN},
            json={
                "project_ids": [],
                "session_ids": [SESSION_ID],
                "max_sessions": 10,
            },
        )
        excessive = client.post(
            "/v1/local-sources/codex/display-labels/enrich",
            headers={API_TOKEN_HEADER: API_TOKEN},
            json={
                "project_ids": [],
                "session_ids": [f"{value:064x}" for value in range(26)],
                "max_sessions": 25,
            },
        )
        invalid_selector = client.post(
            "/v1/local-sources/codex/display-labels/enrich",
            headers={API_TOKEN_HEADER: API_TOKEN},
            json={
                "project_ids": [],
                "session_ids": [validation_canary],
                "max_sessions": 1,
            },
        )

    assert denied.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json()["session_labels_filled"] == 1
    assert service.calls == [(frozenset(), frozenset({SESSION_ID}), 10)]
    assert excessive.status_code == 422

    assert invalid_selector.status_code == 422
    assert validation_canary not in invalid_selector.text
    assert invalid_selector.json() == {"detail": "request validation failed"}

def test_manual_label_http_commands_do_not_echo_or_rename_provider_data(
    tmp_path,
) -> None:
    database = Database(tmp_path / "metrics.sqlite3")
    database.persist_session(
        _safe_session(
            project_label="Provider project",
            session_label="Provider task",
        ),
        (),
    )
    app = create_app(
        settings=AppSettings(home=tmp_path / "app-home"),
        database=database,
        api_token=API_TOKEN,
        display_label_service=ManualDisplayLabelService(database),
    )
    headers = {API_TOKEN_HEADER: API_TOKEN}
    unsafe_canary = "Fix /example/private/SYNTHETIC-LABEL-CANARY.py"

    with TestClient(app, base_url=ORIGIN) as client:
        updated = client.put(
            f"/v1/catalog/sessions/{SESSION_ID}/display-label",
            headers=headers,
            json={"value": "My local task", "expected_revision": 0},
        )
        conflict = client.put(
            f"/v1/catalog/sessions/{SESSION_ID}/display-label",
            headers=headers,
            json={"value": "Another local task", "expected_revision": 0},
        )
        invalid = client.put(
            f"/v1/catalog/sessions/{SESSION_ID}/display-label",
            headers=headers,
            json={"value": unsafe_canary, "expected_revision": 1},
        )
        listed = client.get(
            "/v1/sessions?provider=codex",
            headers=headers,
        )
        cleared = client.delete(
            f"/v1/catalog/sessions/{SESSION_ID}/display-label"
            "?expected_revision=1",
            headers=headers,
        )

    assert updated.status_code == 200
    assert updated.json() == {
        "entity_kind": "session",
        "entity_id": SESSION_ID,
        "revision": 1,
        "changed": True,
    }
    assert "My local task" not in updated.text
    assert conflict.status_code == 409
    assert invalid.status_code == 422
    assert unsafe_canary not in invalid.text
    [record] = listed.json()["sessions"]
    assert record["session_display_name"] == "My local task"
    assert record["session_display_name_origin"] == "manual"
    assert cleared.status_code == 200
    assert database.list_sessions(provider=Provider.CODEX)[0][
        "session_display_name"
    ] == "Provider task"
