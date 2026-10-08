"""Content-free provider compatibility status for the local dashboard."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, Protocol

from fastapi import APIRouter, Depends, HTTPException, Path
from pydantic import Field

from ...application.providers import (
    CapabilityState,
    CompatibilityReasonCode,
    CompatibilityState,
    DecoderDescriptor,
    ProviderCompatibilityCatalogError,
    ProviderCompatibilityReport,
    ProviderSurface,
)
from ...domain import SAFE_VERSION_PATTERN, StrictModel


_PROVIDER_KEY_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_PUBLIC_FAMILIES = {
    "codex": (
        "codex_app_server",
        "codex_app_server",
        "codex_thread",
        "codex_thread_items",
    ),
    "claude_code": (
        "claude_code",
        "claude_code_hooks",
        "claude_hook_ledger",
        "claude_hook_events",
    ),
    # The transcript text window is a different adapter over different files.
    ("claude_code", ProviderSurface.TEXT_WINDOW): (
        "claude_code",
        "claude_code_transcripts",
        "claude_transcript_jsonl",
        "claude_transcript_messages",
    ),
    "synthetic": (
        "synthetic_provider",
        "synthetic_adapter",
        "synthetic_session",
        "synthetic_content",
    ),
}


class ProviderCompatibilityQuery(Protocol):
    def descriptor(
        self, provider: str, surface: ProviderSurface
    ) -> DecoderDescriptor: ...

    def get_cached(
        self, provider: str, surface: ProviderSurface
    ) -> ProviderCompatibilityReport | None: ...

    def refresh(
        self, provider: str, surface: ProviderSurface
    ) -> ProviderCompatibilityReport: ...


class ProviderCompatibilityStateDto(StrEnum):
    EXACT = "exact"
    COMPATIBLE = "compatible"
    DEGRADED = "degraded"
    UNTESTED = "untested"
    INCOMPATIBLE = "incompatible"
    UNAVAILABLE = "unavailable"


class ProviderTextCapabilityStateDto(StrEnum):
    SUPPORTED = "supported"
    UNSUPPORTED = "unsupported"
    UNKNOWN = "unknown"


class ProviderCompatibilityReasonDto(StrEnum):
    EXACT_MATCH = "exact_match"
    COMPATIBLE_VERSION = "compatible_version"
    DEGRADED_EXTRACTION = "degraded_extraction"
    NOT_CHECKED = "not_checked"
    PROVIDER_UNAVAILABLE = "provider_unavailable"
    PROVIDER_VERSION_UNSUPPORTED = "provider_version_unsupported"
    ADAPTER_OUTDATED = "adapter_outdated"
    SOURCE_SCHEMA_UNSUPPORTED = "source_schema_unsupported"
    CONTENT_SCHEMA_UNSUPPORTED = "content_schema_unsupported"
    CHECK_FAILED = "check_failed"


class ProviderCompatibilityStatusDto(StrictModel):
    """Closed projection. It contains no provider payload, path, or identifier."""

    provider: Literal["codex", "claude_code", "synthetic"]
    capability: Literal["session_text_analysis", "operational_events"] = (
        "session_text_analysis"
    )
    state: ProviderCompatibilityStateDto
    capability_state: ProviderTextCapabilityStateDto
    provider_family: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    provider_version: str | None = Field(
        default=None, pattern=SAFE_VERSION_PATTERN.pattern
    )
    adapter_family: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    adapter_version: str | None = Field(
        default=None, pattern=SAFE_VERSION_PATTERN.pattern
    )
    source_schema_family: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    source_schema_version: str | None = Field(
        default=None, pattern=SAFE_VERSION_PATTERN.pattern
    )
    content_schema_family: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{0,63}$")
    content_schema_version: str | None = Field(
        default=None, pattern=SAFE_VERSION_PATTERN.pattern
    )
    reason_code: ProviderCompatibilityReasonDto
    checked_at: datetime | None = None
    update_support: Literal["supported", "unsupported", "unknown"] = "unknown"
    update_target: Literal["prompt_enhancer", "provider"] | None = None


def _families(
    provider: str, surface: ProviderSurface | None = None
) -> tuple[str, str, str, str]:
    try:
        if surface is not None and (provider, surface) in _PUBLIC_FAMILIES:
            return _PUBLIC_FAMILIES[(provider, surface)]
        return _PUBLIC_FAMILIES[provider]
    except KeyError:
        raise ProviderCompatibilityCatalogError(
            "provider compatibility surface is not public"
        ) from None


def _capability_state(
    report: ProviderCompatibilityReport,
) -> ProviderTextCapabilityStateDto:
    if report.state in {CompatibilityState.EXACT, CompatibilityState.COMPATIBLE}:
        return ProviderTextCapabilityStateDto.SUPPORTED
    if report.state is CompatibilityState.INCOMPATIBLE:
        return ProviderTextCapabilityStateDto.UNSUPPORTED
    if report.state is CompatibilityState.DEGRADED and any(
        item.state is CapabilityState.SUPPORTED for item in report.capabilities
    ):
        return ProviderTextCapabilityStateDto.SUPPORTED
    return ProviderTextCapabilityStateDto.UNKNOWN


def _incompatible_reason(
    report: ProviderCompatibilityReport,
) -> ProviderCompatibilityReasonDto:
    codes = {item.code for item in report.reasons}
    if codes & {
        CompatibilityReasonCode.PROVIDER_VERSION_UNKNOWN,
        CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED,
    }:
        return ProviderCompatibilityReasonDto.PROVIDER_VERSION_UNSUPPORTED
    if CompatibilityReasonCode.DECODER_FAILED in codes:
        return ProviderCompatibilityReasonDto.ADAPTER_OUTDATED
    if codes & {
        CompatibilityReasonCode.UNKNOWN_UNION_VARIANT,
        CompatibilityReasonCode.PROTOCOL_UNSUPPORTED,
    }:
        return ProviderCompatibilityReasonDto.CONTENT_SCHEMA_UNSUPPORTED
    return ProviderCompatibilityReasonDto.SOURCE_SCHEMA_UNSUPPORTED


def provider_compatibility_status(
    descriptor: DecoderDescriptor,
    report: ProviderCompatibilityReport | None,
) -> ProviderCompatibilityStatusDto:
    provider = descriptor.provider.key
    provider_family, adapter_family, source_family, content_family = _families(
        provider, descriptor.surface
    )
    untested = report is None or report.state is CompatibilityState.UNTESTED
    common = dict(
        provider=provider,
        capability=(
            "operational_events"
            if descriptor.surface is ProviderSurface.OPERATIONAL_EVENTS
            else "session_text_analysis"
        ),
        provider_family=provider_family,
        provider_version=None if untested else report.provider_version,
        adapter_family=adapter_family,
        adapter_version=descriptor.adapter_version,
        source_schema_family=source_family,
        source_schema_version=descriptor.schema_artifact.artifact_version,
        content_schema_family=content_family,
        content_schema_version=descriptor.canonical_schema_version,
        checked_at=None if untested else report.checked_at,
    )
    if untested:
        return ProviderCompatibilityStatusDto(
            **common,
            state=ProviderCompatibilityStateDto.UNTESTED,
            capability_state=ProviderTextCapabilityStateDto.UNKNOWN,
            reason_code=ProviderCompatibilityReasonDto.NOT_CHECKED,
        )

    reason = {
        CompatibilityState.EXACT: ProviderCompatibilityReasonDto.EXACT_MATCH,
        CompatibilityState.COMPATIBLE: ProviderCompatibilityReasonDto.COMPATIBLE_VERSION,
        CompatibilityState.DEGRADED: ProviderCompatibilityReasonDto.DEGRADED_EXTRACTION,
        CompatibilityState.UNTESTED: ProviderCompatibilityReasonDto.NOT_CHECKED,
        CompatibilityState.UNAVAILABLE: ProviderCompatibilityReasonDto.PROVIDER_UNAVAILABLE,
    }.get(report.state)
    if report.state is CompatibilityState.INCOMPATIBLE:
        reason = _incompatible_reason(report)
    if reason is None:
        reason = ProviderCompatibilityReasonDto.CHECK_FAILED
    return ProviderCompatibilityStatusDto(
        **common,
        state=ProviderCompatibilityStateDto(report.state.value),
        capability_state=_capability_state(report),
        reason_code=reason,
    )


def create_provider_compatibility_router(
    require_local_auth: Callable[..., None],
    catalog: ProviderCompatibilityQuery,
) -> APIRouter:
    router = APIRouter(
        prefix="/v1/providers",
        tags=["provider-compatibility"],
        dependencies=[Depends(require_local_auth)],
    )

    def surface_for(provider: str) -> ProviderSurface:
        """Each provider publishes exactly one primary surface here.

        The text window is preferred when the provider registers one and its
        last check did not find it unavailable (Codex: the app-server; Claude
        Code: the transcript root).  Otherwise the operational-event surface
        speaks for the provider - for Claude Code that is the hook ledger,
        the only source when no transcript root exists.
        """

        has_events = True
        try:
            catalog.descriptor(provider, ProviderSurface.OPERATIONAL_EVENTS)
        except ProviderCompatibilityCatalogError:
            has_events = False
        try:
            catalog.descriptor(provider, ProviderSurface.TEXT_WINDOW)
            cached = catalog.get_cached(provider, ProviderSurface.TEXT_WINDOW)
            if (
                has_events
                and cached is not None
                and cached.state is CompatibilityState.UNAVAILABLE
            ):
                return ProviderSurface.OPERATIONAL_EVENTS
            return ProviderSurface.TEXT_WINDOW
        except ProviderCompatibilityCatalogError:
            pass
        if has_events:
            return ProviderSurface.OPERATIONAL_EVENTS
        raise HTTPException(
            status_code=404,
            detail="provider compatibility surface is unavailable",
        )

    def descriptor_for(provider: str) -> tuple[DecoderDescriptor, ProviderSurface]:
        surface = surface_for(provider)
        try:
            return catalog.descriptor(provider, surface), surface
        except ProviderCompatibilityCatalogError:
            raise HTTPException(
                status_code=404,
                detail="provider compatibility surface is unavailable",
            ) from None

    @router.get(
        "/{provider}/compatibility",
        response_model=ProviderCompatibilityStatusDto,
    )
    def cached_status(
        provider: Annotated[str, Path(pattern=_PROVIDER_KEY_PATTERN)],
    ) -> ProviderCompatibilityStatusDto:
        descriptor, surface = descriptor_for(provider)
        try:
            report = catalog.get_cached(provider, surface)
        except Exception:
            report = None
        return provider_compatibility_status(descriptor, report)

    @router.post(
        "/{provider}/compatibility/check",
        response_model=ProviderCompatibilityStatusDto,
    )
    def check_status(
        provider: Annotated[str, Path(pattern=_PROVIDER_KEY_PATTERN)],
    ) -> ProviderCompatibilityStatusDto:
        descriptor, surface = descriptor_for(provider)
        try:
            report = catalog.refresh(provider, surface)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail="provider compatibility check is unavailable",
            ) from None
        return provider_compatibility_status(descriptor, report)

    return router
