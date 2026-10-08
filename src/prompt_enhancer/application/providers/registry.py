"""Explicit immutable registry for trusted built-in provider decoders.

The registry stores declarative descriptors only.  It deliberately has no
entry-point discovery, import-by-name, runtime registration, or adapter factory
surface.  Concrete code is selected later by the composition root after it has
chosen a descriptor from this closed registry.
"""

from __future__ import annotations

from collections.abc import Iterable
from types import MappingProxyType

from ...domain import SAFE_VERSION_PATTERN
from .contracts import DecoderDescriptor, ProviderIdentity, ProviderSurface


class ProviderRegistryError(ValueError):
    """Base error with a content-free, provider-neutral message."""


class DuplicateDecoderDescriptorError(ProviderRegistryError):
    pass


class ProviderRegistryLookupError(ProviderRegistryError, LookupError):
    pass


def _provider_key(value: str | ProviderIdentity) -> str:
    if isinstance(value, ProviderIdentity):
        return value.key
    try:
        return ProviderIdentity(key=value).key
    except Exception:
        raise ProviderRegistryLookupError("provider registry key is invalid") from None


def _surface(value: ProviderSurface | str) -> ProviderSurface:
    try:
        return value if isinstance(value, ProviderSurface) else ProviderSurface(value)
    except (TypeError, ValueError):
        raise ProviderRegistryLookupError("provider surface is invalid") from None


class TrustedProviderRegistry:
    """Closed descriptor collection assembled explicitly by trusted code."""

    def __init__(self, descriptors: Iterable[DecoderDescriptor]) -> None:
        materialized = tuple(descriptors)
        if not materialized:
            raise ProviderRegistryError(
                "trusted provider registry requires at least one descriptor"
            )

        by_identity: dict[
            tuple[str, ProviderSurface, str, str], DecoderDescriptor
        ] = {}
        by_surface: dict[tuple[str, ProviderSurface], list[DecoderDescriptor]] = {}
        for descriptor in materialized:
            if not isinstance(descriptor, DecoderDescriptor):
                raise ProviderRegistryError(
                    "trusted provider registry accepts decoder descriptors only"
                )
            if descriptor.identity in by_identity:
                raise DuplicateDecoderDescriptorError(
                    "duplicate decoder descriptor in trusted provider registry"
                )
            by_identity[descriptor.identity] = descriptor
            by_surface.setdefault(
                (descriptor.provider.key, descriptor.surface), []
            ).append(descriptor)

        self._descriptors = tuple(
            sorted(
                materialized,
                key=lambda item: (
                    item.provider.key,
                    item.surface.value,
                    item.decoder_key,
                    item.decoder_version,
                ),
            )
        )
        self._by_identity = MappingProxyType(by_identity)
        self._by_surface = MappingProxyType(
            {
                key: tuple(
                    sorted(
                        values,
                        key=lambda item: (item.decoder_key, item.decoder_version),
                    )
                )
                for key, values in by_surface.items()
            }
        )

    @property
    def descriptors(self) -> tuple[DecoderDescriptor, ...]:
        return self._descriptors

    @property
    def providers(self) -> tuple[ProviderIdentity, ...]:
        keys = sorted({item.provider.key for item in self._descriptors})
        return tuple(ProviderIdentity(key=key) for key in keys)

    def surfaces(
        self, provider: str | ProviderIdentity
    ) -> tuple[ProviderSurface, ...]:
        key = _provider_key(provider)
        surfaces = sorted(
            {
                descriptor.surface
                for descriptor in self._descriptors
                if descriptor.provider.key == key
            },
            key=lambda item: item.value,
        )
        if not surfaces:
            raise ProviderRegistryLookupError(
                "provider is not present in the trusted registry"
            )
        return tuple(surfaces)

    def for_surface(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
    ) -> tuple[DecoderDescriptor, ...]:
        key = (_provider_key(provider), _surface(surface))
        descriptors = self._by_surface.get(key)
        if descriptors is None:
            raise ProviderRegistryLookupError(
                "provider surface is not present in the trusted registry"
            )
        return descriptors

    def for_schema_family(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
        wire_schema_family: str,
    ) -> tuple[DecoderDescriptor, ...]:
        if (
            not isinstance(wire_schema_family, str)
            or SAFE_VERSION_PATTERN.fullmatch(wire_schema_family) is None
        ):
            raise ProviderRegistryLookupError("wire schema family is invalid")
        descriptors = tuple(
            descriptor
            for descriptor in self.for_surface(provider, surface)
            if descriptor.wire_schema_family == wire_schema_family
        )
        if not descriptors:
            raise ProviderRegistryLookupError(
                "wire schema family is not present in the trusted registry"
            )
        return descriptors

    def get(
        self,
        provider: str | ProviderIdentity,
        surface: ProviderSurface | str,
        *,
        decoder_key: str,
        decoder_version: str,
    ) -> DecoderDescriptor:
        if (
            not isinstance(decoder_key, str)
            or not isinstance(decoder_version, str)
            or SAFE_VERSION_PATTERN.fullmatch(decoder_key) is None
            or SAFE_VERSION_PATTERN.fullmatch(decoder_version) is None
        ):
            raise ProviderRegistryLookupError(
                "decoder registry identity is invalid"
            )

        identity = (
            _provider_key(provider),
            _surface(surface),
            decoder_key,
            decoder_version,
        )
        descriptor = self._by_identity.get(identity)
        if descriptor is None:
            raise ProviderRegistryLookupError(
                "decoder is not present in the trusted registry"
            )
        return descriptor
