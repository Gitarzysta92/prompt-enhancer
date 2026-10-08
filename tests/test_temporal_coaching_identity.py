from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
import hashlib
import inspect

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.analysis.coaching_baselines import (
    COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from prompt_enhancer.application.analysis.text_contracts import (
    MetricDirection as TextMetricDirection,
)
from prompt_enhancer.application.history import coaching_identity as identity_module
from prompt_enhancer.application.history.coaching_identity import (
    COACHING_TEMPORAL_CALIBRATION_VERSION,
    COACHING_TEMPORAL_CATALOG_SHA256,
    COACHING_TEMPORAL_ENGINE_SHA256,
    COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
    COACHING_TEMPORAL_METRIC_KEYS,
    COACHING_TEMPORAL_PACK_SHA256,
    COACHING_TEMPORAL_PROFILE_KEY,
    COACHING_TEMPORAL_PROFILE_SHA256,
    COACHING_TEMPORAL_PROFILE_VERSION,
    CoachingTemporalIdentityCatalog,
)
from prompt_enhancer.application.history.contracts import (
    AnalysisInputExtractionCompleteness,
    AnalysisInputReceiptV2,
    AnalysisInputSelectionCoverage,
    EstimatorIdentityKind,
    EstimatorLifecycleState,
    EvidenceTier,
    MetricDirection,
    ProjectMetricSelectionAuthorityKind,
    ProjectMetricSelectionRevisionV2,
    ProjectMetricSelectionSource,
    TemporalAggregationSemantics,
    TemporalHistoryRootReceipt,
    TemporalTrendMethod,
    TemporalValueKind,
)
from prompt_enhancer.application.history.persistence import (
    RepositoryPreparedTemporalScopeV1,
    SyntheticTemporalCompletionRequestV1,
    automation_grant_authority_version,
)
from prompt_enhancer.domain import Provider


FLOOR = datetime(2045, 4, 5, 9, tzinfo=UTC)
GRANT_REVISION = 2


def _id(label: str) -> str:
    return hashlib.sha256(f"reserved-coaching-identity:{label}".encode()).hexdigest()


def _request(
    selected_keys: tuple[str, ...],
    *,
    pack_key: str = COACHING_METRIC_PACK_KEY,
    pack_version: int = COACHING_METRIC_PACK_VERSION,
    pack_sha256: str = COACHING_TEMPORAL_PACK_SHA256,
    catalog_version: str = COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
    catalog_sha256: str = COACHING_TEMPORAL_CATALOG_SHA256,
    profile_key: str = COACHING_TEMPORAL_PROFILE_KEY,
    profile_version: int = COACHING_TEMPORAL_PROFILE_VERSION,
    profile_sha256: str = COACHING_TEMPORAL_PROFILE_SHA256,
    engine_version: str | None = None,
    engine_sha256: str = COACHING_TEMPORAL_ENGINE_SHA256,
    model_plan_fingerprint: str = _id("installation-keyed-run-plan-a"),
    router_version: str = "reserved-router-v1",
    provider_version: str = "reserved-synthetic-provider-v1",
    capture_contract_version: str = "reserved-synthetic-capture-v1",
    consent_policy_version: str = "reserved-consent-v1",
    provider_adapter_version: str = "reserved-synthetic-adapter-v1",
    provider_schema_version: str = "reserved-provider-schema-v1",
    source_schema_version: str = "reserved-source-schema-v1",
    content_schema_version: str = "reserved-content-schema-v1",
    privacy_policy_version: str = "reserved-privacy-v1",
    preprocessing_version: str = "reserved-preprocessing-v1",
    preprocessing_sha256: str = _id("preprocessing"),
    router_sha256: str = _id("router"),
    redactor_version: str = "reserved-redactor-v1",
    redactor_sha256: str = _id("redactor"),
) -> SyntheticTemporalCompletionRequestV1:
    root = TemporalHistoryRootReceipt(
        root_receipt_id=_id("root"),
        project_id=_id("project"),
        epoch_ordinal=1,
        history_floor_at=FLOOR,
        issued_at=FLOOR,
    )
    grant_id = _id("grant")
    grant_fingerprint = _id("grant-fingerprint")
    selection = ProjectMetricSelectionRevisionV2(
        selection_revision_id=_id(f"selection:{','.join(selected_keys)}"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        project_id=root.project_id,
        selection_ordinal=1,
        selected_metric_keys=selected_keys,
        source=ProjectMetricSelectionSource.AUTOMATION_GRANT,
        effective_at=FLOOR + timedelta(minutes=1),
        recorded_at=FLOOR + timedelta(minutes=1),
        metric_pack_key=pack_key,
        metric_pack_version=pack_version,
        metric_pack_sha256=pack_sha256,
        metric_catalog_version=catalog_version,
        metric_catalog_sha256=catalog_sha256,
        source_authority_kind=ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT,
        source_authority_id=grant_id,
        source_authority_fingerprint=grant_fingerprint,
        source_authority_version=automation_grant_authority_version(GRANT_REVISION),
    )
    scope = RepositoryPreparedTemporalScopeV1(
        prepared_scope_id=_id("scope"),
        history_root=root,
        selection_revision=selection,
        automation_grant_id=grant_id,
        automation_grant_fingerprint=grant_fingerprint,
        automation_grant_revision=GRANT_REVISION,
        prepared_at=FLOOR + timedelta(minutes=2),
    )
    started = scope.prepared_at + timedelta(minutes=1)
    ended = started + timedelta(minutes=1)
    selected_root = _id("selected-manifest")
    source_root = _id("source-manifest")
    analysis_input = AnalysisInputReceiptV2(
        input_receipt_id=_id("input"),
        root_receipt_id=root.root_receipt_id,
        root_receipt_fingerprint=root.fingerprint,
        selection_revision_id=selection.selection_revision_id,
        selection_revision_fingerprint=selection.fingerprint,
        selection_scope_fingerprint=selection.metric_set_fingerprint,
        analysis_run_id=_id("run"),
        analysis_run_fingerprint=_id("run-fingerprint"),
        analysis_run_fingerprint_version="reserved-run-v1",
        analysis_run_request_fingerprint=_id("run-request"),
        project_id=root.project_id,
        session_id=_id("session"),
        selected_metric_keys=selected_keys,
        analysis_window_fingerprint=_id("window"),
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
        analysis_run_completed_at=ended + timedelta(seconds=1),
        captured_at=ended + timedelta(seconds=2),
        capture_contract_version=capture_contract_version,
        analysis_profile_key=profile_key,
        analysis_profile_version=profile_version,
        analysis_profile_sha256=profile_sha256,
        metric_pack_key=pack_key,
        metric_pack_version=pack_version,
        metric_pack_sha256=pack_sha256,
        metric_engine_version=(
            identity_module.COACHING_METRIC_ENGINE_VERSION
            if engine_version is None
            else engine_version
        ),
        metric_engine_sha256=engine_sha256,
        metric_catalog_version=catalog_version,
        metric_catalog_sha256=catalog_sha256,
        consent_policy_version=consent_policy_version,
        consent_receipt_id=_id("consent"),
        consent_receipt_fingerprint=_id("consent-fingerprint"),
        privacy_policy_version=privacy_policy_version,
        provider=Provider.SYNTHETIC,
        provider_version=provider_version,
        provider_adapter_version=provider_adapter_version,
        provider_schema_version=provider_schema_version,
        source_schema_version=source_schema_version,
        content_schema_version=content_schema_version,
        redactor_version=redactor_version,
        redactor_sha256=redactor_sha256,
        preprocessing_version=preprocessing_version,
        preprocessing_sha256=preprocessing_sha256,
        router_version=router_version,
        router_sha256=router_sha256,
        model_plan_fingerprint=model_plan_fingerprint,
        analysis_run_schema_version=1,
        full_run_metric_observation_count=len(selected_keys),
    )
    return SyntheticTemporalCompletionRequestV1(
        completion_request_id=_id("request"),
        prepared_scope=scope,
        analysis_input=analysis_input,
        analysis_run_id=analysis_input.analysis_run_id,
    )


def test_catalog_key_set_exactly_equals_deterministic_coaching_v3_registry() -> None:
    expected = tuple(sorted(definition.key for definition in COACHING_METRIC_DEFINITIONS))
    assert COACHING_METRIC_PACK_VERSION == 3
    assert COACHING_TEMPORAL_METRIC_KEYS == expected
    assert set(COACHING_TEMPORAL_METRIC_KEYS) == {
        definition.key for definition in COACHING_METRIC_DEFINITIONS
    }
    assert len(COACHING_TEMPORAL_METRIC_KEYS) == len(COACHING_METRIC_DEFINITIONS)
    assert CoachingTemporalIdentityCatalog().metric_keys == expected


@pytest.mark.parametrize(
    "selected_keys",
    (
        (COACHING_TEMPORAL_METRIC_KEYS[0],),
        tuple(sorted(COACHING_TEMPORAL_METRIC_KEYS[2:5])),
        COACHING_TEMPORAL_METRIC_KEYS,
    ),
    ids=("single", "subset", "full"),
)
def test_catalog_returns_exact_selected_subset_in_selection_order(
    selected_keys: tuple[str, ...],
) -> None:
    request = _request(selected_keys)
    identities = CoachingTemporalIdentityCatalog().build_for_synthetic_request(request)
    assert tuple(item.metric_key for item in identities) == selected_keys
    assert len(identities) == len(selected_keys)
    assert len({item.metric_key for item in identities}) == len(selected_keys)


def test_catalog_constructs_complete_deterministic_provisional_identities() -> None:
    request = _request(COACHING_TEMPORAL_METRIC_KEYS)
    identities = CoachingTemporalIdentityCatalog().build_for_synthetic_request(request)
    definitions = {item.key: item for item in COACHING_METRIC_DEFINITIONS}
    for identity in identities:
        definition = definitions[identity.metric_key]
        assert len(identity.metric_definition_sha256) == 64
        assert len(identity.metric_question_sha256) == 64
        assert identity.metric_definition_version.endswith(f"v{definition.version}")
        assert identity.metric_question_version.endswith(f"v{definition.version}")
        assert identity.value_kind is TemporalValueKind.FRACTION
        assert identity.unit_code == definition.unit
        expected_direction = {
            TextMetricDirection.HIGHER_IS_BETTER: MetricDirection.HIGHER_IS_BETTER,
            TextMetricDirection.LOWER_IS_BETTER: MetricDirection.LOWER_IS_BETTER,
        }[definition.direction]
        assert identity.direction is expected_direction
        assert (
            identity.aggregation_semantics
            is TemporalAggregationSemantics.RATIO_OF_SUMS
        )
        assert identity.exposure_unit_code is None
        assert identity.trend.method is TemporalTrendMethod.NONE
        assert identity.interval_method_version is None
        assert identity.evidence_tier is EvidenceTier.REDACTED_CONTENT
        assert (
            identity.evidence_contract_version
            == COACHING_EVIDENCE_CAPABILITY_CATALOG_VERSION
        )
        assert identity.estimator_kind is EstimatorIdentityKind.DETERMINISTIC
        assert identity.estimator_lifecycle is EstimatorLifecycleState.PROVISIONAL
        assert identity.activation_receipt_sha256 is None
        assert identity.calibration_version == COACHING_TEMPORAL_CALIBRATION_VERSION
        assert len(identity.calibration_sha256) == 64
        assert identity.preprocessing_version == request.analysis_input.preprocessing_version
        assert identity.preprocessing_sha256 == request.analysis_input.preprocessing_sha256
        assert identity.router_version == request.analysis_input.router_version
        assert identity.router_sha256 == request.analysis_input.router_sha256
        assert identity.redactor_version == request.analysis_input.redactor_version
        assert identity.redactor_sha256 == request.analysis_input.redactor_sha256
        assert identity.privacy_policy_version == request.analysis_input.privacy_policy_version
        assert identity.provider is Provider.SYNTHETIC
        assert identity.provider_adapter_version == (
            request.analysis_input.provider_adapter_version
        )
        for field in (
            "model_provider",
            "requested_model_key",
            "requested_model_revision",
            "served_model_key",
            "served_model_revision",
            "served_model_fallback",
            "model_weight_identity_state",
            "model_weight_set_sha256",
            "tokenizer_key",
            "tokenizer_revision",
            "tokenizer_identity_state",
            "tokenizer_sha256",
            "model_license_code",
            "reasoning_effort",
            "prompt_template_version",
            "prompt_template_sha256",
            "rubric_version",
            "rubric_sha256",
        ):
            assert getattr(identity, field) is None


def test_installation_keyed_run_plan_digests_do_not_redefine_metric_identity() -> None:
    selected = tuple(sorted(COACHING_TEMPORAL_METRIC_KEYS[:3]))
    first_request = _request(
        selected, model_plan_fingerprint=_id("installation-keyed-plan-one")
    )
    second_request = _request(
        selected, model_plan_fingerprint=_id("installation-keyed-plan-two")
    )
    assert first_request.analysis_input.model_plan_fingerprint != (
        second_request.analysis_input.model_plan_fingerprint
    )
    assert first_request.analysis_input.fingerprint != second_request.analysis_input.fingerprint
    assert first_request.fingerprint != second_request.fingerprint
    catalog = CoachingTemporalIdentityCatalog()
    assert catalog.build_for_synthetic_request(first_request) == (
        catalog.build_for_synthetic_request(second_request)
    )


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("provider_version", "reserved-synthetic-provider-v2"),
        ("capture_contract_version", "reserved-synthetic-capture-v2"),
        ("consent_policy_version", "reserved-consent-v2"),
    ),
)
def test_operational_and_authorization_versions_do_not_fragment_identity(
    field: str, changed_value: str
) -> None:
    selected = tuple(sorted(COACHING_TEMPORAL_METRIC_KEYS[:3]))
    baseline = _request(selected)
    changed = _request(selected, **{field: changed_value})  # type: ignore[arg-type]
    assert baseline.analysis_input.fingerprint != changed.analysis_input.fingerprint
    assert baseline.fingerprint != changed.fingerprint
    catalog = CoachingTemporalIdentityCatalog()
    assert catalog.build_for_synthetic_request(baseline) == (
        catalog.build_for_synthetic_request(changed)
    )


