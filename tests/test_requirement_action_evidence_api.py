from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

from prompt_enhancer.application.analysis.evidence_contracts import (
    ActionFamily,
    ActionState,
    TypedEvidenceProvenance,
)
from prompt_enhancer.application.analysis.requirement_action_evidence import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES,
    REQUIREMENT_ACTION_DECISION_CONFIRMATION,
    REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
    REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
    ConfirmedRequirementActionLink,
    RequirementActionCandidate,
    RequirementActionCandidateManifest,
    RequirementActionConflictError,
    RequirementActionDecisionCommand,
    RequirementActionDecisionKind,
    RequirementActionDecisionRecord,
    RequirementActionEvidenceContract,
    RequirementActionEvidencePreview,
    RequirementActionProposalPageSnapshot,
    RequirementActionProposalRecord,
    RequirementActionProposalReview,
    RequirementActionProposalStatus,
    RequirementActionProposalView,
    RequirementActionRequirement,
    RequirementActionReviewCandidate,
    RequirementActionReviewRequirement,
    RequirementActionStaleWindowError,
)
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    RequirementCoordinate,
    RequirementPlanProducer,
    RequirementPlanProducerReceipt,
)
from prompt_enhancer.domain import EventKind, Provider, ToolCategory
from prompt_enhancer.interfaces.http.requirement_action_evidence_routes import (
    REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE,
    create_requirement_action_evidence_router,
)


TOKEN = "synthetic-local-api-token"
_PRIVATE_HEADERS = {"Cache-Control": "no-store, private", "Pragma": "no-cache"}
_NOW = datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def _id(number: int) -> str:
    return f"{number:064x}"


def _candidate() -> RequirementActionCandidate:
    return RequirementActionCandidate(
        candidate_index=0,
        action_id=_id(21),
        source_reference_id=_id(22),
        sequence=7,
        event_kind=EventKind.TOOL_END,
        tool_category=ToolCategory.TEST,
        occurred_at=_NOW,
        duration_ms=15,
        family=ActionFamily.COMMAND,
        state=ActionState.COMPLETED,
    )


def _provenance() -> TypedEvidenceProvenance:
    return TypedEvidenceProvenance(
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-v1",
        adapter_version="adapter-v1",
        decoder_key="synthetic-decoder",
        decoder_version="decoder-v1",
        source_schema_version="source-v1",
        extraction_complete=True,
    )


def _manifest() -> RequirementActionCandidateManifest:
    return RequirementActionCandidateManifest(
        session_id=_id(1),
        source_run_id=_id(2),
        source_window_fingerprint=_id(3),
        provenance=_provenance(),
        extraction_complete=True,
        enumeration_complete=True,
        actions=(_candidate(),),
        manifest_fingerprint=_id(4),
    )


def _requirement() -> RequirementActionRequirement:
    return RequirementActionRequirement(
        requirement_index=0,
        requirement_id=_id(31),
        coordinate=RequirementCoordinate(message_sequence=4, clause_index=0),
    )


def _proposal(proposal_number: int = 40) -> RequirementActionProposalView:
    record = RequirementActionProposalRecord(
        proposal_id=_id(proposal_number),
        session_id=_id(1),
        source_run_id=_id(2),
        source_window_fingerprint=_id(3),
        requirement_plan_confirmation_id=_id(5),
        requirement_plan_evidence_fingerprint=_id(6),
        candidate_manifest_fingerprint=_id(4),
        candidate_provenance=_provenance(),
        candidate_extraction_complete=True,
        candidate_enumeration_complete=True,
        expected_predecessor_confirmation_id=None,
        payload_sha256=_id(7),
        idempotency_key_digest=_id(8),
        command_fingerprint=_id(9),
        producer_receipt=RequirementPlanProducerReceipt(claim_fingerprint=_id(10)),
        requirements=(_requirement(),),
        candidates=(_candidate(),),
        links=(
            ConfirmedRequirementActionLink(
                requirement_id=_id(31), action_ids=(_id(21),)
            ),
        ),
        created_at=_NOW + timedelta(seconds=proposal_number),
    )
    return RequirementActionProposalView(
        proposal=record,
        status=RequirementActionProposalStatus.PROPOSED,
    )


