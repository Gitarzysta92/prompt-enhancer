"""Repository-returned authority for synthetic comparison-stratum graphs.

The committed comparison-stratum V1 objects are deliberately untrusted drafts.
They also use a comparison-domain grant fingerprint, while the repository-owned
v21 temporal scope uses a different snapshot-domain fingerprint for the same
stored grant revision.  This additive boundary keeps both identities intact and
joins them with an explicit repository-verified bridge; it never rewrites the
temporal scope or pretends that two domain-separated hashes are equal.

Constructing these models is not repository authority.  Authority exists only
when an exact instance is returned by ``TemporalComparisonStratumRepositoryV2``
after same-transaction hydration and rederivation.  Even then the receipt proves
only graph identity and bounded prospective preparation.  Source truth, product
history, matching, comparison, aggregation, snapshots, recommendations,
activation, export, sharing, legacy inference, and backfill remain disabled.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import re
from typing import Any, Final, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...application.analysis.text_analysis_presets import COACHING_PROFILE_V1
from ...application.jobs import AnalysisJobKind
from ...application.persistence import (
    AnalysisRunStatus,
    SessionAnalysisRunRecord,
    SessionMetricScopeState,
)
from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, StrictModel
from .comparison_strata import (
    MAX_COMPARISON_CURRENT_TASKS,
    MAX_SEALED_AUTHORITY_FINGERPRINTS,
    AutomationRevalidationRequestV1,
    ComparisonAnalysisJobAuthorityV1,
    ComparisonAutomationGrantAuthorityV1,
    ComparisonPolicySetV1,
    ComparisonSessionAuthorityV1,
    ComparisonStratumDimensionsV1,
    ExpectedAnalysisRunVerificationRequestV1,
    _AutomationComparisonLeaseAuthorityV1,
    automation_grant_scope_fingerprint,
    comparison_policy_set_v1,
    session_analysis_run_authority_fingerprint,
)
from .contracts import PersistenceRevalidatedModel
from .persistence import (
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
)


AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION: Final = (
    "automation-grant-identity-bridge-v1"
)
AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION: Final = (
    "automation-grant-identity-bridge-verifier-v1"
)
REPOSITORY_PREPARED_COMPARISON_STRATUM_V1_VERSION: Final = (
    "repository-prepared-comparison-stratum-v1"
)
REPOSITORY_SEALED_COMPARISON_STRATUM_V1_VERSION: Final = (
    "repository-sealed-comparison-stratum-v1"
)
EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION: Final = (
    "comparison-expected-run-id-issuance-verifier-v1"
)
COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION: Final = (
    "comparison-stratum-repository-verifier-v1"
)
STORED_SESSION_ANALYSIS_RUN_BRIDGE_V1_VERSION: Final = (
    "stored-session-analysis-run-bridge-v1"
)

_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_PREPARED_BASE_GRAPH_FINGERPRINTS = 12
_PREPARED_MAX_GRAPH_FINGERPRINTS = (
    _PREPARED_BASE_GRAPH_FINGERPRINTS + MAX_COMPARISON_CURRENT_TASKS
)
_METRIC_COMPARISON_DIGEST_FIELDS: Final = (
    "metric_definition_sha256",
    "metric_question_sha256",
    "estimator_plan_sha256",
    "activation_receipt_sha256",
    "model_weight_set_sha256",
    "tokenizer_sha256",
    "preprocessing_sha256",
    "prompt_template_sha256",
    "rubric_sha256",
    "calibration_sha256",
    "router_sha256",
    "redactor_sha256",
)


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_version(value: str) -> str:
    if (
        _SAFE_VERSION_PATTERN.fullmatch(value) is None
        or ".." in value
        or any(character in value for character in ("/", "\\", ":"))
    ):
        raise ValueError("version must be a path-free, URI-free content code")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("repository timestamps must be canonical UTC")
    return value


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _domain_sha256(domain: str, payload: Any) -> str:
    return _canonical_sha256({"domain": domain, "payload": payload})


def _model_sha256(value: StrictModel) -> str:
    return _canonical_sha256(value.model_dump(mode="json"))


def _verifier_fingerprint(*, purpose: str, version: str) -> str:
    return _domain_sha256(
        "comparison.code-owned-verifier-identity.v1",
        {"purpose": purpose, "version": version},
    )


AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT: Final = (
    _verifier_fingerprint(
        purpose="automation_grant_identity_bridge",
        version=AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION,
    )
)
EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT: Final = _verifier_fingerprint(
    purpose="expected_analysis_run_id_issuance",
    version=EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION,
)
COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT: Final = (
    _verifier_fingerprint(
        purpose="comparison_stratum_repository_graph",
        version=COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION,
    )
)


def _ordered_digests(
    values: tuple[str, ...],
    *,
    expected_length: int | None = None,
) -> tuple[str, ...]:
    checked = tuple(_digest(value) for value in values)
    if expected_length is not None and len(checked) != expected_length:
        raise ValueError("ordered authority graph has the wrong cardinality")
    if len(set(checked)) != len(checked):
        raise ValueError("ordered authority graph must be role-separated")
    return checked


def _require_distinct_roles(
    *,
    allowed_alias_groups: tuple[frozenset[str], ...] = (),
    **roles: str | None,
) -> None:
    inverse: dict[str, list[str]] = {}
    for name, value in roles.items():
        if value is None:
            continue
        inverse.setdefault(_digest(value), []).append(name)
    for names in inverse.values():
        if len(names) <= 1:
            continue
        colliding = frozenset(names)
        if any(colliding.issubset(group) for group in allowed_alias_groups):
            continue
        raise ValueError(
            "comparison identities and fingerprints must be role-separated"
        )


def stored_session_analysis_run_bridge_fingerprint_v1(
    *,
    request_fingerprint: str,
    input_fingerprint: str,
    analysis_profile_key: str,
    analysis_profile_version: int,
    metric_pack_key: str,
    metric_pack_version: int,
    selected_metric_keys: tuple[str, ...],
    provider: str,
    provider_version: str,
    adapter_version: str,
    source_schema_version: str,
    content_schema_version: str,
    metric_engine_version: str,
    redactor_version: str,
    model_plan_fingerprint: str,
    schema_version: int,
    analysis_window_fingerprint: str,
) -> str:
    """Reproduce the exact v21 stored-run-to-temporal-input bridge.

    ``input_fingerprint`` is one input to this domain-separated digest; it is
    intentionally not equal to the resulting temporal run fingerprint.
    """

    return _canonical_sha256(
        {
            "analysis_profile_key": analysis_profile_key,
            "analysis_profile_version": analysis_profile_version,
            "analysis_window_fingerprint": analysis_window_fingerprint,
            "bridge_version": STORED_SESSION_ANALYSIS_RUN_BRIDGE_V1_VERSION,
            "content_schema_version": content_schema_version,
            "input_fingerprint": input_fingerprint,
            "metric_engine_version": metric_engine_version,
            "metric_pack_key": metric_pack_key,
            "metric_pack_version": metric_pack_version,
            "model_plan_fingerprint": model_plan_fingerprint,
            "provider": provider,
            "provider_adapter_version": adapter_version,
            "provider_version": provider_version,
            "redactor_version": redactor_version,
            "request_fingerprint": request_fingerprint,
            "schema_version": schema_version,
            "selected_metric_keys": selected_metric_keys,
            "source_schema_version": source_schema_version,
        }
    )


def temporal_automation_grant_snapshot_fingerprint_v1(
    grant: ComparisonAutomationGrantAuthorityV1,
) -> str:
    """Reproduce the full v21 stored-grant snapshot fingerprint."""

    checked = ComparisonAutomationGrantAuthorityV1.revalidate_for_persistence(
        grant
    )
    scope = checked.scope
    resource = scope.resource_policy
    return _canonical_sha256(
        {
            "check_interval_seconds": scope.check_interval_seconds,
            "contract_version": "automation-grant-v1",
            "created_at": checked.created_at.isoformat(timespec="microseconds"),
            "expires_at": checked.expires_at.isoformat(timespec="microseconds"),
            "grant_id": checked.grant_id,
            "local_only": scope.local_only,
            "maximum_session_seconds": resource.maximum_session_seconds,
            "max_cpu_workers": resource.max_cpu_workers,
            "max_gpu_workers": resource.max_gpu_workers,
            "metric_keys": scope.metric_keys,
            "newest_session_limit": scope.newest_session_limit,
            "pause_on_battery": resource.pause_on_battery,
            "project_id": scope.project_id,
            "provider": scope.provider.value,
            "remote_requires_fresh_approval": (
                scope.remote_requires_fresh_approval
            ),
            "renewed_at": checked.renewed_at.isoformat(timespec="microseconds"),
            "revision": checked.revision,
            "route": resource.route.value,
            "snapshot_state": "active",
        }
    )


class AutomationGrantIdentityBridgeV1(PersistenceRevalidatedModel):
    """Repository-verifiable join between two intentional hash domains."""

    contract_version: Literal[AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION] = (
        AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION
    )
    grant_id: str
    revision: int = Field(strict=True, ge=1, le=9_007_199_254_740_991)
    temporal_snapshot_fingerprint: str
    comparison_authority_fingerprint: str
    bridge_verifier_version: Literal[
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION
    ] = AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION
    bridge_verifier_fingerprint: Literal[
        AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT
    ] = AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT
    bridge_fingerprint: str
    repository_rehydration_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True

    _ids = field_validator(
        "grant_id",
        "temporal_snapshot_fingerprint",
        "comparison_authority_fingerprint",
        "bridge_verifier_fingerprint",
        "bridge_fingerprint",
    )(_digest)
    _version = field_validator("bridge_verifier_version")(_safe_version)

    @staticmethod
    def fingerprint_for(
        *,
        grant_id: str,
        revision: int,
        temporal_snapshot_fingerprint: str,
        comparison_authority_fingerprint: str,
    ) -> str:
        return _domain_sha256(
            "comparison.automation-grant-identity-bridge.v1",
            {
                "bridge_verifier_fingerprint": (
                    AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT
                ),
                "bridge_verifier_version": (
                    AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION
                ),
                "comparison_authority_fingerprint": (
                    comparison_authority_fingerprint
                ),
                "grant_id": grant_id,
                "revision": revision,
                "temporal_snapshot_fingerprint": temporal_snapshot_fingerprint,
            },
        )

    @model_validator(mode="after")
    def exact_bridge(self) -> AutomationGrantIdentityBridgeV1:
        expected = self.fingerprint_for(
            grant_id=self.grant_id,
            revision=self.revision,
            temporal_snapshot_fingerprint=self.temporal_snapshot_fingerprint,
            comparison_authority_fingerprint=(
                self.comparison_authority_fingerprint
            ),
        )
        if self.bridge_fingerprint != expected:
            raise ValueError("grant identity bridge fingerprint is not exact")
        _require_distinct_roles(
            grant_id=self.grant_id,
            temporal_snapshot=self.temporal_snapshot_fingerprint,
            comparison_authority=self.comparison_authority_fingerprint,
            bridge_verifier=self.bridge_verifier_fingerprint,
            bridge=self.bridge_fingerprint,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return self.bridge_fingerprint


def _prepared_payload(
    *,
    prepared_scope: RepositoryPreparedTemporalScopeV1,
    analysis_job: ComparisonAnalysisJobAuthorityV1,
    expected_run_request: ExpectedAnalysisRunVerificationRequestV1,
    session_authority: ComparisonSessionAuthorityV1,
    automation_grant: ComparisonAutomationGrantAuthorityV1,
    automation_grant_scope_sha256: str,
    grant_identity_bridge: AutomationGrantIdentityBridgeV1,
    dimensions: ComparisonStratumDimensionsV1,
    policies: ComparisonPolicySetV1,
    prepared_at: datetime,
) -> dict[str, Any]:
    return {
        "analysis_job": analysis_job.model_dump(mode="json"),
        "automation_grant": automation_grant.model_dump(mode="json"),
        "automation_grant_scope_sha256": automation_grant_scope_sha256,
        "contract_version": REPOSITORY_PREPARED_COMPARISON_STRATUM_V1_VERSION,
        "dimensions": dimensions.model_dump(mode="json"),
        "expected_run_request": expected_run_request.model_dump(mode="json"),
        "expected_run_verifier_fingerprint": (
            EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT
        ),
        "grant_identity_bridge": grant_identity_bridge.model_dump(mode="json"),
        "policies": policies.model_dump(mode="json"),
        "prepared_at": prepared_at.isoformat(),
        "prepared_scope": prepared_scope.model_dump(mode="json"),
        "repository_verifier_fingerprint": (
            COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
        ),
        "session_authority": session_authority.model_dump(mode="json"),
    }


def _prepared_ordered_graph(
    *,
    prepared_scope: RepositoryPreparedTemporalScopeV1,
    analysis_job: ComparisonAnalysisJobAuthorityV1,
    expected_run_request: ExpectedAnalysisRunVerificationRequestV1,
    session_authority: ComparisonSessionAuthorityV1,
    automation_grant: ComparisonAutomationGrantAuthorityV1,
    grant_identity_bridge: AutomationGrantIdentityBridgeV1,
    dimensions: ComparisonStratumDimensionsV1,
    policies: ComparisonPolicySetV1,
) -> tuple[str, ...]:
    manifest = dimensions.task_manifest
    return (
        prepared_scope.fingerprint,
        analysis_job.fingerprint,
        session_authority.fingerprint,
        automation_grant.fingerprint,
        grant_identity_bridge.fingerprint,
        manifest.selection_request.fingerprint,
        *(item.fingerprint for item in manifest.current_revisions),
        manifest.fingerprint,
        dimensions.fingerprint,
        policies.fingerprint,
        expected_run_request.fingerprint,
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT,
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT,
    )


def _prepared_distinct_roles(
    prepared: RepositoryPreparedComparisonStratumV1,
) -> dict[str, str | None]:
    """Collect every semantically distinct prepared-graph digest role."""

    scope = prepared.prepared_scope
    root = scope.history_root
    selection = scope.selection_revision
    job = prepared.analysis_job
    identity = job.identity
    session = prepared.session_authority
    grant = prepared.automation_grant
    bridge = prepared.grant_identity_bridge
    manifest = prepared.dimensions.task_manifest
    task_selection = manifest.selection_request
    expected_run = prepared.expected_run_request
    roles: dict[str, str | None] = {
        "prepared_stratum_id": prepared.prepared_stratum_id,
        "prepared_receipt_fingerprint": prepared.fingerprint,
        "prepared_scope_id": scope.prepared_scope_id,
        "prepared_scope_fingerprint": scope.fingerprint,
        "history_root_id": root.root_receipt_id,
        "history_root_fingerprint": root.fingerprint,
        "history_root_predecessor_id": root.predecessor_root_id,
        "history_root_predecessor_fingerprint": root.predecessor_root_fingerprint,
        "project_id": root.project_id,
        "selection_revision_id": selection.selection_revision_id,
        "selection_revision_fingerprint": selection.fingerprint,
        "selection_scope_fingerprint": selection.metric_set_fingerprint,
        "selection_predecessor_id": selection.compare_and_swap_predecessor_id,
        "selection_predecessor_fingerprint": (
            selection.compare_and_swap_predecessor_fingerprint
        ),
        "metric_pack_fingerprint": selection.metric_pack_sha256,
        "metric_catalog_fingerprint": selection.metric_catalog_sha256,
        "automation_grant_id": scope.automation_grant_id,
        "temporal_grant_snapshot_fingerprint": (
            scope.automation_grant_fingerprint
        ),
        "comparison_grant_authority_fingerprint": grant.fingerprint,
        "comparison_grant_scope_fingerprint": (
            prepared.automation_grant_scope_sha256
        ),
        "grant_bridge_verifier": bridge.bridge_verifier_fingerprint,
        "grant_bridge_fingerprint": bridge.fingerprint,
        "analysis_job_id": job.job_id,
        "analysis_job_dedupe_key": job.dedupe_key,
        "analysis_job_authority_fingerprint": job.fingerprint,
        "analysis_job_stored_authority_fingerprint": job.stored_job_fingerprint,
        "analysis_job_lease_authority_fingerprint": (
            job.lease_authority_fingerprint
        ),
        "analysis_job_input_fingerprint": identity.input_fingerprint,
        "analysis_job_provenance_fingerprint": identity.provenance_fingerprint,
        "installation_id": session.installation_id,
        "session_id": session.session_id,
        "session_authority_fingerprint": session.fingerprint,
        "task_selection_request_id": task_selection.selection_request_id,
        "task_selection_request_fingerprint": task_selection.fingerprint,
        "task_selection_query_evidence_fingerprint": (
            task_selection.claimed_query_evidence_fingerprint
        ),
        "task_manifest_fingerprint": manifest.fingerprint,
        "dimensions_fingerprint": prepared.dimensions.fingerprint,
        "task_type_policy": prepared.policies.task_type.sha256,
        "automation_run_binding_policy": (
            prepared.policies.automation_run_binding.sha256
        ),
        "matching_policy": prepared.policies.matching.sha256,
        "censoring_policy": prepared.policies.censoring.sha256,
        "task_mix_policy": prepared.policies.task_mix.sha256,
        "policy_set_fingerprint": prepared.policies.fingerprint,
        "expected_run_receipt_id": expected_run.authority_receipt_id,
        "expected_run_request_fingerprint": expected_run.fingerprint,
        "expected_run_derivation_fingerprint": (
            expected_run.derivation_inputs_sha256
        ),
        "expected_analysis_run_id": expected_run.expected_analysis_run_id,
        "expected_run_verifier_fingerprint": (
            prepared.expected_run_verifier_fingerprint
        ),
        "repository_verifier_fingerprint": prepared.repository_verifier_fingerprint,
    }
    for index, item in enumerate(manifest.current_revisions):
        roles[f"task_{index}_id"] = item.task_id
        roles[f"task_{index}_fingerprint"] = item.fingerprint
    return roles


class RepositoryPreparedComparisonStratumV1(PersistenceRevalidatedModel):
    """Repository-returned prospective preparation over direct components."""

    contract_version: Literal[
        REPOSITORY_PREPARED_COMPARISON_STRATUM_V1_VERSION
    ] = REPOSITORY_PREPARED_COMPARISON_STRATUM_V1_VERSION
    prepared_stratum_id: str
    prepared_scope: RepositoryPreparedTemporalScopeV1
    analysis_job: ComparisonAnalysisJobAuthorityV1
    expected_run_request: ExpectedAnalysisRunVerificationRequestV1
    session_authority: ComparisonSessionAuthorityV1
    automation_grant: ComparisonAutomationGrantAuthorityV1
    automation_grant_scope_sha256: str
    grant_identity_bridge: AutomationGrantIdentityBridgeV1
    dimensions: ComparisonStratumDimensionsV1
    policies: ComparisonPolicySetV1
    expected_run_verifier_version: Literal[
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION
    ] = EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION
    expected_run_verifier_fingerprint: Literal[
        EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT
    ] = EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT
    repository_verifier_version: Literal[
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION
    ] = COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION
    repository_verifier_fingerprint: Literal[
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
    ] = COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
    ordered_graph_fingerprints: tuple[str, ...] = Field(
        min_length=_PREPARED_BASE_GRAPH_FINGERPRINTS,
        max_length=_PREPARED_MAX_GRAPH_FINGERPRINTS,
    )
    prepared_at: datetime

    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[True] = True
    repository_graph_verified: Literal[True] = True
    task_selection_authority_verified: Literal[True] = True
    bounded_task_completeness_verified: Literal[True] = True
    expected_run_id_issuance_verified: Literal[True] = True
    sealed: Literal[True] = True
    run_authority_verified: Literal[False] = False
    batch_authority_verified: Literal[False] = False
    comparison_stratum_complete: Literal[False] = False

    source_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    pair_matching_allowed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    aggregate_materialization_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_allowed: Literal[False] = False
    recommendation_outcome_evaluation_allowed: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_inference_allowed: Literal[False] = False
    backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "prepared_stratum_id",
        "automation_grant_scope_sha256",
        "expected_run_verifier_fingerprint",
        "repository_verifier_fingerprint",
    )(_digest)
    _versions = field_validator(
        "expected_run_verifier_version", "repository_verifier_version"
    )(_safe_version)
    _prepared = field_validator("prepared_at")(_utc)

    @field_validator("ordered_graph_fingerprints")
    @classmethod
    def valid_ordered_graph(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _ordered_digests(values)

    @classmethod
    def prepared_stratum_id_for(
        cls,
        *,
        prepared_scope: RepositoryPreparedTemporalScopeV1,
        analysis_job: ComparisonAnalysisJobAuthorityV1,
        expected_run_request: ExpectedAnalysisRunVerificationRequestV1,
        session_authority: ComparisonSessionAuthorityV1,
        automation_grant: ComparisonAutomationGrantAuthorityV1,
        automation_grant_scope_sha256: str,
        grant_identity_bridge: AutomationGrantIdentityBridgeV1,
        dimensions: ComparisonStratumDimensionsV1,
        policies: ComparisonPolicySetV1,
        prepared_at: datetime,
    ) -> str:
        return _domain_sha256(
            "comparison.repository-prepared-stratum-id.v2",
            _prepared_payload(
                prepared_scope=prepared_scope,
                analysis_job=analysis_job,
                expected_run_request=expected_run_request,
                session_authority=session_authority,
                automation_grant=automation_grant,
                automation_grant_scope_sha256=automation_grant_scope_sha256,
                grant_identity_bridge=grant_identity_bridge,
                dimensions=dimensions,
                policies=policies,
                prepared_at=prepared_at,
            ),
        )

    @classmethod
    def ordered_graph_for(
        cls,
        *,
        prepared_scope: RepositoryPreparedTemporalScopeV1,
        analysis_job: ComparisonAnalysisJobAuthorityV1,
        expected_run_request: ExpectedAnalysisRunVerificationRequestV1,
        session_authority: ComparisonSessionAuthorityV1,
        automation_grant: ComparisonAutomationGrantAuthorityV1,
        grant_identity_bridge: AutomationGrantIdentityBridgeV1,
        dimensions: ComparisonStratumDimensionsV1,
        policies: ComparisonPolicySetV1,
    ) -> tuple[str, ...]:
        return _prepared_ordered_graph(
            prepared_scope=prepared_scope,
            analysis_job=analysis_job,
            expected_run_request=expected_run_request,
            session_authority=session_authority,
            automation_grant=automation_grant,
            grant_identity_bridge=grant_identity_bridge,
            dimensions=dimensions,
            policies=policies,
        )

    @model_validator(mode="after")
    def exact_repository_preparation(
        self,
    ) -> RepositoryPreparedComparisonStratumV1:
        scope = self.prepared_scope
        root = scope.history_root
        selection = scope.selection_revision
        job = self.analysis_job
        identity = job.identity
        session = self.session_authority
        grant = self.automation_grant
        bridge = self.grant_identity_bridge
        expected_run = self.expected_run_request
        if self.policies != comparison_policy_set_v1():
            raise ValueError("prepared stratum requires exact code-owned policies")
        if (
            identity.kind is not AnalysisJobKind.SESSION_QUALITY
            or identity.automation_grant_id is None
            or not identity.local_only
        ):
            raise ValueError("prepared stratum requires a local session-quality job")
        if (
            expected_run.analysis_job_id != job.job_id
            or expected_run.analysis_job_authority_fingerprint != job.fingerprint
            or expected_run.provider is not identity.provider
            or expected_run.session_id != identity.session_id
            or expected_run.issued_at != self.prepared_at
            or expected_run.metric_pack_key != selection.metric_pack_key
            or expected_run.metric_pack_version != selection.metric_pack_version
        ):
            raise ValueError("prepared receipt requires the exact run request")
        if any(
            provider is not Provider.SYNTHETIC
            for provider in (identity.provider, session.provider, grant.scope.provider)
        ):
            raise ValueError("comparison-stratum V1 is synthetic-test-only")
        if (
            scope.automation_grant_id != grant.grant_id
            or scope.automation_grant_revision != grant.revision
            or identity.automation_grant_id != grant.grant_id
            or bridge.grant_id != grant.grant_id
            or bridge.revision != grant.revision
            or bridge.temporal_snapshot_fingerprint
            != scope.automation_grant_fingerprint
            or bridge.comparison_authority_fingerprint != grant.fingerprint
        ):
            raise ValueError("grant identity bridge does not bind the same revision")
        expected_temporal_snapshot = (
            temporal_automation_grant_snapshot_fingerprint_v1(grant)
        )
        if (
            scope.automation_grant_fingerprint != expected_temporal_snapshot
            or bridge.temporal_snapshot_fingerprint != expected_temporal_snapshot
        ):
            raise ValueError(
                "grant identity bridge must bind the exact full temporal snapshot"
            )
        if self.automation_grant_scope_sha256 != automation_grant_scope_fingerprint(
            grant.scope
        ):
            raise ValueError("automation grant scope fingerprint is not exact")
        if (
            root.project_id != identity.project_id
            or root.project_id != session.project_id
            or root.project_id != grant.scope.project_id
            or selection.selected_metric_keys != identity.metric_keys
            or selection.selected_metric_keys != grant.scope.metric_keys
            or identity.session_id != session.session_id
            or identity.provider is not session.provider
            or identity.provider is not grant.scope.provider
        ):
            raise ValueError("task, session, job, grant and selection must agree")
        if (
            identity.provider_schema_version != session.source_schema_version
            or self.dimensions.installation_id != session.installation_id
            or self.dimensions.project_id != session.project_id
            or self.dimensions.provider is not session.provider
            or self.dimensions.task_manifest.session_id != session.session_id
            or self.dimensions.task_manifest.cutoff_at != self.prepared_at
        ):
            raise ValueError("prepared dimensions must derive from the exact session")
        if (
            self.prepared_at < scope.prepared_at
            or self.prepared_at < job.created_at
            or job.lease_verified_at != self.prepared_at
            or grant.observed_active_at != self.prepared_at
        ):
            raise ValueError("comparison stratum must be prepared prospectively")
        if (
            session.terminal_state.value != "completed"
            or not session.events_complete
            or session.ended_at is None
            or session.ended_at > self.prepared_at
        ):
            raise ValueError(
                "comparison preparation requires a completed session before preparation"
            )
        expected_id = self.prepared_stratum_id_for(
            prepared_scope=scope,
            analysis_job=job,
            expected_run_request=expected_run,
            session_authority=session,
            automation_grant=grant,
            automation_grant_scope_sha256=self.automation_grant_scope_sha256,
            grant_identity_bridge=bridge,
            dimensions=self.dimensions,
            policies=self.policies,
            prepared_at=self.prepared_at,
        )
        if self.prepared_stratum_id != expected_id:
            raise ValueError("prepared stratum ID is not the exact repository derivation")
        expected_graph = self.ordered_graph_for(
            prepared_scope=scope,
            analysis_job=job,
            expected_run_request=expected_run,
            session_authority=session,
            automation_grant=grant,
            grant_identity_bridge=bridge,
            dimensions=self.dimensions,
            policies=self.policies,
        )
        if self.ordered_graph_fingerprints != expected_graph:
            raise ValueError("prepared receipt must commit the exact ordered graph")
        _ordered_digests(expected_graph)
        _require_distinct_roles(**_prepared_distinct_roles(self))
        return self

    @property
    def expected_analysis_run_id(self) -> str:
        return self.expected_run_request.expected_analysis_run_id

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)


def _metric_digest_roles(
    batch: RepositorySealedTemporalBatchV1,
) -> dict[str, str | None]:
    observations = batch.seal_draft.observation_batch.observations
    return {
        f"comparison_identity_{index}_{field_name}": getattr(
            observation.comparison_identity, field_name
        )
        for index, observation in enumerate(observations)
        for field_name in _METRIC_COMPARISON_DIGEST_FIELDS
    }


def _sealed_alias_groups(
    batch: RepositorySealedTemporalBatchV1,
) -> tuple[frozenset[str], ...]:
    count = len(batch.seal_draft.observation_batch.observations)
    return tuple(
        frozenset(
            (
                f"input_{field.removesuffix('_sha256')}",
                *(f"comparison_identity_{index}_{field}" for index in range(count)),
            )
        )
        for field in ("preprocessing_sha256", "router_sha256", "redactor_sha256")
    )


def _sealed_distinct_roles(
    *,
    sealed_stratum_id: str,
    prepared: RepositoryPreparedComparisonStratumV1,
    run: SessionAnalysisRunRecord,
    run_authority_fingerprint: str,
    batch: RepositorySealedTemporalBatchV1,
    revalidation: AutomationRevalidationRequestV1,
) -> dict[str, str | None]:
    """Union prepared roles with every new semantically distinct seal role."""

    roles = _prepared_distinct_roles(prepared)
    draft = run.draft
    request = batch.completion_request
    input_receipt = request.analysis_input
    seal_draft = batch.seal_draft
    revision = seal_draft.session_revision
    observation_batch = seal_draft.observation_batch
    roles.update(
        {
            "sealed_stratum_id": sealed_stratum_id,
            "analysis_run_authority_fingerprint": run_authority_fingerprint,
            "analysis_run_input_fingerprint": draft.input_fingerprint,
            "analysis_run_request_fingerprint": draft.request_fingerprint,
            "completion_request_id": request.completion_request_id,
            "completion_request_fingerprint": request.fingerprint,
            "analysis_input_receipt_id": input_receipt.input_receipt_id,
            "analysis_input_receipt_fingerprint": input_receipt.fingerprint,
            "analysis_input_provenance_fingerprint": (
                input_receipt.provenance_fingerprint
            ),
            "stored_run_bridge_fingerprint": (
                input_receipt.analysis_run_fingerprint
            ),
            "analysis_window_fingerprint": (
                input_receipt.analysis_window_fingerprint
            ),
            "selected_manifest_root": input_receipt.selected_window_manifest_root,
            "selected_manifest_identity": (
                input_receipt.selected_window_manifest_identity_fingerprint
            ),
            "observed_manifest_root": (
                input_receipt.post_floor_observed_allowlisted_source_manifest_root
            ),
            "observed_manifest_identity": (
                input_receipt.post_floor_observed_allowlisted_source_manifest_identity_fingerprint
            ),
            "analysis_profile_fingerprint": input_receipt.analysis_profile_sha256,
            "metric_engine_fingerprint": input_receipt.metric_engine_sha256,
            "consent_receipt_id": input_receipt.consent_receipt_id,
            "consent_receipt_fingerprint": (
                input_receipt.consent_receipt_fingerprint
            ),
            "input_redactor": input_receipt.redactor_sha256,
            "input_preprocessing": input_receipt.preprocessing_sha256,
            "input_router": input_receipt.router_sha256,
            "model_plan_fingerprint": input_receipt.model_plan_fingerprint,
            "session_revision_id": revision.revision_id,
            "session_revision_fingerprint": revision.fingerprint,
            "session_revision_predecessor_id": revision.predecessor_revision_id,
            "session_revision_predecessor_fingerprint": (
                revision.predecessor_revision_fingerprint
            ),
            "session_revision_predecessor_link_fingerprint": (
                revision.predecessor_link_fingerprint
            ),
            "observation_batch_id": observation_batch.batch_id,
            "observation_batch_fingerprint": observation_batch.fingerprint,
            "temporal_seal_draft_id": seal_draft.seal_draft_id,
            "temporal_seal_draft_fingerprint": seal_draft.fingerprint,
            "temporal_repository_verifier_fingerprint": (
                batch.repository_verifier_fingerprint
            ),
            "sealed_batch_id": batch.sealed_batch_id,
            "sealed_batch_fingerprint": batch.fingerprint,
            "automation_revalidation_request_id": (
                revalidation.authority_receipt_id
            ),
            "automation_revalidation_request_fingerprint": (
                revalidation.fingerprint
            ),
            "repository_revalidation_authority_fingerprint": (
                revalidation.repository_revalidation_authority_fingerprint
            ),
            **_metric_digest_roles(batch),
        }
    )
    for index, observation in enumerate(observation_batch.observations):
        roles[f"observation_{index}_id"] = observation.observation_id
        roles[f"observation_{index}_fingerprint"] = observation.fingerprint
        roles[f"comparison_identity_{index}_fingerprint"] = (
            observation.comparison_identity.fingerprint
        )
    return roles


class RepositorySealedComparisonStratumV1(PersistenceRevalidatedModel):
    """Repository-returned seal of an exact prepared/run/batch graph."""

    contract_version: Literal[
        REPOSITORY_SEALED_COMPARISON_STRATUM_V1_VERSION
    ] = REPOSITORY_SEALED_COMPARISON_STRATUM_V1_VERSION
    sealed_stratum_id: str
    prepared_receipt: RepositoryPreparedComparisonStratumV1
    analysis_run: SessionAnalysisRunRecord
    analysis_run_authority_sha256: str
    sealed_batch: RepositorySealedTemporalBatchV1
    sealed_batch_sha256: str
    automation_revalidation_request: AutomationRevalidationRequestV1
    ordered_authority_fingerprints: tuple[str, ...] = Field(
        min_length=MAX_SEALED_AUTHORITY_FINGERPRINTS,
        max_length=MAX_SEALED_AUTHORITY_FINGERPRINTS,
    )
    repository_verifier_version: Literal[
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION
    ] = COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION
    repository_verifier_fingerprint: Literal[
        COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
    ] = COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
    sealed_at: datetime

    repository_return_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[True] = True
    repository_graph_verified: Literal[True] = True
    run_graph_verified: Literal[True] = True
    batch_graph_verified: Literal[True] = True
    sealed: Literal[True] = True
    comparison_stratum_complete: Literal[False] = False

    source_authority_verified: Literal[False] = False
    product_capture_allowed: Literal[False] = False
    product_history_eligible: Literal[False] = False
    pair_matching_allowed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    aggregate_materialization_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    recommendation_allowed: Literal[False] = False
    recommendation_outcome_evaluation_allowed: Literal[False] = False
    causal_claim_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_inference_allowed: Literal[False] = False
    backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "sealed_stratum_id",
        "analysis_run_authority_sha256",
        "sealed_batch_sha256",
        "repository_verifier_fingerprint",
    )(_digest)
    _version = field_validator("repository_verifier_version")(_safe_version)
    _sealed = field_validator("sealed_at")(_utc)

    @field_validator("ordered_authority_fingerprints")
    @classmethod
    def valid_ordered_authority(
        cls, values: tuple[str, ...]
    ) -> tuple[str, ...]:
        return _ordered_digests(
            values, expected_length=MAX_SEALED_AUTHORITY_FINGERPRINTS
        )

    @classmethod
    def ordered_authority_for(
        cls,
        *,
        prepared_receipt: RepositoryPreparedComparisonStratumV1,
        analysis_run: SessionAnalysisRunRecord,
        sealed_batch: RepositorySealedTemporalBatchV1,
        automation_revalidation_request: AutomationRevalidationRequestV1,
    ) -> tuple[str, ...]:
        prepared = RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            prepared_receipt
        )
        run = SessionAnalysisRunRecord.model_validate(
            analysis_run.model_dump(mode="python")
        )
        batch = RepositorySealedTemporalBatchV1.revalidate_for_persistence(
            sealed_batch
        )
        revalidation = AutomationRevalidationRequestV1.revalidate_for_persistence(
            automation_revalidation_request
        )
        return (
            prepared.prepared_scope.fingerprint,
            prepared.analysis_job.fingerprint,
            prepared.session_authority.fingerprint,
            prepared.automation_grant.fingerprint,
            prepared.dimensions.task_manifest.selection_request.fingerprint,
            prepared.dimensions.task_manifest.fingerprint,
            prepared.policies.fingerprint,
            prepared.expected_run_request.fingerprint,
            prepared.fingerprint,
            session_analysis_run_authority_fingerprint(run),
            batch.fingerprint,
            revalidation.fingerprint,
        )

    @classmethod
    def sealed_stratum_id_for(
        cls,
        *,
        prepared_receipt: RepositoryPreparedComparisonStratumV1,
        analysis_run: SessionAnalysisRunRecord,
        sealed_batch: RepositorySealedTemporalBatchV1,
        automation_revalidation_request: AutomationRevalidationRequestV1,
        sealed_at: datetime,
    ) -> str:
        return _domain_sha256(
            "comparison.repository-sealed-stratum-id.v2",
            {
                "analysis_run": analysis_run.model_dump(mode="json"),
                "analysis_run_authority_sha256": (
                    session_analysis_run_authority_fingerprint(analysis_run)
                ),
                "automation_revalidation_request": (
                    automation_revalidation_request.model_dump(mode="json")
                ),
                "contract_version": (
                    REPOSITORY_SEALED_COMPARISON_STRATUM_V1_VERSION
                ),
                "ordered_authority_fingerprints": cls.ordered_authority_for(
                    prepared_receipt=prepared_receipt,
                    analysis_run=analysis_run,
                    sealed_batch=sealed_batch,
                    automation_revalidation_request=(
                        automation_revalidation_request
                    ),
                ),
                "prepared_receipt": prepared_receipt.model_dump(mode="json"),
                "repository_verifier_fingerprint": (
                    COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT
                ),
                "sealed_at": sealed_at.isoformat(),
                "sealed_batch": sealed_batch.model_dump(mode="json"),
                "sealed_batch_sha256": sealed_batch.fingerprint,
            },
        )

    @model_validator(mode="after")
    def exact_repository_seal(self) -> RepositorySealedComparisonStratumV1:
        prepared = RepositoryPreparedComparisonStratumV1.revalidate_for_persistence(
            self.prepared_receipt
        )
        run = SessionAnalysisRunRecord.model_validate(
            self.analysis_run.model_dump(mode="python")
        )
        batch = RepositorySealedTemporalBatchV1.revalidate_for_persistence(
            self.sealed_batch
        )
        revalidation = AutomationRevalidationRequestV1.revalidate_for_persistence(
            self.automation_revalidation_request
        )
        draft = run.draft
        input_receipt = batch.completion_request.analysis_input
        job = prepared.analysis_job.identity
        session = prepared.session_authority
        selection = prepared.prepared_scope.selection_revision
        if self.analysis_run_authority_sha256 != session_analysis_run_authority_fingerprint(
            run
        ):
            raise ValueError("sealed receipt must bind the exact stored run")
        if self.sealed_batch_sha256 != batch.fingerprint:
            raise ValueError("sealed receipt must bind the exact temporal batch")
        if run.status is not AnalysisRunStatus.COMPLETED or run.finished_at is None:
            raise ValueError("sealed receipt requires a completed analysis run")
        if (
            draft.run_id != prepared.expected_analysis_run_id
            or draft.run_id != input_receipt.analysis_run_id
            or draft.run_id != batch.seal_draft.analysis_run_id
        ):
            raise ValueError("sealed receipt rejects retrospective run attachment")
        if (
            batch.completion_request.prepared_scope != prepared.prepared_scope
            or batch.prepared_scope_fingerprint != prepared.prepared_scope.fingerprint
        ):
            raise ValueError("sealed batch must descend from the prepared scope")
        if (
            draft.provider is not Provider.SYNTHETIC
            or input_receipt.provider is not Provider.SYNTHETIC
            or draft.provider is not job.provider
            or draft.provider is not session.provider
            or draft.session_id != job.session_id
            or draft.session_id != session.session_id
            or input_receipt.session_id != session.session_id
            or input_receipt.project_id != session.project_id
        ):
            raise ValueError("sealed run must bind the exact synthetic session")
        if (
            draft.analysis_profile_key != COACHING_PROFILE_V1.analysis_profile_key
            or draft.analysis_profile_version
            != COACHING_PROFILE_V1.analysis_profile_version
            or draft.metric_pack_key != COACHING_PROFILE_V1.metric_pack_key
            or draft.metric_pack_version != COACHING_PROFILE_V1.metric_pack_version
            or draft.metric_pack_key != selection.metric_pack_key
            or draft.metric_pack_version != selection.metric_pack_version
        ):
            raise ValueError("sealed run must use the code-owned Coaching profile")
        if (
            draft.metric_scope_state is not SessionMetricScopeState.EXACT
            or draft.selected_metric_keys != job.metric_keys
            or draft.selected_metric_keys != selection.selected_metric_keys
            or input_receipt.selected_metric_keys != draft.selected_metric_keys
        ):
            raise ValueError("sealed run must retain the exact metric scope")
        expected_run_bridge = stored_session_analysis_run_bridge_fingerprint_v1(
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
            analysis_window_fingerprint=input_receipt.analysis_window_fingerprint,
        )
        if (
            input_receipt.analysis_run_fingerprint_version
            != STORED_SESSION_ANALYSIS_RUN_BRIDGE_V1_VERSION
            or input_receipt.analysis_run_fingerprint != expected_run_bridge
        ):
            raise ValueError(
                "temporal input must bind the exact stored-run fingerprint bridge"
            )
        lineage = (
            (draft.request_fingerprint, input_receipt.analysis_run_request_fingerprint),
            (draft.analysis_profile_key, input_receipt.analysis_profile_key),
            (draft.analysis_profile_version, input_receipt.analysis_profile_version),
            (draft.metric_pack_key, input_receipt.metric_pack_key),
            (draft.metric_pack_version, input_receipt.metric_pack_version),
            (draft.consent_policy_version, input_receipt.consent_policy_version),
            (draft.provider_version, input_receipt.provider_version),
            (draft.adapter_version, input_receipt.provider_adapter_version),
            (draft.source_schema_version, input_receipt.source_schema_version),
            (draft.content_schema_version, input_receipt.content_schema_version),
            (draft.metric_engine_version, input_receipt.metric_engine_version),
            (draft.redactor_version, input_receipt.redactor_version),
            (draft.model_plan_fingerprint, input_receipt.model_plan_fingerprint),
            (draft.schema_version, input_receipt.analysis_run_schema_version),
            (run.finished_at, input_receipt.analysis_run_completed_at),
        )
        if any(left != right for left, right in lineage):
            raise ValueError("stored run conflicts with temporal input provenance")
        if (
            draft.provider_version != session.provider_version
            or draft.adapter_version != session.adapter_version
            or draft.source_schema_version != session.source_schema_version
            or draft.source_schema_version != job.provider_schema_version
            or input_receipt.provider_schema_version
            != job.provider_schema_version
            or draft.redactor_version != job.redactor_version
            or draft.data_tier is not DataTier.REDACTED_CONTENT
            or not draft.local_only
        ):
            raise ValueError("stored run conflicts with session or job provenance")
        assert session.ended_at is not None
        if not (
            session.started_at
            <= session.ended_at
            <= prepared.prepared_at
            <= draft.started_at
            <= run.finished_at
            <= batch.sealed_at
            <= self.sealed_at
        ):
            raise ValueError("comparison run and seal chronology is not exact")
        prepared_job = prepared.analysis_job
        prepared_grant = prepared.automation_grant
        if (
            revalidation.reverified_at != self.sealed_at
            or revalidation.prepared_stratum_id != prepared.prepared_stratum_id
            or revalidation.prepared_stratum_fingerprint != prepared.fingerprint
            or revalidation.analysis_job_id != prepared_job.job_id
            or revalidation.analysis_job_record_authority_fingerprint
            != prepared_job.stored_job_fingerprint
            or revalidation.current_job_lease_authority_fingerprint
            != prepared_job.lease_authority_fingerprint
            or revalidation.current_job_lease_expires_at
            != prepared_job.lease_expires_at
            or revalidation.automation_grant_id != prepared_grant.grant_id
            or revalidation.current_grant_revision != prepared_grant.revision
            or revalidation.current_grant_authority_fingerprint
            != prepared_grant.fingerprint
            or revalidation.current_grant_expires_at != prepared_grant.expires_at
            or self.sealed_at >= prepared_job.lease_expires_at
            or self.sealed_at >= prepared_grant.expires_at
        ):
            raise ValueError("automation authority must be live at seal time")
        expected_order = self.ordered_authority_for(
            prepared_receipt=prepared,
            analysis_run=run,
            sealed_batch=batch,
            automation_revalidation_request=revalidation,
        )
        if self.ordered_authority_fingerprints != expected_order:
            raise ValueError("sealed receipt must commit exact ordered authority")
        expected_id = self.sealed_stratum_id_for(
            prepared_receipt=prepared,
            analysis_run=run,
            sealed_batch=batch,
            automation_revalidation_request=revalidation,
            sealed_at=self.sealed_at,
        )
        if self.sealed_stratum_id != expected_id:
            raise ValueError("sealed stratum ID is not the exact repository derivation")
        roles = _sealed_distinct_roles(
            sealed_stratum_id=self.sealed_stratum_id,
            prepared=prepared,
            run=run,
            run_authority_fingerprint=self.analysis_run_authority_sha256,
            batch=batch,
            revalidation=revalidation,
        )
        _require_distinct_roles(
            allowed_alias_groups=_sealed_alias_groups(batch), **roles
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)


class TemporalComparisonStratumRepositoryV2(Protocol):
    """Narrow repository-return boundary; no caller-authored graph writes."""

    def prepare_automation_stratum(
        self,
        prepared_scope_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> RepositoryPreparedComparisonStratumV1: ...

    def seal_automation_stratum(
        self,
        prepared_stratum_id: str,
        sealed_batch_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> RepositorySealedComparisonStratumV1: ...

    def get_prepared_stratum(
        self, prepared_stratum_id: str
    ) -> RepositoryPreparedComparisonStratumV1 | None: ...

    def get_prepared_stratum_for_job(
        self, job_id: str
    ) -> RepositoryPreparedComparisonStratumV1 | None: ...

    def get_sealed_stratum(
        self, sealed_stratum_id: str
    ) -> RepositorySealedComparisonStratumV1 | None: ...

    def get_sealed_stratum_for_run(
        self, analysis_run_id: str
    ) -> RepositorySealedComparisonStratumV1 | None: ...

    def get_sealed_stratum_for_batch(
        self, sealed_batch_id: str
    ) -> RepositorySealedComparisonStratumV1 | None: ...


__all__ = [
    "AUTOMATION_GRANT_IDENTITY_BRIDGE_V1_VERSION",
    "AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_FINGERPRINT",
    "AUTOMATION_GRANT_IDENTITY_BRIDGE_VERIFIER_V1_VERSION",
    "AutomationGrantIdentityBridgeV1",
    "COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_FINGERPRINT",
    "COMPARISON_STRATUM_REPOSITORY_VERIFIER_V1_VERSION",
    "EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_FINGERPRINT",
    "EXPECTED_RUN_ID_ISSUANCE_VERIFIER_V1_VERSION",
    "REPOSITORY_PREPARED_COMPARISON_STRATUM_V1_VERSION",
    "REPOSITORY_SEALED_COMPARISON_STRATUM_V1_VERSION",
    "RepositoryPreparedComparisonStratumV1",
    "RepositorySealedComparisonStratumV1",
    "TemporalComparisonStratumRepositoryV2",
]
