from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
import hashlib
import inspect
import math

import pytest
from pydantic import ValidationError

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
    MAX_OBSERVATIONS,
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
    MAX_REPOSITORY_GRAPH_FINGERPRINTS,
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
    SyntheticTemporalCompletionRequestV1,
    TemporalHistoryPersistenceRepositoryV1,
    TemporalSourceAuthorityStateV1,
    automation_grant_authority_version,
)
from prompt_enhancer.domain import Provider


FLOOR = datetime(2044, 2, 3, 10, tzinfo=UTC)
METRIC = "quality.requirement_coverage"
GRANT_REVISION = 3


def _id(label: str) -> str:
    return hashlib.sha256(f"reserved-temporal-persistence:{label}".encode()).hexdigest()


def _root() -> TemporalHistoryRootReceipt:
    return TemporalHistoryRootReceipt(
        root_receipt_id=_id("history-root"),
        project_id=_id("project"),
        epoch_ordinal=1,
        history_floor_at=FLOOR,
        issued_at=FLOOR,
    )


def _selection(
    root: TemporalHistoryRootReceipt,
    *,
    authority_id: str | None = None,
    authority_fingerprint: str | None = None,
    authority_version: str | None = None,
    source: ProjectMetricSelectionSource = ProjectMetricSelectionSource.AUTOMATION_GRANT,
    authority_kind: ProjectMetricSelectionAuthorityKind = (
        ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT
    ),
) -> ProjectMetricSelectionRevisionV2:
    at = FLOOR + timedelta(minutes=1)
    return ProjectMetricSelectionRevisionV2(
        selection_revision_id=_id("selection"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=1,
        selected_metric_keys=(METRIC,),
        source=source,
        effective_at=at,
        recorded_at=at,
        metric_pack_key="reserved_quality_pack",
        metric_pack_version=1,
        metric_pack_sha256=_id("metric-pack"),
        metric_catalog_version="reserved-metric-catalog-v1",
        metric_catalog_sha256=_id("metric-catalog"),
        source_authority_kind=authority_kind,
        source_authority_id=authority_id or _id("automation-grant"),
        source_authority_fingerprint=(
            authority_fingerprint or _id("automation-grant-fingerprint")
        ),
        source_authority_version=(
            authority_version or automation_grant_authority_version(GRANT_REVISION)
        ),
    )


def _scope() -> RepositoryPreparedTemporalScopeV1:
    root = _root()
    selection = _selection(root)
    return RepositoryPreparedTemporalScopeV1(
        prepared_scope_id=_id("prepared-scope"),
        history_root=root,
        selection_revision=selection,
        automation_grant_id=selection.source_authority_id,
        automation_grant_fingerprint=selection.source_authority_fingerprint,
        automation_grant_revision=GRANT_REVISION,
        prepared_at=FLOOR + timedelta(minutes=2),
    )


def _input(
    scope: RepositoryPreparedTemporalScopeV1,
    *,
    provider: Provider = Provider.SYNTHETIC,
    provider_version: str = "reserved-provider-v1",
    capture_contract_version: str = "reserved-direct-capture-v2",
    consent_policy_version: str = "reserved-consent-v1",
) -> AnalysisInputReceiptV2:
    selection = scope.selection_revision
    started = scope.prepared_at + timedelta(minutes=1)
    ended = started + timedelta(minutes=1)
    completed = ended + timedelta(seconds=1)
    captured = completed + timedelta(seconds=1)
    selected_root = _id("selected-window")
    source_root = _id("source-manifest")
    return AnalysisInputReceiptV2(
        input_receipt_id=_id("analysis-input"),
        root_receipt_id=scope.history_root.root_receipt_id,
        root_receipt_fingerprint=scope.history_root.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        selection_scope_fingerprint=selection.metric_set_fingerprint,
        analysis_run_id=_id("analysis-run"),
        analysis_run_fingerprint=_id("analysis-run-fingerprint"),
        analysis_run_fingerprint_version="reserved-analysis-run-v1",
        analysis_run_request_fingerprint=_id("analysis-run-request"),
        project_id=scope.history_root.project_id,
        session_id=_id("session"),
        selected_metric_keys=selection.selected_metric_keys,
        analysis_window_fingerprint=_id("analysis-window"),
        selected_window_manifest_root=selected_root,
        selected_window_manifest_entry_count=1,
        selected_window_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.selected_manifest_identity(
                root=selected_root, entry_count=1
            )
        ),
        post_floor_observed_allowlisted_source_manifest_root=source_root,
        post_floor_observed_allowlisted_source_manifest_entry_count=1,
        post_floor_observed_allowlisted_source_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.observed_source_manifest_identity(
                root=source_root, entry_count=1
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
        capture_contract_version=capture_contract_version,
        analysis_profile_key="reserved_profile",
        analysis_profile_version=1,
        analysis_profile_sha256=_id("analysis-profile"),
        metric_pack_key=selection.metric_pack_key,
        metric_pack_version=selection.metric_pack_version,
        metric_pack_sha256=selection.metric_pack_sha256,
        metric_engine_version="reserved-engine-v1",
        metric_engine_sha256=_id("metric-engine"),
        metric_catalog_version=selection.metric_catalog_version,
        metric_catalog_sha256=selection.metric_catalog_sha256,
        consent_policy_version=consent_policy_version,
        consent_receipt_id=_id("consent"),
        consent_receipt_fingerprint=_id("consent-fingerprint"),
        privacy_policy_version="reserved-privacy-v1",
        provider=provider,
        provider_version=provider_version,
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
        model_plan_fingerprint=_id("no-model-plan"),
        analysis_run_schema_version=1,
        full_run_metric_observation_count=1,
    )


def _request(**input_overrides: str) -> SyntheticTemporalCompletionRequestV1:
    scope = _scope()
    analysis_input = _input(scope, **input_overrides)
    return SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("completion-request"),
        prepared_scope=scope,
        analysis_input=analysis_input,
        analysis_run_id=analysis_input.analysis_run_id,
    )


