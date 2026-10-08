"""The publication envelope: a closed, minimized, signed measurement report.

Every element of an envelope comes from a server-registered vocabulary or is a
bounded, quantized number:

- metric keys are an enumeration, and units are fixed per key;
- values are non-negative, capped, and quantized to the precision their unit
  allows, so an unbounded float cannot smuggle a payload in its mantissa;
- the definition and producer versions are enumerations of releases this build
  knows, not free strings;
- the period is a canonical bucket key, not a caller-chosen interval;
- timestamps are whole seconds.

This is a *minimized* surface. It is not a proof that nothing can be signalled:
a publisher still chooses which keys to send, what bounded values to put in
them, and when to send. That residual channel is low bandwidth and visible in
the audit log; it is not eliminated, and this module does not claim otherwise.
What it does prevent is any field carrying transcript text, prompts, snippets,
rationales, model output, or operator-supplied strings, because no field
accepts them.

Signing covers canonical bytes with a domain-separation prefix, so a signature
made for one schema version cannot be replayed against another.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import re
from typing import Literal, Mapping, Protocol

from pydantic import Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .contracts import (
    DeviceVerificationKey,
    SignatureAlgorithm,
    VisibilityScope,
)
from .periods import ReportingBucket


SNAPSHOT_ENVELOPE_SCHEMA_VERSION = "control-plane-snapshot-v2"
SNAPSHOT_SIGNING_DOMAIN = b"prompt-enhancer/control-plane-snapshot-v2"

MAX_ISSUE_DELAY = timedelta(days=31)
MAX_SIGNATURE_CHARACTERS = 128
MAX_OBSERVATION_COUNT = 1_000_000
BASE64_PATTERN = re.compile(r"^[A-Za-z0-9+/]{16,}={0,2}$")


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("snapshot identifiers must be HMAC pseudonyms")
    return value


def _optional_pseudonym(value: str | None) -> str | None:
    return None if value is None else _pseudonym(value)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("snapshot timestamps must be UTC")
    if value.microsecond:
        raise ValueError("snapshot timestamps are whole seconds")
    return value


class MeasurementDefinitionVersion(StrEnum):
    """Registered measurement definitions. Unlisted values are rejected."""

    COACHING_FREE_OPERATIONS_V1 = "control-plane-measurements-v1"


class ProducerAdapterVersion(StrEnum):
    """Registered producers. Unlisted values are rejected."""

    DEVELOPMENT_V1 = "development-producer-v1"


class MeasurementUnit(StrEnum):
    COUNT = "count"
    SECONDS = "seconds"
    TOKENS = "tokens"


# Per-unit ceiling and decimal precision. Both are part of the surface: an
# unbounded or arbitrarily precise number is a wider channel than a bounded,
# quantized one, and no honest operational measurement needs either.
UNIT_LIMITS: Mapping[MeasurementUnit, tuple[float, int]] = {
    MeasurementUnit.COUNT: (1_000_000.0, 0),
    MeasurementUnit.SECONDS: (2_678_400.0, 1),
    MeasurementUnit.TOKENS: (1_000_000_000.0, 0),
}


class SnapshotMetricKey(StrEnum):
    """The exact, closed allowlist of publishable measurements.

    Every entry is an objective count or duration derived locally. Private
    coaching, affect, friction, and any model-written judgement are excluded on
    purpose: those must not leave a workstation into a team surface, and an
    enumeration is what prevents adding them by accident.
    """

    SESSIONS_STARTED = "sessions.started_count"
    SESSIONS_COMPLETED = "sessions.completed_count"
    TOOL_INVOCATIONS = "tool.invocation_count"
    TOOL_FAILURES = "tool.failure_count"
    VERIFICATION_OBSERVATIONS = "verification.observed_count"
    CORRECTION_LOOPS = "rework.correction_loop_count"
    ACTIVE_SECONDS = "duration.active_seconds"
    INPUT_TOKENS = "usage.input_tokens"
    OUTPUT_TOKENS = "usage.output_tokens"
    TOTAL_TOKENS = "usage.total_tokens"


SNAPSHOT_METRIC_UNITS: Mapping[SnapshotMetricKey, MeasurementUnit] = {
    SnapshotMetricKey.SESSIONS_STARTED: MeasurementUnit.COUNT,
    SnapshotMetricKey.SESSIONS_COMPLETED: MeasurementUnit.COUNT,
    SnapshotMetricKey.TOOL_INVOCATIONS: MeasurementUnit.COUNT,
    SnapshotMetricKey.TOOL_FAILURES: MeasurementUnit.COUNT,
    SnapshotMetricKey.VERIFICATION_OBSERVATIONS: MeasurementUnit.COUNT,
    SnapshotMetricKey.CORRECTION_LOOPS: MeasurementUnit.COUNT,
    SnapshotMetricKey.ACTIVE_SECONDS: MeasurementUnit.SECONDS,
    SnapshotMetricKey.INPUT_TOKENS: MeasurementUnit.TOKENS,
    SnapshotMetricKey.OUTPUT_TOKENS: MeasurementUnit.TOKENS,
    SnapshotMetricKey.TOTAL_TOKENS: MeasurementUnit.TOKENS,
}

ALLOWED_SNAPSHOT_METRIC_KEYS = frozenset(SnapshotMetricKey)
MAX_SNAPSHOT_MEASUREMENTS = len(SnapshotMetricKey)


def quantize_measurement(value: float, unit: MeasurementUnit) -> float:
    """Return the canonical representation of ``value`` for ``unit``."""

    _, precision = UNIT_LIMITS[unit]
    return round(value, precision)


class SnapshotMeasurement(StrictModel):
    """One allowlisted measurement with its own coverage and missingness.

    ``value`` is ``None`` when nothing eligible was observed. It is never
    replaced by zero, because "no session ran" and "zero tools failed" are
    different facts and a team aggregate that confuses them is wrong.
    """

    key: SnapshotMetricKey
    unit: MeasurementUnit
    value: float | None = Field(default=None, ge=0, allow_inf_nan=False)
    observed_count: int = Field(ge=0, le=MAX_OBSERVATION_COUNT)
    eligible_count: int = Field(ge=0, le=MAX_OBSERVATION_COUNT)

    @model_validator(mode="after")
    def coherent_measurement(self) -> SnapshotMeasurement:
        if self.unit is not SNAPSHOT_METRIC_UNITS[self.key]:
            raise ValueError("measurement unit must match the allowlisted unit")
        if self.observed_count > self.eligible_count:
            raise ValueError("observed_count cannot exceed eligible_count")
        if self.value is None and self.observed_count != 0:
            raise ValueError("an unknown value cannot report observations")
        if self.value is not None:
            if self.observed_count == 0:
                raise ValueError("a known value requires at least one observation")
            ceiling, _ = UNIT_LIMITS[self.unit]
            if self.value > ceiling:
                raise ValueError("measurement values stay inside the unit ceiling")
            if self.value != quantize_measurement(self.value, self.unit):
                raise ValueError("measurement values must be canonically quantized")
        return self

    @property
    def coverage(self) -> float:
        if self.eligible_count == 0:
            return 0.0
        return self.observed_count / self.eligible_count

    @property
    def is_known(self) -> bool:
        return self.value is not None


class SnapshotEnvelope(StrictModel):
    """One minimized measurement snapshot for one canonical period.

    Tenant, subject, client, and device identity are deliberately absent. The
    service obtains them only from the authenticated credential and the
    server-side envelope reservation, then stamps them on ``SnapshotRecord``.
    """

    schema_version: Literal["control-plane-snapshot-v2"] = (
        SNAPSHOT_ENVELOPE_SCHEMA_VERSION
    )
    envelope_id: str
    team_id: str | None = None
    visibility: VisibilityScope = VisibilityScope.INDIVIDUAL
    period: ReportingBucket
    issued_at: datetime
    measurement_definition_version: MeasurementDefinitionVersion
    producer_adapter_version: ProducerAdapterVersion
    measurements: tuple[SnapshotMeasurement, ...] = Field(
        min_length=1, max_length=MAX_SNAPSHOT_MEASUREMENTS
    )

    _identifier = field_validator("envelope_id")(_pseudonym)
    _optional_identifiers = field_validator("team_id")(_optional_pseudonym)
    _timestamps = field_validator("issued_at")(_utc)

    @field_validator("measurements")
    @classmethod
    def canonical_measurements(
        cls, values: tuple[SnapshotMeasurement, ...]
    ) -> tuple[SnapshotMeasurement, ...]:
        keys = tuple(measurement.key.value for measurement in values)
        if keys != tuple(sorted(keys)) or len(set(keys)) != len(keys):
            raise ValueError("measurements must be unique and sorted by key")
        return values

    @model_validator(mode="after")
    def coherent_period_and_scope(self) -> SnapshotEnvelope:
        period_end = self.period.end
        if self.issued_at < period_end:
            raise ValueError("a snapshot cannot be issued before its period ends")
        if self.issued_at - period_end > MAX_ISSUE_DELAY:
            raise ValueError("a snapshot must be issued close to its period")
        if self.visibility is VisibilityScope.TEAM and self.team_id is None:
            raise ValueError("team-visible snapshots must name their team")
        return self


class EnvelopeSignature(StrictModel):
    """A device signature over the canonical envelope bytes."""

    algorithm: SignatureAlgorithm
    key_fingerprint: str
    value: str = Field(max_length=MAX_SIGNATURE_CHARACTERS)

    _fingerprint = field_validator("key_fingerprint")(_pseudonym)

    @field_validator("value")
    @classmethod
    def base64_value(cls, value: str) -> str:
        if BASE64_PATTERN.fullmatch(value) is None:
            raise ValueError("signatures must be compact base64 values")
        return value


class SignedSnapshotEnvelope(StrictModel):
    envelope: SnapshotEnvelope
    signature: EnvelopeSignature


def canonical_envelope_bytes(envelope: SnapshotEnvelope) -> bytes:
    """Serialize an envelope deterministically for signing and digesting.

    The domain-separation prefix binds the bytes to this schema version, so a
    signature cannot be lifted onto a future envelope shape.
    """

    payload = json.dumps(
        envelope.model_dump(mode="json"),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
    )
    return SNAPSHOT_SIGNING_DOMAIN + b"\x00" + payload.encode("ascii")


def envelope_digest(envelope: SnapshotEnvelope) -> str:
    """Return the content digest used for idempotency and replay detection."""

    return hashlib.sha256(canonical_envelope_bytes(envelope)).hexdigest()


class SignatureVerifier(Protocol):
    """Port for one signature algorithm.

    Implementations must be constant-time where the algorithm requires it and
    must never raise on malformed input; returning ``False`` keeps rejection
    reasons uniform and avoids leaking which part of a forgery failed.
    """

    @property
    def algorithm(self) -> SignatureAlgorithm: ...

    def verify(
        self,
        key: DeviceVerificationKey,
        payload: bytes,
        signature: str,
    ) -> bool: ...


__all__ = [
    "ALLOWED_SNAPSHOT_METRIC_KEYS",
    "BASE64_PATTERN",
    "MAX_ISSUE_DELAY",
    "MAX_OBSERVATION_COUNT",
    "MAX_SIGNATURE_CHARACTERS",
    "MAX_SNAPSHOT_MEASUREMENTS",
    "SNAPSHOT_ENVELOPE_SCHEMA_VERSION",
    "SNAPSHOT_METRIC_UNITS",
    "SNAPSHOT_SIGNING_DOMAIN",
    "UNIT_LIMITS",
    "EnvelopeSignature",
    "MeasurementDefinitionVersion",
    "MeasurementUnit",
    "ProducerAdapterVersion",
    "SignatureVerifier",
    "SignedSnapshotEnvelope",
    "SnapshotEnvelope",
    "SnapshotMeasurement",
    "SnapshotMetricKey",
    "canonical_envelope_bytes",
    "envelope_digest",
    "quantize_measurement",
]
