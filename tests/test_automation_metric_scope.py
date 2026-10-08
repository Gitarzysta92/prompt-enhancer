from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from prompt_enhancer.application.analysis import SessionTextAnalysisOutcome
from prompt_enhancer.application.automation import (
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
    AutomationJobGuard,
    SessionQualityAutomationHandler,
)
from prompt_enhancer.application.jobs import (
    AnalysisJobCooperativeStop,
    AnalysisJobExecutionError,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobLease,
    AnalysisJobRecord,
    AnalysisJobState,
)
from prompt_enhancer.application.persistence import AnalysisRunStatus
from prompt_enhancer.domain import DataTier, Provider


NOW = datetime(2048, 4, 5, 6, 7, tzinfo=UTC)
ONE_METRIC = ("prompt.context_sufficiency",)
THREE_METRICS = (
    "collaboration.rework_candidate_rate",
    "logic.decomposition_coverage",
    "prompt.context_sufficiency",
)


def _job(metric_keys: tuple[str, ...] = ONE_METRIC) -> AnalysisJobRecord:
    return AnalysisJobRecord(
        job_id="1" * 64,
        dedupe_key="2" * 64,
        identity=AnalysisJobIdentity(
            kind=AnalysisJobKind.SESSION_QUALITY,
            provider=Provider.CODEX,
            project_id="3" * 64,
            session_id="4" * 64,
            input_fingerprint="5" * 64,
            provenance_fingerprint="6" * 64,
            metric_keys=metric_keys,
            estimator_plan_version="coaching-example-plan-v1",
            redactor_version="example-redactor-v1",
            provider_schema_version="codex-example-schema-v1",
            automation_grant_id="7" * 64,
        ),
        state=AnalysisJobState.QUEUED,
        progress_completed=0,
        progress_total=1,
        attempt_count=0,
        max_attempts=3,
        available_at=NOW,
        cancel_requested=False,
        created_at=NOW,
        updated_at=NOW,
    )


def _grant(
    metric_keys: tuple[str, ...] = ONE_METRIC,
    *,
    state: AutomationGrantState = AutomationGrantState.ACTIVE,
) -> AutomationGrantRecord:
    return AutomationGrantRecord(
        grant_id="7" * 64,
        revision=1,
        scope=AutomationGrantScope(
            provider=Provider.CODEX,
            project_id="3" * 64,
            metric_keys=metric_keys,
        ),
        state=state,
        created_at=NOW,
        renewed_at=NOW,
        expires_at=NOW + timedelta(days=30),
        next_check_at=NOW,
        revoked_at=NOW if state is AutomationGrantState.REVOKED else None,
    )


class RecordingAnalysisService:
    def __init__(self, result_count: int) -> None:
        self.result_count = result_count
        self.calls: list[dict[str, object]] = []

    def run_preset(self, **values: object) -> SessionTextAnalysisOutcome:
        self.calls.append(values)
        cooperative_check = values["cooperative_check"]
        publication_committed = values["publication_committed_callback"]
        assert callable(cooperative_check)
        assert callable(publication_committed)
        cooperative_check()
        publication_committed()
        return SessionTextAnalysisOutcome(
            run_id="8" * 64,
            status=AnalysisRunStatus.COMPLETED,
            result_count=self.result_count,
            applied=True,
            analysis_profile_key="coaching_profile",
            analysis_profile_version=1,
        )


class RecordingContext:
    def __init__(self) -> None:
        self.stages: list[tuple[int, int, int]] = []
        self.heartbeats = 0
        self.publication_checkpoints = 0
        self.publication_committed = False
        self.lease = AnalysisJobLease(
            job_id="1" * 64,
            owner="8" * 64,
            token="9" * 64,
            expires_at=NOW + timedelta(minutes=1),
        )

    def enter_stage(
        self,
        stage_number: int,
        *,
        progress_completed: int,
        progress_total: int,
    ) -> None:
        self.stages.append(
            (stage_number, progress_completed, progress_total)
        )

    def heartbeat(self) -> None:
        self.heartbeats += 1

    def publication_checkpoint(self) -> None:
        self.publication_checkpoints += 1

    def mark_publication_committed(self) -> None:
        self.publication_committed = True


