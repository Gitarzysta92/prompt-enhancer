from __future__ import annotations

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.discovery import (
    AcceptCandidate,
    CandidateNotFoundError,
    InvalidTaskReviewError,
    MergeCandidates,
    RejectCandidate,
    SplitCandidate,
    StaleCandidateError,
    TaskReviewResult,
)
from prompt_enhancer.application.persistence import DecisionAction
from prompt_enhancer.config import AppSettings
from prompt_enhancer.interfaces.http.review_routes import IDEMPOTENCY_HEADER


EXAMPLE_TOKEN = "example_task_review_token_do_not_use_123456789"
CANDIDATE_A = "a" * 64
CANDIDATE_B = "b" * 64
SESSION_A = "c" * 64
SESSION_B = "d" * 64
DECISION_ID = "e" * 64
TASK_ID = "f" * 64


class MinimalStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self):
        return []

    def list_sessions(self, *, limit: int = 100, offset: int = 0):
        return []

    def get_session_metrics(self, session_id: str):
        return []


class MemoryReviewService:
    def __init__(self) -> None:
        self.calls: list[tuple[object, str]] = []
        self.keys: set[str] = set()
        self.failure: Exception | None = None

    def apply(self, command, *, idempotency_key: str) -> TaskReviewResult:
        if self.failure is not None:
            raise self.failure
        self.calls.append((command, idempotency_key))
        applied = idempotency_key not in self.keys
        self.keys.add(idempotency_key)
        if isinstance(command, AcceptCandidate):
            action = DecisionAction.ACCEPT
            outputs = ((TASK_ID, 1),)
        elif isinstance(command, RejectCandidate):
            action = DecisionAction.REJECT
            outputs = ()
        elif isinstance(command, MergeCandidates):
            action = DecisionAction.MERGE
            outputs = ((TASK_ID, 1),)
        else:
            action = DecisionAction.SPLIT
            outputs = ((TASK_ID, 1), ("1" * 64, 1))
        return TaskReviewResult(
            decision_id=DECISION_ID,
            action=action,
            output_revisions=outputs,
            applied=applied,
        )


def _client(tmp_path, service: MemoryReviewService) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(home=tmp_path),
            database=MinimalStore(),
            api_token=EXAMPLE_TOKEN,
            task_review_service=service,
        ),
        base_url="http://127.0.0.1",
    )


def _headers(key: str) -> dict[str, str]:
    return {
        API_TOKEN_HEADER: EXAMPLE_TOKEN,
        IDEMPOTENCY_HEADER: key,
    }


def test_review_routes_map_strict_commands_and_idempotent_retry(tmp_path) -> None:
    service = MemoryReviewService()
    version = "discovery-v1"
    with _client(tmp_path, service) as client:
        capabilities = client.get("/v1/capabilities", headers=_headers("capabilities"))
        first = client.post(
            "/v1/task-decisions/accept",
            headers=_headers("accept-1"),
            json={
                "candidate_id": CANDIDATE_A,
                "expected_discovery_version": version,
                "task_category": "bug_fix",
            },
        )
        retry = client.post(
            "/v1/task-decisions/accept",
            headers=_headers("accept-1"),
            json={
                "candidate_id": CANDIDATE_A,
                "expected_discovery_version": version,
                "task_category": "bug_fix",
            },
        )
        rejected = client.post(
            "/v1/task-decisions/reject",
            headers=_headers("reject-1"),
            json={
                "candidate_id": CANDIDATE_A,
                "expected_discovery_version": version,
                "reason": "wrong_grouping",
            },
        )
        merged = client.post(
            "/v1/task-decisions/merge",
            headers=_headers("merge-1"),
            json={
                "candidate_ids": [CANDIDATE_A, CANDIDATE_B],
                "expected_discovery_version": version,
            },
        )
        split = client.post(
            "/v1/task-decisions/split",
            headers=_headers("split-1"),
            json={
                "candidate_id": CANDIDATE_A,
                "partitions": [[SESSION_A], [SESSION_B]],
                "expected_discovery_version": version,
                "task_categories": ["unknown", "feature_implementation"],
            },
        )

    assert capabilities.json()["write_api"] is True
    assert capabilities.json()["task_review"] is True
    assert first.status_code == 200
    assert first.json() == {
        "decision_id": DECISION_ID,
        "action": "accept",
        "output_revisions": [{"task_id": TASK_ID, "revision": 1}],
        "applied": True,
    }
    assert retry.status_code == 200
    assert retry.json()["decision_id"] == first.json()["decision_id"]
    assert retry.json()["applied"] is False
    assert rejected.json()["action"] == "reject"
    assert merged.json()["action"] == "merge"
    assert split.json()["action"] == "split"
    assert isinstance(service.calls[0][0], AcceptCandidate)
    assert isinstance(service.calls[2][0], RejectCandidate)
    assert isinstance(service.calls[3][0], MergeCandidates)
    assert isinstance(service.calls[4][0], SplitCandidate)
    assert service.calls[0][1] == "accept-1"


def test_review_routes_reject_malformed_commands_before_service_call(tmp_path) -> None:
    service = MemoryReviewService()
    body = {
        "candidate_id": CANDIDATE_A,
        "expected_discovery_version": "discovery-v1",
    }
    with _client(tmp_path, service) as client:
        unauthenticated = client.post(
            "/v1/task-decisions/accept",
            headers={IDEMPOTENCY_HEADER: "accept-1"},
            json=body,
        )
        missing_key = client.post(
            "/v1/task-decisions/accept",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
            json=body,
        )
        unsafe_key = client.post(
            "/v1/task-decisions/accept",
            headers=_headers("contains spaces"),
            json=body,
        )
        extra_field = client.post(
            "/v1/task-decisions/accept",
            headers=_headers("accept-extra"),
            json={**body, "note": "not accepted"},
        )
        duplicate_merge = client.post(
            "/v1/task-decisions/merge",
            headers=_headers("merge-duplicate"),
            json={
                "candidate_ids": [CANDIDATE_A, CANDIDATE_A],
                "expected_discovery_version": "discovery-v1",
            },
        )
        hostile_origin = client.post(
            "/v1/task-decisions/accept",
            headers={**_headers("accept-origin"), "Origin": "https://example.invalid"},
            json=body,
        )

    assert unauthenticated.status_code == 401
    assert missing_key.status_code == 422
    assert unsafe_key.status_code == 422
    assert extra_field.status_code == 422
    assert duplicate_merge.status_code == 422
    assert hostile_origin.status_code == 403
    assert service.calls == []


def test_review_application_errors_have_sanitized_http_statuses(tmp_path) -> None:
    service = MemoryReviewService()
    body = {
        "candidate_id": CANDIDATE_A,
        "expected_discovery_version": "discovery-v1",
    }
    cases = (
        (CandidateNotFoundError("internal candidate context"), 404, "candidate not found"),
        (StaleCandidateError("internal version context"), 409, "candidate version is stale"),
        (InvalidTaskReviewError("internal grouping context"), 422, "invalid task review"),
    )
    with _client(tmp_path, service) as client:
        for index, (failure, expected_status, expected_detail) in enumerate(cases):
            service.failure = failure
            response = client.post(
                "/v1/task-decisions/accept",
                headers=_headers(f"failure-{index}"),
                json=body,
            )
            assert response.status_code == expected_status
            assert response.json() == {"detail": expected_detail}
            assert str(failure) not in response.text
