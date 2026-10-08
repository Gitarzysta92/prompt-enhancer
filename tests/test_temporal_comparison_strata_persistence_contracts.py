from __future__ import annotations

from datetime import timedelta, timezone
import inspect

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.history.comparison_strata import (
    AutomationRevalidationRequestV1,
    ComparisonAnalysisJobAuthorityV1,
    ComparisonAutomationGrantAuthorityV1,
    ComparisonSessionAuthorityV1,
    ComparisonStratumDimensionsV1,
    ExpectedAnalysisRunVerificationRequestV1,
    _AutomationComparisonLeaseAuthorityV1,
    automation_grant_scope_fingerprint,
    session_analysis_run_authority_fingerprint,
)
from prompt_enhancer.application.history.comparison_strata_persistence import (
    AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION,
    AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
    AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION,
    COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION,
    EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
    EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION,
    STORED_SESSION_ANALYSIS_RUN_BRIDGE_V1_VERSION,
    AutomationGrantIdentityBridgeV1,
    RepositoryPreparedComparisonStratumV1,
    RepositorySealedComparisonStratumV1,
    TemporalComparisonStratumRepositoryV2,
    stored_session_analysis_run_bridge_fingerprint_v1,
    temporal_automation_grant_snapshot_fingerprint_v1,
)
from prompt_enhancer.application.history.contracts import (
    EstimatorLifecycleState,
    MetricComparisonIdentity,
    ProjectMetricSelectionRevisionV2,
    RepositoryTemporalBatchSealDraft,
    TemporalMetricObservationV2,
    TemporalObservationBatchV2,
)
from prompt_enhancer.application.history.persistence import (
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
)
from prompt_enhancer.application.persistence.contracts import (
    SessionAnalysisRunDraft,
    SessionAnalysisRunRecord,
)
from tests import test_temporal_comparison_strata_contracts as fixtures


DOWNSTREAM_CAPABILITIES = (
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
)


def _temporal_scope(
    grant: ComparisonAutomationGrantAuthorityV1,
    *,
    temporal_fingerprint: str | None = None,
) -> RepositoryPreparedTemporalScopeV1:
    base = fixtures._temporal_scope(grant)
    exact_temporal_fingerprint = (
        temporal_automation_grant_snapshot_fingerprint_v1(grant)
        if temporal_fingerprint is None
        else temporal_fingerprint
    )
    selection = ProjectMetricSelectionRevisionV2.revalidate_for_persistence(
        base.selection_revision.model_copy(
            update={"source_authority_fingerprint": exact_temporal_fingerprint}
        )
    )
    return RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(
        base.model_copy(
            update={
                "selection_revision": selection,
                "automation_grant_fingerprint": exact_temporal_fingerprint,
            }
        )
    )


def _bridge(
    grant: ComparisonAutomationGrantAuthorityV1,
    scope: RepositoryPreparedTemporalScopeV1,
    **updates: object,
) -> AutomationGrantIdentityBridgeV1:
    values: dict[str, object] = {
        "grant_id": grant.grant_id,
        "revision": grant.revision,
        "temporal_snapshot_fingerprint": scope.automation_grant_fingerprint,
        "comparison_authority_fingerprint": grant.fingerprint,
    }
    values.update(updates)
    values["bridge_fingerprint"] = AutomationGrantIdentityBridgeV1.fingerprint_for(
        grant_id=str(values["grant_id"]),
        revision=int(values["revision"]),
        temporal_snapshot_fingerprint=str(
            values["temporal_snapshot_fingerprint"]
        ),
        comparison_authority_fingerprint=str(
            values["comparison_authority_fingerprint"]
        ),
    )
    return AutomationGrantIdentityBridgeV1(**values)


def _prepared_components(
    *,
    temporal_fingerprint: str | None = None,
    revisions: tuple[object, ...] | None = None,
) -> dict[str, object]:
    base = fixtures._prepared(
        tuple(revisions)
        if revisions is not None
        else (fixtures._task_revision("repository-prepared", task_type="bug_fix"),)
    )
    scope = _temporal_scope(
        base.automation_grant,
        temporal_fingerprint=temporal_fingerprint,
    )
    bridge = _bridge(base.automation_grant, scope)
    return {
        "prepared_scope": scope,
        "analysis_job": base.analysis_job,
        "expected_run_request": base.expected_run_request,
        "session_authority": base.session_authority,
        "automation_grant": base.automation_grant,
        "automation_grant_scope_sha256": (
            automation_grant_scope_fingerprint(base.automation_grant.scope)
        ),
        "grant_identity_bridge": bridge,
        "dimensions": base.dimensions,
        "policies": base.policies,
        "prepared_at": base.prepared_at,
    }


def _prepared_id(components: dict[str, object]) -> str:
    return RepositoryPreparedComparisonStratumV1.prepared_stratum_id_for(
        prepared_scope=components["prepared_scope"],
        analysis_job=components["analysis_job"],
        expected_run_request=components["expected_run_request"],
        session_authority=components["session_authority"],
        automation_grant=components["automation_grant"],
        automation_grant_scope_sha256=components[
            "automation_grant_scope_sha256"
        ],
        grant_identity_bridge=components["grant_identity_bridge"],
        dimensions=components["dimensions"],
        policies=components["policies"],
        prepared_at=components["prepared_at"],
    )


