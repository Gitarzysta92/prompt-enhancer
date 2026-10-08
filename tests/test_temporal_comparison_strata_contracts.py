from __future__ import annotations

from dataclasses import asdict, astuple, is_dataclass
from datetime import UTC, datetime, timedelta, timezone
import copy
import hashlib
import inspect
import pickle

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
)
from prompt_enhancer.application.analysis.text_analysis_presets import (
    COACHING_PROFILE_V1,
)
from prompt_enhancer.application.automation.contracts import (
    AUTOMATION_GRANT_LIFETIME,
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
)
from prompt_enhancer.application.history.comparison_strata import (
    ComparisonAnalysisJobAuthorityV1,
    ComparisonAutomationGrantAuthorityV1,
    ComparisonCensoringReadinessV1,
    ComparisonDimensionStateV1,
    ComparisonMatchReadinessV1,
    ComparisonPolicyIdentityV1,
    ComparisonSessionAuthorityV1,
    ComparisonStratumDimensionsV1,
    ComparisonTaskMixBucketV1,
    ComparisonTaskTypeStateV1,
    ComparisonTaskTypeV1,
    MAX_COMPARISON_CURRENT_TASKS,
    ExpectedAnalysisRunVerificationRequestV1,
    AutomationRevalidationRequestV1,
    PreparedComparisonStratumDraftV1,
    ReviewedTaskSelectionVerificationRequestV1,
    SealedComparisonStratumDraftV1,
    ReviewedTaskManifestV1,
    ReviewedTaskTargetProjectionV1,
    TemporalComparisonStratumRepositoryV1,
    automation_grant_scope_fingerprint,
    comparison_policy_set_v1,
    select_current_reviewed_tasks_as_of,
    session_analysis_run_authority_fingerprint,
    _AutomationComparisonLeaseAuthorityV1,
)
from prompt_enhancer.application.history.contracts import (
    AnalysisInputExtractionCompleteness,
    AnalysisInputReceiptV2,
    AnalysisInputSelectionCoverage,
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    EvidenceTier,
    FractionObservationValue,
    MetricComparisonIdentity,
    MetricDirection,
    ProjectMetricSelectionAuthorityKind,
    ProjectMetricSelectionRevisionV2,
    ProjectMetricSelectionSource,
    RepositoryTemporalBatchSealDraft,
    RevisionEffectiveTimeBasis,
    SessionRevisionReceiptV3,
    TemporalAggregationSemantics,
    TemporalHistoryRootReceipt,
    TemporalMetricObservationV2,
    TemporalObservationBatchV2,
    TemporalScopeState,
    TemporalSelectionState,
    TemporalSourceState,
    TemporalValueKind,
    TemporalValueState,
)
from prompt_enhancer.application.history.persistence import (
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
    SyntheticTemporalCompletionRequestV1,
    automation_grant_authority_version,
)
from prompt_enhancer.application.jobs.contracts import (
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobRecord,
    AnalysisJobState,
)
from prompt_enhancer.application.persistence.contracts import (
    AnalysisRunStatus,
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
    SessionMetricScopeState,
    TaskRevisionRecord,
)
from prompt_enhancer.domain import DataTier, Provider, SafeSession, SessionState
from prompt_enhancer.infrastructure.identifiers import LocalArtifactIdFactory
from prompt_enhancer.privacy import Pseudonymizer


FLOOR = datetime(2048, 5, 6, 10, tzinfo=UTC)
PREPARED_AT = FLOOR + timedelta(minutes=2)
METRIC = COACHING_METRIC_DEFINITIONS[0].key
GRANT_REVISION = 4


def _id(label: str) -> str:
    return hashlib.sha256(
        f"reserved-comparison-stratum:{label}".encode("utf-8")
    ).hexdigest()


def _grant_record(
    *,
    revision: int = GRANT_REVISION,
    state: AutomationGrantState = AutomationGrantState.ACTIVE,
    scope: AutomationGrantScope | None = None,
    renewed_at: datetime | None = None,
    housekeeping: str = "base",
) -> AutomationGrantRecord:
    renewed = renewed_at or FLOOR - timedelta(days=1)
    revoked_at = PREPARED_AT if state is AutomationGrantState.REVOKED else None
    return AutomationGrantRecord(
        grant_id=_id("automation-grant"),
        revision=revision,
        scope=scope
        or AutomationGrantScope(
            provider=Provider.SYNTHETIC,
            project_id=_id("project"),
            metric_keys=(METRIC,),
        ),
        state=state,
        created_at=renewed,
        renewed_at=renewed,
        expires_at=renewed + AUTOMATION_GRANT_LIFETIME,
        next_check_at=PREPARED_AT + timedelta(minutes=1),
        last_checked_at=(
            None
            if housekeeping == "base"
            else PREPARED_AT - timedelta(minutes=1)
        ),
        revoked_at=revoked_at,
        last_error_code=(
            None if housekeeping == "base" else "reserved-housekeeping-code"
        ),
    )


def _grant_authority(
    record: AutomationGrantRecord | None = None,
) -> ComparisonAutomationGrantAuthorityV1:
    return ComparisonAutomationGrantAuthorityV1.from_active_record(
        record or _grant_record(),
        observed_at=PREPARED_AT,
    )


def _root() -> TemporalHistoryRootReceipt:
    return TemporalHistoryRootReceipt(
        root_receipt_id=_id("history-root"),
        project_id=_id("project"),
        epoch_ordinal=1,
        history_floor_at=FLOOR,
        issued_at=FLOOR,
    )