class _Service:
    def __init__(self) -> None:
        self.proposals = [_proposal(40), _proposal(41), _proposal(42)]
        self.import_keys: set[str] = set()
        self.decision_keys: set[str] = set()
        self.preview_error: Exception | None = None

    def contract(self, session_id: str) -> RequirementActionEvidenceContract:
        assert session_id == _id(1)
        return RequirementActionEvidenceContract(
            session_id=session_id,
            expected_source_run_id=_id(2),
            source_window_fingerprint=_id(3),
            source_projection_version="metric-contract-v2-projection-7",
            requirement_plan_confirmation_id=_id(5),
            requirement_plan_evidence_fingerprint=_id(6),
            candidate_manifest=_manifest(),
            requirements=(_requirement(),),
            file_json_schema_sha256=_id(70),
            file_json_schema={"type": "object", "additionalProperties": False},
        )

    def preview(
        self, *, session_id: str, payload: bytes, now: datetime | None = None
    ) -> RequirementActionEvidencePreview:
        assert session_id == _id(1)
        if self.preview_error is not None:
            raise self.preview_error
        return RequirementActionEvidencePreview(
            payload_sha256=hashlib.sha256(payload).hexdigest(),
            session_id=session_id,
            expected_source_run_id=_id(2),
            source_window_fingerprint=_id(3),
            requirement_plan_confirmation_id=_id(5),
            requirement_plan_evidence_fingerprint=_id(6),
            candidate_manifest_fingerprint=_id(4),
            requirement_count=1,
            candidate_count=1,
            linked_requirement_count=1,
            unlinked_requirement_count=0,
            link_count=1,
            expires_at=_NOW + timedelta(hours=1),
            producer=RequirementPlanProducer(
                kind="local_coding_agent",
                producer_id="synthetic-agent",
                producer_version="agent-v1",
                model_id="synthetic-model",
                authority="untrusted_provenance_claim",
            ),
        )

    def import_file(
        self,
        *,
        session_id: str,
        payload: bytes,
        expected_payload_sha256: str,
        confirmation: str,
        idempotency_key: str,
        now: datetime | None = None,
    ) -> tuple[RequirementActionProposalView, bool]:
        assert session_id == _id(1)
        assert expected_payload_sha256 == hashlib.sha256(payload).hexdigest()
        assert confirmation == REQUIREMENT_ACTION_IMPORT_CONFIRMATION
        applied = idempotency_key not in self.import_keys
        self.import_keys.add(idempotency_key)
        return self.proposals[0], applied

    def review_proposal(
        self,
        *,
        session_id: str,
        proposal_id: str,
        expected_source_run_id: str,
    ) -> RequirementActionProposalReview:
        assert (session_id, proposal_id, expected_source_run_id) == (
            _id(1),
            _id(40),
            _id(2),
        )
        return RequirementActionProposalReview(
            proposal_id=proposal_id,
            session_id=session_id,
            source_run_id=expected_source_run_id,
            source_window_fingerprint=_id(3),
            review_receipt_id=_id(50),
            payload_sha256=_id(7),
            requirement_plan_evidence_fingerprint=_id(6),
            candidate_manifest_fingerprint=_id(4),
            reviewed_graph_fingerprint=_id(51),
            reviewed_candidate_set_fingerprint=_id(52),
            reviewed_descriptor_set_fingerprint=_id(56),
            requirements=(
                RequirementActionReviewRequirement(
                    requirement_id=_id(31),
                    coordinate=RequirementCoordinate(
                        message_sequence=4, clause_index=0
                    ),
                    text="Create the synthetic report.",
                    linked_action_ids=(_id(21),),
                ),
            ),
            candidates=(_candidate(),),
            candidate_memberships=(
                RequirementActionReviewCandidate(
                    candidate=_candidate(),
                    candidate_metadata_fingerprint_version=(
                        ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
                    ),
                    candidate_metadata_fingerprint=_id(57),
                    tool_name="synthetic_tool",
                    invocation_preview='{"target":"example-output"}',
                    result_or_effect_preview='{"status":"updated"}',
                    redactor_version="synthetic-redactor-v1",
                    linked_requirement_ids=(_id(31),),
                ),
            ),
            review_context_expires_at=_NOW + timedelta(minutes=15),
            review_receipt_expires_at=_NOW + timedelta(minutes=10),
        )

    def decide(
        self,
        *,
        session_id: str,
        proposal_id: str,
        command: RequirementActionDecisionCommand,
        idempotency_key: str,
    ) -> tuple[RequirementActionProposalView, bool]:
        assert session_id == _id(1)
        assert proposal_id == _id(40)
        applied = idempotency_key not in self.decision_keys
        self.decision_keys.add(idempotency_key)
        decision = RequirementActionDecisionRecord(
            decision_id=_id(53),
            proposal_id=proposal_id,
            session_id=session_id,
            decision=command.decision,
            idempotency_key_digest=_id(54),
            command_fingerprint=_id(55),
            reviewed_descriptor_set_fingerprint=(
                command.reviewed_descriptor_set_fingerprint
            ),
            decision_authority_fingerprint=_id(57),
            decided_at=_NOW + timedelta(minutes=1),
        )
        view = RequirementActionProposalView(
            proposal=self.proposals[0].proposal,
            decision=decision,
            status=(
                RequirementActionProposalStatus.CONFIRMED
                if command.decision is RequirementActionDecisionKind.CONFIRM
                else RequirementActionProposalStatus.REJECTED
            ),
        )
        self.proposals[0] = view
        return view, applied

    def list_page(
        self,
        session_id: str,
        *,
        limit: int,
        offset: int,
        snapshot: RequirementActionProposalPageSnapshot | None = None,
    ) -> tuple[
        tuple[RequirementActionProposalView, ...],
        RequirementActionProposalPageSnapshot,
    ]:
        assert session_id == _id(1)
        decision_count = sum(item.decision is not None for item in self.proposals)
        expected = RequirementActionProposalPageSnapshot(
            snapshot_id=_id(60 + decision_count),
            total=len(self.proposals),
            decision_count=decision_count,
            high_water_created_at=self.proposals[-1].proposal.created_at,
            high_water_proposal_id=self.proposals[-1].proposal.proposal_id,
        )
        if snapshot is not None and snapshot != expected:
            raise RequirementActionConflictError("signed page changed")
        return tuple(self.proposals[offset : offset + limit]), expected