def _prepared_order(components: dict[str, object]) -> tuple[str, ...]:
    return RepositoryPreparedComparisonStratumV1.ordered_graph_for(
        prepared_scope=components["prepared_scope"],
        analysis_job=components["analysis_job"],
        expected_run_request=components["expected_run_request"],
        session_authority=components["session_authority"],
        automation_grant=components["automation_grant"],
        grant_identity_bridge=components["grant_identity_bridge"],
        dimensions=components["dimensions"],
        policies=components["policies"],
    )


def _prepared_receipt(
    *,
    components: dict[str, object] | None = None,
) -> RepositoryPreparedComparisonStratumV1:
    values = _prepared_components() if components is None else components
    return RepositoryPreparedComparisonStratumV1(
        prepared_stratum_id=_prepared_id(values),
        ordered_graph_fingerprints=_prepared_order(values),
        **values,
    )


def _batch_with_exact_run_bridge(
    batch: RepositorySealedTemporalBatchV1,
    run: SessionAnalysisRunRecord,
    prepared: RepositoryPreparedComparisonStratumV1,
    *,
    run_fingerprint_override: str | None = None,
    run_fingerprint_version_override: str | None = None,
    provider_schema_version_override: str | None = None,
) -> RepositorySealedTemporalBatchV1:
    """Rebuild the synthetic batch with the exact production v21 bridge."""

    original_input = batch.completion_request.analysis_input
    draft = run.draft
    expected_run_fingerprint = stored_session_analysis_run_bridge_fingerprint_v1(
        request_fingerprint=draft.request_fingerprint,
        input_fingerprint=draft.input_fingerprint,
        analysis_profile_key=draft.analysis_profile_key,
        analysis_profile_version=draft.analysis_profile_version,
        metric_pack_key=draft.metric_pack_key,
        metric_pack_version=draft.metric_pack_version,
        selected_metric_keys=draft.selected_metric_keys,
        provider=draft.provider.value,
        provider_version=draft.provider_version,
        adapter_version=draft.adapter_version,
        source_schema_version=draft.source_schema_version,
        content_schema_version=draft.content_schema_version,
        metric_engine_version=draft.metric_engine_version,
        redactor_version=draft.redactor_version,
        model_plan_fingerprint=draft.model_plan_fingerprint,
        schema_version=draft.schema_version,
        analysis_window_fingerprint=original_input.analysis_window_fingerprint,
    )
    run_fingerprint = run_fingerprint_override or expected_run_fingerprint
    run_fingerprint_version = (
        run_fingerprint_version_override
        or STORED_SESSION_ANALYSIS_RUN_BRIDGE_V1_VERSION
    )
    provider_schema_version = (
        provider_schema_version_override
        or prepared.analysis_job.identity.provider_schema_version
    )
    analysis_input = type(original_input).model_validate(
        original_input.model_copy(
            update={
                "analysis_run_fingerprint": run_fingerprint,
                "analysis_run_fingerprint_version": run_fingerprint_version,
                "provider_schema_version": provider_schema_version,
            }
        ).model_dump(mode="python")
    )
    old_draft = batch.seal_draft
    old_revision = old_draft.session_revision
    revision = type(old_revision).revalidate_for_persistence(
        old_revision.model_copy(
            update={
                "analysis_input_receipt_fingerprint": analysis_input.fingerprint,
                "input_provenance_fingerprint": analysis_input.provenance_fingerprint,
                "analysis_run_fingerprint": run_fingerprint,
                "provider_schema_version": analysis_input.provider_schema_version,
            }
        )
    )
    old_observation_batch = old_draft.observation_batch
    observations = []
    for old_observation in old_observation_batch.observations:
        identity = MetricComparisonIdentity.model_validate(
            old_observation.comparison_identity.model_copy(
                update={
                    "provider_schema_version": analysis_input.provider_schema_version
                }
            ).model_dump(mode="python")
        )
        observations.append(
            TemporalMetricObservationV2.model_validate(
                old_observation.model_copy(
                    update={
                        "analysis_input_receipt_fingerprint": (
                            analysis_input.fingerprint
                        ),
                        "comparison_identity": identity,
                    }
                ).model_dump(mode="python")
            )
        )
    observation_batch = TemporalObservationBatchV2.model_validate(
        old_observation_batch.model_copy(
            update={
                "revision_fingerprint": revision.fingerprint,
                "analysis_run_fingerprint": run_fingerprint,
                "analysis_input_receipt_fingerprint": analysis_input.fingerprint,
                "observations": tuple(observations),
            }
        ).model_dump(mode="python")
    )
    seal_draft = RepositoryTemporalBatchSealDraft.revalidate_for_persistence(
        old_draft.model_copy(
            update={
                "analysis_input": analysis_input,
                "session_revision": revision,
                "observation_batch": observation_batch,
                "analysis_run_fingerprint": run_fingerprint,
                "ordered_observation_ids": tuple(
                    item.observation_id for item in observations
                ),
                "ordered_observation_fingerprints": tuple(
                    item.fingerprint for item in observations
                ),
            }
        )
    )
    old_request = batch.completion_request
    request = type(old_request).revalidate_for_persistence(
        old_request.model_copy(update={"analysis_input": analysis_input})
    )
    return RepositorySealedTemporalBatchV1.revalidate_for_persistence(
        batch.model_copy(
            update={
                "completion_request": request,
                "completion_request_fingerprint": request.fingerprint,
                "seal_draft": seal_draft,
                "seal_draft_fingerprint": seal_draft.fingerprint,
                "ordered_graph_fingerprints": (
                    RepositorySealedTemporalBatchV1.ordered_graph_for(
                        request, seal_draft
                    )
                ),
            }
        )
    )


