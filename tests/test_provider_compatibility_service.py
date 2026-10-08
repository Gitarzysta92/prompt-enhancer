from __future__ import annotations

from datetime import UTC, datetime
from threading import Barrier, Lock, Thread

import pytest

from prompt_enhancer.application.providers import (
    CapabilityKey,
    CapabilityObservation,
    CapabilityState,
    CompatibilityState,
    DecoderDescriptor,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityProbe,
    ProviderCompatibilityReport,
    ProviderCompatibilityService,
    ProviderCompatibilityServiceError,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
    TrustedProviderRegistry,
)


NOW = datetime(2026, 1, 15, 9, 0, tzinfo=UTC)


def _descriptor(*, decoder_version: str = "1") -> DecoderDescriptor:
    return DecoderDescriptor(
        provider=ProviderIdentity(key="example_agent"),
        surface=ProviderSurface.CATALOG,
        adapter_version="example-adapter-1",
        decoder_key="example.catalog.decoder",
        decoder_version=decoder_version,
        wire_schema_family=f"example.catalog.v{decoder_version}",
        canonical_schema_version="canonical.session.v1",
        schema_artifact=SchemaArtifactProvenance(
            artifact_key="example.catalog-schema",
            artifact_version=decoder_version,
            kind=SchemaArtifactKind.SYNTHETIC,
        ),
        capabilities=(CapabilityKey.SESSION_LIST,),
        tested_provider_versions=(f"example-{decoder_version}",),
    )


def _report(descriptor: DecoderDescriptor) -> ProviderCompatibilityReport:
    return ProviderCompatibilityReport(
        descriptor=descriptor,
        provider_version="example-1",
        state=CompatibilityState.EXACT,
        capabilities=(
            CapabilityObservation(
                key=CapabilityKey.SESSION_LIST,
                state=CapabilityState.SUPPORTED,
            ),
        ),
        extraction=ExtractionCompleteness(
            state=ExtractionCompletenessState.COMPLETE,
            observed_units=1,
            eligible_units=1,
            coverage=1,
        ),
        checked_at=NOW,
    )


class RecordingProbe:
    def __init__(
        self,
        descriptor: DecoderDescriptor,
        *,
        failure: Exception | None = None,
        returned_descriptor: DecoderDescriptor | None = None,
    ) -> None:
        self._descriptor = descriptor
        self._failure = failure
        self._returned_descriptor = returned_descriptor
        self.calls = 0
        self._lock = Lock()

    @property
    def descriptor(self) -> DecoderDescriptor:
        return self._descriptor

    def check(self) -> ProviderCompatibilityReport:
        with self._lock:
            self.calls += 1
        if self._failure is not None:
            raise self._failure
        return _report(self._returned_descriptor or self._descriptor)


def test_probe_protocol_and_explicit_refresh_cache_only_reports() -> None:
    descriptor = _descriptor()
    probe = RecordingProbe(descriptor)
    service = ProviderCompatibilityService(
        TrustedProviderRegistry((descriptor,)),
        (probe,),
        clock=lambda: NOW,
    )

    assert isinstance(probe, ProviderCompatibilityProbe)
    assert service.get_cached(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key=descriptor.decoder_key,
        decoder_version=descriptor.decoder_version,
    ) is None
    assert probe.calls == 0

    refreshed = service.refresh(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key=descriptor.decoder_key,
        decoder_version=descriptor.decoder_version,
    )
    cached = service.get_cached(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key=descriptor.decoder_key,
        decoder_version=descriptor.decoder_version,
    )

    assert refreshed is cached
    assert refreshed.state is CompatibilityState.EXACT
    assert probe.calls == 1
    assert set(service.__dict__) == {
        "_registry",
        "_probes",
        "_clock",
        "_reports",
        "_lock",
    }
    assert all(
        isinstance(value, ProviderCompatibilityReport)
        for value in service._reports.values()  # type: ignore[attr-defined]
    )


@pytest.mark.parametrize("mode", ("failure", "mismatch", "missing"))
def test_unexpected_or_missing_probe_becomes_sanitized_unavailable_report(
    mode: str,
) -> None:
    descriptor = _descriptor()
    private_canary = "PRIVATE-PROBE-FAILURE-CANARY"
    probes: tuple[RecordingProbe, ...]
    if mode == "failure":
        probes = (RecordingProbe(descriptor, failure=RuntimeError(private_canary)),)
    elif mode == "mismatch":
        mismatched = _descriptor(decoder_version="2")
        probes = (RecordingProbe(descriptor, returned_descriptor=mismatched),)
    else:
        probes = ()
    service = ProviderCompatibilityService(
        TrustedProviderRegistry((descriptor,)),
        probes,
        clock=lambda: NOW,
    )

    report = service.refresh(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key=descriptor.decoder_key,
        decoder_version=descriptor.decoder_version,
    )

    assert report.state is CompatibilityState.UNAVAILABLE
    assert report.provider_version == "unknown"
    assert report.extraction.state is ExtractionCompletenessState.NONE
    assert report.extraction.coverage is None
    assert all(
        item.state is CapabilityState.UNKNOWN for item in report.capabilities
    )
    assert private_canary not in repr(report) + report.model_dump_json()


def test_service_rejects_unregistered_and_duplicate_probe_descriptors() -> None:
    registered = _descriptor()
    unregistered = _descriptor(decoder_version="2")
    registry = TrustedProviderRegistry((registered,))

    with pytest.raises(ProviderCompatibilityServiceError, match="not registered"):
        ProviderCompatibilityService(registry, (RecordingProbe(unregistered),))
    with pytest.raises(ProviderCompatibilityServiceError, match="more than once"):
        ProviderCompatibilityService(
            registry,
            (RecordingProbe(registered), RecordingProbe(registered)),
        )

    service = ProviderCompatibilityService(registry, ())
    with pytest.raises(ProviderCompatibilityServiceError, match="not registered"):
        service.refresh(
            "cursor",
            ProviderSurface.CATALOG,
            decoder_key=registered.decoder_key,
            decoder_version=registered.decoder_version,
        )


def test_refresh_is_thread_safe_and_each_result_is_an_immutable_report() -> None:
    descriptor = _descriptor()
    probe = RecordingProbe(descriptor)
    service = ProviderCompatibilityService(
        TrustedProviderRegistry((descriptor,)),
        (probe,),
        clock=lambda: NOW,
    )
    barrier = Barrier(5)
    results: list[ProviderCompatibilityReport] = []
    results_lock = Lock()

    def refresh() -> None:
        barrier.wait()
        report = service.refresh(
            "example_agent",
            ProviderSurface.CATALOG,
            decoder_key=descriptor.decoder_key,
            decoder_version=descriptor.decoder_version,
        )
        with results_lock:
            results.append(report)

    threads = tuple(Thread(target=refresh) for _ in range(4))
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(timeout=2)

    assert len(results) == 4
    assert probe.calls == 4
    assert all(item.state is CompatibilityState.EXACT for item in results)
    assert service.get_cached(
        "example_agent",
        ProviderSurface.CATALOG,
        decoder_key=descriptor.decoder_key,
        decoder_version=descriptor.decoder_version,
    ) in results
