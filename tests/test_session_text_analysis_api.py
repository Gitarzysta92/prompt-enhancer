from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.session_text_service import (
    SESSION_TEXT_ANALYSIS_CONFIRMATION,
    SessionTextAnalysisConflictError,
    SessionTextAnalysisCompatibilityError,
    SessionTextAnalysisConsentError,
    SessionTextAnalysisExecutionError,
    SessionTextAnalysisOutcome,
    SessionTextAnalysisPersistenceError,
    SessionTextAnalysisSelectionError,
    SessionTextAnalysisSourceError,
)
from prompt_enhancer.application.analysis.redaction_preview import (
    REDACTION_PREVIEW_CONFIRMATION,
    AnalysisApproval,
    AnalysisDestination,
    CostEstimateState,
    RedactionPreviewBinding,
    RedactionPreviewConsumedError,
    RedactionPreviewExpiredError,
    RedactionPreviewInspection,
    RedactionPreviewMessage,
    RedactionPreviewMismatchError,
    RedactionPreviewReceipt,
    RetentionClass,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    TextAnalysisPresetId,
)
from prompt_enhancer.application.analysis.text_contracts import (
    TextLanguage,
    TextMessageKind,
    TextRole,
)
from prompt_enhancer.application.analysis.text_source import TextSourceFailureReason
from prompt_enhancer.application.persistence import AnalysisRunStatus
from prompt_enhancer.config import AppSettings
from prompt_enhancer.database import Database
from prompt_enhancer.domain import Provider
from prompt_enhancer.ingestion import IngestionService
from prompt_enhancer.privacy import Pseudonymizer


TOKEN = "example_quality_analysis_token_1234567890"
PREVIEW_CANARY = "SYNTHETIC-REDACTED-PREVIEW-CANARY"
PREVIEW_TIME = datetime(2044, 5, 6, 7, 8, tzinfo=UTC)


def _database(tmp_path) -> tuple[Database, str]:
    database = Database(tmp_path / "metrics.sqlite3")
    database.initialize()
    IngestionService(database, Pseudonymizer(bytes(range(32)))).ingest(
        SyntheticAdapter()
    )
    session_id = database.list_sessions(limit=1)[0]["session_id"]
    return database, session_id


def _payload() -> dict[str, object]:
    return {
        "confirmation": SESSION_TEXT_ANALYSIS_CONFIRMATION,
        "preset_id": TextAnalysisPresetId.STANDARD_ENGINEERING_V1.value,
    }


def _inspection(session_id: str) -> RedactionPreviewInspection:
    binding = RedactionPreviewBinding(
        provider=Provider.CODEX,
        session_id=session_id,
        analysis_window_fingerprint="a" * 64,
        metric_keys=("prompt.task_definition_coverage",),
        destination=AnalysisDestination.LOCAL,
        exact_model="none",
        estimator_plan_version="example-plan-1",
        redactor_version="example-redactor-1",
        retention_class=RetentionClass.LOCAL_EPHEMERAL,
        message_count=1,
        character_count=len(PREVIEW_CANARY),
        cost_state=CostEstimateState.NOT_APPLICABLE,
    )
    return RedactionPreviewInspection(
        receipt=RedactionPreviewReceipt(
            preview_id="e" * 64,
            created_at=PREVIEW_TIME,
            expires_at=PREVIEW_TIME + timedelta(minutes=10),
            binding=binding,
        ),
        messages=(
            RedactionPreviewMessage(
                role=TextRole.USER,
                kind=TextMessageKind.REQUEST,
                language=TextLanguage.ENGLISH,
                text=SecretStr(PREVIEW_CANARY),
            ),
        ),
    )


@dataclass
class RecordingService:
    error: Exception | None = None

    def __post_init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    def run_preset(self, **values: object) -> SessionTextAnalysisOutcome:
        self.calls.append(values)
        if self.error is not None:
            raise self.error
        return SessionTextAnalysisOutcome(
            run_id="f" * 64,
            status=AnalysisRunStatus.COMPLETED,
            result_count=10,
            applied=True,
            analysis_profile_key="standard_engineering",
            analysis_profile_version=1,
        )

    def prepare_preset_preview(
        self,
        **values: object,
    ) -> RedactionPreviewInspection:
        self.calls.append({"operation": "prepare_preview", **values})
        if self.error is not None:
            raise self.error
        return _inspection(str(values["session_id"]))

    def approve_preview(
        self,
        approval: AnalysisApproval,
    ) -> SessionTextAnalysisOutcome:
        self.calls.append({"operation": "approve_preview", "approval": approval})
        if self.error is not None:
            raise self.error
        return SessionTextAnalysisOutcome(
            run_id="f" * 64,
            status=AnalysisRunStatus.COMPLETED,
            result_count=10,
            applied=True,
            analysis_profile_key="standard_engineering",
            analysis_profile_version=1,
        )


