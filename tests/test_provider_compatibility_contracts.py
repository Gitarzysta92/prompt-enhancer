from __future__ import annotations

from datetime import UTC, datetime, timezone, timedelta

import pytest
from pydantic import ValidationError

from prompt_enhancer.application.providers import (
    CapabilityKey,
    CapabilityObservation,
    CapabilityState,
    CompatibilityReason,
    CompatibilityReasonCode,
    CompatibilityState,
    DecoderDescriptor,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)


NOW = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def _descriptor() -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="example_agent"),
        surface=ProviderSurface.TEXT_WINDOW,
        adapter_version="example-adapter-1",
        decoder_key="example.text.decoder",
        decoder_version="1",
        wire_schema_family="example.text-wire.v1",
        canonical_schema_version="canonical.redacted-message.v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="example.text-schema",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
            checksum_sha256="a" * 64,
        ),
        capabilities=(
            CapabilityKey.USER_MESSAGES,
            CapabilityKey.AGENT_MESSAGES,
        ),
        tested_provider_versions=("example-1.0", "example-1.1"),
    )


def _supported() -> tuple[CapabilityObservation, ...]:
    return tuple(
        CapabilityObservation(key=key, state=CapabilityState.SUPPORTED)
        for key in _descriptor().capabilities
    )


def _complete() -> ExtractionCompleteness:
    return ExtractionCompleteness(
        state=ExtractionCompletenessState.COMPLETE,
        observed_units=2,
        eligible_units=2,
        coverage=1,
    )


def test_provider_identity_is_extensible_but_strict_and_content_free() -> None:
    assert ProviderIdentity(key="cursor").key == "cursor"
    assert ProviderIdentity(key="claude_code").key == "claude_code"

    for invalid in ("Cursor", "cursor-plugin/path", "", "a" * 65):
        with pytest.raises(ValidationError) as raised:
            ProviderIdentity(key=invalid)
        if invalid:
            assert invalid not in str(raised.value)


def test_decoder_descriptor_is_frozen_versioned_and_rejects_duplicates() -> None:
    descriptor = _descriptor()

    assert descriptor.identity == (
        "example_agent",
        ProviderSurface.TEXT_WINDOW,
        "example.text.decoder",
        "1",
    )
    with pytest.raises(ValidationError):
        descriptor.adapter_version = "changed"  # type: ignore[misc]
    with pytest.raises(ValidationError, match="duplicates"):
        DecoderDescriptor.model_validate(
            {
                **descriptor.model_dump(),
                "capabilities": ["user_messages", "user_messages"],
            }
        )
    with pytest.raises(ValidationError):
        SchemaArtifactProvenance(
            artifact_key="example.schema",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
            checksum_sha256="not-a-checksum",
        )


def test_extraction_completeness_never_invents_unknown_denominators() -> None:
    assert _complete().coverage == 1
    partial = ExtractionCompleteness(
        state=ExtractionCompletenessState.PARTIAL,
        observed_units=2,
        eligible_units=3,
        unknown_units=1,
        coverage=2 / 3,
    )
    unknown = ExtractionCompleteness(
        state=ExtractionCompletenessState.UNKNOWN,
        observed_units=2,
        unknown_units=1,
    )
    none = ExtractionCompleteness(
        state=ExtractionCompletenessState.NONE,
        observed_units=0,
    )

    assert partial.state is ExtractionCompletenessState.PARTIAL
    assert unknown.coverage is None and unknown.eligible_units is None
    assert none.coverage is None

    invalid = (
        {
            "state": "complete",
            "observed_units": 1,
            "eligible_units": 2,
            "coverage": 0.5,
        },
        {
            "state": "partial",
            "observed_units": 2,
            "eligible_units": 2,
            "coverage": 1,
        },
        {
            "state": "unknown",
            "observed_units": 1,
            "eligible_units": 2,
            "coverage": 0.5,
        },
        {
            "state": "none",
            "observed_units": 0,
            "eligible_units": 0,
            "coverage": 0,
        },
    )
    for payload in invalid:
        with pytest.raises(ValidationError):
            ExtractionCompleteness.model_validate(payload)