def _temporal_scope(
    grant: ComparisonAutomationGrantAuthorityV1,
) -> RepositoryPreparedTemporalScopeV1:
    root = _root()
    selection = ProjectMetricSelectionRevisionV2(
        selection_revision_id=_id("selection"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=1,
        selected_metric_keys=grant.scope.metric_keys,
        source=ProjectMetricSelectionSource.AUTOMATION_GRANT,
        effective_at=FLOOR + timedelta(seconds=30),
        recorded_at=FLOOR + timedelta(seconds=30),
        metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
        metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
        metric_pack_sha256=_id("metric-pack"),
        metric_catalog_version="reserved-metric-catalog-v1",
        metric_catalog_sha256=_id("metric-catalog"),
        source_authority_kind=ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT,
        source_authority_id=grant.grant_id,
        source_authority_fingerprint=grant.fingerprint,
        source_authority_version=automation_grant_authority_version(grant.revision),
    )
    return RepositoryPreparedTemporalScopeV1(
        prepared_scope_id=_id("prepared-scope"),
        history_root=root,
        selection_revision=selection,
        automation_grant_id=grant.grant_id,
        automation_grant_fingerprint=grant.fingerprint,
        automation_grant_revision=grant.revision,
        prepared_at=FLOOR + timedelta(minutes=1),
    )


def _stored_session(
    *,
    provider: Provider = Provider.SYNTHETIC,
    project_display_name: str | None = "Reserved Example Project",
    session_display_name: str | None = "Reserved Example Session",
) -> SafeSession:
    return SafeSession(
        provider=provider,
        installation_id=_id("installation"),
        project_id=_id("project"),
        session_id=_id("session"),
        provider_version="reserved-provider-v1",
        adapter_version="reserved-adapter-v1",
        source_schema_version="reserved-source-schema-v1",
        started_at=FLOOR - timedelta(hours=1),
        ended_at=FLOOR - timedelta(minutes=1),
        terminal_state=SessionState.COMPLETED,
        events_complete=True,
        project_display_name=project_display_name,
        session_display_name=session_display_name,
    )


def _job_record(
    grant: AutomationGrantRecord | None = None,
    *,
    state: AnalysisJobState = AnalysisJobState.PREPROCESSING,
    job_kind: AnalysisJobKind = AnalysisJobKind.SESSION_QUALITY,
    progress_completed: int = 0,
    lease_label: str = "base",
) -> AnalysisJobRecord:
    stored_grant = grant or _grant_record()
    active = state in {AnalysisJobState.PREPROCESSING, AnalysisJobState.STAGE_N}
    terminal = state in {
        AnalysisJobState.COMPLETED,
        AnalysisJobState.PARTIAL,
        AnalysisJobState.FAILED,
        AnalysisJobState.CANCELLED,
        AnalysisJobState.SUPERSEDED,
    }
    return AnalysisJobRecord(
        job_id=_id("analysis-job"),
        dedupe_key=_id("analysis-job-dedupe"),
        identity=AnalysisJobIdentity(
            kind=job_kind,
            provider=stored_grant.scope.provider,
            project_id=stored_grant.scope.project_id,
            session_id=_id("session"),
            input_fingerprint=_id("job-input"),
            provenance_fingerprint=_id("job-provenance"),
            metric_keys=stored_grant.scope.metric_keys,
            estimator_plan_version="reserved-automation-plan-v1",
            redactor_version="reserved-redactor-v1",
            provider_schema_version="reserved-source-schema-v1",
            automation_grant_id=stored_grant.grant_id,
        ),
        state=state,
        stage_number=1 if state is AnalysisJobState.STAGE_N else None,
        progress_completed=progress_completed,
        progress_total=1,
        attempt_count=1,
        max_attempts=3,
        available_at=FLOOR,
        cancel_requested=False,
        lease_owner=_id(f"lease-owner-{lease_label}") if active else None,
        lease_token=_id(f"lease-token-{lease_label}") if active else None,
        lease_expires_at=PREPARED_AT + timedelta(minutes=5) if active else None,
        terminal_reason_code="reserved-terminal" if terminal else None,
        created_at=FLOOR + timedelta(minutes=1, seconds=30),
        updated_at=PREPARED_AT,
        terminal_at=PREPARED_AT if terminal else None,
    )


def _task_revision(
    label: str,
    *,
    task_type: str = "bug_fix",
    revision: int = 1,
    session_ids: tuple[str, ...] | None = None,
    project_id: str | None = None,
    lifecycle_state: str = "confirmed",
    created_at: datetime | None = None,
) -> TaskRevisionRecord:
    return TaskRevisionRecord(
        task_id=_id(f"task-{label}"),
        revision=revision,
        project_id=project_id or _id("project"),
        task_type=task_type,
        lifecycle_state=lifecycle_state,
        session_ids=session_ids or (_id("session"),),
        input_fingerprint=_id(f"task-{label}-input-r{revision}"),
        created_at=created_at or PREPARED_AT - timedelta(seconds=1),
    )


def _selection_request(
    revisions: tuple[TaskRevisionRecord, ...],
    *,
    session_id: str = _id("session"),
    cutoff_at: datetime = PREPARED_AT,
    scanned_current_candidate_count: int | None = None,
    overflow_detected: bool = False,
) -> ReviewedTaskSelectionVerificationRequestV1:
    selected = select_current_reviewed_tasks_as_of(
        revisions=revisions,
        session_id=session_id,
        cutoff_at=cutoff_at,
    )
    scanned = (
        len(selected)
        if scanned_current_candidate_count is None
        else scanned_current_candidate_count
    )
    if overflow_detected or scanned > MAX_COMPARISON_CURRENT_TASKS:
        raise ValueError("repository MAX+1 query detected task-selection overflow")
    if scanned != len(selected):
        raise ValueError("repository scan count must bind the exact selected rows")
    projections = tuple(
        ReviewedTaskTargetProjectionV1.from_source_revision(
            record,
            target_session_id=session_id,
        )
        for record in selected
    )
    selection_id = _id("task-selection-receipt")
    evidence = _id("task-query-evidence")
    selection_sha256 = ReviewedTaskSelectionVerificationRequestV1.selection_for(
        selection_request_id=selection_id,
        session_id=session_id,
        cutoff_at=cutoff_at,
        scanned_current_candidate_count=scanned,
        ordered_projection_fingerprints=tuple(item.fingerprint for item in projections),
        claimed_query_evidence_fingerprint=evidence,
    )
    return ReviewedTaskSelectionVerificationRequestV1(
        selection_request_id=selection_id,
        session_id=session_id,
        cutoff_at=cutoff_at,
        scanned_current_candidate_count=scanned,
        current_revisions=projections,
        claimed_query_evidence_fingerprint=evidence,
        selection_sha256=selection_sha256,
    )


def _expected_run_request(
    job: ComparisonAnalysisJobAuthorityV1,
    *,
    run_id: str = _id("analysis-run"),
    issued_at: datetime = PREPARED_AT,
) -> ExpectedAnalysisRunVerificationRequestV1:
    derivation = ExpectedAnalysisRunVerificationRequestV1.derivation_for(
        analysis_job_id=job.job_id,
        provider=job.identity.provider,
        session_id=job.identity.session_id,
        metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
        metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
    )
    authority_receipt_id = _id("expected-run-receipt")
    idempotency_key = f"automation-{job.job_id}"
    request_sha256 = ExpectedAnalysisRunVerificationRequestV1.request_for(
        authority_receipt_id=authority_receipt_id,
        analysis_job_id=job.job_id,
        analysis_job_authority_fingerprint=job.fingerprint,
        provider=job.identity.provider,
        session_id=job.identity.session_id,
        idempotency_key=idempotency_key,
        metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
        metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
        expected_analysis_run_id=run_id,
        derivation_inputs_sha256=derivation,
        issued_at=issued_at,
    )
    return ExpectedAnalysisRunVerificationRequestV1(
        authority_receipt_id=authority_receipt_id,
        analysis_job_id=job.job_id,
        analysis_job_authority_fingerprint=job.fingerprint,
        provider=job.identity.provider,
        session_id=job.identity.session_id,
        idempotency_key=idempotency_key,
        metric_pack_key=COACHING_PROFILE_V1.metric_pack_key,
        metric_pack_version=COACHING_PROFILE_V1.metric_pack_version,
        expected_analysis_run_id=run_id,
        derivation_inputs_sha256=derivation,
        request_sha256=request_sha256,
        issued_at=issued_at,
    )


def _prepared(
    revisions: tuple[TaskRevisionRecord, ...] = (),
    *,
    grant_record: AutomationGrantRecord | None = None,
    job_record: AnalysisJobRecord | None = None,
    stored_session: SafeSession | None = None,
) -> PreparedComparisonStratumDraftV1:
    raw_grant = grant_record or _grant_record()
    grant = _grant_authority(raw_grant)
    scope = _temporal_scope(grant)
    session = ComparisonSessionAuthorityV1.from_stored_session(
        stored_session or _stored_session()
    )
    job = ComparisonAnalysisJobAuthorityV1.from_active_record(
        job_record or _job_record(raw_grant),
        observed_at=PREPARED_AT,
    )
    selection_request = _selection_request(
        revisions,
        session_id=session.session_id,
        cutoff_at=PREPARED_AT,
    )
    manifest = ReviewedTaskManifestV1.from_selection_verification_request(
        selection_request=selection_request,
    )
    dimensions = ComparisonStratumDimensionsV1.from_authority(
        session=session,
        task_manifest=manifest,
    )
    return PreparedComparisonStratumDraftV1(
        prepared_stratum_id=_id("prepared-stratum"),
        prepared_scope=scope,
        analysis_job=job,
        expected_run_request=_expected_run_request(job),
        session_authority=session,
        automation_grant=grant,
        automation_grant_scope_sha256=automation_grant_scope_fingerprint(
            grant.scope
        ),
        dimensions=dimensions,
        policies=comparison_policy_set_v1(),
        prepared_at=PREPARED_AT,
    )


def _analysis_input(
    prepared: PreparedComparisonStratumDraftV1,
    *,
    run_id: str | None = None,
) -> AnalysisInputReceiptV2:
    scope = prepared.prepared_scope
    selection = scope.selection_revision
    started = PREPARED_AT + timedelta(minutes=1)
    ended = started + timedelta(minutes=1)
    completed = ended + timedelta(seconds=1)
    captured = completed + timedelta(seconds=1)
    selected_root = _id("selected-window")
    observed_root = _id("observed-source-manifest")
    return AnalysisInputReceiptV2(
        input_receipt_id=_id("analysis-input"),
        root_receipt_id=scope.history_root.root_receipt_id,
        root_receipt_fingerprint=scope.history_root.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        selection_scope_fingerprint=selection.metric_set_fingerprint,
        analysis_run_id=run_id or prepared.expected_analysis_run_id,
        analysis_run_fingerprint=_id("temporal-analysis-run-fingerprint"),
        analysis_run_fingerprint_version="reserved-analysis-run-v1",
        analysis_run_request_fingerprint=_id("analysis-request"),
        project_id=scope.history_root.project_id,
        session_id=prepared.session_authority.session_id,
        selected_metric_keys=selection.selected_metric_keys,
        analysis_window_fingerprint=_id("analysis-window"),
        selected_window_manifest_root=selected_root,
        selected_window_manifest_entry_count=1,
        selected_window_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.selected_manifest_identity(
                root=selected_root,
                entry_count=1,
            )
        ),
        post_floor_observed_allowlisted_source_manifest_root=observed_root,
        post_floor_observed_allowlisted_source_manifest_entry_count=1,
        post_floor_observed_allowlisted_source_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.observed_source_manifest_identity(
                root=observed_root,
                entry_count=1,
            )
        ),
        successfully_extracted_source_entry_count=1,
        selection_eligible_entry_count=1,
        extraction_completeness=AnalysisInputExtractionCompleteness.COMPLETE,
        selection_coverage=AnalysisInputSelectionCoverage.COMPLETE,
        analysis_window_started_at=started,
        analysis_window_ended_at=ended,
        analysis_run_completed_at=completed,
        captured_at=captured,
        capture_contract_version="reserved-direct-capture-v2",
        analysis_profile_key=COACHING_PROFILE_V1.analysis_profile_key,
        analysis_profile_version=COACHING_PROFILE_V1.analysis_profile_version,
        analysis_profile_sha256=_id("analysis-profile"),
        metric_pack_key=selection.metric_pack_key,
        metric_pack_version=selection.metric_pack_version,
        metric_pack_sha256=selection.metric_pack_sha256,
        metric_engine_version="reserved-engine-v1",
        metric_engine_sha256=_id("metric-engine"),
        metric_catalog_version=selection.metric_catalog_version,
        metric_catalog_sha256=selection.metric_catalog_sha256,
        consent_policy_version="reserved-consent-v1",
        consent_receipt_id=_id("consent"),
        consent_receipt_fingerprint=_id("consent-fingerprint"),
        privacy_policy_version="reserved-privacy-v1",
        provider=Provider.SYNTHETIC,
        provider_version="reserved-provider-v1",
        provider_adapter_version="reserved-adapter-v1",
        provider_schema_version="reserved-provider-schema-v1",
        source_schema_version="reserved-source-schema-v1",
        content_schema_version="reserved-content-schema-v1",
        redactor_version="reserved-redactor-v1",
        redactor_sha256=_id("redactor"),
        preprocessing_version="reserved-preprocessing-v1",
        preprocessing_sha256=_id("preprocessing"),
        router_version="reserved-router-v1",
        router_sha256=_id("router"),
        model_plan_fingerprint=_id("model-plan"),
        analysis_run_schema_version=1,
        full_run_metric_observation_count=1,
    )


