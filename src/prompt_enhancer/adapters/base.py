"""Provider adapter contract.

Mutation methods are intentionally absent. Implementations may probe, list, and
read only the source scope explicitly authorized by the user.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from enum import StrEnum
from typing import Iterator

from pydantic import BaseModel, ConfigDict

from ..domain import (
    DataTier,
    Provider,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
)


class AdapterHealth(StrEnum):
    READY = "ready"
    UNAVAILABLE = "unavailable"
    INCOMPATIBLE = "incompatible"


class AdapterProbe(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    provider: Provider
    provider_version: str
    adapter_version: str
    source_schema_version: str
    supports_metadata: bool
    supports_content: bool
    supports_watch: bool
    health: AdapterHealth


class ProviderAdapter(ABC):
    @property
    def required_consent_tier(self) -> DataTier:
        """Return the local source-access tier required by this adapter."""

        return DataTier.METADATA

    @property
    def requires_explicit_selection(self) -> bool:
        """Whether detail access must be bounded by safe persisted selectors."""

        return False

    @property
    @abstractmethod
    def provider(self) -> Provider:
        raise NotImplementedError

    @abstractmethod
    def probe(self) -> AdapterProbe:
        raise NotImplementedError

    @abstractmethod
    def list_sessions(self, *, cursor: str | None = None, limit: int = 100) -> SourceSessionPage:
        raise NotImplementedError

    @abstractmethod
    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        raise NotImplementedError

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        """Read and enrich one session without mutating provider state."""

        return SourceSessionSnapshot(
            session=session,
            events=tuple(self.read_events(session)),
        )

    @abstractmethod
    def health(self) -> AdapterHealth:
        raise NotImplementedError

    def close(self) -> None:
        """Release adapter-owned resources without touching provider state."""
