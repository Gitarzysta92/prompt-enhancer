"""Backward-compatible facade for deterministic session metrics.

The implementation lives in :mod:`prompt_enhancer.application.analysis` so new
features and calculators can be composed without changing ingestion, persistence,
API, or callers of ``compute_session_metrics``.
"""

from __future__ import annotations

from collections.abc import Iterable

from .application.analysis.contracts import MetricDefinition
from .application.analysis.deterministic import (
    DEFAULT_ANALYSIS_REGISTRY,
    DEFAULT_METRIC_ENGINE,
    DEFAULT_METRIC_PACK_KEY,
    METRIC_ENGINE_VERSION,
    NOT_APPLICABLE_VERSION,
)
from .application.analysis.task_metrics import (
    TASK_METRIC_DEFINITIONS,
    TASK_METRIC_ENGINE_VERSION,
)
from .application.analysis.text_baselines import (
    TEXT_METRIC_DEFINITIONS,
    TEXT_METRIC_ENGINE_VERSION,
)
from .application.analysis.coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_ENGINE_VERSION,
)
from .domain import MetricObservation, MetricSource, SafeEvent, SafeSession


TEXT_METRIC_PRESENTATION_DEFINITIONS = tuple(
    MetricDefinition(
        key=definition.key,
        version=definition.version,
        dimension=definition.dimension,
        display_name=definition.display_name,
        description=definition.description,
        unit=definition.unit,
        source=MetricSource.DETERMINISTIC,
    )
    for definition in TEXT_METRIC_DEFINITIONS
)
COACHING_METRIC_PRESENTATION_DEFINITIONS = tuple(
    MetricDefinition(
        key=definition.key,
        version=definition.version,
        dimension=definition.dimension,
        display_name=definition.display_name,
        description=definition.description,
        unit=definition.unit,
        source=MetricSource.DETERMINISTIC,
    )
    for definition in COACHING_METRIC_DEFINITIONS
)
METRIC_DEFINITIONS = (
    DEFAULT_ANALYSIS_REGISTRY.definitions
    + TASK_METRIC_DEFINITIONS
    + TEXT_METRIC_PRESENTATION_DEFINITIONS
    + COACHING_METRIC_PRESENTATION_DEFINITIONS
)
_TASK_METRIC_IDENTITIES = frozenset(
    (definition.key, definition.version) for definition in TASK_METRIC_DEFINITIONS
)
_TEXT_METRIC_IDENTITIES = frozenset(
    (definition.key, definition.version)
    for definition in TEXT_METRIC_PRESENTATION_DEFINITIONS
)
_COACHING_METRIC_IDENTITIES = frozenset(
    (definition.key, definition.version)
    for definition in COACHING_METRIC_PRESENTATION_DEFINITIONS
)


def metric_engine_version_for_definition(definition: MetricDefinition) -> str:
    """Return the immutable calculator family recorded for a definition."""

    identity = (definition.key, definition.version)
    if identity in _TASK_METRIC_IDENTITIES:
        return TASK_METRIC_ENGINE_VERSION
    if identity in _TEXT_METRIC_IDENTITIES:
        return TEXT_METRIC_ENGINE_VERSION
    if identity in _COACHING_METRIC_IDENTITIES:
        return COACHING_METRIC_ENGINE_VERSION
    return METRIC_ENGINE_VERSION


def compute_session_metrics(
    session: SafeSession,
    events: Iterable[SafeEvent],
) -> tuple[MetricObservation, ...]:
    """Compute the trusted metadata-only metric pack.

    This stable adapter preserves the original public function while routing the
    calculation through the validated registry, privacy gate, and feature DAG.
    """

    return DEFAULT_METRIC_ENGINE.compute_session(
        session,
        events,
        pack_key=DEFAULT_METRIC_PACK_KEY,
    )


__all__ = [
    "METRIC_DEFINITIONS",
    "METRIC_ENGINE_VERSION",
    "MetricDefinition",
    "NOT_APPLICABLE_VERSION",
    "TEXT_METRIC_PRESENTATION_DEFINITIONS",
    "COACHING_METRIC_PRESENTATION_DEFINITIONS",
    "compute_session_metrics",
    "metric_engine_version_for_definition",
]