@pytest.mark.parametrize(
    ("field", "changed_value"),
    (
        ("provider_adapter_version", "reserved-synthetic-adapter-v2"),
        ("provider_schema_version", "reserved-provider-schema-v2"),
        ("source_schema_version", "reserved-source-schema-v2"),
        ("content_schema_version", "reserved-content-schema-v2"),
        ("privacy_policy_version", "reserved-privacy-v2"),
        ("preprocessing_version", "reserved-preprocessing-v2"),
        ("preprocessing_sha256", _id("preprocessing-v2")),
        ("router_version", "reserved-router-v2"),
        ("router_sha256", _id("router-v2")),
        ("redactor_version", "reserved-redactor-v2"),
        ("redactor_sha256", _id("redactor-v2")),
    ),
)
def test_comparison_semantic_provenance_changes_move_identity_boundary(
    field: str, changed_value: str
) -> None:
    selected = (COACHING_TEMPORAL_METRIC_KEYS[0],)
    baseline = _request(selected)
    changed = _request(selected, **{field: changed_value})  # type: ignore[arg-type]
    catalog = CoachingTemporalIdentityCatalog()
    assert catalog.build_for_synthetic_request(baseline) != (
        catalog.build_for_synthetic_request(changed)
    )


def test_risk_and_nonrisk_metrics_map_unit_and_direction_boundaries() -> None:
    selected = tuple(
        sorted(
            (
                "collaboration.rework_candidate_rate",
                "prompt.task_definition_coverage",
            )
        )
    )
    identities = {
        item.metric_key: item
        for item in CoachingTemporalIdentityCatalog().build_for_synthetic_request(
            _request(selected)
        )
    }
    assert identities["collaboration.rework_candidate_rate"].unit_code == "risk_ratio"
    assert (
        identities["collaboration.rework_candidate_rate"].direction
        is MetricDirection.LOWER_IS_BETTER
    )
    assert identities["prompt.task_definition_coverage"].unit_code == "ratio"
    assert (
        identities["prompt.task_definition_coverage"].direction
        is MetricDirection.HIGHER_IS_BETTER
    )


