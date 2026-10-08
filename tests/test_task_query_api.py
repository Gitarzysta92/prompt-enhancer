from __future__ import annotations

from datetime import UTC, datetime

from fastapi.testclient import TestClient

from prompt_enhancer.api import API_TOKEN_HEADER, create_app
from prompt_enhancer.application.discovery import SignalDirection
from prompt_enhancer.application.persistence import (
    AnalysisResultRecord,
    AnalysisRunDraft,
    AnalysisRunRecord,
    AnalysisRunStatus,
    CandidateDecisionStatus,
    CandidateListItem,
    CandidateSignalRecord,
    DecisionAction,
    MetricValueState,
    TaskCandidateRecord,
    TaskDecisionRecord,
    TaskRevisionRecord,
)
from prompt_enhancer.config import AppSettings
from prompt_enhancer.domain import (
    DataTier,
    MetricObservation,
    MetricSource,
    Provider,
)


EXAMPLE_TOKEN = "example_task_query_token_do_not_use_123456789"
NOW = datetime(2026, 1, 2, 3, 4, tzinfo=UTC)
CANDIDATE_ID = "a" * 64
PROJECT_ID = "b" * 64
SESSION_IDS = ("c" * 64, "d" * 64)
INSTALLATION_ID = "4" * 64
FINGERPRINT = "e" * 64
DECISION_ID = "f" * 64
TASK_ID = "1" * 64
RUN_ID = "2" * 64
EVENT_ID = "3" * 64


def _candidate() -> TaskCandidateRecord:
    signal = CandidateSignalRecord(
        key="time_gap",
        version=1,
        session_ids=SESSION_IDS,
        direction=SignalDirection.SUPPORTS_LINK,
        confidence=0.75,
        weight=1.0,
        evidence_code="within_threshold",
        observed_count=1,
        eligible_count=1,
        coverage=1.0,
        numeric_evidence=300.0,
        evidence_unit="seconds",
    )
    return TaskCandidateRecord(
        candidate_id=CANDIDATE_ID,
        provider=Provider.SYNTHETIC,
        installation_id=INSTALLATION_ID,
        project_id=PROJECT_ID,
        session_ids=SESSION_IDS,
        signals=(signal,),
        confidence=0.75,
        observed_count=1,
        eligible_count=1,
        coverage=1.0,
        discovery_version="discovery-v1",
        input_fingerprint=FINGERPRINT,
        created_at=NOW,
    )


def _task_revision() -> TaskRevisionRecord:
    return TaskRevisionRecord(
        task_id=TASK_ID,
        revision=1,
        project_id=PROJECT_ID,
        task_type="unknown",
        lifecycle_state="active",
        session_ids=SESSION_IDS,
        input_fingerprint=FINGERPRINT,
        created_at=NOW,
    )


def _analysis_run() -> AnalysisRunRecord:
    return AnalysisRunRecord(
        draft=AnalysisRunDraft(
            run_id=RUN_ID,
            task_id=TASK_ID,
            task_revision=1,
            metric_pack_key="baseline",
            metric_pack_version=1,
            data_tier=DataTier.METADATA,
            input_fingerprint=FINGERPRINT,
            metric_engine_version="engine-v1",
            redactor_version="metadata-only-v1",
            schema_version=2,
            started_at=NOW,
        ),
        status=AnalysisRunStatus.COMPLETED,
        finished_at=NOW,
    )


def _analysis_result() -> AnalysisResultRecord:
    return AnalysisResultRecord(
        observation=MetricObservation(
            key="workflow.event_count",
            version=1,
            numeric_value=2.0,
            unit="count",
            source=MetricSource.DETERMINISTIC,
            observed_count=2,
            eligible_count=2,
            coverage=1.0,
            confidence=1.0,
        ),
        value_state=MetricValueState.KNOWN,
        calculator_version="calculator-v1",
        evidence_event_ids=(EVENT_ID,),
        computed_at=NOW,
    )