def _require_local_auth(request: Request) -> None:
    if request.headers.get("X-Synthetic-Api-Token") == TOKEN:
        return
    if request.headers.get("X-Synthetic-Native-Presence") == "confirmed":
        return
    raise HTTPException(401, detail="local authentication required", headers=_PRIVATE_HEADERS)


def _require_user_confirmation(request: Request) -> None:
    if request.headers.get("X-Synthetic-Api-Token") == TOKEN:
        raise HTTPException(
            403,
            detail="API credentials cannot assert native user presence",
            headers=_PRIVATE_HEADERS,
        )
    if request.headers.get("X-Synthetic-Native-Presence") != "confirmed":
        raise HTTPException(
            503, detail="native user presence unavailable", headers=_PRIVATE_HEADERS
        )


def _app() -> tuple[FastAPI, _Service]:
    service = _Service()
    app = FastAPI()
    app.include_router(
        create_requirement_action_evidence_router(
            _require_local_auth, _require_user_confirmation, service
        )
    )
    return app, service


def _private(response) -> None:  # type: ignore[no-untyped-def]
    assert response.headers["cache-control"] == "no-store, private"
    assert response.headers["pragma"] == "no-cache"


def _file_headers(payload: bytes, *, key: str) -> dict[str, str]:
    return {
        "X-Synthetic-Api-Token": TOKEN,
        "Content-Type": REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE,
        "X-Requirement-Action-Payload-SHA256": hashlib.sha256(payload).hexdigest(),
        "X-Requirement-Action-Confirmation": REQUIREMENT_ACTION_IMPORT_CONFIRMATION,
        "Idempotency-Key": key,
    }