def _identity(input_receipt: AnalysisInputReceiptV2) -> MetricComparisonIdentity:
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
        preprocessing_version=input_receipt.preprocessing_version,
        preprocessing_sha256=input_receipt.preprocessing_sha256,
        calibration_version="not-calibrated-v1",
        calibration_sha256=_id("not-calibrated"),
        router_version=input_receipt.router_version,
        router_sha256=input_receipt.router_sha256,
        redactor_version=input_receipt.redactor_version,
        redactor_sha256=input_receipt.redactor_sha256,
        provider=input_receipt.provider,
        provider_adapter_version=input_receipt.provider_adapter_version,
        provider_schema_version=input_receipt.provider_schema_version,
        source_schema_version=input_receipt.source_schema_version,
        content_schema_version=input_receipt.content_schema_version,
        privacy_policy_version=input_receipt.privacy_policy_version,
    )


def _seal_draft(**input_overrides: str) -> RepositoryTemporalBatchSealDraft:
    scope = _scope()
    input_receipt = _input(scope, **input_overrides)
    revision = SessionRevisionReceiptV3.from_direct_input(
        revision_id=_id("session-revision"),
        input_receipt=input_receipt,
        revision_ordinal=1,
        effective_time_basis=RevisionEffectiveTimeBasis.SESSION_ENDED_AT,
    )
    observation = TemporalMetricObservationV2(
        observation_id=_id("observation"),
        revision_id=revision.revision_id,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        comparison_identity=_identity(input_receipt),
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=FractionObservationValue(numerator=1, denominator=1),
        evidence_coverage_eligibility=EvidenceCoverageEligibility.ELIGIBLE,
        evidence_coverage_state=EvidenceCoverageState.KNOWN,
        evidence_numerator=0,
        evidence_denominator=0,
        observed_at=input_receipt.captured_at + timedelta(seconds=1),
    )
    batch = TemporalObservationBatchV2(
        batch_id=_id("batch"),
        root_receipt_id=scope.history_root.root_receipt_id,
        root_receipt_fingerprint=scope.history_root.fingerprint,
        project_id=scope.history_root.project_id,
        session_id=input_receipt.session_id,
        revision_id=revision.revision_id,
        revision_fingerprint=revision.fingerprint,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        selection_revision_id=scope.selection_revision.selection_revision_id,
        selection_revision_fingerprint=scope.selection_revision.fingerprint,
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=input_receipt.selected_metric_keys,
        observations=(observation,),
        recorded_at=observation.observed_at + timedelta(seconds=1),
    )
    return RepositoryTemporalBatchSealDraft(
        seal_draft_id=_id("seal-draft"),
        history_root=scope.history_root,
        selection_revision=scope.selection_revision,
        analysis_input=input_receipt,
        session_revision=revision,
        observation_batch=batch,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
        ordered_observation_ids=(observation.observation_id,),
        ordered_observation_fingerprints=(observation.fingerprint,),
        requested_repository_verifier_version="reserved-repository-verifier-v1",
        requested_repository_verifier_fingerprint=_id("repository-verifier"),
        drafted_at=batch.recorded_at + timedelta(seconds=1),
    )


