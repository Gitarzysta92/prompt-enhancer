from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.history import (
    AnalysisInputCompleteness,
    AnalysisInputReceipt,
    AppendVerificationState,
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceTier,
    FractionObservationValue,
    MetricComparisonIdentity,
    MetricDirection,
    ProjectMetricSelectionRevision,
    ProjectMetricSelectionSource,
    RevisionEffectiveTimeBasis,
    SessionRevisionRelation,
    SessionRevisionReceipt,
    TemporalAggregationSemantics,
    TemporalCompletionProjection,
    TemporalHistoryRootReceipt,
    TemporalMetricObservation,
    TemporalObservationBatch,
    TemporalScopeState,
    TemporalSelectionState,
    TemporalSourceState,
    TemporalValueKind,
    TemporalValueState,
)
from prompt_enhancer.domain import Provider


FLOOR = datetime(2045, 2, 1, 9, 0, tzinfo=UTC)
METRIC = "quality.requirement_coverage"


def _id(label: str) -> str:
    return hashlib.sha256(label.encode("ascii")).hexdigest()


def _root() -> TemporalHistoryRootReceipt:
    return TemporalHistoryRootReceipt(
        root_receipt_id=_id("temporal-root"),
        project_id=_id("example-project"),
        epoch_ordinal=1,
        history_floor_at=FLOOR,
        issued_at=FLOOR,
    )


