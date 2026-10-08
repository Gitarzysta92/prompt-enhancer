"""Thread-safe orchestration for content-free provider compatibility reports."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from threading import RLock
from typing import Protocol, runtime_checkable

from .contracts import (
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
)
from .registry import ProviderRegistryLookupError, TrustedProviderRegistry


Clock = Callable[[], datetime]


@runtime_checkable
class ProviderCompatibilityProbe(Protocol):
    """Least-capability probe: one descriptor in, one safe report out."""

    @property
    def descriptor(self) -> DecoderDescriptor: ...

    def check(self) -> ProviderCompatibilityReport: ...


class ProviderCompatibilityServiceError(ValueError):
    """Sanitized service configuration or lookup failure."""


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _unavailable_report(
    descriptor: DecoderDescriptor,
    *,
    checked_at: datetime,
) -> ProviderCompatibilityReport:
    return ProviderCompatibilityReport(
        descriptor=descriptor,
        provider_version="unknown",
        state=CompatibilityState.UNAVAILABLE,
        capabilities=tuple(
            CapabilityObservation(
                key=capability,
                state=CapabilityState.UNKNOWN,
                reason_code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE,
            )
            for capability in descriptor.capabilities
        ),
        extraction=ExtractionCompleteness(
            state=ExtractionCompletenessState.NONE,
            observed_units=0,
        ),
        reasons=(
            CompatibilityReason(
                code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE,
            ),
        ),
        checked_at=checked_at,
    )


class ProviderCompatibilityService:
    """Cache validated reports; provider inspection occurs only on refresh."""

    def __init__(
        self,
        registry: TrustedProviderRegistry,
        probes: Iterable[ProviderCompatibilityProbe],
        *,
        clock: Clock = _utc_now,
    ) -> None:
        if not isinstance(registry, TrustedProviderRegistry):
            raise ProviderCompatibilityServiceError(
                "compatibility service requires a trusted provider registry"
            )
        if not callable(clock):
            raise ProviderCompatibilityServiceError(
                "compatibility service requires a clock"
            )

        by_identity: dict[
            tuple[str, ProviderSurface, str, str], ProviderCompatibilityProbe
        ] = {}
        for probe in tuple(probes):
            try:
                descriptor = probe.descriptor
                registered = registry.get(
                    descriptor.provider,
                    descriptor.surface,
                    decoder_key=descriptor.decoder_key,
                    decoder_version=descriptor.decoder_version,
                )
            except Exception:
                raise ProviderCompatibilityServiceError(
                    "compatibility probe is not registered"
                ) from None
            if registered != descriptor:
                raise ProviderCompatibilityServiceError(
                    "compatibility probe descriptor does not match the registry"
                )
            if descriptor.identity in by_identity:
                raise ProviderCompatibilityServiceError(
                    "compatibility probe is registered more than once"
                )
            if not isinstance(probe, ProviderCompatibilityProbe):
                raise ProviderCompatibilityServiceError(
                    "compatibility probe does not satisfy the safe protocol"
                )
            by_identity[descriptor.identity] = probe

        self._registry = registry
        self._probes = by_identity
        self._clock = clock
        self._reports: dict[
            tuple[str, ProviderSurface, str, str], ProviderCompatibilityReport
        ] = {}
        self._lock = RLock()

    def get_cached(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
        *,
        decoder_key: str,
        decoder_version: str,
    ) -> ProviderCompatibilityReport | None:
        descriptor = self._descriptor(
            provider,
            surface,
            decoder_key=decoder_key,
            decoder_version=decoder_version,
        )
        with self._lock:
            return self._reports.get(descriptor.identity)

    def refresh(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
        *,
        decoder_key: str,
        decoder_version: str,
    ) -> ProviderCompatibilityReport:
        descriptor = self._descriptor(
            provider,
            surface,
            decoder_key=decoder_key,
            decoder_version=decoder_version,
        )
        with self._lock:
            probe = self._probes.get(descriptor.identity)
            try:
                if probe is None:
                    raise ProviderCompatibilityServiceError(
                        "compatibility probe is unavailable"
                    )
                report = probe.check()
                if (
                    not isinstance(report, ProviderCompatibilityReport)
                    or report.descriptor != descriptor
                ):
                    raise ProviderCompatibilityServiceError(
                        "compatibility probe returned mismatched provenance"
                    )
            except Exception:
                # Provider failures can contain content, identifiers, paths, or
                # subprocess details.  They never enter the report or exception
                # chain and are not retained by this service.
                report = _unavailable_report(
                    descriptor,
                    checked_at=self._safe_now(),
                )
            self._reports[descriptor.identity] = report
            return report

    def _descriptor(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
        *,
        decoder_key: str,
        decoder_version: str,
    ) -> DecoderDescriptor:
        try:
            return self._registry.get(
                provider,
                surface,
                decoder_key=decoder_key,
                decoder_version=decoder_version,
            )
        except ProviderRegistryLookupError:
            raise ProviderCompatibilityServiceError(
                "compatibility descriptor is not registered"
            ) from None

    def _safe_now(self) -> datetime:
        try:
            value = self._clock()
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError
            return value.astimezone(UTC)
        except Exception:
            # A broken application clock is configuration failure, not provider
            # drift.  Use the local UTC clock without retaining the exception.
            return _utc_now()