def test_contract_preview_import_and_replay_are_bounded_private_and_inert() -> None:
    app, _service = _app()
    base = f"/v1/sessions/{_id(1)}/requirement-action-evidence"
    payload = b'{"synthetic":"proposal"}'
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unauthorized = client.get(f"{base}/contract")
        contract = client.get(
            f"{base}/contract", headers={"X-Synthetic-Api-Token": TOKEN}
        )
        preview = client.post(
            f"{base}/preview",
            headers={
                "X-Synthetic-Api-Token": TOKEN,
                "Content-Type": REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE,
            },
            content=payload,
        )
        first = client.post(
            f"{base}/import",
            headers=_file_headers(payload, key="synthetic-action-import"),
            content=payload,
        )
        replay = client.post(
            f"{base}/import",
            headers=_file_headers(payload, key="synthetic-action-import"),
            content=payload,
        )

    for response in (unauthorized, contract, preview, first, replay):
        _private(response)
    assert unauthorized.status_code == 401
    assert contract.status_code == 200
    contract_body = contract.json()
    assert contract_body["candidate_manifest"]["actions"][0] == {
        "candidate_index": 0,
        "action_id": _id(21),
        "source_reference_id": _id(22),
        "sequence": 7,
        "event_kind": "tool_end",
        "tool_category": "test",
        "occurred_at": "2026-01-02T03:04:05Z",
        "duration_ms": 15,
        "family": "command",
        "state": "completed",
    }
    assert contract_body["native_confirmation_required_for_metric_authority"] is True
    assert contract_body["action_state_claims_allowed_in_file"] is False
    assert preview.status_code == 200
    assert preview.json()["payload_sha256"] == hashlib.sha256(payload).hexdigest()
    assert preview.json()["raw_producer_claim_persisted"] is False
    assert first.status_code == 201
    assert first.json()["applied"] is True
    assert first.json()["proposal"]["status"] == "proposed"
    assert first.json()["raw_payload_persisted"] is False
    assert replay.status_code == 200
    assert replay.json()["applied"] is False
    serialized = replay.text.casefold()
    for internal_or_raw in (
        "idempotency_key_digest",
        "command_fingerprint",
        "producer_id",
        "model_id",
        "synthetic-agent",
        "synthetic-model",
    ):
        assert internal_or_raw not in serialized
    receipt = replay.json()["proposal"]["producer_receipt"]
    assert receipt == {
        "kind": "local_coding_agent",
        "claim_fingerprint": _id(10),
        "authority": "untrusted_provenance_claim_commitment",
        "raw_claim_persisted": False,
    }


