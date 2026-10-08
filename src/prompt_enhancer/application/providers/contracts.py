"""Provider-neutral compatibility contracts for trusted local integrations.

These contracts describe *how* a built-in provider surface is decoded without
holding a transport, adapter factory, filesystem path, provider payload, or any
other runtime capability.  Provider identities are validated stable strings
rather than a closed enum so adding a built-in such as Cursor does not require a
database-wide enum migration.  The composition root remains responsible for
deciding which identities are actually trusted and registered.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
import re

from pydantic import Field, field_validator, model_validator

from ...domain import SAFE_VERSION_PATTERN, StrictModel


MAX_PROVIDER_CAPABILITIES = 64
MAX_COMPATIBILITY_REASONS = 32
MAX_TESTED_PROVIDER_VERSIONS = 64

_PROVIDER_KEY_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SHA256_PATTERN = re.compile(r"^[a-f0-9]{64}$")


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("provider provenance must use safe version identifiers")
    return value


def _aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("compatibility timestamps must include a timezone")
    return value.astimezone(UTC)


class ProviderSurface(StrEnum):
    """Separately negotiable, least-capability provider surfaces."""

    CATALOG = "catalog"
    DISPLAY_LABELS = "display_labels"
    OPERATIONAL_EVENTS = "operational_events"
    TEXT_WINDOW = "text_window"
    LIVE_TELEMETRY = "live_telemetry"


class CapabilityKey(StrEnum):
    """Provider facts that downstream use cases may depend on explicitly.

    The ``*_opportunities`` and ``*_links`` members are deliberately separate
    from the evidence-record members above them.  Being able to *observe* a
    verification event is not the same authority as being able to *enumerate*
    the eligible verification tasks of a session, and neither implies the
    authority to say which requirement a given receipt belongs to.  An
    objective metric denominator may only come from a decoder that declares the
    matching enumeration capability, and an evidence link may only be read from
    a decoder that declares the matching link capability.  A decoder that
    declares neither can still contribute evidence records; its objective
    contracts simply stay unknown instead of borrowing an invented denominator.
    """

    SESSION_LIST = "session_list"
    SESSION_LABELS = "session_labels"
    OPERATIONAL_EVENTS = "operational_events"
    USER_MESSAGES = "user_messages"
    AGENT_MESSAGES = "agent_messages"
    PLAN_MESSAGES = "plan_messages"
    TOOL_EVENTS = "tool_events"
    DECISION_EVENTS = "decision_events"
    FEEDBACK_MESSAGES = "feedback_messages"
    VERIFICATION_EVENTS = "verification_events"
    EVENT_TIMING = "event_timing"
    TOKEN_USAGE = "token_usage"
    LIVE_UPDATES = "live_updates"
    REQUIREMENT_OPPORTUNITIES = "requirement_opportunities"
    HYPOTHESIS_OPPORTUNITIES = "hypothesis_opportunities"
    MATERIAL_CLAIM_OPPORTUNITIES = "material_claim_opportunities"
    VERIFICATION_TASK_OPPORTUNITIES = "verification_task_opportunities"
    REQUIREMENT_EVIDENCE_LINKS = "requirement_evidence_links"
    HYPOTHESIS_EVIDENCE_LINKS = "hypothesis_evidence_links"
    MATERIAL_CLAIM_EVIDENCE_LINKS = "material_claim_evidence_links"
    VERIFICATION_TASK_EVIDENCE_LINKS = "verification_task_evidence_links"


class CapabilityState(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class CompatibilityState(StrEnum):
    """Compatibility of one provider surface, never the whole provider."""

    EXACT = "exact"
    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    UNTESTED = "untested"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


class ExtractionCompletenessState(StrEnum):
    COMPLETE = "complete"
    PARTIAL = "partial"
    UNKNOWN = "unknown"
    NONE = "none"


class SchemaArtifactKind(StrEnum):
    DOCUMENTED = "documented"
    GENERATED = "generated"
    MINIMIZED = "minimized"
    SYNTHETIC = "synthetic"


class CompatibilityReasonCode(StrEnum):
    """Closed, content-free diagnostics safe to persist and display."""

    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_VERSION_UNKNOWN = "provider_version_unknown"
    PROVIDER_VERSION_UNTESTED = "provider_version_untested"
    SCHEMA_ARTIFACT_UNKNOWN = "schema_artifact_unknown"
    SCHEMA_FAMILY_UNSUPPORTED = "schema_family_unsupported"
    REQUIRED_FIELD_MISSING = "required_field_missing"
    FIELD_TYPE_MISMATCH = "field_type_mismatch"
    UNKNOWN_UNION_VARIANT = "unknown_union_variant"
    OPTIONAL_CAPABILITY_MISSING = "optional_capability_missing"
    PROTOCOL_UNSUPPORTED = "protocol_unsupported"
    PROTOCOL_VIOLATION = "protocol_violation"
    RESOURCE_LIMIT = "resource_limit"
    TIMEOUT = "timeout"
    DECODER_FAILED = "decoder_failed"
    COMPLETE_DELIVERY_UNPROVEN = "complete_delivery_unproven"
    EPHEMERAL_DESCRIPTORS_UNAVAILABLE = "ephemeral_descriptors_unavailable"
    SOURCE_BOUNDARY_INVALID = "source_boundary_invalid"
    RECEIVER_CLOCK_AMBIGUOUS = "receiver_clock_ambiguous"


class ProviderIdentity(StrictModel):
    """Stable public integration key; not an account or installation identity."""

    key: str = Field(min_length=1, max_length=64)

    @field_validator("key")
    @classmethod
    def safe_provider_key(cls, value: str) -> str:
        if _PROVIDER_KEY_PATTERN.fullmatch(value) is None:
            raise ValueError("provider keys must be lowercase safe identifiers")
        return value


class SchemaArtifactProvenance(StrictModel):
    """Content-free identity of the schema material used by a decoder."""

    artifact_key: str
    artifact_version: str
    kind: SchemaArtifactKind
    checksum_sha256: str | None = None

    _validate_versions = field_validator("artifact_key", "artifact_version")(
        _safe_version
    )

    @field_validator("checksum_sha256")
    @classmethod
    def safe_checksum(cls, value: str | None) -> str | None:
        if value is not None and _SHA256_PATTERN.fullmatch(value) is None:
            raise ValueError("schema artifact checksums must be lowercase SHA-256")
        return value


class DecoderDescriptor(StrictModel):
    """Versioned, declarative identity of one trusted built-in decoder."""

    provider: ProviderIdentity
    surface: ProviderSurface
    adapter_version: str
    decoder_key: str
    decoder_version: str
    wire_schema_family: str
    canonical_schema_version: str
    schema_artifact: SchemaArtifactProvenance
    capabilities: tuple[CapabilityKey, ...] = Field(
        min_length=1,
        max_length=MAX_PROVIDER_CAPABILITIES,
    )
    tested_provider_versions: tuple[str, ...] = Field(
        default=(),
        max_length=MAX_TESTED_PROVIDER_VERSIONS,
    )

    _validate_versions = field_validator(
        "adapter_version",
        "decoder_key",
        "decoder_version",
        "wire_schema_family",
        "canonical_schema_version",
    )(_safe_version)

    @field_validator("capabilities")
    @classmethod
    def unique_capabilities(
        cls, values: tuple[CapabilityKey, ...]
    ) -> tuple[CapabilityKey, ...]:
        if len(set(values)) != len(values):
            raise ValueError("decoder capabilities cannot contain duplicates")
        return values

    @field_validator("tested_provider_versions")
    @classmethod
    def safe_tested_versions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(values)) != len(values):
            raise ValueError("tested provider versions cannot contain duplicates")
        return tuple(_safe_version(value) for value in values)

    @property
    def identity(self) -> tuple[str, ProviderSurface, str, str]:
        return (
            self.provider.key,
            self.surface,
            self.decoder_key,
            self.decoder_version,
        )


class CompatibilityReason(StrictModel):
    """A bounded diagnostic count with no provider-controlled text."""

    code: CompatibilityReasonCode
    count: int = Field(default=1, ge=1, le=10_000_000)


class CapabilityObservation(StrictModel):
    key: CapabilityKey
    state: CapabilityState
    reason_code: CompatibilityReasonCode | None = None

    @model_validator(mode="after")
    def reason_matches_state(self) -> CapabilityObservation:
        if self.state is CapabilityState.SUPPORTED:
            if self.reason_code is not None:
                raise ValueError("supported capabilities cannot contain a failure reason")
        elif self.reason_code is None:
            raise ValueError("non-supported capabilities require a safe reason code")
        return self


class ExtractionCompleteness(StrictModel):
    """Coverage of an ephemeral decoder projection, not a quality score."""

    state: ExtractionCompletenessState
    observed_units: int = Field(ge=0, le=10_000_000)
    eligible_units: int | None = Field(default=None, ge=0, le=10_000_000)
    unknown_units: int = Field(default=0, ge=0, le=10_000_000)
    coverage: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def validate_completeness(self) -> ExtractionCompleteness:
        if self.state is ExtractionCompletenessState.NONE:
            if (
                self.observed_units != 0
                or self.eligible_units not in (None, 0)
                or self.unknown_units != 0
                or self.coverage is not None
            ):
                raise ValueError("no extraction cannot claim observations or coverage")
            return self

        if self.state is ExtractionCompletenessState.UNKNOWN:
            if self.eligible_units is not None or self.coverage is not None:
                raise ValueError("unknown extraction cannot claim a denominator")
            return self

        if self.eligible_units is None:
            raise ValueError("complete and partial extraction require a denominator")
        if self.observed_units > self.eligible_units:
            raise ValueError("observed extraction units cannot exceed eligible units")
        if self.unknown_units > self.eligible_units - self.observed_units:
            raise ValueError("unknown units must belong to the unobserved denominator")
        expected_coverage = (
            None
            if self.eligible_units == 0
            else self.observed_units / self.eligible_units
        )
        if expected_coverage is None:
            if self.coverage is not None:
                raise ValueError("empty extraction has no numeric coverage")
        elif self.coverage is None or abs(self.coverage - expected_coverage) > 1e-9:
            raise ValueError("extraction coverage must match observed over eligible")

        if self.state is ExtractionCompletenessState.COMPLETE:
            if self.observed_units != self.eligible_units or self.unknown_units != 0:
                raise ValueError("complete extraction cannot omit or unknown units")
        elif self.observed_units == self.eligible_units:
            raise ValueError("partial extraction must identify an incomplete unit")
        return self


class ProviderCompatibilityReport(StrictModel):
    """Immutable, content-free result for exactly one registered surface."""

    descriptor: DecoderDescriptor
    provider_version: str
    state: CompatibilityState
    capabilities: tuple[CapabilityObservation, ...] = Field(
        min_length=1,
        max_length=MAX_PROVIDER_CAPABILITIES,
    )
    extraction: ExtractionCompleteness
    reasons: tuple[CompatibilityReason, ...] = Field(
        default=(),
        max_length=MAX_COMPATIBILITY_REASONS,
    )
    checked_at: datetime

    _validate_provider_version = field_validator("provider_version")(_safe_version)
    _validate_checked_at = field_validator("checked_at")(_aware_utc)

    @model_validator(mode="after")
    def validate_report(self) -> ProviderCompatibilityReport:
        capability_keys = tuple(item.key for item in self.capabilities)
        if len(set(capability_keys)) != len(capability_keys):
            raise ValueError("compatibility capabilities cannot contain duplicates")
        if set(capability_keys) != set(self.descriptor.capabilities):
            raise ValueError(
                "compatibility capabilities must match the decoder descriptor"
            )

        reason_codes = tuple(item.code for item in self.reasons)
        if len(set(reason_codes)) != len(reason_codes):
            raise ValueError("compatibility reasons cannot contain duplicates")
        report_reason_codes = set(reason_codes)
        capability_reason_codes = {
            item.reason_code
            for item in self.capabilities
            if item.reason_code is not None
        }
        if not capability_reason_codes.issubset(report_reason_codes):
            raise ValueError("capability reasons must be represented in report reasons")

        all_supported = all(
            item.state is CapabilityState.SUPPORTED for item in self.capabilities
        )
        no_supported = all(
            item.state is not CapabilityState.SUPPORTED for item in self.capabilities
        )
        completeness = self.extraction.state

        if self.state is CompatibilityState.EXACT:
            if (
                completeness is not ExtractionCompletenessState.COMPLETE
                or not all_supported
                or self.reasons
            ):
                raise ValueError("exact compatibility requires complete clean support")
        elif self.state is CompatibilityState.COMPATIBLE:
            if completeness is not ExtractionCompletenessState.COMPLETE or not all_supported:
                raise ValueError("compatible schemas require complete supported extraction")
        elif self.state is CompatibilityState.DEGRADED:
            if completeness is ExtractionCompletenessState.NONE:
                raise ValueError("degraded compatibility must retain some extraction")
            if all_supported and completeness is ExtractionCompletenessState.COMPLETE:
                raise ValueError("degraded compatibility requires an observable limitation")
            if not self.reasons:
                raise ValueError("degraded compatibility requires a safe reason")
        elif self.state is CompatibilityState.UNTESTED:
            if completeness not in {
                ExtractionCompletenessState.UNKNOWN,
                ExtractionCompletenessState.NONE,
            }:
                raise ValueError("untested compatibility cannot claim measured extraction")
            if not no_supported:
                raise ValueError("untested compatibility cannot claim decoded capabilities")
            if not self.reasons:
                raise ValueError("untested compatibility requires a safe reason")
        elif self.state is CompatibilityState.INCOMPATIBLE:
            if completeness is not ExtractionCompletenessState.NONE or not no_supported:
                raise ValueError("incompatible schemas cannot expose decoded capabilities")
            if not self.reasons:
                raise ValueError("incompatible compatibility requires a safe reason")
        else:
            if completeness is not ExtractionCompletenessState.NONE or not no_supported:
                raise ValueError("unavailable providers cannot expose decoded capabilities")
            if CompatibilityReasonCode.PROVIDER_UNAVAILABLE not in report_reason_codes:
                raise ValueError("unavailable providers require the unavailable reason")
        return self
