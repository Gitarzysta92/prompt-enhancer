"""Provider-neutral release policy over content-free compatibility reports."""

from __future__ import annotations

from collections.abc import Iterable

from .catalog import ProviderCompatibilityCatalog
from .contracts import (
    CapabilityKey,
    CapabilityState,
    CompatibilityState,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
)


class ProviderCompatibilityBlockedError(RuntimeError):
    """The selected surface is not verified for the requested capability."""


class ProviderSurfaceCompatibilityPolicy:
    """Refresh and fail closed before a sensitive provider capability is used."""

    def __init__(
        self,
        catalog: ProviderCompatibilityCatalog,
        *,
        surface: ProviderSurface,
        required_capabilities: Iterable[CapabilityKey],
    ) -> None:
        if not isinstance(catalog, ProviderCompatibilityCatalog):
            raise ValueError("compatibility policy requires a configured catalog")
        required = tuple(required_capabilities)
        if not required or len(set(required)) != len(required):
            raise ValueError("compatibility requirements must be unique and nonempty")
        if any(not isinstance(item, CapabilityKey) for item in required):
            raise ValueError("compatibility requirements must use capability keys")
        self._catalog = catalog
        self._surface = surface
        self._required = required

    def require_compatible(
        self, provider: str | ProviderIdentity
    ) -> ProviderCompatibilityReport:
        try:
            descriptor = self._catalog.descriptor(provider, self._surface)
            if not set(self._required).issubset(descriptor.capabilities):
                raise ProviderCompatibilityBlockedError(
                    "provider decoder does not declare required capabilities"
                )
            report = self._catalog.refresh(provider, self._surface)
            observations = {item.key: item.state for item in report.capabilities}
            if (
                report.state
                not in {CompatibilityState.EXACT, CompatibilityState.COMPATIBLE}
                or report.extraction.state
                is not ExtractionCompletenessState.COMPLETE
                or any(
                    observations.get(capability) is not CapabilityState.SUPPORTED
                    for capability in self._required
                )
            ):
                raise ProviderCompatibilityBlockedError(
                    "provider surface is not verified for this capability"
                )
            return report
        except ProviderCompatibilityBlockedError:
            raise
        except Exception:
            raise ProviderCompatibilityBlockedError(
                "provider compatibility could not be verified"
            ) from None