def _sealed_components(
    prepared: RepositoryPreparedComparisonStratumV1 | None = None,
) -> dict[str, object]:
    receipt = prepared or _prepared_receipt()
    batch = fixtures._sealed_batch(receipt)
    run = fixtures._analysis_run(receipt, batch)
    batch = _batch_with_exact_run_bridge(batch, run, receipt)
    sealed_at = batch.sealed_at + timedelta(seconds=1)
    revalidation = fixtures._automation_revalidation_request(
        receipt,
        reverified_at=sealed_at,
    )
    return {
        "prepared_receipt": receipt,
        "analysis_run": run,
        "analysis_run_authority_sha256": (
            session_analysis_run_authority_fingerprint(run)
        ),
        "sealed_batch": batch,
        "sealed_batch_sha256": batch.fingerprint,
        "automation_revalidation_request": revalidation,
        "sealed_at": sealed_at,
    }


def _sealed_order(values: dict[str, object]) -> tuple[str, ...]:
    return RepositorySealedComparisonStratumV1.ordered_authority_for(
        prepared_receipt=values["prepared_receipt"],
        analysis_run=values["analysis_run"],
        sealed_batch=values["sealed_batch"],
        automation_revalidation_request=values[
            "automation_revalidation_request"
        ],
    )


def _sealed_id(values: dict[str, object]) -> str:
    return RepositorySealedComparisonStratumV1.sealed_stratum_id_for(
        prepared_receipt=values["prepared_receipt"],
        analysis_run=values["analysis_run"],
        sealed_batch=values["sealed_batch"],
        automation_revalidation_request=values[
            "automation_revalidation_request"
        ],
        sealed_at=values["sealed_at"],
    )


def _sealed_receipt(
    *,
    components: dict[str, object] | None = None,
) -> RepositorySealedComparisonStratumV1:
    values = _sealed_components() if components is None else components
    return RepositorySealedComparisonStratumV1(
        sealed_stratum_id=_sealed_id(values),
        ordered_authority_fingerprints=_sealed_order(values),
        **values,
    )


def _changed_run_input(
    values: dict[str, object],
    input_fingerprint: str,
) -> dict[str, object]:
    run = values["analysis_run"]
    run_draft = SessionAnalysisRunDraft.model_validate(
        run.draft.model_copy(
            update={"input_fingerprint": input_fingerprint}
        ).model_dump(mode="python")
    )
    changed_run = SessionAnalysisRunRecord.model_validate(
        run.model_copy(update={"draft": run_draft}).model_dump(mode="python")
    )
    changed_batch = _batch_with_exact_run_bridge(
        values["sealed_batch"],
        changed_run,
        values["prepared_receipt"],
    )
    return {
        **values,
        "analysis_run": changed_run,
        "analysis_run_authority_sha256": (
            session_analysis_run_authority_fingerprint(changed_run)
        ),
        "sealed_batch": changed_batch,
        "sealed_batch_sha256": changed_batch.fingerprint,
    }


def _changed_metric_identity(
    values: dict[str, object],
    update: dict[str, object],
) -> dict[str, object]:
    batch = values["sealed_batch"]
    temporal_draft = batch.seal_draft
    observation_batch = temporal_draft.observation_batch
    observation = observation_batch.observations[0]
    identity = MetricComparisonIdentity.model_validate(
        observation.comparison_identity.model_copy(update=update).model_dump(
            mode="python"
        )
    )
    changed_observation = TemporalMetricObservationV2.model_validate(
        observation.model_copy(update={"comparison_identity": identity}).model_dump(
            mode="python"
        )
    )
    changed_observation_batch = TemporalObservationBatchV2.model_validate(
        observation_batch.model_copy(
            update={"observations": (changed_observation,)}
        ).model_dump(mode="python")
    )
    changed_temporal_draft = RepositoryTemporalBatchSealDraft.revalidate_for_persistence(
        temporal_draft.model_copy(
            update={
                "observation_batch": changed_observation_batch,
                "ordered_observation_ids": (changed_observation.observation_id,),
                "ordered_observation_fingerprints": (
                    changed_observation.fingerprint,
                ),
            }
        )
    )
    changed_batch = RepositorySealedTemporalBatchV1.revalidate_for_persistence(
        batch.model_copy(
            update={
                "seal_draft": changed_temporal_draft,
                "seal_draft_fingerprint": changed_temporal_draft.fingerprint,
                "ordered_graph_fingerprints": (
                    RepositorySealedTemporalBatchV1.ordered_graph_for(
                        batch.completion_request,
                        changed_temporal_draft,
                    )
                ),
            }
        )
    )
    return {
        **values,
        "sealed_batch": changed_batch,
        "sealed_batch_sha256": changed_batch.fingerprint,
    }


def _changed_revalidation(
    values: dict[str, object],
    repository_authority: str,
) -> dict[str, object]:
    request = values["automation_revalidation_request"]
    request_type = type(request)
    authority_sha256 = request_type.authority_for(
        authority_receipt_id=request.authority_receipt_id,
        prepared_stratum_id=request.prepared_stratum_id,
        prepared_stratum_fingerprint=request.prepared_stratum_fingerprint,
        analysis_job_id=request.analysis_job_id,
        analysis_job_record_authority_fingerprint=(
            request.analysis_job_record_authority_fingerprint
        ),
        current_job_state=request.current_job_state,
        current_job_lease_authority_fingerprint=(
            request.current_job_lease_authority_fingerprint
        ),
        current_job_lease_expires_at=request.current_job_lease_expires_at,
        automation_grant_id=request.automation_grant_id,
        current_grant_revision=request.current_grant_revision,
        current_grant_authority_fingerprint=(
            request.current_grant_authority_fingerprint
        ),
        current_grant_expires_at=request.current_grant_expires_at,
        reverified_at=request.reverified_at,
        repository_revalidation_authority_fingerprint=repository_authority,
    )
    changed = AutomationRevalidationRequestV1.revalidate_for_persistence(
        request.model_copy(
            update={
                "repository_revalidation_authority_fingerprint": (
                    repository_authority
                ),
                "authority_sha256": authority_sha256,
            }
        )
    )
    return {**values, "automation_revalidation_request": changed}