class MemoryTaskRepository:
    def get_candidate(self, candidate_id: str):
        return _candidate() if candidate_id == CANDIDATE_ID else None

    def list_candidates(
        self,
        *,
        status: CandidateDecisionStatus | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        if status is CandidateDecisionStatus.UNDECIDED or offset:
            return ()
        return (
            CandidateListItem(
                candidate=_candidate(),
                decision_status=CandidateDecisionStatus.DECIDED,
                decision_id=DECISION_ID,
                decision_action=DecisionAction.REJECT,
            ),
        )[:limit]

    def get_revision(self, task_id: str, revision: int):
        if (task_id, revision) == (TASK_ID, 1):
            return _task_revision()
        return None

    def list_task_revisions(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        if task_id not in (None, TASK_ID) or offset:
            return ()
        return (_task_revision(),)[:limit]

    def list_decisions(self, candidate_id: str):
        if candidate_id != CANDIDATE_ID:
            return ()
        return (
            TaskDecisionRecord(
                decision_id=DECISION_ID,
                action=DecisionAction.REJECT,
                candidate_ids=(CANDIDATE_ID,),
                revision_links=(),
                decision_schema_version="1",
                decision_code="wrong_grouping",
                decided_at=NOW,
            ),
        )


class MemoryAnalysisRepository:
    def get(self, run_id: str):
        return _analysis_run() if run_id == RUN_ID else None

    def list_analysis_runs(
        self,
        *,
        task_id: str | None = None,
        limit: int = 100,
        offset: int = 0,
    ):
        if task_id not in (None, TASK_ID) or offset:
            return ()
        return (_analysis_run(),)[:limit]

    def get_results(self, run_id: str):
        return (_analysis_result(),) if run_id == RUN_ID else ()


class TaskQueryStore:
    def initialize(self) -> None:
        return None

    def list_metric_definitions(self):
        return [
            {
                "key": "workflow.event_count",
                "version": 1,
                "dimension": "legacy_workflow",
                "display_name": "Persisted v1 event count",
                "description": "Synthetic version-one task event observation.",
            },
            {
                "key": "workflow.event_count",
                "version": 2,
                "dimension": "workflow",
                "display_name": "Current event count",
                "description": "Synthetic version-two task event observation.",
            },
        ]

    def list_sessions(self, *, limit: int = 100, offset: int = 0):
        return []

    def get_session_metrics(self, session_id: str):
        return []

    def task_repository(self):
        return MemoryTaskRepository()

    def analysis_run_repository(self):
        return MemoryAnalysisRepository()


class MissingDefinitionTaskQueryStore(TaskQueryStore):
    def list_metric_definitions(self):
        return []


def _client(tmp_path) -> TestClient:
    return TestClient(
        create_app(
            settings=AppSettings(home=tmp_path),
            database=TaskQueryStore(),
            api_token=EXAMPLE_TOKEN,
        ),
        base_url="http://127.0.0.1",
    )


def test_analysis_result_presentation_is_optional_for_legacy_stores(tmp_path) -> None:
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=MissingDefinitionTaskQueryStore(),
        api_token=EXAMPLE_TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        response = client.get(
            f"/v1/analysis/runs/{RUN_ID}",
            headers={API_TOKEN_HEADER: EXAMPLE_TOKEN},
        )

    assert response.status_code == 200
    result = response.json()["results"][0]
    assert result["dimension"] is None
    assert result["display_name"] is None
    assert result["description"] is None


def test_authenticated_queries_return_only_typed_metadata(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with _client(tmp_path) as client:
        unauthorized = client.get(f"/v1/discovery/candidates/{CANDIDATE_ID}")
        inbox = client.get(
            "/v1/discovery/candidates?status=decided&limit=10", headers=headers
        )
        candidate = client.get(
            f"/v1/discovery/candidates/{CANDIDATE_ID}", headers=headers
        )
        decisions = client.get(
            f"/v1/discovery/candidates/{CANDIDATE_ID}/decisions", headers=headers
        )
        task_list = client.get(
            f"/v1/task-revisions?task_id={TASK_ID}", headers=headers
        )
        task = client.get(f"/v1/tasks/{TASK_ID}/revisions/1", headers=headers)
        run_list = client.get(
            f"/v1/analysis/runs?task_id={TASK_ID}", headers=headers
        )
        run = client.get(f"/v1/analysis/runs/{RUN_ID}", headers=headers)

    assert unauthorized.status_code == 401
    assert inbox.status_code == 200
    assert inbox.json()["candidates"][0]["decision_status"] == "decided"
    assert candidate.status_code == 200
    assert candidate.json()["candidate"]["signals"][0]["evidence_code"] == "within_threshold"
    assert decisions.json()["decisions"][0]["decision_code"] == "wrong_grouping"
    assert task_list.json()["tasks"][0]["task_id"] == TASK_ID
    assert task.json()["task"]["lifecycle_state"] == "active"
    assert run_list.json()["runs"][0]["run_id"] == RUN_ID
    assert run.json()["run"]["status"] == "completed"
    assert run.json()["results"][0]["value_state"] == "known"
    assert run.json()["results"][0]["dimension"] == "legacy_workflow"
    assert run.json()["results"][0]["display_name"] == "Persisted v1 event count"
    assert run.json()["results"][0]["description"] == (
        "Synthetic version-one task event observation."
    )

    serialized = "".join(
        response.text
        for response in (
            inbox,
            candidate,
            decisions,
            task_list,
            task,
            run_list,
            run,
        )
    ).casefold()
    for prohibited in ("prompt_text", "transcript", "filesystem", "account_id"):
        assert prohibited not in serialized
    assert EXAMPLE_TOKEN not in serialized


def test_query_filters_and_identifiers_are_strict(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    with _client(tmp_path) as client:
        malformed = client.get(
            "/v1/discovery/candidates/not-a-pseudonym", headers=headers
        )
        invalid_status = client.get(
            "/v1/discovery/candidates?status=pending", headers=headers
        )
        invalid_limit = client.get(
            "/v1/discovery/candidates?limit=101", headers=headers
        )
        invalid_task_filter = client.get(
            "/v1/task-revisions?task_id=not-a-pseudonym", headers=headers
        )
        missing_candidate = client.get(
            f"/v1/discovery/candidates/{'9' * 64}", headers=headers
        )
        invalid_revision = client.get(
            f"/v1/tasks/{TASK_ID}/revisions/0", headers=headers
        )
        missing_run = client.get(f"/v1/analysis/runs/{'8' * 64}", headers=headers)

    assert malformed.status_code == 422
    assert invalid_status.status_code == 422
    assert invalid_limit.status_code == 422
    assert invalid_task_filter.status_code == 422
    assert missing_candidate.status_code == 404
    assert invalid_revision.status_code == 422
    assert missing_run.status_code == 404


def test_task_interface_is_query_only_and_runtime_schema_is_disabled(tmp_path) -> None:
    headers = {API_TOKEN_HEADER: EXAMPLE_TOKEN}
    app = create_app(
        settings=AppSettings(home=tmp_path),
        database=TaskQueryStore(),
        api_token=EXAMPLE_TOKEN,
    )
    with TestClient(app, base_url="http://127.0.0.1") as client:
        assert client.get("/openapi.json").status_code == 404
        assert client.post(
            f"/v1/discovery/candidates/{CANDIDATE_ID}/accept",
            headers=headers,
            json={},
        ).status_code == 404
        assert client.post("/v1/sql", headers=headers, json={}).status_code == 404

    schema = app.openapi()
    paths = schema["paths"]
    assert "/v1/discovery/candidates" in paths
    assert "/v1/discovery/candidates/{candidate_id}" in paths
    assert "/v1/task-revisions" in paths
    assert "/v1/tasks/{task_id}/revisions/{revision}" in paths
    assert "/v1/analysis/runs" in paths
    assert "/v1/analysis/runs/{run_id}" in paths
    post_paths = {
        path for path, operations in paths.items() if "post" in operations
    }
    # The provider/task surface remains query-only. The other POSTs are
    # authenticated, same-origin local UI capabilities: one opens a native
    # folder chooser and one requests only a content-free update advisory.
    assert post_paths == {
        "/v1/application-updates/check",
        "/v1/local-ui/workspace-folder-picker",
        "/v1/quality-analysis/aggregate",
    }