def _sealed(**input_overrides: str) -> RepositorySealedTemporalBatchV1:
    draft = _seal_draft(**input_overrides)
    request = _request(**input_overrides)
    return RepositorySealedTemporalBatchV1(
        sealed_batch_id=_id("sealed-batch"),
        completion_request=request,
        prepared_scope_fingerprint=request.prepared_scope.fingerprint,
        completion_request_fingerprint=request.fingerprint,
        seal_draft=draft,
        seal_draft_fingerprint=draft.fingerprint,
        ordered_graph_fingerprints=RepositorySealedTemporalBatchV1.ordered_graph_for(
            request, draft
        ),
        repository_verifier_version=draft.requested_repository_verifier_version,
        repository_verifier_fingerprint=(
            draft.requested_repository_verifier_fingerprint
        ),
        sealed_at=draft.drafted_at + timedelta(seconds=1),
    )


def _raw_ordered_graph(
    request: SyntheticTemporalCompletionRequestV1,
    draft: RepositoryTemporalBatchSealDraft,
) -> tuple[str, ...]:
    return (
        request.prepared_scope.fingerprint,
        request.fingerprint,
        draft.history_root.fingerprint,
        draft.selection_revision.fingerprint,
        draft.analysis_input.fingerprint,
        draft.session_revision.fingerprint,
        draft.observation_batch.fingerprint,
        *(item.fingerprint for item in draft.observation_batch.observations),
    )


def _rebuild_draft_with_observations(
    base: RepositoryTemporalBatchSealDraft,
    observations: tuple[TemporalMetricObservationV2, ...],
    *,
    revision: SessionRevisionReceiptV3 | None = None,
) -> RepositoryTemporalBatchSealDraft:
    checked_revision = base.session_revision if revision is None else revision
    batch = TemporalObservationBatchV2(
        **{
            **base.observation_batch.model_dump(),
            "revision_id": checked_revision.revision_id,
            "revision_fingerprint": checked_revision.fingerprint,
            "observations": tuple(item.model_dump() for item in observations),
        }
    )
    return RepositoryTemporalBatchSealDraft(
        **{
            **base.model_dump(),
            "session_revision": checked_revision.model_dump(),
            "observation_batch": batch.model_dump(),
            "ordered_observation_ids": tuple(
                item.observation_id for item in observations
            ),
            "ordered_observation_fingerprints": tuple(
                item.fingerprint for item in observations
            ),
        }
    )


def _assert_graph_collision_rejected(
    request: SyntheticTemporalCompletionRequestV1,
    draft: RepositoryTemporalBatchSealDraft,
) -> None:
    assert RepositoryTemporalBatchSealDraft.revalidate_for_persistence(draft) == draft
    with pytest.raises(ValueError, match="role-separated"):
        RepositorySealedTemporalBatchV1.ordered_graph_for(request, draft)
    with pytest.raises(ValidationError, match="role-separated"):
        RepositorySealedTemporalBatchV1(
            sealed_batch_id=_id("collision-sealed-batch"),
            completion_request=request,
            prepared_scope_fingerprint=request.prepared_scope.fingerprint,
            completion_request_fingerprint=request.fingerprint,
            seal_draft=draft,
            seal_draft_fingerprint=draft.fingerprint,
            ordered_graph_fingerprints=_raw_ordered_graph(request, draft),
            repository_verifier_version=draft.requested_repository_verifier_version,
            repository_verifier_fingerprint=(
                draft.requested_repository_verifier_fingerprint
            ),
            sealed_at=draft.drafted_at + timedelta(seconds=1),
        )
    forged = _sealed().model_copy(
        update={
            "completion_request": request,
            "prepared_scope_fingerprint": request.prepared_scope.fingerprint,
            "completion_request_fingerprint": request.fingerprint,
            "seal_draft": draft,
            "seal_draft_fingerprint": draft.fingerprint,
            "ordered_graph_fingerprints": _raw_ordered_graph(request, draft),
            "repository_verifier_version": (
                draft.requested_repository_verifier_version
            ),
            "repository_verifier_fingerprint": (
                draft.requested_repository_verifier_fingerprint
            ),
            "sealed_at": draft.drafted_at + timedelta(seconds=1),
        }
    )
    with pytest.raises(ValidationError, match="role-separated"):
        RepositorySealedTemporalBatchV1.revalidate_for_persistence(forged)