def test_unknown_metric_is_rejected_without_missing_or_extra_identity() -> None:
    request = _request(("reserved.unknown_metric",))
    with pytest.raises(ValueError, match="subset"):
        CoachingTemporalIdentityCatalog().build_for_synthetic_request(request)


@pytest.mark.parametrize(
    "overrides",
    (
        {"pack_key": "core.redacted-text.prompt-logic"},
        {"pack_version": 2},
        {"pack_sha256": _id("other-pack")},
        {"catalog_version": "reserved-other-catalog-v1"},
        {"catalog_sha256": _id("other-catalog")},
        {"profile_key": "standard_engineering"},
        {"profile_version": 2},
        {"profile_sha256": _id("other-profile")},
        {"engine_version": "reserved-other-engine-v1"},
        {"engine_sha256": _id("other-engine")},
    ),
)
def test_exact_pack_catalog_profile_and_engine_mismatch_rejects(
    overrides: dict[str, object],
) -> None:
    request = _request((COACHING_TEMPORAL_METRIC_KEYS[0],), **overrides)  # type: ignore[arg-type]
    with pytest.raises(ValueError):
        CoachingTemporalIdentityCatalog().build_for_synthetic_request(request)


def test_catalog_accepts_no_caller_identity_or_pack_arguments() -> None:
    catalog = CoachingTemporalIdentityCatalog()
    request = _request((COACHING_TEMPORAL_METRIC_KEYS[0],))
    signature = inspect.signature(catalog.build_for_synthetic_request)
    assert tuple(signature.parameters) == ("request",)
    with pytest.raises(TypeError):
        catalog.build_for_synthetic_request(  # type: ignore[call-arg]
            request, identities=()
        )
    with pytest.raises(TypeError):
        CoachingTemporalIdentityCatalog(metric_pack_key="reserved")  # type: ignore[call-arg]
    assert COACHING_METRIC_PACK_KEY != "core.redacted-text.prompt-logic"


