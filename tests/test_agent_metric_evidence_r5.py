from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from prompt_enhancer.application.analysis.agent_metric_evidence import (
    AGENT_METRIC_EVIDENCE_FILE_VERSION,
    AGENT_METRIC_EVIDENCE_FILE_VERSION_2,
    AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION,
    AgentMetricEvidenceDefinitionsOutOfDateError,
    AgentMetricEvidenceFileError,
    AgentMetricEvidenceFileV2,
    AgentMetricEvidenceService,
    AgentMetricEvidenceSourceContract,
    SealedRunAgentMetricEvidenceSource,
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
    MetricLifecycleProposalStatus,
    MetricLifecycleStaleWindowError,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_4,
    METRIC_PROJECTION_V2_VERSION_5,
)
from prompt_enhancer.interfaces.http.agent_metric_evidence_routes import (
    create_agent_metric_evidence_router,
)

from test_agent_metric_evidence_api import _file as _v1_file
from test_metric_lifecycle_evidence_persistence import _opportunity_command, _service


NOW = datetime(2042, 1, 1, tzinfo=UTC)


class _SourceAuthority:
    def __init__(self, source: AgentMetricEvidenceSourceContract) -> None:
        self.source = source

    def current_source_contract(
        self, session_id: str
    ) -> AgentMetricEvidenceSourceContract:
        return self.source


def _source(
    session_id: str,
    run_id: str,
    window_fingerprint: str,
    *,
    projection_version: str = METRIC_PROJECTION_V2_VERSION_5,
) -> AgentMetricEvidenceSourceContract:
    return AgentMetricEvidenceSourceContract(
        session_id=session_id,
        expected_source_run_id=run_id,
        source_window_fingerprint=window_fingerprint,
        registry_version=METRIC_CONTRACT_REGISTRY_VERSION_V2,
        contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
        projection_version=projection_version,
    )


def _canonical(value: object) -> bytes:
    return json.dumps(
        value, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")


def _v2_value(
    session_id: str,
    run_id: str,
    window_fingerprint: str,
    *,
    expiry: datetime = NOW + timedelta(minutes=30),
) -> dict[str, object]:
    family = MetricLifecycleFamily.AMBIGUITY_RESOLUTION
    return {
        "command": _opportunity_command(run_id, family).model_dump(mode="json"),
        "contains_objective_receipt_claims": False,
        "contains_prose": False,
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
            "model_id": "example-model-v2",
            "producer_id": "example-agent",
            "producer_version": "example-agent-v2",
        },
        "projection_version": METRIC_PROJECTION_V2_VERSION_5,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "schema_version": AGENT_METRIC_EVIDENCE_FILE_VERSION_2,
        "session_id": session_id,
        "source_window_fingerprint": window_fingerprint,
    }


def test_r5_contract_preview_and_duplicate_import_remain_inert(tmp_path) -> None:
    _database, session_id, run, _models, _repository, lifecycle = _service(tmp_path)
    source = _source(session_id, run.run_id, run.input_fingerprint)
    service = AgentMetricEvidenceService(lifecycle, _SourceAuthority(source))
    payload = _canonical(
        _v2_value(session_id, run.run_id, run.input_fingerprint)
    )
    digest = hashlib.sha256(payload).hexdigest()

    contract = service.contract(session_id)
    preview = service.preview(session_id=session_id, payload=payload, now=NOW)
    first = service.import_file(
        session_id=session_id,
        payload=payload,
        expected_payload_sha256=digest,
        confirmation=AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-r5-import-0001",
        now=NOW,
    )
    replay = service.import_file(
        session_id=session_id,
        payload=payload,
        expected_payload_sha256=digest,
        confirmation=AGENT_METRIC_EVIDENCE_IMPORT_CONFIRMATION,
        idempotency_key="synthetic-r5-import-0001",
        now=NOW,
    )

    assert contract.schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION_2
    assert contract.projection_version == METRIC_PROJECTION_V2_VERSION_5
    assert contract.source_window_fingerprint == run.input_fingerprint
    assert contract.scores_allowed is False
    assert contract.prose_allowed is False
    assert contract.objective_receipt_claims_allowed is False
    assert preview.schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION_2
    assert preview.source_window_fingerprint == run.input_fingerprint
    assert preview.can_set_numeric_metric is False
    assert first.applied is True
    assert first.proposal.status is MetricLifecycleProposalStatus.PROPOSED
    assert first.producer_claim_persisted is False
    assert first.raw_payload_persisted is False
    assert replay.applied is False
    assert replay.proposal == first.proposal


def test_sealed_run_adapter_preserves_r4_v1_history(tmp_path) -> None:
    _database, session_id, run, _repository, _evidence_repository, lifecycle = _service(
        tmp_path
    )
    service = AgentMetricEvidenceService(lifecycle)
    contract = service.contract(session_id)
    payload = _v1_file(
        session_id,
        run.run_id,
        expiry=NOW + timedelta(minutes=30),
    )
    parsed, _digest = parse_agent_metric_evidence_file(payload, now=NOW)

    assert contract.schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION
    assert contract.projection_version == METRIC_PROJECTION_V2_VERSION_4
    assert parsed.schema_version == AGENT_METRIC_EVIDENCE_FILE_VERSION