def _client(tmp_path, service: RecordingService) -> tuple[TestClient, str]:
    database, session_id = _database(tmp_path)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        session_text_analysis_service=service,  # type: ignore[arg-type]
    )
    return TestClient(app, base_url="http://127.0.0.1"), session_id


def test_explicit_quality_command_is_authenticated_and_content_free(tmp_path) -> None:
    service = RecordingService()
    client, session_id = _client(tmp_path, service)
    path = f"/v1/sessions/{session_id}/quality-analysis-runs"

    with client:
        unauthorized = client.post(path, json=_payload(), headers={"Idempotency-Key": "run-1"})
        response = client.post(
            path,
            json=_payload(),
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "run-1",
            },
        )

    assert unauthorized.status_code == 401
    assert response.status_code == 200
    assert response.json() == {
        "run_id": "f" * 64,
        "status": "completed",
        "result_count": 10,
        "applied": True,
        "analysis_profile_key": "standard_engineering",
        "analysis_profile_version": 1,
    }
    assert len(service.calls) == 1
    call = service.calls[0]
    # The route passes the session's own catalog provider (the fixture seeds a
    # synthetic session) instead of assuming Codex.
    assert call["provider"] is Provider.SYNTHETIC
    assert call["session_id"] == session_id
    assert call["confirmation"] == SESSION_TEXT_ANALYSIS_CONFIRMATION
    assert call["preset_id"] is TextAnalysisPresetId.STANDARD_ENGINEERING_V1
    assert set(call) == {
        "provider",
        "session_id",
        "preset_id",
        "confirmation",
        "idempotency_key",
    }
    assert "text" not in response.text.casefold()


def test_preview_and_approval_are_authenticated_private_no_store_flows(
    tmp_path,
    caplog,
) -> None:
    service = RecordingService()
    client, session_id = _client(tmp_path, service)
    preview_path = f"/v1/sessions/{session_id}/quality-analysis-previews"

    with client:
        unauthorized = client.post(
            preview_path,
            json={"preset_id": "standard_engineering_v1"},
        )
        preview = client.post(
            preview_path,
            json={"preset_id": "standard_engineering_v1"},
            headers={API_TOKEN_HEADER: TOKEN},
        )
        preview_payload = preview.json()
        approval = client.post(
            f"/v1/quality-analysis-previews/{preview_payload['preview_id']}/approval",
            json={
                "confirmation": REDACTION_PREVIEW_CONFIRMATION,
                "expected_binding": preview_payload["binding"],
            },
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "preview-run-1",
            },
        )

    assert unauthorized.status_code == 401
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store, private"
    assert preview.headers["pragma"] == "no-cache"
    assert preview_payload["messages"][0]["text"] == PREVIEW_CANARY
    assert preview_payload["binding"]["destination"] == "local"
    assert preview_payload["binding"]["exact_model"] == "none"
    assert preview_payload["binding"]["retention_class"] == "local_ephemeral"
    assert preview_payload["binding"]["cost_state"] == "not_applicable"
    assert approval.status_code == 200
    assert approval.headers["cache-control"] == "no-store, private"
    assert approval.headers["pragma"] == "no-cache"
    assert PREVIEW_CANARY not in approval.text
    assert len(service.calls) == 2
    assert PREVIEW_CANARY not in repr(service.calls)
    assert PREVIEW_CANARY not in caplog.text
    assert PREVIEW_CANARY.encode() not in (tmp_path / "metrics.sqlite3").read_bytes()
    approved = service.calls[1]["approval"]
    assert isinstance(approved, AnalysisApproval)
    assert approved.idempotency_key == "preview-run-1"
    assert approved.expected_binding == _inspection(session_id).receipt.binding