def test_code_owned_contract_and_verifier_identities_are_fixed() -> None:
    assert AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION == (
        "automation-grant-identity-bridge-v1"
    )
    assert AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION == (
        "automation-grant-identity-bridge-verifier-v1"
    )
    assert EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION == (
        "comparison-expected-run-id-issuance-verifier-v1"
    )
    assert COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION == (
        "comparison-stratum-repository-verifier-v1"
    )
    assert len(AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT) == 64
    assert len(EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT) == 64
    assert len(COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT) == 64
    assert len(
        {
            AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
            EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
            COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
        }
    ) == 3


def test_distinct_grant_fingerprint_domains_bridge_successfully() -> None:
    receipt = _prepared_receipt()
    bridge = receipt.grant_identity_bridge
    assert bridge.temporal_snapshot_fingerprint == (
        receipt.prepared_scope.automation_grant_fingerprint
    )
    assert bridge.comparison_authority_fingerprint == (
        receipt.automation_grant.fingerprint
    )
    assert bridge.temporal_snapshot_fingerprint != (
        bridge.comparison_authority_fingerprint
    )
    assert bridge.grant_id == receipt.automation_grant.grant_id
    assert bridge.revision == receipt.automation_grant.revision
    assert bridge.repository_rehydration_required
    assert bridge.structurally_constructible_not_capability
    assert AutomationGrantIdentityBridgeV1.revalidate_for_persistence(bridge) == bridge


@pytest.mark.parametrize(
    "mutation",
    ("grant_id", "revision", "temporal_fingerprint", "comparison_fingerprint"),
)
def test_bridge_tamper_or_wrong_grant_binding_is_rejected(mutation: str) -> None:
    components = _prepared_components()
    grant = components["automation_grant"]
    scope = components["prepared_scope"]
    updates: dict[str, object]
    if mutation == "grant_id":
        updates = {"grant_id": fixtures._id("wrong-bridge-grant")}
    elif mutation == "revision":
        updates = {"revision": grant.revision + 1}
    elif mutation == "temporal_fingerprint":
        updates = {
            "temporal_snapshot_fingerprint": fixtures._id(
                "wrong-temporal-grant-fingerprint"
            )
        }
    else:
        updates = {
            "comparison_authority_fingerprint": fixtures._id(
                "wrong-comparison-grant-fingerprint"
            )
        }
    components["grant_identity_bridge"] = _bridge(grant, scope, **updates)
    with pytest.raises(ValidationError, match="bridge|same revision"):
        _prepared_receipt(components=components)


def test_bridge_internal_fingerprint_tamper_is_rejected() -> None:
    bridge = _prepared_components()["grant_identity_bridge"]
    with pytest.raises(ValidationError, match="fingerprint"):
        AutomationGrantIdentityBridgeV1.revalidate_for_persistence(
            bridge.model_copy(
                update={"bridge_fingerprint": fixtures._id("forged-bridge")}
            )
        )


@pytest.mark.parametrize(
    "scope_axis",
    (
        "newest_session_limit",
        "check_interval_seconds",
        "route",
        "max_cpu_workers",
        "pause_on_battery",
        "maximum_session_seconds",
    ),
)
def test_full_grant_scope_must_rederive_both_bridge_domains(
    scope_axis: str,
) -> None:
    values = _prepared_components()
    baseline_grant = values["automation_grant"]
    scope = baseline_grant.scope
    resource = scope.resource_policy
    if scope_axis == "newest_session_limit":
        changed_scope = scope.model_copy(
            update={"newest_session_limit": scope.newest_session_limit + 1}
        )
    elif scope_axis == "check_interval_seconds":
        changed_scope = scope.model_copy(
            update={"check_interval_seconds": scope.check_interval_seconds + 60}
        )
    else:
        resource_updates = {
            "route": type(resource.route).FAST,
            "max_cpu_workers": resource.max_cpu_workers + 1,
            "pause_on_battery": not resource.pause_on_battery,
            "maximum_session_seconds": resource.maximum_session_seconds + 60,
        }
        changed_scope = scope.model_copy(
            update={
                "resource_policy": resource.model_copy(
                    update={scope_axis: resource_updates[scope_axis]}
                )
            }
        )
    changed_record = fixtures._grant_record(scope=changed_scope)
    changed_grant = fixtures._grant_authority(changed_record)
    values.update(
        {
            "automation_grant": changed_grant,
            "automation_grant_scope_sha256": (
                automation_grant_scope_fingerprint(changed_grant.scope)
            ),
            "grant_identity_bridge": _bridge(
                changed_grant,
                values["prepared_scope"],
            ),
        }
    )
    with pytest.raises(ValidationError, match="full temporal snapshot"):
        _prepared_receipt(components=values)


