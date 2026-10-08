"""Built-in metadata-only strategies for deterministic task discovery."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import timedelta

from ...domain import SafeSession, SessionState
from .contracts import DiscoverySignal, SignalDirection


def _coverage(observed_count: int, eligible_count: int) -> float:
    return 0.0 if eligible_count == 0 else observed_count / eligible_count


@dataclass(frozen=True, slots=True)
class TemporalProximityStrategy:
    """Compare adjacent session windows without inventing missing end times.

    When an end time is unknown, the always-observed start-to-start distance is
    used with deliberately lower confidence and 50% temporal evidence coverage.
    """

    maximum_gap: timedelta = timedelta(hours=2)
    key: str = "discovery.temporal_proximity"
    version: int = 1
    weight: float = 3.0

    def __post_init__(self) -> None:
        if self.maximum_gap <= timedelta(0):
            raise ValueError("maximum temporal gap must be positive")
        if self.weight <= 0:
            raise ValueError("temporal signal weight must be positive")

    def evaluate(self, left: SafeSession, right: SafeSession) -> DiscoverySignal:
        maximum_seconds = self.maximum_gap.total_seconds()
        if right.started_at < left.started_at:
            raise ValueError("adjacent sessions must be chronologically ordered")

        if left.ended_at is None:
            distance = (right.started_at - left.started_at).total_seconds()
            observed_count = 1
            eligible_count = 2
            if distance <= maximum_seconds:
                ratio = distance / maximum_seconds
                direction = SignalDirection.SUPPORTS_LINK
                confidence = 0.75 - (0.20 * ratio)
                evidence_code = "start_gap_without_end_time"
            else:
                excess_ratio = min(1.0, (distance - maximum_seconds) / maximum_seconds)
                direction = SignalDirection.SUPPORTS_BOUNDARY
                confidence = 0.55 + (0.30 * excess_ratio)
                evidence_code = "distant_start_without_end_time"
        elif right.started_at <= left.ended_at:
            distance = 0.0
            observed_count = 2
            eligible_count = 2
            direction = SignalDirection.SUPPORTS_LINK
            confidence = 0.85
            evidence_code = "overlapping_session_windows"
        else:
            distance = (right.started_at - left.ended_at).total_seconds()
            observed_count = 2
            eligible_count = 2
            if distance <= maximum_seconds:
                ratio = distance / maximum_seconds
                direction = SignalDirection.SUPPORTS_LINK
                confidence = 0.85 - (0.25 * ratio)
                evidence_code = "within_temporal_window"
            else:
                excess_ratio = min(1.0, (distance - maximum_seconds) / maximum_seconds)
                direction = SignalDirection.SUPPORTS_BOUNDARY
                confidence = 0.60 + (0.35 * excess_ratio)
                evidence_code = "outside_temporal_window"

        return DiscoverySignal(
            key=self.key,
            version=self.version,
            session_ids=(left.session_id, right.session_id),
            direction=direction,
            confidence=confidence,
            weight=self.weight,
            evidence_code=evidence_code,
            observed_count=observed_count,
            eligible_count=eligible_count,
            coverage=_coverage(observed_count, eligible_count),
            numeric_evidence=distance,
            evidence_unit="seconds",
        )


@dataclass(frozen=True, slots=True)
class TerminalContinuityStrategy:
    """Use provider terminal state as weak workflow evidence, never task proof."""

    key: str = "discovery.terminal_continuity"
    version: int = 1
    weight: float = 1.0

    def __post_init__(self) -> None:
        if self.weight <= 0:
            raise ValueError("terminal signal weight must be positive")

    def evaluate(self, left: SafeSession, right: SafeSession) -> DiscoverySignal:
        state = left.terminal_state
        if state is SessionState.UNKNOWN:
            direction = SignalDirection.UNKNOWN
            confidence = None
            observed_count = 0
            evidence_code = "terminal_state_unknown"
        elif state is SessionState.BLOCKED:
            direction = SignalDirection.SUPPORTS_LINK
            confidence = 0.80
            observed_count = 1
            evidence_code = "previous_session_blocked"
        elif state is SessionState.INTERRUPTED:
            direction = SignalDirection.SUPPORTS_LINK
            confidence = 0.75
            observed_count = 1
            evidence_code = "previous_session_interrupted"
        elif state is SessionState.FAILED:
            direction = SignalDirection.SUPPORTS_LINK
            confidence = 0.60
            observed_count = 1
            evidence_code = "previous_session_failed"
        elif state is SessionState.ABANDONED:
            direction = SignalDirection.SUPPORTS_BOUNDARY
            confidence = 0.65
            observed_count = 1
            evidence_code = "previous_session_abandoned"
        else:
            # Completion is only a weak boundary signal: an assistant's terminal
            # claim is not objective evidence that the user's task is complete.
            direction = SignalDirection.SUPPORTS_BOUNDARY
            confidence = 0.35
            observed_count = 1
            evidence_code = "previous_session_completed"

        return DiscoverySignal(
            key=self.key,
            version=self.version,
            session_ids=(left.session_id, right.session_id),
            direction=direction,
            confidence=confidence,
            weight=self.weight,
            evidence_code=evidence_code,
            observed_count=observed_count,
            eligible_count=1,
            coverage=_coverage(observed_count, 1),
        )


DEFAULT_DISCOVERY_STRATEGIES = (
    TemporalProximityStrategy(),
    TerminalContinuityStrategy(),
)