@pytest.mark.parametrize(
    ("error", "status", "code"),
    (
        (
            RedactionPreviewMismatchError(),
            409,
            "redaction_preview_binding_mismatch",
        ),
        (
            RedactionPreviewConsumedError(),
            409,
            "redaction_preview_consumed",
        ),
        (
            RedactionPreviewExpiredError(),
            410,
            "redaction_preview_expired",
        ),
    ),
)
def test_preview_approval_errors_are_sanitized_and_no_store(
    tmp_path,
    error: Exception,
    status: int,
    code: str,
) -> None:
    service = RecordingService(error=error)
    client, session_id = _client(tmp_path, service)
    inspection = _inspection(session_id)

    with client:
        response = client.post(
            f"/v1/quality-analysis-previews/{inspection.receipt.preview_id}/approval",
            json={
                "confirmation": REDACTION_PREVIEW_CONFIRMATION,
                "expected_binding": inspection.receipt.binding.model_dump(
                    mode="json"
                ),
            },
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "preview-run-1",
            },
        )

    assert response.status_code == status
    assert response.json()["detail"]["code"] == code
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"
    assert PREVIEW_CANARY not in response.text


def test_preview_openapi_requires_idempotency_only_for_approval(tmp_path) -> None:
    service = RecordingService()
    client, _session_id = _client(tmp_path, service)
    paths = client.app.openapi()["paths"]

    preview_operation = paths[
        "/v1/sessions/{session_id}/quality-analysis-previews"
    ]["post"]
    approval_operation = paths[
        "/v1/quality-analysis-previews/{preview_id}/approval"
    ]["post"]

    preview_parameters = {
        parameter["name"] for parameter in preview_operation["parameters"]
    }
    approval_parameters = {
        parameter["name"] for parameter in approval_operation["parameters"]
    }
    assert "session_id" in preview_parameters
    assert "Idempotency-Key" not in preview_parameters
    assert {"preview_id", "Idempotency-Key"}.issubset(approval_parameters)
    assert "410" in approval_operation["responses"]


def test_quality_command_rejects_unknown_preset_before_service(tmp_path) -> None:
    service = RecordingService()
    client, session_id = _client(tmp_path, service)
    path = f"/v1/sessions/{session_id}/quality-analysis-runs"
    payload = _payload()
    payload["preset_id"] = "private_custom_profile"

    with client:
        response = client.post(
            path,
            json=payload,
            headers={API_TOKEN_HEADER: TOKEN, "Idempotency-Key": "run-1"},
        )

    assert response.status_code == 422
    assert response.json() == {"detail": "request validation failed"}
    assert service.calls == []


def test_quality_command_documents_both_sanitized_422_shapes(tmp_path) -> None:
    service = RecordingService()
    client, session_id = _client(tmp_path, service)
    del session_id

    operation = client.app.openapi()["paths"][
        "/v1/sessions/{session_id}/quality-analysis-runs"
    ]["post"]
    response_schema = operation["responses"]["422"]["content"][
        "application/json"
    ]["schema"]
    references = {
        item["$ref"]
        for item in response_schema["anyOf"]
    }

    assert references == {
        "#/components/schemas/SessionTextAnalysisFailureResponse",
        "#/components/schemas/SanitizedRequestValidationFailureResponse",
    }


def test_quality_command_rejects_client_profile_bounds_and_content_before_service(
    tmp_path,
) -> None:
    service = RecordingService()
    client, session_id = _client(tmp_path, service)
    path = f"/v1/sessions/{session_id}/quality-analysis-runs"
    headers = {API_TOKEN_HEADER: TOKEN, "Idempotency-Key": "run-1"}
    content_payload = _payload()
    content_payload["transcript"] = "PRIVATE-REQUEST-CONTENT-CANARY"
    profile_payload = _payload()
    profile_payload["task_profile"] = {"applicability": []}
    bounds_payload = _payload()
    bounds_payload["max_messages"] = 500

    with client:
        profile_field = client.post(path, json=profile_payload, headers=headers)
        bounds_field = client.post(path, json=bounds_payload, headers=headers)
        content_field = client.post(path, json=content_payload, headers=headers)

    assert profile_field.status_code == 422
    assert bounds_field.status_code == 422
    assert content_field.status_code == 422
    assert profile_field.json() == {"detail": "request validation failed"}
    assert bounds_field.json() == {"detail": "request validation failed"}
    assert content_field.json() == {"detail": "request validation failed"}
    assert "PRIVATE-REQUEST-CONTENT-CANARY" not in content_field.text
    assert service.calls == []