def test_valid_full_grant_scope_change_moves_both_hashes_and_prepared_id() -> None:
    baseline = _prepared_components()
    baseline_id = _prepared_id(baseline)
    baseline_grant = baseline["automation_grant"]
    changed_scope = baseline_grant.scope.model_copy(
        update={
            "newest_session_limit": baseline_grant.scope.newest_session_limit + 1
        }
    )
    changed_base = fixtures._prepared(
        (fixtures._task_revision("repository-prepared", task_type="bug_fix"),),
        grant_record=fixtures._grant_record(scope=changed_scope),
    )
    temporal_scope = _temporal_scope(changed_base.automation_grant)
    changed = {
        "prepared_scope": temporal_scope,
        "analysis_job": changed_base.analysis_job,
        "expected_run_request": changed_base.expected_run_request,
        "session_authority": changed_base.session_authority,
        "automation_grant": changed_base.automation_grant,
        "automation_grant_scope_sha256": automation_grant_scope_fingerprint(
            changed_base.automation_grant.scope
        ),
        "grant_identity_bridge": _bridge(
            changed_base.automation_grant, temporal_scope
        ),
        "dimensions": changed_base.dimensions,
        "policies": changed_base.policies,
        "prepared_at": changed_base.prepared_at,
    }
    receipt = _prepared_receipt(components=changed)
    assert receipt.grant_identity_bridge.temporal_snapshot_fingerprint != (
        baseline["grant_identity_bridge"].temporal_snapshot_fingerprint
    )
    assert receipt.grant_identity_bridge.comparison_authority_fingerprint != (
        baseline["grant_identity_bridge"].comparison_authority_fingerprint
    )
    assert receipt.prepared_stratum_id != baseline_id


@pytest.mark.parametrize(
    "verifier_fingerprint",
    (
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    ),
)
def test_prepared_scope_id_cannot_collide_with_fixed_verifier(
    verifier_fingerprint: str,
) -> None:
    values = _prepared_components()
    scope = RepositoryPreparedTemporalScopeV1.revalidate_for_persistence(
        values["prepared_scope"].model_copy(
            update={
                "prepared_scope_id": (
                    verifier_fingerprint
                )
            }
        )
    )
    values["prepared_scope"] = scope
    with pytest.raises(ValidationError, match="role-separated"):
        _prepared_receipt(components=values)


def test_prepared_receipt_verifies_only_the_bounded_repository_graph() -> None:
    receipt = _prepared_receipt()
    components = _prepared_components()
    assert receipt.prepared_stratum_id == _prepared_id(components)
    assert receipt.ordered_graph_fingerprints == _prepared_order(components)
    assert len(receipt.ordered_graph_fingerprints) == 13
    assert receipt.repository_return_required
    assert receipt.structurally_constructible_not_capability
    assert receipt.repository_owned
    assert receipt.repository_graph_verified
    assert receipt.task_selection_authority_verified
    assert receipt.bounded_task_completeness_verified
    assert receipt.expected_run_id_issuance_verified
    assert receipt.sealed
    assert not receipt.run_authority_verified
    assert not receipt.batch_authority_verified
    assert not receipt.comparison_stratum_complete
    assert all(not getattr(receipt, field) for field in DOWNSTREAM_CAPABILITIES)
    assert RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
        receipt
    ) == receipt


def test_sealed_receipt_verifies_run_and_batch_graphs_only() -> None:
    receipt = _sealed_receipt()
    assert len(receipt.ordered_authority_fingerprints) == 12
    assert receipt.ordered_authority_fingerprints[8] == (
        receipt.prepared_receipt.fingerprint
    )
    assert receipt.repository_return_required
    assert receipt.structurally_constructible_not_capability
    assert receipt.repository_owned
    assert receipt.repository_graph_verified
    assert receipt.run_graph_verified
    assert receipt.batch_graph_verified
    assert receipt.sealed
    assert not receipt.comparison_stratum_complete
    assert all(not getattr(receipt, field) for field in DOWNSTREAM_CAPABILITIES)
    assert RepositorySealedComparisonStratumV1.revalidate_for_persistence(
        receipt
    ) == receipt


@pytest.mark.parametrize("field", DOWNSTREAM_CAPABILITIES)
def test_downstream_capability_promotion_is_rejected(field: str) -> None:
    prepared = _prepared_receipt()
    with pytest.raises(ValidationError):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            prepared.model_copy(update={field: True})
        )
    sealed = _sealed_receipt()
    with pytest.raises(ValidationError):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            sealed.model_copy(update={field: True})
        )


@pytest.mark.parametrize(
    "field",
    ("run_authority_verified", "batch_authority_verified", "comparison_stratum_complete"),
)
def test_prepared_receipt_cannot_claim_completion(field: str) -> None:
    receipt = _prepared_receipt()
    with pytest.raises(ValidationError):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(update={field: True})
        )


def test_sealed_receipt_cannot_claim_complete_comparison_stratum() -> None:
    receipt = _sealed_receipt()
    with pytest.raises(ValidationError):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(update={"comparison_stratum_complete": True})
        )


def test_prepared_order_is_exact_and_cardinality_bounded() -> None:
    receipt = _prepared_receipt()
    with pytest.raises(ValidationError, match="exact ordered graph"):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(
                update={
                    "ordered_graph_fingerprints": tuple(
                        reversed(receipt.ordered_graph_fingerprints)
                    )
                }
            )
        )
    with pytest.raises(ValidationError):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(update={"ordered_graph_fingerprints": ()})
        )


