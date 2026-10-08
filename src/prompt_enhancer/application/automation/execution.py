"""Reviewed execution bridge from active automation grants to local analysis."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from ...domain import DataTier

from ..analysis import (
    SESSION_TEXT_ANALYSIS_CONFIRMATION,
    SessionTextAnalysisCooperativeStop,
    SessionTextAnalysisCompatibilityError,
    SessionTextAnalysisConflictError,
    SessionTextAnalysisConsentError,
    SessionTextAnalysisExecutionError,
    SessionTextAnalysisInputError,
    SessionTextAnalysisPersistenceError,
    SessionTextAnalysisSelectionError,
    SessionTextAnalysisService,
    SessionTextAnalysisSourceError,
    TextAnalysisPresetId,
)
from ..jobs import (
    AnalysisJobCooperativeStop,
    AnalysisJobExecutionContext,
    AnalysisJobExecutionError,
    AnalysisJobExecutionResult,
    AnalysisJobRecord,
    AnalysisJobState,
)
from ..persistence import SessionAnalysisCompletionAuthority
from .contracts import (
    AutomationCandidateSource,
    AutomationGrantRepository,
    AutomationGrantState,
    is_reviewed_automation_resource_policy,
)
from .service import AutomationAccessPolicy


class AutomationJobGuard:
    """Recheck grant, consent, scope, and fingerprints at every heartbeat."""

    def __init__(
        self,
        grants: AutomationGrantRepository,
        access: AutomationAccessPolicy,
        candidates: AutomationCandidateSource,
        *,
        clock: Callable[[], datetime],
    ) -> None:
        self._grants = grants
        self._access = access
        self._candidates = candidates
        self._clock = clock

    def authorized(self, job: AnalysisJobRecord) -> bool:
        grant_id = job.identity.automation_grant_id
        if grant_id is None:
            return False
        grant = self._grants.get(grant_id)
        if (
            grant is None
            or grant.effective_state(self._clock())
            is not AutomationGrantState.ACTIVE
        ):
            return False
        scope = grant.scope
        return (
            is_reviewed_automation_resource_policy(scope.resource_policy)
            and
            scope.provider is job.identity.provider
            and scope.project_id == job.identity.project_id
            and scope.metric_keys == job.identity.metric_keys
            and self._access.has_active_consent(
                scope.provider,
                DataTier.REDACTED_CONTENT,
            )
        )

    def fingerprints(self, job: AnalysisJobRecord) -> tuple[str, str] | None:
        grant_id = job.identity.automation_grant_id
        if grant_id is None:
            return None
        grant = self._grants.get(grant_id)
        if grant is None or not self.authorized(job):
            return None
        candidates = self._candidates.newest_changed(
            grant.scope,
            limit=grant.scope.newest_session_limit,
        )
        for candidate in candidates:
            if candidate.session_id == job.identity.session_id:
                return (
                    candidate.input_fingerprint,
                    candidate.provenance_fingerprint,
                )
        return None


class SessionQualityAutomationHandler:
    """Run the server-owned Coaching v1 pack under a checked local grant."""

    def __init__(self, analyses: SessionTextAnalysisService) -> None:
        self._analyses = analyses

    def __call__(
        self,
        job: AnalysisJobRecord,
        context: AnalysisJobExecutionContext,
    ) -> AnalysisJobExecutionResult:
        context.enter_stage(2, progress_completed=0, progress_total=1)
        grant_id = job.identity.automation_grant_id
        if grant_id is None:
            raise AnalysisJobExecutionError(
                "automation_authorization_revoked",
                retryable=False,
            )
        completion_authority = SessionAnalysisCompletionAuthority(
            job_id=job.job_id,
            automation_grant_id=grant_id,
            lease_owner=context.lease.owner,
            lease_token=context.lease.token,
        )

        def cooperative_check() -> None:
            try:
                context.publication_checkpoint()
            except AnalysisJobCooperativeStop as error:
                raise SessionTextAnalysisCooperativeStop(
                    error.reason_code
                ) from None

        try:
            outcome = self._analyses.run_preset(
                provider=job.identity.provider,
                session_id=job.identity.session_id,
                preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
                # The worker may use the literal only after AutomationJobGuard
                # rechecks the renewable local-only grant. It never authorizes
                # remote disclosure.
                confirmation=SESSION_TEXT_ANALYSIS_CONFIRMATION,
                idempotency_key=f"automation-{job.job_id}",
                selected_metric_keys=job.identity.metric_keys,
                completion_authority=completion_authority,
                cooperative_check=cooperative_check,
                publication_committed_callback=context.mark_publication_committed,
            )
        except SessionTextAnalysisCooperativeStop as error:
            raise AnalysisJobCooperativeStop(error.reason_code) from None
        except (
            SessionTextAnalysisConsentError,
            SessionTextAnalysisSelectionError,
        ):
            raise AnalysisJobExecutionError(
                "automation_authorization_revoked",
                retryable=False,
            ) from None
        except SessionTextAnalysisCompatibilityError:
            raise AnalysisJobExecutionError(
                "provider_schema_incompatible",
                retryable=False,
            ) from None
        except (
            SessionTextAnalysisInputError,
            SessionTextAnalysisConflictError,
        ):
            raise AnalysisJobExecutionError(
                "automation_analysis_conflict",
                retryable=False,
            ) from None
        except SessionTextAnalysisSourceError:
            raise AnalysisJobExecutionError(
                "provider_read_failed",
                retryable=True,
            ) from None
        except (
            SessionTextAnalysisExecutionError,
            SessionTextAnalysisPersistenceError,
        ):
            raise AnalysisJobExecutionError(
                "local_analysis_failed",
                retryable=True,
            ) from None
        context.heartbeat()
        if outcome.status.value != "completed":
            raise AnalysisJobExecutionError(
                "local_analysis_incomplete",
                retryable=True,
            )
        if outcome.result_count != len(job.identity.metric_keys):
            raise AnalysisJobExecutionError(
                "automation_metric_scope_mismatch",
                retryable=False,
            )
        return AnalysisJobExecutionResult(
            state=AnalysisJobState.COMPLETED,
            reason_code="local_analysis_completed",
            progress_completed=1,
            progress_total=1,
        )


__all__ = ["AutomationJobGuard", "SessionQualityAutomationHandler"]
