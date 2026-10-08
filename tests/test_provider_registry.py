from __future__ import annotations

import pytest

from prompt_enhancer.application.providers import (
    CapabilityKey,
    DecoderDescriptor,
    DuplicateDecoderDescriptorError,
    ProviderIdentity,
    ProviderRegistryError,
    ProviderRegistryLookupError,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
    TrustedProviderRegistry,
)


def _descriptor(
    *,
    provider: str = "example_agent",
    surface: ProviderSurface = ProviderSurface.CATALOG,
    decoder_key: str = "example.catalog.decoder",
    decoder_version: str = "1",
    wire_schema_family: str = "example.catalog.v1",
) -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key=provider),
        surface=surface,
        adapter_version="example-adapter-1",
        decoder_key=decoder_key,
        decoder_version=decoder_version,
        wire_schema_family=wire_schema_family,
        canonical_schema_version="canonical.session.v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="example.catalog-schema",
            artifact_version="1",
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=(CapabilityKey.SESSION_LIST,),
        tested_provider_versions=("example-1",),
    )


def test_registry_is_explicit_immutable_and_supports_versioned_lookups() -> None:
    first = _descriptor()
    second = _descriptor(
        decoder_version="2",
        wire_schema_family="example.catalog.v2",
    )
    text = _descriptor(
        surface=ProviderSurface.TEXT_WINDOW,
        decoder_key="example.text.decoder",
        wire_schema_family="example.text.v1",
    ).model_copy(update={"capabilities": (CapabilityKey.USER_MESSAGES,)})
    cursor = _descriptor(provider="cursor")
    registry = TrustedProviderRegistry((text, second, cursor, first))

    assert tuple(item.key for item in registry.providers) == (
        "cursor",
        "example_agent",
    )
    assert registry.surfaces("example_agent") == (
        ProviderSurface.CATALOG,
        ProviderSurface.TEXT_WINDOW,
    )
    assert registry.for_surface("example_agent", "catalog") == (first, second)
    assert registry.for_schema_family(
        "example_agent", ProviderSurface.CATALOG, "example.catalog.v2"
    ) == (second,)
    assert registry.get(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key="example.catalog.decoder",
        decoder_version="1",
    ) == first
    assert registry.descriptors == tuple(
        sorted(
            registry.descriptors,
            key=lambda item: (
                item.provider.key,
                item.surface.value,
                item.decoder_key,
                item.decoder_version,
            ),
        )
    )

    public_names = {name for name in dir(registry) if not name.startswith("_")}
    assert not {
        "discover",
        "load",
        "load_entry_points",
        "register",
        "remove",
    }.intersection(public_names)


def test_registry_rejects_empty_duplicate_and_non_descriptor_inputs() -> None:
    descriptor = _descriptor()
    with pytest.raises(ProviderRegistryError, match="at least one"):
        TrustedProviderRegistry(())
    with pytest.raises(DuplicateDecoderDescriptorError, match="duplicate"):
        TrustedProviderRegistry((descriptor, descriptor))
    with pytest.raises(ProviderRegistryError, match="descriptors only"):
        TrustedProviderRegistry((descriptor, object()))  # type: ignore[arg-type]


def test_registry_lookup_errors_are_bounded_and_do_not_echo_input() -> None:
    registry = TrustedProviderRegistry((_descriptor(),))
    private_canary = "PRIVATE-REGISTRY-LOOKUP-CANARY"

    operations = (
        lambda: registry.surfaces(private_canary),
        lambda: registry.for_surface("example_agent", "private-surface"),
        lambda: registry.for_schema_family(
            "example_agent", ProviderSurface.CATALOG, private_canary
        ),
        lambda: registry.get(
            "example_agent",
            ProviderSurface.CATALOG,
            decoder_key=private_canary,
            decoder_version="1",
        ),
    )
    for operation in operations:
        with pytest.raises(ProviderRegistryLookupError) as raised:
            operation()
        assert private_canary not in str(raised.value)