def test_sealed_order_is_exact_unique_and_exactly_twelve() -> None:
    receipt = _sealed_receipt()
    with pytest.raises(ValidationError, match="exact ordered authority"):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(
                update={
                    "ordered_authority_fingerprints": tuple(
                        reversed(receipt.ordered_authority_fingerprints)
                    )
                }
            )
        )
    duplicate = list(receipt.ordered_authority_fingerprints)
    duplicate[1] = duplicate[0]
    with pytest.raises(ValidationError, match="role-separated"):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(
                update={"ordered_authority_fingerprints": tuple(duplicate)}
            )
        )
    with pytest.raises(ValidationError):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(
                update={
                    "ordered_authority_fingerprints": (
                        receipt.ordered_authority_fingerprints[:-1]
                    )
                }
            )
        )


@pytest.mark.parametrize(
    "component",
    (
        "prepared_scope",
        "analysis_job",
        "expected_run_request",
        "session_authority",
        "automation_grant",
        "automation_grant_scope_sha256",
        "grant_identity_bridge",
        "dimensions",
        "policies",
        "prepared_at",
    ),
)
def test_prepared_id_moves_with_every_independent_component(component: str) -> None:
    values = _prepared_components()
    baseline = _prepared_id(values)
    changed = dict(values)
    current = values[component]
    if component == "prepared_scope":
        changed[component] = current.model_copy(
            update={"prepared_at": current.prepared_at + timedelta(seconds=1)}
        )
    elif component == "analysis_job":
        changed[component] = current.model_copy(
            update={"lease_expires_at": current.lease_expires_at + timedelta(seconds=1)}
        )
    elif component == "expected_run_request":
        changed[component] = current.model_copy(
            update={"request_sha256": fixtures._id("changed-request-root")}
        )
    elif component == "session_authority":
        changed[component] = current.model_copy(
            update={"ended_at": current.started_at + timedelta(seconds=1)}
        )
    elif component == "automation_grant":
        changed[component] = current.model_copy(
            update={"authority_sha256": fixtures._id("changed-grant-root")}
        )
    elif component == "automation_grant_scope_sha256":
        changed[component] = fixtures._id("changed-grant-scope-root")
    elif component == "grant_identity_bridge":
        changed[component] = current.model_copy(
            update={"bridge_fingerprint": fixtures._id("changed-bridge-root")}
        )
    elif component == "dimensions":
        changed[component] = current.model_copy(
            update={"project_id": fixtures._id("changed-dimensions-root")}
        )
    elif component == "policies":
        changed[component] = current.model_copy(
            update={"matching": current.matching.model_copy(update={"sha256": fixtures._id("changed-policy-root")})}
        )
    else:
        changed[component] = current + timedelta(seconds=1)
    assert _prepared_id(changed) != baseline


def test_each_grant_fingerprint_domain_moves_prepared_id_independently() -> None:
    baseline = _prepared_components()
    baseline_id = _prepared_id(baseline)

    temporal = _prepared_components(
        temporal_fingerprint=fixtures._id("other-temporal-grant-domain")
    )
    assert _prepared_id(temporal) != baseline_id

    grant_record = fixtures._grant_record(
        renewed_at=fixtures.FLOOR - timedelta(days=1) + timedelta(seconds=1)
    )
    comparison_base = fixtures._prepared(
        (fixtures._task_revision("repository-prepared", task_type="bug_fix"),),
        grant_record=grant_record,
    )
    scope = _temporal_scope(comparison_base.automation_grant)
    comparison = {
        "prepared_scope": scope,
        "analysis_job": comparison_base.analysis_job,
        "expected_run_request": comparison_base.expected_run_request,
        "session_authority": comparison_base.session_authority,
        "automation_grant": comparison_base.automation_grant,
        "automation_grant_scope_sha256": automation_grant_scope_fingerprint(
            comparison_base.automation_grant.scope
        ),
        "grant_identity_bridge": _bridge(
            comparison_base.automation_grant,
            scope,
        ),
        "dimensions": comparison_base.dimensions,
        "policies": comparison_base.policies,
        "prepared_at": comparison_base.prepared_at,
    }
    assert comparison_base.automation_grant.fingerprint != (
        baseline["automation_grant"].fingerprint
    )
    assert _prepared_id(comparison) != baseline_id


def test_grant_id_revision_and_full_scope_mismatch_remain_rejected() -> None:
    baseline = _prepared_receipt()
    for update in (
        {"grant_id": fixtures._id("other-grant-id")},
        {"revision": baseline.automation_grant.revision + 1},
        {
            "scope": baseline.automation_grant.scope.model_copy(
                update={"metric_keys": ("reserved.other.metric",)}
            )
        },
    ):
        grant = baseline.automation_grant.model_copy(update=update)
        with pytest.raises(ValidationError):
            RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
                baseline.model_copy(update={"automation_grant": grant})
            )


@pytest.mark.parametrize(
    "component",
    ("prepared_receipt", "analysis_run", "sealed_batch", "revalidation", "sealed_at"),
)
def test_sealed_id_moves_with_every_independent_component(component: str) -> None:
    values = _sealed_components()
    baseline = _sealed_id(values)
    if component == "prepared_receipt":
        other = _prepared_receipt(
            components=_prepared_components(
                revisions=(
                    fixtures._task_revision(
                        "other-prepared",
                        task_type="research_design",
                    ),
                )
            )
        )
        changed = {**values, "prepared_receipt": other}
    elif component == "analysis_run":
        changed = _changed_run_input(
            values,
            fixtures._id("other-run-input-root"),
        )
    elif component == "sealed_batch":
        changed = _changed_metric_identity(
            values,
            {
                "metric_definition_version": "reserved-other-definition-v1",
                "metric_definition_sha256": fixtures._id("other-definition-root"),
            },
        )
    elif component == "revalidation":
        changed = _changed_revalidation(
            values,
            fixtures._id("other-revalidation-root"),
        )
    else:
        changed = {**values, "sealed_at": values["sealed_at"] + timedelta(seconds=1)}
    assert _sealed_id(changed) != baseline