@pytest.mark.parametrize("metric_keys", (ONE_METRIC, THREE_METRICS))
def test_automation_handler_forwards_exact_immutable_metric_scope(
    metric_keys: tuple[str, ...],
) -> None:
    analyses = RecordingAnalysisService(len(metric_keys))
    context = RecordingContext()

    result = SessionQualityAutomationHandler(analyses)(  # type: ignore[arg-type]
        _job(metric_keys),
        context,  # type: ignore[arg-type]
    )

    assert analyses.calls[0]["selected_metric_keys"] == metric_keys
    assert analyses.calls[0]["idempotency_key"] == f"automation-{'1' * 64}"
    authority = analyses.calls[0]["completion_authority"]
    assert authority.job_id == "1" * 64  # type: ignore[union-attr]
    assert authority.automation_grant_id == "7" * 64  # type: ignore[union-attr]
    assert "8" * 64 not in repr(authority)
    assert "9" * 64 not in repr(authority)
    assert context.stages == [(2, 0, 1)]
    assert context.publication_checkpoints == 1
    assert context.publication_committed is True
    assert context.heartbeats == 1
    assert result.state is AnalysisJobState.COMPLETED


def test_automation_handler_fails_closed_on_result_scope_mismatch() -> None:
    analyses = RecordingAnalysisService(result_count=2)

    with pytest.raises(AnalysisJobExecutionError) as raised:
        SessionQualityAutomationHandler(analyses)(  # type: ignore[arg-type]
            _job(ONE_METRIC),
            RecordingContext(),  # type: ignore[arg-type]
        )

    assert raised.value.code == "automation_metric_scope_mismatch"
    assert raised.value.retryable is False


def test_automation_handler_preserves_fixed_cooperative_deadline_reason() -> None:
    class DeadlineContext(RecordingContext):
        def publication_checkpoint(self) -> None:
            raise AnalysisJobCooperativeStop(
                "automation_publication_deadline_exceeded"
            )

    with pytest.raises(AnalysisJobCooperativeStop) as raised:
        SessionQualityAutomationHandler(RecordingAnalysisService(1))(
            _job(ONE_METRIC),
            DeadlineContext(),  # type: ignore[arg-type]
        )

    assert raised.value.reason_code == "automation_publication_deadline_exceeded"


class GrantRepository:
    def __init__(self, record: AutomationGrantRecord) -> None:
        self.record = record

    def get(self, grant_id: str) -> AutomationGrantRecord | None:
        assert grant_id == "7" * 64
        return self.record


class AccessPolicy:
    def has_active_consent(self, provider: Provider, tier: DataTier) -> bool:
        return provider is Provider.CODEX and tier is DataTier.REDACTED_CONTENT


class UnusedCandidates:
    def newest_changed(
        self,
        *_args: object,
        **_kwargs: object,
    ) -> tuple[object, ...]:
        raise AssertionError("scope rejection must not query candidates")


@pytest.mark.parametrize(
    "grant",
    (
        _grant(THREE_METRICS),
        _grant(ONE_METRIC, state=AutomationGrantState.REVOKED),
    ),
)
def test_guard_rejects_changed_or_revoked_scope_before_retry(
    grant: AutomationGrantRecord,
) -> None:
    guard = AutomationJobGuard(
        GrantRepository(grant),  # type: ignore[arg-type]
        AccessPolicy(),  # type: ignore[arg-type]
        UnusedCandidates(),  # type: ignore[arg-type]
        clock=lambda: NOW,
    )
    job = _job(ONE_METRIC)

    assert guard.authorized(job) is False
    assert guard.fingerprints(job) is None
