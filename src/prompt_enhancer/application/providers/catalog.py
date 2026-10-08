"""Configured provider decoders and their content-free compatibility reports."""

from __future__ import annotations

from collections.abc import Iterable

from .contracts import (
    DecoderDescriptor,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
)
from .service import ProviderCompatibilityService


class ProviderCompatibilityCatalogError(LookupError):
    """A sanitized active-decoder lookup failure."""


def _provider_key(value: str | ProviderIdentity) -> str:
    if isinstance(value, ProviderIdentity):
        return value.key
    try:
        return ProviderIdentity(key=value).key
    except Exception:
        raise ProviderCompatibilityCatalogError(
            "provider compatibility key is invalid"
        ) from None


def _surface(value: ProviderSurface | str) -> ProviderSurface:
    try:
        return value if isinstance(value, ProviderSurface) else ProviderSurface(value)
    except (TypeError, ValueError):
        raise ProviderCompatibilityCatalogError(
            "provider compatibility surface is invalid"
        ) from None


class ProviderCompatibilityCatalog:
    """Bind one explicitly selected decoder to each active provider surface.

    Decoder discovery is intentionally absent. Adding or changing an adapter is
    a composition-root and release action; runtime checks can only exercise the
    trusted descriptors already present in this immutable catalog.
    """

    def __init__(
        self,
        service: ProviderCompatibilityService,
        active_descriptors: Iterable[DecoderDescriptor],
    ) -> None:
        if not isinstance(service, ProviderCompatibilityService):
            raise ValueError("compatibility catalog requires a trusted service")
        selected: dict[tuple[str, ProviderSurface], DecoderDescriptor] = {}
        for descriptor in tuple(active_descriptors):
            if not isinstance(descriptor, DecoderDescriptor):
                raise ValueError("active compatibility entries must be descriptors")
            key = (descriptor.provider.key, descriptor.surface)
            if key in selected:
                raise ValueError(
                    "only one decoder may be active for a provider surface"
                )
            selected[key] = descriptor
        if not selected:
            raise ValueError("compatibility catalog requires an active decoder")
        self._service = service
        self._selected = selected

    @property
    def descriptors(self) -> tuple[DecoderDescriptor, ...]:
        return tuple(
            sorted(
                self._selected.values(),
                key=lambda item: (item.provider.key, item.surface.value),
            )
        )

    def descriptor(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
    ) -> DecoderDescriptor:
        descriptor = self._selected.get((_provider_key(provider), _surface(surface)))
        if descriptor is None:
            raise ProviderCompatibilityCatalogError(
                "provider compatibility surface is not configured"
            )
        return descriptor

    def get_cached(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
    ) -> ProviderCompatibilityReport | None:
        descriptor = self.descriptor(provider, surface)
        return self._service.get_cached(
            descriptor.provider,
            descriptor.surface,
            decoder_key=descriptor.decoder_key,
            decoder_version=descriptor.decoder_version,
        )

    def refresh(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
    ) -> ProviderCompatibilityReport:
        descriptor = self.descriptor(provider, surface)
        return self._service.refresh(
            descriptor.provider,
            descriptor.surface,
            decoder_key=descriptor.decoder_key,
            decoder_version=descriptor.decoder_version,
        )
