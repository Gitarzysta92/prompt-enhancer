from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
import json

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.analysis.requirement_plan_evidence import (
    REQUIREMENT_PLAN_DECISION_CONFIRMATION,
    REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    RequirementPlanDecisionCommand,
    RequirementPlanDecisionKind,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.browser_session import CSRF_HEADER
from prompt_enhancer.interfaces.http.requirement_plan_evidence_routes import (
    REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
)

from test_requirement_plan_evidence_persistence import _payload, _setup


TOKEN = "example_requirement_plan_api_token_do_not_use_123456789"


def _confirm_command(run_id: str, review: dict[str, object]) -> dict[str, object]:
    return RequirementPlanDecisionCommand(
        expected_source_run_id=run_id,
        decision=RequirementPlanDecisionKind.CONFIRM,
        confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
        review_receipt_id=str(review["review_receipt_id"]),
        manifest_fingerprint=str(review["manifest_fingerprint"]),
        reviewed_graph_fingerprint=str(review["reviewed_graph_fingerprint"]),
        reviewed_candidate_set_fingerprint=str(
            review["reviewed_candidate_set_fingerprint"]
        ),
        complete_review_acknowledged=True,
    ).model_dump(mode="json")


def _trusted_user_presence(_request, _body: bytes) -> None:
    """Synthetic native presence adapter; never a production credential."""


def _app(tmp_path, *, presence: bool = True):  # type: ignore[no-untyped-def]
    database, session_id, run, _repository, service = _setup(tmp_path)
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=database,
        api_token=TOKEN,
        requirement_plan_evidence_service=service,
        user_presence_confirmation=(
            _trusted_user_presence if presence else None
        ),
    )
    document = json.loads(_payload(session_id, run))
    document["expires_at"] = (
        datetime.now(UTC) + timedelta(minutes=30)
    ).isoformat().replace("+00:00", "Z")
    payload = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("ascii")
    return app, session_id, run, payload


def _private(response) -> None:  # type: ignore[no-untyped-def]
    assert response.headers["cache-control"] == "no-store, private", (
        response.request.method,
        response.request.url,
        response.status_code,
        response.text,
    )
    assert response.headers["pragma"] == "no-cache"


