"""In-memory-only selected-metric evidence packets.

Packets may contain redacted source text and therefore never cross a persistence,
logging, analytics, or export boundary.  Their normal representations hide every
text-bearing field, and their public serialization methods fail closed.  The
only durable projection is the content-free receipt returned by
``build_runtime_evidence_packet_receipt``.

Packet spans are direct redacted source spans.  This layer has no generated-fact,
summary, rationale, or chain-of-thought field.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
import hashlib
import json
import re
from typing import Any, Literal

from pydantic import ConfigDict, Field, SecretStr, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from ..analysis.scope_router_contracts import (
    EvidenceCoverageState,
    ScopeCompatibilityState,
    ScopeEvidenceAvailability,
    ScopeEvidenceKind,
    ScopeRouterOutput,
)
from .contracts import EstimatorRoute, MetricQuestionSpec
from .runtime_contracts import RuntimeEvidencePacketReceipt
from .scope_projection import RuntimeScopeProjection


EPHEMERAL_QUESTION_MATERIAL_VERSION = "ephemeral-question-material-v1"
EPHEMERAL_DIRECT_SPAN_VERSION = "ephemeral-direct-span-v1"
EPHEMERAL_METRIC_EVIDENCE_PACKET_VERSION = "ephemeral-metric-evidence-packet-v1"
MAX_PACKET_SPANS = 10_000
SAFE_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_.:-]{0,127}$")


def _safe_code(value: str) -> str:
    if SAFE_CODE_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase content-free code")
    return value


def _safe_version(value: str) -> str:
    if (
        value.startswith(("/", "\\"))
        or re.match(r"^[A-Za-z]:[/\\]", value) is not None
        or "\\" in value
        or "://" in value
        or ".." in value.split("/")
    ):
        raise ValueError("version identifiers cannot encode paths or URIs")
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a content-free version identifier")
    return value


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 digest")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _text_sha256(value: SecretStr) -> str:
    return hashlib.sha256(value.get_secret_value().encode("utf-8")).hexdigest()


def _canonical_sha256(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class _EphemeralTextModel(StrictModel):
    """Fail-closed base for text-bearing in-memory values."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    def model_dump(self, *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        raise TypeError("ephemeral text-bearing contracts cannot be serialized")

    def model_dump_json(self, *_args: Any, **_kwargs: Any) -> str:
        raise TypeError("ephemeral text-bearing contracts cannot be serialized")

    def __getstate__(self) -> dict[str, Any]:
        raise TypeError("ephemeral text-bearing contracts cannot be pickled")

    def model_copy(
        self,
        *,
        update: dict[str, object] | None = None,
        deep: bool = False,
    ) -> _EphemeralTextModel:
        if update:
            raise TypeError("ephemeral contracts forbid update-copy bypass")
        return super().model_copy(deep=deep)


class PacketSpanRole(StrEnum):
    REQUIREMENT = "requirement"
    CHRONOLOGY = "chronology"
    CANDIDATE_EVIDENCE = "candidate_evidence"


