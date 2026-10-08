"""Provider-neutral compatibility contracts and explicit trusted registry."""

from .contracts import (
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
from .registry import (
    DuplicateDecoderDescriptorError,
    ProviderRegistryError,
    ProviderRegistryLookupError,
    TrustedProviderRegistry,
)
from .service import (
    ProviderCompatibilityProbe,
    ProviderCompatibilityService,
    ProviderCompatibilityServiceError,
)
from .catalog import (
    ProviderCompatibilityCatalog,
    ProviderCompatibilityCatalogError,
)
from .policy import (
    ProviderCompatibilityBlockedError,
    ProviderSurfaceCompatibilityPolicy,
)

__all__ = [
    "CapabilityKey",
    "CapabilityObservation",
    "CapabilityState",
    "CompatibilityReason",
    "CompatibilityReasonCode",
    "CompatibilityState",
    "DecoderDescriptor",
    "DuplicateDecoderDescriptorError",
    "ExtractionCompleteness",
    "ExtractionCompletenessState",
    "ProviderCompatibilityReport",
    "ProviderCompatibilityProbe",
    "ProviderCompatibilityCatalog",
    "ProviderCompatibilityCatalogError",
    "ProviderCompatibilityBlockedError",
    "ProviderCompatibilityService",
    "ProviderCompatibilityServiceError",
    "ProviderIdentity",
    "ProviderRegistryError",
    "ProviderRegistryLookupError",
    "ProviderSurface",
    "ProviderSurfaceCompatibilityPolicy",
    "SchemaArtifactKind",
    "SchemaArtifactProvenance",
    "TrustedProviderRegistry",
]
