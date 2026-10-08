from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.agent_metric_evidence import (
    AGENT_METRIC_EVIDENCE_FILE_VERSION,
    AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION,
    AgentMetricEvidenceFileError,
    parse_agent_metric_evidence_file,
)
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    METRIC_CONTRACT_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.metric_lifecycle_evidence import (
    MetricLifecycleFamily,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_4,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.agent_metric_evidence_routes import (
    AGENT_METRIC_EVIDENCE_MEDIA_TYPE,
)

from test_metric_lifecycle_evidence_persistence import (
    _opportunity_command,
    _service,
)


TOKEN = "example_agent_evidence_token_do_not_use_123456789"


def _file(session_id: str, run_id: str, *, expiry: datetime) -> bytes:
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    value = {
        "command": _opportunity_command(run_id, family).model_dump(mode="json"),
        "contains_objective_receipt_claims": False,
        "contains_scores": False,
        "contract_set_fingerprint": metric_contract_v2_set_fingerprint(),
        "contract_version": METRIC_CONTRACT_VERSION_V2,
        "expected_source_run_id": run_id,
        "expires_at": expiry.isoformat(),
        "metric_contract_fingerprint": metric_contract_v2(family.value).fingerprint,
        "metric_key": family.value,
        "nonce": "9" * 64,
        "producer": {
            "authority": "untrusted_provenance_claim",
            "kind": "local_coding_agent",
            "model_id": "example-model-v1",
            "producer_id": "example-agent",
            "producer_version": "example-agent-v1",
        },
        "projection_version": METRIC_PROJECTION_V2_VERSION_4,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "schema_version": AGENT_METRIC_EVIDENCE_FILE_VERSION,
        "session_id": session_id,
    }
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode("ascii")


def _app(tmp_path):
    database, session_id, run, _models, _repository, service = _service(tmp_path)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        metric_lifecycle_evidence_service=service,
    )
    return app, session_id, run


def test_preview_then_import_creates_only_an_unconfirmed_proposal(tmp_path) -> None:
    app, session_id, run = _app(tmp_path)
    payload = _file(
        session_id,
        run.run_id,
        expiry=datetime.now(UTC) + timedelta(minutes=30),
    )
    digest = hashlib.sha256(payload).hexdigest()
    base = f"/v1/sessions/{session_id}/agent-metric-evidence"
    common = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": AGENT_METRIC_EVIDENCE_MEDIA_TYPE,
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.post(f"{base}/preview", content=payload).status_code == 401
        contract = client.get(f"{base}/contract", headers={API_TOKEN_HEADER: TOKEN})
        preview = client.post(f"{base}/preview", headers=common, content=payload)
        imported = client.post(
            f"{base}/import",
            headers={
                **common,
                "Idempotency-Key": "example-agent-file-import-0001",
                "X-Agent-Evidence-Confirmation": (
                    AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION
                ),
                "X-Agent-Evidence-Payload-SHA256": digest,
            },
            content=payload,
        )

    assert contract.status_code == 200
    assert contract.headers["cache-control"] == "no-store, private"
    assert contract.json()["expected_source_run_id"] == run.run_id
    assert len(contract.json()["metrics"]) == 5
    assert contract.json()["scores_allowed"] is False
    assert contract.json()["objective_receipt_claims_allowed"] is False
    assert preview.status_code == 200
    assert preview.headers["cache-control"] == "no-store, private"
    assert preview.headers["pragma"] == "no-cache"
    assert preview.json()["payload_sha256"] == digest
    assert preview.json()["can_set_numeric_metric"] is False
    assert preview.json()["creates_unconfirmed_proposal_only"] is True
    assert preview.json()["requires_authenticated_local_user_confirmation"] is True
    assert imported.status_code == 201
    assert imported.headers["cache-control"] == "no-store, private"
    assert imported.json()["proposal"]["status"] == "proposed"
    assert imported.json()["raw_payload_persisted"] is False
    assert imported.json()["producer_claim_persisted"] is False
    serialized = imported.text.casefold()
    for prohibited in ("prompt", "transcript", "excerpt", "file_path", "score"):
        assert prohibited not in serialized


def test_file_boundary_rejects_noncanonical_duplicate_score_stale_and_rebinding(
    tmp_path,
) -> None:
    app, session_id, run = _app(tmp_path)
    payload = _file(
        session_id,
        run.run_id,
        expiry=datetime.now(UTC) + timedelta(minutes=30),
    )
    base = f"/v1/sessions/{session_id}/agent-metric-evidence/preview"
    headers = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": AGENT_METRIC_EVIDENCE_MEDIA_TYPE,
    }
    decoded = json.loads(payload)
    forbidden = json.dumps(
        {**decoded, "score": 1}, sort_keys=True, separators=(",", ":")
    ).encode("ascii")
    duplicate = payload[:-1] + b',"nonce":"8' + b"8" * 63 + b'"}'
    noncanonical = json.dumps(decoded, indent=2).encode("ascii")
    stale = _file(
        session_id,
        "f" * 64,
        expiry=datetime.now(UTC) + timedelta(minutes=30),
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        wrong_type = client.post(base, headers={API_TOKEN_HEADER: TOKEN}, content=payload)
        responses = [
            client.post(base, headers=headers, content=item)
            for item in (forbidden, duplicate, noncanonical, stale)
        ]
    assert wrong_type.status_code == 415
    assert [item.status_code for item in responses] == [422, 422, 422, 409]
    for response in responses:
        assert response.headers["cache-control"] == "no-store, private"
        assert "score" not in response.text.casefold()


def test_parser_rejects_expired_or_overlong_lifetime() -> None:
    now = datetime(2042, 1, 1, tzinfo=UTC)
    session_id = "1" * 64
    run_id = "2" * 64
    for expiry in (now, now + timedelta(hours=24, seconds=1)):
        try:
            parse_agent_metric_evidence_file(
                _file(session_id, run_id, expiry=expiry), now=now
            )
        except AgentMetricEvidenceFileError:
            pass
        else:
            raise AssertionError("out-of-policy agent evidence expiry was accepted")


def test_openapi_exposes_raw_file_preview_and_import_without_score_fields(tmp_path) -> None:
    app, _session_id, _run = _app(tmp_path)
    schema = app.openapi()
    paths = tuple(path for path in schema["paths"] if "agent-metric-evidence" in path)
    assert paths == (
        "/v1/sessions/{session_id}/agent-metric-evidence/contract",
        "/v1/sessions/{session_id}/agent-metric-evidence/preview",
        "/v1/sessions/{session_id}/agent-metric-evidence/import",
    )
    serialized = str(
        {
            key: value
            for key, value in schema["components"]["schemas"].items()
            if "AgentMetricEvidence" in key
        }
    ).casefold()
    for prohibited in ("prompt_text", "transcript", "excerpt", "file_path", "numeric_value"):
        assert prohibited not in serialized