def _selection(
    root: TemporalHistoryRootReceipt,
    *,
    ordinal: int = 1,
    predecessor: ProjectMetricSelectionRevision | None = None,
    metrics: tuple[str, ...] = (METRIC,),
) -> ProjectMetricSelectionRevision:
    return ProjectMetricSelectionRevision(
        selection_revision_id=_id(f"selection-{ordinal}"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=ordinal,
        compare_and_swap_predecessor_id=(
            predecessor.selection_revision_id if predecessor else None
        ),
        compare_and_swap_predecessor_fingerprint=(
            predecessor.fingerprint if predecessor else None
        ),
        selected_metric_keys=metrics,
        source=ProjectMetricSelectionSource.EXPLICIT_PROJECT_CONFIGURATION,
        effective_at=FLOOR + timedelta(minutes=ordinal),
        recorded_at=FLOOR + timedelta(minutes=ordinal),
    )


def _input(
    root: TemporalHistoryRootReceipt,
    selection: ProjectMetricSelectionRevision,
    *,
    ordinal: int = 1,
    count: int = 4,
    provider: Provider = Provider.SYNTHETIC,
    adapter_version: str = "adapter-v1",
    metrics: tuple[str, ...] | None = None,
) -> AnalysisInputReceipt:
    started_at = FLOOR + timedelta(minutes=10 + ordinal)
    ended_at = started_at + timedelta(minutes=10)
    return AnalysisInputReceipt(
        input_receipt_id=_id(f"analysis-input-{ordinal}"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        analysis_run_id=_id(f"analysis-run-{ordinal}"),
        project_id=root.project_id,
        session_id=_id("example-session"),
        selected_metric_keys=metrics or selection.selected_metric_keys,
        analysis_window_fingerprint=_id(f"analysis-window-{ordinal}"),
        analysis_window_fingerprint_version="canonical-events-v1",
        source_manifest_fingerprint=_id(f"source-manifest-{ordinal}"),
        source_manifest_version="source-manifest-v1",
        source_manifest_entry_count=count,
        captured_source_entry_count=count,
        completeness=AnalysisInputCompleteness.COMPLETE,
        analysis_window_started_at=started_at,
        analysis_window_ended_at=ended_at,
        captured_at=ended_at + timedelta(minutes=1),
        capture_contract_version="direct-capture-v1",
        provider=provider,
        provider_adapter_version=adapter_version,
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        redactor_version="redactor-v1",
        redactor_sha256=_id("redactor"),
        preprocessing_version="preprocess-v1",
        preprocessing_sha256=_id("preprocessing"),
        router_version="router-v1",
        router_sha256=_id("router"),
    )


class _PrefixVerifier:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls = 0

    @property
    def verifier_fingerprint(self) -> str:
        return _id("example-prefix-verifier")

    def claims_strict_append(
        self,
        *,
        predecessor: SessionRevisionReceipt,
        current_input: AnalysisInputReceipt,
    ) -> bool:
        self.calls += 1
        return self.result


def _revision(
    input_receipt: AnalysisInputReceipt,
    *,
    ordinal: int = 1,
    predecessor: SessionRevisionReceipt | None = None,
    verifier: _PrefixVerifier | None = None,
) -> SessionRevisionReceipt:
    return SessionRevisionReceipt.from_direct_input(
        revision_id=_id(f"session-revision-{ordinal}"),
        input_receipt=input_receipt,
        revision_ordinal=ordinal,
        effective_time_basis=RevisionEffectiveTimeBasis.SESSION_ENDED_AT,
        predecessor=predecessor,
        prefix_verifier=verifier,
    )


def _identity() -> MetricComparisonIdentity:
    return MetricComparisonIdentity(
        metric_key=METRIC,
        metric_definition_version="metric-v1",
        metric_definition_sha256=_id("metric-definition"),
        metric_question_version="question-v1",
        metric_question_sha256=_id("metric-question"),
        value_kind=TemporalValueKind.FRACTION,
        unit_code="ratio",
        direction=MetricDirection.HIGHER_IS_BETTER,
        aggregation_semantics=TemporalAggregationSemantics.RATIO_OF_SUMS,
        evidence_tier=EvidenceTier.OBJECTIVE_ARTIFACT,
        evidence_contract_version="evidence-v1",
        estimator_kind=EstimatorIdentityKind.DETERMINISTIC,
        estimator_plan_version="plan-v1",
        estimator_plan_sha256=_id("estimator-plan"),
        estimator_lifecycle=EstimatorLifecycleState.PROVISIONAL,
        preprocessing_version="preprocess-v1",
        preprocessing_sha256=_id("preprocessing"),
        calibration_version="calibration-v1",
        calibration_sha256=_id("calibration"),
        router_version="router-v1",
        router_sha256=_id("router"),
        redactor_version="redactor-v1",
        redactor_sha256=_id("redactor"),
        provider=Provider.SYNTHETIC,
        provider_adapter_version="adapter-v1",
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        privacy_policy_version="privacy-v1",
    )


def _batch(
    selection: ProjectMetricSelectionRevision,
    input_receipt: AnalysisInputReceipt,
    revision: SessionRevisionReceipt,
) -> TemporalObservationBatch:
    observed_at = input_receipt.captured_at + timedelta(minutes=1)
    observation = TemporalMetricObservation(
        observation_id=_id("temporal-observation"),
        revision_id=revision.revision_id,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        comparison_identity=_identity(),
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=FractionObservationValue(numerator=3, denominator=4),
        observed_at=observed_at,
    )
    return TemporalObservationBatch(
        batch_id=_id("temporal-batch"),
        project_id=input_receipt.project_id,
        session_id=input_receipt.session_id,
        revision_id=revision.revision_id,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=input_receipt.selected_metric_keys,
        observations=(observation,),
        recorded_at=observed_at + timedelta(minutes=1),
    )


def _completion() -> TemporalCompletionProjection:
    root = _root()
    selection = _selection(root)
    analysis_input = _input(root, selection)
    revision = _revision(analysis_input)
    batch = _batch(selection, analysis_input, revision)
    return TemporalCompletionProjection(
        completion_projection_id=_id("completion-projection"),
        history_root=root,
        selection_revision=selection,
        analysis_input=analysis_input,
        session_revision=revision,
        observation_batch=batch,
        completed_at=batch.recorded_at + timedelta(minutes=1),
    )


def test_history_root_is_a_server_issued_prospective_floor() -> None:
    root = _root()
    assert root.history_floor_at == root.issued_at
    assert root.legacy_backfill_allowed is False
    assert root.private_export_allowed is False
    assert root.team_share_allowed is False
    with pytest.raises(ValidationError):
        TemporalHistoryRootReceipt(
            **{
                **root.model_dump(),
                "history_floor_at": root.issued_at - timedelta(seconds=1),
            }
        )


def test_history_epoch_chain_requires_exact_predecessor_pair_and_ordinal_shape() -> None:
    first = _root()
    second = TemporalHistoryRootReceipt(
        root_receipt_id=_id("temporal-root-2"),
        project_id=first.project_id,
        epoch_ordinal=2,
        predecessor_root_id=first.root_receipt_id,
        predecessor_root_fingerprint=first.fingerprint,
        history_floor_at=FLOOR + timedelta(days=1),
        issued_at=FLOOR + timedelta(days=1),
    )
    assert second.predecessor_root_fingerprint == first.fingerprint
    assert second.repository_verification_required is True
    assert second.fingerprint != first.fingerprint

    with pytest.raises(ValidationError):
        TemporalHistoryRootReceipt(
            **{**second.model_dump(), "predecessor_root_fingerprint": None}
        )
    with pytest.raises(ValidationError):
        TemporalHistoryRootReceipt(
            **{
                **first.model_dump(),
                "predecessor_root_id": _id("unexpected-root"),
                "predecessor_root_fingerprint": _id("unexpected-root-fingerprint"),
            }
        )


def test_metric_selection_has_exact_idempotency_and_cas_predecessor_semantics() -> None:
    root = _root()
    first = _selection(root)
    replay = ProjectMetricSelectionRevision(
        **{
            **first.model_dump(),
            "selection_revision_id": _id("idempotent-selection-retry"),
            "recorded_at": first.recorded_at + timedelta(minutes=1),
        }
    )
    assert replay.metric_set_fingerprint == first.metric_set_fingerprint
    assert replay.fingerprint != first.fingerprint

    exact_retry = ProjectMetricSelectionRevision(**first.model_dump())
    assert exact_retry.fingerprint == first.fingerprint

    second = _selection(root, ordinal=2, predecessor=first)
    assert second.compare_and_swap_predecessor_id == first.selection_revision_id
    assert second.compare_and_swap_predecessor_fingerprint == first.fingerprint
    assert second.metric_set_fingerprint == first.metric_set_fingerprint

    with pytest.raises(ValidationError):
        ProjectMetricSelectionRevision(
            **{
                **second.model_dump(),
                "compare_and_swap_predecessor_fingerprint": None,
            }
        )


def test_selection_a_to_b_to_a_is_three_distinct_revision_identities() -> None:
    root = _root()
    first_a = _selection(root)
    second_b = _selection(
        root,
        ordinal=2,
        predecessor=first_a,
        metrics=("quality.verification_coverage",),
    )
    third_a = _selection(root, ordinal=3, predecessor=second_b)

    assert first_a.metric_set_fingerprint == third_a.metric_set_fingerprint
    assert len({first_a.fingerprint, second_b.fingerprint, third_a.fingerprint}) == 3
    assert third_a.compare_and_swap_predecessor_fingerprint == second_b.fingerprint
    changed_effective = first_a.model_copy(
        update={"effective_at": first_a.effective_at - timedelta(seconds=1)}
    )
    assert ProjectMetricSelectionRevision.revalidate_for_persistence(
        changed_effective
    ).fingerprint != first_a.fingerprint
    with pytest.raises(ValidationError):
        ProjectMetricSelectionRevision(
            **{
                **first_a.model_dump(),
                "selected_metric_keys": (METRIC, METRIC),
            }
        )


def test_analysis_input_exposes_manifest_completeness_and_full_provenance() -> None:
    root = _root()
    selection = _selection(root)
    receipt = _input(root, selection)
    assert receipt.source_manifest_entry_count == receipt.captured_source_entry_count
    assert receipt.completeness is AnalysisInputCompleteness.COMPLETE
    assert len(receipt.provenance_fingerprint) == 64
    assert receipt.private_export_allowed is False
    assert receipt.team_share_allowed is False

    partial = AnalysisInputReceipt(
        **{
            **receipt.model_dump(),
            "input_receipt_id": _id("partial-analysis-input"),
            "captured_source_entry_count": 3,
            "completeness": AnalysisInputCompleteness.PARTIAL,
        }
    )
    assert partial.captured_source_entry_count == 3
    with pytest.raises(ValidationError):
        AnalysisInputReceipt(
            **{
                **receipt.model_dump(),
                "captured_source_entry_count": 3,
                "completeness": AnalysisInputCompleteness.COMPLETE,
            }
        )
    with pytest.raises(ValidationError):
        AnalysisInputReceipt(
            **{
                **receipt.model_dump(),
                "captured_source_entry_count": 5,
            }
        )


def test_revision_never_uses_count_or_updated_time_as_append_proof() -> None:
    root = _root()
    selection = _selection(root)
    first = _revision(_input(root, selection, count=4))
    larger = _input(root, selection, ordinal=2, count=7)

    missing_proof = _revision(larger, ordinal=2, predecessor=first)
    assert missing_proof.relation is SessionRevisionRelation.CHANGED_OR_REORDERED

    refusing = _PrefixVerifier(False)
    refused = _revision(
        larger,
        ordinal=2,
        predecessor=first,
        verifier=refusing,
    )
    assert refusing.calls == 1
    assert refused.relation is SessionRevisionRelation.CHANGED_OR_REORDERED

    verifier = _PrefixVerifier(True)
    appended = _revision(larger, ordinal=2, predecessor=first, verifier=verifier)
    assert verifier.calls == 1
    assert appended.relation is SessionRevisionRelation.APPEND_PREFIX_PROVED
    assert (
        appended.append_verification_state
        is AppendVerificationState.UNTRUSTED_UNTIL_REPOSITORY_VERIFIED
    )
    assert appended.append_prefix_proof is not None
    assert appended.append_prefix_proof.sealed is False
    assert appended.append_prefix_proof.comparison_allowed is False
    assert appended.comparison_allowed is False
    assert appended.persisted_prefix_root == larger.source_manifest_fingerprint
    assert appended.persisted_prefix_event_count == 7

    with pytest.raises(ValidationError):
        SessionRevisionReceipt.revalidate_for_persistence(
            {
                **appended.model_dump(),
                "append_prefix_proof": None,
            }
        )
    with pytest.raises(ValidationError):
        SessionRevisionReceipt.revalidate_for_persistence(
            {
                **missing_proof.model_dump(),
                "relation": SessionRevisionRelation.APPEND_PREFIX_PROVED,
            }
        )


def test_revision_marks_provider_or_capture_provenance_changes_as_boundaries() -> None:
    root = _root()
    selection = _selection(root)
    first = _revision(_input(root, selection, count=4))
    changed = _input(
        root,
        selection,
        ordinal=2,
        count=7,
        provider=Provider.CODEX,
        adapter_version="adapter-v2",
    )
    verifier = _PrefixVerifier(True)
    boundary = _revision(changed, ordinal=2, predecessor=first, verifier=verifier)
    assert boundary.relation is SessionRevisionRelation.PROVENANCE_BOUNDARY
    assert verifier.calls == 0


def test_completion_cross_validates_root_selection_run_revision_and_batch() -> None:
    projection = _completion()
    assert (
        projection.analysis_input.selected_metric_keys
        == projection.selection_revision.selected_metric_keys
        == projection.observation_batch.selected_metric_keys
    )
    assert projection.sealed is False
    assert projection.comparison_allowed is False
    assert projection.repository_verification_required is True

    forged_run = projection.analysis_input.model_copy(
        update={"selected_metric_keys": ("quality.other_metric",)}
    )
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "analysis_input": forged_run}
        )

    forged_batch = projection.observation_batch.model_copy(
        update={"revision_id": _id("other-revision")}
    )
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "observation_batch": forged_batch}
        )