def _comparison_identity(
    analysis_input: AnalysisInputReceiptV2,
) -> MetricComparisonIdentity:
    return MetricComparisonIdentity(
        metric_key=METRIC,
        metric_definition_version="reserved-definition-v1",
        metric_definition_sha256=_id("metric-definition"),
        metric_question_version="reserved-question-v1",
        metric_question_sha256=_id("metric-question"),
        value_kind=TemporalValueKind.FRACTION,
        unit_code="ratio",
        direction=MetricDirection.HIGHER_IS_BETTER,
        aggregation_semantics=TemporalAggregationSemantics.RATIO_OF_SUMS,
        evidence_tier=EvidenceTier.REDACTED_CONTENT,
        evidence_contract_version="reserved-evidence-v1",
        estimator_kind=EstimatorIdentityKind.DETERMINISTIC,
        estimator_plan_version="reserved-plan-v1",
        estimator_plan_sha256=_id("estimator-plan"),
        estimator_lifecycle=EstimatorLifecycleState.PROVISIONAL,
        preprocessing_version=analysis_input.preprocessing_version,
        preprocessing_sha256=analysis_input.preprocessing_sha256,
        calibration_version="not-calibrated-v1",
        calibration_sha256=_id("not-calibrated"),
        router_version=analysis_input.router_version,
        router_sha256=analysis_input.router_sha256,
        redactor_version=analysis_input.redactor_version,
        redactor_sha256=analysis_input.redactor_sha256,
        provider=analysis_input.provider,
        provider_adapter_version=analysis_input.provider_adapter_version,
        provider_schema_version=analysis_input.provider_schema_version,
        source_schema_version=analysis_input.source_schema_version,
        content_schema_version=analysis_input.content_schema_version,
        privacy_policy_version=analysis_input.privacy_policy_version,
    )


def _sealed_batch(
    prepared: PreparedComparisonStratumDraftV1,
    *,
    run_id: str | None = None,
) -> RepositorySealedTemporalBatchV1:
    scope = prepared.prepared_scope
    analysis_input = _analysis_input(prepared, run_id=run_id)
    revision = SessionRevisionReceiptV3.from_direct_input(
        revision_id=_id(f"session-revision-{analysis_input.analysis_run_id}"),
        input_receipt=analysis_input,
        revision_ordinal=1,
        effective_time_basis=RevisionEffectiveTimeBasis.SESSION_ENDED_AT,
    )
    observation = TemporalMetricObservationV2(
        observation_id=_id(f"observation-{analysis_input.analysis_run_id}"),
        revision_id=revision.revision_id,
        analysis_run_id=analysis_input.analysis_run_id,
        analysis_input_receipt_id=analysis_input.input_receipt_id,
        analysis_input_receipt_fingerprint=analysis_input.fingerprint,
        comparison_identity=_comparison_identity(analysis_input),
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=FractionObservationValue(numerator=1, denominator=1),
        evidence_coverage_eligibility=EvidenceCoverageEligibility.ELIGIBLE,
        evidence_coverage_state=EvidenceCoverageState.KNOWN,
        evidence_numerator=0,
        evidence_denominator=0,
        observed_at=analysis_input.captured_at + timedelta(seconds=1),
    )
    temporal_batch = TemporalObservationBatchV2(
        batch_id=_id(f"batch-{analysis_input.analysis_run_id}"),
        root_receipt_id=scope.history_root.root_receipt_id,
        root_receipt_fingerprint=scope.history_root.fingerprint,
        project_id=scope.history_root.project_id,
        session_id=analysis_input.session_id,
        revision_id=revision.revision_id,
        revision_fingerprint=revision.fingerprint,
        analysis_run_id=analysis_input.analysis_run_id,
        analysis_run_fingerprint=analysis_input.analysis_run_fingerprint,
        analysis_input_receipt_id=analysis_input.input_receipt_id,
        analysis_input_receipt_fingerprint=analysis_input.fingerprint,
        selection_revision_id=scope.selection_revision.selection_revision_id,
        selection_revision_fingerprint=scope.selection_revision.fingerprint,
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=analysis_input.selected_metric_keys,
        observations=(observation,),
        recorded_at=observation.observed_at + timedelta(seconds=1),
    )
    draft = RepositoryTemporalBatchSealDraft(
        seal_draft_id=_id(f"seal-draft-{analysis_input.analysis_run_id}"),
        history_root=scope.history_root,
        selection_revision=scope.selection_revision,
        analysis_input=analysis_input,
        session_revision=revision,
        observation_batch=temporal_batch,
        analysis_run_id=analysis_input.analysis_run_id,
        analysis_run_fingerprint=analysis_input.analysis_run_fingerprint,
        ordered_observation_ids=(observation.observation_id,),
        ordered_observation_fingerprints=(observation.fingerprint,),
        requested_repository_verifier_version="reserved-repository-verifier-v1",
        requested_repository_verifier_fingerprint=_id("repository-verifier"),
        drafted_at=temporal_batch.recorded_at + timedelta(seconds=1),
    )
    request = SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id(f"completion-{analysis_input.analysis_run_id}"),
        prepared_scope=scope,
        analysis_input=analysis_input,
        analysis_run_id=analysis_input.analysis_run_id,
    )
    return RepositorySealedTemporalBatchV1(
        sealed_batch_id=_id(f"sealed-batch-{analysis_input.analysis_run_id}"),
        completion_request=request,
        prepared_scope_fingerprint=scope.fingerprint,
        completion_request_fingerprint=request.fingerprint,
        seal_draft=draft,
        seal_draft_fingerprint=draft.fingerprint,
        ordered_graph_fingerprints=RepositorySealedTemporalBatchV1.ordered_graph_for(
            request,
            draft,
        ),
        repository_verifier_version=draft.requested_repository_verifier_version,
        repository_verifier_fingerprint=(
            draft.requested_repository_verifier_fingerprint
        ),
        sealed_at=draft.drafted_at + timedelta(seconds=1),
    )


