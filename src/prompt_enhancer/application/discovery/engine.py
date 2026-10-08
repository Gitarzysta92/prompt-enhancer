"""Deterministic, metadata-only engine for reviewable task candidates."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
import math

from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, SafeSession
from .contracts import (
    CandidateIdFactory,
    CandidateIdentity,
    DiscoveryBatch,
    DiscoveryBoundary,
    DiscoverySignal,
    DiscoverySignalStrategy,
    SignalDirection,
    TaskCandidate,
)
from .signals import DEFAULT_DISCOVERY_STRATEGIES


class DiscoveryError(RuntimeError):
    """Sanitized failure that does not disclose pseudonymous input values."""


class InvalidDiscoveryInputError(DiscoveryError):
    """Safe session metadata violates discovery preconditions."""


class CandidateIdError(DiscoveryError):
    """The injected ID factory did not produce a safe candidate pseudonym."""


@dataclass(frozen=True, slots=True)
class DiscoveryConfig:
    discovery_version: str = "metadata-v1"
    minimum_link_score: float = 0.55

    def __post_init__(self) -> None:
        if not SAFE_VERSION_PATTERN.fullmatch(self.discovery_version):
            raise ValueError("discovery version must be a safe identifier")
        if not math.isfinite(self.minimum_link_score) or not (
            0 <= self.minimum_link_score <= 1
        ):
            raise ValueError("minimum link score must be between zero and one")


@dataclass(slots=True)
class _Cluster:
    sessions: list[SafeSession]
    signals: list[DiscoverySignal]
    relation_scores: list[float]


@dataclass(frozen=True, slots=True)
class _RawBoundary:
    left_session_id: str
    right_session_id: str
    signals: tuple[DiscoverySignal, ...]
    link_score: float | None


def _counts(signals: Iterable[DiscoverySignal]) -> tuple[int, int, float]:
    signal_items = tuple(signals)
    observed = sum(signal.observed_count for signal in signal_items)
    eligible = sum(signal.eligible_count for signal in signal_items)
    coverage = 0.0 if eligible == 0 else observed / eligible
    return observed, eligible, coverage


def _link_score(signals: Iterable[DiscoverySignal]) -> float | None:
    weighted_support = 0.0
    total_weight = 0.0
    for signal in signals:
        if signal.direction is SignalDirection.UNKNOWN or signal.confidence is None:
            continue
        # A signal's confidence is directional strength, where zero is weak
        # evidence rather than evidence for the opposite direction. Map it
        # around a neutral 0.5 link score before combining strategy weights.
        support = (
            0.5 + (0.5 * signal.confidence)
            if signal.direction is SignalDirection.SUPPORTS_LINK
            else 0.5 - (0.5 * signal.confidence)
        )
        weighted_support += support * signal.weight
        total_weight += signal.weight
    if total_weight == 0:
        return None
    return weighted_support / total_weight


class TaskDiscoveryEngine:
    """Group adjacent safe sessions into suggestions with inspectable evidence.

    Provider, installation, and project are hard scope boundaries. Within each
    scope, explicitly registered strategies score only adjacent chronological
    sessions. There is no provider read, semantic content access, persistence, or
    automatic task mutation.
    """

    def __init__(
        self,
        candidate_id_factory: CandidateIdFactory,
        *,
        strategies: Iterable[DiscoverySignalStrategy] = DEFAULT_DISCOVERY_STRATEGIES,
        config: DiscoveryConfig = DiscoveryConfig(),
    ) -> None:
        strategy_items = tuple(strategies)
        identities = tuple((strategy.key, strategy.version) for strategy in strategy_items)
        if len(set(identities)) != len(identities):
            raise ValueError("discovery strategy identities must be unique")
        if any(strategy.weight <= 0 for strategy in strategy_items):
            raise ValueError("discovery strategy weights must be positive")
        self._candidate_id_factory = candidate_id_factory
        self._strategies = strategy_items
        self._config = config

    def discover(self, sessions: Iterable[SafeSession]) -> DiscoveryBatch:
        session_items = tuple(sessions)
        if any(not isinstance(session, SafeSession) for session in session_items):
            raise InvalidDiscoveryInputError("discovery accepts only safe sessions")
        session_ids = tuple(session.session_id for session in session_items)
        if len(set(session_ids)) != len(session_ids):
            raise InvalidDiscoveryInputError("discovery input contains a duplicate session")

        scopes: dict[tuple[str, str, str], list[SafeSession]] = defaultdict(list)
        for session in session_items:
            scope = (
                session.provider.value,
                session.installation_id,
                session.project_id,
            )
            scopes[scope].append(session)

        clusters: list[_Cluster] = []
        raw_boundaries: list[_RawBoundary] = []
        for scope in sorted(scopes):
            ordered = sorted(
                scopes[scope],
                key=lambda session: (session.started_at, session.session_id),
            )
            if not ordered:
                continue
            current = _Cluster(sessions=[ordered[0]], signals=[], relation_scores=[])
            for left, right in zip(ordered, ordered[1:]):
                try:
                    relation_signals = tuple(
                        strategy.evaluate(left, right) for strategy in self._strategies
                    )
                except Exception as exc:
                    raise DiscoveryError("discovery signal strategy failed") from None
                for signal, strategy in zip(
                    relation_signals, self._strategies, strict=True
                ):
                    if (
                        signal.key != strategy.key
                        or signal.version != strategy.version
                        or abs(signal.weight - strategy.weight) > 1e-12
                        or signal.session_ids != (left.session_id, right.session_id)
                    ):
                        raise DiscoveryError("discovery signal violated its contract")
                score = _link_score(relation_signals)
                if score is not None and score >= self._config.minimum_link_score:
                    current.sessions.append(right)
                    current.signals.extend(relation_signals)
                    current.relation_scores.append(score)
                else:
                    clusters.append(current)
                    raw_boundaries.append(
                        _RawBoundary(
                            left_session_id=left.session_id,
                            right_session_id=right.session_id,
                            signals=relation_signals,
                            link_score=score,
                        )
                    )
                    current = _Cluster(sessions=[right], signals=[], relation_scores=[])
            clusters.append(current)

        candidates: list[TaskCandidate] = []
        candidate_by_session: dict[str, str] = {}
        for cluster in clusters:
            first = cluster.sessions[0]
            identity = CandidateIdentity(
                discovery_version=self._config.discovery_version,
                provider=first.provider,
                installation_id=first.installation_id,
                project_id=first.project_id,
                session_ids=tuple(sorted(session.session_id for session in cluster.sessions)),
            )
            try:
                candidate_id = self._candidate_id_factory.create(identity)
            except Exception:
                raise CandidateIdError("candidate ID factory failed") from None
            if not isinstance(candidate_id, str) or not PSEUDONYM_PATTERN.fullmatch(
                candidate_id
            ):
                raise CandidateIdError(
                    "candidate ID factory returned an invalid pseudonym"
                )
            if candidate_id in {candidate.candidate_id for candidate in candidates}:
                raise CandidateIdError("candidate ID factory returned a duplicate pseudonym")

            observed, eligible, coverage = _counts(cluster.signals)
            confidence = (
                min(cluster.relation_scores) if cluster.relation_scores else None
            )
            candidate = TaskCandidate(
                candidate_id=candidate_id,
                discovery_version=self._config.discovery_version,
                provider=first.provider,
                installation_id=first.installation_id,
                project_id=first.project_id,
                session_ids=tuple(session.session_id for session in cluster.sessions),
                signals=tuple(cluster.signals),
                confidence=confidence,
                observed_count=observed,
                eligible_count=eligible,
                coverage=coverage,
            )
            candidates.append(candidate)
            for session in cluster.sessions:
                candidate_by_session[session.session_id] = candidate_id

        boundaries: list[DiscoveryBoundary] = []
        for raw in raw_boundaries:
            observed, eligible, coverage = _counts(raw.signals)
            boundaries.append(
                DiscoveryBoundary(
                    left_candidate_id=candidate_by_session[raw.left_session_id],
                    right_candidate_id=candidate_by_session[raw.right_session_id],
                    left_session_id=raw.left_session_id,
                    right_session_id=raw.right_session_id,
                    signals=raw.signals,
                    confidence=(
                        None if raw.link_score is None else 1.0 - raw.link_score
                    ),
                    observed_count=observed,
                    eligible_count=eligible,
                    coverage=coverage,
                )
            )

        return DiscoveryBatch(
            discovery_version=self._config.discovery_version,
            candidates=tuple(candidates),
            boundaries=tuple(boundaries),
        )