@pytest.mark.parametrize(
    ("error", "expected_status", "code", "message"),
    (
        (
            SessionTextAnalysisConsentError("PRIVATE-CANARY"),
            403,
            "redacted_content_consent_required",
            "redacted-content consent required",
        ),
        (
            SessionTextAnalysisSelectionError("PRIVATE-CANARY"),
            404,
            "session_not_in_safe_index",
            "selected session is not indexed",
        ),
        (
            SessionTextAnalysisConflictError("PRIVATE-CANARY"),
            409,
            "analysis_idempotency_conflict",
            "analysis idempotency conflict",
        ),
        (
            SessionTextAnalysisCompatibilityError("PRIVATE-CANARY"),
            409,
            "provider_compatibility_blocked",
            "provider compatibility is not verified",
        ),
        (
            SessionTextAnalysisSourceError(
                TextSourceFailureReason.PROVIDER_UNAVAILABLE
            ),
            503,
            "provider_unavailable",
            "local source provider is unavailable",
        ),
        (
            SessionTextAnalysisExecutionError("PRIVATE-CANARY"),
            503,
            "metric_execution_failed",
            "local metric execution is unavailable",
        ),
        (
            SessionTextAnalysisPersistenceError("PRIVATE-CANARY"),
            503,
            "analysis_persistence_failed",
            "local analysis persistence is unavailable",
        ),
    ),
)
def test_quality_command_errors_are_sanitized(
    tmp_path,
    error: Exception,
    expected_status: int,
    code: str,
    message: str,
) -> None:
    service = RecordingService(error=error)
    client, session_id = _client(tmp_path, service)

    with client:
        response = client.post(
            f"/v1/sessions/{session_id}/quality-analysis-runs",
            json=_payload(),
            headers={API_TOKEN_HEADER: TOKEN, "Idempotency-Key": "run-1"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "detail": {"code": code, "message": message}
    }
    assert "PRIVATE-CANARY" not in response.text


@pytest.mark.parametrize(
    ("reason", "expected_status", "message"),
    (
        (
            TextSourceFailureReason.SCHEMA_UNSUPPORTED,
            503,
            "local source schema is unsupported",
        ),
        (
            TextSourceFailureReason.SELECTION_SNAPSHOT_MISS,
            409,
            "selected session is absent from the current provider snapshot",
        ),
        (
            TextSourceFailureReason.SELECTION_LIMIT,
            413,
            "provider session selection exceeds the local scan bounds",
        ),
        (
            TextSourceFailureReason.PROVIDER_RESPONSE_LIMIT,
            413,
            "local provider response exceeds the transport bound",
        ),
        (
            TextSourceFailureReason.THREAD_STRUCTURE_LIMIT,
            413,
            "selected session structure exceeds the local parser bounds",
        ),
        (
            TextSourceFailureReason.PREVIEW_WINDOW_LIMIT,
            413,
            "selected focus message exceeds the local preview bound",
        ),
        (
            TextSourceFailureReason.RESOURCE_LIMIT,
            413,
            "local source exceeded an unspecified resource bound",
        ),
        (
            TextSourceFailureReason.TIMEOUT,
            504,
            "local source read timed out",
        ),
        (
            TextSourceFailureReason.NO_ANALYZABLE_TEXT,
            422,
            "selected session has no analyzable text",
        ),
        (
            TextSourceFailureReason.PROTOCOL_REJECTED,
            503,
            "local provider rejected the bounded read protocol",
        ),
    ),
)
def test_quality_command_exposes_only_bounded_source_failure_codes(
    tmp_path,
    reason: TextSourceFailureReason,
    expected_status: int,
    message: str,
) -> None:
    service = RecordingService(error=SessionTextAnalysisSourceError(reason))
    client, session_id = _client(tmp_path, service)

    with client:
        response = client.post(
            f"/v1/sessions/{session_id}/quality-analysis-runs",
            json=_payload(),
            headers={API_TOKEN_HEADER: TOKEN, "Idempotency-Key": "run-1"},
        )

    assert response.status_code == expected_status
    assert response.json() == {
        "detail": {"code": reason.value, "message": message}
    }
    assert "PRIVATE" not in response.text