def _analysis_run(
    prepared: PreparedComparisonStratumDraftV1,
    batch: RepositorySealedTemporalBatchV1,
    *,
    started_at: datetime | None = None,
    status: AnalysisRunStatus = AnalysisRunStatus.COMPLETED,
) -> SessionAnalysisRunRecord:
    analysis_input = batch.completion_request.analysis_input
    draft = SessionAnalysisRunDraft(
        run_id=analysis_input.analysis_run_id,
        session_id=analysis_input.session_id,
        request_fingerprint=analysis_input.analysis_run_request_fingerprint,
        input_fingerprint=_id("stored-analysis-input"),
        analysis_profile_key=analysis_input.analysis_profile_key,
        analysis_profile_version=analysis_input.analysis_profile_version,
        metric_pack_key=analysis_input.metric_pack_key,
        metric_pack_version=analysis_input.metric_pack_version,
        metric_scope_state=SessionMetricScopeState.EXACT,
        selected_metric_keys=analysis_input.selected_metric_keys,
        data_tier=DataTier.REDACTED_CONTENT,
        consent_purpose="text_analysis",
        consent_policy_version=analysis_input.consent_policy_version,
        provider=analysis_input.provider,
        provider_version=analysis_input.provider_version,
        adapter_version=analysis_input.provider_adapter_version,
        source_schema_version=analysis_input.source_schema_version,
        content_schema_version=analysis_input.content_schema_version,
        metric_engine_version=analysis_input.metric_engine_version,
        redactor_version=analysis_input.redactor_version,
        model_plan_fingerprint=analysis_input.model_plan_fingerprint,
        schema_version=analysis_input.analysis_run_schema_version,
        local_only=True,
        started_at=started_at or prepared.prepared_at + timedelta(seconds=10),
    )
    if status is AnalysisRunStatus.RUNNING:
        return SessionAnalysisRunRecord(draft=draft, status=status)
    if status is AnalysisRunStatus.FAILED:
        return SessionAnalysisRunRecord(
            draft=draft,
            status=status,
            finished_at=analysis_input.analysis_run_completed_at,
            failure_code="reserved-analysis-failure",
        )
    return SessionAnalysisRunRecord(
        draft=draft,
        status=status,
        finished_at=analysis_input.analysis_run_completed_at,
    )


def _automation_revalidation_request(
    prepared: PreparedComparisonStratumDraftV1,
    *,
    reverified_at: datetime,
) -> AutomationRevalidationRequestV1:
    authority_receipt_id = _id("automation-revalidation-receipt")
    repository_authority = _id("repository-revalidation-authority")
    authority_sha256 = AutomationRevalidationRequestV1.authority_for(
        authority_receipt_id=authority_receipt_id,
        prepared_stratum_id=prepared.prepared_stratum_id,
        prepared_stratum_fingerprint=prepared.fingerprint,
        analysis_job_id=prepared.analysis_job.job_id,
        analysis_job_record_authority_fingerprint=(
            prepared.analysis_job.stored_job_fingerprint
        ),
        current_job_state=prepared.analysis_job.state_at_preparation,
        current_job_lease_authority_fingerprint=(
            prepared.analysis_job.lease_authority_fingerprint
        ),
        current_job_lease_expires_at=prepared.analysis_job.lease_expires_at,
        automation_grant_id=prepared.automation_grant.grant_id,
        current_grant_revision=prepared.automation_grant.revision,
        current_grant_authority_fingerprint=prepared.automation_grant.fingerprint,
        current_grant_expires_at=prepared.automation_grant.expires_at,
        reverified_at=reverified_at,
        repository_revalidation_authority_fingerprint=repository_authority,
    )
    return AutomationRevalidationRequestV1(
        authority_receipt_id=authority_receipt_id,
        prepared_stratum_id=prepared.prepared_stratum_id,
        prepared_stratum_fingerprint=prepared.fingerprint,
        analysis_job_id=prepared.analysis_job.job_id,
        analysis_job_record_authority_fingerprint=(
            prepared.analysis_job.stored_job_fingerprint
        ),
        current_job_state=prepared.analysis_job.state_at_preparation,
        current_job_lease_authority_fingerprint=(
            prepared.analysis_job.lease_authority_fingerprint
        ),
        current_job_lease_expires_at=prepared.analysis_job.lease_expires_at,
        automation_grant_id=prepared.automation_grant.grant_id,
        current_grant_revision=prepared.automation_grant.revision,
        current_grant_authority_fingerprint=prepared.automation_grant.fingerprint,
        current_grant_expires_at=prepared.automation_grant.expires_at,
        reverified_at=reverified_at,
        repository_revalidation_authority_fingerprint=repository_authority,
        authority_sha256=authority_sha256,
    )


def _seal_prepared(
    prepared: PreparedComparisonStratumDraftV1,
) -> SealedComparisonStratumDraftV1:
    batch = _sealed_batch(prepared)
    run = _analysis_run(prepared, batch)
    sealed_at = batch.sealed_at + timedelta(seconds=1)
    revalidation = _automation_revalidation_request(
        prepared,
        reverified_at=sealed_at,
    )
    return SealedComparisonStratumDraftV1(
        sealed_stratum_id=_id("sealed-stratum"),
        prepared_stratum=prepared,
        prepared_stratum_sha256=prepared.fingerprint,
        analysis_run=run,
        analysis_run_authority_sha256=(
            session_analysis_run_authority_fingerprint(run)
        ),
        sealed_batch=batch,
        sealed_batch_sha256=batch.fingerprint,
        ordered_authority_fingerprints=(
            SealedComparisonStratumDraftV1.ordered_authority_for(
                prepared,
                run,
                batch,
                revalidation,
            )
        ),
        sealed_at=sealed_at,
        automation_revalidation_request=revalidation,
    )


def _seal_draft(
    revisions: tuple[TaskRevisionRecord, ...] = (),
) -> SealedComparisonStratumDraftV1:
    return _seal_prepared(_prepared(revisions))


def _revalidate_prepared(
    prepared: PreparedComparisonStratumDraftV1,
) -> PreparedComparisonStratumDraftV1:
    return PreparedComparisonStratumDraftV1.revalidate_for_persistence(prepared)


def _revalidate_seal_draft(
    sealed: SealedComparisonStratumDraftV1,
) -> SealedComparisonStratumDraftV1:
    return SealedComparisonStratumDraftV1.revalidate_for_persistence(sealed)


def test_code_owned_policy_catalog_has_fixed_versions_and_hashes() -> None:
    policies = comparison_policy_set_v1()
    assert {
        identity.kind.value: identity.sha256
        for identity in (
            policies.task_type,
            policies.automation_run_binding,
            policies.matching,
            policies.censoring,
            policies.task_mix,
        )
    } == {
        "task_type": "d2dffb1b51aed20b6059f402e15ae398db3a1a7b15c02af376b74fb12ce0cd5b",
        "automation_run_binding": (
            "e227a6d3e2fce34ec33b6f9764ce3744d32b46219e4cddc13957df106c958e23"
        ),
        "matching": "de416687c03f292ebc5c09d39cbb59906316830cd754ec9854cf402dda69db71",
        "censoring": "7e23e4fa2c339b7f7b81a6959ae4c2c2ae61078967bc980cace2c566eedcffc7",
        "task_mix": "fc40bcee9f7e3546e95dba344b176778e84ad12d51b71c92e12baf1fb115c127",
    }
    assert policies.fingerprint == (
        "dcde195fd6ae0803afc4b14dec4e79e2f0918f5c1ccb36b6502bd8fa1fd8dd89"
    )


def test_policy_identity_cannot_be_caller_overridden() -> None:
    policy = comparison_policy_set_v1().matching
    forged = policy.model_copy(update={"version": "caller-policy-v2"})
    with pytest.raises(ValidationError, match="code-owned"):
        ComparisonPolicyIdentityV1.revalidate_for_persistence(forged)
    forged = policy.model_copy(update={"sha256": _id("caller-policy")})
    with pytest.raises(ValidationError, match="code-owned"):
        ComparisonPolicyIdentityV1.revalidate_for_persistence(forged)


@pytest.mark.parametrize(
    ("revisions", "state", "task_type", "bucket"),
    (
        (
            (),
            ComparisonTaskTypeStateV1.UNKNOWN_NOT_REVIEWED,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_NOT_REVIEWED,
        ),
        (
            (_task_revision("bug", task_type="bug_fix"),),
            ComparisonTaskTypeStateV1.KNOWN_REVIEWED,
            ComparisonTaskTypeV1.BUG_FIX,
            ComparisonTaskMixBucketV1.BUG_FIX,
        ),
        (
            (_task_revision("feature", task_type="feature_implementation"),),
            ComparisonTaskTypeStateV1.KNOWN_REVIEWED,
            ComparisonTaskTypeV1.FEATURE_IMPLEMENTATION,
            ComparisonTaskMixBucketV1.FEATURE_IMPLEMENTATION,
        ),
        (
            (_task_revision("research", task_type="research_design"),),
            ComparisonTaskTypeStateV1.KNOWN_REVIEWED,
            ComparisonTaskTypeV1.RESEARCH_DESIGN,
            ComparisonTaskMixBucketV1.RESEARCH_DESIGN,
        ),
        (
            (_task_revision("reviewed-unknown", task_type="unknown"),),
            ComparisonTaskTypeStateV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
        ),
        (
            (_task_revision("future-code", task_type="reserved_future_type"),),
            ComparisonTaskTypeStateV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
        ),
        (
            (
                _task_revision("ambiguous-a", task_type="bug_fix"),
                _task_revision("ambiguous-b", task_type="research_design"),
            ),
            ComparisonTaskTypeStateV1.UNKNOWN_AMBIGUOUS_CURRENT_TASKS,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_AMBIGUOUS_CURRENT_TASKS,
        ),
    ),
)
def test_task_type_state_and_visible_task_mix_bucket_are_exact(
    revisions: tuple[TaskRevisionRecord, ...],
    state: ComparisonTaskTypeStateV1,
    task_type: ComparisonTaskTypeV1 | None,
    bucket: ComparisonTaskMixBucketV1,
) -> None:
    dimensions = _prepared(revisions).dimensions
    assert dimensions.task_type_state is state
    assert dimensions.task_type is task_type
    assert dimensions.task_mix_bucket is bucket


