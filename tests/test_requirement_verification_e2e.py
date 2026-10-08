"""Synthetic vertical tour for durable reviewed-requirement verification.

The golden path deliberately crosses the production composition root, real
SQLite migrations/repositories, and authenticated HTTP routes.  All source
content is fictional and ephemeral; the durable contract contains keyed
identities, closed enums, coordinates, counts, and versions only.

Checkpoint 7B owns live objective-metric projection.  This 7A/7C tour therefore
asserts the durable evidence snapshot and the still-frozen public operability
catalog without pretending that persisted evidence already rewrites a sealed
metric publication.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import json
import sqlite3
from typing import Any

from fastapi import HTTPException
from fastapi.testclient import TestClient
from pydantic import SecretStr
import pytest

from prompt_enhancer.adapters.synthetic import SyntheticAdapter
from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.metric_contract_v2 import (
    METRIC_CONTRACT_REGISTRY_VERSION_V2,
    metric_contract_v2,
    metric_contract_v2_set_fingerprint,
)
from prompt_enhancer.application.analysis.metric_projection_v2 import (
    METRIC_PROJECTION_V2_VERSION_6,
)
from prompt_enhancer.application.analysis.metric_projection_v6 import (
    project_metric_states_v6,
)
from prompt_enhancer.application.analysis.metric_publication_v2 import (
    publish_metric_states_v2,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
    REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    REQUIREMENT_PLAN_METRIC_KEY,
    REQUIREMENT_PLAN_REVIEW_CONFIRMATION,
    REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
    InMemoryRequirementPlanReviewContextStore,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
)
from prompt_enhancer.application.analysis.requirement_verification_evidence import (
    AppIssuedRequirementVerificationOpportunitySet,
    RequirementAcceptanceOutcome,
    RequirementVerificationMethod,
    RequirementVerificationOutcome,
    issue_requirement_verification_result,
)
from prompt_enhancer.application.analysis.requirement_verification_persistence import (
    REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    RequirementAcceptanceAppendCommand,
    RequirementVerificationResultAppendCommand,
)
from prompt_enhancer.application.analysis.semantic_units import (
    SemanticUnitReconciler,
)
from prompt_enhancer.application.analysis.session_model_ensemble import (
    REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
    REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION,
    REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION,
    RequirementPlanEvidenceSource,
    SessionRequirementPlanEvidenceBinding,
)
from prompt_enhancer.application.analysis.text_contracts import TextMessageKind
from prompt_enhancer.bootstrap import LocalApplication, bootstrap_local_application
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import Provider
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from prompt_enhancer.interfaces.http.requirement_plan_evidence_routes import (
    REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
)
from prompt_enhancer.interfaces.http.user_presence import (
    USER_PRESENCE_HEADER,
    UserPresenceApprovalManager,
)
from prompt_enhancer.privacy import load_or_create_api_token

from test_model_ensemble_r5_profile_persistence import _preset_binding, _record
from test_probabilistic_metric_persistence import IDS, _context


PRIVATE_CANARY = "SYNTHETIC-RAW-REQUIREMENT-CANARY-DO-NOT-PERSIST"
MODEL_CLAIM_CANARY = "SYNTHETIC-MODEL-CLAIM-CANARY-DO-NOT-PERSIST"
BASE_URL = "http://127.0.0.1"
VERIFICATION_TABLES = (
    "requirement_verification_opportunity_sets",
    "requirement_verification_opportunities",
    "requirement_verification_opportunity_set_seals",
    "requirement_verification_authority_records",
    "requirement_verification_result_receipt_refs",
    "requirement_verification_authority_record_seals",
)


@dataclass(frozen=True, slots=True)
class _Seed:
    session_id: str
    run: Any
    review_contexts: InMemoryRequirementPlanReviewContextStore


@dataclass(frozen=True, slots=True)
class _HttpStack:
    application: LocalApplication
    app: Any
    token: str
    presence: UserPresenceApprovalManager


def _assert_private(response: Any) -> None:
    assert response.headers["cache-control"] == "no-store, private", (
        response.request.method,
        response.request.url,
        response.status_code,
        response.text,
    )
    assert response.headers["pragma"] == "no-cache"


def _verify_presence(manager: UserPresenceApprovalManager):  # type: ignore[no-untyped-def]
    def verify(request: Any, body: bytes) -> None:
        if not manager.consume(
            token=request.headers.get(USER_PRESENCE_HEADER),
            method=request.method,
            path=request.url.path,
            body=body,
        ):
            raise HTTPException(
                status_code=403,
                detail="native user-presence confirmation required",
            )

    return verify


def _native_post(
    client: TestClient,
    manager: UserPresenceApprovalManager,
    *,
    path: str,
    payload: dict[str, object],
    csrf_token: str,
    idempotency_key: str | None = None,
):  # type: ignore[no-untyped-def]
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )
    approval = manager.issue(
        method="POST",
        path=path,
        body_sha256=hashlib.sha256(body).hexdigest(),
    )
    headers = {
        "Content-Type": "application/json",
        "Origin": BASE_URL,
        CSRF_HEADER: csrf_token,
        USER_PRESENCE_HEADER: approval,
    }
    if idempotency_key is not None:
        headers["Idempotency-Key"] = idempotency_key
    return client.post(path, headers=headers, content=body)


def _seed_sealed_run(application: LocalApplication) -> _Seed:
    """Seed one fictional current run through production storage/services."""

    application.create_ingestion_service().ingest(SyntheticAdapter())
    database = application.database
    session_id = str(
        database.list_sessions(provider=Provider.SYNTHETIC, limit=1)[0]["session_id"]
    )
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE projects SET provider='codex'")
        connection.execute("UPDATE sessions SET provider='codex'")
        connection.commit()

    legacy = _record(
        session_id,
        run_character="a",
        request_character="b",
        binding=_preset_binding(session_id),
    )
    base_context = _context(session_id)
    context = base_context.model_copy(
        update={
            "available_message_kinds": frozenset(
                {TextMessageKind.REQUEST, TextMessageKind.PLAN}
            ),
            "messages": (
                base_context.messages[0].model_copy(
                    update={
                        "text": SecretStr(
                            "First fictional requirement. "
                            "Second fictional requirement. "
                            "Third fictional requirement. "
                            f"{PRIVATE_CANARY}."
                        )
                    }
                ),
                base_context.messages[1].model_copy(
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
    publication = publish_metric_states_v2(
        project_metric_states_v6(
            context=context,
            reconciliation=SemanticUnitReconciler(IDS).reconcile(
                context
            ).reconciliation,
            id_factory=IDS,
        )
    )
    run = legacy.model_copy(
        update={
            "requirement_plan_evidence_binding": (
                SessionRequirementPlanEvidenceBinding(
                    evidence_source=RequirementPlanEvidenceSource.UNAVAILABLE,
                    session_id=session_id,
                    source_window_fingerprint=legacy.input_fingerprint,
                    evidence_fingerprint=REQUIREMENT_PLAN_UNAVAILABLE_FINGERPRINT,
                    evidence_schema_version=(
                        REQUIREMENT_PLAN_UNAVAILABLE_SCHEMA_VERSION
                    ),
                    evidence_policy_version=(
                        REQUIREMENT_PLAN_UNAVAILABLE_POLICY_VERSION
                    ),
                    bound_at=datetime.now(UTC),
                )
            ),
            "receipt": legacy.receipt.model_copy(
                update={"metric_publication_v2": publication}
            ),
        }
    )
    database.model_ensemble_repository().save_completed(run)
    review_contexts = InMemoryRequirementPlanReviewContextStore()
    review_contexts.publish(run.run_id, context)
    return _Seed(session_id=session_id, run=run, review_contexts=review_contexts)


def _build_stack(
    home: Any,
    *,
    seed: _Seed | None = None,
    application: LocalApplication | None = None,
) -> _HttpStack:
    settings = AppSettings(home=home)
    local = application or bootstrap_local_application(settings)
    presence = UserPresenceApprovalManager()
    plan_service = (
        None
        if seed is None
        else local.create_requirement_plan_evidence_service(seed.review_contexts)
    )
    app = create_app(
        settings=settings,
        database=local.database,
        api_token=load_or_create_api_token(settings.api_token_path),
        requirement_plan_evidence_service=plan_service,
        requirement_verification_evidence_service=(
            local.create_requirement_verification_evidence_service()
        ),
        user_presence_confirmation=_verify_presence(presence),
        user_presence_confirmation_mode="native_bridge_bound_token",
    )
    return _HttpStack(
        application=local,
        app=app,
        token=load_or_create_api_token(settings.api_token_path),
        presence=presence,
    )


def _new_seeded_stack(home: Any) -> tuple[_HttpStack, _Seed]:
    application = bootstrap_local_application(AppSettings(home=home))
    seed = _seed_sealed_run(application)
    return _build_stack(home, seed=seed, application=application), seed


def _plan_payload(
    seed: _Seed,
    *,
    predecessor: str | None,
    nonce: int,
) -> bytes:
    document = {
        "schema_version": REQUIREMENT_PLAN_EVIDENCE_FILE_VERSION,
        "session_id": seed.session_id,
        "expected_source_run_id": seed.run.run_id,
        "source_window_fingerprint": seed.run.input_fingerprint,
        "expected_predecessor_confirmation_id": predecessor,
        "registry_version": METRIC_CONTRACT_REGISTRY_VERSION_V2,
        "contract_set_fingerprint": metric_contract_v2_set_fingerprint(),
        "metric_key": REQUIREMENT_PLAN_METRIC_KEY,
        "metric_contract_fingerprint": metric_contract_v2(
            REQUIREMENT_PLAN_METRIC_KEY
        ).fingerprint,
        "source_projection_version": METRIC_PROJECTION_V2_VERSION_6,
        "clause_algorithm": "message-clause-coordinates-en-pl-v1",
        "review_rubric_version": REQUIREMENT_PLAN_REVIEW_RUBRIC_VERSION,
        "nonce": f"{nonce:064x}",
        "expires_at": (
            datetime.now(UTC) + timedelta(minutes=30)
        ).isoformat().replace("+00:00", "Z"),
        "producer": {
            "kind": "local_coding_agent",
            "producer_id": "reserved-example-agent",
            "producer_version": "1",
            "model_id": MODEL_CLAIM_CANARY,
            "authority": "untrusted_provenance_claim",
        },
        "contains_prose": False,
        "contains_scores": False,
        "contains_authoritative_model_judgment_claims": False,
        "contains_untrusted_structured_proposals": True,
        "contains_objective_receipt_claims": False,
        "complete_user_clause_classification": True,
        "requirements": [
            {
                "coordinate": {"message_sequence": 0, "clause_index": 0},
                "disposition": "linked",
                "plan_indexes": [0],
            },
            {
                "coordinate": {"message_sequence": 0, "clause_index": 1},
                "disposition": "not_linked",
                "plan_indexes": [],
            },
            {
                "coordinate": {"message_sequence": 0, "clause_index": 2},
                "disposition": "pending",
                "plan_indexes": [],
            },
        ],
        "excluded_user_clauses": [
            {
                "coordinate": {"message_sequence": 0, "clause_index": 3},
                "reason": "not_requirement",
                "basis_coordinate": None,
            }
        ],
        "plan_items": [{"message_sequence": 1, "clause_index": 0}],
    }
    return json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    ).encode("ascii")


def _confirm_plan(
    client: TestClient,
    stack: _HttpStack,
    seed: _Seed,
    *,
    predecessor: str | None = None,
    nonce: int = 1,
) -> tuple[dict[str, object], tuple[Any, ...]]:
    base = f"/v1/sessions/{seed.session_id}/requirement-plan-evidence"
    payload = _plan_payload(seed, predecessor=predecessor, nonce=nonce)
    digest = hashlib.sha256(payload).hexdigest()
    suffix = f"{nonce:04d}"
    imported = client.post(
        f"{base}/import",
        headers={
            API_TOKEN_HEADER: stack.token,
            "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
            "Idempotency-Key": f"synthetic-plan-import-{suffix}",
            "X-Requirement-Plan-Payload-SHA256": digest,
            "X-Requirement-Plan-Confirmation": (
                REQUIREMENT_PLAN_IMPORT_CONFIRMATION
            ),
        },
        content=payload,
    )
    assert imported.status_code == 201, imported.text
    proposal = imported.json()["proposal"]
    browser = client.get("/auth/session").json()
    review_path = f"{base}/proposals/{proposal['proposal_id']}/review"
    reviewed = _native_post(
        client,
        stack.presence,
        path=review_path,
        payload={
            "expected_source_run_id": seed.run.run_id,
            "confirmation": REQUIREMENT_PLAN_REVIEW_CONFIRMATION,
        },
        csrf_token=browser["csrf_token"],
    )
    assert reviewed.status_code == 200, reviewed.text
    review = reviewed.json()
    decision_path = f"{base}/proposals/{proposal['proposal_id']}/decision"
    command = RequirementPlanDecisionCommand(
        expected_source_run_id=seed.run.run_id,
        decision=RequirementPlanDecisionKind.CONFIRM,
        confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        review_receipt_id=review["review_receipt_id"],
        manifest_fingerprint=review["manifest_fingerprint"],
        reviewed_graph_fingerprint=review["reviewed_graph_fingerprint"],
        reviewed_candidate_set_fingerprint=(
            review["reviewed_candidate_set_fingerprint"]
        ),
        complete_review_acknowledged=True,
    )
    decided = _native_post(
        client,
        stack.presence,
        path=decision_path,
        payload=command.model_dump(mode="json"),
        csrf_token=browser["csrf_token"],
        idempotency_key=f"synthetic-plan-decision-{suffix}",
    )
    assert decided.status_code == 201, decided.text
    for response in (imported, reviewed, decided):
        _assert_private(response)
    return decided.json()["proposal"], (imported, reviewed, decided)


def _verification_base(session_id: str) -> str:
    return f"/v1/sessions/{session_id}/requirement-verification-evidence"


def _issue_opportunities(
    client: TestClient, stack: _HttpStack, session_id: str
) -> Any:
    response = client.post(
        f"{_verification_base(session_id)}/opportunity-sets/current",
        headers={API_TOKEN_HEADER: stack.token},
    )
    _assert_private(response)
    return response


def _opportunity_set(snapshot: dict[str, object]) -> AppIssuedRequirementVerificationOpportunitySet:
    return AppIssuedRequirementVerificationOpportunitySet.model_validate(
        snapshot["evidence"]["opportunities"]  # type: ignore[index]
    )


def _result_command(
    stack: _HttpStack,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    *,
    ordinal: int,
    observed_sequence: int,
    outcome: RequirementVerificationOutcome,
    predecessor: str | None = None,
) -> RequirementVerificationResultAppendCommand:
    result = issue_requirement_verification_result(
        opportunities,
        opportunity_id=opportunities.opportunities[ordinal].opportunity_id,
        observed_sequence=observed_sequence,
        method=RequirementVerificationMethod.TEST,
        outcome=outcome,
        receipt_reference_ids=(f"{observed_sequence + 1000:064x}",),
        identifiers=LocalArtifactIdFactory(stack.application.pseudonymizer),
    )
    return RequirementVerificationResultAppendCommand(
        result=result,
        expected_predecessor_authority_id=predecessor,
    )


def _append_result(
    client: TestClient,
    stack: _HttpStack,
    session_id: str,
    command: RequirementVerificationResultAppendCommand,
    *,
    key: str,
):  # type: ignore[no-untyped-def]
    response = client.post(
        f"{_verification_base(session_id)}/objective-results",
        headers={API_TOKEN_HEADER: stack.token, "Idempotency-Key": key},
        json=command.model_dump(mode="json"),
    )
    _assert_private(response)
    return response


def _append_acceptance(
    client: TestClient,
    stack: _HttpStack,
    session_id: str,
    opportunities: AppIssuedRequirementVerificationOpportunitySet,
    *,
    ordinal: int,
    outcome: RequirementAcceptanceOutcome,
    key: str,
    predecessor: str | None = None,
):  # type: ignore[no-untyped-def]
    path = f"{_verification_base(session_id)}/acceptances"
    browser = client.get("/auth/session").json()
    command = RequirementAcceptanceAppendCommand(
        opportunity_set_fingerprint=opportunities.opportunity_set_fingerprint,
        opportunity_id=opportunities.opportunities[ordinal].opportunity_id,
        expected_predecessor_authority_id=predecessor,
        outcome=outcome,
        confirmation=REQUIREMENT_ACCEPTANCE_APPEND_CONFIRMATION,
    )
    response = _native_post(
        client,
        stack.presence,
        path=path,
        payload=command.model_dump(mode="json"),
        csrf_token=browser["csrf_token"],
        idempotency_key=key,
    )
    _assert_private(response)
    return response


def _assert_frozen_operability(client: TestClient, token: str) -> None:
    response = client.get(
        "/v1/metric-contracts/v2/operability-catalog",
        headers={API_TOKEN_HEADER: token},
    )
    assert response.status_code == 200, response.text
    catalog = response.json()
    assert (
        catalog["total_metric_count"],
        catalog["shipped_path_count"],
        catalog["task_profile_configuration_gap_count"],
        catalog["provider_adapter_gap_count"],
        catalog["model_authoritative_metric_count"],
    ) == (20, 16, 0, 4, 0)
    verified = next(
        item
        for item in catalog["entries"]
        if item["metric_key"] == "outcome.verified_requirement_coverage"
    )
    assert verified["shipped_path_state"] == "provider_adapter_required"
    assert verified["next_step_code"] == "add_objective_opportunity_link_adapter"
    assert verified["measured_value_may_use_model_output"] is False


def test_review_to_owned_native_evidence_restart_replay_and_privacy(tmp_path) -> None:
    stack, seed = _new_seeded_stack(tmp_path)
    responses: list[Any] = []
    base = _verification_base(seed.session_id)
    with TestClient(stack.app, base_url=BASE_URL) as client:
        confirmed, plan_responses = _confirm_plan(client, stack, seed)
        # The owned-native review is the one intentional ephemeral raw-content
        # surface.  Import/decision and every verification response stay
        # content-free, and the canary must never reach SQLite.
        assert PRIVATE_CANARY in plan_responses[1].text
        responses.extend((plan_responses[0], plan_responses[2]))
        issued = _issue_opportunities(client, stack, seed.session_id)
        responses.append(issued)
        assert issued.status_code == 201
        assert issued.json()["applied"] is True
        issued_snapshot = issued.json()["snapshot"]
        opportunities = _opportunity_set(issued_snapshot)
        assert len(opportunities.opportunities) == 3
        assert tuple(item.requirement_index for item in opportunities.opportunities) == (
            0,
            1,
            2,
        )
        assert opportunities.requirement_plan_confirmation_id == confirmed["decision_id"]
        assert opportunities.local_only is True
        assert opportunities.content_persisted is False

        issued_replay = _issue_opportunities(client, stack, seed.session_id)
        responses.append(issued_replay)
        assert issued_replay.status_code == 200
        assert issued_replay.json() == {
            "snapshot": issued_snapshot,
            "applied": False,
        }

        first = _result_command(
            stack,
            opportunities,
            ordinal=0,
            observed_sequence=1,
            outcome=RequirementVerificationOutcome.PASSED,
        )
        appended = _append_result(
            client,
            stack,
            seed.session_id,
            first,
            key="synthetic-objective-result-0001",
        )
        responses.append(appended)
        assert appended.status_code == 201
        assert appended.json()["applied"] is True
        assert appended.json()["snapshot"]["revision"] == 1

        replay = _append_result(
            client,
            stack,
            seed.session_id,
            first,
            key="synthetic-objective-result-0001",
        )
        responses.append(replay)
        assert replay.status_code == 200
        assert replay.json()["applied"] is False
        assert replay.json()["snapshot"] == appended.json()["snapshot"]

        conflicting_command = _result_command(
            stack,
            opportunities,
            ordinal=1,
            observed_sequence=2,
            outcome=RequirementVerificationOutcome.FAILED,
        )
        conflicting_reuse = _append_result(
            client,
            stack,
            seed.session_id,
            conflicting_command,
            key="synthetic-objective-result-0001",
        )
        responses.append(conflicting_reuse)
        assert conflicting_reuse.status_code == 409
        assert conflicting_reuse.json()["detail"]["code"] == (
            "requirement_verification_evidence_conflict"
        )

        accepted = _append_acceptance(
            client,
            stack,
            seed.session_id,
            opportunities,
            ordinal=1,
            outcome=RequirementAcceptanceOutcome.ACCEPTED,
            key="synthetic-native-acceptance-0001",
        )
        responses.append(accepted)
        assert accepted.status_code == 201
        assert accepted.json()["snapshot"]["revision"] == 2

        final_result = _result_command(
            stack,
            opportunities,
            ordinal=2,
            observed_sequence=3,
            outcome=RequirementVerificationOutcome.FAILED,
        )
        completed = _append_result(
            client,
            stack,
            seed.session_id,
            final_result,
            key="synthetic-objective-result-0002",
        )
        responses.append(completed)
        assert completed.status_code == 201
        completed_snapshot = completed.json()["snapshot"]
        assert completed_snapshot["revision"] == 3
        assert len(completed_snapshot["authority_heads"]) == 3
        assert len(completed_snapshot["evidence"]["verification_results"]) == 2
        assert len(completed_snapshot["evidence"]["acceptance_authorities"]) == 1
        assert completed_snapshot["local_only"] is True
        assert completed_snapshot["content_persisted"] is False
        _assert_frozen_operability(client, stack.token)

    restarted = _build_stack(tmp_path)
    with TestClient(restarted.app, base_url=BASE_URL) as client:
        after_restart = client.get(
            f"{base}/opportunity-sets/{opportunities.opportunity_set_fingerprint}",
            headers={API_TOKEN_HEADER: restarted.token},
        )
        _assert_private(after_restart)
        assert after_restart.status_code == 200
        assert after_restart.json() == completed_snapshot
        _assert_frozen_operability(client, restarted.token)

    rendered = "\n".join(response.text for response in (*responses, after_restart))
    assert PRIVATE_CANARY not in rendered
    assert MODEL_CLAIM_CANARY not in rendered
    database_path = restarted.application.database.path
    sqlite_artifacts = (
        database_path,
        database_path.with_name(f"{database_path.name}-wal"),
        database_path.with_name(f"{database_path.name}-shm"),
    )
    for sqlite_artifact in sqlite_artifacts:
        if not sqlite_artifact.exists():
            continue
        database_bytes = sqlite_artifact.read_bytes()
        assert PRIVATE_CANARY.encode("ascii") not in database_bytes
        assert MODEL_CLAIM_CANARY.encode("ascii") not in database_bytes
    with sqlite3.connect(restarted.application.database.path) as connection:
        for table in VERIFICATION_TABLES:
            columns = tuple(
                str(row[1]).casefold()
                for row in connection.execute(f"PRAGMA table_info({table})")
            )
            assert columns, table
            for column in columns:
                assert not any(
                    forbidden in column
                    for forbidden in (
                        "prompt",
                        "transcript",
                        "excerpt",
                        "prose",
                        "payload",
                        "model_id",
                        "raw_content",
                        "file_path",
                    )
                ), (table, column)


def test_incomplete_and_unknown_authority_remain_distinct_without_live_promotion(
    tmp_path,
) -> None:
    stack, seed = _new_seeded_stack(tmp_path)
    with TestClient(stack.app, base_url=BASE_URL) as client:
        _confirm_plan(client, stack, seed)
        issued = _issue_opportunities(client, stack, seed.session_id)
        opportunities = _opportunity_set(issued.json()["snapshot"])
        passed = _append_result(
            client,
            stack,
            seed.session_id,
            _result_command(
                stack,
                opportunities,
                ordinal=0,
                observed_sequence=10,
                outcome=RequirementVerificationOutcome.PASSED,
            ),
            key="synthetic-incomplete-result-0001",
        )
        assert passed.status_code == 201
        unknown = _append_acceptance(
            client,
            stack,
            seed.session_id,
            opportunities,
            ordinal=1,
            outcome=RequirementAcceptanceOutcome.UNKNOWN,
            key="synthetic-incomplete-native-0001",
        )
        assert unknown.status_code == 201
        snapshot = unknown.json()["snapshot"]
        assert snapshot["revision"] == 2
        assert len(snapshot["evidence"]["opportunities"]["opportunities"]) == 3
        assert len(snapshot["authority_heads"]) == 2
        assert [
            item["outcome"]
            for item in snapshot["evidence"]["verification_results"]
        ] == ["passed"]
        assert [
            item["outcome"]
            for item in snapshot["evidence"]["acceptance_authorities"]
        ] == ["unknown"]
        resolved_ids = {
            item["opportunity_id"] for item in snapshot["authority_heads"]
        }
        assert opportunities.opportunities[2].opportunity_id not in resolved_ids
        serialized = json.dumps(snapshot, sort_keys=True)
        for forbidden_numeric_claim in (
            "numeric_value",
            "numerator",
            "denominator",
            "composite_score",
        ):
            assert forbidden_numeric_claim not in serialized
        _assert_frozen_operability(client, stack.token)

    restarted = _build_stack(tmp_path)
    with TestClient(restarted.app, base_url=BASE_URL) as client:
        durable = client.get(
            f"{_verification_base(seed.session_id)}/opportunity-sets/"
            f"{opportunities.opportunity_set_fingerprint}",
            headers={API_TOKEN_HEADER: restarted.token},
        )
        _assert_private(durable)
        assert durable.status_code == 200
        assert durable.json() == snapshot
        _assert_frozen_operability(client, restarted.token)


def test_stale_foreign_tampered_missing_duplicate_and_model_claims_fail_closed(
    tmp_path,
) -> None:
    stack, seed = _new_seeded_stack(tmp_path)
    base = _verification_base(seed.session_id)
    with TestClient(stack.app, base_url=BASE_URL) as client:
        first_plan, _ = _confirm_plan(client, stack, seed, nonce=1)
        issued_a = _issue_opportunities(client, stack, seed.session_id)
        opportunities_a = _opportunity_set(issued_a.json()["snapshot"])

        valid = _result_command(
            stack,
            opportunities_a,
            ordinal=0,
            observed_sequence=20,
            outcome=RequirementVerificationOutcome.PASSED,
        )
        valid_json = valid.model_dump(mode="json")
        attacks = (
            (
                "missing",
                {"expected_predecessor_authority_id": None},
                422,
            ),
            (
                "tampered-fingerprint",
                {
                    **valid_json,
                    "result": {
                        **valid_json["result"],
                        "result_fingerprint": "f" * 64,
                    },
                },
                422,
            ),
            (
                "model-authored",
                {
                    **valid_json,
                    "result": {
                        **valid_json["result"],
                        "authority_kind": "assistant_completion_claim",
                        "model_claim": MODEL_CLAIM_CANARY,
                    },
                },
                422,
            ),
            (
                "foreign-set",
                {
                    **valid_json,
                    "result": {
                        **valid_json["result"],
                        "opportunity_set_fingerprint": "f" * 64,
                    },
                },
                404,
            ),
        )
        for label, payload, expected_status in attacks:
            attacked = client.post(
                f"{base}/objective-results",
                headers={
                    API_TOKEN_HEADER: stack.token,
                    "Idempotency-Key": f"synthetic-attack-{label}-0001",
                },
                json=payload,
            )
            _assert_private(attacked)
            assert attacked.status_code == expected_status, (label, attacked.text)
            assert MODEL_CLAIM_CANARY not in attacked.text

        appended = _append_result(
            client,
            stack,
            seed.session_id,
            valid,
            key="synthetic-valid-before-tamper-0001",
        )
        assert appended.status_code == 201
        duplicate = _append_result(
            client,
            stack,
            seed.session_id,
            valid,
            key="synthetic-duplicate-authority-0001",
        )
        assert duplicate.status_code == 409

        with sqlite3.connect(stack.application.database.path) as connection:
            with pytest.raises(sqlite3.IntegrityError, match="immutable"):
                connection.execute(
                    """UPDATE requirement_verification_authority_records
                       SET verification_outcome='failed'
                       WHERE authority_record_id=?""",
                    (valid.result.result_id,),
                )

        unchanged = client.get(
            f"{base}/opportunity-sets/"
            f"{opportunities_a.opportunity_set_fingerprint}",
            headers={API_TOKEN_HEADER: stack.token},
        )
        _assert_private(unchanged)
        assert unchanged.status_code == 200
        assert unchanged.json() == appended.json()["snapshot"]

        second_plan, _ = _confirm_plan(
            client,
            stack,
            seed,
            predecessor=str(first_plan["decision_id"]),
            nonce=2,
        )
        assert second_plan["decision_id"] != first_plan["decision_id"]
        delayed_a = _append_result(
            client,
            stack,
            seed.session_id,
            _result_command(
                stack,
                opportunities_a,
                ordinal=1,
                observed_sequence=21,
                outcome=RequirementVerificationOutcome.FAILED,
            ),
            key="synthetic-stale-a-result-0001",
        )
        assert delayed_a.status_code == 409
        assert delayed_a.json()["detail"]["code"] == (
            "requirement_verification_source_window_stale"
        )

        issued_b = _issue_opportunities(client, stack, seed.session_id)
        assert issued_b.status_code == 201
        opportunities_b = _opportunity_set(issued_b.json()["snapshot"])
        assert opportunities_b.opportunity_set_fingerprint != (
            opportunities_a.opportunity_set_fingerprint
        )
        foreign_session = "f" * 64
        foreign = client.get(
            f"{_verification_base(foreign_session)}/opportunity-sets/"
            f"{opportunities_b.opportunity_set_fingerprint}",
            headers={API_TOKEN_HEADER: stack.token},
        )
        _assert_private(foreign)
        assert foreign.status_code == 404
        assert foreign.json()["detail"]["code"] == (
            "requirement_verification_evidence_not_found"
        )


def test_concurrent_result_replay_and_conflicts_are_linearizable_after_restart(
    tmp_path,
) -> None:
    initial, seed = _new_seeded_stack(tmp_path)
    with TestClient(initial.app, base_url=BASE_URL) as client:
        _confirm_plan(client, initial, seed)
        issued = _issue_opportunities(client, initial, seed.session_id)
        opportunities = _opportunity_set(issued.json()["snapshot"])

    stacks = (_build_stack(tmp_path), _build_stack(tmp_path))
    exact_commands = tuple(
        _result_command(
            stack,
            opportunities,
            ordinal=0,
            observed_sequence=30,
            outcome=RequirementVerificationOutcome.PASSED,
        )
        for stack in stacks
    )

    def post(
        index: int,
        command: RequirementVerificationResultAppendCommand,
        key: str,
    ) -> tuple[int, dict[str, object]]:
        stack = stacks[index]
        with TestClient(stack.app, base_url=BASE_URL) as client:
            response = _append_result(
                client,
                stack,
                seed.session_id,
                command,
                key=key,
            )
            return response.status_code, response.json()

    with ThreadPoolExecutor(max_workers=2) as executor:
        exact = tuple(
            executor.map(
                lambda item: post(
                    item[0], item[1], "synthetic-concurrent-replay-0001"
                ),
                enumerate(exact_commands),
            )
        )
    assert sorted(status for status, _body in exact) == [200, 201]
    assert sorted(body["applied"] for _status, body in exact) == [False, True]
    assert {body["snapshot"]["revision"] for _status, body in exact} == {1}

    conflicting = (
        _result_command(
            stacks[0],
            opportunities,
            ordinal=1,
            observed_sequence=31,
            outcome=RequirementVerificationOutcome.PASSED,
        ),
        _result_command(
            stacks[1],
            opportunities,
            ordinal=1,
            observed_sequence=32,
            outcome=RequirementVerificationOutcome.FAILED,
        ),
    )
    with ThreadPoolExecutor(max_workers=2) as executor:
        raced = tuple(
            executor.map(
                lambda item: post(
                    item[0], item[1], f"synthetic-concurrent-conflict-{item[0]}"
                ),
                enumerate(conflicting),
            )
        )
    assert sorted(status for status, _body in raced) == [201, 409]
    assert sum(body.get("applied") is True for _status, body in raced) == 1

    restarted = _build_stack(tmp_path)
    with TestClient(restarted.app, base_url=BASE_URL) as client:
        snapshot = client.get(
            f"{_verification_base(seed.session_id)}/opportunity-sets/"
            f"{opportunities.opportunity_set_fingerprint}",
            headers={API_TOKEN_HEADER: restarted.token},
        )
        _assert_private(snapshot)
        assert snapshot.status_code == 200
        body = snapshot.json()
        assert body["revision"] == 2
        assert len(body["authority_heads"]) == 2
        assert len(body["evidence"]["verification_results"]) == 2
    with sqlite3.connect(restarted.application.database.path) as connection:
        count = connection.execute(
            "SELECT COUNT(*) FROM requirement_verification_authority_records"
        ).fetchone()[0]
        assert count == 2