@pytest.mark.parametrize(
    ("constant_name", "changed_value"),
    (
        ("COACHING_METRIC_ALGORITHM_ID", "rules.reserved.changed"),
        ("COACHING_METRIC_ALGORITHM_VERSION", "99"),
        ("COACHING_METRIC_ENGINE_VERSION", "reserved-changed-engine-v99"),
        ("COACHING_METRIC_RUBRIC_VERSION", "reserved-changed-rubric-v99"),
    ),
)
def test_plan_identity_binds_algorithm_engine_and_rubric(
    monkeypatch: pytest.MonkeyPatch,
    constant_name: str,
    changed_value: str,
) -> None:
    definition = COACHING_METRIC_DEFINITIONS[0]
    original = identity_module._make_spec(definition).estimator_plan_sha256
    monkeypatch.setattr(identity_module, constant_name, changed_value)
    changed = identity_module._make_spec(definition).estimator_plan_sha256
    assert changed != original


def test_definition_and_question_changes_move_identity_boundaries() -> None:
    definition = COACHING_METRIC_DEFINITIONS[0]
    original = identity_module._make_spec(definition)
    changed = identity_module._make_spec(
        replace(definition, description="Reserved synthetic changed question.")
    )
    assert changed.metric_definition_sha256 != original.metric_definition_sha256
    assert changed.metric_question_sha256 != original.metric_question_sha256
    assert changed.estimator_plan_sha256 != original.estimator_plan_sha256