class EphemeralMetricQuestionMaterial(_EphemeralTextModel):
    """Reviewed question, prompt, and rubric material used only in memory."""

    contract_version: Literal[EPHEMERAL_QUESTION_MATERIAL_VERSION] = (
        EPHEMERAL_QUESTION_MATERIAL_VERSION
    )
    question_id: str
    question_version: str
    question_text: SecretStr = Field(repr=False)
    prompt_template_id: str
    prompt_template_version: str
    prompt_template_text: SecretStr = Field(repr=False)
    rubric_id: str
    rubric_version: str
    rubric_text: SecretStr = Field(repr=False)
    persistence_allowed: Literal[False] = False

    _safe_codes = field_validator("question_id", "prompt_template_id", "rubric_id")(
        _safe_code
    )
    _safe_versions = field_validator(
        "question_version", "prompt_template_version", "rubric_version"
    )(_safe_version)

    @field_validator("question_text", "prompt_template_text", "rubric_text")
    @classmethod
    def bounded_material(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if not text.strip() or len(text) > 100_000 or "\x00" in text:
            raise ValueError("question material must be non-empty bounded text")
        return value

    @property
    def question_sha256(self) -> str:
        return _text_sha256(self.question_text)

    @property
    def prompt_template_sha256(self) -> str:
        return _text_sha256(self.prompt_template_text)

    @property
    def rubric_sha256(self) -> str:
        return _text_sha256(self.rubric_text)


class EphemeralDirectSpan(_EphemeralTextModel):
    """One direct, redacted source span with an exact source-text digest."""

    contract_version: Literal[EPHEMERAL_DIRECT_SPAN_VERSION] = (
        EPHEMERAL_DIRECT_SPAN_VERSION
    )
    reference_id: str
    source_record_id: str
    role: PacketSpanRole
    observed_sequence: int = Field(ge=0)
    evidence_kind: ScopeEvidenceKind | None = None
    requirement_id: str | None = None
    requirement_version_id: str | None = None
    redacted_text: SecretStr = Field(repr=False)
    redacted_text_sha256: str
    derivation: Literal["direct_redacted_span"] = "direct_redacted_span"
    persistence_allowed: Literal[False] = False

    _safe_ids = field_validator("reference_id", "source_record_id")(_digest)
    _safe_text_hash = field_validator("redacted_text_sha256")(_digest)

    @field_validator("requirement_id", "requirement_version_id")
    @classmethod
    def safe_optional_id(cls, value: str | None) -> str | None:
        return None if value is None else _digest(value)

    @field_validator("redacted_text")
    @classmethod
    def bounded_direct_text(cls, value: SecretStr) -> SecretStr:
        text = value.get_secret_value()
        if not text.strip() or len(text) > 250_000 or "\x00" in text:
            raise ValueError("direct redacted spans must be non-empty bounded text")
        return value

    @model_validator(mode="after")
    def validate_direct_span(self) -> EphemeralDirectSpan:
        if self.redacted_text_sha256 != _text_sha256(self.redacted_text):
            raise ValueError("redacted span digest must match the exact in-memory text")
        requirement_pair = (self.requirement_id, self.requirement_version_id)
        if (requirement_pair[0] is None) != (requirement_pair[1] is None):
            raise ValueError("requirement linkage must include identity and version")
        if self.role is PacketSpanRole.REQUIREMENT:
            if requirement_pair[0] is None or self.evidence_kind is not None:
                raise ValueError("requirement spans require only requirement linkage")
        elif self.role is PacketSpanRole.CANDIDATE_EVIDENCE:
            if self.evidence_kind is None:
                raise ValueError("candidate evidence requires a typed evidence kind")
        elif self.evidence_kind is not None:
            raise ValueError("chronology spans cannot claim typed evidence")
        return self


def _material_payload(material: EphemeralMetricQuestionMaterial) -> dict[str, Any]:
    return {
        "contract_version": material.contract_version,
        "question_id": material.question_id,
        "question_version": material.question_version,
        "question_text": material.question_text.get_secret_value(),
        "prompt_template_id": material.prompt_template_id,
        "prompt_template_version": material.prompt_template_version,
        "prompt_template_text": material.prompt_template_text.get_secret_value(),
        "rubric_id": material.rubric_id,
        "rubric_version": material.rubric_version,
        "rubric_text": material.rubric_text.get_secret_value(),
    }


def _span_payload(span: EphemeralDirectSpan) -> dict[str, Any]:
    return {
        "contract_version": span.contract_version,
        "reference_id": span.reference_id,
        "source_record_id": span.source_record_id,
        "role": span.role.value,
        "observed_sequence": span.observed_sequence,
        "evidence_kind": None if span.evidence_kind is None else span.evidence_kind.value,
        "requirement_id": span.requirement_id,
        "requirement_version_id": span.requirement_version_id,
        "redacted_text": span.redacted_text.get_secret_value(),
        "redacted_text_sha256": span.redacted_text_sha256,
        "derivation": span.derivation,
    }


class EphemeralMetricEvidencePacket(_EphemeralTextModel):
    """Selected-metric packet that exists only for the lifetime of one run."""

    contract_version: Literal[EPHEMERAL_METRIC_EVIDENCE_PACKET_VERSION] = (
        EPHEMERAL_METRIC_EVIDENCE_PACKET_VERSION
    )
    packet_schema_version: str
    plan_fingerprint: str
    route: EstimatorRoute
    question_spec: MetricQuestionSpec
    question_material: EphemeralMetricQuestionMaterial = Field(repr=False)
    scope_projection: RuntimeScopeProjection = Field(repr=False)
    scope_router_output: ScopeRouterOutput
    provider: Provider
    adapter_version: str
    provider_schema_version: str
    preprocessing_version: str
    preprocessing_sha256: str
    router_version: str
    router_sha256: str
    redactor_version: str
    redactor_sha256: str
    spans: tuple[EphemeralDirectSpan, ...] = Field(
        min_length=1,
        max_length=MAX_PACKET_SPANS,
        repr=False,
    )
    created_at: datetime
    retention_class: Literal["memory_only"] = "memory_only"
    persistence_allowed: Literal[False] = False
    logging_allowed: Literal[False] = False
    analytics_allowed: Literal[False] = False
    export_allowed: Literal[False] = False
    execution_only: Literal[True] = True
    activation_allowed: Literal[False] = False

    _safe_versions = field_validator(
        "packet_schema_version",
        "adapter_version",
        "provider_schema_version",
        "preprocessing_version",
        "router_version",
        "redactor_version",
    )(_safe_version)
    _safe_digests = field_validator(
        "plan_fingerprint",
        "preprocessing_sha256",
        "router_sha256",
        "redactor_sha256",
    )(_digest)
    _utc_created = field_validator("created_at")(_utc)

    @field_validator("spans")
    @classmethod
    def canonical_spans(
        cls, values: tuple[EphemeralDirectSpan, ...]
    ) -> tuple[EphemeralDirectSpan, ...]:
        keys = tuple(
            (item.observed_sequence, item.role.value, item.reference_id)
            for item in values
        )
        if keys != tuple(sorted(keys)):
            raise ValueError("packet spans must be chronologically and role sorted")
        references = tuple(item.reference_id for item in values)
        if len(references) != len(set(references)):
            raise ValueError("packet span references must be unique")
        return values

    @model_validator(mode="after")
    def validate_packet(self) -> EphemeralMetricEvidencePacket:
        spec = MetricQuestionSpec.model_validate(
            self.question_spec.model_dump(mode="python")
        )
        material = self.question_material
        exact_material_identity = (
            material.question_id == spec.question_id
            and material.question_version == spec.question_version
            and material.prompt_template_id == spec.prompt_template_id
            and material.prompt_template_version == spec.prompt_template_version
            and material.rubric_id == spec.rubric_id
            and material.rubric_version == spec.rubric_version
            and material.question_sha256 == spec.question_sha256
            and material.prompt_template_sha256 == spec.prompt_template_sha256
            and material.rubric_sha256 == spec.rubric_sha256
        )
        if not exact_material_identity:
            raise ValueError("question, prompt, and rubric material must match exact hashes")

        projection = RuntimeScopeProjection.model_validate(
            self.scope_projection.model_dump(mode="python")
        )
        router_output = ScopeRouterOutput.model_validate(
            self.scope_router_output.model_dump(mode="python")
        )
        if projection.metric_question_fingerprint != spec.canonical_fingerprint:
            raise ValueError("scope projection must bind the exact metric question")
        if (
            router_output.router_version != self.router_version
            or router_output.state is not ScopeCompatibilityState.COMPATIBLE
            or router_output.evidence_coverage.state is not EvidenceCoverageState.KNOWN
            or router_output.evidence_coverage.ratio != 1.0
        ):
            raise ValueError("evidence packets require an exact compatible router result")

        requirement_spans = tuple(
            span for span in self.spans if span.role is PacketSpanRole.REQUIREMENT
        )
        if not requirement_spans:
            raise ValueError("metric evidence packets require a canonical requirement")
        if any(
            span.requirement_id != projection.target_requirement_id
            or span.requirement_version_id
            != projection.target_requirement_version_id
            or span.observed_sequence != projection.requirement_observed_sequence
            for span in requirement_spans
        ):
            raise ValueError("requirement spans must match the routed target requirement")

        available_by_kind = {
            receipt.kind: set(receipt.evidence_reference_ids)
            for receipt in projection.evidence_receipts
            if receipt.availability is ScopeEvidenceAvailability.AVAILABLE
        }
        candidate_spans = tuple(
            span
            for span in self.spans
            if span.role is PacketSpanRole.CANDIDATE_EVIDENCE
        )
        for span in candidate_spans:
            assert span.evidence_kind is not None
            if span.reference_id not in available_by_kind.get(span.evidence_kind, set()):
                raise ValueError("packet evidence was not vetted by the scope router")
            if (
                span.requirement_id != projection.target_requirement_id
                or span.requirement_version_id
                != projection.target_requirement_version_id
            ):
                raise ValueError("packet evidence must link the routed requirement version")
            assert projection.evidence_observed_sequence is not None
            if not (
                projection.requirement_observed_sequence
                <= span.observed_sequence
                <= projection.evidence_observed_sequence
            ):
                raise ValueError("packet evidence sequence is outside the routed window")
        candidate_kinds = {span.evidence_kind for span in candidate_spans}
        if not set(projection.required_evidence_kinds).issubset(candidate_kinds):
            raise ValueError("packet must carry vetted evidence for every required kind")
        return self

    @property
    def scope_projection_fingerprint(self) -> str:
        return self.scope_projection.canonical_fingerprint

    @property
    def scope_router_output_fingerprint(self) -> str:
        return _canonical_sha256(self.scope_router_output.model_dump(mode="json"))

    @property
    def retrieval_query_fingerprint(self) -> str:
        return _canonical_sha256(
            {
                "metric_question_fingerprint": self.question_spec.canonical_fingerprint,
                "question_material": _material_payload(self.question_material),
            }
        )

    @property
    def packet_fingerprint(self) -> str:
        """Digest the exact ephemeral payload without returning its contents."""

        payload = {
            "contract_version": self.contract_version,
            "packet_schema_version": self.packet_schema_version,
            "plan_fingerprint": self.plan_fingerprint,
            "route": self.route.value,
            "question_spec": self.question_spec.model_dump(mode="json"),
            "question_material": _material_payload(self.question_material),
            "scope_projection": self.scope_projection.model_dump(mode="json"),
            "scope_router_output": self.scope_router_output.model_dump(mode="json"),
            "provider": self.provider.value,
            "adapter_version": self.adapter_version,
            "provider_schema_version": self.provider_schema_version,
            "preprocessing_version": self.preprocessing_version,
            "preprocessing_sha256": self.preprocessing_sha256,
            "router_version": self.router_version,
            "router_sha256": self.router_sha256,
            "redactor_version": self.redactor_version,
            "redactor_sha256": self.redactor_sha256,
            "spans": [_span_payload(span) for span in self.spans],
            "created_at": self.created_at.isoformat(),
        }
        return _canonical_sha256(payload)

    @property
    def requirements_sha256(self) -> str:
        return _canonical_sha256(
            [
                _span_payload(span)
                for span in self.spans
                if span.role is PacketSpanRole.REQUIREMENT
            ]
        )

    @property
    def chronology_sha256(self) -> str:
        return _canonical_sha256(
            [
                _span_payload(span)
                for span in self.spans
                if span.role is PacketSpanRole.CHRONOLOGY
            ]
        )

    @property
    def retrieval_index_sha256(self) -> str:
        return _canonical_sha256(
            [
                _span_payload(span)
                for span in self.spans
                if span.role is PacketSpanRole.CANDIDATE_EVIDENCE
            ]
        )


def build_runtime_evidence_packet_receipt(
    packet: EphemeralMetricEvidencePacket,
) -> RuntimeEvidencePacketReceipt:
    """Drop all packet text and return its immutable execution-only receipt."""

    material = EphemeralMetricQuestionMaterial(**packet.question_material.__dict__)
    spans = tuple(EphemeralDirectSpan(**span.__dict__) for span in packet.spans)
    packet = EphemeralMetricEvidencePacket(
        **{
            **packet.__dict__,
            "question_material": material,
            "spans": spans,
            "scope_projection": RuntimeScopeProjection.model_validate(
                packet.scope_projection.model_dump(mode="python")
            ),
            "scope_router_output": ScopeRouterOutput.model_validate(
                packet.scope_router_output.model_dump(mode="python")
            ),
        }
    )

    evidence_spans = tuple(
        span
        for span in packet.spans
        if span.role is PacketSpanRole.CANDIDATE_EVIDENCE
    )
    evidence_refs = tuple(sorted(span.reference_id for span in evidence_spans))
    evidence_counts = {
        kind: sum(span.evidence_kind is kind for span in evidence_spans)
        for kind in ScopeEvidenceKind
    }
    return RuntimeEvidencePacketReceipt(
        packet_schema_version=packet.packet_schema_version,
        packet_fingerprint=packet.packet_fingerprint,
        plan_fingerprint=packet.plan_fingerprint,
        metric_key=packet.question_spec.metric_key,
        metric_question_fingerprint=packet.question_spec.canonical_fingerprint,
        route=packet.route,
        scope_projection_fingerprint=packet.scope_projection_fingerprint,
        scope_router_output_fingerprint=packet.scope_router_output_fingerprint,
        retrieval_query_fingerprint=packet.retrieval_query_fingerprint,
        requirements_sha256=packet.requirements_sha256,
        chronology_sha256=packet.chronology_sha256,
        retrieval_index_sha256=packet.retrieval_index_sha256,
        provider=packet.provider,
        adapter_version=packet.adapter_version,
        provider_schema_version=packet.provider_schema_version,
        preprocessing_version=packet.preprocessing_version,
        preprocessing_sha256=packet.preprocessing_sha256,
        router_version=packet.router_version,
        router_sha256=packet.router_sha256,
        redactor_version=packet.redactor_version,
        redactor_sha256=packet.redactor_sha256,
        source_record_count=len({span.source_record_id for span in packet.spans}),
        requirement_count=sum(
            span.role is PacketSpanRole.REQUIREMENT for span in packet.spans
        ),
        chronology_count=sum(
            span.role is PacketSpanRole.CHRONOLOGY for span in packet.spans
        ),
        action_count=evidence_counts[ScopeEvidenceKind.ACTION],
        decision_count=evidence_counts[ScopeEvidenceKind.DECISION],
        feedback_count=evidence_counts[ScopeEvidenceKind.FEEDBACK],
        verification_count=evidence_counts[ScopeEvidenceKind.VERIFICATION],
        opaque_evidence_refs=evidence_refs,
        created_at=packet.created_at,
    )


__all__ = [
    "EphemeralDirectSpan",
    "EphemeralMetricEvidencePacket",
    "EphemeralMetricQuestionMaterial",
    "PacketSpanRole",
    "build_runtime_evidence_packet_receipt",
]
