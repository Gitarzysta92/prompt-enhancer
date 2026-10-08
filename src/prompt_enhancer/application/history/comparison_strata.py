"""Repository-derived comparison-stratum authority contracts.

The first comparison-stratum boundary is deliberately narrow.  This module can
construct content-free preparation and exact-run/batch drafts, but the required
installation-keyed run issuance and repository verification do not yet exist.
Accordingly, no structurally constructed model in this module is repository
authority or a sealed comparison stratum.  V1 remains synthetic-test-only and
cannot authorize matching, comparison, aggregation, snapshots, recommendations,
activation, export, sharing, legacy inference, or backfill.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import re
from typing import Annotated, Any, Final, Literal, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import (
    DataTier,
    PSEUDONYM_PATTERN,
    Provider,
    SafeSession,
    SessionState,
    StrictModel,
)
from ..analysis.text_analysis_presets import COACHING_PROFILE_V1
from ..automation.contracts import (
    AutomationGrantRecord,
    AutomationGrantScope,
    AutomationGrantState,
)
from ..jobs.contracts import (
    ACTIVE_ANALYSIS_JOB_STATES,
    MAX_ANALYSIS_JOB_ATTEMPTS,
    AnalysisJobIdentity,
    AnalysisJobKind,
    AnalysisJobRecord,
    AnalysisJobState,
)
from ..persistence.contracts import (
    AnalysisRunStatus,
    SessionAnalysisRunRecord,
    SessionMetricScopeState,
    TaskRevisionRecord,
)
from .contracts import PersistenceRevalidatedModel
from .persistence import (
    REPOSITORY_TEMPORAL_TIME_BASIS_V1,
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
)


PREPARED_COMPARISON_STRATUM_DRAFT_V1_VERSION = (
    "prepared-comparison-stratum-draft-v1"
)
SEALED_COMPARISON_STRATUM_DRAFT_V1_VERSION = (
    "sealed-comparison-stratum-draft-v1"
)
COMPARISON_SESSION_AUTHORITY_V1_VERSION = "comparison-session-authority-v1"
COMPARISON_JOB_AUTHORITY_V1_VERSION = "comparison-job-authority-v1"
COMPARISON_GRANT_AUTHORITY_V1_VERSION = "comparison-grant-authority-v1"
EXPECTED_ANALYSIS_RUN_VERIFICATION_REQUEST_V1_VERSION = (
    "expected-analysis-run-verification-request-v1"
)
AUTOMATION_REVALIDATION_REQUEST_V1_VERSION = (
    "automation-revalidation-request-v1"
)
REVIEWED_TASK_TARGET_PROJECTION_V1_VERSION = (
    "reviewed-task-target-projection-v1"
)
REVIEWED_TASK_SELECTION_VERIFICATION_REQUEST_V1_VERSION = (
    "reviewed-task-selection-verification-request-v1"
)
REVIEWED_TASK_MANIFEST_V1_VERSION = "reviewed-task-manifest-v1"
COMPARISON_STRATUM_DIMENSIONS_V1_VERSION = "comparison-stratum-dimensions-v1"
COMPARISON_POLICY_IDENTITY_V1_VERSION = "comparison-policy-identity-v1"
COMPARISON_POLICY_SET_V1_VERSION = "comparison-policy-set-v1"

TASK_TYPE_POLICY_V1_VERSION = "reviewed-task-category-exact-v1"
AUTOMATION_RUN_BINDING_POLICY_V1_VERSION = (
    "automation-session-quality-run-binding-v1"
)
MATCHING_POLICY_V1_VERSION = (
    "exact-known-within-project-no-unknown-equality-v1"
)
CENSORING_POLICY_V1_VERSION = "recommendation-followup-unavailable-v1"
TASK_MIX_POLICY_V1_VERSION = (
    "separate-reviewed-categories-visible-unknown-no-pooling-v1"
)

COMPARISON_AUTHORITY_SCOPE_V1 = "automation-pre-read-exact-run-batch-v1"
MAX_COMPARISON_CURRENT_TASKS = 100
COMPARISON_CURRENT_TASK_QUERY_LIMIT = MAX_COMPARISON_CURRENT_TASKS + 1
MAX_SEALED_AUTHORITY_FINGERPRINTS = 12

_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
_MAX_ORDINAL = 9_007_199_254_740_991
NonNegativeStrictInt = Annotated[
    int, Field(strict=True, ge=0, le=_MAX_ORDINAL)
]
PositiveStrictInt = Annotated[int, Field(strict=True, ge=1, le=_MAX_ORDINAL)]


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


def _optional_utc(value: datetime | None) -> datetime | None:
    return None if value is None else _utc(value)


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(
            value,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _model_sha256(value: StrictModel) -> str:
    return _canonical_sha256(value.model_dump(mode="json"))


def _domain_sha256(domain: str, payload: Any) -> str:
    return _canonical_sha256({"domain": domain, "payload": payload})


def _require_unique_roles(**roles: str | None) -> None:
    populated = {name: value for name, value in roles.items() if value is not None}
    inverse: dict[str, list[str]] = {}
    for name, value in populated.items():
        assert value is not None
        inverse.setdefault(value, []).append(name)
    if any(len(names) > 1 for names in inverse.values()):
        raise ValueError("comparison identities and fingerprints must be role-separated")


class ComparisonAuthorityKindV1(StrEnum):
    AUTOMATION_SESSION_QUALITY = "automation_session_quality"


class ComparisonTaskTypeV1(StrEnum):
    BUG_FIX = "bug_fix"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    RESEARCH_DESIGN = "research_design"


class ComparisonTaskTypeStateV1(StrEnum):
    KNOWN_REVIEWED = "known_reviewed"
    UNKNOWN_NOT_REVIEWED = "unknown_not_reviewed"
    UNKNOWN_AMBIGUOUS_CURRENT_TASKS = "unknown_ambiguous_current_tasks"
    UNKNOWN_UNSUPPORTED_REVIEWED_VALUE = "unknown_unsupported_reviewed_value"


class ComparisonDimensionStateV1(StrEnum):
    KNOWN = "known"
    UNKNOWN_NOT_RECORDED = "unknown_not_recorded"


class ComparisonTaskMixBucketV1(StrEnum):
    BUG_FIX = "bug_fix"
    FEATURE_IMPLEMENTATION = "feature_implementation"
    RESEARCH_DESIGN = "research_design"
    UNKNOWN_NOT_REVIEWED = "unknown_not_reviewed"
    UNKNOWN_AMBIGUOUS_CURRENT_TASKS = "unknown_ambiguous_current_tasks"
    UNKNOWN_UNSUPPORTED_REVIEWED_VALUE = "unknown_unsupported_reviewed_value"


class ComparisonMatchReadinessV1(StrEnum):
    INSUFFICIENT_REQUIRED_STRATA = "insufficient_required_strata"


class ComparisonCensoringReadinessV1(StrEnum):
    NO_FOLLOWUP_AUTHORITY = "no_followup_authority"


class ComparisonPolicyKindV1(StrEnum):
    TASK_TYPE = "task_type"
    AUTOMATION_RUN_BINDING = "automation_run_binding"
    MATCHING = "matching"
    CENSORING = "censoring"
    TASK_MIX = "task_mix"


_POLICY_VERSIONS: Final[dict[ComparisonPolicyKindV1, str]] = {
    ComparisonPolicyKindV1.TASK_TYPE: TASK_TYPE_POLICY_V1_VERSION,
    ComparisonPolicyKindV1.AUTOMATION_RUN_BINDING: (
        AUTOMATION_RUN_BINDING_POLICY_V1_VERSION
    ),
    ComparisonPolicyKindV1.MATCHING: MATCHING_POLICY_V1_VERSION,
    ComparisonPolicyKindV1.CENSORING: CENSORING_POLICY_V1_VERSION,
    ComparisonPolicyKindV1.TASK_MIX: TASK_MIX_POLICY_V1_VERSION,
}

_POLICY_PAYLOADS: Final[dict[ComparisonPolicyKindV1, dict[str, Any]]] = {
    ComparisonPolicyKindV1.TASK_TYPE: {
        "as_of_selection": (
            "latest_revision_per_task_then_target_session_membership"
        ),
        "known_mapping": {
            "bug_fix": "bug_fix",
            "feature_implementation": "feature_implementation",
            "research_design": "research_design",
        },
        "multiple_current_tasks": "unknown_ambiguous_current_tasks",
        "no_current_task": "unknown_not_reviewed",
        "post_cutoff_revision_allowed": False,
        "required_lifecycle_state": "confirmed",
        "text_inference_allowed": False,
        "unsupported_reviewed_value": "unknown_unsupported_reviewed_value",
        "version": TASK_TYPE_POLICY_V1_VERSION,
    },
    ComparisonPolicyKindV1.AUTOMATION_RUN_BINDING: {
        "automation_grant_required": True,
        "idempotency_key_template": "automation-{job_id}",
        "job_kind": AnalysisJobKind.SESSION_QUALITY.value,
        "lease_required_at_prepare_and_seal": True,
        "local_only": True,
        "metric_pack_key": COACHING_PROFILE_V1.metric_pack_key,
        "metric_pack_version": COACHING_PROFILE_V1.metric_pack_version,
        "preset_id": COACHING_PROFILE_V1.preset_id.value,
        "run_id_domain": "session-analysis-run-v1",
        "run_id_inputs": (
            "idempotency_key",
            "provider",
            "session_id",
            "metric_pack_key",
            "metric_pack_version",
        ),
        "version": AUTOMATION_RUN_BINDING_POLICY_V1_VERSION,
    },
    ComparisonPolicyKindV1.MATCHING: {
        "causal_label_allowed": False,
        "cross_definition_allowed": False,
        "cross_project_allowed": False,
        "cross_provider_allowed": False,
        "design": "prospective_observational_exact_match",
        "post_outcome_matching_allowed": False,
        "required_exact_dimensions": (
            "installation_id",
            "project_id",
            "provider",
            "task_type",
            "language",
            "complexity",
            "agent_model_key",
            "agent_model_revision",
            "agent_permission_mode",
            "agent_sandbox_mode",
            "agent_network_mode",
            "agent_tool_policy_version",
            "metric_comparison_identity_fingerprint",
        ),
        "required_value_state": "known",
        "unknown_equals_unknown": False,
        "version": MATCHING_POLICY_V1_VERSION,
    },
    ComparisonPolicyKindV1.CENSORING: {
        "followup_deadline_required": True,
        "followup_window_available": False,
        "missing_followup_is_failure": False,
        "missing_followup_is_success": False,
        "recommendation_anchor_required": True,
        "right_censoring_classification_allowed": False,
        "state": ComparisonCensoringReadinessV1.NO_FOLLOWUP_AUTHORITY.value,
        "version": CENSORING_POLICY_V1_VERSION,
    },
    ComparisonPolicyKindV1.TASK_MIX: {
        "drop_unknown": False,
        "impute_unknown": False,
        "known_categories": (
            "bug_fix",
            "feature_implementation",
            "research_design",
        ),
        "pool_categories": False,
        "standardization_allowed": False,
        "unknown_buckets": (
            "unknown_not_reviewed",
            "unknown_ambiguous_current_tasks",
            "unknown_unsupported_reviewed_value",
        ),
        "unknown_comparison_eligible": False,
        "unknown_in_population_coverage": True,
        "weighting_allowed": False,
        "version": TASK_MIX_POLICY_V1_VERSION,
    },
}

_POLICY_SHA256: Final[dict[ComparisonPolicyKindV1, str]] = {
    kind: _domain_sha256(f"comparison.{kind.value}-policy.v1", payload)
    for kind, payload in _POLICY_PAYLOADS.items()
}


class ComparisonPolicyIdentityV1(PersistenceRevalidatedModel):
    contract_version: Literal[COMPARISON_POLICY_IDENTITY_V1_VERSION] = (
        COMPARISON_POLICY_IDENTITY_V1_VERSION
    )
    kind: ComparisonPolicyKindV1
    version: str
    sha256: str
    code_owned: Literal[True] = True
    caller_override_allowed: Literal[False] = False

    _version = field_validator("version")(_safe_version)
    _sha = field_validator("sha256")(_digest)

    @model_validator(mode="after")
    def exact_code_owned_policy(self) -> ComparisonPolicyIdentityV1:
        if (
            self.version != _POLICY_VERSIONS[self.kind]
            or self.sha256 != _POLICY_SHA256[self.kind]
        ):
            raise ValueError("comparison policy identity is not the code-owned policy")
        return self


def _policy(kind: ComparisonPolicyKindV1) -> ComparisonPolicyIdentityV1:
    return ComparisonPolicyIdentityV1(
        kind=kind,
        version=_POLICY_VERSIONS[kind],
        sha256=_POLICY_SHA256[kind],
    )


class ComparisonPolicySetV1(PersistenceRevalidatedModel):
    contract_version: Literal[COMPARISON_POLICY_SET_V1_VERSION] = (
        COMPARISON_POLICY_SET_V1_VERSION
    )
    task_type: ComparisonPolicyIdentityV1
    automation_run_binding: ComparisonPolicyIdentityV1
    matching: ComparisonPolicyIdentityV1
    censoring: ComparisonPolicyIdentityV1
    task_mix: ComparisonPolicyIdentityV1
    code_owned: Literal[True] = True
    caller_override_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exact_policy_roles(self) -> ComparisonPolicySetV1:
        expected = (
            (self.task_type, ComparisonPolicyKindV1.TASK_TYPE),
            (
                self.automation_run_binding,
                ComparisonPolicyKindV1.AUTOMATION_RUN_BINDING,
            ),
            (self.matching, ComparisonPolicyKindV1.MATCHING),
            (self.censoring, ComparisonPolicyKindV1.CENSORING),
            (self.task_mix, ComparisonPolicyKindV1.TASK_MIX),
        )
        if any(identity.kind is not kind for identity, kind in expected):
            raise ValueError("comparison policy roles must be exact")
        _require_unique_roles(
            task_type_policy=self.task_type.sha256,
            automation_run_binding_policy=self.automation_run_binding.sha256,
            matching_policy=self.matching.sha256,
            censoring_policy=self.censoring.sha256,
            task_mix_policy=self.task_mix.sha256,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)


_COMPARISON_POLICY_SET_V1: Final[ComparisonPolicySetV1] = ComparisonPolicySetV1(
    task_type=_policy(ComparisonPolicyKindV1.TASK_TYPE),
    automation_run_binding=_policy(
        ComparisonPolicyKindV1.AUTOMATION_RUN_BINDING
    ),
    matching=_policy(ComparisonPolicyKindV1.MATCHING),
    censoring=_policy(ComparisonPolicyKindV1.CENSORING),
    task_mix=_policy(ComparisonPolicyKindV1.TASK_MIX),
)


def comparison_policy_set_v1() -> ComparisonPolicySetV1:
    """Return the immutable, code-owned V1 policy catalog."""

    return _COMPARISON_POLICY_SET_V1


class ComparisonSessionAuthorityV1(PersistenceRevalidatedModel):
    """Content-free projection of one stored session row.

    Private display names are intentionally absent, and provider-reported
    session timestamps do not become temporal source-item authority.
    """

    contract_version: Literal[COMPARISON_SESSION_AUTHORITY_V1_VERSION] = (
        COMPARISON_SESSION_AUTHORITY_V1_VERSION
    )
    provider: Provider
    installation_id: str
    project_id: str
    session_id: str
    provider_version: str
    adapter_version: str
    source_schema_version: str
    started_at: datetime
    ended_at: datetime | None = None
    terminal_state: SessionState
    events_complete: bool
    display_fields_excluded: Literal[True] = True
    source_item_time_authority: Literal[False] = False
    stable_snapshot_cursor_authority: Literal[False] = False

    _ids = field_validator("installation_id", "project_id", "session_id")(_digest)
    _versions = field_validator(
        "provider_version", "adapter_version", "source_schema_version"
    )(_safe_version)
    _started = field_validator("started_at")(_utc)
    _ended = field_validator("ended_at")(_optional_utc)

    @model_validator(mode="after")
    def coherent_session_time(self) -> ComparisonSessionAuthorityV1:
        if self.ended_at is not None and self.ended_at < self.started_at:
            raise ValueError("session end cannot precede its start")
        return self

    @classmethod
    def from_stored_session(
        cls, session: SafeSession
    ) -> ComparisonSessionAuthorityV1:
        return cls(
            provider=session.provider,
            installation_id=session.installation_id,
            project_id=session.project_id,
            session_id=session.session_id,
            provider_version=session.provider_version,
            adapter_version=session.adapter_version,
            source_schema_version=session.source_schema_version,
            started_at=session.started_at,
            ended_at=session.ended_at,
            terminal_state=session.terminal_state,
            events_complete=session.events_complete,
        )

    @property
    def fingerprint(self) -> str:
        return _domain_sha256(
            "comparison.safe-session-authority.v1",
            self.model_dump(mode="json"),
        )


class ComparisonAnalysisJobAuthorityV1(PersistenceRevalidatedModel):
    """Immutable job projection plus one claimed content-free lease binding."""

    contract_version: Literal[COMPARISON_JOB_AUTHORITY_V1_VERSION] = (
        COMPARISON_JOB_AUTHORITY_V1_VERSION
    )
    job_id: str
    dedupe_key: str
    identity: AnalysisJobIdentity
    max_attempts: Annotated[
        int, Field(strict=True, ge=1, le=MAX_ANALYSIS_JOB_ATTEMPTS)
    ]
    created_at: datetime
    state_at_preparation: AnalysisJobState
    lease_verified_at: datetime
    lease_expires_at: datetime
    lease_authority_fingerprint: str
    authority_sha256: str
    active_lease_verified: Literal[True] = True
    lease_secrets_persisted: Literal[False] = False

    _ids = field_validator(
        "job_id",
        "dedupe_key",
        "lease_authority_fingerprint",
        "authority_sha256",
    )(_digest)
    _times = field_validator(
        "created_at", "lease_verified_at", "lease_expires_at"
    )(_utc)

    @staticmethod
    def authority_for(record: AnalysisJobRecord) -> str:
        return _domain_sha256(
            "comparison.analysis-job-authority.v1",
            {
                "created_at": record.created_at.isoformat(),
                "dedupe_key": record.dedupe_key,
                "identity": record.identity.model_dump(mode="json"),
                "job_id": record.job_id,
                "max_attempts": record.max_attempts,
            },
        )

    @classmethod
    def from_active_record(
        cls,
        record: AnalysisJobRecord,
        *,
        observed_at: datetime,
    ) -> ComparisonAnalysisJobAuthorityV1:
        checked_at = _utc(observed_at)
        if record.state not in ACTIVE_ANALYSIS_JOB_STATES:
            raise ValueError("comparison preparation requires an active leased job")
        if any(
            value is None
            for value in (record.lease_owner, record.lease_token, record.lease_expires_at)
        ):
            raise ValueError("comparison preparation requires a complete live lease")
        assert record.lease_expires_at is not None
        if checked_at >= record.lease_expires_at:
            raise ValueError("comparison preparation requires an unexpired job lease")
        assert record.lease_owner is not None
        assert record.lease_token is not None
        lease_authority_fingerprint = _domain_sha256(
            "comparison.ephemeral-job-lease-binding.v1",
            {
                "job_id": record.job_id,
                "lease_expires_at": record.lease_expires_at.isoformat(),
                "lease_owner": record.lease_owner,
                "lease_token": record.lease_token,
            },
        )
        return cls(
            job_id=record.job_id,
            dedupe_key=record.dedupe_key,
            identity=record.identity,
            max_attempts=record.max_attempts,
            created_at=record.created_at,
            state_at_preparation=record.state,
            lease_verified_at=checked_at,
            lease_expires_at=record.lease_expires_at,
            lease_authority_fingerprint=lease_authority_fingerprint,
            authority_sha256=cls.authority_for(record),
        )

    @model_validator(mode="after")
    def exact_job_authority(self) -> ComparisonAnalysisJobAuthorityV1:
        if not (
            self.created_at <= self.lease_verified_at < self.lease_expires_at
        ):
            raise ValueError("analysis job lease must be live at preparation")
        if self.state_at_preparation not in ACTIVE_ANALYSIS_JOB_STATES:
            raise ValueError("analysis job state must be active at preparation")
        expected = _domain_sha256(
            "comparison.analysis-job-authority.v1",
            {
                "created_at": self.created_at.isoformat(),
                "dedupe_key": self.dedupe_key,
                "identity": self.identity.model_dump(mode="json"),
                "job_id": self.job_id,
                "max_attempts": self.max_attempts,
            },
        )
        if self.authority_sha256 != expected:
            raise ValueError("analysis job authority fingerprint is not exact")
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)

    @property
    def stored_job_fingerprint(self) -> str:
        """Immutable stored-job authority, excluding the current lease."""

        return self.authority_sha256


class ComparisonAutomationGrantAuthorityV1(PersistenceRevalidatedModel):
    """Security-relevant projection of one active stored grant revision."""

    contract_version: Literal[COMPARISON_GRANT_AUTHORITY_V1_VERSION] = (
        COMPARISON_GRANT_AUTHORITY_V1_VERSION
    )
    grant_id: str
    revision: PositiveStrictInt
    scope: AutomationGrantScope
    created_at: datetime
    renewed_at: datetime
    expires_at: datetime
    observed_active_at: datetime
    authority_sha256: str
    state_at_preparation: Literal[AutomationGrantState.ACTIVE] = (
        AutomationGrantState.ACTIVE
    )
    scheduling_housekeeping_excluded: Literal[True] = True

    _ids = field_validator("grant_id", "authority_sha256")(_digest)
    _times = field_validator(
        "created_at", "renewed_at", "expires_at", "observed_active_at"
    )(_utc)

    @staticmethod
    def authority_for(record: AutomationGrantRecord) -> str:
        if record.state is not AutomationGrantState.ACTIVE:
            raise ValueError("grant authority fingerprint requires an active record")
        return _domain_sha256(
            "comparison.automation-grant-authority.v1",
            {
                "created_at": record.created_at.isoformat(),
                "expires_at": record.expires_at.isoformat(),
                "grant_id": record.grant_id,
                "renewed_at": record.renewed_at.isoformat(),
                "revision": record.revision,
                "scope": record.scope.model_dump(mode="json"),
                "state": AutomationGrantState.ACTIVE.value,
            },
        )

    @classmethod
    def from_active_record(
        cls,
        record: AutomationGrantRecord,
        *,
        observed_at: datetime,
    ) -> ComparisonAutomationGrantAuthorityV1:
        checked_at = _utc(observed_at)
        if record.effective_state(checked_at) is not AutomationGrantState.ACTIVE:
            raise ValueError("comparison preparation requires an active grant")
        return cls(
            grant_id=record.grant_id,
            revision=record.revision,
            scope=record.scope,
            created_at=record.created_at,
            renewed_at=record.renewed_at,
            expires_at=record.expires_at,
            observed_active_at=checked_at,
            authority_sha256=cls.authority_for(record),
        )

    @model_validator(mode="after")
    def exact_grant_authority(self) -> ComparisonAutomationGrantAuthorityV1:
        if not (
            self.created_at <= self.renewed_at <= self.observed_active_at
            < self.expires_at
        ):
            raise ValueError("grant authority must be active at preparation")
        expected = _domain_sha256(
            "comparison.automation-grant-authority.v1",
            {
                "created_at": self.created_at.isoformat(),
                "expires_at": self.expires_at.isoformat(),
                "grant_id": self.grant_id,
                "renewed_at": self.renewed_at.isoformat(),
                "revision": self.revision,
                "scope": self.scope.model_dump(mode="json"),
                "state": AutomationGrantState.ACTIVE.value,
            },
        )
        if self.authority_sha256 != expected:
            raise ValueError("automation grant authority fingerprint is not exact")
        return self

    @property
    def fingerprint(self) -> str:
        return self.authority_sha256


def automation_grant_scope_fingerprint(scope: AutomationGrantScope) -> str:
    """Commit the exact local analytics scope without implying agent permission."""

    checked = AutomationGrantScope.model_validate(scope.model_dump(mode="python"))
    return _domain_sha256(
        "comparison.automation-grant-scope.v1",
        checked.model_dump(mode="json"),
    )


class ReviewedTaskTargetProjectionV1(PersistenceRevalidatedModel):
    """Target-only task projection with no cross-session membership metadata."""

    contract_version: Literal[REVIEWED_TASK_TARGET_PROJECTION_V1_VERSION] = (
        REVIEWED_TASK_TARGET_PROJECTION_V1_VERSION
    )
    task_id: str
    revision: PositiveStrictInt
    project_id: str
    target_session_id: str
    task_type: str
    lifecycle_state: str
    created_at: datetime
    projection_sha256: str
    target_session_membership_verified: Literal[True] = True
    unrelated_session_ids_omitted: Literal[True] = True
    repository_rehydration_required: Literal[True] = True

    _ids = field_validator(
        "task_id",
        "project_id",
        "target_session_id",
        "projection_sha256",
    )(_digest)
    _created = field_validator("created_at")(_utc)
    _task_codes = field_validator("task_type", "lifecycle_state")(_safe_version)

    @staticmethod
    def projection_for(
        *,
        task_id: str,
        revision: int,
        project_id: str,
        target_session_id: str,
        task_type: str,
        lifecycle_state: str,
        created_at: datetime,
    ) -> str:
        return _domain_sha256(
            "comparison.reviewed-task-target-projection.v1",
            {
                "created_at": created_at.isoformat(),
                "lifecycle_state": lifecycle_state,
                "project_id": project_id,
                "revision": revision,
                "target_session_id": target_session_id,
                "target_session_membership_verified": True,
                "task_id": task_id,
                "task_type": task_type,
                "unrelated_session_ids_omitted": True,
            },
        )

    @classmethod
    def from_source_revision(
        cls,
        record: TaskRevisionRecord,
        *,
        target_session_id: str,
    ) -> ReviewedTaskTargetProjectionV1:
        checked = TaskRevisionRecord.model_validate(record.model_dump(mode="python"))
        target = _digest(target_session_id)
        if target not in checked.session_ids:
            raise ValueError("reviewed-task projection requires target membership")
        projection = cls.projection_for(
            task_id=checked.task_id,
            revision=checked.revision,
            project_id=checked.project_id,
            target_session_id=target,
            task_type=checked.task_type,
            lifecycle_state=checked.lifecycle_state,
            created_at=checked.created_at,
        )
        return cls(
            task_id=checked.task_id,
            revision=checked.revision,
            project_id=checked.project_id,
            target_session_id=target,
            task_type=checked.task_type,
            lifecycle_state=checked.lifecycle_state,
            created_at=checked.created_at,
            projection_sha256=projection,
        )

    @model_validator(mode="after")
    def exact_projection(self) -> ReviewedTaskTargetProjectionV1:
        expected = self.projection_for(
            task_id=self.task_id,
            revision=self.revision,
            project_id=self.project_id,
            target_session_id=self.target_session_id,
            task_type=self.task_type,
            lifecycle_state=self.lifecycle_state,
            created_at=self.created_at,
        )
        if self.projection_sha256 != expected:
            raise ValueError("reviewed-task projection fingerprint is not exact")
        return self

    @property
    def fingerprint(self) -> str:
        return self.projection_sha256


class ReviewedTaskSelectionVerificationRequestV1(PersistenceRevalidatedModel):
    """Untrusted MAX+1 query claim awaiting repository verification."""

    contract_version: Literal[
        REVIEWED_TASK_SELECTION_VERIFICATION_REQUEST_V1_VERSION
    ] = REVIEWED_TASK_SELECTION_VERIFICATION_REQUEST_V1_VERSION
    selection_request_id: str
    session_id: str
    cutoff_at: datetime
    query_limit: Literal[COMPARISON_CURRENT_TASK_QUERY_LIMIT] = (
        COMPARISON_CURRENT_TASK_QUERY_LIMIT
    )
    scanned_current_candidate_count: NonNegativeStrictInt
    current_revisions: tuple[ReviewedTaskTargetProjectionV1, ...] = Field(
        max_length=MAX_COMPARISON_CURRENT_TASKS
    )
    claimed_query_evidence_fingerprint: str
    selection_sha256: str
    overflow_detected: Literal[False] = False
    max_plus_one_query_verified: Literal[False] = False
    complete_not_truncated: Literal[False] = False
    latest_revision_before_membership_filter_required: Literal[True] = True
    repository_verification_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_verified: Literal[False] = False
    synthetic_test_only: Literal[True] = True

    _ids = field_validator(
        "selection_request_id",
        "session_id",
        "claimed_query_evidence_fingerprint",
        "selection_sha256",
    )(_digest)
    _cutoff = field_validator("cutoff_at")(_utc)

    @staticmethod
    def selection_for(
        *,
        selection_request_id: str,
        session_id: str,
        cutoff_at: datetime,
        scanned_current_candidate_count: int,
        ordered_projection_fingerprints: tuple[str, ...],
        claimed_query_evidence_fingerprint: str,
    ) -> str:
        return _domain_sha256(
            "comparison.reviewed-task-selection-verification-request.v1",
            {
                "cutoff_at": cutoff_at.isoformat(),
                "ordered_projection_fingerprints": ordered_projection_fingerprints,
                "overflow_detected": False,
                "query_limit": COMPARISON_CURRENT_TASK_QUERY_LIMIT,
                "claimed_query_evidence_fingerprint": (
                    claimed_query_evidence_fingerprint
                ),
                "scanned_current_candidate_count": scanned_current_candidate_count,
                "selection_request_id": selection_request_id,
                "session_id": session_id,
            },
        )

    @model_validator(mode="after")
    def exact_complete_selection(self) -> ReviewedTaskSelectionVerificationRequestV1:
        ordered = tuple(
            sorted(self.current_revisions, key=lambda item: (item.task_id, item.revision))
        )
        if self.current_revisions != ordered:
            raise ValueError("current task projections must be canonically ordered")
        if self.scanned_current_candidate_count != len(self.current_revisions):
            raise ValueError("claimed scan count must bind every supplied candidate")
        if self.scanned_current_candidate_count > MAX_COMPARISON_CURRENT_TASKS:
            raise ValueError("claimed MAX+1 query detected task-selection overflow")
        if len({item.task_id for item in self.current_revisions}) != len(
            self.current_revisions
        ):
            raise ValueError("selection may contain only one current revision per task")
        if any(
            item.target_session_id != self.session_id
            for item in self.current_revisions
        ):
            raise ValueError("every task projection must bind the target session")
        expected = self.selection_for(
            selection_request_id=self.selection_request_id,
            session_id=self.session_id,
            cutoff_at=self.cutoff_at,
            scanned_current_candidate_count=self.scanned_current_candidate_count,
            ordered_projection_fingerprints=tuple(
                item.fingerprint for item in self.current_revisions
            ),
            claimed_query_evidence_fingerprint=(
                self.claimed_query_evidence_fingerprint
            ),
        )
        if self.selection_sha256 != expected:
            raise ValueError("task-selection verification request is not exact")
        _require_unique_roles(
            selection_request_id=self.selection_request_id,
            session_id=self.session_id,
            claimed_query_evidence=self.claimed_query_evidence_fingerprint,
            selection_fingerprint=self.selection_sha256,
            **{
                f"task_{index}_id": item.task_id
                for index, item in enumerate(self.current_revisions)
            },
            **{
                f"task_{index}_projection": item.fingerprint
                for index, item in enumerate(self.current_revisions)
            },
        )
        return self

    @property
    def fingerprint(self) -> str:
        return self.selection_sha256


def select_current_reviewed_tasks_as_of(
    *,
    revisions: tuple[TaskRevisionRecord, ...],
    session_id: str,
    cutoff_at: datetime,
) -> tuple[TaskRevisionRecord, ...]:
    """Select latest task revisions before testing target-session membership.

    This pins only the latest-revision/membership semantics.  Its bare tuple is
    never completeness authority.  A repository must separately issue a
    ``ReviewedTaskSelectionVerificationRequestV1`` from a MAX+1 query before the
    rows can enter a manifest.
    """

    checked_session = _digest(session_id)
    checked_cutoff = _utc(cutoff_at)
    latest: dict[str, TaskRevisionRecord] = {}
    seen: dict[tuple[str, int], TaskRevisionRecord] = {}
    for value in revisions:
        record = TaskRevisionRecord.model_validate(value.model_dump(mode="python"))
        identity = (record.task_id, record.revision)
        prior_exact = seen.get(identity)
        if prior_exact is not None and prior_exact != record:
            raise ValueError("stored task revision identity is conflicting")
        seen[identity] = record
        if record.created_at > checked_cutoff:
            continue
        prior = latest.get(record.task_id)
        if prior is None or record.revision > prior.revision:
            latest[record.task_id] = record
    selected = tuple(
        sorted(
            (
                record
                for record in latest.values()
                if checked_session in record.session_ids
            ),
            key=lambda item: (item.task_id, item.revision),
        )
    )
    if any(record.lifecycle_state != "confirmed" for record in selected):
        raise ValueError("comparison task authority requires confirmed revisions")
    return selected


class ReviewedTaskManifestV1(PersistenceRevalidatedModel):
    """Unverified latest-revision-as-of manifest for one target session."""

    contract_version: Literal[REVIEWED_TASK_MANIFEST_V1_VERSION] = (
        REVIEWED_TASK_MANIFEST_V1_VERSION
    )
    cutoff_at: datetime
    session_id: str
    selection_request: ReviewedTaskSelectionVerificationRequestV1
    manifest_sha256: str
    latest_revision_before_membership_filter_required: Literal[True] = True
    complete_not_truncated: Literal[False] = False
    bounded_completeness_verified: Literal[False] = False
    repository_verification_required: Literal[True] = True
    post_cutoff_revision_allowed: Literal[False] = False

    _cutoff = field_validator("cutoff_at")(_utc)
    _session = field_validator("session_id")(_digest)
    _manifest = field_validator("manifest_sha256")(_digest)

    @staticmethod
    def manifest_for(
        *,
        session_id: str,
        cutoff_at: datetime,
        selection_request_fingerprint: str,
    ) -> str:
        return _domain_sha256(
            "comparison.task-manifest.v1",
            {
                "cutoff_at": cutoff_at.isoformat(),
                "selection_request_fingerprint": selection_request_fingerprint,
                "session_id": session_id,
            },
        )

    @classmethod
    def from_selection_verification_request(
        cls,
        *,
        selection_request: ReviewedTaskSelectionVerificationRequestV1,
    ) -> ReviewedTaskManifestV1:
        checked = ReviewedTaskSelectionVerificationRequestV1.revalidate_for_persistence(
            selection_request
        )
        return cls(
            cutoff_at=checked.cutoff_at,
            session_id=checked.session_id,
            selection_request=checked,
            manifest_sha256=cls.manifest_for(
                session_id=checked.session_id,
                cutoff_at=checked.cutoff_at,
                selection_request_fingerprint=checked.fingerprint,
            ),
        )

    @model_validator(mode="after")
    def exact_manifest(self) -> ReviewedTaskManifestV1:
        selection = self.selection_request
        if (
            self.session_id != selection.session_id
            or self.cutoff_at != selection.cutoff_at
        ):
            raise ValueError("task manifest must bind its selection request")
        expected_order = tuple(
            sorted(self.current_revisions, key=lambda item: (item.task_id, item.revision))
        )
        if self.current_revisions != expected_order:
            raise ValueError("current task revisions must be canonically ordered")
        if self.current_task_count != len(self.current_revisions):
            raise ValueError("current task count must be exact")
        if len({item.task_id for item in self.current_revisions}) != len(
            self.current_revisions
        ):
            raise ValueError("a task manifest may contain only one current revision per task")
        if any(
            item.lifecycle_state != "confirmed"
            or item.target_session_id != self.session_id
            or not item.target_session_membership_verified
            or item.created_at > self.cutoff_at
            for item in self.current_revisions
        ):
            raise ValueError(
                "task manifest requires confirmed target-session revisions at its cutoff"
            )
        expected_fingerprints = tuple(item.fingerprint for item in self.current_revisions)
        if self.ordered_revision_fingerprints != expected_fingerprints:
            raise ValueError("task manifest must bind every exact revision")
        expected_manifest = self.manifest_for(
            session_id=self.session_id,
            cutoff_at=self.cutoff_at,
            selection_request_fingerprint=selection.fingerprint,
        )
        if self.manifest_sha256 != expected_manifest:
            raise ValueError("task manifest fingerprint is not exact")
        _require_unique_roles(
            session_id=self.session_id,
            selection_request_id=selection.selection_request_id,
            selection_request_fingerprint=selection.fingerprint,
            selection_query_evidence=selection.claimed_query_evidence_fingerprint,
            manifest=self.manifest_sha256,
            **{
                f"task_{index}_id": item.task_id
                for index, item in enumerate(self.current_revisions)
            },
            **{
                f"task_{index}_fingerprint": fingerprint
                for index, fingerprint in enumerate(expected_fingerprints)
            },
        )
        return self

    @property
    def current_revisions(self) -> tuple[ReviewedTaskTargetProjectionV1, ...]:
        return self.selection_request.current_revisions

    @property
    def current_task_count(self) -> int:
        return self.selection_request.scanned_current_candidate_count

    @property
    def ordered_revision_fingerprints(self) -> tuple[str, ...]:
        return tuple(item.fingerprint for item in self.current_revisions)

    @property
    def fingerprint(self) -> str:
        return self.manifest_sha256


def _task_projection(
    manifest: ReviewedTaskManifestV1,
) -> tuple[
    ComparisonTaskTypeStateV1,
    ComparisonTaskTypeV1 | None,
    ComparisonTaskMixBucketV1,
]:
    if manifest.current_task_count == 0:
        return (
            ComparisonTaskTypeStateV1.UNKNOWN_NOT_REVIEWED,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_NOT_REVIEWED,
        )
    if manifest.current_task_count > 1:
        return (
            ComparisonTaskTypeStateV1.UNKNOWN_AMBIGUOUS_CURRENT_TASKS,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_AMBIGUOUS_CURRENT_TASKS,
        )
    task_code = manifest.current_revisions[0].task_type
    try:
        task_type = ComparisonTaskTypeV1(task_code)
    except ValueError:
        return (
            ComparisonTaskTypeStateV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
            None,
            ComparisonTaskMixBucketV1.UNKNOWN_UNSUPPORTED_REVIEWED_VALUE,
        )
    return (
        ComparisonTaskTypeStateV1.KNOWN_REVIEWED,
        task_type,
        ComparisonTaskMixBucketV1(task_type.value),
    )


class ComparisonStratumDimensionsV1(PersistenceRevalidatedModel):
    contract_version: Literal[COMPARISON_STRATUM_DIMENSIONS_V1_VERSION] = (
        COMPARISON_STRATUM_DIMENSIONS_V1_VERSION
    )
    repository_scope_state: Literal[ComparisonDimensionStateV1.KNOWN] = (
        ComparisonDimensionStateV1.KNOWN
    )
    installation_id: str
    project_id: str
    provider: Provider
    task_type_state: ComparisonTaskTypeStateV1
    task_type: ComparisonTaskTypeV1 | None = None
    task_mix_bucket: ComparisonTaskMixBucketV1
    task_manifest: ReviewedTaskManifestV1

    language_state: Literal[
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    ] = ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    language_code: None = None

    complexity_state: Literal[
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    ] = ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    complexity_schema_version: None = None
    complexity_value: None = None

    agent_permission_state: Literal[
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    ] = ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    agent_permission_mode: None = None
    agent_sandbox_mode: None = None
    agent_network_mode: None = None
    agent_tool_policy_version: None = None

    agent_model_state: Literal[
        ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    ] = ComparisonDimensionStateV1.UNKNOWN_NOT_RECORDED
    agent_model_provider: None = None
    agent_model_key: None = None
    agent_model_revision: None = None

    match_readiness: Literal[
        ComparisonMatchReadinessV1.INSUFFICIENT_REQUIRED_STRATA
    ] = ComparisonMatchReadinessV1.INSUFFICIENT_REQUIRED_STRATA
    censoring_readiness: Literal[
        ComparisonCensoringReadinessV1.NO_FOLLOWUP_AUTHORITY
    ] = ComparisonCensoringReadinessV1.NO_FOLLOWUP_AUTHORITY

    _ids = field_validator("installation_id", "project_id")(_digest)

    @classmethod
    def from_authority(
        cls,
        *,
        session: ComparisonSessionAuthorityV1,
        task_manifest: ReviewedTaskManifestV1,
    ) -> ComparisonStratumDimensionsV1:
        state, task_type, bucket = _task_projection(task_manifest)
        return cls(
            installation_id=session.installation_id,
            project_id=session.project_id,
            provider=session.provider,
            task_type_state=state,
            task_type=task_type,
            task_mix_bucket=bucket,
            task_manifest=task_manifest,
        )

    @model_validator(mode="after")
    def exact_dimensions(self) -> ComparisonStratumDimensionsV1:
        expected_state, expected_type, expected_bucket = _task_projection(
            self.task_manifest
        )
        if (
            self.task_type_state is not expected_state
            or self.task_type is not expected_type
            or self.task_mix_bucket is not expected_bucket
        ):
            raise ValueError("task dimension must derive from the frozen manifest")
        if any(
            item.project_id != self.project_id
            for item in self.task_manifest.current_revisions
        ):
            raise ValueError("reviewed tasks must belong to the exact project")
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)


class ExpectedAnalysisRunVerificationRequestV1(PersistenceRevalidatedModel):
    """Untrusted expected-run request awaiting keyed repository verification."""

    contract_version: Literal[
        EXPECTED_ANALYSIS_RUN_VERIFICATION_REQUEST_V1_VERSION
    ] = EXPECTED_ANALYSIS_RUN_VERIFICATION_REQUEST_V1_VERSION
    authority_receipt_id: str
    analysis_job_id: str
    analysis_job_authority_fingerprint: str
    provider: Provider
    session_id: str
    idempotency_key: str
    metric_pack_key: str
    metric_pack_version: PositiveStrictInt
    expected_analysis_run_id: str
    derivation_inputs_sha256: str
    request_sha256: str
    issued_at: datetime
    idempotency_key_template: Literal["automation-{job_id}"] = "automation-{job_id}"
    run_id_domain: Literal["session-analysis-run-v1"] = "session-analysis-run-v1"
    repository_verification_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_verified: Literal[False] = False
    sealed: Literal[False] = False
    local_keyed_run_id_issuance_required: Literal[True] = True
    caller_digest_not_authority: Literal[True] = True
    comparison_allowed: Literal[False] = False
    synthetic_test_only: Literal[True] = True

    _ids = field_validator(
        "authority_receipt_id",
        "analysis_job_id",
        "analysis_job_authority_fingerprint",
        "session_id",
        "expected_analysis_run_id",
        "derivation_inputs_sha256",
        "request_sha256",
    )(_digest)
    _versions = field_validator("idempotency_key", "metric_pack_key")(_safe_version)
    _issued = field_validator("issued_at")(_utc)

    @staticmethod
    def derivation_for(
        *,
        analysis_job_id: str,
        provider: Provider,
        session_id: str,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> str:
        return _domain_sha256(
            "comparison.automation-analysis-run-derivation-inputs.v1",
            {
                "idempotency_key": f"automation-{analysis_job_id}",
                "metric_pack_key": metric_pack_key,
                "metric_pack_version": str(metric_pack_version),
                "provider": provider.value,
                "run_id_domain": "session-analysis-run-v1",
                "session_id": session_id,
            },
        )

    @staticmethod
    def request_for(
        *,
        authority_receipt_id: str,
        analysis_job_id: str,
        analysis_job_authority_fingerprint: str,
        provider: Provider,
        session_id: str,
        idempotency_key: str,
        metric_pack_key: str,
        metric_pack_version: int,
        expected_analysis_run_id: str,
        derivation_inputs_sha256: str,
        issued_at: datetime,
    ) -> str:
        return _domain_sha256(
            "comparison.expected-analysis-run-verification-request.v1",
            {
                "analysis_job_authority_fingerprint": (
                    analysis_job_authority_fingerprint
                ),
                "analysis_job_id": analysis_job_id,
                "authority_receipt_id": authority_receipt_id,
                "derivation_inputs_sha256": derivation_inputs_sha256,
                "expected_analysis_run_id": expected_analysis_run_id,
                "idempotency_key": idempotency_key,
                "issued_at": issued_at.isoformat(),
                "metric_pack_key": metric_pack_key,
                "metric_pack_version": metric_pack_version,
                "provider": provider.value,
                "session_id": session_id,
            },
        )

    @model_validator(mode="after")
    def exact_verification_request(
        self,
    ) -> ExpectedAnalysisRunVerificationRequestV1:
        if self.provider is not Provider.SYNTHETIC:
            raise ValueError("expected-run V1 is synthetic-test-only")
        if self.idempotency_key != f"automation-{self.analysis_job_id}":
            raise ValueError("expected run must use the code-owned automation key")
        if (
            self.metric_pack_key != COACHING_PROFILE_V1.metric_pack_key
            or self.metric_pack_version != COACHING_PROFILE_V1.metric_pack_version
        ):
            raise ValueError("expected run must use the code-owned metric pack")
        expected = self.derivation_for(
            analysis_job_id=self.analysis_job_id,
            provider=self.provider,
            session_id=self.session_id,
            metric_pack_key=self.metric_pack_key,
            metric_pack_version=self.metric_pack_version,
        )
        if self.derivation_inputs_sha256 != expected:
            raise ValueError("expected-run derivation input fingerprint is not exact")
        expected_request = self.request_for(
            authority_receipt_id=self.authority_receipt_id,
            analysis_job_id=self.analysis_job_id,
            analysis_job_authority_fingerprint=(
                self.analysis_job_authority_fingerprint
            ),
            provider=self.provider,
            session_id=self.session_id,
            idempotency_key=self.idempotency_key,
            metric_pack_key=self.metric_pack_key,
            metric_pack_version=self.metric_pack_version,
            expected_analysis_run_id=self.expected_analysis_run_id,
            derivation_inputs_sha256=self.derivation_inputs_sha256,
            issued_at=self.issued_at,
        )
        if self.request_sha256 != expected_request:
            raise ValueError("expected-run verification request fingerprint is not exact")
        _require_unique_roles(
            authority_receipt_id=self.authority_receipt_id,
            analysis_job_id=self.analysis_job_id,
            analysis_job_authority=self.analysis_job_authority_fingerprint,
            session_id=self.session_id,
            expected_analysis_run_id=self.expected_analysis_run_id,
            derivation_inputs=self.derivation_inputs_sha256,
            request_fingerprint=self.request_sha256,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return self.request_sha256


class _AutomationComparisonLeaseAuthorityV1:
    """Private non-dataclass carrier for ephemeral raw lease credentials."""

    __slots__ = (
        "_job_id",
        "_automation_grant_id",
        "_lease_owner",
        "_lease_token",
    )

    def __init__(
        self,
        *,
        job_id: str,
        automation_grant_id: str,
        lease_owner: str,
        lease_token: str,
    ) -> None:
        object.__setattr__(self, "_job_id", _digest(job_id))
        object.__setattr__(
            self,
            "_automation_grant_id",
            _digest(automation_grant_id),
        )
        object.__setattr__(self, "_lease_owner", _digest(lease_owner))
        object.__setattr__(self, "_lease_token", _digest(lease_token))

    def __setattr__(self, name: str, value: object) -> None:
        del name, value
        raise TypeError("ephemeral comparison lease authority is immutable")

    @property
    def job_id(self) -> str:
        return self._job_id

    @property
    def automation_grant_id(self) -> str:
        return self._automation_grant_id

    def __repr__(self) -> str:
        return (
            "_AutomationComparisonLeaseAuthorityV1("
            f"job_id={self.job_id!r}, "
            f"automation_grant_id={self.automation_grant_id!r}, "
            "lease_secrets=<ephemeral>)"
        )

    def __copy__(self) -> None:
        raise TypeError("ephemeral comparison lease authority cannot be copied")

    def __deepcopy__(self, memo: object) -> None:
        del memo
        raise TypeError("ephemeral comparison lease authority cannot be copied")

    def __reduce_ex__(self, protocol: int) -> None:
        del protocol
        raise TypeError("ephemeral comparison lease authority cannot be serialized")

    def __getstate__(self) -> None:
        raise TypeError("ephemeral comparison lease authority cannot be serialized")

    def model_dump(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ephemeral comparison lease authority cannot be serialized")

    def model_dump_json(self, *_args: object, **_kwargs: object) -> None:
        raise TypeError("ephemeral comparison lease authority cannot be serialized")


def _prepared_role_identities(
    value: PreparedComparisonStratumDraftV1,
) -> dict[str, str | None]:
    scope = value.prepared_scope
    root = scope.history_root
    selection = scope.selection_revision
    job = value.analysis_job
    session = value.session_authority
    grant = value.automation_grant
    manifest = value.dimensions.task_manifest
    task_selection = manifest.selection_request
    expected_run = value.expected_run_request
    roles: dict[str, str | None] = {
        "prepared_stratum_id": value.prepared_stratum_id,
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
        "automation_grant_id": grant.grant_id,
        "automation_grant_fingerprint": grant.fingerprint,
        "automation_grant_scope_fingerprint": value.automation_grant_scope_sha256,
        "analysis_job_id": job.job_id,
        "analysis_job_dedupe_key": job.dedupe_key,
        "analysis_job_authority_fingerprint": job.fingerprint,
        "analysis_job_stored_authority_fingerprint": job.stored_job_fingerprint,
        "analysis_job_lease_authority_fingerprint": (
            job.lease_authority_fingerprint
        ),
        "analysis_job_input_fingerprint": job.identity.input_fingerprint,
        "analysis_job_provenance_fingerprint": job.identity.provenance_fingerprint,
        "expected_run_request_id": expected_run.authority_receipt_id,
        "expected_run_request_fingerprint": expected_run.fingerprint,
        "expected_run_derivation_inputs_fingerprint": (
            expected_run.derivation_inputs_sha256
        ),
        "expected_analysis_run_id": expected_run.expected_analysis_run_id,
        "installation_id": session.installation_id,
        "session_id": session.session_id,
        "session_authority_fingerprint": session.fingerprint,
        "task_selection_request_id": task_selection.selection_request_id,
        "task_selection_request_fingerprint": task_selection.fingerprint,
        "task_selection_claimed_query_evidence_fingerprint": (
            task_selection.claimed_query_evidence_fingerprint
        ),
        "task_manifest_fingerprint": manifest.fingerprint,
        "dimensions_fingerprint": value.dimensions.fingerprint,
        "task_type_policy": value.policies.task_type.sha256,
        "automation_run_binding_policy": (
            value.policies.automation_run_binding.sha256
        ),
        "matching_policy": value.policies.matching.sha256,
        "censoring_policy": value.policies.censoring.sha256,
        "task_mix_policy": value.policies.task_mix.sha256,
        "policy_set_fingerprint": value.policies.fingerprint,
    }
    for index, item in enumerate(manifest.current_revisions):
        roles[f"task_{index}_id"] = item.task_id
        roles[f"task_{index}_fingerprint"] = (
            manifest.ordered_revision_fingerprints[index]
        )
    return roles


class PreparedComparisonStratumDraftV1(PersistenceRevalidatedModel):
    """Structurally valid pre-read draft awaiting repository verification."""

    contract_version: Literal[
        PREPARED_COMPARISON_STRATUM_DRAFT_V1_VERSION
    ] = PREPARED_COMPARISON_STRATUM_DRAFT_V1_VERSION
    prepared_stratum_id: str
    prepared_scope: RepositoryPreparedTemporalScopeV1
    analysis_job: ComparisonAnalysisJobAuthorityV1
    expected_run_request: ExpectedAnalysisRunVerificationRequestV1
    session_authority: ComparisonSessionAuthorityV1
    automation_grant: ComparisonAutomationGrantAuthorityV1
    automation_grant_scope_sha256: str
    dimensions: ComparisonStratumDimensionsV1
    policies: ComparisonPolicySetV1
    prepared_at: datetime
    authority_kind: Literal[
        ComparisonAuthorityKindV1.AUTOMATION_SESSION_QUALITY
    ] = ComparisonAuthorityKindV1.AUTOMATION_SESSION_QUALITY
    repository_time_basis: Literal[REPOSITORY_TEMPORAL_TIME_BASIS_V1] = (
        REPOSITORY_TEMPORAL_TIME_BASIS_V1
    )
    repository_authority_scope: Literal[COMPARISON_AUTHORITY_SCOPE_V1] = (
        COMPARISON_AUTHORITY_SCOPE_V1
    )

    repository_verification_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_authority_verified: Literal[False] = False
    automation_only: Literal[True] = True
    synthetic_test_only: Literal[True] = True
    prospective_only: Literal[True] = True
    task_context_frozen: Literal[True] = True
    sealed: Literal[False] = False
    analysis_execution_local_only: Literal[True] = True
    analysis_remote_requires_fresh_approval: Literal[True] = True

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
    )(_digest)
    _prepared = field_validator("prepared_at")(_utc)

    @model_validator(mode="after")
    def exact_prepared_draft(self) -> PreparedComparisonStratumDraftV1:
        scope = self.prepared_scope
        root = scope.history_root
        selection = scope.selection_revision
        job = self.analysis_job
        identity = job.identity
        session = self.session_authority
        grant = self.automation_grant
        dimensions = self.dimensions
        expected_run = self.expected_run_request
        if self.policies != comparison_policy_set_v1():
            raise ValueError("prepared stratum requires the exact code-owned policies")
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
            raise ValueError("prepared draft requires the exact run verification request")
        if any(
            provider is not Provider.SYNTHETIC
            for provider in (identity.provider, session.provider, grant.scope.provider)
        ):
            raise ValueError("comparison-stratum V1 is synthetic-test-only")
        if (
            scope.automation_grant_id != grant.grant_id
            or scope.automation_grant_revision != grant.revision
            or scope.automation_grant_fingerprint != grant.fingerprint
            or identity.automation_grant_id != grant.grant_id
        ):
            raise ValueError("prepared stratum must bind the exact grant revision")
        expected_grant_scope = automation_grant_scope_fingerprint(grant.scope)
        if self.automation_grant_scope_sha256 != expected_grant_scope:
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
            raise ValueError("task, session, job, grant and selection scope must agree")
        if (
            identity.provider_schema_version != session.source_schema_version
            or dimensions.installation_id != session.installation_id
            or dimensions.project_id != session.project_id
            or dimensions.provider is not session.provider
            or dimensions.task_manifest.session_id != session.session_id
            or dimensions.task_manifest.cutoff_at != self.prepared_at
        ):
            raise ValueError("prepared dimensions must derive from the exact session")
        if (
            self.prepared_at < scope.prepared_at
            or self.prepared_at < job.created_at
            or job.lease_verified_at != self.prepared_at
            or grant.observed_active_at != self.prepared_at
        ):
            raise ValueError("comparison stratum must be prepared prospectively")
        _require_unique_roles(
            **_prepared_role_identities(self),
            prepared_stratum_fingerprint=_model_sha256(self),
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)

    @property
    def expected_analysis_run_id(self) -> str:
        return self.expected_run_request.expected_analysis_run_id


def session_analysis_run_authority_fingerprint(
    record: SessionAnalysisRunRecord,
) -> str:
    return _domain_sha256(
        "comparison.session-analysis-run-authority.v1",
        record.model_dump(mode="json"),
    )


class AutomationRevalidationRequestV1(PersistenceRevalidatedModel):
    """Untrusted seal-time job/grant projection awaiting repository verification."""

    contract_version: Literal[
        AUTOMATION_REVALIDATION_REQUEST_V1_VERSION
    ] = AUTOMATION_REVALIDATION_REQUEST_V1_VERSION
    authority_receipt_id: str
    prepared_stratum_id: str
    prepared_stratum_fingerprint: str
    analysis_job_id: str
    analysis_job_record_authority_fingerprint: str
    current_job_state: AnalysisJobState
    current_job_lease_authority_fingerprint: str
    current_job_lease_expires_at: datetime
    automation_grant_id: str
    current_grant_revision: PositiveStrictInt
    current_grant_authority_fingerprint: str
    current_grant_expires_at: datetime
    reverified_at: datetime
    repository_revalidation_authority_fingerprint: str
    authority_sha256: str
    current_grant_state: Literal[AutomationGrantState.ACTIVE] = (
        AutomationGrantState.ACTIVE
    )
    repository_verification_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_verified: Literal[False] = False
    current_rows_rehydrated: Literal[False] = False
    ephemeral_lease_proof_verified_not_persisted: Literal[False] = False
    lease_secrets_persisted: Literal[False] = False
    synthetic_test_only: Literal[True] = True

    _ids = field_validator(
        "authority_receipt_id",
        "prepared_stratum_id",
        "prepared_stratum_fingerprint",
        "analysis_job_id",
        "analysis_job_record_authority_fingerprint",
        "current_job_lease_authority_fingerprint",
        "automation_grant_id",
        "current_grant_authority_fingerprint",
        "repository_revalidation_authority_fingerprint",
        "authority_sha256",
    )(_digest)
    _times = field_validator(
        "current_job_lease_expires_at",
        "current_grant_expires_at",
        "reverified_at",
    )(_utc)

    @staticmethod
    def authority_for(
        *,
        authority_receipt_id: str,
        prepared_stratum_id: str,
        prepared_stratum_fingerprint: str,
        analysis_job_id: str,
        analysis_job_record_authority_fingerprint: str,
        current_job_state: AnalysisJobState,
        current_job_lease_authority_fingerprint: str,
        current_job_lease_expires_at: datetime,
        automation_grant_id: str,
        current_grant_revision: int,
        current_grant_authority_fingerprint: str,
        current_grant_expires_at: datetime,
        reverified_at: datetime,
        repository_revalidation_authority_fingerprint: str,
    ) -> str:
        return _domain_sha256(
            "comparison.automation-revalidation-request.v1",
            {
                "analysis_job_id": analysis_job_id,
                "analysis_job_record_authority_fingerprint": (
                    analysis_job_record_authority_fingerprint
                ),
                "authority_receipt_id": authority_receipt_id,
                "automation_grant_id": automation_grant_id,
                "current_grant_authority_fingerprint": (
                    current_grant_authority_fingerprint
                ),
                "current_grant_expires_at": current_grant_expires_at.isoformat(),
                "current_grant_revision": current_grant_revision,
                "current_grant_state": AutomationGrantState.ACTIVE.value,
                "current_job_lease_authority_fingerprint": (
                    current_job_lease_authority_fingerprint
                ),
                "current_job_lease_expires_at": (
                    current_job_lease_expires_at.isoformat()
                ),
                "current_job_state": current_job_state.value,
                "prepared_stratum_fingerprint": prepared_stratum_fingerprint,
                "prepared_stratum_id": prepared_stratum_id,
                "repository_revalidation_authority_fingerprint": (
                    repository_revalidation_authority_fingerprint
                ),
                "reverified_at": reverified_at.isoformat(),
            },
        )

    @model_validator(mode="after")
    def exact_revalidation_request(self) -> AutomationRevalidationRequestV1:
        if self.current_job_state not in ACTIVE_ANALYSIS_JOB_STATES:
            raise ValueError("seal revalidation requires a currently active job")
        if self.reverified_at >= self.current_job_lease_expires_at:
            raise ValueError("job lease must be live at requested revalidation time")
        if self.reverified_at >= self.current_grant_expires_at:
            raise ValueError("grant must be live at requested revalidation time")
        expected = self.authority_for(
            authority_receipt_id=self.authority_receipt_id,
            prepared_stratum_id=self.prepared_stratum_id,
            prepared_stratum_fingerprint=self.prepared_stratum_fingerprint,
            analysis_job_id=self.analysis_job_id,
            analysis_job_record_authority_fingerprint=(
                self.analysis_job_record_authority_fingerprint
            ),
            current_job_state=self.current_job_state,
            current_job_lease_authority_fingerprint=(
                self.current_job_lease_authority_fingerprint
            ),
            current_job_lease_expires_at=self.current_job_lease_expires_at,
            automation_grant_id=self.automation_grant_id,
            current_grant_revision=self.current_grant_revision,
            current_grant_authority_fingerprint=(
                self.current_grant_authority_fingerprint
            ),
            current_grant_expires_at=self.current_grant_expires_at,
            reverified_at=self.reverified_at,
            repository_revalidation_authority_fingerprint=(
                self.repository_revalidation_authority_fingerprint
            ),
        )
        if self.authority_sha256 != expected:
            raise ValueError("automation revalidation request fingerprint is not exact")
        _require_unique_roles(
            authority_receipt_id=self.authority_receipt_id,
            prepared_stratum_id=self.prepared_stratum_id,
            prepared_stratum_fingerprint=self.prepared_stratum_fingerprint,
            analysis_job_id=self.analysis_job_id,
            analysis_job_record_authority=(
                self.analysis_job_record_authority_fingerprint
            ),
            current_job_lease_authority=(
                self.current_job_lease_authority_fingerprint
            ),
            automation_grant_id=self.automation_grant_id,
            current_grant_authority=self.current_grant_authority_fingerprint,
            repository_revalidation_authority=(
                self.repository_revalidation_authority_fingerprint
            ),
            receipt_fingerprint=self.authority_sha256,
        )
        return self

    @property
    def fingerprint(self) -> str:
        return self.authority_sha256


def _sealed_role_identities(
    value: SealedComparisonStratumDraftV1,
) -> dict[str, str | None]:
    roles = _prepared_role_identities(value.prepared_stratum)
    sealed_batch = value.sealed_batch
    request = sealed_batch.completion_request
    analysis_input = request.analysis_input
    draft = sealed_batch.seal_draft
    revision = draft.session_revision
    observation_batch = draft.observation_batch
    revalidation = value.automation_revalidation_request
    roles.update(
        {
            "prepared_stratum_fingerprint": value.prepared_stratum.fingerprint,
            "sealed_stratum_id": value.sealed_stratum_id,
            "analysis_run_authority_fingerprint": (
                value.analysis_run_authority_sha256
            ),
            "completion_request_id": request.completion_request_id,
            "completion_request_fingerprint": request.fingerprint,
            "analysis_input_receipt_id": analysis_input.input_receipt_id,
            "analysis_input_receipt_fingerprint": analysis_input.fingerprint,
            "analysis_input_provenance_fingerprint": (
                analysis_input.provenance_fingerprint
            ),
            "analysis_run_fingerprint": analysis_input.analysis_run_fingerprint,
            "analysis_run_request_fingerprint": (
                analysis_input.analysis_run_request_fingerprint
            ),
            "analysis_window_fingerprint": (
                analysis_input.analysis_window_fingerprint
            ),
            "selected_manifest_root": (
                analysis_input.selected_window_manifest_root
            ),
            "selected_manifest_identity": (
                analysis_input.selected_window_manifest_identity_fingerprint
            ),
            "observed_manifest_root": (
                analysis_input.post_floor_observed_allowlisted_source_manifest_root
            ),
            "observed_manifest_identity": (
                analysis_input.post_floor_observed_allowlisted_source_manifest_identity_fingerprint
            ),
            "analysis_profile_fingerprint": analysis_input.analysis_profile_sha256,
            "metric_engine_fingerprint": analysis_input.metric_engine_sha256,
            "consent_receipt_id": analysis_input.consent_receipt_id,
            "consent_receipt_fingerprint": (
                analysis_input.consent_receipt_fingerprint
            ),
            "redactor_fingerprint": analysis_input.redactor_sha256,
            "preprocessing_fingerprint": analysis_input.preprocessing_sha256,
            "router_fingerprint": analysis_input.router_sha256,
            "run_plan_fingerprint": analysis_input.model_plan_fingerprint,
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
            "seal_draft_id": draft.seal_draft_id,
            "seal_draft_fingerprint": draft.fingerprint,
            "repository_verifier_fingerprint": (
                draft.requested_repository_verifier_fingerprint
            ),
            "sealed_batch_id": sealed_batch.sealed_batch_id,
            "sealed_batch_fingerprint": value.sealed_batch_sha256,
            "automation_revalidation_request_id": (
                revalidation.authority_receipt_id
            ),
            "automation_revalidation_request_fingerprint": (
                revalidation.fingerprint
            ),
            "repository_revalidation_authority_fingerprint": (
                revalidation.repository_revalidation_authority_fingerprint
            ),
        }
    )
    for index, observation in enumerate(observation_batch.observations):
        roles[f"observation_{index}_id"] = observation.observation_id
        roles[f"observation_{index}_fingerprint"] = observation.fingerprint
        roles[f"comparison_identity_{index}_fingerprint"] = (
            observation.comparison_identity.fingerprint
        )
    return roles


class SealedComparisonStratumDraftV1(PersistenceRevalidatedModel):
    """Untrusted exact-run/batch draft; it is deliberately not a seal."""

    contract_version: Literal[
        SEALED_COMPARISON_STRATUM_DRAFT_V1_VERSION
    ] = SEALED_COMPARISON_STRATUM_DRAFT_V1_VERSION
    sealed_stratum_id: str
    prepared_stratum: PreparedComparisonStratumDraftV1
    prepared_stratum_sha256: str
    analysis_run: SessionAnalysisRunRecord
    analysis_run_authority_sha256: str
    sealed_batch: RepositorySealedTemporalBatchV1
    sealed_batch_sha256: str
    ordered_authority_fingerprints: tuple[str, ...] = Field(
        min_length=MAX_SEALED_AUTHORITY_FINGERPRINTS,
        max_length=MAX_SEALED_AUTHORITY_FINGERPRINTS,
    )
    sealed_at: datetime
    automation_revalidation_request: AutomationRevalidationRequestV1
    repository_time_basis: Literal[REPOSITORY_TEMPORAL_TIME_BASIS_V1] = (
        REPOSITORY_TEMPORAL_TIME_BASIS_V1
    )
    repository_authority_scope: Literal[COMPARISON_AUTHORITY_SCOPE_V1] = (
        COMPARISON_AUTHORITY_SCOPE_V1
    )

    repository_verification_required: Literal[True] = True
    structurally_constructible_not_capability: Literal[True] = True
    repository_owned: Literal[False] = False
    repository_authority_verified: Literal[False] = False
    run_authority_verified: Literal[False] = False
    batch_authority_verified: Literal[False] = False
    automation_only: Literal[True] = True
    synthetic_test_only: Literal[True] = True
    prospective_only: Literal[True] = True
    task_context_frozen: Literal[True] = True
    sealed: Literal[False] = False

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
        "prepared_stratum_sha256",
        "analysis_run_authority_sha256",
        "sealed_batch_sha256",
    )(_digest)
    _sealed = field_validator("sealed_at")(_utc)

    @field_validator("ordered_authority_fingerprints")
    @classmethod
    def exact_fingerprint_sequence(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if len(set(checked)) != len(checked):
            raise ValueError("ordered authority fingerprints must be unique")
        return checked

    @classmethod
    def ordered_authority_for(
        cls,
        prepared: PreparedComparisonStratumDraftV1,
        analysis_run: SessionAnalysisRunRecord,
        sealed_batch: RepositorySealedTemporalBatchV1,
        automation_revalidation_request: AutomationRevalidationRequestV1,
    ) -> tuple[str, ...]:
        checked_prepared = PreparedComparisonStratumDraftV1.revalidate_for_persistence(
            prepared
        )
        checked_run = SessionAnalysisRunRecord.model_validate(
            analysis_run.model_dump(mode="python")
        )
        checked_batch = RepositorySealedTemporalBatchV1.revalidate_for_persistence(
            sealed_batch
        )
        checked_revalidation = (
            AutomationRevalidationRequestV1.revalidate_for_persistence(
                automation_revalidation_request
            )
        )
        return (
            checked_prepared.prepared_scope.fingerprint,
            checked_prepared.analysis_job.fingerprint,
            checked_prepared.session_authority.fingerprint,
            checked_prepared.automation_grant.fingerprint,
            checked_prepared.dimensions.task_manifest.selection_request.fingerprint,
            checked_prepared.dimensions.task_manifest.fingerprint,
            checked_prepared.policies.fingerprint,
            checked_prepared.expected_run_request.fingerprint,
            checked_prepared.fingerprint,
            session_analysis_run_authority_fingerprint(checked_run),
            checked_batch.fingerprint,
            checked_revalidation.fingerprint,
        )

    @model_validator(mode="after")
    def exact_seal_draft(self) -> SealedComparisonStratumDraftV1:
        prepared = self.prepared_stratum
        run = self.analysis_run
        draft = run.draft
        batch = self.sealed_batch
        analysis_input = batch.completion_request.analysis_input
        revalidation = self.automation_revalidation_request
        job = prepared.analysis_job.identity
        session = prepared.session_authority
        selection = prepared.prepared_scope.selection_revision
        if self.prepared_stratum_sha256 != prepared.fingerprint:
            raise ValueError("seal draft must bind the exact preparation draft")
        expected_run_fingerprint = session_analysis_run_authority_fingerprint(run)
        if self.analysis_run_authority_sha256 != expected_run_fingerprint:
            raise ValueError("seal draft must bind the exact stored run projection")
        if self.sealed_batch_sha256 != batch.fingerprint:
            raise ValueError("seal draft must bind the exact temporal batch")
        if run.status is not AnalysisRunStatus.COMPLETED or run.finished_at is None:
            raise ValueError("seal draft requires a completed analysis run")
        if (
            draft.run_id
            != prepared.expected_run_request.expected_analysis_run_id
            or draft.run_id != analysis_input.analysis_run_id
            or draft.run_id != batch.seal_draft.analysis_run_id
        ):
            raise ValueError("seal draft rejects retrospective run attachment")
        if (
            batch.completion_request.prepared_scope != prepared.prepared_scope
            or batch.prepared_scope_fingerprint != prepared.prepared_scope.fingerprint
        ):
            raise ValueError("sealed batch must descend from the prepared temporal scope")
        if (
            draft.provider is not Provider.SYNTHETIC
            or analysis_input.provider is not Provider.SYNTHETIC
            or draft.provider is not job.provider
            or draft.provider is not session.provider
            or draft.session_id != job.session_id
            or draft.session_id != session.session_id
            or analysis_input.session_id != session.session_id
            or analysis_input.project_id != session.project_id
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
            or analysis_input.selected_metric_keys != draft.selected_metric_keys
        ):
            raise ValueError("sealed run must retain the exact automation metric scope")
        run_input_lineage = (
            (draft.request_fingerprint, analysis_input.analysis_run_request_fingerprint),
            (draft.analysis_profile_key, analysis_input.analysis_profile_key),
            (draft.analysis_profile_version, analysis_input.analysis_profile_version),
            (draft.metric_pack_key, analysis_input.metric_pack_key),
            (draft.metric_pack_version, analysis_input.metric_pack_version),
            (draft.consent_policy_version, analysis_input.consent_policy_version),
            (draft.provider_version, analysis_input.provider_version),
            (draft.adapter_version, analysis_input.provider_adapter_version),
            (draft.source_schema_version, analysis_input.source_schema_version),
            (draft.content_schema_version, analysis_input.content_schema_version),
            (draft.metric_engine_version, analysis_input.metric_engine_version),
            (draft.redactor_version, analysis_input.redactor_version),
            (draft.model_plan_fingerprint, analysis_input.model_plan_fingerprint),
            (draft.schema_version, analysis_input.analysis_run_schema_version),
            (run.finished_at, analysis_input.analysis_run_completed_at),
        )
        if any(left != right for left, right in run_input_lineage):
            raise ValueError("stored run conflicts with temporal input provenance")
        if (
            draft.provider_version != session.provider_version
            or draft.adapter_version != session.adapter_version
            or draft.source_schema_version != session.source_schema_version
            or draft.source_schema_version != job.provider_schema_version
            or draft.redactor_version != job.redactor_version
            or draft.data_tier is not DataTier.REDACTED_CONTENT
            or not draft.local_only
        ):
            raise ValueError("stored run conflicts with session or job provenance")
        if draft.started_at < prepared.prepared_at:
            raise ValueError("an existing run cannot be retrospectively attached")
        if self.sealed_at < run.finished_at or self.sealed_at < batch.sealed_at:
            raise ValueError("comparison seal draft cannot predate its run or batch")
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
            raise ValueError("automation authority must be live at draft time")
        expected_order = self.ordered_authority_for(
            prepared,
            run,
            batch,
            revalidation,
        )
        if self.ordered_authority_fingerprints != expected_order:
            raise ValueError("comparison seal draft must commit the exact graph")
        _require_unique_roles(
            **_sealed_role_identities(self),
            sealed_stratum_fingerprint=_model_sha256(self),
        )
        return self

    @property
    def fingerprint(self) -> str:
        return _model_sha256(self)


class TemporalComparisonStratumRepositoryV1(Protocol):
    """Future issuance seam; this application-only slice returns drafts only."""

    def draft_automation_stratum(
        self,
        prepared_scope_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> PreparedComparisonStratumDraftV1: ...

    def draft_automation_seal(
        self,
        prepared_stratum_id: str,
        sealed_batch_id: str,
        *,
        authority: _AutomationComparisonLeaseAuthorityV1,
    ) -> SealedComparisonStratumDraftV1: ...

    def get_prepared_stratum_draft(
        self, prepared_stratum_id: str
    ) -> PreparedComparisonStratumDraftV1 | None: ...

    def get_prepared_stratum_draft_for_job(
        self, job_id: str
    ) -> PreparedComparisonStratumDraftV1 | None: ...

    def get_sealed_stratum_draft(
        self, sealed_stratum_id: str
    ) -> SealedComparisonStratumDraftV1 | None: ...

    def get_sealed_stratum_draft_for_run(
        self, analysis_run_id: str
    ) -> SealedComparisonStratumDraftV1 | None: ...

    def get_sealed_stratum_draft_for_batch(
        self, sealed_batch_id: str
    ) -> SealedComparisonStratumDraftV1 | None: ...


__all__ = [
    "AUTOMATION_RUN_BINDING_POLICY_V1_VERSION",
    "CENSORING_POLICY_V1_VERSION",
    "COMPARISON_AUTHORITY_SCOPE_V1",
    "COMPARISON_POLICY_SET_V1_VERSION",
    "ComparisonAnalysisJobAuthorityV1",
    "ComparisonAuthorityKindV1",
    "ComparisonAutomationGrantAuthorityV1",
    "ComparisonCensoringReadinessV1",
    "ComparisonDimensionStateV1",
    "ComparisonMatchReadinessV1",
    "ComparisonPolicyIdentityV1",
    "ComparisonPolicyKindV1",
    "ComparisonPolicySetV1",
    "ComparisonSessionAuthorityV1",
    "ComparisonStratumDimensionsV1",
    "ComparisonTaskMixBucketV1",
    "ComparisonTaskTypeStateV1",
    "ComparisonTaskTypeV1",
    "MATCHING_POLICY_V1_VERSION",
    "MAX_COMPARISON_CURRENT_TASKS",
    "PREPARED_COMPARISON_STRATUM_DRAFT_V1_VERSION",
    "SEALED_COMPARISON_STRATUM_DRAFT_V1_VERSION",
    "PreparedComparisonStratumDraftV1",
    "AutomationRevalidationRequestV1",
    "ExpectedAnalysisRunVerificationRequestV1",
    "ReviewedTaskSelectionVerificationRequestV1",
    "SealedComparisonStratumDraftV1",
    "ReviewedTaskManifestV1",
    "ReviewedTaskTargetProjectionV1",
    "TASK_MIX_POLICY_V1_VERSION",
    "TASK_TYPE_POLICY_V1_VERSION",
    "TemporalComparisonStratumRepositoryV1",
    "automation_grant_scope_fingerprint",
    "comparison_policy_set_v1",
    "select_current_reviewed_tasks_as_of",
    "session_analysis_run_authority_fingerprint",
]