def test_agent_file_is_inert_until_native_confirmed_then_paged(tmp_path) -> None:
    app, session_id, run, payload = _app(tmp_path)
    base = f"/v1/sessions/{session_id}/requirement-plan-evidence"
    file_headers = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
    }
    digest = hashlib.sha256(payload).hexdigest()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        unauthorized = client.get(f"{base}/contract")
        contract = client.get(
            f"{base}/contract", headers={API_TOKEN_HEADER: TOKEN}
        )
        preview = client.post(f"{base}/preview", headers=file_headers, content=payload)
        imported = client.post(
            f"{base}/import",
            headers={
                **file_headers,
                "Idempotency-Key": "requirement-plan-import-example-0001",
                "X-Requirement-Plan-Payload-SHA256": digest,
                "X-Requirement-Plan-Confirmation": (
                    REQUIREMENT_PLAN_IMPORT_CONFIRMATION
                ),
            },
            content=payload,
        )
        proposal = imported.json()["proposal"]
        before = client.get(
            f"{base}/proposal-page?limit=1&offset=0",
            headers={API_TOKEN_HEADER: TOKEN},
        )
        token_decision = client.post(
            f"{base}/proposals/{proposal['proposal_id']}/decision",
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Idempotency-Key": "requirement-plan-token-decision-denied",
            },
            json=RequirementPlanDecisionCommand(
                expected_source_run_id=run.run_id,
                decision=RequirementPlanDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
                review_receipt_id="1" * 64,
                manifest_fingerprint="2" * 64,
                reviewed_graph_fingerprint="3" * 64,
                reviewed_candidate_set_fingerprint="4" * 64,
                complete_review_acknowledged=True,
            ).model_dump(mode="json"),
        )
        browser = client.get("/auth/session")
        review = client.post(
            f"{base}/proposals/{proposal['proposal_id']}/review",
            headers={
                CSRF_HEADER: browser.json()["csrf_token"],
                "Origin": "http://127.0.0.1",
            },
            json={
                "expected_source_run_id": run.run_id,
                "confirmation": "open_exact_local_requirement_plan_clause_review",
            },
        )
        decided = client.post(
            f"{base}/proposals/{proposal['proposal_id']}/decision",
            headers={
                "Idempotency-Key": "requirement-plan-native-decision-example",
                CSRF_HEADER: browser.json()["csrf_token"],
                "Origin": "http://127.0.0.1",
            },
            json=_confirm_command(run.run_id, review.json()),
        )
        after = client.get(
            f"{base}/proposal-page?limit=1&offset=0",
            headers={API_TOKEN_HEADER: TOKEN},
        )

    assert unauthorized.status_code == 401
    for response in (
        contract, preview, imported, before, token_decision, review, decided, after
    ):
        _private(response)
    assert contract.status_code == 200
    assert contract.json()["expected_source_run_id"] == run.run_id
    assert contract.json()["source_projection_version"].endswith("-6")
    assert contract.json()["prose_allowed"] is False
    assert contract.json()["scores_allowed"] is False
    assert contract.json()["native_confirmation_required_for_metric_authority"] is True
    assert preview.status_code == 200
    assert preview.json()["payload_sha256"] == digest
    assert preview.json()["can_set_numeric_metric_on_import"] is False
    assert imported.status_code == 201
    assert imported.json()["proposal"]["status"] == "proposed"
    assert imported.json()["raw_payload_persisted"] is False
    assert before.json()["proposals"][0]["status"] == "proposed"
    assert before.json()["complete"] is True
    assert token_decision.status_code == 403
    assert review.status_code == 200
    assert review.json()["raw_text_persisted"] is False
    assert any(
        item["included_in_proposal"] is False
        for item in review.json()["candidate_clauses"]
    )
    assert decided.status_code == 201
    assert decided.json()["proposal"]["status"] == "confirmed"
    assert after.json()["proposals"][0] == decided.json()["proposal"]
    serialized = after.text.casefold()
    for prohibited in ("prompt", "transcript", "excerpt", "file_path", "score"):
        assert prohibited not in serialized


def test_self_bootstrapped_browser_cannot_authorize_requirement_plan(tmp_path) -> None:
    app, session_id, run, payload = _app(tmp_path, presence=False)
    base = f"/v1/sessions/{session_id}/requirement-plan-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    with TestClient(app, base_url="http://127.0.0.1") as client:
        imported = client.post(
            f"{base}/import",
            headers={
                API_TOKEN_HEADER: TOKEN,
                "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
                "Idempotency-Key": "requirement-plan-import-example-0002",
                "X-Requirement-Plan-Payload-SHA256": digest,
                "X-Requirement-Plan-Confirmation": (
                    REQUIREMENT_PLAN_IMPORT_CONFIRMATION
                ),
            },
            content=payload,
        )
        browser = client.get("/auth/session")
        unavailable_review = client.post(
            f"{base}/proposals/{imported.json()['proposal']['proposal_id']}/review",
            headers={
                CSRF_HEADER: browser.json()["csrf_token"],
                "Origin": "http://127.0.0.1",
            },
            json={
                "expected_source_run_id": run.run_id,
                "confirmation": "open_exact_local_requirement_plan_clause_review",
            },
        )
        attacked = client.post(
            f"{base}/proposals/{imported.json()['proposal']['proposal_id']}/decision",
            headers={
                "Idempotency-Key": "requirement-plan-self-issued-decision",
                CSRF_HEADER: browser.json()["csrf_token"],
                "Origin": "http://127.0.0.1",
            },
            json=RequirementPlanDecisionCommand(
                expected_source_run_id=run.run_id,
                decision=RequirementPlanDecisionKind.CONFIRM,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
                review_receipt_id="1" * 64,
                manifest_fingerprint="2" * 64,
                reviewed_graph_fingerprint="3" * 64,
                reviewed_candidate_set_fingerprint="4" * 64,
                complete_review_acknowledged=True,
            ).model_dump(mode="json"),
        )
        page = client.get(
            f"{base}/proposal-page", headers={API_TOKEN_HEADER: TOKEN}
        )
    assert attacked.status_code == 503
    assert unavailable_review.status_code == 503
    assert page.json()["proposals"][0]["status"] == "proposed"
    _private(attacked)