def test_prepared_scope_exactly_binds_repository_graph_and_grant_revision() -> None:
    scope = _scope()
    assert scope.selection_revision.source_authority_id == scope.automation_grant_id
    assert (
        scope.selection_revision.source_authority_fingerprint
        == scope.automation_grant_fingerprint
    )
    assert scope.selection_revision.source_authority_version == (
        automation_grant_authority_version(scope.automation_grant_revision)
    )
    assert scope.repository_owned is scope.repository_graph_verified is True
    assert scope.selection_authority_verified is scope.sealed is True
    assert scope.repository_authority_scope == "graph-selection-only-v1"
    assert scope.structurally_constructible_not_capability is True
    assert scope.repository_return_required is True
    assert scope.capture_authority_verified is False
    assert scope.product_capture_allowed is False
    assert scope.product_history_eligible is False
    assert scope.comparison_allowed is scope.snapshot_materialization_allowed is False
    assert scope.activation_allowed is scope.private_export_allowed is False
    assert scope.team_share_allowed is scope.remote_processing_allowed is False
    assert scope.fingerprint == RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(
        scope
    ).fingerprint


def test_repository_graph_capacity_is_fixed_nodes_plus_all_observations() -> None:
    assert MAX_REPOSITORY_GRAPH_FINGERPRINTS == 7 + MAX_OBSERVATIONS == 107


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("automation_grant_id", _id("other-grant")),
        ("automation_grant_fingerprint", _id("other-grant-fingerprint")),
        ("automation_grant_revision", 4),
        ("prepared_at", FLOOR),
    ),
)
def test_prepared_scope_rejects_mismatched_grant_and_chronology(
    field: str, value: object
) -> None:
    scope = _scope()
    with pytest.raises(ValidationError):
        RepositoryPreparedTemporalScopeV1(
            **{**scope.model_dump(), field: value}
        )
    forged = scope.model_copy(update={field: value})
    with pytest.raises(ValidationError):
        RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(forged)


def test_prepared_scope_rejects_nested_graph_and_non_automation_authority() -> None:
    scope = _scope()
    changed_root = scope.history_root.model_copy(update={"project_id": _id("other-project")})
    changed_selection = scope.selection_revision.model_copy(
        update={"root_receipt_fingerprint": _id("other-root")}
    )
    for nested in (
        {"history_root": changed_root},
        {"selection_revision": changed_selection},
    ):
        forged = scope.model_copy(update=nested)
        with pytest.raises(ValidationError):
            RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(forged)

    root = _root()
    manual = _selection(
        root,
        source=ProjectMetricSelectionSource.EXPLICIT_PROJECT_CONFIGURATION,
        authority_kind=ProjectMetricSelectionAuthorityKind.PROJECT_CONFIGURATION,
    )
    with pytest.raises(ValidationError):
        RepositoryPreparedTemporalScopeV1(
            **{
                **scope.model_dump(),
                "history_root": root,
                "selection_revision": manual,
                "automation_grant_id": manual.source_authority_id,
                "automation_grant_fingerprint": manual.source_authority_fingerprint,
            }
        )


@pytest.mark.parametrize(
    "revision",
    (True, 0, -1, -0.0, 1.0, math.inf, math.nan),
)
def test_grant_revision_rejects_non_integer_nonfinite_and_negative_zero(
    revision: object,
) -> None:
    with pytest.raises((ValidationError, ValueError)):
        RepositoryPreparedTemporalScopeV1(
            **{**_scope().model_dump(), "automation_grant_revision": revision}
        )
    with pytest.raises(ValueError):
        automation_grant_authority_version(revision)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad_time",
    (
        datetime(2044, 2, 3, 10),
        datetime(2044, 2, 3, 11, tzinfo=timezone(timedelta(hours=1))),
    ),
)
def test_repository_time_is_exact_utc(bad_time: datetime) -> None:
    with pytest.raises(ValidationError):
        RepositoryPreparedTemporalScopeV1(
            **{**_scope().model_dump(), "prepared_at": bad_time}
        )