def test_latest_revision_is_selected_before_target_session_membership() -> None:
    older = _task_revision("changing", revision=1)
    later = _task_revision(
        "changing",
        revision=2,
        session_ids=(_id("other-session"),),
    )
    selected = _selection_request((older, later))
    assert selected.current_revisions == ()


def test_post_cutoff_revision_is_excluded_and_cannot_rewrite_frozen_manifest() -> None:
    current = _task_revision("stable", revision=1)
    future = _task_revision(
        "stable",
        revision=2,
        task_type="research_design",
        created_at=PREPARED_AT + timedelta(seconds=1),
    )
    selected = _selection_request((future, current))
    assert tuple(item.task_id for item in selected.current_revisions) == (
        current.task_id,
    )
    before = _prepared((current,))
    assert before.dimensions.task_type is ComparisonTaskTypeV1.BUG_FIX
    assert before.dimensions.task_manifest.current_revisions == (
        selected.current_revisions[0],
    )


def test_task_manifest_is_complete_canonical_and_order_sensitive_to_semantics() -> None:
    second = _task_revision("z-task")
    first = _task_revision("a-task")
    prepared = _prepared((second, first))
    manifest = prepared.dimensions.task_manifest
    assert tuple(item.task_id for item in manifest.current_revisions) == tuple(
        item.task_id
        for item in sorted((first, second), key=lambda item: (item.task_id, item.revision))
    )
    changed = _task_revision("a-task", task_type="research_design")
    assert _prepared((changed, second)).dimensions.task_manifest.fingerprint != (
        manifest.fingerprint
    )


@pytest.mark.parametrize(
    "revision",
    (
        _task_revision("draft", lifecycle_state="draft"),
        _task_revision("wrong-session", session_ids=(_id("other-session"),)),
    ),
)
def test_nonreviewed_or_wrong_session_task_cannot_enter_manifest(
    revision: TaskRevisionRecord,
) -> None:
    if revision.lifecycle_state != "confirmed":
        with pytest.raises(ValueError, match="confirmed"):
            _selection_request((revision,))
    else:
        assert _selection_request((revision,)).current_revisions == ()


def test_cross_project_task_rejects_dimensions() -> None:
    task = _task_revision("cross-project", project_id=_id("other-project"))
    with pytest.raises(ValidationError, match="exact project"):
        _prepared((task,))


def test_conflicting_duplicate_task_revision_identity_rejects() -> None:
    first = _task_revision("duplicate", task_type="bug_fix")
    conflicting = TaskRevisionRecord(
        **{
            **first.model_dump(),
            "task_type": "research_design",
        }
    )
    with pytest.raises(ValueError, match="conflicting"):
        _selection_request((first, conflicting))


def test_current_task_bound_fails_closed_without_truncation() -> None:
    revisions = tuple(
        _task_revision(f"bounded-{index}")
        for index in range(MAX_COMPARISON_CURRENT_TASKS + 1)
    )
    with pytest.raises(ValueError, match=r"MAX\+1"):
        _selection_request(
            revisions,
            scanned_current_candidate_count=MAX_COMPARISON_CURRENT_TASKS + 1,
            overflow_detected=True,
        )


def test_truncated_task_query_cannot_claim_bounded_completeness() -> None:
    full_query = tuple(
        _task_revision(f"truncated-{index}")
        for index in range(MAX_COMPARISON_CURRENT_TASKS + 1)
    )
    with pytest.raises(ValueError, match=r"scan count|MAX\+1"):
        _selection_request(
            full_query[:MAX_COMPARISON_CURRENT_TASKS],
            scanned_current_candidate_count=MAX_COMPARISON_CURRENT_TASKS + 1,
            overflow_detected=True,
        )


def test_bare_selection_has_no_repository_completeness_authority() -> None:
    selected = select_current_reviewed_tasks_as_of(
        revisions=(_task_revision("bare-selection"),),
        session_id=_id("session"),
        cutoff_at=PREPARED_AT,
    )
    assert isinstance(selected, tuple)
    assert not isinstance(selected, ReviewedTaskSelectionVerificationRequestV1)


def test_repository_selection_request_rejects_scan_and_overflow_forgery() -> None:
    receipt = _selection_request((_task_revision("selection-proof"),))
    for update in (
        {"scanned_current_candidate_count": 0},
        {"overflow_detected": True},
        {"query_limit": MAX_COMPARISON_CURRENT_TASKS},
        {"claimed_query_evidence_fingerprint": _id("other-query-proof")},
    ):
        with pytest.raises(ValidationError):
            ReviewedTaskSelectionVerificationRequestV1.revalidate_for_persistence(
                receipt.model_copy(update=update)
            )


def test_selection_request_cannot_claim_repository_completeness() -> None:
    request = _selection_request((_task_revision("unverified-selection"),))
    assert not request.repository_owned
    assert not request.repository_verified
    assert not request.max_plus_one_query_verified
    assert not request.complete_not_truncated
    assert request.repository_verification_required
    for update in (
        {"repository_owned": True},
        {"repository_verified": True},
        {"max_plus_one_query_verified": True},
        {"complete_not_truncated": True},
    ):
        with pytest.raises(ValidationError):
            ReviewedTaskSelectionVerificationRequestV1.revalidate_for_persistence(
                request.model_copy(update=update)
            )


def test_reviewed_task_projection_omits_unrelated_session_ids() -> None:
    first_unrelated = _id("first-unrelated-session-membership")
    second_unrelated = _id("second-unrelated-session-membership")
    target_session = _id("session")
    identifiers = LocalArtifactIdFactory(Pseudonymizer(bytes(range(32))))
    first_membership = tuple(sorted((target_session, first_unrelated)))
    second_membership = tuple(sorted((target_session, second_unrelated)))
    first_input = identifiers.fingerprint(
        "task-revision-v1",
        (
            "accept",
            "reserved-discovery-v1",
            "bug_fix",
            _id("project"),
            *first_membership,
        ),
    )
    second_input = identifiers.fingerprint(
        "task-revision-v1",
        (
            "accept",
            "reserved-discovery-v1",
            "bug_fix",
            _id("project"),
            *second_membership,
        ),
    )
    first_revision = _task_revision(
        "minimal-projection",
        session_ids=first_membership,
    )
    first_revision = first_revision.model_copy(
        update={"input_fingerprint": first_input}
    )
    second_revision = first_revision.model_copy(
        update={
            "session_ids": second_membership,
            "input_fingerprint": second_input,
        }
    )
    assert first_revision.input_fingerprint != second_revision.input_fingerprint
    first_prepared = _prepared((first_revision,))
    second_prepared = _prepared((second_revision,))
    projection = first_prepared.dimensions.task_manifest.current_revisions[0]
    serialized = first_prepared.model_dump_json()
    assert projection.target_session_id == _id("session")
    assert projection.target_session_membership_verified
    assert projection == second_prepared.dimensions.task_manifest.current_revisions[0]
    assert first_prepared.dimensions.task_manifest == (
        second_prepared.dimensions.task_manifest
    )
    assert first_prepared.fingerprint == second_prepared.fingerprint
    assert first_prepared.model_dump_json() == second_prepared.model_dump_json()
    assert first_unrelated not in serialized
    assert second_unrelated not in second_prepared.model_dump_json()
    assert '"session_ids"' not in serialized
    assert "input_fingerprint" not in projection.model_dump_json()
    assert first_input not in serialized
    assert second_input not in second_prepared.model_dump_json()
    assert "source_session_count" not in serialized
    assert "source_revision_fingerprint" not in serialized
    with pytest.raises(ValueError, match="target membership"):
        ReviewedTaskTargetProjectionV1.from_source_revision(
            first_revision,
            target_session_id=_id("absent-target-session"),
        )


