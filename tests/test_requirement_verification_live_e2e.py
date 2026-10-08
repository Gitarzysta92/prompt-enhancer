"""Synthetic live r8 tour from durable verification evidence to HTTP metrics."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import sqlite3
from typing import Any

from fastapi.testclient import TestClient
from pydantic import SecretStr

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    InMemoryRequirementPlanReviewContextStore,
)
from prompt_enhancer.application.analysis.semantic_units import SemanticUnitReconciler
from prompt_enhancer.application.analysis.session_model_ensemble import (
    MODEL_ENSEMBLE_CONFIRMATION,
    SessionModelEnsembleService,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.application.analysis.text_contracts import TextMessageKind
from prompt_enhancer.application.analysis.text_source import TextAnalysisPurpose
from prompt_enhancer.bootstrap import LocalApplication, bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import DataTier, Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.infrastructure.text_models.model_ensemble import (
    SerialModelEnsembleRunner,
)
from prompt_enhancer.interfaces.http.user_presence import (
    UserPresenceApprovalManager,
)
from prompt_enhancer.interfaces.http.model_ensemble_routes import ModelEnsembleRunDto
from prompt_enhancer.privacy import load_or_create_api_token

from test_probabilistic_metric_persistence import _context
from test_requirement_verification_e2e import (
    BASE_URL,
    MODEL_CLAIM_CANARY,
    PRIVATE_CANARY,
    _HttpStack,
    _append_acceptance,
    _append_result,
    _assert_private,
    _confirm_plan,
    _issue_opportunities,
    _opportunity_set,
    _result_command,
    _seed_sealed_run,
    _verify_presence,
)
from test_session_model_ensemble import _execute
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    RequirementAcceptanceOutcome,
    RequirementVerificationOutcome,
)


class _Compatible:
    def require_compatible(self, provider: str) -> object:
        assert provider == "codex"
        return object()


class _IndexedConsent:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return provider is Provider.CODEX and tier is DataTier.REDACTED_CONTENT

    def selection_is_indexed(
        self,
        provider: Provider,
        *,
        project_ids: frozenset[str],
        session_ids: frozenset[str],
    ) -> bool:
        return (
            provider is Provider.CODEX
            and not project_ids
            and session_ids == {self._session_id}
        )


class _FixedSyntheticSource:
    provider = Provider.CODEX
    purpose = TextAnalysisPurpose.TEXT_ANALYSIS
    read_only = True
    requires_explicit_selection = True

    def __init__(self, context: Any) -> None:
        self._context = context

    def read(self, *, selection: Any, grant: Any, task_profile: Any) -> Any:
        assert selection.session_id == self._context.session_id
        assert grant.local_only is True
        assert grant.content_persistence_allowed is False
        assert task_profile == self._context.task_profile
        return self._context


class _AdvancingClock:
    def __init__(self) -> None:
        self._next = datetime(2043, 1, 1, tzinfo=UTC)

    def __call__(self) -> datetime:
        value = self._next
        self._next += timedelta(seconds=1)
        return value


def _source_context(session_id: str) -> Any:
    base = _context(session_id)
    return base.model_copy(
        update={
            "available_message_kinds": frozenset(
                {TextMessageKind.REQUEST, TextMessageKind.PLAN}
            ),
            "task_profile": COACHING_PROFILE_V1.task_profile,
            "messages": (
                base.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "First fictional requirement. "
                            "Second fictional requirement. "
                            "Third fictional requirement. "
                            f"{PRIVATE_CANARY}."
                        )
                    }
                ),
                base.messages[1].model_copy(
                    update={
                        "kind": TextMessageKind.PLAN,
                        "text": SecretStr(
                            "Implement the first fictional requirement. "
                            "Verify the fictional result."
                        ),
                    }
                ),
            ),
        }
    )


def _live_stack(
    application: LocalApplication,
    *,
    session_id: str,
    review_contexts: InMemoryRequirementPlanReviewContextStore | None,
) -> _HttpStack:
    identifiers = LocalArtifactIdFactory(application.pseudonymizer)
    source = _FixedSyntheticSource(_source_context(session_id))
    clock = _AdvancingClock()
    service = SessionModelEnsembleService(
        _IndexedConsent(session_id),
        application.database.model_ensemble_repository(),
        lambda provider: source,
        _Compatible(),
        identifiers,
        SerialModelEnsembleRunner(
            executor=_execute,
            device="cpu",
            clock=clock,
        ),
        clock=clock,
        semantic_unit_reconciler=SemanticUnitReconciler(identifiers),
        lifecycle_evidence_reader=(
            application.database.metric_lifecycle_evidence_repository()
        ),
        declared_task_profile_reader=(
            application.database.declared_task_profile_repository()
        ),
        requirement_plan_evidence_reader=(
            application.database.requirement_plan_evidence_repository()
        ),
        requirement_plan_review_contexts=review_contexts,
        requirement_action_evidence_reader=(
            application.database.requirement_action_evidence_repository()
        ),
        requirement_verification_reader=(
            application.database.requirement_verification_evidence_repository()
        ),
    )
    presence = UserPresenceApprovalManager()
    token = load_or_create_api_token(application.settings.api_token_path)
    app = create_app(
        settings=application.settings,
        database=application.database,
        api_token=token,
        session_model_ensemble_service=service,
        requirement_plan_evidence_service=(
            None
            if review_contexts is None
            else application.create_requirement_plan_evidence_service(
                review_contexts
            )
        ),
        requirement_verification_evidence_service=(
            application.create_requirement_verification_evidence_service()
        ),
        user_presence_confirmation=_verify_presence(presence),
        user_presence_confirmation_mode="native_bridge_bound_token",
    )
    return _HttpStack(
        application=application,
        app=app,
        token=token,
        presence=presence,
    )


def _run_live(client: TestClient, stack: _HttpStack, session_id: str, key: str) -> Any:
    response = client.post(
        f"/v1/sessions/{session_id}/model-ensemble-runs",
        headers={API_TOKEN_HEADER: stack.token, "Idempotency-Key": key},
        json={"confirmation": MODEL_ENSEMBLE_CONFIRMATION},
    )
    _assert_private(response)
    assert response.status_code == 200, response.text
    return response


def _metric(run: dict[str, object], metric_key: str) -> dict[str, Any]:
    publication = run["metric_publication_v2"]
    assert isinstance(publication, dict)
    return next(
        item["state"]
        for item in publication["metrics"]
        if item["state"]["metric_key"] == metric_key
    )


def _assert_verified_typed_receipt(
    run: dict[str, Any], state: dict[str, Any]
) -> None:
    typed = next(
        item
        for item in run["typed_metrics"]
        if item["metric_key"] == "outcome.verified_requirement_coverage"
    )
    statistics = state["statistics"]
    resolved = statistics["met_count"] + statistics["not_met_count"]
    expected_coverage = (
        0
        if statistics["eligible_count"] == 0
        else resolved / statistics["eligible_count"]
    )
    assert (
        typed["value_state"],
        typed["numerator"],
        typed["denominator"],
        typed["numeric_value"],
        typed["observed_message_count"],
        typed["eligible_message_count"],
        typed["coverage"],
        typed["explanation_code"],
        typed["error_code"],
    ) == (
        state["value_state"],
        state["numerator"],
        state["denominator"],
        state["numeric_value"],
        resolved,
        statistics["eligible_count"],
        expected_coverage,
        state["explanation_code"],
        None,
    )
    assert (
        typed["engine_version"],
        typed["algorithm_id"],
        typed["algorithm_version"],
        typed["rubric_version"],
    ) == (
        "reviewed-requirement-verification-objective-projection-v1",
        "reviewed-requirement-verification-authority",
        "4",
        "objective-evidence-no-rubric-v4",
    )


def test_historical_awaiting_marker_survives_later_opportunity_issuance(
    tmp_path,
) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path))
    seed = _seed_sealed_run(application)
    stack = _live_stack(
        application,
        session_id=seed.session_id,
        review_contexts=seed.review_contexts,
    )
    with TestClient(stack.app, base_url=BASE_URL) as client:
        _confirm_plan(client, stack, seed)
        awaiting_response = _run_live(
            client,
            stack,
            seed.session_id,
            "synthetic-live-r8-pre-issuance-0001",
        )
        awaiting_run = awaiting_response.json()["run"]
        awaiting_binding = awaiting_run[
            "requirement_verification_evidence_binding"
        ]
        assert awaiting_binding["evidence_source"] == "awaiting_evidence"
        awaiting_metric = _metric(
            awaiting_run,
            "outcome.verified_requirement_coverage",
        )
        assert awaiting_metric["explanation_code"] == (
            "requirement_verification_evidence_unavailable"
        )

        issued = _issue_opportunities(client, stack, seed.session_id)
        assert issued.status_code == 201

    historical = application.database.model_ensemble_repository().get(
        awaiting_run["run_id"]
    )
    assert historical is not None
    historical_payload = ModelEnsembleRunDto.from_record(historical).model_dump(
        mode="json"
    )
    assert historical_payload["requirement_verification_evidence_binding"] == (
        awaiting_binding
    )
    assert _metric(
        historical_payload,
        "outcome.verified_requirement_coverage",
    ) == awaiting_metric

    restarted = bootstrap_local_application(AppSettings(home=tmp_path))
    restarted_historical = restarted.database.model_ensemble_repository().get(
        awaiting_run["run_id"]
    )
    assert restarted_historical is not None
    assert ModelEnsembleRunDto.from_record(restarted_historical).model_dump(
        mode="json"
    ) == historical_payload


def test_persisted_requirement_verification_becomes_live_r8_and_survives_restart(
    tmp_path,
) -> None:
    application = bootstrap_local_application(AppSettings(home=tmp_path))
    seed = _seed_sealed_run(application)
    stack = _live_stack(
        application,
        session_id=seed.session_id,
        review_contexts=seed.review_contexts,
    )
    rendered: list[str] = []
    with TestClient(stack.app, base_url=BASE_URL) as client:
        _confirm_plan(client, stack, seed)
        issued = _issue_opportunities(client, stack, seed.session_id)
        opportunities = _opportunity_set(issued.json()["snapshot"])

        awaiting_response = _run_live(
            client,
            stack,
            seed.session_id,
            "synthetic-live-r8-awaiting-0001",
        )
        rendered.append(awaiting_response.text)
        awaiting = awaiting_response.json()
        assert awaiting["applied"] is True
        awaiting_run = awaiting["run"]
        assert awaiting_run["metric_publication_v2"]["projection_version"] == (
            "metric-contract-v2-projection-8"
        )
        assert awaiting_run["metric_evidence_readiness_v2"]["catalog_version"] == (
            "metric-evidence-readiness-v2-7"
        )
        awaiting_binding = awaiting_run[
            "requirement_verification_evidence_binding"
        ]
        assert awaiting_binding["evidence_source"] == "persisted_evidence"
        assert awaiting_binding["through_revision"] == 0
        assert awaiting_binding["authority_head_count"] == 0
        assert awaiting_binding["resolved_opportunity_count"] == 0
        assert set(awaiting_binding).isdisjoint(
            {"session_id", "source_window_fingerprint", "bound_at"}
        )
        awaiting_metric = _metric(
            awaiting_run, "outcome.verified_requirement_coverage"
        )
        assert awaiting_metric["value_state"] == "unknown"
        assert awaiting_metric["explanation_code"] == (
            "app_issued_requirement_verification_pending"
        )
        assert awaiting_metric["statistics"]["eligible_count"] == 3
        assert awaiting_metric["statistics"]["unknown_count"] == 3
        assert (
            awaiting_metric["numerator"],
            awaiting_metric["denominator"],
            awaiting_metric["numeric_value"],
        ) == (None, None, None)
        _assert_verified_typed_receipt(awaiting_run, awaiting_metric)

        first = _append_result(
            client,
            stack,
            seed.session_id,
            _result_command(
                stack,
                opportunities,
                ordinal=0,
                observed_sequence=101,
                outcome=RequirementVerificationOutcome.PASSED,
            ),
            key="synthetic-live-r8-result-0001",
        )
        accepted = _append_acceptance(
            client,
            stack,
            seed.session_id,
            opportunities,
            ordinal=1,
            outcome=RequirementAcceptanceOutcome.ACCEPTED,
            key="synthetic-live-r8-acceptance-0001",
        )
        failed = _append_result(
            client,
            stack,
            seed.session_id,
            _result_command(
                stack,
                opportunities,
                ordinal=2,
                observed_sequence=102,
                outcome=RequirementVerificationOutcome.FAILED,
            ),
            key="synthetic-live-r8-result-0002",
        )
        assert (first.status_code, accepted.status_code, failed.status_code) == (
            201,
            201,
            201,
        )

        measured_response = _run_live(
            client,
            stack,
            seed.session_id,
            "synthetic-live-r8-measured-0001",
        )
        rendered.append(measured_response.text)
        measured = measured_response.json()
        assert measured["applied"] is True
        measured_run = measured["run"]
        assert measured_run["run_id"] != awaiting_run["run_id"]
        measured_binding = measured_run[
            "requirement_verification_evidence_binding"
        ]
        assert measured_binding["evidence_source"] == "persisted_evidence"
        assert (
            measured_binding["through_revision"],
            measured_binding["authority_head_count"],
            measured_binding["objective_result_count"],
            measured_binding["native_acceptance_count"],
            measured_binding["resolved_opportunity_count"],
            measured_binding["met_requirement_count"],
        ) == (3, 3, 2, 1, 3, 2)
        assert measured_binding["binding_fingerprint"] != awaiting_binding[
            "binding_fingerprint"
        ]
        measured_metric = _metric(
            measured_run, "outcome.verified_requirement_coverage"
        )
        assert measured_metric["value_state"] == "known"
        assert measured_metric["explanation_code"] == (
            "app_issued_verified_requirement_coverage"
        )
        assert (
            measured_metric["numerator"],
            measured_metric["denominator"],
            measured_metric["numeric_value"],
        ) == (2, 3, 2 / 3)
        _assert_verified_typed_receipt(measured_run, measured_metric)
        verified_typed_receipt = next(
            item
            for item in measured_run["typed_metrics"]
            if item["metric_key"] == "outcome.verified_requirement_coverage"
        )
        assert verified_typed_receipt["algorithm_id"] == (
            "reviewed-requirement-verification-authority"
        )
        assert verified_typed_receipt["engine_version"] == (
            "reviewed-requirement-verification-objective-projection-v1"
        )

        latest = client.get(
            f"/v1/sessions/{seed.session_id}/model-ensemble-runs/latest",
            headers={API_TOKEN_HEADER: stack.token},
        )
        _assert_private(latest)
        assert latest.status_code == 200
        assert latest.json()["run_id"] == measured_run["run_id"], (
            latest.json()["run_id"],
            latest.json()["completed_at"],
            awaiting_run["run_id"],
            awaiting_run["completed_at"],
            measured_run["run_id"],
            measured_run["completed_at"],
        )
        assert latest.json()["requirement_verification_evidence_binding"] == (
            measured_binding
        )
        assert _metric(
            latest.json(), "outcome.verified_requirement_coverage"
        ) == measured_metric
        operability = client.get(
            "/v1/metric-contracts/v2/operability-catalog",
            headers={API_TOKEN_HEADER: stack.token},
        )
        assert operability.status_code == 200
        catalog = operability.json()
        assert catalog["catalog_version"] == "metric-operability-v4"
        assert catalog["projection_version"] == "metric-contract-v2-projection-8"
        assert catalog["readiness_catalog_version"] == (
            "metric-evidence-readiness-v2-7"
        )
        assert (
            catalog["shipped_path_count"],
            catalog["task_profile_configuration_gap_count"],
            catalog["provider_adapter_gap_count"],
            catalog["model_authoritative_metric_count"],
        ) == (16, 0, 4, 0)

    historical = application.database.model_ensemble_repository().get(
        awaiting_run["run_id"]
    )
    assert historical is not None
    assert historical.requirement_verification_evidence_binding is not None
    assert historical.requirement_verification_evidence_binding.through_revision == 0
    historical_payload = ModelEnsembleRunDto.from_record(historical).model_dump(
        mode="json"
    )
    assert historical_payload["requirement_verification_evidence_binding"] == (
        awaiting_binding
    )
    assert _metric(
        historical_payload, "outcome.verified_requirement_coverage"
    ) == awaiting_metric

    restarted_application = bootstrap_local_application(AppSettings(home=tmp_path))
    restarted = _live_stack(
        restarted_application,
        session_id=seed.session_id,
        review_contexts=None,
    )
    with TestClient(restarted.app, base_url=BASE_URL) as client:
        replay = _run_live(
            client,
            restarted,
            seed.session_id,
            "synthetic-live-r8-measured-0001",
        )
        rendered.append(replay.text)
        assert replay.json()["applied"] is False
        replay_run = replay.json()["run"]
        assert replay_run["run_id"] == measured_run["run_id"]
        assert replay_run["requirement_verification_evidence_binding"] == (
            measured_binding
        )
        assert _metric(
            replay_run, "outcome.verified_requirement_coverage"
        ) == measured_metric

    public_text = "\n".join(rendered)
    assert PRIVATE_CANARY not in public_text
    assert MODEL_CLAIM_CANARY not in public_text
    for artifact in (
        restarted_application.database.path,
        restarted_application.database.path.with_name(
            f"{restarted_application.database.path.name}-wal"
        ),
        restarted_application.database.path.with_name(
            f"{restarted_application.database.path.name}-shm"
        ),
    ):
        if artifact.exists():
            payload = artifact.read_bytes()
            assert PRIVATE_CANARY.encode("ascii") not in payload
            assert MODEL_CLAIM_CANARY.encode("ascii") not in payload
    with sqlite3.connect(restarted_application.database.path) as connection:
        stored = connection.execute(
            "SELECT COUNT(*) FROM session_model_ensemble_requirement_verification_bindings"
        ).fetchone()
    assert stored == (2,)
