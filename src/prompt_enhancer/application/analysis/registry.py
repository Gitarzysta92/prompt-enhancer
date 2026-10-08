"""Validated, explicit registry and dependency-driven analysis engine."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from types import MappingProxyType
from typing import AbstractSet

from ...domain import DataTier, MetricObservation, SafeEvent, SafeSession
from .contracts import (
    AnalysisContext,
    FeatureExtractor,
    MetricCalculator,
    MetricDefinition,
    MetricPack,
)


DEFAULT_ALLOWED_TIERS = frozenset({DataTier.METADATA})


class AnalysisRegistryError(ValueError):
    """The trusted analysis composition is internally inconsistent."""


class DuplicateMetricDefinitionError(AnalysisRegistryError):
    """Two calculators claim the same metric key."""


class DuplicateFeatureError(AnalysisRegistryError):
    """Two extractors claim the same feature key."""


class MissingDependencyError(AnalysisRegistryError):
    """A metric or feature references an unregistered feature."""


class DependencyCycleError(AnalysisRegistryError):
    """Feature dependencies contain a cycle."""


class PrivacyTierDeniedError(PermissionError):
    """The selected analysis requires a tier not granted for this run."""


class MetricContractError(RuntimeError):
    """A trusted calculator returned an observation outside its contract."""


class TrustedAnalysisRegistry:
    """Immutable registry built only from explicitly supplied trusted objects.

    No dynamic module, package entry-point, model, or filesystem discovery occurs
    here.  Construction validates all identities and the complete feature graph so
    configuration errors fail before any session data is processed.
    """

    def __init__(
        self,
        *,
        calculators: Iterable[MetricCalculator],
        feature_extractors: Iterable[FeatureExtractor],
        packs: Iterable[MetricPack],
    ) -> None:
        calculator_items = tuple(calculators)
        extractor_items = tuple(feature_extractors)
        pack_items = tuple(packs)

        calculators_by_key: dict[str, MetricCalculator] = {}
        for calculator in calculator_items:
            key = calculator.definition.key
            if key in calculators_by_key:
                raise DuplicateMetricDefinitionError(
                    "duplicate metric definition in trusted registry"
                )
            calculators_by_key[key] = calculator

        extractors_by_key: dict[str, FeatureExtractor] = {}
        for extractor in extractor_items:
            if extractor.key in extractors_by_key:
                raise DuplicateFeatureError(
                    "duplicate feature extractor in trusted registry"
                )
            extractors_by_key[extractor.key] = extractor

        packs_by_key: dict[str, MetricPack] = {}
        for pack in pack_items:
            if pack.key in packs_by_key:
                raise AnalysisRegistryError("duplicate metric pack in trusted registry")
            if len(set(pack.metric_keys)) != len(pack.metric_keys):
                raise AnalysisRegistryError("metric pack contains a duplicate metric")
            unknown_metrics = set(pack.metric_keys) - calculators_by_key.keys()
            if unknown_metrics:
                raise AnalysisRegistryError("metric pack references an unknown metric")
            packs_by_key[pack.key] = pack

        self._validate_dependencies(calculator_items, extractors_by_key)
        self._validate_acyclic(extractors_by_key)

        self._calculator_order = tuple(
            calculator.definition.key for calculator in calculator_items
        )
        self._calculators: Mapping[str, MetricCalculator] = MappingProxyType(
            calculators_by_key
        )
        self._extractors: Mapping[str, FeatureExtractor] = MappingProxyType(
            extractors_by_key
        )
        self._packs: Mapping[str, MetricPack] = MappingProxyType(packs_by_key)

    @staticmethod
    def _validate_dependencies(
        calculators: tuple[MetricCalculator, ...],
        extractors: Mapping[str, FeatureExtractor],
    ) -> None:
        known_features = extractors.keys()
        for extractor in extractors.values():
            if not extractor.required_features <= known_features:
                raise MissingDependencyError(
                    "feature extractor references an unregistered dependency"
                )
        for calculator in calculators:
            if not calculator.required_features <= known_features:
                raise MissingDependencyError(
                    "metric calculator references an unregistered feature"
                )

    @staticmethod
    def _validate_acyclic(extractors: Mapping[str, FeatureExtractor]) -> None:
        visiting: set[str] = set()
        visited: set[str] = set()

        def visit(key: str) -> None:
            if key in visited:
                return
            if key in visiting:
                raise DependencyCycleError("feature dependency cycle detected")
            visiting.add(key)
            for dependency in sorted(extractors[key].required_features):
                visit(dependency)
            visiting.remove(key)
            visited.add(key)

        for key in sorted(extractors):
            visit(key)

    @property
    def definitions(self) -> tuple[MetricDefinition, ...]:
        """Metric definitions in deterministic registration order."""

        return tuple(
            self._calculators[key].definition for key in self._calculator_order
        )

    def calculator(self, key: str) -> MetricCalculator:
        try:
            return self._calculators[key]
        except KeyError:
            raise AnalysisRegistryError("unknown metric key") from None

    def extractor(self, key: str) -> FeatureExtractor:
        try:
            return self._extractors[key]
        except KeyError:
            raise AnalysisRegistryError("unknown feature key") from None

    def pack(self, key: str) -> MetricPack:
        try:
            return self._packs[key]
        except KeyError:
            raise AnalysisRegistryError("unknown metric pack") from None


class MetricEngine:
    """Evaluate an explicit metric pack through a cached feature DAG."""

    def __init__(self, registry: TrustedAnalysisRegistry) -> None:
        self._registry = registry

    @property
    def registry(self) -> TrustedAnalysisRegistry:
        return self._registry

    def compute_session(
        self,
        session: SafeSession,
        events: Iterable[SafeEvent],
        *,
        pack_key: str,
        allowed_tiers: AbstractSet[DataTier] = DEFAULT_ALLOWED_TIERS,
    ) -> tuple[MetricObservation, ...]:
        context = AnalysisContext(session=session, events=tuple(events))
        pack = self._registry.pack(pack_key)
        calculators = tuple(
            self._registry.calculator(key) for key in pack.metric_keys
        )

        required_feature_keys: set[str] = set()
        required_feature_order: list[str] = []

        def include_feature(key: str) -> None:
            if key in required_feature_keys:
                return
            for dependency in sorted(self._registry.extractor(key).required_features):
                include_feature(dependency)
            required_feature_keys.add(key)
            required_feature_order.append(key)

        for calculator in calculators:
            for feature_key in sorted(calculator.required_features):
                include_feature(feature_key)

        # Fail closed before extracting any feature. Tiers are explicit
        # capabilities rather than an ordering: granting raw-vault access does not
        # implicitly grant remote-redacted processing, or vice versa.
        required_tiers = {
            calculator.required_tier for calculator in calculators
        } | {
            self._registry.extractor(key).required_tier
            for key in required_feature_order
        }
        denied_tiers = required_tiers - set(allowed_tiers)
        if denied_tiers:
            raise PrivacyTierDeniedError(
                "selected analysis requires an unavailable data tier"
            )

        feature_values: dict[str, object] = {}

        def extract_feature(key: str) -> None:
            if key in feature_values:
                return
            extractor = self._registry.extractor(key)
            for dependency in sorted(extractor.required_features):
                extract_feature(dependency)
            dependency_view = MappingProxyType(
                {
                    dependency: feature_values[dependency]
                    for dependency in sorted(extractor.required_features)
                }
            )
            feature_values[key] = extractor.extract(
                context, dependency_view
            )

        for key in required_feature_order:
            extract_feature(key)

        observations: list[MetricObservation] = []
        for calculator in calculators:
            calculator_features = MappingProxyType(
                {
                    key: feature_values[key]
                    for key in sorted(calculator.required_features)
                }
            )
            observation = calculator.calculate(context, calculator_features)
            definition = calculator.definition
            if not isinstance(observation, MetricObservation) or (
                observation.key != definition.key
                or observation.version != definition.version
                or observation.unit != definition.unit
            ):
                raise MetricContractError(
                    "metric calculator returned an observation outside its definition"
                )
            observations.append(observation)
        return tuple(observations)