@pytest.mark.parametrize(
    "bad_version",
    (
        "file:/reserved/path",
        "https://reserved.example/path",
        "reserved\\path",
        "reserved\x00value",
        "reserved..value",
    ),
)
def test_grant_authority_version_rejects_path_uri_and_control_text(
    bad_version: str,
) -> None:
    root = _root()
    with pytest.raises(ValidationError):
        _selection(root, authority_version=bad_version)


def test_structural_scope_cannot_promote_forbidden_capabilities() -> None:
    scope = _scope()
    for field in (
        "capture_authority_verified",
        "product_capture_allowed",
        "product_history_eligible",
        "comparison_allowed",
        "snapshot_materialization_allowed",
        "activation_allowed",
        "private_export_allowed",
        "team_share_allowed",
    ):
        with pytest.raises(ValidationError):
            RepositoryPreparedTemporalScopeV1(
                **{**scope.model_dump(), field: True}
            )
        forged = scope.model_copy(update={field: True})
        with pytest.raises(ValidationError):
            RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(forged)
    assert "returned" in (RepositoryPreparedTemporalScopeV1.__doc__ or "").lower()


@pytest.mark.parametrize(
    "colliding_value",
    (
        _id("automation-grant"),
        _id("automation-grant-fingerprint"),
        _id("history-root"),
        _id("project"),
        _id("selection"),
    ),
)
def test_prepared_scope_id_is_role_separated_from_grant_root_project_and_selection(
    colliding_value: str,
) -> None:
    scope = _scope()
    with pytest.raises(ValidationError, match="role-separated"):
        RepositoryPreparedTemporalScopeV1(
            **{**scope.model_dump(), "prepared_scope_id": colliding_value}
        )


def test_prepared_scope_rejects_root_predecessor_collision_recursively() -> None:
    scope = _scope()
    later_root = TemporalHistoryRootReceipt(
        **{
            **scope.history_root.model_dump(),
            "epoch_ordinal": 2,
            "predecessor_root_id": scope.prepared_scope_id,
            "predecessor_root_fingerprint": _id("prior-root-fingerprint"),
        }
    )
    later_selection = ProjectMetricSelectionRevisionV2(
        **{
            **scope.selection_revision.model_dump(),
            "root_receipt_fingerprint": later_root.fingerprint,
        }
    )
    forged = scope.model_copy(
        update={"history_root": later_root, "selection_revision": later_selection}
    )
    with pytest.raises(ValidationError, match="role-separated"):
        RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(forged)


@pytest.mark.parametrize(
    ("predecessor_id", "predecessor_fingerprint"),
    (
        (_id("automation-grant"), _id("prior-selection-fingerprint")),
        (_id("prior-selection"), _id("automation-grant-fingerprint")),
    ),
)
def test_prepared_scope_rejects_grant_and_selection_predecessor_collisions(
    predecessor_id: str, predecessor_fingerprint: str
) -> None:
    scope = _scope()
    later_selection = ProjectMetricSelectionRevisionV2(
        **{
            **scope.selection_revision.model_dump(),
            "selection_ordinal": 2,
            "compare_and_swap_predecessor_id": predecessor_id,
            "compare_and_swap_predecessor_fingerprint": predecessor_fingerprint,
        }
    )
    forged = scope.model_copy(update={"selection_revision": later_selection})
    with pytest.raises(ValidationError, match="role-separated"):
        RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(forged)


def test_synthetic_completion_has_no_public_graph_write_shape() -> None:
    request = _request()
    assert request.analysis_run_id == request.analysis_input.analysis_run_id
    assert request.analysis_input.provider is Provider.SYNTHETIC
    assert request.synthetic_test_only is True
    assert request.repository_rehydration_required is True
    assert request.source_authority_verified is request.product_authority is False
    assert request.product_history_eligible is request.sealed is False
    forbidden = {
        "history_root",
        "selection_revision",
        "session_revision",
        "observation_batch",
        "observations",
        "seal_draft",
        "sealed_batch",
    }
    assert forbidden.isdisjoint(SyntheticTemporalCompletionRequestV1.model_fields)
    with pytest.raises(ValidationError):
        SyntheticTemporalCompletionRequestV1(
            **{**request.model_dump(), "observation_batch": {}}
        )