def test_review_and_both_decisions_require_native_presence_and_replay_exactly() -> None:
    app, _service = _app()
    base = f"/v1/sessions/{_id(1)}/requirement-action-evidence"
    review_path = f"{base}/proposals/{_id(40)}/review"
    decision_path = f"{base}/proposals/{_id(40)}/decision"
    api_headers = {"X-Synthetic-Api-Token": TOKEN}
    native_headers = {"X-Synthetic-Native-Presence": "confirmed"}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        token_review = client.post(
            review_path,
            headers=api_headers,
            json={
                "expected_source_run_id": _id(2),
                "confirmation": REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
            },
        )
        review = client.post(
            review_path,
            headers=native_headers,
            json={
                "expected_source_run_id": _id(2),
                "confirmation": REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
            },
        )
        confirm_command = RequirementActionDecisionCommand(
            expected_source_run_id=_id(2),
            decision=RequirementActionDecisionKind.CONFIRM,
            confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
            review_receipt_id=_id(50),
            reviewed_graph_fingerprint=_id(51),
            candidate_manifest_fingerprint=_id(4),
            reviewed_candidate_set_fingerprint=_id(52),
            reviewed_descriptor_set_fingerprint=_id(56),
            complete_review_acknowledged=True,
            all_requirements_and_candidates_acknowledged=True,
            all_linked_action_semantics_reviewed=True,
        ).model_dump(mode="json")
        token_confirm = client.post(
            decision_path,
            headers={**api_headers, "Idempotency-Key": "synthetic-token-confirm"},
            json=confirm_command,
        )
        confirmed = client.post(
            decision_path,
            headers={**native_headers, "Idempotency-Key": "synthetic-native-confirm"},
            json=confirm_command,
        )
        replay = client.post(
            decision_path,
            headers={**native_headers, "Idempotency-Key": "synthetic-native-confirm"},
            json=confirm_command,
        )
        token_reject = client.post(
            decision_path,
            headers={**api_headers, "Idempotency-Key": "synthetic-token-reject"},
            json=RequirementActionDecisionCommand(
                expected_source_run_id=_id(2),
                decision=RequirementActionDecisionKind.REJECT,
                confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
            ).model_dump(mode="json"),
        )
        native_reject = client.post(
            decision_path,
            headers={**native_headers, "Idempotency-Key": "synthetic-native-reject"},
            json=RequirementActionDecisionCommand(
                expected_source_run_id=_id(2),
                decision=RequirementActionDecisionKind.REJECT,
                confirmation=REQUIREMENT_ACTION_DECISION_CONFIRMATION,
            ).model_dump(mode="json"),
        )

    for response in (
        token_review,
        review,
        token_confirm,
        confirmed,
        replay,
        token_reject,
        native_reject,
    ):
        _private(response)
    assert token_review.status_code == 403
    assert token_confirm.status_code == 403
    assert token_reject.status_code == 403
    assert review.status_code == 200
    review_body = review.json()
    assert review_body["all_requirements_and_candidates_displayed"] is True
    assert review_body["requirements"][0]["text"] == (
        "Create the synthetic report."
    )
    assert review_body["candidates"] == [review_body["candidate_memberships"][0]["candidate"]]
    assert confirmed.status_code == 201
    assert confirmed.json()["proposal"]["status"] == "confirmed"
    assert confirmed.json()["proposal"]["confirmation_authority"] == (
        "owned_native_user_presence"
    )
    assert replay.status_code == 200
    assert replay.json()["applied"] is False
    assert native_reject.status_code == 201
    assert native_reject.json()["proposal"]["status"] == "rejected"


def test_media_type_size_strict_dto_and_stale_errors_fail_closed() -> None:
    app, service = _app()
    base = f"/v1/sessions/{_id(1)}/requirement-action-evidence"
    with TestClient(app, base_url="http://127.0.0.1") as client:
        wrong_type = client.post(
            f"{base}/preview",
            headers={
                "X-Synthetic-Api-Token": TOKEN,
                "Content-Type": "application/json",
            },
            content=b"{}",
        )
        oversized = client.post(
            f"{base}/preview",
            headers={
                "X-Synthetic-Api-Token": TOKEN,
                "Content-Type": REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE,
            },
            content=b"x" * (MAX_REQUIREMENT_ACTION_EVIDENCE_BYTES + 1),
        )
        strict_review = client.post(
            f"{base}/proposals/{_id(40)}/review",
            headers={"X-Synthetic-Native-Presence": "confirmed"},
            json={
                "expected_source_run_id": _id(2),
                "confirmation": REQUIREMENT_ACTION_REVIEW_CONFIRMATION,
                "unexpected": True,
            },
        )
        service.preview_error = RequirementActionStaleWindowError(
            "synthetic sealed window changed"
        )
        stale = client.post(
            f"{base}/preview",
            headers={
                "X-Synthetic-Api-Token": TOKEN,
                "Content-Type": REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE,
            },
            content=b"{}",
        )

    for response in (wrong_type, oversized, stale):
        _private(response)
    assert wrong_type.status_code == 415
    assert wrong_type.json()["detail"]["code"] == (
        "requirement_action_evidence_media_type_required"
    )
    assert oversized.status_code == 413
    assert oversized.json()["detail"]["code"] == (
        "requirement_action_evidence_too_large"
    )
    assert strict_review.status_code == 422
    assert stale.status_code == 409
    assert stale.json()["detail"]["code"] == "requirement_action_source_window_stale"