@pytest.mark.parametrize(
    "axis",
    (
        "request_fingerprint",
        "input_fingerprint",
        "analysis_profile_key",
        "analysis_profile_version",
        "metric_pack_key",
        "metric_pack_version",
        "selected_metric_keys",
        "provider",
        "provider_version",
        "adapter_version",
        "source_schema_version",
        "content_schema_version",
        "metric_engine_version",
        "redactor_version",
        "model_plan_fingerprint",
        "schema_version",
        "analysis_window_fingerprint",
    ),
)
def test_stored_run_bridge_moves_with_every_production_input(axis: str) -> None:
    values = _sealed_components()
    run = values["analysis_run"].draft
    analysis_input = values["sealed_batch"].completion_request.analysis_input
    arguments: dict[str, object] = {
        "request_fingerprint": run.request_fingerprint,
        "input_fingerprint": run.input_fingerprint,
        "analysis_profile_key": run.analysis_profile_key,
        "analysis_profile_version": run.analysis_profile_version,
        "metric_pack_key": run.metric_pack_key,
        "metric_pack_version": run.metric_pack_version,
        "selected_metric_keys": run.selected_metric_keys,
        "provider": run.provider.value,
        "provider_version": run.provider_version,
        "adapter_version": run.adapter_version,
        "source_schema_version": run.source_schema_version,
        "content_schema_version": run.content_schema_version,
        "metric_engine_version": run.metric_engine_version,
        "redactor_version": run.redactor_version,
        "model_plan_fingerprint": run.model_plan_fingerprint,
        "schema_version": run.schema_version,
        "analysis_window_fingerprint": analysis_input.analysis_window_fingerprint,
    }
    baseline = stored_session_analysis_run_bridge_fingerprint_v1(**arguments)
    current = arguments[axis]
    if isinstance(current, int):
        arguments[axis] = current + 1
    elif isinstance(current, tuple):
        arguments[axis] = (*current, "reserved.other.metric")
    elif axis in {
        "request_fingerprint",
        "input_fingerprint",
        "model_plan_fingerprint",
        "analysis_window_fingerprint",
    }:
        arguments[axis] = fixtures._id(f"other-{axis}")
    else:
        arguments[axis] = f"reserved-other-{axis}"
    assert stored_session_analysis_run_bridge_fingerprint_v1(**arguments) != baseline


@pytest.mark.parametrize(
    "mutation",
    ("stored_input", "temporal_bridge_fingerprint", "temporal_bridge_version"),
)
def test_seal_rejects_stale_or_wrong_stored_run_bridge(mutation: str) -> None:
    values = _sealed_components()
    if mutation == "stored_input":
        run = values["analysis_run"]
        changed_draft = SessionAnalysisRunDraft.model_validate(
            run.draft.model_copy(
                update={"input_fingerprint": fixtures._id("stale-run-input")}
            ).model_dump(mode="python")
        )
        changed_run = SessionAnalysisRunRecord.model_validate(
            run.model_copy(update={"draft": changed_draft}).model_dump(
                mode="python"
            )
        )
        values.update(
            {
                "analysis_run": changed_run,
                "analysis_run_authority_sha256": (
                    session_analysis_run_authority_fingerprint(changed_run)
                ),
            }
        )
    else:
        batch = _batch_with_exact_run_bridge(
            values["sealed_batch"],
            values["analysis_run"],
            values["prepared_receipt"],
            run_fingerprint_override=(
                fixtures._id("wrong-temporal-run-bridge")
                if mutation == "temporal_bridge_fingerprint"
                else None
            ),
            run_fingerprint_version_override=(
                "reserved-wrong-run-bridge-v1"
                if mutation == "temporal_bridge_version"
                else None
            ),
        )
        values.update(
            {"sealed_batch": batch, "sealed_batch_sha256": batch.fingerprint}
        )
    with pytest.raises(ValidationError, match="stored-run fingerprint bridge"):
        _sealed_receipt(components=values)


def test_seal_rejects_temporal_provider_schema_mismatch_with_job() -> None:
    values = _sealed_components()
    batch = _batch_with_exact_run_bridge(
        values["sealed_batch"],
        values["analysis_run"],
        values["prepared_receipt"],
        provider_schema_version_override="reserved-other-provider-schema-v1",
    )
    values.update(
        {"sealed_batch": batch, "sealed_batch_sha256": batch.fingerprint}
    )
    with pytest.raises(ValidationError, match="session or job provenance"):
        _sealed_receipt(components=values)


@pytest.mark.parametrize(
    "verifier_fingerprint",
    (
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    ),
)
def test_run_input_verifier_collision_is_rejected(
    verifier_fingerprint: str,
) -> None:
    values = _changed_run_input(
        _sealed_components(),
        verifier_fingerprint,
    )
    with pytest.raises(ValidationError, match="role-separated"):
        _sealed_receipt(components=values)