def test_synthetic_completion_rejects_non_synthetic_and_lineage_mismatch() -> None:
    request = _request()
    codex_input = _input(request.prepared_scope, provider=Provider.CODEX)
    for update in (
        {"analysis_input": codex_input},
        {"analysis_run_id": _id("other-run")},
        {
            "analysis_input": request.analysis_input.model_copy(
                update={"root_receipt_fingerprint": _id("other-root")}
            )
        },
        {
            "prepared_scope": request.prepared_scope.model_copy(
                update={"automation_grant_revision": GRANT_REVISION + 1}
            )
        },
    ):
        forged = request.model_copy(update=update)
        with pytest.raises(ValidationError):
            SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(forged)


@pytest.mark.parametrize(
    "colliding_value",
    (
        _id("prepared-scope"),
        _id("automation-grant"),
        _id("automation-grant-fingerprint"),
        _id("history-root"),
        _id("project"),
        _id("selection"),
        _id("analysis-input"),
        _id("session"),
        _id("analysis-run"),
        _id("analysis-run-fingerprint"),
    ),
)
def test_completion_request_id_is_role_separated_from_full_lineage(
    colliding_value: str,
) -> None:
    request = _request()
    with pytest.raises(ValidationError, match="role-separated"):
        SyntheticTemporalCompletionRequestV1(
            **{**request.model_dump(), "completion_request_id": colliding_value}
        )


@pytest.mark.parametrize(
    ("field", "collision_source"),
    (
        ("input_receipt_id", "prepared_scope_id"),
        ("session_id", "automation_grant_id"),
        ("analysis_run_fingerprint", "history_root_fingerprint"),
        ("analysis_run_request_fingerprint", "selection_revision_id"),
    ),
)
def test_synthetic_request_rejects_named_cross_role_collisions_recursively(
    field: str, collision_source: str
) -> None:
    request = _request()
    collision = {
        "prepared_scope_id": request.prepared_scope.prepared_scope_id,
        "automation_grant_id": request.prepared_scope.automation_grant_id,
        "history_root_fingerprint": request.prepared_scope.history_root.fingerprint,
        "selection_revision_id": (
            request.prepared_scope.selection_revision.selection_revision_id
        ),
    }[collision_source]
    forged_input = request.analysis_input.model_copy(update={field: collision})
    with pytest.raises(ValidationError, match="role-separated"):
        SyntheticTemporalCompletionRequestV1(
            **{**request.model_dump(), "analysis_input": forged_input.model_dump()}
        )
    forged_request = request.model_copy(update={"analysis_input": forged_input})
    with pytest.raises(ValidationError, match="role-separated"):
        SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(forged_request)


def test_synthetic_request_rejects_manifest_root_collision_with_grant() -> None:
    request = _request()
    manifest_root = request.prepared_scope.automation_grant_id
    forged_input = AnalysisInputReceiptV2(
        **{
            **request.analysis_input.model_dump(),
            "selected_window_manifest_root": manifest_root,
            "selected_window_manifest_identity_fingerprint": (
                AnalysisInputReceiptV2.selected_manifest_identity(
                    root=manifest_root,
                    entry_count=(
                        request.analysis_input.selected_window_manifest_entry_count
                    ),
                )
            ),
        }
    )
    forged_request = request.model_copy(update={"analysis_input": forged_input})
    with pytest.raises(ValidationError, match="role-separated"):
        SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(forged_request)


def test_repository_protocol_is_prepare_and_reads_only() -> None:
    methods = {
        name
        for name, value in TemporalHistoryPersistenceRepositoryV1.__dict__.items()
        if not name.startswith("_") and inspect.isfunction(value)
    }
    assert methods == {
        "prepare_automation_scope",
        "get_prepared_scope",
        "get_prepared_scope_for_grant",
        "get_sealed_batch",
        "get_sealed_batch_for_run",
    }
    assert not any(
        token in methods
        for token in ("write", "save", "complete", "seal", "persist_graph")
    )