def test_sealed_run_adapter_reads_only_verified_content_free_identity() -> None:
    latest = SimpleNamespace(
        session_id="1" * 64,
        run_id="2" * 64,
        input_fingerprint="3" * 64,
        receipt=SimpleNamespace(
            metric_publication_v2=SimpleNamespace(
                registry_version=METRIC_CONTRACT_REGISTRY_VERSION_V2,
                contract_set_fingerprint=metric_contract_v2_set_fingerprint(),
                projection_version=METRIC_PROJECTION_V2_VERSION_5,
            )
        ),
    )
    repository = SimpleNamespace(get_latest=lambda _session_id: latest)

    source = SealedRunAgentMetricEvidenceSource(repository).current_source_contract(
        latest.session_id
    )

    assert source.model_dump() == {
        "session_id": latest.session_id,
        "expected_source_run_id": latest.run_id,
        "source_window_fingerprint": latest.input_fingerprint,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "contract_set_fingerprint": metric_contract_v2_set_fingerprint(),
        "projection_version": METRIC_PROJECTION_V2_VERSION_5,
    }


@pytest.mark.parametrize(
    "mutate",
    (
        lambda value: value.update(contract_set_fingerprint="7" * 64),
        lambda value: value.update(metric_contract_fingerprint="6" * 64),
        lambda value: value.update(contains_scores=True),
        lambda value: value.update(contains_prose=True),
        lambda value: value.update(contains_objective_receipt_claims=True),
        lambda value: value.update(score=1),
        lambda value: value.update(prose="synthetic prose is still forbidden"),
        lambda value: value.update(objective_receipt="5" * 64),
        lambda value: value["producer"].update(producer_id="unsafe producer"),
    ),
)
def test_r5_parser_rejects_tampered_bindings_content_and_producer_keys(
    mutate,
) -> None:
    value = _v2_value("1" * 64, "2" * 64, "3" * 64)
    mutate(value)
    with pytest.raises(AgentMetricEvidenceFileError):
        parse_agent_metric_evidence_file(_canonical(value), now=NOW)


def test_r5_parser_rejects_duplicate_keys_depth_item_budget_and_expiry() -> None:
    value = _v2_value("1" * 64, "2" * 64, "3" * 64)
    payload = _canonical(value)
    duplicate = payload[:-1] + b',"nonce":"' + b"8" * 64 + b'"}'
    deep: object = None
    for _ in range(10):
        deep = [deep]
    too_deep = _canonical({**value, "unknown": deep})
    too_many = _canonical({**value, "unknown": [None] * 1_101})
    expired = _canonical(
        _v2_value(
            "1" * 64,
            "2" * 64,
            "3" * 64,
            expiry=NOW,
        )
    )
    too_long = _canonical(
        _v2_value(
            "1" * 64,
            "2" * 64,
            "3" * 64,
            expiry=NOW + timedelta(hours=24, seconds=1),
        )
    )

    for candidate in (duplicate, too_deep, too_many, expired, too_long):
        with pytest.raises(AgentMetricEvidenceFileError):
            parse_agent_metric_evidence_file(candidate, now=NOW)


def test_r5_preview_rejects_wrong_window_even_when_run_is_unchanged(tmp_path) -> None:
    _database, session_id, run, _models, _repository, lifecycle = _service(tmp_path)
    service = AgentMetricEvidenceService(
        lifecycle,
        _SourceAuthority(_source(session_id, run.run_id, run.input_fingerprint)),
    )
    payload = _canonical(_v2_value(session_id, run.run_id, "8" * 64))

    with pytest.raises(AgentMetricEvidenceFileError):
        service.preview(session_id=session_id, payload=payload, now=NOW)

    wrong_run = _canonical(_v2_value(session_id, "8" * 64, run.input_fingerprint))
    with pytest.raises(MetricLifecycleStaleWindowError):
        service.preview(session_id=session_id, payload=wrong_run, now=NOW)


def test_r5_schema_with_future_projection_is_definitions_out_of_date() -> None:
    value = _v2_value("1" * 64, "2" * 64, "3" * 64)
    value["projection_version"] = "metric-contract-v2-projection-6"

    with pytest.raises(AgentMetricEvidenceDefinitionsOutOfDateError):
        parse_agent_metric_evidence_file(_canonical(value), now=NOW)


def test_contract_endpoint_selects_r5_and_names_future_definition_drift(
    tmp_path,
) -> None:
    _database, session_id, run, _models, _repository, lifecycle = _service(tmp_path)
    authority = _SourceAuthority(_source(session_id, run.run_id, run.input_fingerprint))
    service = AgentMetricEvidenceService(lifecycle, authority)
    app = FastAPI()
    app.include_router(create_agent_metric_evidence_router(lambda: None, service))
    path = f"/v1/sessions/{session_id}/agent-metric-evidence/contract"

    with TestClient(app, base_url="http://127.0.0.1") as client:
        current = client.get(path)
        authority.source = _source(
            session_id,
            run.run_id,
            run.input_fingerprint,
            projection_version="metric-contract-v2-projection-6",
        )
        future = client.get(path)

    assert current.status_code == 200
    assert current.json()["schema_version"] == AGENT_METRIC_EVIDENCE_FILE_VERSION_2
    assert current.json()["projection_version"] == METRIC_PROJECTION_V2_VERSION_5
    assert future.status_code == 409
    assert future.json()["detail"]["code"] == (
        "agent_metric_evidence_definitions_out_of_date"
    )


def test_v2_model_has_no_score_prose_or_objective_claim_fields() -> None:
    fields = set(AgentMetricEvidenceFileV2.model_fields)
    assert fields.isdisjoint(
        {
            "score",
            "numeric_value",
            "prose",
            "prompt",
            "transcript",
            "path",
            "objective_receipt",
        }
    )