def test_private_session_display_names_never_enter_authority_or_fingerprint() -> None:
    first = ComparisonSessionAuthorityV1.from_stored_session(
        _stored_session(
            project_display_name="Reserved Example Alpha",
            session_display_name="Reserved Example One",
        )
    )
    second = ComparisonSessionAuthorityV1.from_stored_session(
        _stored_session(
            project_display_name="Reserved Example Beta",
            session_display_name="Reserved Example Two",
        )
    )
    assert first == second
    assert first.fingerprint == second.fingerprint
    serialized = first.model_dump_json()
    assert "project_display_name" not in serialized
    assert "session_display_name" not in serialized
    assert "Reserved Example" not in serialized


def test_unknown_dimensions_are_forced_unknown_and_cannot_be_populated() -> None:
    prepared = _prepared((_task_revision("known-task"),))
    dimensions = prepared.dimensions
    assert dimensions.language_state is ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    assert dimensions.complexity_state is ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    assert (
        dimensions.agent_permission_state
        is ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    )
    assert dimensions.agent_model_state is ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    assert dimensions.match_readiness is (
        ComparisonMatchReadinessV1.INSUFFICIENT_REQUIRED_STRATA
    )
    assert dimensions.censoring_readiness is (
        ComparisonCensoringReadinessV1.NO_FOLLOWUP_AUTHORITY
    )
    for field, value in (
        ("language_code", "en"),
        ("complexity_value", "high"),
        ("agent_permission_mode", "full"),
        ("agent_sandbox_mode", "unrestricted"),
        ("agent_network_mode", "enabled"),
        ("agent_model_key", "reserved-agent-model"),
        ("agent_model_revision", "reserved-agent-revision"),
    ):
        forged_dimensions = dimensions.model_copy(update={field: value})
        forged = prepared.model_copy(update={"dimensions": forged_dimensions})
        with pytest.raises(ValidationError):
            _revalidate_prepared(forged)


def test_local_analytics_grant_does_not_promote_agent_permission() -> None:
    prepared = _prepared()
    assert prepared.analysis_execution_local_only
    assert prepared.analysis_remote_requires_fresh_approval
    assert prepared.automation_grant.scope.resource_policy.route.value == "balanced"
    assert prepared.dimensions.agent_permission_mode is None
    assert prepared.dimensions.agent_sandbox_mode is None
    assert prepared.dimensions.agent_network_mode is None


def test_job_authority_excludes_progress_and_binds_lease_without_credentials() -> None:
    base = _job_record()
    progressed = _job_record(progress_completed=1)
    replaced = _job_record(progress_completed=1, lease_label="replacement")
    first = ComparisonAnalysisJobAuthorityV1.from_active_record(
        base,
        observed_at=PREPARED_AT,
    )
    second = ComparisonAnalysisJobAuthorityV1.from_active_record(
        progressed,
        observed_at=PREPARED_AT,
    )
    replacement = ComparisonAnalysisJobAuthorityV1.from_active_record(
        replaced,
        observed_at=PREPARED_AT,
    )
    assert first == second
    assert first.fingerprint == second.fingerprint
    assert first.lease_authority_fingerprint != (
        replacement.lease_authority_fingerprint
    )
    assert first.fingerprint != replacement.fingerprint
    serialized = first.model_dump_json()
    assert "lease_owner" not in serialized
    assert "lease_token" not in serialized


@pytest.mark.parametrize(
    "state",
    (
        AnalysisJobState.QUEUED,
        AnalysisJobState.COMPLETED,
        AnalysisJobState.FAILED,
        AnalysisJobState.CANCELLED,
    ),
)
def test_job_authority_requires_an_active_leased_job(state: AnalysisJobState) -> None:
    with pytest.raises(ValueError, match="active leased"):
        ComparisonAnalysisJobAuthorityV1.from_active_record(
            _job_record(state=state),
            observed_at=PREPARED_AT,
        )


def test_job_authority_rejects_an_expired_lease() -> None:
    stale = _job_record().model_copy(update={"lease_expires_at": PREPARED_AT})
    with pytest.raises(ValueError, match="unexpired"):
        ComparisonAnalysisJobAuthorityV1.from_active_record(
            stale,
            observed_at=PREPARED_AT,
        )


def test_grant_authority_excludes_housekeeping_but_revision_changes_identity() -> None:
    base = _grant_record()
    housekeeping = _grant_record(housekeeping="changed")
    assert ComparisonAutomationGrantAuthorityV1.authority_for(base) == (
        ComparisonAutomationGrantAuthorityV1.authority_for(housekeeping)
    )
    renewed_at = FLOOR
    renewed = _grant_record(
        revision=GRANT_REVISION + 1,
        renewed_at=renewed_at,
    )
    assert ComparisonAutomationGrantAuthorityV1.authority_for(base) != (
        ComparisonAutomationGrantAuthorityV1.authority_for(renewed)
    )


@pytest.mark.parametrize(
    "record",
    (
        _grant_record(state=AutomationGrantState.REVOKED),
        _grant_record(renewed_at=PREPARED_AT - AUTOMATION_GRANT_LIFETIME),
    ),
)
def test_revoked_or_expired_grant_cannot_prepare(record: AutomationGrantRecord) -> None:
    with pytest.raises(ValueError, match="active grant"):
        ComparisonAutomationGrantAuthorityV1.from_active_record(
            record,
            observed_at=PREPARED_AT,
        )


@pytest.mark.parametrize(
    "mutation",
    (
        "job_kind",
        "missing_grant",
        "provider",
        "project",
        "session",
        "metrics",
        "schema",
    ),
)
def test_prepared_authority_rejects_job_scope_substitution(mutation: str) -> None:
    prepared = _prepared()
    identity = prepared.analysis_job.identity
    update: dict[str, object]
    if mutation == "job_kind":
        update = {"kind": AnalysisJobKind.SYNTHETIC_VALIDATION}
    elif mutation == "missing_grant":
        update = {"automation_grant_id": None}
    elif mutation == "provider":
        update = {"provider": Provider.CODEX}
    elif mutation == "project":
        update = {"project_id": _id("other-project")}
    elif mutation == "session":
        update = {"session_id": _id("other-session")}
    elif mutation == "metrics":
        update = {"metric_keys": ("reserved.other.metric",)}
    else:
        update = {"provider_schema_version": "reserved-other-schema-v1"}
    forged_identity = identity.model_copy(update=update)
    forged_job = prepared.analysis_job.model_copy(update={"identity": forged_identity})
    forged = prepared.model_copy(update={"analysis_job": forged_job})
    with pytest.raises(ValidationError):
        _revalidate_prepared(forged)


def test_prepared_authority_rejects_grant_revision_and_scope_forgery() -> None:
    prepared = _prepared()
    for update in (
        {"revision": prepared.automation_grant.revision + 1},
        {"authority_sha256": _id("forged-grant-authority")},
        {"automation_grant_scope_sha256": _id("forged-grant-scope")},
    ):
        if "automation_grant_scope_sha256" in update:
            forged = prepared.model_copy(update=update)
        else:
            forged_grant = prepared.automation_grant.model_copy(update=update)
            forged = prepared.model_copy(update={"automation_grant": forged_grant})
        with pytest.raises(ValidationError):
            _revalidate_prepared(forged)


def test_prepared_authority_requires_repository_chronology_and_canonical_utc() -> None:
    prepared = _prepared()
    forged = prepared.model_copy(update={"prepared_at": FLOOR})
    with pytest.raises(ValidationError):
        _revalidate_prepared(forged)
    with pytest.raises(ValidationError, match="canonical UTC"):
        PreparedComparisonStratumDraftV1(
            **{
                **prepared.model_dump(),
                "prepared_at": PREPARED_AT.astimezone(timezone(timedelta(hours=1))),
            }
        )


def test_prepared_fingerprint_is_stable_and_moves_with_task_or_policy() -> None:
    baseline = _prepared((_task_revision("fingerprint", task_type="bug_fix"),))
    replay = _prepared((_task_revision("fingerprint", task_type="bug_fix"),))
    changed = _prepared(
        (_task_revision("fingerprint", task_type="research_design"),)
    )
    assert baseline.fingerprint == replay.fingerprint
    assert baseline.fingerprint != changed.fingerprint
    forged_policy = baseline.policies.matching.model_copy(
        update={"sha256": _id("other-matching-policy")}
    )
    forged_set = baseline.policies.model_copy(update={"matching": forged_policy})
    forged = baseline.model_copy(update={"policies": forged_set})
    with pytest.raises(ValidationError):
        _revalidate_prepared(forged)