def test_repository_seal_commits_exact_ordered_graph_without_source_authority() -> None:
    sealed = _sealed()
    assert sealed.seal_draft_fingerprint == sealed.seal_draft.fingerprint
    assert sealed.ordered_graph_fingerprints == (
        sealed.completion_request.prepared_scope.fingerprint,
        sealed.completion_request.fingerprint,
        sealed.seal_draft.history_root.fingerprint,
        sealed.seal_draft.selection_revision.fingerprint,
        sealed.seal_draft.analysis_input.fingerprint,
        sealed.seal_draft.session_revision.fingerprint,
        sealed.seal_draft.observation_batch.fingerprint,
        *(item.fingerprint for item in sealed.seal_draft.observation_batch.observations),
    )
    assert (
        sealed.source_authority_state
        is TemporalSourceAuthorityStateV1.SYNTHETIC_TEST_ONLY
    )
    assert sealed.repository_owned is sealed.repository_graph_verified is sealed.sealed
    assert sealed.source_authority_verified is sealed.capture_authority_verified is False
    assert sealed.product_history_eligible is sealed.comparison_allowed is False
    assert sealed.snapshot_materialization_allowed is sealed.activation_allowed is False
    assert sealed.private_export_allowed is sealed.team_share_allowed is False


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("provider_version", "reserved-provider-v2"),
        ("capture_contract_version", "reserved-direct-capture-v3"),
        ("consent_policy_version", "reserved-consent-v2"),
    ),
)
def test_operational_authorization_lineage_changes_exact_request_and_seal(
    field: str, changed_value: str
) -> None:
    baseline = _sealed()
    changed = _sealed(**{field: changed_value})
    assert baseline.completion_request.analysis_input.fingerprint != (
        changed.completion_request.analysis_input.fingerprint
    )
    assert baseline.completion_request.fingerprint != (
        changed.completion_request.fingerprint
    )
    assert baseline.seal_draft.fingerprint != changed.seal_draft.fingerprint
    assert baseline.fingerprint != changed.fingerprint


@pytest.mark.parametrize(
    ("field", "value_factory"),
    (
        ("seal_draft_fingerprint", lambda sealed: _id("other-draft")),
        (
            "ordered_graph_fingerprints",
            lambda sealed: tuple(reversed(sealed.ordered_graph_fingerprints)),
        ),
        (
            "repository_verifier_version",
            lambda sealed: "reserved-other-verifier-v1",
        ),
        (
            "repository_verifier_fingerprint",
            lambda sealed: _id("other-verifier"),
        ),
        ("sealed_at", lambda sealed: FLOOR),
    ),
)
def test_repository_seal_rejects_draft_graph_verifier_and_time_mismatch(
    field: str, value_factory: object
) -> None:
    sealed = _sealed()
    value = value_factory(sealed)  # type: ignore[operator]
    with pytest.raises(ValidationError):
        RepositorySealedTemporalBatchV1(
            **{**sealed.model_dump(), field: value}
        )
    forged = sealed.model_copy(update={field: value})
    with pytest.raises(ValidationError):
        RepositorySealedTemporalBatchV1.revalidate_for_persistence(forged)


def test_repository_seal_revalidates_nested_draft_and_blocks_trust_promotion() -> None:
    sealed = _sealed()
    forged_input = sealed.seal_draft.analysis_input.model_copy(
        update={"provider": Provider.CODEX}
    )
    forged_draft = sealed.seal_draft.model_copy(update={"analysis_input": forged_input})
    with pytest.raises(ValidationError):
        RepositorySealedTemporalBatchV1.ordered_graph_for(
            sealed.completion_request, forged_draft
        )
    with pytest.raises(ValidationError):
        RepositorySealedTemporalBatchV1.revalidate_for_persistence(
            sealed.model_copy(update={"seal_draft": forged_draft})
        )
    for field in (
        "source_authority_verified",
        "capture_authority_verified",
        "product_history_eligible",
        "comparison_allowed",
        "snapshot_materialization_allowed",
        "activation_allowed",
        "private_export_allowed",
        "team_share_allowed",
    ):
        forged = sealed.model_copy(update={field: True})
        with pytest.raises(ValidationError):
            RepositorySealedTemporalBatchV1.revalidate_for_persistence(forged)


def test_repository_seal_binds_exact_prepared_scope_and_completion_request() -> None:
    sealed = _sealed()
    for update in (
        {"prepared_scope_fingerprint": _id("other-scope")},
        {"completion_request_fingerprint": _id("other-request")},
        {
            "completion_request": sealed.completion_request.model_copy(
                update={"completion_request_id": _id("other-request-id")}
            )
        },
    ):
        forged = sealed.model_copy(update=update)
        with pytest.raises(ValidationError):
            RepositorySealedTemporalBatchV1.revalidate_for_persistence(forged)