def test_exact_report_requires_complete_clean_supported_capabilities() -> None:
    report = ProviderCompatibilityReport(
        descriptor=_descriptor(),
        provider_version="example-1.1",
        state=CompatibilityState.EXACT,
        capabilities=_supported(),
        extraction=_complete(),
        checked_at=NOW.astimezone(timezone(timedelta(hours=1))),
    )

    assert report.checked_at == NOW
    assert report.reasons == ()
    assert report.model_config["frozen"] is True
    with pytest.raises(ValidationError):
        ProviderCompatibilityReport(
            descriptor=_descriptor(),
            provider_version="example-1.1",
            state=CompatibilityState.EXACT,
            capabilities=_supported(),
            extraction=_complete(),
            reasons=(
                CompatibilityReason(
                    code=CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED
                ),
            ),
            checked_at=NOW,
        )


def test_degraded_report_requires_bounded_reasons_and_honest_coverage() -> None:
    reason = CompatibilityReasonCode.UNKNOWN_UNION_VARIANT
    report = ProviderCompatibilityReport(
        descriptor=_descriptor(),
        provider_version="example-1.2",
        state=CompatibilityState.DEGRADED,
        capabilities=(
            CapabilityObservation(
                key=CapabilityKey.USER_MESSAGES,
                state=CapabilityState.SUPPORTED,
            ),
            CapabilityObservation(
                key=CapabilityKey.AGENT_MESSAGES,
                state=CapabilityState.UNKNOWN,
                reason_code=reason,
            ),
        ),
        extraction=ExtractionCompleteness(
            state=ExtractionCompletenessState.PARTIAL,
            observed_units=2,
            eligible_units=3,
            unknown_units=1,
            coverage=2 / 3,
        ),
        reasons=(CompatibilityReason(code=reason, count=1),),
        checked_at=NOW,
    )

    assert report.state is CompatibilityState.DEGRADED
    assert report.extraction.coverage == pytest.approx(2 / 3)
    with pytest.raises(ValidationError, match="represented"):
        ProviderCompatibilityReport.model_validate(
            {**report.model_dump(), "reasons": []}
        )


@pytest.mark.parametrize(
    ("state", "reason"),
    (
        (
            CompatibilityState.UNTESTED,
            CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED,
        ),
        (
            CompatibilityState.INCOMPATIBLE,
            CompatibilityReasonCode.SCHEMA_FAMILY_UNSUPPORTED,
        ),
        (
            CompatibilityState.UNAVAILABLE,
            CompatibilityReasonCode.PROVIDER_UNAVAILABLE,
        ),
    ),
)
def test_non_decoding_states_cannot_claim_supported_capabilities(
    state: CompatibilityState,
    reason: CompatibilityReasonCode,
) -> None:
    report = ProviderCompatibilityReport(
        descriptor=_descriptor(),
        provider_version="unknown",
        state=state,
        capabilities=tuple(
            CapabilityObservation(
                key=key,
                state=CapabilityState.UNKNOWN,
                reason_code=reason,
            )
            for key in _descriptor().capabilities
        ),
        extraction=ExtractionCompleteness(
            state=(
                ExtractionCompletenessState.UNKNOWN
                if state is CompatibilityState.UNTESTED
                else ExtractionCompletenessState.NONE
            ),
            observed_units=0,
        ),
        reasons=(CompatibilityReason(code=reason),),
        checked_at=NOW,
    )

    assert report.state is state
    assert report.extraction.coverage is None
    with pytest.raises(ValidationError):
        ProviderCompatibilityReport.model_validate(
            {
                **report.model_dump(),
                "capabilities": [
                    {"key": key.value, "state": "supported"}
                    for key in _descriptor().capabilities
                ],
            }
        )


def test_report_contract_has_no_field_for_payload_schema_or_freeform_errors() -> None:
    fields = set(ProviderCompatibilityReport.model_fields)
    descriptor_fields = set(DecoderDescriptor.model_fields)

    assert not {
        "payload",
        "raw_schema",
        "response",
        "exception",
        "error_message",
        "path",
        "transcript",
    }.intersection(fields | descriptor_fields)
    with pytest.raises(ValidationError):
        CompatibilityReason.model_validate(
            {"code": "private.provider.value", "count": 1}
        )
