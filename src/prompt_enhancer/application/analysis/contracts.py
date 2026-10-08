"""Stable contracts for composing local analysis features and metrics.

Registrations are ordinary Python objects supplied by the application composition
root.  This module intentionally provides no entry-point or filesystem discovery:
metric code must be reviewed and explicitly trusted before it can execute.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from ...domain import DataTier, MetricObservation, MetricSource, SafeEvent, SafeSession


FeatureSet = Mapping[str, object]


@dataclass(frozen=True, slots=True)
class MetricDefinition:
    """Immutable identity and presentation metadata for one metric version."""

    key: str
    version: int
    dimension: str
    display_name: str
    description: str
    unit: str
    source: MetricSource = MetricSource.DETERMINISTIC

    def as_dict(self) -> dict[str, object]:
        return {
            "key": self.key,
            "version": self.version,
            "dimension": self.dimension,
            "display_name": self.display_name,
            "description": self.description,
            "unit": self.unit,
            "source": self.source.value,
        }


@dataclass(frozen=True, slots=True)
class AnalysisContext:
    """Content-free input available to the Phase 1 analysis engine."""

    session: SafeSession
    events: tuple[SafeEvent, ...]


@dataclass(frozen=True, slots=True)
class MetricPack:
    """An explicit, ordered selection of metrics for an analysis use case."""

    key: str
    version: int
    metric_keys: tuple[str, ...]


class FeatureExtractor(Protocol):
    """Compute one reusable feature after its declared dependencies."""

    key: str
    required_features: frozenset[str]
    required_tier: DataTier

    def extract(self, context: AnalysisContext, features: FeatureSet) -> object:
        """Return one safe derived feature without mutating the input."""


class MetricCalculator(Protocol):
    """Turn canonical context and reusable features into one observation."""

    definition: MetricDefinition
    required_features: frozenset[str]
    required_tier: DataTier

    def calculate(
        self,
        context: AnalysisContext,
        features: FeatureSet,
    ) -> MetricObservation:
        """Calculate the metric described by ``definition``."""