def test_prepared_cross_role_collision_rejects() -> None:
    prepared = _prepared()
    with pytest.raises(ValidationError, match="role-separated"):
        _expected_run_request(
            prepared.analysis_job,
            run_id=prepared.analysis_job.job_id,
        )


def test_prepared_id_cannot_alias_dimensions_fingerprint() -> None:
    prepared = _prepared()
    forged = prepared.model_copy(
        update={"prepared_stratum_id": prepared.dimensions.fingerprint}
    )
    with pytest.raises(ValidationError, match="role-separated"):
        _revalidate_prepared(forged)


def test_arbitrary_expected_run_remains_untrusted_and_cannot_claim_verification() -> None:
    prepared = _prepared()
    arbitrary = _expected_run_request(
        prepared.analysis_job,
        run_id=_id("not-the-derived-job-run"),
    )
    forged = prepared.model_copy(update={"expected_run_request": arbitrary})
    structurally_valid = _revalidate_prepared(forged)
    assert structurally_valid.expected_analysis_run_id == _id(
        "not-the-derived-job-run"
    )
    assert not structurally_valid.expected_run_request.repository_verified
    assert structurally_valid.expected_run_request.repository_verification_required
    assert not structurally_valid.repository_authority_verified
    assert not structurally_valid.repository_owned
    assert not structurally_valid.sealed
    for update in (
        {"repository_verified": True},
        {"repository_owned": True},
        {"sealed": True},
    ):
        with pytest.raises(ValidationError):
            ExpectedAnalysisRunVerificationRequestV1.revalidate_for_persistence(
                arbitrary.model_copy(update=update)
            )


def test_expected_run_request_rejects_code_owned_input_rewrite() -> None:
    request = _prepared().expected_run_request
    with pytest.raises(ValidationError):
        ExpectedAnalysisRunVerificationRequestV1.revalidate_for_persistence(
            request.model_copy(update={"idempotency_key": "reserved-caller-key"})
        )


def test_seal_draft_binds_exact_completed_run_batch_and_frozen_task() -> None:
    task = _task_revision("sealed", task_type="feature_implementation")
    sealed = _seal_draft((task,))
    assert sealed.prepared_stratum.dimensions.task_type is (
        ComparisonTaskTypeV1.FEATURE_IMPLEMENTATION
    )
    assert sealed.analysis_run.draft.run_id == (
        sealed.prepared_stratum.expected_analysis_run_id
    )
    assert sealed.sealed_batch_sha256 == sealed.sealed_batch.fingerprint
    assert not sealed.prepared_stratum.repository_owned
    assert not sealed.prepared_stratum.repository_authority_verified
    assert not sealed.prepared_stratum.sealed
    assert sealed.prepared_stratum.repository_verification_required
    assert not sealed.repository_owned
    assert not sealed.repository_authority_verified
    assert not sealed.run_authority_verified
    assert not sealed.batch_authority_verified
    assert not sealed.sealed
    assert sealed.repository_verification_required
    assert sealed.ordered_authority_fingerprints == (
        SealedComparisonStratumDraftV1.ordered_authority_for(
            sealed.prepared_stratum,
            sealed.analysis_run,
            sealed.sealed_batch,
            sealed.automation_revalidation_request,
        )
    )
    assert _revalidate_seal_draft(sealed) == sealed


@pytest.mark.parametrize(
    ("target", "field", "value"),
    (
        ("run", "run_id", _id("other-run")),
        ("run", "analysis_profile_key", "reserved-other-profile"),
        ("run", "metric_pack_version", 999),
        ("run", "selected_metric_keys", ("reserved.other.metric",)),
        ("run", "redactor_version", "reserved-other-redactor-v1"),
        ("run", "source_schema_version", "reserved-other-schema-v1"),
        ("run", "local_only", False),
        ("input", "analysis_run_request_fingerprint", _id("other-request")),
        ("input", "metric_engine_version", "reserved-other-engine-v1"),
        ("input", "model_plan_fingerprint", _id("other-model-plan")),
    ),
)
def test_seal_draft_rejects_run_and_input_lineage_mismatch(
    target: str,
    field: str,
    value: object,
) -> None:
    sealed = _seal_draft()
    if target == "run":
        forged_draft = sealed.analysis_run.draft.model_copy(update={field: value})
        forged_run = sealed.analysis_run.model_copy(update={"draft": forged_draft})
        forged = sealed.model_copy(update={"analysis_run": forged_run})
    else:
        request = sealed.sealed_batch.completion_request
        forged_input = request.analysis_input.model_copy(update={field: value})
        forged_request = request.model_copy(update={"analysis_input": forged_input})
        forged_batch = sealed.sealed_batch.model_copy(
            update={"completion_request": forged_request}
        )
        forged = sealed.model_copy(update={"sealed_batch": forged_batch})
    with pytest.raises(ValidationError):
        _revalidate_seal_draft(forged)


@pytest.mark.parametrize(
    "status",
    (AnalysisRunStatus.RUNNING, AnalysisRunStatus.FAILED),
)
def test_seal_draft_requires_completed_run(status: AnalysisRunStatus) -> None:
    sealed = _seal_draft()
    run = _analysis_run(sealed.prepared_stratum, sealed.sealed_batch, status=status)
    forged = sealed.model_copy(
        update={
            "analysis_run": run,
            "analysis_run_authority_sha256": (
                session_analysis_run_authority_fingerprint(run)
            ),
            "ordered_authority_fingerprints": (
                SealedComparisonStratumDraftV1.ordered_authority_for(
                    sealed.prepared_stratum,
                    run,
                    sealed.sealed_batch,
                    sealed.automation_revalidation_request,
                )
            ),
        }
    )
    with pytest.raises(ValidationError, match="completed"):
        _revalidate_seal_draft(forged)


def test_seal_draft_rejects_preexisting_run_and_other_same_scope_batch() -> None:
    sealed = _seal_draft()
    old_run = _analysis_run(
        sealed.prepared_stratum,
        sealed.sealed_batch,
        started_at=PREPARED_AT - timedelta(seconds=1),
    )
    forged_old = sealed.model_copy(
        update={
            "analysis_run": old_run,
            "analysis_run_authority_sha256": (
                session_analysis_run_authority_fingerprint(old_run)
            ),
            "ordered_authority_fingerprints": (
                SealedComparisonStratumDraftV1.ordered_authority_for(
                    sealed.prepared_stratum,
                    old_run,
                    sealed.sealed_batch,
                    sealed.automation_revalidation_request,
                )
            ),
        }
    )
    with pytest.raises(ValidationError, match="retrospectively"):
        _revalidate_seal_draft(forged_old)

    other_batch = _sealed_batch(
        sealed.prepared_stratum,
        run_id=_id("same-scope-other-run"),
    )
    forged_batch = sealed.model_copy(
        update={
            "sealed_batch": other_batch,
            "sealed_batch_sha256": other_batch.fingerprint,
            "ordered_authority_fingerprints": (
                SealedComparisonStratumDraftV1.ordered_authority_for(
                    sealed.prepared_stratum,
                    sealed.analysis_run,
                    other_batch,
                    sealed.automation_revalidation_request,
                )
            ),
        }
    )
    with pytest.raises(ValidationError, match="retrospective"):
        _revalidate_seal_draft(forged_batch)


def test_seal_draft_rejects_prepared_batch_and_time_substitution() -> None:
    sealed = _seal_draft()
    other_prepared = _prepared((_task_revision("other-prepared"),))
    for update in (
        {"prepared_stratum_sha256": _id("other-prepared-fingerprint")},
        {"analysis_run_authority_sha256": _id("other-run-authority")},
        {"sealed_batch_sha256": _id("other-batch-fingerprint")},
        {"sealed_at": FLOOR},
        {"prepared_stratum": other_prepared},
    ):
        with pytest.raises(ValidationError):
            _revalidate_seal_draft(sealed.model_copy(update=update))


def test_seal_draft_requires_live_automation_reverification() -> None:
    sealed = _seal_draft()
    stale_revalidation = sealed.automation_revalidation_request.model_copy(
        update={"reverified_at": sealed.sealed_at - timedelta(seconds=1)}
    )
    forged = sealed.model_copy(
        update={"automation_revalidation_request": stale_revalidation}
    )
    with pytest.raises(ValidationError, match="reverified|fingerprint"):
        _revalidate_seal_draft(forged)
    expired_at = sealed.prepared_stratum.analysis_job.lease_expires_at
    expired_revalidation = sealed.automation_revalidation_request.model_copy(
        update={"reverified_at": expired_at}
    )
    forged = sealed.model_copy(
        update={
            "sealed_at": expired_at,
            "automation_revalidation_request": expired_revalidation,
        }
    )
    with pytest.raises(ValidationError, match="live|reverified|fingerprint"):
        _revalidate_seal_draft(forged)


