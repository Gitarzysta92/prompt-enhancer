"""Narrow inward-facing ports for provider ingestion orchestration."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Protocol

from ...domain import (
    SAFE_VERSION_PATTERN,
    DataTier,
    MetricObservation,
    Provider,
    SafeEvent,
    SafeSession,
)


class PersistenceOutcome(Protocol):
    session_inserted: int
    session_updated: int
    events_inserted: int
    events_updated: int


class IngestionRepository(Protocol):
    """Persistence capability needed by one ingestion transaction stream."""

    def initialize(self) -> None: ...

    def has_active_consent(
        self, provider: Provider, tier: DataTier = DataTier.METADATA
    ) -> bool: ...

    def begin_ingestion_run(
        self,
        *,
        provider: Provider,
        provider_version: str,
        adapter_version: str,
        source_schema_version: str,
        data_tier: DataTier = DataTier.METADATA,
    ) -> str: ...

    def finish_ingestion_run(
        self,
        run_id: str,
        *,
        status: str,
        sessions_seen: int,
        events_seen: int,
        metrics_written: int,
        error_code: str | None = None,
    ) -> None: ...

    def persist_session(
        self, session: SafeSession, events: Iterable[SafeEvent]
    ) -> PersistenceOutcome: ...

    def get_session(self, session_id: str) -> SafeSession | None: ...

    def supersede_session_events(
        self, session_id: str, *, only_source_schema_version: str
    ) -> int: ...

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]: ...

    def replace_session_metrics(
        self,
        session_id: str,
        observations: Iterable[MetricObservation],
        *,
        metric_pack_key: str,
        metric_pack_version: int,
        metric_engine_version: str,
    ) -> int: ...


class SourceIdentifierProtector(Protocol):
    """One-way domain-separated transformation before persistence."""

    def pseudonymize(self, namespace: str, value: str) -> str: ...


class SessionMetricComputer(Protocol):
    def __call__(
        self, session: SafeSession, events: Iterable[SafeEvent]
    ) -> tuple[MetricObservation, ...]: ...


@dataclass(frozen=True, slots=True)
class SessionMetricPlan:
    """Bind one trusted session calculator to its persisted provenance."""

    computer: SessionMetricComputer
    pack_key: str
    pack_version: int
    metric_engine_version: str

    def __post_init__(self) -> None:
        if not callable(self.computer):
            raise ValueError("session metric computer must be callable")
        if (
            not isinstance(self.pack_key, str)
            or SAFE_VERSION_PATTERN.fullmatch(self.pack_key) is None
        ):
            raise ValueError("session metric pack key must be a safe identifier")
        if (
            isinstance(self.pack_version, bool)
            or not isinstance(self.pack_version, int)
            or self.pack_version < 1
        ):
            raise ValueError("session metric pack version must be positive")
        if (
            not isinstance(self.metric_engine_version, str)
            or SAFE_VERSION_PATTERN.fullmatch(self.metric_engine_version) is None
        ):
            raise ValueError("session metric engine version must be a safe identifier")