def test_proposal_page_carries_and_enforces_every_signed_snapshot_field() -> None:
    app, service = _app()
    base = f"/v1/sessions/{_id(1)}/requirement-action-evidence/proposal-page"
    headers = {"X-Synthetic-Api-Token": TOKEN}
    with TestClient(app, base_url="http://127.0.0.1") as client:
        first = client.get(base, headers=headers, params={"limit": 2, "offset": 0})
        snapshot = first.json()["snapshot"]
        signed = {
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_total": snapshot["total"],
            "snapshot_decision_count": snapshot["decision_count"],
            "snapshot_high_water_created_at": snapshot["high_water_created_at"],
            "snapshot_high_water_proposal_id": snapshot[
                "high_water_proposal_id"
            ],
        }
        second = client.get(
            base, headers=headers, params={"limit": 2, "offset": 2, **signed}
        )
        missing = client.get(
            base, headers=headers, params={"limit": 2, "offset": 2}
        )
        forged = client.get(
            base,
            headers=headers,
            params={
                "limit": 2,
                "offset": 2,
                **signed,
                "snapshot_decision_count": snapshot["decision_count"] + 1,
            },
        )
        service.proposals[0] = RequirementActionProposalView(
            proposal=service.proposals[0].proposal,
            decision=RequirementActionDecisionRecord(
                decision_id=_id(80),
                proposal_id=_id(40),
                session_id=_id(1),
                decision=RequirementActionDecisionKind.REJECT,
                idempotency_key_digest=_id(81),
                command_fingerprint=_id(82),
                decision_authority_fingerprint=_id(83),
                decided_at=_NOW + timedelta(minutes=2),
            ),
            status=RequirementActionProposalStatus.REJECTED,
        )
        decision_stale = client.get(
            base, headers=headers, params={"limit": 2, "offset": 2, **signed}
        )

    for response in (first, second, missing, forged, decision_stale):
        _private(response)
    assert first.status_code == 200
    assert first.json()["total"] == 3
    assert first.json()["next_offset"] == 2
    assert first.json()["complete"] is False
    assert second.status_code == 200
    assert second.json()["snapshot"] == snapshot
    assert second.json()["next_offset"] is None
    assert second.json()["complete"] is True
    assert missing.status_code == 422
    assert forged.status_code == 409
    assert decision_stale.status_code == 409


def test_openapi_exposes_bounded_vendor_files_and_complete_r7_wire() -> None:
    app, _service = _app()
    schema = app.openapi()
    paths = tuple(
        path for path in schema["paths"] if "requirement-action-evidence" in path
    )
    assert paths == (
        "/v1/sessions/{session_id}/requirement-action-evidence/contract",
        "/v1/sessions/{session_id}/requirement-action-evidence/preview",
        "/v1/sessions/{session_id}/requirement-action-evidence/import",
        "/v1/sessions/{session_id}/requirement-action-evidence/proposals/{proposal_id}/review",
        "/v1/sessions/{session_id}/requirement-action-evidence/proposals/{proposal_id}/decision",
        "/v1/sessions/{session_id}/requirement-action-evidence/proposal-page",
    )
    for endpoint in ("preview", "import"):
        body = schema["paths"][
            f"/v1/sessions/{{session_id}}/requirement-action-evidence/{endpoint}"
        ]["post"]["requestBody"]
        assert body["required"] is True
        assert body["content"][REQUIREMENT_ACTION_EVIDENCE_MEDIA_TYPE]["schema"] == {
            "type": "string",
            "format": "binary",
            "maxLength": 64 * 1024,
        }
    assert "201" in schema["paths"][
        "/v1/sessions/{session_id}/requirement-action-evidence/import"
    ]["post"]["responses"]
    assert "201" in schema["paths"][
        "/v1/sessions/{session_id}/requirement-action-evidence/proposals/"
        "{proposal_id}/decision"
    ]["post"]["responses"]
    proposal_schema = schema["components"]["schemas"]["RequirementActionProposalDto"]
    serialized = str(proposal_schema).casefold()
    for prohibited in (
        "idempotency_key_digest",
        "command_fingerprint",
        "producer_id",
        "model_id",
        "transcript",
        "file_path",
        "objective_proof",
        "metric_value",
    ):
        assert prohibited not in serialized
    assert "producer_receipt" in serialized
    assert "candidate_manifest_fingerprint" in serialized