def test_boolean_cannot_bypass_expired_or_substituted_seal_authority() -> None:
    sealed = _seal_draft()
    for update in (
        {
            "current_job_lease_expires_at": sealed.sealed_at,
            "reverified_at": sealed.sealed_at,
        },
        {"current_job_state": AnalysisJobState.COMPLETED},
        {"current_job_lease_authority_fingerprint": _id("other-live-lease")},
        {"current_grant_revision": sealed.prepared_stratum.automation_grant.revision + 1},
        {"current_grant_authority_fingerprint": _id("other-live-grant")},
    ):
        forged_receipt = sealed.automation_revalidation_request.model_copy(update=update)
        forged = sealed.model_copy(update={"automation_revalidation_request": forged_receipt})
        with pytest.raises(ValidationError):
            _revalidate_seal_draft(forged)


def test_revalidation_request_cannot_claim_repository_verification() -> None:
    request = _seal_draft().automation_revalidation_request
    assert not request.repository_owned
    assert not request.repository_verified
    assert not request.current_rows_rehydrated
    assert not request.ephemeral_lease_proof_verified_not_persisted
    assert request.repository_verification_required
    for update in (
        {"repository_owned": True},
        {"repository_verified": True},
        {"current_rows_rehydrated": True},
        {"ephemeral_lease_proof_verified_not_persisted": True},
    ):
        with pytest.raises(ValidationError):
            AutomationRevalidationRequestV1.revalidate_for_persistence(
                request.model_copy(update=update)
            )


def test_seal_draft_rejects_ordered_graph_and_cross_role_collision() -> None:
    sealed = _seal_draft()
    reversed_graph = tuple(reversed(sealed.ordered_authority_fingerprints))
    with pytest.raises(ValidationError, match="exact graph"):
        _revalidate_seal_draft(
            sealed.model_copy(
                update={"ordered_authority_fingerprints": reversed_graph}
            )
        )
    with pytest.raises(ValidationError, match="role-separated"):
        _revalidate_seal_draft(
            sealed.model_copy(
                update={
                    "sealed_stratum_id": sealed.sealed_batch.sealed_batch_id,
                }
            )
        )


@pytest.mark.parametrize("nested_role", ("completion", "observation"))
def test_global_role_separation_reaches_nested_sealed_graph(
    nested_role: str,
) -> None:
    prepared = _prepared()
    batch = _sealed_batch(prepared)
    collision = (
        batch.completion_request.completion_request_id
        if nested_role == "completion"
        else batch.seal_draft.observation_batch.observations[0].observation_id
    )
    forged_prepared = prepared.model_copy(
        update={"prepared_stratum_id": collision}
    )
    assert _revalidate_prepared(forged_prepared) == forged_prepared
    with pytest.raises(ValidationError, match="role-separated"):
        _seal_prepared(forged_prepared)


@pytest.mark.parametrize(
    "field",
    (
        "source_authority_verified",
        "product_capture_allowed",
        "product_history_eligible",
        "pair_matching_allowed",
        "comparison_allowed",
        "aggregate_materialization_allowed",
        "snapshot_materialization_allowed",
        "recommendation_allowed",
        "recommendation_outcome_evaluation_allowed",
        "causal_claim_allowed",
        "activation_allowed",
        "legacy_inference_allowed",
        "backfill_allowed",
        "remote_processing_allowed",
        "private_export_allowed",
        "team_share_allowed",
    ),
)
def test_prepared_and_sealed_downstream_capabilities_cannot_be_promoted(
    field: str,
) -> None:
    prepared = _prepared()
    with pytest.raises(ValidationError):
        _revalidate_prepared(prepared.model_copy(update={field: True}))
    sealed = _seal_draft()
    with pytest.raises(ValidationError):
        _revalidate_seal_draft(sealed.model_copy(update={field: True}))


def test_recursive_persistence_revalidation_blocks_nested_model_copy_tampering() -> None:
    sealed = _seal_draft((_task_revision("nested"),))
    forged_dimensions = sealed.prepared_stratum.dimensions.model_copy(
        update={"language_code": "en"}
    )
    forged_prepared = sealed.prepared_stratum.model_copy(
        update={"dimensions": forged_dimensions}
    )
    forged = sealed.model_copy(update={"prepared_stratum": forged_prepared})
    with pytest.raises(ValidationError):
        _revalidate_seal_draft(forged)


def test_recursive_persistence_revalidation_blocks_model_construct_tampering() -> None:
    prepared = _prepared()
    raw = prepared.dimensions.model_dump(mode="python")
    raw["language_code"] = "en"
    forged_dimensions = ComparisonStratumDimensionsV1.model_construct(**raw)
    forged = prepared.model_copy(update={"dimensions": forged_dimensions})
    with pytest.raises(ValidationError):
        _revalidate_prepared(forged)


def test_serialized_receipts_are_content_free_and_omit_ephemeral_authority() -> None:
    sealed = _seal_draft((_task_revision("privacy"),))
    serialized = sealed.model_dump_json()
    forbidden = (
        "project_display_name",
        "session_display_name",
        "lease_owner",
        "lease_token",
        "prompt_text",
        "response_text",
        "transcript",
        "excerpt",
        "source_path",
        "credential",
    )
    assert all(value not in serialized for value in forbidden)


def test_repository_protocol_exposes_only_opaque_automation_writes_and_reads() -> None:
    methods = {
        name
        for name, value in inspect.getmembers(
            TemporalComparisonStratumRepositoryV1,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert methods == {
        "draft_automation_stratum",
        "draft_automation_seal",
        "get_prepared_stratum_draft",
        "get_prepared_stratum_draft_for_job",
        "get_sealed_stratum_draft",
        "get_sealed_stratum_draft_for_run",
        "get_sealed_stratum_draft_for_batch",
    }
    prepare = inspect.signature(
        TemporalComparisonStratumRepositoryV1.draft_automation_stratum
    )
    seal = inspect.signature(
        TemporalComparisonStratumRepositoryV1.draft_automation_seal
    )
    assert tuple(prepare.parameters) == (
        "self",
        "prepared_scope_id",
        "authority",
    )
    assert tuple(seal.parameters) == (
        "self",
        "prepared_stratum_id",
        "sealed_batch_id",
        "authority",
    )
    forbidden_terms = {
        "task",
        "language",
        "complexity",
        "permission",
        "model",
        "policy",
        "clock",
        "fingerprint",
        "run_id",
        "backfill",
        "manual",
        "update",
        "delete",
        "list",
    }
    public_text = " ".join(sorted(methods))
    assert all(term not in public_text for term in forbidden_terms)


def test_lease_authority_is_ephemeral_and_content_free() -> None:
    authority = _AutomationComparisonLeaseAuthorityV1(
        job_id=_id("analysis-job"),
        automation_grant_id=_id("automation-grant"),
        lease_owner=_id("lease-owner"),
        lease_token=_id("lease-token"),
    )
    assert _id("lease-owner") not in repr(authority)
    assert _id("lease-token") not in repr(authority)
    assert not is_dataclass(authority)
    assert not hasattr(authority, "__dict__")
    assert "lease_owner" not in _prepared().model_dump_json()
    for dataclass_serializer in (asdict, astuple):
        with pytest.raises(TypeError) as error:
            dataclass_serializer(authority)
        assert _id("lease-owner") not in str(error.value)
        assert _id("lease-token") not in str(error.value)
    for operation in (
        lambda: authority.model_dump(),
        lambda: authority.model_dump_json(),
        lambda: pickle.dumps(authority),
        lambda: copy.copy(authority),
        lambda: copy.deepcopy(authority),
    ):
        with pytest.raises(TypeError, match="cannot be (serialized|copied)") as error:
            operation()
        assert _id("lease-owner") not in str(error.value)
        assert _id("lease-token") not in str(error.value)


def test_policy_kind_is_closed_and_unknown_is_not_a_matchable_value() -> None:
    with pytest.raises(ValidationError):
        ComparisonPolicyIdentityV1(
            kind="caller_matching",
            version="caller-v1",
            sha256=_id("caller"),
        )
    prepared = _prepared()
    assert prepared.dimensions.task_type is None
    assert not prepared.pair_matching_allowed
    assert not prepared.comparison_allowed