@pytest.mark.parametrize(
    "verifier_fingerprint",
    (
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    ),
)
def test_required_metric_digest_verifier_collision_is_rejected(
    verifier_fingerprint: str,
) -> None:
    values = _changed_metric_identity(
        _sealed_components(),
        {
            "metric_definition_version": "reserved-colliding-definition-v1",
            "metric_definition_sha256": verifier_fingerprint,
        },
    )
    with pytest.raises(ValidationError, match="role-separated"):
        _sealed_receipt(components=values)


@pytest.mark.parametrize(
    "verifier_fingerprint",
    (
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT,
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    ),
)
def test_optional_metric_digest_verifier_collision_is_rejected(
    verifier_fingerprint: str,
) -> None:
    values = _changed_metric_identity(
        _sealed_components(),
        {
            "estimator_lifecycle": EstimatorLifecycleState.ACTIVATED,
            "activation_receipt_sha256": verifier_fingerprint,
        },
    )
    with pytest.raises(ValidationError, match="role-separated"):
        _sealed_receipt(components=values)


def test_recursive_revalidation_rejects_nested_prepared_model_copy() -> None:
    receipt = _prepared_receipt()
    dimensions = receipt.dimensions.model_copy(update={"language_code": "en"})
    with pytest.raises(ValidationError):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(update={"dimensions": dimensions})
        )


def test_recursive_revalidation_rejects_nested_sealed_model_copy() -> None:
    receipt = _sealed_receipt()
    run_draft = receipt.analysis_run.draft.model_copy(update={"local_only": False})
    run = receipt.analysis_run.model_copy(update={"draft": run_draft})
    with pytest.raises(ValidationError):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            receipt.model_copy(update={"analysis_run": run})
        )


def test_repository_chronology_and_canonical_utc_are_enforced() -> None:
    prepared = _prepared_receipt()
    with pytest.raises(ValidationError):
        RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            prepared.model_copy(update={"prepared_at": fixtures.FLOOR})
        )
    noncanonical = prepared.prepared_at.astimezone(timezone(timedelta(hours=1)))
    with pytest.raises(ValidationError, match="canonical UTC"):
        RepositoryPreparedComparisonStratumV1(
            **{**prepared.model_dump(), "prepared_at": noncanonical}
        )
    sealed = _sealed_receipt()
    with pytest.raises(ValidationError, match="chronology"):
        RepositorySealedComparisonStratumV1.revalidate_for_persistence(
            sealed.model_copy(update={"sealed_at": prepared.prepared_at})
        )


def test_preparation_rejects_session_ending_after_preparation() -> None:
    values = _prepared_components()
    session = ComparisonSessionAuthorityV1.revalidate_for_persistence(
        values["session_authority"].model_copy(
            update={"ended_at": values["prepared_at"] + timedelta(seconds=1)}
        )
    )
    values["session_authority"] = session
    with pytest.raises(ValidationError, match="completed session"):
        _prepared_receipt(components=values)


def test_seal_rejects_run_starting_after_its_finish() -> None:
    values = _sealed_components()
    run = values["analysis_run"]
    assert run.finished_at is not None
    forged_run = run.model_copy(
        update={
            "draft": run.draft.model_copy(
                update={"started_at": run.finished_at + timedelta(seconds=1)}
            )
        }
    )
    values.update(
        {
            "analysis_run": forged_run,
            "analysis_run_authority_sha256": (
                session_analysis_run_authority_fingerprint(forged_run)
            ),
        }
    )
    with pytest.raises(ValidationError):
        _sealed_receipt(components=values)


def test_serialized_receipts_are_content_free_and_omit_lease_secrets() -> None:
    serialized = _sealed_receipt().model_dump_json()
    forbidden = (
        "lease_owner",
        "lease_token",
        "prompt_text",
        "response_text",
        "transcript",
        "excerpt",
        "source_path",
        "credential",
        "project_display_name",
        "session_display_name",
    )
    assert all(value not in serialized for value in forbidden)


def test_v2_protocol_is_narrow_and_uses_private_ephemeral_authority() -> None:
    methods = {
        name
        for name, value in inspect.getmembers(
            TemporalComparisonStratumRepositoryV2,
            predicate=inspect.isfunction,
        )
        if not name.startswith("_")
    }
    assert methods == {
        "prepare_automation_stratum",
        "seal_automation_stratum",
        "get_prepared_stratum",
        "get_prepared_stratum_for_job",
        "get_sealed_stratum",
        "get_sealed_stratum_for_run",
        "get_sealed_stratum_for_batch",
    }
    prepare = inspect.signature(
        TemporalComparisonStratumRepositoryV2.prepare_automation_stratum
    )
    seal = inspect.signature(
        TemporalComparisonStratumRepositoryV2.seal_automation_stratum
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
    assert prepare.parameters["authority"].kind is inspect.Parameter.KEYWORD_ONLY
    assert seal.parameters["authority"].kind is inspect.Parameter.KEYWORD_ONLY
    annotations = inspect.get_annotations(
        TemporalComparisonStratumRepositoryV2.prepare_automation_stratum,
        eval_str=True,
    )
    assert annotations["authority"] is _AutomationComparisonLeaseAuthorityV1
    annotations = inspect.get_annotations(
        TemporalComparisonStratumRepositoryV2.seal_automation_stratum,
        eval_str=True,
    )
    assert annotations["authority"] is _AutomationComparisonLeaseAuthorityV1
    public_text = " ".join(sorted(methods))
    assert all(
        term not in public_text
        for term in (
            "task",
            "language",
            "complexity",
            "permission",
            "model",
            "policy",
            "clock",
            "fingerprint",
            "backfill",
            "manual",
            "update",
            "delete",
            "list",
        )
    )