@pytest.mark.parametrize(
    "collision_role",
    ("batch_id", "analysis_run_id"),
)
def test_repository_seal_rejects_observation_id_cross_role_collision(
    collision_role: str,
) -> None:
    request = _request()
    base = _seal_draft()
    collision = {
        "batch_id": base.observation_batch.batch_id,
        "analysis_run_id": base.analysis_run_id,
    }[collision_role]
    observation = TemporalMetricObservationV2(
        **{
            **base.observation_batch.observations[0].model_dump(),
            "observation_id": collision,
        }
    )
    colliding_draft = _rebuild_draft_with_observations(base, (observation,))
    _assert_graph_collision_rejected(request, colliding_draft)


def test_repository_seal_rejects_revision_id_equal_to_batch_id() -> None:
    request = _request()
    base = _seal_draft()
    revision = SessionRevisionReceiptV3(
        **{
            **base.session_revision.model_dump(),
            "revision_id": base.observation_batch.batch_id,
        }
    )
    observation = TemporalMetricObservationV2(
        **{
            **base.observation_batch.observations[0].model_dump(),
            "revision_id": revision.revision_id,
        }
    )
    colliding_draft = _rebuild_draft_with_observations(
        base, (observation,), revision=revision
    )
    _assert_graph_collision_rejected(request, colliding_draft)


def test_repository_seal_rejects_draft_id_equal_to_completion_request_id() -> None:
    request = _request()
    base = _seal_draft()
    colliding_draft = RepositoryTemporalBatchSealDraft(
        **{**base.model_dump(), "seal_draft_id": request.completion_request_id}
    )
    _assert_graph_collision_rejected(request, colliding_draft)


def test_sealed_batch_and_verifier_are_role_separated_from_graph() -> None:
    sealed = _sealed()
    with pytest.raises(ValidationError, match="role-separated"):
        RepositorySealedTemporalBatchV1(
            **{
                **sealed.model_dump(),
                "sealed_batch_id": sealed.seal_draft.history_root.root_receipt_id,
            }
        )

    request = _request()
    base_draft = _seal_draft()
    verifier_collision = base_draft.history_root.root_receipt_id
    colliding_draft = RepositoryTemporalBatchSealDraft(
        **{
            **base_draft.model_dump(),
            "requested_repository_verifier_fingerprint": verifier_collision,
        }
    )
    with pytest.raises(ValueError, match="role-separated"):
        RepositorySealedTemporalBatchV1.ordered_graph_for(request, colliding_draft)
    colliding_graph = (
        request.prepared_scope.fingerprint,
        request.fingerprint,
        colliding_draft.history_root.fingerprint,
        colliding_draft.selection_revision.fingerprint,
        colliding_draft.analysis_input.fingerprint,
        colliding_draft.session_revision.fingerprint,
        colliding_draft.observation_batch.fingerprint,
        *(
            item.fingerprint
            for item in colliding_draft.observation_batch.observations
        ),
    )
    with pytest.raises(ValidationError, match="role-separated"):
        RepositorySealedTemporalBatchV1(
            sealed_batch_id=_id("role-separated-sealed-batch"),
            completion_request=request,
            prepared_scope_fingerprint=request.prepared_scope.fingerprint,
            completion_request_fingerprint=request.fingerprint,
            seal_draft=colliding_draft,
            seal_draft_fingerprint=colliding_draft.fingerprint,
            ordered_graph_fingerprints=colliding_graph,
            repository_verifier_version=(
                colliding_draft.requested_repository_verifier_version
            ),
            repository_verifier_fingerprint=verifier_collision,
            sealed_at=colliding_draft.drafted_at + timedelta(seconds=1),
        )


def test_persistence_contract_dumps_are_content_free() -> None:
    private_canary = "PRIVATE-CANARY-SHOULD-NOT-APPEAR"
    for value in (_scope(), _request(), _sealed()):
        payload = value.model_dump_json()
        assert private_canary not in payload
        assert "file:" not in payload.lower()
        assert "http:" not in payload.lower()
        assert "https:" not in payload.lower()
        assert "reserved\\path" not in payload