@pytest.mark.parametrize(
    "bad_version",
    (
        "file:/reserved/router",
        "https://reserved.example/router",
        "reserved\\router",
        "reserved\x00router",
        "reserved..router",
    ),
)
def test_bound_provenance_rejects_path_uri_and_control_versions(
    bad_version: str,
) -> None:
    with pytest.raises(ValidationError):
        _request((COACHING_TEMPORAL_METRIC_KEYS[0],), router_version=bad_version)


def test_recursive_request_revalidation_blocks_copied_identity_scope_forgery() -> None:
    request = _request((COACHING_TEMPORAL_METRIC_KEYS[0],))
    forged_selection = request.prepared_scope.selection_revision.model_copy(
        update={"metric_pack_sha256": _id("forged-pack")}
    )
    forged_scope = request.prepared_scope.model_copy(
        update={"selection_revision": forged_selection}
    )
    forged_request = request.model_copy(update={"prepared_scope": forged_scope})
    with pytest.raises(ValidationError):
        SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(forged_request)
    with pytest.raises(ValidationError):
        CoachingTemporalIdentityCatalog().build_for_synthetic_request(forged_request)


def test_identity_catalog_outputs_only_content_free_receipts() -> None:
    private_canary = "PRIVATE-CANARY-SHOULD-NOT-APPEAR"
    identities = CoachingTemporalIdentityCatalog().build_for_synthetic_request(
        _request(COACHING_TEMPORAL_METRIC_KEYS)
    )
    for identity in identities:
        payload = identity.model_dump_json().lower()
        assert private_canary.lower() not in payload
        assert "file:" not in payload
        assert "http:" not in payload
        assert "https:" not in payload
        assert "\\" not in payload