def test_proposal_page_uses_exact_signed_snapshot_pagination(tmp_path) -> None:
    app, session_id, _run, payload = _app(tmp_path)
    base = f"/v1/sessions/{session_id}/requirement-plan-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    headers = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
        "X-Requirement-Plan-Payload-SHA256": digest,
        "X-Requirement-Plan-Confirmation": REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for index in range(3):
            imported = client.post(
                f"{base}/import",
                headers={
                    **headers,
                    "Idempotency-Key": f"requirement-plan-page-import-{index}",
                },
                content=payload,
            )
            assert imported.status_code == 201
        first = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={"limit": 2, "offset": 0},
        )
        first_body = first.json()
        snapshot = first_body["snapshot"]
        snapshot_params = {
            "snapshot_id": snapshot["snapshot_id"],
            "snapshot_total": snapshot["total"],
            "snapshot_decision_count": snapshot["decision_count"],
            "snapshot_high_water_created_at": snapshot[
                "high_water_created_at"
            ],
            "snapshot_high_water_proposal_id": snapshot[
                "high_water_proposal_id"
            ],
        }
        second = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={
                "limit": 2,
                "offset": 2,
                **snapshot_params,
            },
        )
        missing_snapshot = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={"limit": 2, "offset": 2},
        )
        forged_snapshot = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={
                "limit": 2,
                "offset": 2,
                **snapshot_params,
                "snapshot_total": snapshot["total"] + 1,
            },
        )

    for response in (first, second, missing_snapshot, forged_snapshot):
        _private(response)
    assert first.status_code == 200
    assert first_body["total"] == 3
    assert len(first_body["proposals"]) == 2
    assert first_body["next_offset"] == 2
    assert first_body["complete"] is False
    assert snapshot["total"] == 3
    second_body = second.json()
    assert second.status_code == 200
    assert second_body["snapshot"] == snapshot
    assert second_body["total"] == 3
    assert len(second_body["proposals"]) == 1
    assert second_body["next_offset"] is None
    assert second_body["complete"] is True
    proposal_ids = tuple(
        item["proposal_id"]
        for item in (*first_body["proposals"], *second_body["proposals"])
    )
    assert len(proposal_ids) == 3
    assert len(set(proposal_ids)) == 3
    assert missing_snapshot.status_code == 422
    assert forged_snapshot.status_code == 409


