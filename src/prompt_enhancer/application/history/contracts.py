"""Content-free contracts for prospective temporal metric history.

These contracts deliberately do not infer revisions, metric selection, or values
from legacy rows.  A temporal series starts at a declared history floor and is
built only from immutable, directly observed receipts at or after that floor.

The models contain opaque digests, closed enums, bounded numbers, and short
path-free codes only.  Prompts, evidence text, model commentary, source paths,
URIs, and user-authored labels are outside this boundary.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import math
import re
from typing import Annotated, Any, Literal, Protocol, TypeVar

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import DataTier, PSEUDONYM_PATTERN, Provider, StrictModel


TEMPORAL_HISTORY_CONTRACT_VERSION = "temporal-history-v1"
TEMPORAL_HISTORY_ROOT_RECEIPT_VERSION = "temporal-history-root-receipt-v1"
PROJECT_METRIC_SELECTION_REVISION_VERSION = "project-metric-selection-revision-v1"
PROJECT_METRIC_SELECTION_REVISION_V2_VERSION = "project-metric-selection-revision-v2"
ANALYSIS_INPUT_RECEIPT_VERSION = "analysis-input-receipt-v1"
ANALYSIS_INPUT_RECEIPT_V2_VERSION = "analysis-input-receipt-v2"
APPEND_PREFIX_PROOF_RECEIPT_VERSION = "append-prefix-proof-receipt-v1"
SESSION_REVISION_RECEIPT_VERSION = "session-revision-receipt-v2"
SESSION_REVISION_RECEIPT_V3_VERSION = "session-revision-receipt-v3"
TEMPORAL_OBSERVATION_BATCH_VERSION = "temporal-observation-batch-v1"
TEMPORAL_METRIC_OBSERVATION_V2_VERSION = "temporal-metric-observation-v2"
TEMPORAL_OBSERVATION_BATCH_V2_VERSION = "temporal-observation-batch-v2"
REPOSITORY_TEMPORAL_BATCH_SEAL_DRAFT_VERSION = (
    "repository-temporal-batch-seal-draft-v1"
)
TEMPORAL_COMPLETION_PROJECTION_VERSION = "temporal-completion-projection-v1"
TEMPORAL_SNAPSHOT_SPEC_VERSION = "temporal-snapshot-spec-v1"
TEMPORAL_SNAPSHOT_RECEIPT_VERSION = "temporal-snapshot-receipt-v1"
COMPATIBILITY_BOUNDARY_VERSION = "compatibility-boundary-v1"
HALF_OPEN_WINDOW_BOUNDARY = "half_open_start_inclusive_end_exclusive"
KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION = (
    "keyed-selected-redacted-message-window-v1"
)
SELECTED_WINDOW_MANIFEST_VERSION = "selected-window-manifest-v1"
POST_FLOOR_OBSERVED_ALLOWLISTED_SOURCE_MANIFEST_VERSION = (
    "post-floor-observed-allowlisted-source-manifest-v1"
)

MAX_LAST_N = 10_000
MAX_METRICS = 100
MAX_OBSERVATIONS = 100
MAX_COUNT = 9_007_199_254_740_991

_SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SAFE_VERSION_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")

NonNegativeInt = Annotated[int, Field(strict=True, ge=0, le=MAX_COUNT)]
PositiveInt = Annotated[int, Field(strict=True, ge=1, le=MAX_COUNT)]
PersistenceModel = TypeVar("PersistenceModel", bound=StrictModel)


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_code(value: str) -> str:
    if _SAFE_CODE_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a lowercase path-free content code")
    return value


def _optional_code(value: str | None) -> str | None:
    return None if value is None else _safe_code(value)


def _safe_version(value: str) -> str:
    if _SAFE_VERSION_PATTERN.fullmatch(value) is None or ".." in value:
        raise ValueError("value must be a path-free, URI-free version identifier")
    return value


def _optional_version(value: str | None) -> str | None:
    return None if value is None else _safe_version(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be canonical UTC")
    return value


def _finite(value: Any, *, field_name: str, nonnegative: bool = False) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{field_name} must be a JSON number")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{field_name} must be finite")
    if nonnegative and number < 0:
        raise ValueError(f"{field_name} must be non-negative")
    if number == 0 and math.copysign(1.0, number) < 0:
        raise ValueError(f"{field_name} cannot be negative zero")
    return number


def _probability(value: Any, *, field_name: str) -> float:
    number = _finite(value, field_name=field_name, nonnegative=True)
    if number > 1:
        raise ValueError(f"{field_name} must be between zero and one")
    return number


def _canonical_codes(
    values: tuple[str, ...], *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not allow_empty and not values:
        raise ValueError("code set may not be empty")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("codes must be unique and sorted")
    return tuple(_safe_code(value) for value in values)


def _canonical_digests(
    values: tuple[str, ...], *, allow_empty: bool = False
) -> tuple[str, ...]:
    if not allow_empty and not values:
        raise ValueError("digest set may not be empty")
    if values != tuple(sorted(values)) or len(values) != len(set(values)):
        raise ValueError("digests must be unique and sorted")
    return tuple(_digest(value) for value in values)


def _canonical_digest(model: StrictModel) -> str:
    payload = json.dumps(
        model.model_dump(mode="json"),
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _manifest_identity_fingerprint(
    *, role: str, root: str, version: str, entry_count: int
) -> str:
    """Domain-separate a manifest root, schema, and cardinality commitment."""

    payload = json.dumps(
        {
            "entry_count": entry_count,
            "role": role,
            "root": root,
            "version": version,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _predecessor_link_fingerprint(
    *,
    predecessor_revision_id: str,
    predecessor_revision_fingerprint: str,
    successor_ordinal: int,
    root_receipt_id: str,
    project_id: str,
    session_id: str,
) -> str:
    payload = json.dumps(
        {
            "predecessor_revision_fingerprint": predecessor_revision_fingerprint,
            "predecessor_revision_id": predecessor_revision_id,
            "project_id": project_id,
            "root_receipt_id": root_receipt_id,
            "session_id": session_id,
            "successor_ordinal": successor_ordinal,
        },
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _plain_persistence_value(value: Any) -> Any:
    """Recursively discard trusted model instances before boundary validation."""

    if isinstance(value, StrictModel):
        return {
            field_name: _plain_persistence_value(getattr(value, field_name))
            for field_name in type(value).model_fields
        }
    if isinstance(value, dict):
        return {
            key: _plain_persistence_value(nested)
            for key, nested in value.items()
        }
    if isinstance(value, (tuple, list)):
        return tuple(_plain_persistence_value(nested) for nested in value)
    return value


def _revalidate_persistence_model(
    model_type: type[PersistenceModel], value: Any
) -> PersistenceModel:
    return model_type.model_validate(_plain_persistence_value(value))


class PersistenceRevalidatedModel(StrictModel):
    """Fail closed when nested frozen models cross a persistence boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    @model_validator(mode="before")
    @classmethod
    def recursively_revalidate_nested_models(cls, value: Any) -> Any:
        return _plain_persistence_value(value)

    @classmethod
    def revalidate_for_persistence(cls, value: Any) -> Any:
        """Revalidate plain values at every persistence read/write boundary."""

        return _revalidate_persistence_model(cls, value)


class TemporalWindowKind(StrEnum):
    LAST_N = "last_n"
    ROLLING_DAYS = "rolling_days"
    CUSTOM = "custom"


class HistoryCoverageState(StrEnum):
    COMPLETE = "complete"
    LEFT_CENSORED = "left_censored"
    PARTIAL = "partial"
    LEFT_CENSORED_PARTIAL = "left_censored_partial"
    NO_POST_FLOOR_OBSERVATIONS = "no_post_floor_observations"


class RevisionEffectiveTimeBasis(StrEnum):
    SESSION_ENDED_AT = "session_ended_at"
    REVISION_CAPTURED_AT = "revision_captured_at"


class HistoryFloorSource(StrEnum):
    SERVER_CLOCK = "server_clock"


class ProjectMetricSelectionSource(StrEnum):
    EXPLICIT_PROJECT_CONFIGURATION = "explicit_project_configuration"
    AUTOMATION_GRANT = "automation_grant"
    SYSTEM_INITIALIZATION = "system_initialization"


class ProjectMetricSelectionAuthorityKind(StrEnum):
    PROJECT_CONFIGURATION = "project_configuration"
    AUTOMATION_GRANT = "automation_grant"
    SYSTEM_INITIALIZATION = "system_initialization"


class AnalysisInputCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"