def test_completion_rejects_observation_provider_and_pipeline_provenance_mismatch() -> None:
    projection = _completion()
    observation = projection.observation_batch.observations[0]
    wrong_provider = observation.comparison_identity.model_copy(
        update={"provider": Provider.CODEX}
    )
    forged_observation = observation.model_copy(
        update={"comparison_identity": wrong_provider}
    )
    forged_batch = projection.observation_batch.model_copy(
        update={"observations": (forged_observation,)}
    )
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "observation_batch": forged_batch}
        )

    wrong_preprocessing = observation.comparison_identity.model_copy(
        update={
            "preprocessing_version": "preprocess-v2",
            "preprocessing_sha256": _id("preprocessing-v2"),
        }
    )
    forged_observation = observation.model_copy(
        update={"comparison_identity": wrong_preprocessing}
    )
    forged_batch = projection.observation_batch.model_copy(
        update={"observations": (forged_observation,)}
    )
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "observation_batch": forged_batch}
        )


def test_completion_rejects_coordinated_arbitrary_input_and_run_substitution() -> None:
    projection = _completion()
    substituted_run = _id("substituted-analysis-run")
    substituted_input = _id("substituted-analysis-input")
    substituted_fingerprint = _id("substituted-analysis-input-fingerprint")
    forged_observation = projection.observation_batch.observations[0].model_copy(
        update={
            "analysis_run_id": substituted_run,
            "analysis_input_receipt_id": substituted_input,
            "analysis_input_receipt_fingerprint": substituted_fingerprint,
        }
    )
    forged_batch = projection.observation_batch.model_copy(
        update={
            "analysis_run_id": substituted_run,
            "analysis_input_receipt_id": substituted_input,
            "analysis_input_receipt_fingerprint": substituted_fingerprint,
            "observations": (forged_observation,),
        }
    )
    assert TemporalObservationBatch.revalidate_for_persistence(forged_batch)
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "observation_batch": forged_batch}
        )