def test_decision_between_signed_proposal_pages_returns_409(tmp_path) -> None:
    app, session_id, run, payload = _app(tmp_path)
    base = f"/v1/sessions/{session_id}/requirement-plan-evidence"
    digest = hashlib.sha256(payload).hexdigest()
    headers = {
        API_TOKEN_HEADER: TOKEN,
        "Content-Type": REQUIREMENT_PLAN_EVIDENCE_MEDIA_TYPE,
        "X-Requirement-Plan-Payload-SHA256": digest,
        "X-Requirement-Plan-Confirmation": REQUIREMENT_PLAN_IMPORT_CONFIRMATION,
    }
    with TestClient(app, base_url="http://127.0.0.1") as client:
        for index in range(2):
            imported = client.post(
                f"{base}/import",
                headers={
                    **headers,
                    "Idempotency-Key": (
                        f"requirement-plan-decision-page-import-{index}"
                    ),
                },
                content=payload,
            )
            assert imported.status_code == 201
        first = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={"limit": 1, "offset": 0},
        )
        first_body = first.json()
        assert first_body["snapshot"]["decision_count"] == 0
        browser = client.get("/auth/session")
        decided = client.post(
            (
                f"{base}/proposals/"
                f"{first_body['proposals'][0]['proposal_id']}/decision"
            ),
            headers={
                "Idempotency-Key": "requirement-plan-page-reject-decision",
                CSRF_HEADER: browser.json()["csrf_token"],
                "Origin": "http://127.0.0.1",
            },
            json=RequirementPlanDecisionCommand(
                expected_source_run_id=run.run_id,
                decision=RequirementPlanDecisionKind.REJECT,
                confirmation=REQUIREMENT_PLAN_DECISION_CONFIRMATION,
            ).model_dump(mode="json"),
        )
        snapshot = first_body["snapshot"]
        stale_second_page = client.get(
            f"{base}/proposal-page",
            headers={API_TOKEN_HEADER: TOKEN},
            params={
                "limit": 1,
                "offset": 1,
                "snapshot_id": snapshot["snapshot_id"],
                "snapshot_total": snapshot["total"],
                "snapshot_decision_count": snapshot["decision_count"],
                "snapshot_high_water_created_at": snapshot[
                    "high_water_created_at"
                ],
                "snapshot_high_water_proposal_id": snapshot[
                    "high_water_proposal_id"
                ],
            },
        )

    for response in (first, decided, stale_second_page):
        _private(response)
    assert first.status_code == 200
    assert first_body["total"] == 2
    assert first_body["next_offset"] == 1
    assert first_body["complete"] is False
    assert decided.status_code == 201
    assert decided.json()["proposal"]["status"] == "rejected"
    assert stale_second_page.status_code == 409
    assert stale_second_page.json()["detail"]["code"] == (
        "requirement_plan_evidence_conflict"
    )


def test_openapi_exposes_only_content_free_requirement_plan_contract(tmp_path) -> None:
    app, _session_id, _run, _payload_bytes = _app(tmp_path)
    schema = app.openapi()
    paths = tuple(path for path in schema["paths"] if "requirement-plan-evidence" in path)
    assert paths == (
        "/v1/sessions/{session_id}/requirement-plan-evidence/contract",
        "/v1/sessions/{session_id}/requirement-plan-evidence/preview",
        "/v1/sessions/{session_id}/requirement-plan-evidence/import",
        "/v1/sessions/{session_id}/requirement-plan-evidence/proposals/{proposal_id}/review",
        "/v1/sessions/{session_id}/requirement-plan-evidence/proposals/{proposal_id}/decision",
        "/v1/sessions/{session_id}/requirement-plan-evidence/proposal-page",
    )
    serialized = str(
        {
            key: value
            for key, value in schema["components"]["schemas"].items()
            if "RequirementPlan" in key
        }
    ).casefold()
    for prohibited in ("prompt_text", "transcript", "excerpt", "file_path", "numeric_value"):
        assert prohibited not in serialized
    assert "requirementplanproposalreview" in serialized
    for endpoint in ("preview", "import"):
        operation = schema["paths"][
            f"/v1/sessions/{{session_id}}/requirement-plan-evidence/{endpoint}"
        ]["post"]
        request_body = operation["requestBody"]
        assert request_body["required"] is True
        file_schema = request_body["content"][
            "application/vnd.prompt-enhancer.requirement-plan-evidence+json"
        ]["schema"]
        assert file_schema == {
            "type": "string",
            "format": "binary",
            "maxLength": 64 * 1024,
        }
    assert "201" in schema["paths"][
        "/v1/sessions/{session_id}/requirement-plan-evidence/import"
    ]["post"]["responses"]
    assert "201" in schema["paths"][
        "/v1/sessions/{session_id}/requirement-plan-evidence/proposals/"
        "{proposal_id}/decision"
    ]["post"]["responses"]