class AnalysisInputExtractionCompleteness(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_APPLICABLE_EMPTY_SOURCE = "not_applicable_empty_source"


class AnalysisInputSelectionCoverage(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    NOT_APPLICABLE_EMPTY_ELIGIBLE_SET = "not_applicable_empty_eligible_set"


class AnalysisInputCaptureSource(StrEnum):
    DOCUMENTED_PROVIDER_ADAPTER = "documented_provider_adapter"


class SessionRevisionRelation(StrEnum):
    FIRST = "first"
    APPEND_PREFIX_PROVED = "append_prefix_proved"
    CHANGED_OR_REORDERED = "changed_or_reordered"
    PROVENANCE_BOUNDARY = "provenance_boundary"


class SessionRevisionRelationV3(StrEnum):
    """Conservative durable relation; append is deliberately unrepresentable."""

    FIRST = "first"
    CHANGED_OR_REORDERED = "changed_or_reordered"
    PROVENANCE_BOUNDARY = "provenance_boundary"


class AppendVerificationState(StrEnum):
    NOT_APPLICABLE = "not_applicable"
    UNTRUSTED_UNTIL_REPOSITORY_VERIFIED = "untrusted_until_repository_verified"


class SessionRevisionProvenance(StrEnum):
    DIRECT_ANALYSIS_WINDOW_RECEIPT = "direct_analysis_window_receipt"


class AnalysisWindowFingerprintBasis(StrEnum):
    CANONICAL_PROVIDER_EVENT_MANIFEST = "canonical_provider_event_manifest"


class AnalysisWindowFingerprintBasisV2(StrEnum):
    KEYED_SELECTED_REDACTED_MESSAGE_WINDOW = (
        "keyed_selected_redacted_message_window"
    )


class EvidenceCoverageEligibility(StrEnum):
    ELIGIBLE = "eligible"
    NOT_ELIGIBLE = "not_eligible"
    UNKNOWN = "unknown"


class EvidenceCoverageState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    NOT_APPLICABLE = "not_applicable"


class TemporalSelectionState(StrEnum):
    SELECTED = "selected"
    NOT_SELECTED = "not_selected"
    SELECTION_UNKNOWN = "selection_unknown"


class TemporalScopeState(StrEnum):
    EXACT_SELECTION_RECEIPT = "exact_selection_receipt"
    NO_SELECTION_RECEIPT = "no_selection_receipt"


class TemporalSourceState(StrEnum):
    PRESENT = "present"
    NOT_REQUESTED = "not_requested"
    NO_POST_FLOOR_SOURCE = "no_post_floor_source"
    SOURCE_MISSING = "source_missing"
    SOURCE_FAILED = "source_failed"
    SOURCE_INCOMPATIBLE = "source_incompatible"


class TemporalValueState(StrEnum):
    KNOWN = "known"
    UNKNOWN = "unknown"
    ABSTAINED = "abstained"
    NOT_APPLICABLE = "not_applicable"
    FAILED = "failed"
    INCOMPATIBLE = "incompatible"


class TemporalValueKind(StrEnum):
    FRACTION = "fraction"
    COUNT_WITH_EXPOSURE = "count_with_exposure"
    DISTRIBUTION_SAMPLE = "distribution_sample"
    SAMPLED_PROPORTION = "sampled_proportion"


class TemporalAggregationSemantics(StrEnum):
    RATIO_OF_SUMS = "ratio_of_sums"
    COUNT_SUM_WITH_EXPOSURE = "count_sum_with_exposure"
    MEDIAN_AND_QUANTILES = "median_and_quantiles"
    PROPORTION_INTERVAL_FROM_SUMS = "proportion_interval_from_sums"


class TemporalTrendMethod(StrEnum):
    NONE = "none"
    ROLLING_MEDIAN = "rolling_median"
    EWMA = "ewma"


class MetricDirection(StrEnum):
    HIGHER_IS_BETTER = "higher_is_better"
    LOWER_IS_BETTER = "lower_is_better"
    NEUTRAL = "neutral"


class EvidenceTier(StrEnum):
    METADATA = "metadata"
    REDACTED_CONTENT = "redacted_content"
    OBJECTIVE_ARTIFACT = "objective_artifact"
    HUMAN_ADJUDICATED = "human_adjudicated"


class EstimatorIdentityKind(StrEnum):
    DETERMINISTIC = "deterministic"
    MODEL_ASSISTED = "model_assisted"


class EstimatorLifecycleState(StrEnum):
    PROVISIONAL = "provisional"
    ACTIVATED = "activated"
    RETIRED = "retired"


class ModelProviderKind(StrEnum):
    LOCAL = "local"
    OPENAI = "openai"
    ANTHROPIC = "anthropic"
    SYNTHETIC = "synthetic"


class ArtifactIdentityState(StrEnum):
    PINNED_SHA256 = "pinned_sha256"
    PROVIDER_MANAGED_UNAVAILABLE = "provider_managed_unavailable"
    SYNTHETIC_NO_ARTIFACT = "synthetic_no_artifact"


class ReasoningEffort(StrEnum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    XHIGH = "xhigh"
    MAX = "max"
    ULTRA = "ultra"


class SnapshotAsOfSource(StrEnum):
    SERVER_CLOCK = "server_clock"


class SnapshotMetricCompatibilityState(StrEnum):
    COMPATIBLE = "compatible"
    DISCONTINUITY = "discontinuity"
    NO_COMPARABLE_OBSERVATIONS = "no_comparable_observations"


class MaterializationTrustState(StrEnum):
    UNTRUSTED_UNTIL_MATERIALIZED = "untrusted_until_materialized"


class CompatibilityDimension(StrEnum):
    METRIC_CONTRACT = "metric_contract"
    VALUE_SEMANTICS = "value_semantics"
    EVIDENCE_CONTRACT = "evidence_contract"
    ESTIMATOR_CONFIGURATION = "estimator_configuration"
    MODEL_IDENTITY = "model_identity"
    CALIBRATION = "calibration"
    PROVIDER_SCHEMA = "provider_schema"
    PRIVACY_REDACTOR = "privacy_redactor"


class TemporalWindowSpec(StrictModel):
    kind: TemporalWindowKind
    window_boundary_semantics: Literal[HALF_OPEN_WINDOW_BOUNDARY] = (
        HALF_OPEN_WINDOW_BOUNDARY
    )
    last_n: int | None = Field(default=None, strict=True, ge=1, le=MAX_LAST_N)
    days: int | None = Field(default=None, strict=True)
    start_at: datetime | None = None
    end_at: datetime | None = None

    @field_validator("start_at", "end_at")
    @classmethod
    def utc_optional(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def exact_shape(self) -> TemporalWindowSpec:
        if self.kind is TemporalWindowKind.LAST_N:
            if self.last_n is None or any(
                value is not None for value in (self.days, self.start_at, self.end_at)
            ):
                raise ValueError("last-N windows require only last_n")
        elif self.kind is TemporalWindowKind.ROLLING_DAYS:
            if self.days not in {7, 30, 90} or any(
                value is not None
                for value in (self.last_n, self.start_at, self.end_at)
            ):
                raise ValueError("rolling windows must be exactly 7, 30, or 90 days")
        elif (
            self.start_at is None
            or self.end_at is None
            or self.start_at >= self.end_at
            or self.last_n is not None
            or self.days is not None
        ):
            raise ValueError("custom windows require only an ordered UTC range")
        return self


class TemporalHistoryRootReceipt(PersistenceRevalidatedModel):
    """Prospective project-history floor issued by the local server clock.

    A root is not a claim about data that predates ``history_floor_at``.  The
    equality between floor and issue time deliberately prevents callers from
    backdating a new history root and presenting legacy rows as observations.
    """

    contract_version: Literal[TEMPORAL_HISTORY_ROOT_RECEIPT_VERSION] = (
        TEMPORAL_HISTORY_ROOT_RECEIPT_VERSION
    )
    root_receipt_id: str
    project_id: str
    epoch_ordinal: PositiveInt
    predecessor_root_id: str | None = None
    predecessor_root_fingerprint: str | None = None
    history_floor_at: datetime
    issued_at: datetime
    floor_source: Literal[HistoryFloorSource.SERVER_CLOCK] = (
        HistoryFloorSource.SERVER_CLOCK
    )
    prospective_capture_only: Literal[True] = True
    legacy_backfill_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("root_receipt_id", "project_id")(_digest)
    _times = field_validator("history_floor_at", "issued_at")(_utc)

    @field_validator("predecessor_root_id", "predecessor_root_fingerprint")
    @classmethod
    def optional_predecessor_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def exact_server_floor(self) -> TemporalHistoryRootReceipt:
        if self.history_floor_at != self.issued_at:
            raise ValueError("a prospective history floor must equal its issue time")
        has_predecessor = self.predecessor_root_id is not None
        if has_predecessor != (self.predecessor_root_fingerprint is not None):
            raise ValueError("history-root predecessor id and fingerprint travel together")
        if self.epoch_ordinal == 1 and has_predecessor:
            raise ValueError("the first history epoch cannot name a predecessor")
        if self.epoch_ordinal > 1 and not has_predecessor:
            raise ValueError("later history epochs require an exact predecessor")
        if self.predecessor_root_id == self.root_receipt_id:
            raise ValueError("a history root cannot be its own predecessor")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ProjectMetricSelectionRevision(PersistenceRevalidatedModel):
    """Immutable, CAS-linked revision of a project's exact metric set."""

    contract_version: Literal[PROJECT_METRIC_SELECTION_REVISION_VERSION] = (
        PROJECT_METRIC_SELECTION_REVISION_VERSION
    )
    selection_revision_id: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    project_id: str
    selection_ordinal: PositiveInt
    compare_and_swap_predecessor_id: str | None = None
    compare_and_swap_predecessor_fingerprint: str | None = None
    selected_metric_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )
    source: ProjectMetricSelectionSource
    effective_at: datetime
    recorded_at: datetime
    direct_receipt_only: Literal[True] = True
    legacy_inference_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "selection_revision_id",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "project_id",
    )(_digest)
    _times = field_validator("effective_at", "recorded_at")(_utc)

    @field_validator(
        "compare_and_swap_predecessor_id",
        "compare_and_swap_predecessor_fingerprint",
    )
    @classmethod
    def optional_predecessor_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("selected_metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(values)

    @model_validator(mode="after")
    def exact_compare_and_swap_shape(self) -> ProjectMetricSelectionRevision:
        has_predecessor = self.compare_and_swap_predecessor_id is not None
        if has_predecessor != (
            self.compare_and_swap_predecessor_fingerprint is not None
        ):
            raise ValueError("CAS predecessor id and fingerprint must be present together")
        if self.selection_ordinal == 1 and has_predecessor:
            raise ValueError("the first metric selection cannot name a predecessor")
        if self.selection_ordinal > 1 and not has_predecessor:
            raise ValueError("later metric selections require an exact CAS predecessor")
        if self.compare_and_swap_predecessor_id == self.selection_revision_id:
            raise ValueError("a metric selection cannot be its own predecessor")
        if self.effective_at > self.recorded_at:
            raise ValueError("metric selection cannot become effective after recording")
        return self

    @property
    def metric_set_fingerprint(self) -> str:
        """Content-free identity of the metric set, not of its revision."""

        return hashlib.sha256(
            json.dumps(
                {
                    "project_id": self.project_id,
                    "selected_metric_keys": self.selected_metric_keys,
                },
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class ProjectMetricSelectionRevisionV2(ProjectMetricSelectionRevision):
    """Metric selection whose identity includes its pack, catalog, and authority.

    Equal metric keys are not an equal selection scope when their defining pack,
    catalog, or authorizing receipt differs.  Repository persistence must still
    verify the root and compare-and-swap predecessor named by this unsealed
    content-free receipt.
    """

    contract_version: Literal[PROJECT_METRIC_SELECTION_REVISION_V2_VERSION] = (
        PROJECT_METRIC_SELECTION_REVISION_V2_VERSION
    )
    metric_pack_key: str
    metric_pack_version: PositiveInt
    metric_pack_sha256: str
    metric_catalog_version: str
    metric_catalog_sha256: str
    source_authority_kind: ProjectMetricSelectionAuthorityKind
    source_authority_id: str
    source_authority_fingerprint: str
    source_authority_version: str
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _v2_digests = field_validator(
        "metric_pack_sha256",
        "metric_catalog_sha256",
        "source_authority_id",
        "source_authority_fingerprint",
    )(_digest)
    _v2_codes = field_validator("metric_pack_key")(_safe_code)
    _v2_versions = field_validator(
        "metric_catalog_version", "source_authority_version"
    )(_safe_version)

    @model_validator(mode="after")
    def exact_source_authority(self) -> ProjectMetricSelectionRevisionV2:
        expected = {
            ProjectMetricSelectionSource.EXPLICIT_PROJECT_CONFIGURATION: (
                ProjectMetricSelectionAuthorityKind.PROJECT_CONFIGURATION
            ),
            ProjectMetricSelectionSource.AUTOMATION_GRANT: (
                ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT
            ),
            ProjectMetricSelectionSource.SYSTEM_INITIALIZATION: (
                ProjectMetricSelectionAuthorityKind.SYSTEM_INITIALIZATION
            ),
        }[self.source]
        if self.source_authority_kind is not expected:
            raise ValueError("selection source and source authority must agree")
        if self.source_authority_id == self.selection_revision_id:
            raise ValueError("selection revision and source authority require distinct ids")
        return self

    @property
    def metric_set_fingerprint(self) -> str:
        """Exact selection scope, including semantic source identities."""

        payload = {
            "metric_catalog_sha256": self.metric_catalog_sha256,
            "metric_catalog_version": self.metric_catalog_version,
            "metric_pack_key": self.metric_pack_key,
            "metric_pack_sha256": self.metric_pack_sha256,
            "metric_pack_version": self.metric_pack_version,
            "project_id": self.project_id,
            "selected_metric_keys": self.selected_metric_keys,
            "source": self.source,
            "source_authority_fingerprint": self.source_authority_fingerprint,
            "source_authority_id": self.source_authority_id,
            "source_authority_kind": self.source_authority_kind,
            "source_authority_version": self.source_authority_version,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()


class AnalysisInputReceipt(PersistenceRevalidatedModel):
    """Content-free receipt for one directly captured selected analysis window."""

    contract_version: Literal[ANALYSIS_INPUT_RECEIPT_VERSION] = (
        ANALYSIS_INPUT_RECEIPT_VERSION
    )
    input_receipt_id: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    selection_revision_id: str
    selection_revision_fingerprint: str
    analysis_run_id: str
    project_id: str
    session_id: str
    selected_metric_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )
    analysis_window_fingerprint: str
    analysis_window_fingerprint_basis: Literal[
        AnalysisWindowFingerprintBasis.CANONICAL_PROVIDER_EVENT_MANIFEST
    ] = AnalysisWindowFingerprintBasis.CANONICAL_PROVIDER_EVENT_MANIFEST
    analysis_window_fingerprint_version: str
    source_manifest_fingerprint: str
    source_manifest_version: str
    source_manifest_entry_count: NonNegativeInt
    captured_source_entry_count: NonNegativeInt
    completeness: AnalysisInputCompleteness
    analysis_window_started_at: datetime
    analysis_window_ended_at: datetime
    captured_at: datetime
    capture_source: Literal[
        AnalysisInputCaptureSource.DOCUMENTED_PROVIDER_ADAPTER
    ] = AnalysisInputCaptureSource.DOCUMENTED_PROVIDER_ADAPTER
    capture_contract_version: str
    provider: Provider
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    redactor_sha256: str
    preprocessing_version: str
    preprocessing_sha256: str
    router_version: str
    router_sha256: str
    direct_selected_window: Literal[True] = True
    legacy_inference_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "input_receipt_id",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "selection_revision_id",
        "selection_revision_fingerprint",
        "analysis_run_id",
        "project_id",
        "session_id",
        "analysis_window_fingerprint",
        "source_manifest_fingerprint",
        "redactor_sha256",
        "preprocessing_sha256",
        "router_sha256",
    )(_digest)
    _versions = field_validator(
        "analysis_window_fingerprint_version",
        "source_manifest_version",
        "capture_contract_version",
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
        "preprocessing_version",
        "router_version",
    )(_safe_version)
    _times = field_validator(
        "analysis_window_started_at", "analysis_window_ended_at", "captured_at"
    )(_utc)

    @field_validator("selected_metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(values)

    @model_validator(mode="after")
    def exact_direct_capture_shape(self) -> AnalysisInputReceipt:
        if self.analysis_window_started_at > self.analysis_window_ended_at:
            raise ValueError("analysis window timestamps must be ordered")
        if self.analysis_window_ended_at > self.captured_at:
            raise ValueError("an analysis window cannot end after capture")
        if self.captured_source_entry_count > self.source_manifest_entry_count:
            raise ValueError("captured source entries cannot exceed the manifest")
        if self.completeness is AnalysisInputCompleteness.COMPLETE:
            if self.captured_source_entry_count != self.source_manifest_entry_count:
                raise ValueError("complete input requires exact source-manifest coverage")
        elif self.captured_source_entry_count >= self.source_manifest_entry_count:
            raise ValueError("partial input requires a visible source-manifest omission")
        return self

    @property
    def provenance_fingerprint(self) -> str:
        """Identity boundary for adapter/source/content/redactor compatibility."""

        payload = {
            "analysis_window_fingerprint_basis": self.analysis_window_fingerprint_basis,
            "analysis_window_fingerprint_version": (
                self.analysis_window_fingerprint_version
            ),
            "capture_contract_version": self.capture_contract_version,
            "capture_source": self.capture_source,
            "content_schema_version": self.content_schema_version,
            "provider": self.provider,
            "provider_adapter_version": self.provider_adapter_version,
            "provider_schema_version": self.provider_schema_version,
            "preprocessing_sha256": self.preprocessing_sha256,
            "preprocessing_version": self.preprocessing_version,
            "redactor_version": self.redactor_version,
            "redactor_sha256": self.redactor_sha256,
            "router_sha256": self.router_sha256,
            "router_version": self.router_version,
            "source_manifest_version": self.source_manifest_version,
            "source_schema_version": self.source_schema_version,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AnalysisInputReceiptV2(PersistenceRevalidatedModel):
    """Truthful, content-free receipt for a complete selected analysis run.

    The selected redacted-message window and the post-floor allowlisted source
    population are separate manifests.  Extraction completeness and selection
    coverage are also separate axes: a complete selection cannot conceal an
    incomplete provider extraction, and an empty denominator is explicit rather
    than silently treated as full coverage.
    """

    contract_version: Literal[ANALYSIS_INPUT_RECEIPT_V2_VERSION] = (
        ANALYSIS_INPUT_RECEIPT_V2_VERSION
    )
    input_receipt_id: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    selection_revision_id: str
    selection_revision_fingerprint: str
    selection_scope_fingerprint: str
    analysis_run_id: str
    analysis_run_fingerprint: str
    analysis_run_fingerprint_version: str
    analysis_run_request_fingerprint: str
    project_id: str
    session_id: str
    selected_metric_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )

    analysis_window_fingerprint: str
    analysis_window_fingerprint_basis: Literal[
        AnalysisWindowFingerprintBasisV2.KEYED_SELECTED_REDACTED_MESSAGE_WINDOW
    ] = AnalysisWindowFingerprintBasisV2.KEYED_SELECTED_REDACTED_MESSAGE_WINDOW
    analysis_window_fingerprint_version: Literal[
        KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION
    ] = KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION

    selected_window_manifest_root: str
    selected_window_manifest_version: Literal[SELECTED_WINDOW_MANIFEST_VERSION] = (
        SELECTED_WINDOW_MANIFEST_VERSION
    )
    selected_window_manifest_entry_count: NonNegativeInt
    selected_window_manifest_identity_fingerprint: str
    post_floor_observed_allowlisted_source_manifest_root: str
    post_floor_observed_allowlisted_source_manifest_version: Literal[
        POST_FLOOR_OBSERVED_ALLOWLISTED_SOURCE_MANIFEST_VERSION
    ] = POST_FLOOR_OBSERVED_ALLOWLISTED_SOURCE_MANIFEST_VERSION
    post_floor_observed_allowlisted_source_manifest_entry_count: NonNegativeInt
    post_floor_observed_allowlisted_source_manifest_identity_fingerprint: str
    successfully_extracted_source_entry_count: NonNegativeInt
    selection_eligible_entry_count: NonNegativeInt
    extraction_completeness: AnalysisInputExtractionCompleteness
    selection_coverage: AnalysisInputSelectionCoverage

    analysis_window_started_at: datetime
    analysis_window_ended_at: datetime
    analysis_run_completed_at: datetime
    captured_at: datetime
    capture_source: Literal[
        AnalysisInputCaptureSource.DOCUMENTED_PROVIDER_ADAPTER
    ] = AnalysisInputCaptureSource.DOCUMENTED_PROVIDER_ADAPTER
    capture_contract_version: str

    analysis_profile_key: str
    analysis_profile_version: PositiveInt
    analysis_profile_sha256: str
    metric_pack_key: str
    metric_pack_version: PositiveInt
    metric_pack_sha256: str
    metric_engine_version: str
    metric_engine_sha256: str
    metric_catalog_version: str
    metric_catalog_sha256: str
    data_tier: Literal[DataTier.REDACTED_CONTENT] = DataTier.REDACTED_CONTENT
    consent_purpose: Literal["text_analysis"] = "text_analysis"
    consent_policy_version: str
    consent_receipt_id: str
    consent_receipt_fingerprint: str
    privacy_policy_version: str
    provider: Provider
    provider_version: str
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    redactor_sha256: str
    preprocessing_version: str
    preprocessing_sha256: str
    router_version: str
    router_sha256: str
    model_plan_fingerprint: str
    analysis_run_schema_version: PositiveInt
    full_run_metric_observation_count: NonNegativeInt
    full_run_completed: Literal[True] = True
    direct_selected_window: Literal[True] = True
    legacy_inference_allowed: Literal[False] = False
    local_only: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _v2_ids = field_validator(
        "input_receipt_id",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "selection_revision_id",
        "selection_revision_fingerprint",
        "selection_scope_fingerprint",
        "analysis_run_id",
        "analysis_run_fingerprint",
        "analysis_run_request_fingerprint",
        "project_id",
        "session_id",
        "analysis_window_fingerprint",
        "selected_window_manifest_root",
        "selected_window_manifest_identity_fingerprint",
        "post_floor_observed_allowlisted_source_manifest_root",
        "post_floor_observed_allowlisted_source_manifest_identity_fingerprint",
        "analysis_profile_sha256",
        "metric_pack_sha256",
        "metric_engine_sha256",
        "metric_catalog_sha256",
        "consent_receipt_id",
        "consent_receipt_fingerprint",
        "redactor_sha256",
        "preprocessing_sha256",
        "router_sha256",
        "model_plan_fingerprint",
    )(_digest)
    _v2_codes = field_validator(
        "analysis_profile_key", "metric_pack_key"
    )(_safe_code)
    _v2_versions = field_validator(
        "analysis_run_fingerprint_version",
        "capture_contract_version",
        "metric_engine_version",
        "metric_catalog_version",
        "consent_policy_version",
        "privacy_policy_version",
        "provider_version",
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
        "preprocessing_version",
        "router_version",
    )(_safe_version)
    _v2_times = field_validator(
        "analysis_window_started_at",
        "analysis_window_ended_at",
        "analysis_run_completed_at",
        "captured_at",
    )(_utc)

    @field_validator("selected_metric_keys")
    @classmethod
    def canonical_v2_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(values)

    @model_validator(mode="after")
    def exact_v2_capture_shape(self) -> AnalysisInputReceiptV2:
        if not (
            self.analysis_window_started_at
            <= self.analysis_window_ended_at
            <= self.analysis_run_completed_at
            <= self.captured_at
        ):
            raise ValueError("window, run completion, and capture times must be ordered")
        if len(
            {
                self.analysis_window_fingerprint,
                self.selected_window_manifest_root,
                self.post_floor_observed_allowlisted_source_manifest_root,
            }
        ) != 3:
            raise ValueError("window and manifest roots require distinct domains")

        expected_selected_manifest_identity = _manifest_identity_fingerprint(
            role="selected_window",
            root=self.selected_window_manifest_root,
            version=self.selected_window_manifest_version,
            entry_count=self.selected_window_manifest_entry_count,
        )
        expected_source_manifest_identity = _manifest_identity_fingerprint(
            role="post_floor_observed_allowlisted_source",
            root=self.post_floor_observed_allowlisted_source_manifest_root,
            version=(
                self.post_floor_observed_allowlisted_source_manifest_version
            ),
            entry_count=(
                self.post_floor_observed_allowlisted_source_manifest_entry_count
            ),
        )
        if (
            self.selected_window_manifest_identity_fingerprint
            != expected_selected_manifest_identity
            or self.post_floor_observed_allowlisted_source_manifest_identity_fingerprint
            != expected_source_manifest_identity
        ):
            raise ValueError("manifest identities must bind their exact role, root, and count")

        observed = (
            self.post_floor_observed_allowlisted_source_manifest_entry_count
        )
        extracted = self.successfully_extracted_source_entry_count
        eligible = self.selection_eligible_entry_count
        selected = self.selected_window_manifest_entry_count
        if extracted > observed:
            raise ValueError("extracted entries cannot exceed observed source entries")
        if eligible > extracted:
            raise ValueError("selection eligibility cannot exceed extracted entries")
        if selected > eligible:
            raise ValueError("selected-window entries cannot exceed eligible entries")

        if observed == 0:
            if (
                extracted != 0
                or self.extraction_completeness
                is not AnalysisInputExtractionCompleteness.NOT_APPLICABLE_EMPTY_SOURCE
            ):
                raise ValueError("an empty observed source requires explicit N/A extraction")
        elif extracted == observed:
            if self.extraction_completeness is not AnalysisInputExtractionCompleteness.COMPLETE:
                raise ValueError("complete extraction requires exact observed coverage")
        elif self.extraction_completeness is not AnalysisInputExtractionCompleteness.PARTIAL:
            raise ValueError("source omissions require partial extraction")

        if eligible == 0:
            if (
                selected != 0
                or self.selection_coverage
                is not AnalysisInputSelectionCoverage.NOT_APPLICABLE_EMPTY_ELIGIBLE_SET
            ):
                raise ValueError("an empty eligible set requires explicit N/A selection")
        elif selected == eligible:
            if self.selection_coverage is not AnalysisInputSelectionCoverage.COMPLETE:
                raise ValueError("complete selection requires exact eligible coverage")
        elif self.selection_coverage is not AnalysisInputSelectionCoverage.PARTIAL:
            raise ValueError("selection omissions require partial coverage")

        if self.full_run_metric_observation_count != len(self.selected_metric_keys):
            raise ValueError("a full run must account for every selected metric")
        return self

    @staticmethod
    def selected_manifest_identity(*, root: str, entry_count: int) -> str:
        return _manifest_identity_fingerprint(
            role="selected_window",
            root=_digest(root),
            version=SELECTED_WINDOW_MANIFEST_VERSION,
            entry_count=entry_count,
        )

    @staticmethod
    def observed_source_manifest_identity(*, root: str, entry_count: int) -> str:
        return _manifest_identity_fingerprint(
            role="post_floor_observed_allowlisted_source",
            root=_digest(root),
            version=POST_FLOOR_OBSERVED_ALLOWLISTED_SOURCE_MANIFEST_VERSION,
            entry_count=entry_count,
        )

    @property
    def provenance_fingerprint(self) -> str:
        """Semantic boundary, excluding run-specific ids, roots, counts, and times."""

        payload = {
            "analysis_profile_key": self.analysis_profile_key,
            "analysis_profile_sha256": self.analysis_profile_sha256,
            "analysis_profile_version": self.analysis_profile_version,
            "analysis_run_fingerprint_version": self.analysis_run_fingerprint_version,
            "analysis_run_schema_version": self.analysis_run_schema_version,
            "analysis_window_fingerprint_basis": self.analysis_window_fingerprint_basis,
            "analysis_window_fingerprint_version": self.analysis_window_fingerprint_version,
            "capture_contract_version": self.capture_contract_version,
            "capture_source": self.capture_source,
            "consent_policy_version": self.consent_policy_version,
            "consent_purpose": self.consent_purpose,
            "content_schema_version": self.content_schema_version,
            "data_tier": self.data_tier,
            "metric_catalog_sha256": self.metric_catalog_sha256,
            "metric_catalog_version": self.metric_catalog_version,
            "metric_engine_sha256": self.metric_engine_sha256,
            "metric_engine_version": self.metric_engine_version,
            "metric_pack_key": self.metric_pack_key,
            "metric_pack_sha256": self.metric_pack_sha256,
            "metric_pack_version": self.metric_pack_version,
            "model_plan_fingerprint": self.model_plan_fingerprint,
            "post_floor_manifest_version": (
                self.post_floor_observed_allowlisted_source_manifest_version
            ),
            "preprocessing_sha256": self.preprocessing_sha256,
            "preprocessing_version": self.preprocessing_version,
            "privacy_policy_version": self.privacy_policy_version,
            "provider": self.provider,
            "provider_adapter_version": self.provider_adapter_version,
            "provider_schema_version": self.provider_schema_version,
            "provider_version": self.provider_version,
            "redactor_sha256": self.redactor_sha256,
            "redactor_version": self.redactor_version,
            "router_sha256": self.router_sha256,
            "router_version": self.router_version,
            "selected_window_manifest_version": self.selected_window_manifest_version,
            "source_schema_version": self.source_schema_version,
        }
        return hashlib.sha256(
            json.dumps(
                payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            ).encode("utf-8")
        ).hexdigest()

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class AppendPrefixProofReceipt(PersistenceRevalidatedModel):
    """Content-free append claim awaiting repository-side verification.

    This receipt intentionally cannot authorize comparisons by itself.  Its
    digests make the transient verifier result auditable while persistence must
    still verify the predecessor graph and seal it in a later phase.
    """

    contract_version: Literal[APPEND_PREFIX_PROOF_RECEIPT_VERSION] = (
        APPEND_PREFIX_PROOF_RECEIPT_VERSION
    )
    proof_receipt_id: str
    predecessor_revision_id: str
    predecessor_revision_fingerprint: str
    predecessor_input_receipt_id: str
    predecessor_input_receipt_fingerprint: str
    current_input_receipt_id: str
    current_input_receipt_fingerprint: str
    predecessor_prefix_root: str
    predecessor_prefix_event_count: NonNegativeInt
    current_prefix_root: str
    current_prefix_event_count: PositiveInt
    verifier_fingerprint: str
    assessed_at: datetime
    verification_state: Literal[
        AppendVerificationState.UNTRUSTED_UNTIL_REPOSITORY_VERIFIED
    ] = AppendVerificationState.UNTRUSTED_UNTIL_REPOSITORY_VERIFIED
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "proof_receipt_id",
        "predecessor_revision_id",
        "predecessor_revision_fingerprint",
        "predecessor_input_receipt_id",
        "predecessor_input_receipt_fingerprint",
        "current_input_receipt_id",
        "current_input_receipt_fingerprint",
        "predecessor_prefix_root",
        "current_prefix_root",
        "verifier_fingerprint",
    )(_digest)
    _assessed = field_validator("assessed_at")(_utc)

    @model_validator(mode="after")
    def strict_growth_claim(self) -> AppendPrefixProofReceipt:
        if self.current_prefix_event_count <= self.predecessor_prefix_event_count:
            raise ValueError("an append claim requires strict prefix-count growth")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class PrefixProofVerifier(Protocol):
    """Ephemeral seam for claiming append-only capture without persisting leaves.

    Implementations may inspect transient provider-event commitments in memory.
    Only the resulting relation plus the current prefix root/count is persisted.
    """

    @property
    def verifier_fingerprint(self) -> str: ...

    def claims_strict_append(
        self,
        *,
        predecessor: SessionRevisionReceipt,
        current_input: AnalysisInputReceipt,
    ) -> bool: ...


class SessionRevisionReceipt(PersistenceRevalidatedModel):
    contract_version: Literal[SESSION_REVISION_RECEIPT_VERSION] = (
        SESSION_REVISION_RECEIPT_VERSION
    )
    revision_id: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    project_id: str
    session_id: str
    revision_ordinal: PositiveInt
    predecessor_revision_id: str | None = None
    analysis_input_receipt_id: str
    analysis_input_receipt_fingerprint: str
    input_provenance_fingerprint: str
    relation: SessionRevisionRelation
    append_verification_state: AppendVerificationState = (
        AppendVerificationState.NOT_APPLICABLE
    )
    append_prefix_proof: AppendPrefixProofReceipt | None = None
    persisted_prefix_root: str
    persisted_prefix_event_count: NonNegativeInt
    analysis_window_fingerprint: str
    analysis_window_fingerprint_basis: Literal[
        AnalysisWindowFingerprintBasis.CANONICAL_PROVIDER_EVENT_MANIFEST
    ] = AnalysisWindowFingerprintBasis.CANONICAL_PROVIDER_EVENT_MANIFEST
    analysis_window_fingerprint_version: str
    analysis_window_started_at: datetime
    analysis_window_ended_at: datetime
    effective_at: datetime
    captured_at: datetime
    effective_time_basis: RevisionEffectiveTimeBasis
    provenance: Literal[
        SessionRevisionProvenance.DIRECT_ANALYSIS_WINDOW_RECEIPT
    ] = SessionRevisionProvenance.DIRECT_ANALYSIS_WINDOW_RECEIPT
    legacy_inference_allowed: Literal[False] = False
    provider: Provider
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    event_count: NonNegativeInt
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False

    _digests = field_validator(
        "revision_id",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "project_id",
        "session_id",
        "analysis_input_receipt_id",
        "analysis_input_receipt_fingerprint",
        "input_provenance_fingerprint",
        "persisted_prefix_root",
        "analysis_window_fingerprint",
    )(_digest)
    _versions = field_validator(
        "provider_adapter_version",
        "analysis_window_fingerprint_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
    )(_safe_version)
    _times = field_validator(
        "analysis_window_started_at",
        "analysis_window_ended_at",
        "effective_at",
        "captured_at",
    )(_utc)

    @field_validator("predecessor_revision_id")
    @classmethod
    def optional_predecessor(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def immutable_revision_shape(self) -> SessionRevisionReceipt:
        if self.analysis_window_started_at > self.analysis_window_ended_at:
            raise ValueError("analysis window timestamps must be ordered")
        if self.analysis_window_ended_at > self.captured_at:
            raise ValueError("analysis windows cannot end after capture")
        if self.effective_at > self.captured_at:
            raise ValueError("revision effective time cannot follow capture")
        if self.effective_time_basis is RevisionEffectiveTimeBasis.SESSION_ENDED_AT:
            if self.effective_at != self.analysis_window_ended_at:
                raise ValueError("ended-session revisions use the window end time")
        elif self.effective_at != self.captured_at:
            raise ValueError("open-session revisions use the capture time")
        if self.revision_ordinal == 1 and self.predecessor_revision_id is not None:
            raise ValueError("the first revision cannot have a predecessor")
        if self.revision_ordinal > 1 and self.predecessor_revision_id is None:
            raise ValueError("later revisions require an immutable predecessor")
        if self.predecessor_revision_id == self.revision_id:
            raise ValueError("a revision cannot be its own predecessor")
        if self.event_count != self.persisted_prefix_event_count:
            raise ValueError("revision event count must equal its persisted prefix count")
        if self.revision_ordinal == 1:
            if self.relation is not SessionRevisionRelation.FIRST:
                raise ValueError("the first revision must use the first relation")
        elif self.relation is SessionRevisionRelation.FIRST:
            raise ValueError("later revisions cannot use the first relation")
        append_claimed = self.relation is SessionRevisionRelation.APPEND_PREFIX_PROVED
        if append_claimed:
            if (
                self.append_verification_state
                is not AppendVerificationState.UNTRUSTED_UNTIL_REPOSITORY_VERIFIED
                or self.append_prefix_proof is None
            ):
                raise ValueError("append relations require an explicitly untrusted proof")
            proof = self.append_prefix_proof
            if (
                proof.predecessor_revision_id != self.predecessor_revision_id
                or proof.current_input_receipt_id != self.analysis_input_receipt_id
                or proof.current_input_receipt_fingerprint
                != self.analysis_input_receipt_fingerprint
                or proof.current_prefix_root != self.persisted_prefix_root
                or proof.current_prefix_event_count
                != self.persisted_prefix_event_count
            ):
                raise ValueError("append claim fields must match the session revision")
        elif (
            self.append_verification_state is not AppendVerificationState.NOT_APPLICABLE
            or self.append_prefix_proof is not None
        ):
            raise ValueError("non-append relations cannot carry an append proof")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)

    @classmethod
    def from_direct_input(
        cls,
        *,
        revision_id: str,
        input_receipt: AnalysisInputReceipt,
        revision_ordinal: int,
        effective_time_basis: RevisionEffectiveTimeBasis,
        predecessor: SessionRevisionReceipt | None = None,
        prefix_verifier: PrefixProofVerifier | None = None,
    ) -> SessionRevisionReceipt:
        """Derive a conservative revision relation from direct input receipts.

        Counts and timestamps are never accepted as evidence of append-only
        growth.  A strict-append claim requires an ephemeral verifier; absent or
        failed proof becomes ``changed_or_reordered``.  The claim remains
        untrusted until repository verification.  A provenance change is always
        recorded as a visible boundary before prefix proof is considered.
        """

        current = AnalysisInputReceipt.revalidate_for_persistence(input_receipt)
        if predecessor is None:
            relation = SessionRevisionRelation.FIRST
            predecessor_revision_id = None
        else:
            prior = cls.revalidate_for_persistence(predecessor)
            if revision_ordinal != prior.revision_ordinal + 1:
                raise ValueError("a revision must immediately follow its predecessor")
            if (
                prior.root_receipt_id != current.root_receipt_id
                or prior.root_receipt_fingerprint
                != current.root_receipt_fingerprint
                or prior.project_id != current.project_id
                or prior.session_id != current.session_id
            ):
                raise ValueError("a revision predecessor must share root, project, and session")
            predecessor_revision_id = prior.revision_id
            if prior.input_provenance_fingerprint != current.provenance_fingerprint:
                relation = SessionRevisionRelation.PROVENANCE_BOUNDARY
            else:
                append_proved = False
                if (
                    prefix_verifier is not None
                    and current.captured_source_entry_count
                    > prior.persisted_prefix_event_count
                ):
                    try:
                        append_proved = prefix_verifier.claims_strict_append(
                            predecessor=prior,
                            current_input=current,
                        )
                    except Exception:
                        append_proved = False
                relation = (
                    SessionRevisionRelation.APPEND_PREFIX_PROVED
                    if append_proved
                    else SessionRevisionRelation.CHANGED_OR_REORDERED
                )

        effective_at = (
            current.analysis_window_ended_at
            if effective_time_basis is RevisionEffectiveTimeBasis.SESSION_ENDED_AT
            else current.captured_at
        )
        values: dict[str, Any] = {
                "revision_id": revision_id,
                "root_receipt_id": current.root_receipt_id,
                "root_receipt_fingerprint": current.root_receipt_fingerprint,
                "project_id": current.project_id,
                "session_id": current.session_id,
                "revision_ordinal": revision_ordinal,
                "predecessor_revision_id": predecessor_revision_id,
                "analysis_input_receipt_id": current.input_receipt_id,
                "analysis_input_receipt_fingerprint": current.fingerprint,
                "input_provenance_fingerprint": current.provenance_fingerprint,
                "relation": relation,
                "persisted_prefix_root": current.source_manifest_fingerprint,
                "persisted_prefix_event_count": current.captured_source_entry_count,
                "analysis_window_fingerprint": current.analysis_window_fingerprint,
                "analysis_window_fingerprint_version": (
                    current.analysis_window_fingerprint_version
                ),
                "analysis_window_started_at": current.analysis_window_started_at,
                "analysis_window_ended_at": current.analysis_window_ended_at,
                "effective_at": effective_at,
                "captured_at": current.captured_at,
                "effective_time_basis": effective_time_basis,
                "provider": current.provider,
                "provider_adapter_version": current.provider_adapter_version,
                "provider_schema_version": current.provider_schema_version,
                "source_schema_version": current.source_schema_version,
                "content_schema_version": current.content_schema_version,
                "redactor_version": current.redactor_version,
                "event_count": current.captured_source_entry_count,
            }
        if relation is SessionRevisionRelation.APPEND_PREFIX_PROVED:
            assert predecessor is not None
            prior = cls.revalidate_for_persistence(predecessor)
            assert prefix_verifier is not None
            proof = AppendPrefixProofReceipt(
                proof_receipt_id=hashlib.sha256(
                    (
                        "append-prefix-proof-v1:"
                        + prior.revision_id
                        + current.input_receipt_id
                        + prefix_verifier.verifier_fingerprint
                    ).encode("ascii")
                ).hexdigest(),
                predecessor_revision_id=prior.revision_id,
                predecessor_revision_fingerprint=prior.fingerprint,
                predecessor_input_receipt_id=prior.analysis_input_receipt_id,
                predecessor_input_receipt_fingerprint=(
                    prior.analysis_input_receipt_fingerprint
                ),
                current_input_receipt_id=current.input_receipt_id,
                current_input_receipt_fingerprint=current.fingerprint,
                predecessor_prefix_root=prior.persisted_prefix_root,
                predecessor_prefix_event_count=prior.persisted_prefix_event_count,
                current_prefix_root=current.source_manifest_fingerprint,
                current_prefix_event_count=current.captured_source_entry_count,
                verifier_fingerprint=prefix_verifier.verifier_fingerprint,
                assessed_at=current.captured_at,
            )
            values["append_verification_state"] = (
                AppendVerificationState.UNTRUSTED_UNTIL_REPOSITORY_VERIFIED
            )
            values["append_prefix_proof"] = proof
        return cls.revalidate_for_persistence(values)


class SessionRevisionReceiptV3(PersistenceRevalidatedModel):
    """Conservative immutable revision linked by predecessor id and fingerprint.

    V3 intentionally has no append-proof state or constructor input.  Until a
    future repository can verify a content-free prefix protocol, every
    same-provenance successor is ``changed_or_reordered``.
    """

    contract_version: Literal[SESSION_REVISION_RECEIPT_V3_VERSION] = (
        SESSION_REVISION_RECEIPT_V3_VERSION
    )
    revision_id: str
    root_receipt_id: str
    root_receipt_fingerprint: str
    project_id: str
    session_id: str
    revision_ordinal: PositiveInt
    predecessor_revision_id: str | None = None
    predecessor_revision_fingerprint: str | None = None
    predecessor_link_fingerprint: str | None = None
    analysis_input_receipt_id: str
    analysis_input_receipt_fingerprint: str
    input_provenance_fingerprint: str
    analysis_run_id: str
    analysis_run_fingerprint: str
    relation: SessionRevisionRelationV3
    selected_window_manifest_root: str
    selected_window_manifest_version: Literal[SELECTED_WINDOW_MANIFEST_VERSION] = (
        SELECTED_WINDOW_MANIFEST_VERSION
    )
    selected_window_manifest_entry_count: NonNegativeInt
    analysis_window_fingerprint: str
    analysis_window_fingerprint_basis: Literal[
        AnalysisWindowFingerprintBasisV2.KEYED_SELECTED_REDACTED_MESSAGE_WINDOW
    ] = AnalysisWindowFingerprintBasisV2.KEYED_SELECTED_REDACTED_MESSAGE_WINDOW
    analysis_window_fingerprint_version: Literal[
        KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION
    ] = KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION
    analysis_window_started_at: datetime
    analysis_window_ended_at: datetime
    effective_at: datetime
    captured_at: datetime
    effective_time_basis: RevisionEffectiveTimeBasis
    provenance: Literal[
        SessionRevisionProvenance.DIRECT_ANALYSIS_WINDOW_RECEIPT
    ] = SessionRevisionProvenance.DIRECT_ANALYSIS_WINDOW_RECEIPT
    provider: Provider
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    legacy_inference_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _v3_digests = field_validator(
        "revision_id",
        "root_receipt_id",
        "root_receipt_fingerprint",
        "project_id",
        "session_id",
        "analysis_input_receipt_id",
        "analysis_input_receipt_fingerprint",
        "input_provenance_fingerprint",
        "analysis_run_id",
        "analysis_run_fingerprint",
        "selected_window_manifest_root",
        "analysis_window_fingerprint",
    )(_digest)
    _v3_versions = field_validator(
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
    )(_safe_version)
    _v3_times = field_validator(
        "analysis_window_started_at",
        "analysis_window_ended_at",
        "effective_at",
        "captured_at",
    )(_utc)

    @field_validator(
        "predecessor_revision_id",
        "predecessor_revision_fingerprint",
        "predecessor_link_fingerprint",
    )
    @classmethod
    def optional_v3_predecessor_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def conservative_revision_shape(self) -> SessionRevisionReceiptV3:
        if not (
            self.analysis_window_started_at
            <= self.analysis_window_ended_at
            <= self.captured_at
        ):
            raise ValueError("revision window and capture times must be ordered")
        if self.effective_at > self.captured_at:
            raise ValueError("revision effective time cannot follow capture")
        expected_effective = (
            self.analysis_window_ended_at
            if self.effective_time_basis is RevisionEffectiveTimeBasis.SESSION_ENDED_AT
            else self.captured_at
        )
        if self.effective_at != expected_effective:
            raise ValueError("revision effective time must follow its declared basis")

        has_predecessor = self.predecessor_revision_id is not None
        if not (
            has_predecessor
            == (self.predecessor_revision_fingerprint is not None)
            == (self.predecessor_link_fingerprint is not None)
        ):
            raise ValueError("revision predecessor id, fingerprint, and link travel together")
        if self.revision_ordinal == 1:
            if has_predecessor or self.relation is not SessionRevisionRelationV3.FIRST:
                raise ValueError("the first revision has no predecessor and uses FIRST")
        elif (
            not has_predecessor
            or self.relation is SessionRevisionRelationV3.FIRST
        ):
            raise ValueError("later revisions require an exact non-FIRST predecessor")
        if self.predecessor_revision_id == self.revision_id:
            raise ValueError("a revision cannot be its own predecessor")
        if has_predecessor:
            assert self.predecessor_revision_id is not None
            assert self.predecessor_revision_fingerprint is not None
            expected_link = _predecessor_link_fingerprint(
                predecessor_revision_id=self.predecessor_revision_id,
                predecessor_revision_fingerprint=self.predecessor_revision_fingerprint,
                successor_ordinal=self.revision_ordinal,
                root_receipt_id=self.root_receipt_id,
                project_id=self.project_id,
                session_id=self.session_id,
            )
            if self.predecessor_link_fingerprint != expected_link:
                raise ValueError("predecessor link must bind the exact successor scope")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)

    @classmethod
    def from_direct_input(
        cls,
        *,
        revision_id: str,
        input_receipt: AnalysisInputReceiptV2,
        revision_ordinal: int,
        effective_time_basis: RevisionEffectiveTimeBasis,
        predecessor: SessionRevisionReceiptV3 | None = None,
    ) -> SessionRevisionReceiptV3:
        current = AnalysisInputReceiptV2.revalidate_for_persistence(input_receipt)
        if predecessor is None:
            relation = SessionRevisionRelationV3.FIRST
            predecessor_revision_id = None
            predecessor_revision_fingerprint = None
            predecessor_link_fingerprint = None
        else:
            prior = cls.revalidate_for_persistence(predecessor)
            if revision_ordinal != prior.revision_ordinal + 1:
                raise ValueError("a revision must immediately follow its predecessor")
            if (
                prior.root_receipt_id != current.root_receipt_id
                or prior.root_receipt_fingerprint != current.root_receipt_fingerprint
                or prior.project_id != current.project_id
                or prior.session_id != current.session_id
            ):
                raise ValueError("a revision predecessor must share root, project, and session")
            predecessor_revision_id = prior.revision_id
            predecessor_revision_fingerprint = prior.fingerprint
            predecessor_link_fingerprint = _predecessor_link_fingerprint(
                predecessor_revision_id=prior.revision_id,
                predecessor_revision_fingerprint=prior.fingerprint,
                successor_ordinal=revision_ordinal,
                root_receipt_id=current.root_receipt_id,
                project_id=current.project_id,
                session_id=current.session_id,
            )
            relation = (
                SessionRevisionRelationV3.PROVENANCE_BOUNDARY
                if prior.input_provenance_fingerprint
                != current.provenance_fingerprint
                else SessionRevisionRelationV3.CHANGED_OR_REORDERED
            )

        effective_at = (
            current.analysis_window_ended_at
            if effective_time_basis is RevisionEffectiveTimeBasis.SESSION_ENDED_AT
            else current.captured_at
        )
        return cls.revalidate_for_persistence(
            {
                "revision_id": revision_id,
                "root_receipt_id": current.root_receipt_id,
                "root_receipt_fingerprint": current.root_receipt_fingerprint,
                "project_id": current.project_id,
                "session_id": current.session_id,
                "revision_ordinal": revision_ordinal,
                "predecessor_revision_id": predecessor_revision_id,
                "predecessor_revision_fingerprint": predecessor_revision_fingerprint,
                "predecessor_link_fingerprint": predecessor_link_fingerprint,
                "analysis_input_receipt_id": current.input_receipt_id,
                "analysis_input_receipt_fingerprint": current.fingerprint,
                "input_provenance_fingerprint": current.provenance_fingerprint,
                "analysis_run_id": current.analysis_run_id,
                "analysis_run_fingerprint": current.analysis_run_fingerprint,
                "relation": relation,
                "selected_window_manifest_root": current.selected_window_manifest_root,
                "selected_window_manifest_entry_count": (
                    current.selected_window_manifest_entry_count
                ),
                "analysis_window_fingerprint": current.analysis_window_fingerprint,
                "analysis_window_started_at": current.analysis_window_started_at,
                "analysis_window_ended_at": current.analysis_window_ended_at,
                "effective_at": effective_at,
                "captured_at": current.captured_at,
                "effective_time_basis": effective_time_basis,
                "provider": current.provider,
                "provider_adapter_version": current.provider_adapter_version,
                "provider_schema_version": current.provider_schema_version,
                "source_schema_version": current.source_schema_version,
                "content_schema_version": current.content_schema_version,
                "redactor_version": current.redactor_version,
            }
        )


class TemporalTrendSpec(StrictModel):
    method: TemporalTrendMethod = TemporalTrendMethod.NONE
    rolling_observation_count: int | None = Field(
        default=None, strict=True, ge=2, le=MAX_LAST_N
    )
    ewma_alpha: float | None = None

    @field_validator("ewma_alpha", mode="before")
    @classmethod
    def finite_alpha(cls, value: Any) -> float | None:
        return None if value is None else _probability(value, field_name="ewma_alpha")

    @model_validator(mode="after")
    def exact_shape(self) -> TemporalTrendSpec:
        if self.method is TemporalTrendMethod.NONE:
            if self.rolling_observation_count is not None or self.ewma_alpha is not None:
                raise ValueError("untrended observations cannot carry trend parameters")
        elif self.method is TemporalTrendMethod.ROLLING_MEDIAN:
            if self.rolling_observation_count is None or self.ewma_alpha is not None:
                raise ValueError("rolling medians require only an observation count")
        elif (
            self.ewma_alpha is None
            or self.ewma_alpha <= 0
            or self.rolling_observation_count is not None
        ):
            raise ValueError("EWMA requires only an alpha greater than zero")
        return self


class MetricComparisonIdentity(StrictModel):
    metric_key: str
    metric_definition_version: str
    metric_definition_sha256: str
    metric_question_version: str
    metric_question_sha256: str
    value_kind: TemporalValueKind
    unit_code: str
    direction: MetricDirection
    aggregation_semantics: TemporalAggregationSemantics
    exposure_unit_code: str | None = None
    trend: TemporalTrendSpec = Field(default_factory=TemporalTrendSpec)
    interval_method_version: str | None = None
    evidence_tier: EvidenceTier
    evidence_contract_version: str
    estimator_kind: EstimatorIdentityKind
    estimator_plan_version: str
    estimator_plan_sha256: str
    estimator_lifecycle: EstimatorLifecycleState
    activation_receipt_sha256: str | None = None
    model_provider: ModelProviderKind | None = None
    requested_model_key: str | None = None
    requested_model_revision: str | None = None
    served_model_key: str | None = None
    served_model_revision: str | None = None
    served_model_fallback: bool | None = None
    model_weight_identity_state: ArtifactIdentityState | None = None
    model_weight_set_sha256: str | None = None
    tokenizer_key: str | None = None
    tokenizer_revision: str | None = None
    tokenizer_identity_state: ArtifactIdentityState | None = None
    tokenizer_sha256: str | None = None
    model_license_code: str | None = None
    reasoning_effort: ReasoningEffort | None = None
    preprocessing_version: str
    preprocessing_sha256: str
    prompt_template_version: str | None = None
    prompt_template_sha256: str | None = None
    rubric_version: str | None = None
    rubric_sha256: str | None = None
    calibration_version: str
    calibration_sha256: str
    router_version: str
    router_sha256: str
    redactor_version: str
    redactor_sha256: str
    provider: Provider
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    privacy_policy_version: str
    observation_contract_version: Literal[TEMPORAL_HISTORY_CONTRACT_VERSION] = (
        TEMPORAL_HISTORY_CONTRACT_VERSION
    )

    _codes = field_validator("metric_key", "unit_code")(_safe_code)
    _optional_exposure_unit = field_validator("exposure_unit_code")(_optional_code)
    _digests = field_validator(
        "metric_definition_sha256",
        "metric_question_sha256",
        "estimator_plan_sha256",
        "preprocessing_sha256",
        "calibration_sha256",
        "router_sha256",
        "redactor_sha256",
    )(_digest)
    _versions = field_validator(
        "metric_definition_version",
        "metric_question_version",
        "evidence_contract_version",
        "estimator_plan_version",
        "preprocessing_version",
        "calibration_version",
        "router_version",
        "redactor_version",
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "privacy_policy_version",
    )(_safe_version)
    _optional_codes = field_validator(
        "requested_model_key",
        "served_model_key",
        "tokenizer_key",
        "model_license_code",
    )(_optional_code)
    _optional_versions = field_validator(
        "interval_method_version",
        "requested_model_revision",
        "served_model_revision",
        "tokenizer_revision",
        "prompt_template_version",
        "rubric_version",
    )(_optional_version)

    @field_validator(
        "activation_receipt_sha256",
        "model_weight_set_sha256",
        "tokenizer_sha256",
        "prompt_template_sha256",
        "rubric_sha256",
    )
    @classmethod
    def optional_digest(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @model_validator(mode="after")
    def complete_identity(self) -> MetricComparisonIdentity:
        expected_semantics = {
            TemporalValueKind.FRACTION: TemporalAggregationSemantics.RATIO_OF_SUMS,
            TemporalValueKind.COUNT_WITH_EXPOSURE: (
                TemporalAggregationSemantics.COUNT_SUM_WITH_EXPOSURE
            ),
            TemporalValueKind.DISTRIBUTION_SAMPLE: (
                TemporalAggregationSemantics.MEDIAN_AND_QUANTILES
            ),
            TemporalValueKind.SAMPLED_PROPORTION: (
                TemporalAggregationSemantics.PROPORTION_INTERVAL_FROM_SUMS
            ),
        }[self.value_kind]
        if self.aggregation_semantics is not expected_semantics:
            raise ValueError("aggregation semantics must match the raw value kind")
        if (
            self.aggregation_semantics
            is TemporalAggregationSemantics.COUNT_SUM_WITH_EXPOSURE
        ) != (self.exposure_unit_code is not None):
            raise ValueError("count-with-exposure identities require an exposure unit")
        if (self.value_kind is TemporalValueKind.SAMPLED_PROPORTION) != (
            self.interval_method_version is not None
        ):
            raise ValueError("sampled proportions require an interval method version")
        if self.estimator_lifecycle is EstimatorLifecycleState.PROVISIONAL:
            if self.activation_receipt_sha256 is not None:
                raise ValueError("provisional estimators cannot claim activation")
        elif self.activation_receipt_sha256 is None:
            raise ValueError("activated or retired estimators require activation provenance")

        model_fields = (
            self.model_provider,
            self.requested_model_key,
            self.requested_model_revision,
            self.served_model_key,
            self.served_model_revision,
            self.served_model_fallback,
            self.model_weight_identity_state,
            self.tokenizer_key,
            self.tokenizer_revision,
            self.tokenizer_identity_state,
            self.model_license_code,
            self.reasoning_effort,
            self.prompt_template_version,
            self.prompt_template_sha256,
            self.rubric_version,
            self.rubric_sha256,
        )
        if self.estimator_kind is EstimatorIdentityKind.DETERMINISTIC:
            if any(value is not None for value in model_fields):
                raise ValueError("deterministic identities cannot claim model provenance")
            if self.model_weight_set_sha256 is not None or self.tokenizer_sha256 is not None:
                raise ValueError("deterministic identities cannot claim model artifacts")
            return self

        if any(value is None for value in model_fields):
            raise ValueError("model-assisted identities require complete model provenance")
        if self.reasoning_effort is ReasoningEffort.NONE:
            raise ValueError("model-assisted identities require an explicit non-none effort")
        served_is_fallback = (
            self.requested_model_key,
            self.requested_model_revision,
        ) != (
            self.served_model_key,
            self.served_model_revision,
        )
        if self.served_model_fallback is not served_is_fallback:
            raise ValueError("fallback state must match requested and served identities")
        if (
            self.model_weight_identity_state is ArtifactIdentityState.PINNED_SHA256
        ) != (self.model_weight_set_sha256 is not None):
            raise ValueError("model weight hash presence must match its identity state")
        if (self.tokenizer_identity_state is ArtifactIdentityState.PINNED_SHA256) != (
            self.tokenizer_sha256 is not None
        ):
            raise ValueError("tokenizer hash presence must match its identity state")
        required_artifact_state = {
            ModelProviderKind.LOCAL: ArtifactIdentityState.PINNED_SHA256,
            ModelProviderKind.OPENAI: (
                ArtifactIdentityState.PROVIDER_MANAGED_UNAVAILABLE
            ),
            ModelProviderKind.ANTHROPIC: (
                ArtifactIdentityState.PROVIDER_MANAGED_UNAVAILABLE
            ),
            ModelProviderKind.SYNTHETIC: ArtifactIdentityState.SYNTHETIC_NO_ARTIFACT,
        }[self.model_provider]
        if (
            self.model_weight_identity_state is not required_artifact_state
            or self.tokenizer_identity_state is not required_artifact_state
        ):
            raise ValueError(
                "weight and tokenizer identity states must match the model provider"
            )
        return self

    @property
    def fingerprint(self) -> str:
        """Return the canonical comparison identity used to join observations."""

        return _canonical_digest(self)


class FractionObservationValue(StrictModel):
    kind: Literal[TemporalValueKind.FRACTION] = TemporalValueKind.FRACTION
    numerator: NonNegativeInt
    denominator: PositiveInt

    @model_validator(mode="after")
    def valid_fraction(self) -> FractionObservationValue:
        if self.numerator > self.denominator:
            raise ValueError("fraction numerator cannot exceed denominator")
        return self


class CountExposureObservationValue(StrictModel):
    kind: Literal[TemporalValueKind.COUNT_WITH_EXPOSURE] = (
        TemporalValueKind.COUNT_WITH_EXPOSURE
    )
    count: NonNegativeInt
    exposure: float
    exposure_unit_code: str

    _unit = field_validator("exposure_unit_code")(_safe_code)

    @field_validator("exposure", mode="before")
    @classmethod
    def finite_positive_exposure(cls, value: Any) -> float:
        number = _finite(value, field_name="exposure", nonnegative=True)
        if number == 0:
            raise ValueError("exposure must be greater than zero")
        return number


class DistributionSampleObservationValue(StrictModel):
    kind: Literal[TemporalValueKind.DISTRIBUTION_SAMPLE] = (
        TemporalValueKind.DISTRIBUTION_SAMPLE
    )
    sample: float

    @field_validator("sample", mode="before")
    @classmethod
    def finite_sample(cls, value: Any) -> float:
        return _finite(value, field_name="sample")


class SampledProportionObservationValue(StrictModel):
    kind: Literal[TemporalValueKind.SAMPLED_PROPORTION] = (
        TemporalValueKind.SAMPLED_PROPORTION
    )
    successes: NonNegativeInt
    trials: PositiveInt

    @model_validator(mode="after")
    def valid_proportion(self) -> SampledProportionObservationValue:
        if self.successes > self.trials:
            raise ValueError("successes cannot exceed trials")
        return self


TemporalObservationValue = Annotated[
    FractionObservationValue
    | CountExposureObservationValue
    | DistributionSampleObservationValue
    | SampledProportionObservationValue,
    Field(discriminator="kind"),
]


class TemporalUncertainty(StrictModel):
    lower: float
    upper: float
    confidence_level: float
    method_version: str

    _method = field_validator("method_version")(_safe_version)

    @field_validator("lower", "upper", mode="before")
    @classmethod
    def finite_bound(cls, value: Any, info: Any) -> float:
        return _finite(value, field_name=info.field_name)

    @field_validator("confidence_level", mode="before")
    @classmethod
    def confidence_probability(cls, value: Any) -> float:
        number = _probability(value, field_name="confidence_level")
        if number in {0.0, 1.0}:
            raise ValueError("confidence level must be strictly between zero and one")
        return number

    @model_validator(mode="after")
    def ordered_bounds(self) -> TemporalUncertainty:
        if self.lower > self.upper:
            raise ValueError("uncertainty bounds must be ordered")
        return self


class TemporalMetricObservation(PersistenceRevalidatedModel):
    observation_id: str
    revision_id: str
    analysis_run_id: str
    analysis_input_receipt_id: str
    analysis_input_receipt_fingerprint: str
    comparison_identity: MetricComparisonIdentity
    selection_state: TemporalSelectionState
    source_state: TemporalSourceState
    value_state: TemporalValueState
    value: TemporalObservationValue | None = None
    unavailable_reason_code: str | None = None
    evidence_numerator: NonNegativeInt | None = None
    evidence_denominator: PositiveInt | None = None
    uncertainty: TemporalUncertainty | None = None
    observed_at: datetime
    follow_up_window_end_at: datetime | None = None
    contains_local_content: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "observation_id",
        "revision_id",
        "analysis_run_id",
        "analysis_input_receipt_id",
        "analysis_input_receipt_fingerprint",
    )(_digest)
    _reason = field_validator("unavailable_reason_code")(_optional_code)
    _observed = field_validator("observed_at")(_utc)

    @field_validator("follow_up_window_end_at")
    @classmethod
    def optional_follow_up(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def truthful_state_axes(self) -> TemporalMetricObservation:
        if (self.evidence_numerator is None) != (self.evidence_denominator is None):
            raise ValueError("evidence coverage requires numerator and denominator")
        if (
            self.evidence_numerator is not None
            and self.evidence_denominator is not None
            and self.evidence_numerator > self.evidence_denominator
        ):
            raise ValueError("evidence numerator cannot exceed denominator")
        if self.follow_up_window_end_at is not None and (
            self.follow_up_window_end_at < self.observed_at
        ):
            raise ValueError("follow-up windows cannot end before observation")
        if self.source_state is not TemporalSourceState.PRESENT and any(
            value is not None
            for value in (self.evidence_numerator, self.evidence_denominator)
        ):
            raise ValueError("absent sources cannot claim evidence coverage")

        allowed_sources = {
            TemporalSelectionState.SELECTED: {
                TemporalSourceState.PRESENT,
                TemporalSourceState.SOURCE_MISSING,
                TemporalSourceState.SOURCE_FAILED,
                TemporalSourceState.SOURCE_INCOMPATIBLE,
            },
            TemporalSelectionState.NOT_SELECTED: {TemporalSourceState.NOT_REQUESTED},
            TemporalSelectionState.SELECTION_UNKNOWN: {
                TemporalSourceState.NO_POST_FLOOR_SOURCE
            },
        }[self.selection_state]
        if self.source_state not in allowed_sources:
            raise ValueError("selection state conflicts with source state")

        allowed_values = {
            TemporalSourceState.PRESENT: {
                TemporalValueState.KNOWN,
                TemporalValueState.UNKNOWN,
                TemporalValueState.ABSTAINED,
                TemporalValueState.NOT_APPLICABLE,
            },
            TemporalSourceState.NOT_REQUESTED: {TemporalValueState.UNKNOWN},
            TemporalSourceState.NO_POST_FLOOR_SOURCE: {TemporalValueState.UNKNOWN},
            TemporalSourceState.SOURCE_MISSING: {TemporalValueState.UNKNOWN},
            TemporalSourceState.SOURCE_FAILED: {TemporalValueState.FAILED},
            TemporalSourceState.SOURCE_INCOMPATIBLE: {
                TemporalValueState.INCOMPATIBLE
            },
        }[self.source_state]
        if self.value_state not in allowed_values:
            raise ValueError("source state conflicts with value state")

        is_known = self.value_state is TemporalValueState.KNOWN
        if is_known:
            if self.selection_state is not TemporalSelectionState.SELECTED:
                raise ValueError("known values must have been selected")
            if self.source_state is not TemporalSourceState.PRESENT:
                raise ValueError("known values require a present source")
            if self.value is None or self.unavailable_reason_code is not None:
                raise ValueError("known values require only their typed value")
            if self.value.kind is not self.comparison_identity.value_kind:
                raise ValueError("value shape must match the comparison identity")
            if (
                isinstance(self.value, CountExposureObservationValue)
                and self.value.exposure_unit_code
                != self.comparison_identity.exposure_unit_code
            ):
                raise ValueError("observation exposure unit must match its identity")
            if self.value.kind is TemporalValueKind.SAMPLED_PROPORTION:
                if self.uncertainty is None or (
                    self.uncertainty.method_version
                    != self.comparison_identity.interval_method_version
                ):
                    raise ValueError(
                        "sampled-proportion uncertainty must use the identity interval method"
                    )
            if (
                self.uncertainty is not None
                and self.value.kind
                in {
                    TemporalValueKind.FRACTION,
                    TemporalValueKind.SAMPLED_PROPORTION,
                }
                and not (
                    0 <= self.uncertainty.lower <= self.uncertainty.upper <= 1
                )
            ):
                raise ValueError("fraction uncertainty must remain within zero and one")
        else:
            if self.value is not None or self.uncertainty is not None:
                raise ValueError("unavailable observations cannot carry values")
            if self.unavailable_reason_code is None:
                raise ValueError("unavailable observations require a safe reason code")
        return self


class TemporalMetricObservationV2(TemporalMetricObservation):
    """Observation with an explicit evidence-coverage eligibility/state axis.

    A known empty eligible set is represented by ``0 / 0`` and deliberately has
    no ratio.  That is different from unknown coverage and from a metric for
    which evidence coverage is not applicable.
    """

    contract_version: Literal[TEMPORAL_METRIC_OBSERVATION_V2_VERSION] = (
        TEMPORAL_METRIC_OBSERVATION_V2_VERSION
    )
    evidence_coverage_eligibility: EvidenceCoverageEligibility
    evidence_coverage_state: EvidenceCoverageState
    evidence_denominator: NonNegativeInt | None = None
    remote_processing_allowed: Literal[False] = False

    @model_validator(mode="after")
    def exact_evidence_coverage_state(self) -> TemporalMetricObservationV2:
        has_counts = self.evidence_numerator is not None
        if self.evidence_coverage_eligibility is EvidenceCoverageEligibility.ELIGIBLE:
            if self.evidence_coverage_state is EvidenceCoverageState.KNOWN:
                if not has_counts:
                    raise ValueError("known eligible evidence coverage requires counts")
            elif self.evidence_coverage_state is EvidenceCoverageState.UNKNOWN:
                if has_counts:
                    raise ValueError("unknown evidence coverage cannot carry counts")
            else:
                raise ValueError("eligible evidence coverage cannot be not-applicable")
        elif (
            self.evidence_coverage_eligibility
            is EvidenceCoverageEligibility.NOT_ELIGIBLE
        ):
            if (
                self.evidence_coverage_state is not EvidenceCoverageState.NOT_APPLICABLE
                or has_counts
            ):
                raise ValueError("ineligible evidence coverage must be count-free N/A")
        elif (
            self.evidence_coverage_state is not EvidenceCoverageState.UNKNOWN
            or has_counts
        ):
            raise ValueError("unknown eligibility requires count-free unknown coverage")
        return self

    @property
    def evidence_coverage_ratio(self) -> float | None:
        if (
            self.evidence_coverage_state is not EvidenceCoverageState.KNOWN
            or self.evidence_denominator in {None, 0}
        ):
            return None
        assert self.evidence_numerator is not None
        return self.evidence_numerator / self.evidence_denominator

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TemporalObservationBatch(PersistenceRevalidatedModel):
    contract_version: Literal[TEMPORAL_OBSERVATION_BATCH_VERSION] = (
        TEMPORAL_OBSERVATION_BATCH_VERSION
    )
    batch_id: str
    project_id: str
    session_id: str
    revision_id: str
    analysis_run_id: str | None = None
    analysis_input_receipt_id: str | None = None
    analysis_input_receipt_fingerprint: str | None = None
    selection_revision_id: str | None = None
    scope_state: TemporalScopeState
    source_state: TemporalSourceState
    selected_metric_keys: tuple[str, ...] = Field(
        default=(), max_length=MAX_METRICS
    )
    observations: tuple[TemporalMetricObservation, ...] = Field(
        default=(), max_length=MAX_OBSERVATIONS
    )
    recorded_at: datetime
    direct_receipt_only: Literal[True] = True
    legacy_inference_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "batch_id",
        "project_id",
        "session_id",
        "revision_id",
    )(_digest)
    _recorded = field_validator("recorded_at")(_utc)

    @field_validator("selection_revision_id")
    @classmethod
    def optional_selection_id(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator(
        "analysis_run_id",
        "analysis_input_receipt_id",
        "analysis_input_receipt_fingerprint",
    )
    @classmethod
    def optional_input_id(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("selected_metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(values, allow_empty=True)

    @model_validator(mode="after")
    def exact_scope_and_source(self) -> TemporalObservationBatch:
        exact_scope = self.scope_state is TemporalScopeState.EXACT_SELECTION_RECEIPT
        has_exact_input = all(
            value is not None
            for value in (
                self.analysis_run_id,
                self.analysis_input_receipt_id,
                self.analysis_input_receipt_fingerprint,
            )
        )
        if any(
            value is not None
            for value in (
                self.analysis_run_id,
                self.analysis_input_receipt_id,
                self.analysis_input_receipt_fingerprint,
            )
        ) != has_exact_input:
            raise ValueError("batch input id, fingerprint, and run travel together")
        if exact_scope != has_exact_input:
            raise ValueError("only exact batches bind a direct analysis input and run")
        if exact_scope != (self.selection_revision_id is not None):
            raise ValueError("exact scope requires a selection revision receipt")
        if exact_scope != bool(self.selected_metric_keys):
            raise ValueError("exact scope requires a non-empty selected metric set")
        if not exact_scope and self.observations:
            raise ValueError("unknown selection scope cannot invent metric observations")

        observation_keys = tuple(
            observation.comparison_identity.metric_key
            for observation in self.observations
        )
        if len(observation_keys) != len(set(observation_keys)):
            raise ValueError("a batch may contain at most one observation per metric")
        if exact_scope and observation_keys != self.selected_metric_keys:
            raise ValueError("observations must exactly cover the selected metric set")
        if any(observation.revision_id != self.revision_id for observation in self.observations):
            raise ValueError("all observations must bind to the batch revision")
        if any(
            observation.analysis_run_id != self.analysis_run_id
            or observation.analysis_input_receipt_id
            != self.analysis_input_receipt_id
            or observation.analysis_input_receipt_fingerprint
            != self.analysis_input_receipt_fingerprint
            for observation in self.observations
        ):
            raise ValueError("all observations must bind the exact batch input and run")
        if any(
            observation.selection_state is not TemporalSelectionState.SELECTED
            for observation in self.observations
        ):
            raise ValueError("exact batch observations must be selected")
        if any(
            observation.observed_at > self.recorded_at
            for observation in self.observations
        ):
            raise ValueError("a batch cannot precede any contained observation")
        if exact_scope:
            if self.source_state is not TemporalSourceState.PRESENT:
                raise ValueError("prospective exact batches require a present batch receipt")
            if not self.observations:
                raise ValueError("present batches require observations")
        elif self.source_state is not TemporalSourceState.NO_POST_FLOOR_SOURCE:
            raise ValueError("missing selection receipts remain no-post-floor history")
        return self

    @property
    def fingerprint(self) -> str:
        """Derive the immutable batch fingerprint from its canonical payload."""

        return _canonical_digest(self)


class TemporalObservationBatchV2(TemporalObservationBatch):
    """Unsealed prospective batch with exact fingerprints for every parent."""

    contract_version: Literal[TEMPORAL_OBSERVATION_BATCH_V2_VERSION] = (
        TEMPORAL_OBSERVATION_BATCH_V2_VERSION
    )
    root_receipt_id: str
    root_receipt_fingerprint: str
    revision_fingerprint: str
    analysis_run_id: str
    analysis_run_fingerprint: str
    analysis_input_receipt_id: str
    analysis_input_receipt_fingerprint: str
    selection_revision_id: str
    selection_revision_fingerprint: str
    scope_state: Literal[TemporalScopeState.EXACT_SELECTION_RECEIPT] = (
        TemporalScopeState.EXACT_SELECTION_RECEIPT
    )
    source_state: Literal[TemporalSourceState.PRESENT] = TemporalSourceState.PRESENT
    selected_metric_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )
    observations: tuple[TemporalMetricObservationV2, ...] = Field(
        min_length=1, max_length=MAX_OBSERVATIONS
    )
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _v2_parent_digests = field_validator(
        "root_receipt_id",
        "root_receipt_fingerprint",
        "revision_fingerprint",
        "analysis_run_fingerprint",
        "selection_revision_fingerprint",
    )(_digest)

    @model_validator(mode="after")
    def exact_v2_observation_order(self) -> TemporalObservationBatchV2:
        observation_ids = tuple(item.observation_id for item in self.observations)
        if len(observation_ids) != len(set(observation_ids)):
            raise ValueError("batch observation ids must be unique")
        return self


class RepositoryTemporalBatchSealDraft(PersistenceRevalidatedModel):
    """Untrusted request to repository-verify one exact temporal batch.

    Public construction proves only internal graph consistency.  It cannot claim
    repository authorship.  A later persistence slice must authenticate this
    draft and issue a separate sealed receipt.  This draft grants no comparison,
    snapshot, activation, export, or remote-processing capability.
    """

    contract_version: Literal[REPOSITORY_TEMPORAL_BATCH_SEAL_DRAFT_VERSION] = (
        REPOSITORY_TEMPORAL_BATCH_SEAL_DRAFT_VERSION
    )
    seal_draft_id: str
    history_root: TemporalHistoryRootReceipt
    selection_revision: ProjectMetricSelectionRevisionV2
    analysis_input: AnalysisInputReceiptV2
    session_revision: SessionRevisionReceiptV3
    observation_batch: TemporalObservationBatchV2
    analysis_run_id: str
    analysis_run_fingerprint: str
    ordered_observation_ids: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_OBSERVATIONS
    )
    ordered_observation_fingerprints: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_OBSERVATIONS
    )
    requested_repository_verifier_version: str
    requested_repository_verifier_fingerprint: str
    drafted_at: datetime
    direct_receipts_only: Literal[True] = True
    legacy_backfill_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    issuance_required: Literal[True] = True
    persistence_state: Literal["untrusted_seal_draft"] = "untrusted_seal_draft"
    repository_verified: Literal[False] = False
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _seal_digests = field_validator(
        "seal_draft_id",
        "analysis_run_id",
        "analysis_run_fingerprint",
        "requested_repository_verifier_fingerprint",
    )(_digest)
    _seal_version = field_validator("requested_repository_verifier_version")(
        _safe_version
    )
    _drafted_at = field_validator("drafted_at")(_utc)

    @field_validator("ordered_observation_ids", "ordered_observation_fingerprints")
    @classmethod
    def canonical_ordered_digests(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(values) != len(set(values)):
            raise ValueError("ordered seal commitments must be unique")
        return tuple(_digest(value) for value in values)

    @model_validator(mode="after")
    def exact_repository_graph(self) -> RepositoryTemporalBatchSealDraft:
        root = self.history_root
        selection = self.selection_revision
        analysis_input = self.analysis_input
        revision = self.session_revision
        batch = self.observation_batch

        if (
            selection.root_receipt_id != root.root_receipt_id
            or selection.root_receipt_fingerprint != root.fingerprint
            or analysis_input.root_receipt_id != root.root_receipt_id
            or analysis_input.root_receipt_fingerprint != root.fingerprint
            or revision.root_receipt_id != root.root_receipt_id
            or revision.root_receipt_fingerprint != root.fingerprint
            or batch.root_receipt_id != root.root_receipt_id
            or batch.root_receipt_fingerprint != root.fingerprint
        ):
            raise ValueError("seal children must bind the exact history root")
        if len(
            {
                root.project_id,
                selection.project_id,
                analysis_input.project_id,
                revision.project_id,
                batch.project_id,
            }
        ) != 1:
            raise ValueError("seal children must share one project")
        if len({analysis_input.session_id, revision.session_id, batch.session_id}) != 1:
            raise ValueError("seal children must share one session")
        if (
            selection.effective_at < root.history_floor_at
            or selection.recorded_at < root.history_floor_at
            or analysis_input.analysis_window_started_at < root.history_floor_at
        ):
            raise ValueError("a prospective seal cannot include pre-floor history")
        if analysis_input.captured_at < selection.recorded_at:
            raise ValueError("analysis input cannot predate its selected metric scope")

        if (
            analysis_input.selection_revision_id != selection.selection_revision_id
            or analysis_input.selection_revision_fingerprint != selection.fingerprint
            or analysis_input.selection_scope_fingerprint
            != selection.metric_set_fingerprint
            or analysis_input.selected_metric_keys != selection.selected_metric_keys
            or analysis_input.metric_pack_key != selection.metric_pack_key
            or analysis_input.metric_pack_version != selection.metric_pack_version
            or analysis_input.metric_pack_sha256 != selection.metric_pack_sha256
            or analysis_input.metric_catalog_version
            != selection.metric_catalog_version
            or analysis_input.metric_catalog_sha256 != selection.metric_catalog_sha256
        ):
            raise ValueError("analysis input must bind the exact selection identity")

        if (
            revision.analysis_input_receipt_id != analysis_input.input_receipt_id
            or revision.analysis_input_receipt_fingerprint != analysis_input.fingerprint
            or revision.input_provenance_fingerprint
            != analysis_input.provenance_fingerprint
            or revision.analysis_run_id != analysis_input.analysis_run_id
            or revision.analysis_run_fingerprint
            != analysis_input.analysis_run_fingerprint
            or revision.selected_window_manifest_root
            != analysis_input.selected_window_manifest_root
            or revision.selected_window_manifest_entry_count
            != analysis_input.selected_window_manifest_entry_count
            or revision.analysis_window_fingerprint
            != analysis_input.analysis_window_fingerprint
            or revision.analysis_window_started_at
            != analysis_input.analysis_window_started_at
            or revision.analysis_window_ended_at
            != analysis_input.analysis_window_ended_at
            or revision.captured_at != analysis_input.captured_at
            or revision.provider != analysis_input.provider
            or revision.provider_adapter_version
            != analysis_input.provider_adapter_version
            or revision.provider_schema_version != analysis_input.provider_schema_version
            or revision.source_schema_version != analysis_input.source_schema_version
            or revision.content_schema_version != analysis_input.content_schema_version
            or revision.redactor_version != analysis_input.redactor_version
        ):
            raise ValueError("session revision must bind the exact analysis input")

        if (
            self.analysis_run_id != analysis_input.analysis_run_id
            or self.analysis_run_fingerprint
            != analysis_input.analysis_run_fingerprint
            or batch.analysis_run_id != analysis_input.analysis_run_id
            or batch.analysis_run_fingerprint
            != analysis_input.analysis_run_fingerprint
            or batch.analysis_input_receipt_id != analysis_input.input_receipt_id
            or batch.analysis_input_receipt_fingerprint != analysis_input.fingerprint
            or batch.selection_revision_id != selection.selection_revision_id
            or batch.selection_revision_fingerprint != selection.fingerprint
            or batch.revision_id != revision.revision_id
            or batch.revision_fingerprint != revision.fingerprint
            or batch.selected_metric_keys != analysis_input.selected_metric_keys
        ):
            raise ValueError("observation batch must bind the exact run and receipt graph")

        observation_ids = tuple(item.observation_id for item in batch.observations)
        observation_fingerprints = tuple(
            item.fingerprint for item in batch.observations
        )
        if (
            self.ordered_observation_ids != observation_ids
            or self.ordered_observation_fingerprints != observation_fingerprints
        ):
            raise ValueError("seal must commit the exact ordered batch observations")
        if tuple(
            item.comparison_identity.metric_key for item in batch.observations
        ) != analysis_input.selected_metric_keys:
            raise ValueError("sealed observations must exactly cover selected metrics")
        if any(
            item.revision_id != revision.revision_id
            or item.analysis_run_id != analysis_input.analysis_run_id
            or item.analysis_input_receipt_id != analysis_input.input_receipt_id
            or item.analysis_input_receipt_fingerprint != analysis_input.fingerprint
            for item in batch.observations
        ):
            raise ValueError("sealed observations must bind the exact revision and input")
        if any(
            item.comparison_identity.provider != analysis_input.provider
            or item.comparison_identity.provider_adapter_version
            != analysis_input.provider_adapter_version
            or item.comparison_identity.provider_schema_version
            != analysis_input.provider_schema_version
            or item.comparison_identity.source_schema_version
            != analysis_input.source_schema_version
            or item.comparison_identity.content_schema_version
            != analysis_input.content_schema_version
            or item.comparison_identity.redactor_version
            != analysis_input.redactor_version
            or item.comparison_identity.redactor_sha256
            != analysis_input.redactor_sha256
            or item.comparison_identity.preprocessing_version
            != analysis_input.preprocessing_version
            or item.comparison_identity.preprocessing_sha256
            != analysis_input.preprocessing_sha256
            or item.comparison_identity.router_version != analysis_input.router_version
            or item.comparison_identity.router_sha256 != analysis_input.router_sha256
            for item in batch.observations
        ):
            raise ValueError("sealed observations must preserve input provenance")
        if any(
            not (
                analysis_input.captured_at
                <= item.observed_at
                and revision.captured_at <= item.observed_at
                <= batch.recorded_at
            )
            for item in batch.observations
        ):
            raise ValueError("observation times must follow input capture and precede batch")
        if batch.recorded_at > self.drafted_at:
            raise ValueError("a repository seal draft cannot predate its batch")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TemporalCompletionProjection(PersistenceRevalidatedModel):
    """Cross-validated prospective capture, still unsealed until persistence.

    ``analysis_input.selected_metric_keys`` is the exact metric set of the
    identified analysis run.  The projection requires that run set, the project
    selection, the observation batch, and its observations all agree exactly.
    """

    contract_version: Literal[TEMPORAL_COMPLETION_PROJECTION_VERSION] = (
        TEMPORAL_COMPLETION_PROJECTION_VERSION
    )
    completion_projection_id: str
    history_root: TemporalHistoryRootReceipt
    selection_revision: ProjectMetricSelectionRevision
    analysis_input: AnalysisInputReceipt
    session_revision: SessionRevisionReceipt
    observation_batch: TemporalObservationBatch
    completed_at: datetime
    direct_receipts_only: Literal[True] = True
    legacy_backfill_allowed: Literal[False] = False
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _id = field_validator("completion_projection_id")(_digest)
    _completed = field_validator("completed_at")(_utc)

    @model_validator(mode="after")
    def exact_receipt_graph(self) -> TemporalCompletionProjection:
        root = self.history_root
        selection = self.selection_revision
        analysis_input = self.analysis_input
        revision = self.session_revision
        batch = self.observation_batch

        if selection.root_receipt_id != root.root_receipt_id or (
            selection.root_receipt_fingerprint != root.fingerprint
        ):
            raise ValueError("metric selection must bind the exact history root")
        if analysis_input.root_receipt_id != root.root_receipt_id or (
            analysis_input.root_receipt_fingerprint != root.fingerprint
        ):
            raise ValueError("analysis input must bind the exact history root")
        if revision.root_receipt_id != root.root_receipt_id or (
            revision.root_receipt_fingerprint != root.fingerprint
        ):
            raise ValueError("session revision must bind the exact history root")
        if len({root.project_id, selection.project_id, analysis_input.project_id,
                revision.project_id, batch.project_id}) != 1:
            raise ValueError("all completion receipts must share one project")
        if (
            selection.effective_at < root.history_floor_at
            or selection.recorded_at < root.history_floor_at
        ):
            raise ValueError("metric selection cannot predate the prospective floor")
        if analysis_input.analysis_window_started_at < root.history_floor_at:
            raise ValueError("direct input cannot include pre-floor history")
        if analysis_input.captured_at < selection.recorded_at:
            raise ValueError("analysis input cannot predate its metric selection")

        if (
            analysis_input.selection_revision_id != selection.selection_revision_id
            or analysis_input.selection_revision_fingerprint != selection.fingerprint
        ):
            raise ValueError("analysis input must bind the exact metric selection revision")
        if analysis_input.selected_metric_keys != selection.selected_metric_keys:
            raise ValueError("analysis-run metrics must exactly match project selection")
        if (
            revision.analysis_input_receipt_id != analysis_input.input_receipt_id
            or revision.analysis_input_receipt_fingerprint != analysis_input.fingerprint
        ):
            raise ValueError("session revision must bind the exact analysis input")
        if revision.input_provenance_fingerprint != analysis_input.provenance_fingerprint:
            raise ValueError("session revision must bind exact input provenance")
        copied_revision_fields = (
            (revision.session_id, analysis_input.session_id),
            (revision.analysis_window_fingerprint, analysis_input.analysis_window_fingerprint),
            (
                revision.analysis_window_fingerprint_version,
                analysis_input.analysis_window_fingerprint_version,
            ),
            (revision.analysis_window_started_at, analysis_input.analysis_window_started_at),
            (revision.analysis_window_ended_at, analysis_input.analysis_window_ended_at),
            (revision.captured_at, analysis_input.captured_at),
            (revision.provider, analysis_input.provider),
            (revision.provider_adapter_version, analysis_input.provider_adapter_version),
            (revision.provider_schema_version, analysis_input.provider_schema_version),
            (revision.source_schema_version, analysis_input.source_schema_version),
            (revision.content_schema_version, analysis_input.content_schema_version),
            (revision.redactor_version, analysis_input.redactor_version),
            (revision.event_count, analysis_input.captured_source_entry_count),
            (revision.persisted_prefix_root, analysis_input.source_manifest_fingerprint),
            (
                revision.persisted_prefix_event_count,
                analysis_input.captured_source_entry_count,
            ),
        )
        if any(left != right for left, right in copied_revision_fields):
            raise ValueError("session revision projection conflicts with direct input")

        if len({analysis_input.session_id, revision.session_id, batch.session_id}) != 1:
            raise ValueError("input, revision, and batch must share one session")
        if batch.revision_id != revision.revision_id:
            raise ValueError("observation batch must bind the exact session revision")
        if (
            batch.analysis_run_id != analysis_input.analysis_run_id
            or batch.analysis_input_receipt_id != analysis_input.input_receipt_id
            or batch.analysis_input_receipt_fingerprint != analysis_input.fingerprint
        ):
            raise ValueError("observation batch must bind the exact analysis input and run")
        if batch.selection_revision_id != selection.selection_revision_id:
            raise ValueError("observation batch must bind the exact metric selection")
        if batch.selected_metric_keys != analysis_input.selected_metric_keys:
            raise ValueError("batch metrics must exactly match analysis-run metrics")
        for observation in batch.observations:
            if (
                observation.analysis_run_id != analysis_input.analysis_run_id
                or observation.analysis_input_receipt_id
                != analysis_input.input_receipt_id
                or observation.analysis_input_receipt_fingerprint
                != analysis_input.fingerprint
            ):
                raise ValueError("every observation must bind the exact analysis input and run")
            identity = observation.comparison_identity
            identity_provenance = (
                (identity.provider, analysis_input.provider),
                (
                    identity.provider_adapter_version,
                    analysis_input.provider_adapter_version,
                ),
                (identity.provider_schema_version, analysis_input.provider_schema_version),
                (identity.source_schema_version, analysis_input.source_schema_version),
                (identity.content_schema_version, analysis_input.content_schema_version),
                (identity.redactor_version, analysis_input.redactor_version),
                (identity.redactor_sha256, analysis_input.redactor_sha256),
                (identity.preprocessing_version, analysis_input.preprocessing_version),
                (identity.preprocessing_sha256, analysis_input.preprocessing_sha256),
                (identity.router_version, analysis_input.router_version),
                (identity.router_sha256, analysis_input.router_sha256),
            )
            if any(left != right for left, right in identity_provenance):
                raise ValueError("observation identity conflicts with input provenance")
        if batch.recorded_at < revision.captured_at:
            raise ValueError("observations cannot be recorded before direct capture")
        if any(
            observation.observed_at < analysis_input.captured_at
            for observation in batch.observations
        ):
            raise ValueError("metric observations cannot predate direct capture")
        if self.completed_at < batch.recorded_at:
            raise ValueError("completion cannot predate its observation batch")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)


class TemporalSnapshotMaterializationRequest(StrictModel):
    project_id: str
    selection_revision_id: str
    selected_metric_keys: tuple[str, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )
    window: TemporalWindowSpec
    task_mix_policy_version: str
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator("project_id", "selection_revision_id")(_digest)
    _policy = field_validator("task_mix_policy_version")(_safe_version)

    @field_validator("selected_metric_keys")
    @classmethod
    def canonical_metrics(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_codes(values)


class TemporalSnapshotSpec(PersistenceRevalidatedModel):
    contract_version: Literal[TEMPORAL_SNAPSHOT_SPEC_VERSION] = (
        TEMPORAL_SNAPSHOT_SPEC_VERSION
    )
    request: TemporalSnapshotMaterializationRequest
    as_of: datetime
    as_of_source: Literal[SnapshotAsOfSource.SERVER_CLOCK] = (
        SnapshotAsOfSource.SERVER_CLOCK
    )
    history_floor_at: datetime
    source_manifest_fingerprint: str
    materializer_version: str
    aggregation_contract_version: str
    no_legacy_backfill: Literal[True] = True
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _times = field_validator("as_of", "history_floor_at")(_utc)
    _manifest = field_validator("source_manifest_fingerprint")(_digest)
    _versions = field_validator(
        "materializer_version", "aggregation_contract_version"
    )(_safe_version)

    @model_validator(mode="after")
    def server_bounded_window(self) -> TemporalSnapshotSpec:
        if self.history_floor_at > self.as_of:
            raise ValueError("history floor cannot follow the server as-of time")
        if (
            self.request.window.kind is TemporalWindowKind.CUSTOM
            and self.request.window.end_at is not None
            and self.request.window.end_at > self.as_of
        ):
            raise ValueError("custom windows cannot extend beyond the server as-of time")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_digest(self)

    @classmethod
    def revalidate_for_persistence(cls, value: Any) -> TemporalSnapshotSpec:
        """Revalidate plain values at every persistence read/write boundary."""

        return _revalidate_persistence_model(cls, value)


class TemporalSnapshotMetricReceipt(PersistenceRevalidatedModel):
    metric_key: str
    compatibility_state: SnapshotMetricCompatibilityState
    comparison_identity_fingerprints: tuple[str, ...] = Field(
        default=(), max_length=MAX_OBSERVATIONS
    )
    eligible_revision_count: NonNegativeInt
    selected_revision_count: NonNegativeInt
    not_selected_revision_count: NonNegativeInt
    selection_unknown_revision_count: NonNegativeInt
    present_source_count: NonNegativeInt
    not_requested_source_count: NonNegativeInt
    no_post_floor_source_count: NonNegativeInt
    source_missing_count: NonNegativeInt
    source_failed_count: NonNegativeInt
    source_incompatible_count: NonNegativeInt
    known_count: NonNegativeInt
    unknown_count: NonNegativeInt
    abstained_count: NonNegativeInt
    not_applicable_count: NonNegativeInt
    failed_count: NonNegativeInt
    incompatible_count: NonNegativeInt
    aggregate_values_omitted: Literal[True] = True
    materialization_trust: Literal[
        MaterializationTrustState.UNTRUSTED_UNTIL_MATERIALIZED
    ] = MaterializationTrustState.UNTRUSTED_UNTIL_MATERIALIZED
    comparison_allowed: Literal[False] = False

    _metric = field_validator("metric_key")(_safe_code)

    @field_validator("comparison_identity_fingerprints")
    @classmethod
    def canonical_identities(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        return _canonical_digests(values, allow_empty=True)

    @model_validator(mode="after")
    def coherent_counts_and_compatibility(self) -> TemporalSnapshotMetricReceipt:
        selection_classified = sum(
            (
                self.selected_revision_count,
                self.not_selected_revision_count,
                self.selection_unknown_revision_count,
            )
        )
        source_classified = sum(
            (
                self.present_source_count,
                self.not_requested_source_count,
                self.no_post_floor_source_count,
                self.source_missing_count,
                self.source_failed_count,
                self.source_incompatible_count,
            )
        )
        value_classified = sum(
            (
                self.known_count,
                self.unknown_count,
                self.abstained_count,
                self.not_applicable_count,
                self.failed_count,
                self.incompatible_count,
            )
        )
        if any(
            count != self.eligible_revision_count
            for count in (selection_classified, source_classified, value_classified)
        ):
            raise ValueError("selection, source, and value axes must each cover eligibility")
        if self.not_requested_source_count != self.not_selected_revision_count:
            raise ValueError("not-requested sources must exactly match unselected scope")
        if self.no_post_floor_source_count != self.selection_unknown_revision_count:
            raise ValueError("unknown selection must remain no-post-floor source state")
        selected_sources = sum(
            (
                self.present_source_count,
                self.source_missing_count,
                self.source_failed_count,
                self.source_incompatible_count,
            )
        )
        if selected_sources != self.selected_revision_count:
            raise ValueError("selected scope must map to an explicit selected-source state")
        mandatory_unknown = sum(
            (
                self.not_requested_source_count,
                self.no_post_floor_source_count,
                self.source_missing_count,
            )
        )
        if self.unknown_count < mandatory_unknown:
            raise ValueError("missing or absent sources must remain unknown values")
        present_unknown = self.unknown_count - mandatory_unknown
        if sum(
            (
                self.known_count,
                present_unknown,
                self.abstained_count,
                self.not_applicable_count,
            )
        ) != self.present_source_count:
            raise ValueError("present sources must map to a permitted present value state")
        if self.failed_count != self.source_failed_count:
            raise ValueError("failed sources must exactly map to failed values")
        if self.incompatible_count != self.source_incompatible_count:
            raise ValueError("incompatible sources must exactly map to incompatible values")
        if self.compatibility_state is SnapshotMetricCompatibilityState.COMPATIBLE:
            if len(self.comparison_identity_fingerprints) != 1:
                raise ValueError("compatible aggregates require exactly one identity")
        elif self.compatibility_state is SnapshotMetricCompatibilityState.DISCONTINUITY:
            if len(self.comparison_identity_fingerprints) < 2:
                raise ValueError("discontinuities require at least two identities")
        elif len(self.comparison_identity_fingerprints) > 1 or self.known_count:
            raise ValueError("no-comparison metrics cannot claim comparable known values")
        return self

    @classmethod
    def revalidate_for_persistence(
        cls, value: Any
    ) -> TemporalSnapshotMetricReceipt:
        """Revalidate plain values at every persistence read/write boundary."""

        return _revalidate_persistence_model(cls, value)


class TemporalSnapshotReceipt(PersistenceRevalidatedModel):
    contract_version: Literal[TEMPORAL_SNAPSHOT_RECEIPT_VERSION] = (
        TEMPORAL_SNAPSHOT_RECEIPT_VERSION
    )
    snapshot_id: str
    spec: TemporalSnapshotSpec
    coverage_state: HistoryCoverageState
    effective_window_start_at: datetime | None = None
    effective_window_end_at: datetime | None = None
    selected_session_count: NonNegativeInt
    eligible_revision_count: NonNegativeInt
    included_revision_count: NonNegativeInt
    omitted_revision_count: NonNegativeInt
    present_batch_revision_count: NonNegativeInt
    metric_receipts: tuple[TemporalSnapshotMetricReceipt, ...] = Field(
        min_length=1, max_length=MAX_METRICS
    )
    materialized_at: datetime
    materialization_trust: Literal[
        MaterializationTrustState.UNTRUSTED_UNTIL_MATERIALIZED
    ] = MaterializationTrustState.UNTRUSTED_UNTIL_MATERIALIZED
    repository_verification_required: Literal[True] = True
    sealed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    legacy_backfill_performed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _id = field_validator("snapshot_id")(_digest)
    _materialized = field_validator("materialized_at")(_utc)

    @field_validator("effective_window_start_at", "effective_window_end_at")
    @classmethod
    def optional_window_time(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def immutable_snapshot_shape(self) -> TemporalSnapshotReceipt:
        if self.materialized_at < self.spec.as_of:
            raise ValueError("materialization cannot precede the server as-of time")
        if (self.effective_window_start_at is None) != (
            self.effective_window_end_at is None
        ):
            raise ValueError("effective window bounds must be present together")
        if self.effective_window_start_at is not None:
            if self.effective_window_start_at < self.spec.history_floor_at:
                raise ValueError("effective history cannot precede the declared floor")
            if self.effective_window_end_at is None or (
                self.effective_window_start_at > self.effective_window_end_at
                or self.effective_window_end_at > self.spec.as_of
            ):
                raise ValueError("effective window bounds must be ordered before as-of")
        if (self.included_revision_count > 0) != (
            self.effective_window_start_at is not None
        ):
            raise ValueError("included history requires an explicit effective window")
        if self.included_revision_count + self.omitted_revision_count != (
            self.eligible_revision_count
        ):
            raise ValueError("included and omitted revisions must cover eligibility")
        if self.eligible_revision_count == 0:
            if self.selected_session_count != 0:
                raise ValueError("empty eligibility cannot claim selected sessions")
        elif not 1 <= self.selected_session_count <= self.eligible_revision_count:
            raise ValueError(
                "selected-session count must be a distinct-session projection of eligibility"
            )
        if self.present_batch_revision_count > self.included_revision_count:
            raise ValueError("present batch revisions must be included exactly once")

        metric_keys = tuple(receipt.metric_key for receipt in self.metric_receipts)
        if metric_keys != tuple(sorted(metric_keys)) or len(metric_keys) != len(
            set(metric_keys)
        ):
            raise ValueError("snapshot metric receipts must be unique and sorted")
        if any(
            receipt.eligible_revision_count != self.eligible_revision_count
            for receipt in self.metric_receipts
        ):
            raise ValueError("every metric receipt must cover global revision eligibility")
        if any(
            receipt.present_source_count > self.present_batch_revision_count
            for receipt in self.metric_receipts
        ):
            raise ValueError("metric present sources cannot exceed materialized batches")
        if any(
            (
                receipt.selected_revision_count
                + receipt.not_selected_revision_count
                != self.present_batch_revision_count
            )
            or receipt.selection_unknown_revision_count
            != (
                self.eligible_revision_count
                - self.present_batch_revision_count
            )
            for receipt in self.metric_receipts
        ):
            raise ValueError(
                "each metric selection axis must exactly partition present-batch and unknown revisions"
            )
        if metric_keys != self.spec.request.selected_metric_keys:
            raise ValueError("metric receipts must exactly cover the snapshot selection")

        if self.coverage_state is HistoryCoverageState.COMPLETE:
            if self.omitted_revision_count != 0 or self.included_revision_count == 0:
                raise ValueError("complete history cannot omit eligible revisions")
        elif self.coverage_state is HistoryCoverageState.LEFT_CENSORED:
            if (
                self.omitted_revision_count != 0
                or self.included_revision_count == 0
                or self.effective_window_start_at != self.spec.history_floor_at
            ):
                raise ValueError("left-censored history must visibly begin at its floor")
        elif self.coverage_state is HistoryCoverageState.PARTIAL:
            if self.omitted_revision_count == 0 or self.included_revision_count == 0:
                raise ValueError("partial history must identify omitted revisions")
        elif self.coverage_state is HistoryCoverageState.LEFT_CENSORED_PARTIAL:
            if (
                self.omitted_revision_count == 0
                or self.included_revision_count == 0
                or self.effective_window_start_at != self.spec.history_floor_at
            ):
                raise ValueError(
                    "left-censored partial history must expose its floor and omissions"
                )
        elif self.coverage_state is HistoryCoverageState.NO_POST_FLOOR_OBSERVATIONS:
            if self.included_revision_count != 0 or self.present_batch_revision_count != 0:
                raise ValueError("empty post-floor history cannot claim observations")
            if self.effective_window_start_at is not None:
                raise ValueError("empty post-floor history has no effective window")
        return self

    @classmethod
    def from_spec_and_children(
        cls,
        *,
        snapshot_id: str,
        spec: TemporalSnapshotSpec,
        coverage_state: HistoryCoverageState,
        effective_window_start_at: datetime | None,
        effective_window_end_at: datetime | None,
        selected_session_count: int,
        eligible_revision_count: int,
        included_revision_count: int,
        omitted_revision_count: int,
        present_batch_revision_count: int,
        metric_receipts: tuple[TemporalSnapshotMetricReceipt, ...],
        materialized_at: datetime,
    ) -> TemporalSnapshotReceipt:
        """Reconstruct an untrusted receipt from its complete materialization inputs."""

        return cls.revalidate_for_persistence(
            {
                "snapshot_id": snapshot_id,
                "spec": spec,
                "coverage_state": coverage_state,
                "effective_window_start_at": effective_window_start_at,
                "effective_window_end_at": effective_window_end_at,
                "selected_session_count": selected_session_count,
                "eligible_revision_count": eligible_revision_count,
                "included_revision_count": included_revision_count,
                "omitted_revision_count": omitted_revision_count,
                "present_batch_revision_count": present_batch_revision_count,
                "metric_receipts": metric_receipts,
                "materialized_at": materialized_at,
            }
        )

    @property
    def spec_fingerprint(self) -> str:
        return self.spec.fingerprint

    @property
    def snapshot_fingerprint(self) -> str:
        return _canonical_digest(self)

    @classmethod
    def revalidate_for_persistence(cls, value: Any) -> TemporalSnapshotReceipt:
        """Recursively revalidate nested spec and metrics for persistence."""

        return _revalidate_persistence_model(cls, value)


class CompatibilityBoundary(PersistenceRevalidatedModel):
    contract_version: Literal[COMPATIBILITY_BOUNDARY_VERSION] = (
        COMPATIBILITY_BOUNDARY_VERSION
    )
    boundary_id: str
    project_id: str
    from_snapshot_id: str
    to_snapshot_id: str
    from_as_of: datetime
    to_as_of: datetime
    from_identity: MetricComparisonIdentity
    to_identity: MetricComparisonIdentity
    dimensions: tuple[CompatibilityDimension, ...] = Field(min_length=1)
    detected_at: datetime
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _ids = field_validator(
        "boundary_id", "project_id", "from_snapshot_id", "to_snapshot_id"
    )(_digest)
    _times = field_validator("from_as_of", "to_as_of", "detected_at")(_utc)

    @field_validator("dimensions")
    @classmethod
    def canonical_dimensions(
        cls, values: tuple[CompatibilityDimension, ...]
    ) -> tuple[CompatibilityDimension, ...]:
        if values != tuple(sorted(values, key=lambda value: value.value)) or len(
            values
        ) != len(set(values)):
            raise ValueError("compatibility dimensions must be unique and sorted")
        return values

    @model_validator(mode="after")
    def exact_boundary(self) -> CompatibilityBoundary:
        if self.from_snapshot_id == self.to_snapshot_id:
            raise ValueError("a boundary requires distinct snapshots")
        if self.from_as_of >= self.to_as_of or self.detected_at < self.to_as_of:
            raise ValueError("boundary timestamps must be strictly ordered")
        if self.from_identity.metric_key != self.to_identity.metric_key:
            raise ValueError("a compatibility boundary cannot change metric keys")
        if self.from_identity.fingerprint == self.to_identity.fingerprint:
            raise ValueError("identical comparison identities have no boundary")

        expected: set[CompatibilityDimension] = set()
        if (
            self.from_identity.metric_definition_version,
            self.from_identity.metric_definition_sha256,
            self.from_identity.metric_question_version,
            self.from_identity.metric_question_sha256,
        ) != (
            self.to_identity.metric_definition_version,
            self.to_identity.metric_definition_sha256,
            self.to_identity.metric_question_version,
            self.to_identity.metric_question_sha256,
        ):
            expected.add(CompatibilityDimension.METRIC_CONTRACT)
        if (
            self.from_identity.value_kind,
            self.from_identity.unit_code,
            self.from_identity.direction,
            self.from_identity.aggregation_semantics,
            self.from_identity.exposure_unit_code,
            self.from_identity.trend,
            self.from_identity.interval_method_version,
        ) != (
            self.to_identity.value_kind,
            self.to_identity.unit_code,
            self.to_identity.direction,
            self.to_identity.aggregation_semantics,
            self.to_identity.exposure_unit_code,
            self.to_identity.trend,
            self.to_identity.interval_method_version,
        ):
            expected.add(CompatibilityDimension.VALUE_SEMANTICS)
        if (
            self.from_identity.evidence_tier,
            self.from_identity.evidence_contract_version,
        ) != (
            self.to_identity.evidence_tier,
            self.to_identity.evidence_contract_version,
        ):
            expected.add(CompatibilityDimension.EVIDENCE_CONTRACT)
        if (
            self.from_identity.estimator_kind,
            self.from_identity.estimator_plan_version,
            self.from_identity.estimator_plan_sha256,
            self.from_identity.estimator_lifecycle,
            self.from_identity.activation_receipt_sha256,
            self.from_identity.preprocessing_version,
            self.from_identity.preprocessing_sha256,
            self.from_identity.prompt_template_version,
            self.from_identity.prompt_template_sha256,
            self.from_identity.rubric_version,
            self.from_identity.rubric_sha256,
            self.from_identity.reasoning_effort,
            self.from_identity.router_version,
            self.from_identity.router_sha256,
        ) != (
            self.to_identity.estimator_kind,
            self.to_identity.estimator_plan_version,
            self.to_identity.estimator_plan_sha256,
            self.to_identity.estimator_lifecycle,
            self.to_identity.activation_receipt_sha256,
            self.to_identity.preprocessing_version,
            self.to_identity.preprocessing_sha256,
            self.to_identity.prompt_template_version,
            self.to_identity.prompt_template_sha256,
            self.to_identity.rubric_version,
            self.to_identity.rubric_sha256,
            self.to_identity.reasoning_effort,
            self.to_identity.router_version,
            self.to_identity.router_sha256,
        ):
            expected.add(CompatibilityDimension.ESTIMATOR_CONFIGURATION)
        if (
            self.from_identity.model_provider,
            self.from_identity.requested_model_key,
            self.from_identity.requested_model_revision,
            self.from_identity.served_model_key,
            self.from_identity.served_model_revision,
            self.from_identity.served_model_fallback,
            self.from_identity.model_weight_identity_state,
            self.from_identity.model_weight_set_sha256,
            self.from_identity.tokenizer_key,
            self.from_identity.tokenizer_revision,
            self.from_identity.tokenizer_identity_state,
            self.from_identity.tokenizer_sha256,
            self.from_identity.model_license_code,
        ) != (
            self.to_identity.model_provider,
            self.to_identity.requested_model_key,
            self.to_identity.requested_model_revision,
            self.to_identity.served_model_key,
            self.to_identity.served_model_revision,
            self.to_identity.served_model_fallback,
            self.to_identity.model_weight_identity_state,
            self.to_identity.model_weight_set_sha256,
            self.to_identity.tokenizer_key,
            self.to_identity.tokenizer_revision,
            self.to_identity.tokenizer_identity_state,
            self.to_identity.tokenizer_sha256,
            self.to_identity.model_license_code,
        ):
            expected.add(CompatibilityDimension.MODEL_IDENTITY)
        if (
            self.from_identity.calibration_version,
            self.from_identity.calibration_sha256,
        ) != (
            self.to_identity.calibration_version,
            self.to_identity.calibration_sha256,
        ):
            expected.add(CompatibilityDimension.CALIBRATION)
        if (
            self.from_identity.provider,
            self.from_identity.provider_adapter_version,
            self.from_identity.provider_schema_version,
            self.from_identity.source_schema_version,
            self.from_identity.content_schema_version,
        ) != (
            self.to_identity.provider,
            self.to_identity.provider_adapter_version,
            self.to_identity.provider_schema_version,
            self.to_identity.source_schema_version,
            self.to_identity.content_schema_version,
        ):
            expected.add(CompatibilityDimension.PROVIDER_SCHEMA)
        if (
            self.from_identity.redactor_version,
            self.from_identity.redactor_sha256,
            self.from_identity.privacy_policy_version,
        ) != (
            self.to_identity.redactor_version,
            self.to_identity.redactor_sha256,
            self.to_identity.privacy_policy_version,
        ):
            expected.add(CompatibilityDimension.PRIVACY_REDACTOR)
        if set(self.dimensions) != expected:
            raise ValueError("boundary dimensions must exactly describe identity changes")
        return self


__all__ = [
    "ANALYSIS_INPUT_RECEIPT_VERSION",
    "ANALYSIS_INPUT_RECEIPT_V2_VERSION",
    "APPEND_PREFIX_PROOF_RECEIPT_VERSION",
    "COMPATIBILITY_BOUNDARY_VERSION",
    "HALF_OPEN_WINDOW_BOUNDARY",
    "KEYED_SELECTED_REDACTED_MESSAGE_WINDOW_VERSION",
    "MAX_LAST_N",
    "POST_FLOOR_OBSERVED_ALLOWLISTED_SOURCE_MANIFEST_VERSION",
    "PROJECT_METRIC_SELECTION_REVISION_VERSION",
    "PROJECT_METRIC_SELECTION_REVISION_V2_VERSION",
    "REPOSITORY_TEMPORAL_BATCH_SEAL_DRAFT_VERSION",
    "SELECTED_WINDOW_MANIFEST_VERSION",
    "SESSION_REVISION_RECEIPT_VERSION",
    "SESSION_REVISION_RECEIPT_V3_VERSION",
    "TEMPORAL_COMPLETION_PROJECTION_VERSION",
    "TEMPORAL_HISTORY_CONTRACT_VERSION",
    "TEMPORAL_HISTORY_ROOT_RECEIPT_VERSION",
    "TEMPORAL_METRIC_OBSERVATION_V2_VERSION",
    "TEMPORAL_OBSERVATION_BATCH_VERSION",
    "TEMPORAL_OBSERVATION_BATCH_V2_VERSION",
    "TEMPORAL_SNAPSHOT_RECEIPT_VERSION",
    "TEMPORAL_SNAPSHOT_SPEC_VERSION",
    "AnalysisInputCaptureSource",
    "AnalysisInputCompleteness",
    "AnalysisInputExtractionCompleteness",
    "AnalysisInputReceipt",
    "AnalysisInputReceiptV2",
    "AnalysisInputSelectionCoverage",
    "AppendPrefixProofReceipt",
    "AppendVerificationState",
    "ArtifactIdentityState",
    "AnalysisWindowFingerprintBasis",
    "AnalysisWindowFingerprintBasisV2",
    "CompatibilityBoundary",
    "CompatibilityDimension",
    "CountExposureObservationValue",
    "DistributionSampleObservationValue",
    "EstimatorIdentityKind",
    "EstimatorLifecycleState",
    "EvidenceTier",
    "EvidenceCoverageEligibility",
    "EvidenceCoverageState",
    "FractionObservationValue",
    "HistoryFloorSource",
    "HistoryCoverageState",
    "MaterializationTrustState",
    "MetricComparisonIdentity",
    "MetricDirection",
    "ModelProviderKind",
    "PrefixProofVerifier",
    "ProjectMetricSelectionRevision",
    "ProjectMetricSelectionRevisionV2",
    "ProjectMetricSelectionAuthorityKind",
    "ProjectMetricSelectionSource",
    "ReasoningEffort",
    "RevisionEffectiveTimeBasis",
    "SampledProportionObservationValue",
    "SessionRevisionProvenance",
    "SessionRevisionRelation",
    "SessionRevisionRelationV3",
    "SessionRevisionReceipt",
    "SessionRevisionReceiptV3",
    "SnapshotAsOfSource",
    "SnapshotMetricCompatibilityState",
    "TemporalAggregationSemantics",
    "TemporalCompletionProjection",
    "TemporalHistoryRootReceipt",
    "TemporalMetricObservation",
    "TemporalMetricObservationV2",
    "TemporalObservationBatch",
    "TemporalObservationBatchV2",
    "TemporalObservationValue",
    "TemporalScopeState",
    "TemporalSelectionState",
    "TemporalSnapshotMaterializationRequest",
    "TemporalSnapshotMetricReceipt",
    "TemporalSnapshotReceipt",
    "TemporalSnapshotSpec",
    "TemporalSourceState",
    "TemporalTrendMethod",
    "TemporalTrendSpec",
    "TemporalUncertainty",
    "TemporalValueKind",
    "TemporalValueState",
    "TemporalWindowKind",
    "TemporalWindowSpec",
    "RepositoryTemporalBatchSealDraft",
]
