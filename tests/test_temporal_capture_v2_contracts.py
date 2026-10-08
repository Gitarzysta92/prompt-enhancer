from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.history import (
    AnalysisInputExtractionCompleteness,
    AnalysisInputReceiptV2,
    AnalysisInputSelectionCoverage,
    AnalysisWindowFingerprintBasisV2,
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
    SessionRevisionRelationV3,
    TemporalAggregationSemantics,
    TemporalHistoryRootReceipt,
    TemporalMetricObservation,
    TemporalMetricObservationV2,
    TemporalObservationBatchV2,
    TemporalScopeState,
    TemporalSelectionState,
    TemporalSourceState,
    TemporalValueKind,
    TemporalValueState,
)
from prompt_enhancer.domain import Provider


FLOOR = datetime(2042, 1, 1, 12, tzinfo=UTC)
METRIC = "quality.requirement_coverage"


def _id(label: str) -> str:
    return hashlib.sha256(f"synthetic-v2:{label}".encode("ascii")).hexdigest()


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
    ordinal: int = 1,
    predecessor: ProjectMetricSelectionRevisionV2 | None = None,
    pack_key: str = "quality_pack",
    pack_version: int = 1,
    pack_sha: str | None = None,
    catalog_version: str = "metric-catalog-v1",
    catalog_sha: str | None = None,
    source: ProjectMetricSelectionSource = (
        ProjectMetricSelectionSource.EXPLICIT_PROJECT_CONFIGURATION
    ),
    authority_kind: ProjectMetricSelectionAuthorityKind = (
        ProjectMetricSelectionAuthorityKind.PROJECT_CONFIGURATION
    ),
    authority_id: str | None = None,
    authority_fingerprint: str | None = None,
) -> ProjectMetricSelectionRevisionV2:
    at = FLOOR + timedelta(minutes=ordinal)
    return ProjectMetricSelectionRevisionV2(
        selection_revision_id=_id(f"selection-{ordinal}-{pack_key}"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=ordinal,
        compare_and_swap_predecessor_id=(
            None if predecessor is None else predecessor.selection_revision_id
        ),
        compare_and_swap_predecessor_fingerprint=(
            None if predecessor is None else predecessor.fingerprint
        ),
        selected_metric_keys=(METRIC,),
        source=source,
        effective_at=at,
        recorded_at=at,
        metric_pack_key=pack_key,
        metric_pack_version=pack_version,
        metric_pack_sha256=pack_sha or _id(f"pack:{pack_key}:{pack_version}"),
        metric_catalog_version=catalog_version,
        metric_catalog_sha256=catalog_sha or _id(f"catalog:{catalog_version}"),
        source_authority_kind=authority_kind,
        source_authority_id=authority_id or _id("project-config-authority"),
        source_authority_fingerprint=(
            authority_fingerprint or _id("project-config-authority-receipt")
        ),
        source_authority_version="selection-authority-v1",
    )


def _input(
    root: TemporalHistoryRootReceipt,
    selection: ProjectMetricSelectionRevisionV2,
    *,
    ordinal: int = 1,
    observed: int = 5,
    extracted: int = 5,
    eligible: int = 4,
    selected: int = 4,
    extraction: AnalysisInputExtractionCompleteness = (
        AnalysisInputExtractionCompleteness.COMPLETE
    ),
    selection_coverage: AnalysisInputSelectionCoverage = (
        AnalysisInputSelectionCoverage.COMPLETE
    ),
    provider_adapter_version: str = "adapter-v2",
) -> AnalysisInputReceiptV2:
    started_at = FLOOR + timedelta(minutes=10 + ordinal)
    ended_at = started_at + timedelta(minutes=5)
    completed_at = ended_at + timedelta(minutes=1)
    captured_at = completed_at + timedelta(seconds=1)
    selected_root = _id(f"selected-window-manifest-{ordinal}")
    source_root = _id(f"observed-source-manifest-{ordinal}")
    return AnalysisInputReceiptV2(
        input_receipt_id=_id(f"input-receipt-{ordinal}"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        selection_scope_fingerprint=selection.metric_set_fingerprint,
        analysis_run_id=_id(f"analysis-run-{ordinal}"),
        analysis_run_fingerprint=_id(f"full-analysis-run-{ordinal}"),
        analysis_run_fingerprint_version="session-analysis-run-record-v1",
        analysis_run_request_fingerprint=_id(f"analysis-request-{ordinal}"),
        project_id=root.project_id,
        session_id=_id("session"),
        selected_metric_keys=selection.selected_metric_keys,
        analysis_window_fingerprint=_id(f"keyed-redacted-window-{ordinal}"),
        selected_window_manifest_root=selected_root,
        selected_window_manifest_entry_count=selected,
        selected_window_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.selected_manifest_identity(
                root=selected_root, entry_count=selected
            )
        ),
        post_floor_observed_allowlisted_source_manifest_root=source_root,
        post_floor_observed_allowlisted_source_manifest_entry_count=observed,
        post_floor_observed_allowlisted_source_manifest_identity_fingerprint=(
            AnalysisInputReceiptV2.observed_source_manifest_identity(
                root=source_root, entry_count=observed
            )
        ),
        successfully_extracted_source_entry_count=extracted,
        selection_eligible_entry_count=eligible,
        extraction_completeness=extraction,
        selection_coverage=selection_coverage,
        analysis_window_started_at=started_at,
        analysis_window_ended_at=ended_at,
        analysis_run_completed_at=completed_at,
        captured_at=captured_at,
        capture_contract_version="direct-capture-v2",
        analysis_profile_key="standard_engineering",
        analysis_profile_version=1,
        analysis_profile_sha256=_id("analysis-profile"),
        metric_pack_key=selection.metric_pack_key,
        metric_pack_version=selection.metric_pack_version,
        metric_pack_sha256=selection.metric_pack_sha256,
        metric_engine_version="metric-engine-v3",
        metric_engine_sha256=_id("metric-engine"),
        metric_catalog_version=selection.metric_catalog_version,
        metric_catalog_sha256=selection.metric_catalog_sha256,
        consent_policy_version="local-redacted-content-consent-v1",
        consent_receipt_id=_id("consent-receipt"),
        consent_receipt_fingerprint=_id("consent-receipt-fingerprint"),
        privacy_policy_version="local-privacy-v1",
        provider=Provider.SYNTHETIC,
        provider_version="synthetic-provider-v1",
        provider_adapter_version=provider_adapter_version,
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        redactor_version="redactor-v1",
        redactor_sha256=_id("redactor"),
        preprocessing_version="preprocess-v1",
        preprocessing_sha256=_id("preprocessing"),
        router_version="router-v1",
        router_sha256=_id("router"),
        model_plan_fingerprint=_id("model-plan"),
        analysis_run_schema_version=1,
        full_run_metric_observation_count=1,
    )


def _revision(
    input_receipt: AnalysisInputReceiptV2,
    *,
    ordinal: int = 1,
    predecessor: SessionRevisionReceiptV3 | None = None,
) -> SessionRevisionReceiptV3:
    return SessionRevisionReceiptV3.from_direct_input(
        revision_id=_id(f"session-revision-{ordinal}"),
        input_receipt=input_receipt,
        revision_ordinal=ordinal,
        effective_time_basis=RevisionEffectiveTimeBasis.SESSION_ENDED_AT,
        predecessor=predecessor,
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
        provider_adapter_version="adapter-v2",
        provider_schema_version="provider-schema-v1",
        source_schema_version="source-schema-v1",
        content_schema_version="content-schema-v1",
        privacy_policy_version="local-privacy-v1",
    )


def _observation(
    input_receipt: AnalysisInputReceiptV2,
    revision: SessionRevisionReceiptV3,
) -> TemporalMetricObservationV2:
    return TemporalMetricObservationV2(
        observation_id=_id("observation"),
        revision_id=revision.revision_id,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        comparison_identity=_identity(),
        selection_state=TemporalSelectionState.SELECTED,
        source_state=TemporalSourceState.PRESENT,
        value_state=TemporalValueState.KNOWN,
        value=FractionObservationValue(numerator=0, denominator=1),
        evidence_coverage_eligibility=EvidenceCoverageEligibility.ELIGIBLE,
        evidence_coverage_state=EvidenceCoverageState.KNOWN,
        evidence_numerator=0,
        evidence_denominator=0,
        observed_at=input_receipt.captured_at + timedelta(minutes=1),
    )


def _batch(
    root: TemporalHistoryRootReceipt,
    selection: ProjectMetricSelectionRevisionV2,
    input_receipt: AnalysisInputReceiptV2,
    revision: SessionRevisionReceiptV3,
) -> TemporalObservationBatchV2:
    observation = _observation(input_receipt, revision)
    return TemporalObservationBatchV2(
        batch_id=_id("batch"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        session_id=input_receipt.session_id,
        revision_id=revision.revision_id,
        revision_fingerprint=revision.fingerprint,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
        analysis_input_receipt_id=input_receipt.input_receipt_id,
        analysis_input_receipt_fingerprint=input_receipt.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        scope_state=TemporalScopeState.EXACT_SELECTION_RECEIPT,
        source_state=TemporalSourceState.PRESENT,
        selected_metric_keys=input_receipt.selected_metric_keys,
        observations=(observation,),
        recorded_at=observation.observed_at + timedelta(minutes=1),
    )


def _seal() -> RepositoryTemporalBatchSealDraft:
    root = _root()
    selection = _selection(root)
    input_receipt = _input(root, selection)
    revision = _revision(input_receipt)
    batch = _batch(root, selection, input_receipt, revision)
    return RepositoryTemporalBatchSealDraft(
        seal_draft_id=_id("repository-seal-draft"),
        history_root=root,
        selection_revision=selection,
        analysis_input=input_receipt,
        session_revision=revision,
        observation_batch=batch,
        analysis_run_id=input_receipt.analysis_run_id,
        analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
        ordered_observation_ids=tuple(item.observation_id for item in batch.observations),
        ordered_observation_fingerprints=tuple(
            item.fingerprint for item in batch.observations
        ),
        requested_repository_verifier_version="temporal-repository-verifier-v1",
        requested_repository_verifier_fingerprint=_id("repository-verifier"),
        drafted_at=batch.recorded_at + timedelta(minutes=1),
    )


def test_v2_graph_uses_truthful_window_basis_and_drafts_no_product_capability() -> None:
    seal = _seal()
    assert (
        seal.analysis_input.analysis_window_fingerprint_basis
        is AnalysisWindowFingerprintBasisV2.KEYED_SELECTED_REDACTED_MESSAGE_WINDOW
    )
    assert seal.repository_verification_required is True
    assert seal.issuance_required is True
    assert seal.persistence_state == "untrusted_seal_draft"
    assert seal.repository_verified is False
    assert seal.sealed is False
    assert seal.comparison_allowed is False
    assert seal.snapshot_materialization_allowed is False
    assert seal.activation_allowed is False
    assert seal.remote_processing_allowed is False
    assert seal.private_export_allowed is False
    assert seal.team_share_allowed is False
    assert seal.observation_batch.observations[0].evidence_coverage_ratio is None


def test_public_seal_draft_cannot_claim_repository_issuance_or_sealed_state() -> None:
    draft = _seal()
    promotions = (
        {"repository_verified": True},
        {"sealed": True},
        {"issuance_required": False},
        {"persistence_state": "repository_issued"},
    )
    for update in promotions:
        with pytest.raises(ValidationError):
            RepositoryTemporalBatchSealDraft(
                **{**draft.model_dump(), **update}
            )
        forged = draft.model_copy(update=update)
        with pytest.raises(ValidationError):
            RepositoryTemporalBatchSealDraft.revalidate_for_persistence(forged)


def test_manifest_roles_counts_and_coverage_axes_cannot_be_conflated() -> None:
    root = _root()
    selection = _selection(root)
    receipt = _input(
        root,
        selection,
        observed=6,
        extracted=5,
        eligible=4,
        selected=3,
        extraction=AnalysisInputExtractionCompleteness.PARTIAL,
        selection_coverage=AnalysisInputSelectionCoverage.PARTIAL,
    )
    assert receipt.successfully_extracted_source_entry_count == 5
    assert receipt.selection_eligible_entry_count == 4

    root_only_swap = {
        **receipt.model_dump(),
        "selected_window_manifest_root": (
            receipt.post_floor_observed_allowlisted_source_manifest_root
        ),
        "post_floor_observed_allowlisted_source_manifest_root": (
            receipt.selected_window_manifest_root
        ),
    }
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2.revalidate_for_persistence(root_only_swap)
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2.revalidate_for_persistence(
            {
                **receipt.model_dump(),
                "post_floor_observed_allowlisted_source_manifest_entry_count": 7,
            }
        )

    equal_counts = _input(
        root,
        selection,
        observed=4,
        extracted=4,
        eligible=4,
        selected=4,
    )
    role_pair_swap = {
        **equal_counts.model_dump(),
        "selected_window_manifest_root": (
            equal_counts.post_floor_observed_allowlisted_source_manifest_root
        ),
        "selected_window_manifest_identity_fingerprint": (
            equal_counts.post_floor_observed_allowlisted_source_manifest_identity_fingerprint
        ),
        "post_floor_observed_allowlisted_source_manifest_root": (
            equal_counts.selected_window_manifest_root
        ),
        "post_floor_observed_allowlisted_source_manifest_identity_fingerprint": (
            equal_counts.selected_window_manifest_identity_fingerprint
        ),
    }
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2.revalidate_for_persistence(role_pair_swap)

    empty = _input(
        root,
        selection,
        observed=0,
        extracted=0,
        eligible=0,
        selected=0,
        extraction=(
            AnalysisInputExtractionCompleteness.NOT_APPLICABLE_EMPTY_SOURCE
        ),
        selection_coverage=(
            AnalysisInputSelectionCoverage.NOT_APPLICABLE_EMPTY_ELIGIBLE_SET
        ),
    )
    assert empty.selected_window_manifest_entry_count == 0
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2(
            **{
                **empty.model_dump(),
                "extraction_completeness": AnalysisInputExtractionCompleteness.COMPLETE,
            }
        )


def test_same_metric_keys_differ_across_pack_catalog_and_authority_identity() -> None:
    root = _root()
    base = _selection(root)
    changed_pack = ProjectMetricSelectionRevisionV2(
        **{
            **base.model_dump(),
            "metric_pack_version": 2,
            "metric_pack_sha256": _id("pack-v2"),
        }
    )
    changed_catalog = ProjectMetricSelectionRevisionV2(
        **{
            **base.model_dump(),
            "metric_catalog_version": "metric-catalog-v2",
            "metric_catalog_sha256": _id("catalog-v2"),
        }
    )
    changed_authority = ProjectMetricSelectionRevisionV2(
        **{
            **base.model_dump(),
            "source_authority_id": _id("different-authority"),
            "source_authority_fingerprint": _id("different-authority-receipt"),
        }
    )
    assert len(
        {
            base.metric_set_fingerprint,
            changed_pack.metric_set_fingerprint,
            changed_catalog.metric_set_fingerprint,
            changed_authority.metric_set_fingerprint,
        }
    ) == 4
    with pytest.raises(ValidationError):
        ProjectMetricSelectionRevisionV2(
            **{
                **base.model_dump(),
                "source_authority_kind": (
                    ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT
                ),
            }
        )


def test_revision_v3_binds_predecessor_fingerprint_and_cannot_claim_append() -> None:
    root = _root()
    selection = _selection(root)
    first = _revision(_input(root, selection))
    second = _revision(_input(root, selection, ordinal=2), ordinal=2, predecessor=first)
    assert second.predecessor_revision_id == first.revision_id
    assert second.predecessor_revision_fingerprint == first.fingerprint
    assert second.relation is SessionRevisionRelationV3.CHANGED_OR_REORDERED

    with pytest.raises(ValidationError):
        SessionRevisionReceiptV3.revalidate_for_persistence(
            {
                **second.model_dump(),
                "predecessor_revision_id": _id("substituted-predecessor"),
            }
        )
    with pytest.raises(ValidationError):
        SessionRevisionReceiptV3(
            **{**second.model_dump(), "relation": "append_prefix_proved"}
        )


def test_revision_v3_marks_semantic_pipeline_changes_as_boundaries() -> None:
    root = _root()
    first_selection = _selection(root)
    first = _revision(_input(root, first_selection))
    second_selection = _selection(
        root,
        ordinal=2,
        predecessor=first_selection,
        pack_key="quality_pack_v2",
        pack_version=2,
    )
    changed_input = _input(root, second_selection, ordinal=2)
    second = _revision(changed_input, ordinal=2, predecessor=first)
    assert second.relation is SessionRevisionRelationV3.PROVENANCE_BOUNDARY


def test_v2_evidence_coverage_distinguishes_known_zero_denominator() -> None:
    seal = _seal()
    observation = seal.observation_batch.observations[0]
    assert observation.evidence_numerator == 0
    assert observation.evidence_denominator == 0
    assert observation.evidence_coverage_state is EvidenceCoverageState.KNOWN
    assert observation.evidence_coverage_ratio is None

    with pytest.raises(ValidationError):
        TemporalMetricObservationV2(
            **{
                **observation.model_dump(),
                "evidence_numerator": 1,
                "evidence_denominator": 0,
            }
        )
    with pytest.raises(ValidationError):
        TemporalMetricObservationV2(
            **{
                **observation.model_dump(),
                "evidence_coverage_state": EvidenceCoverageState.UNKNOWN,
            }
        )
    legacy = observation.model_dump(
        exclude={
            "contract_version",
            "evidence_coverage_eligibility",
            "evidence_coverage_state",
            "remote_processing_allowed",
        }
    )
    with pytest.raises(ValidationError):
        TemporalMetricObservation(**legacy)


def test_seal_rejects_root_selection_run_revision_and_order_substitutions() -> None:
    seal = _seal()
    wrong_selection = seal.selection_revision.model_copy(
        update={"metric_catalog_sha256": _id("wrong-catalog")}
    )
    wrong_input = seal.analysis_input.model_copy(
        update={"analysis_run_fingerprint": _id("wrong-run")}
    )
    wrong_revision = seal.session_revision.model_copy(
        update={"analysis_input_receipt_id": _id("wrong-input")}
    )
    wrong_batch = seal.observation_batch.model_copy(
        update={"root_receipt_fingerprint": _id("wrong-root")}
    )
    substitutions = (
        ("selection_revision", wrong_selection),
        ("analysis_input", wrong_input),
        ("session_revision", wrong_revision),
        ("observation_batch", wrong_batch),
    )
    for field, value in substitutions:
        with pytest.raises(ValidationError):
            RepositoryTemporalBatchSealDraft.revalidate_for_persistence(
                {**seal.model_dump(), field: value}
            )
    with pytest.raises(ValidationError):
        RepositoryTemporalBatchSealDraft(
            **{
                **seal.model_dump(),
                "ordered_observation_fingerprints": (_id("substituted-observation"),),
            }
        )


def test_seal_rejects_observation_recorded_before_input_and_revision_capture() -> None:
    draft = _seal()
    premature = draft.observation_batch.observations[0].model_copy(
        update={"observed_at": draft.analysis_input.analysis_run_completed_at}
    )
    assert premature.observed_at < draft.analysis_input.captured_at
    assert premature.observed_at < draft.session_revision.captured_at
    forged_batch = TemporalObservationBatchV2.revalidate_for_persistence(
        {
            **draft.observation_batch.model_dump(),
            "observations": (premature,),
        }
    )
    with pytest.raises(ValidationError):
        RepositoryTemporalBatchSealDraft.revalidate_for_persistence(
            {
                **draft.model_dump(),
                "observation_batch": forged_batch,
                "ordered_observation_fingerprints": (premature.fingerprint,),
            }
        )


def test_recursive_revalidation_blocks_model_copy_privacy_bypasses() -> None:
    seal = _seal()
    forged_input = seal.analysis_input.model_copy(
        update={"private_export_allowed": True}
    )
    forged_observation = seal.observation_batch.observations[0].model_copy(
        update={"remote_processing_allowed": True}
    )
    forged_batch = seal.observation_batch.model_copy(
        update={"observations": (forged_observation,)}
    )
    for field, value in (
        ("analysis_input", forged_input),
        ("observation_batch", forged_batch),
    ):
        with pytest.raises(ValidationError):
            RepositoryTemporalBatchSealDraft.revalidate_for_persistence(
                {**seal.model_dump(), field: value}
            )


def test_v2_capture_graph_serializes_only_content_free_local_commitments() -> None:
    draft = _seal()
    for node in (
        draft.selection_revision,
        draft.analysis_input,
        draft.session_revision,
        draft.observation_batch,
        *draft.observation_batch.observations,
        draft,
    ):
        assert node.contains_local_content is False
        assert node.private_export_allowed is False
        assert node.team_share_allowed is False
        if hasattr(node, "remote_processing_allowed"):
            assert node.remote_processing_allowed is False
    serialized = draft.model_dump_json()
    for forbidden in (
        '"prompt"',
        '"transcript"',
        '"evidence_text"',
        '"source_path"',
        '"uri"',
        '"raw_payload"',
    ):
        assert forbidden not in serialized


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("provider_version", "file:///private/example"),
        ("analysis_profile_key", "C:\\private\\profile"),
        ("metric_engine_version", "engine-v1\nsecret"),
    ),
)
def test_v2_input_rejects_paths_uris_and_control_text(field: str, value: str) -> None:
    root = _root()
    selection = _selection(root)
    receipt = _input(root, selection)
    with pytest.raises(ValidationError) as raised:
        AnalysisInputReceiptV2(**{**receipt.model_dump(), field: value})
    assert value not in str(raised.value)


def test_v2_guards_utc_time_and_strict_bounded_counts() -> None:
    root = _root()
    selection = _selection(root)
    receipt = _input(root, selection)
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2(
            **{
                **receipt.model_dump(),
                "analysis_run_completed_at": datetime(2042, 1, 1, 12),
            }
        )
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2(
            **{**receipt.model_dump(), "successfully_extracted_source_entry_count": True}
        )
    with pytest.raises(ValidationError):
        AnalysisInputReceiptV2(
            **{**receipt.model_dump(), "selection_eligible_entry_count": -1}
        )