def test_completion_rejects_a_same_root_id_with_wrong_root_fingerprint() -> None:
    projection = _completion()
    forged_revision = projection.session_revision.model_copy(
        update={"root_receipt_fingerprint": _id("wrong-root-fingerprint")}
    )
    with pytest.raises(ValidationError):
        TemporalCompletionProjection.revalidate_for_persistence(
            {**projection.model_dump(), "session_revision": forged_revision}
        )


def test_completion_rejects_nested_model_copy_privacy_and_legacy_bypasses() -> None:
    projection = _completion()
    forged_root = projection.history_root.model_copy(
        update={"legacy_backfill_allowed": True}
    )
    forged_input = projection.analysis_input.model_copy(
        update={"private_export_allowed": True}
    )
    forged_revision = projection.session_revision.model_copy(
        update={"legacy_inference_allowed": True}
    )
    for field, forged in (
        ("history_root", forged_root),
        ("analysis_input", forged_input),
        ("session_revision", forged_revision),
    ):
        with pytest.raises(ValidationError):
            TemporalCompletionProjection.revalidate_for_persistence(
                {**projection.model_dump(), field: forged}
            )


def test_persisted_revision_has_no_prefix_leaves_or_private_payload_fields() -> None:
    projection = _completion()
    serialized = projection.session_revision.model_dump_json()
    assert '"persisted_prefix_root"' in serialized
    assert '"persisted_prefix_event_count"' in serialized
    for forbidden in (
        '"prefix_leaves"',
        '"event_payloads"',
        '"prompt"',
        '"evidence_text"',
        '"source_path"',
        '"uri"',
    ):
        assert forbidden not in serialized
