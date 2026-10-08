from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
import hashlib
import hmac

from prompt_enhancer.application.discovery import (
    CandidateIdentity,
    DiscoveryConfig,
    DiscoverySignal,
    SignalDirection,
    TaskDiscoveryEngine,
)
from prompt_enhancer.domain import Provider, SafeSession, SessionState


class _SyntheticIdFactory:
    def create(self, identity: CandidateIdentity) -> str:
        payload = "|".join(identity.session_ids).encode()
        return hmac.new(b"synthetic-score-key", payload, hashlib.sha256).hexdigest()


@dataclass(frozen=True, slots=True)
class _ZeroStrengthStrategy:
    direction: SignalDirection
    key: str = "discovery.zero_strength"
    version: int = 1
    weight: float = 1.0

    def evaluate(self, left: SafeSession, right: SafeSession) -> DiscoverySignal:
        return DiscoverySignal(
            key=self.key,
            version=self.version,
            session_ids=(left.session_id, right.session_id),
            direction=self.direction,
            confidence=0.0,
            weight=self.weight,
            evidence_code="zero_strength_fixture",
            observed_count=1,
            eligible_count=1,
            coverage=1.0,
        )


def _sessions() -> tuple[SafeSession, SafeSession]:
    base = datetime(2026, 5, 2, 9, 0, tzinfo=UTC)
    common = {
        "provider": Provider.SYNTHETIC,
        "installation_id": "0" * 64,
        "project_id": "1" * 64,
        "provider_version": "synthetic-1",
        "adapter_version": "0.1.0",
        "source_schema_version": "synthetic-1",
        "terminal_state": SessionState.UNKNOWN,
        "events_complete": False,
    }
    return (
        SafeSession(
            **common,
            session_id="a" * 64,
            started_at=base,
            ended_at=None,
        ),
        SafeSession(
            **common,
            session_id="b" * 64,
            started_at=base + timedelta(minutes=1),
            ended_at=None,
        ),
    )


def test_zero_directional_strength_is_neutral_and_never_reverses_direction() -> None:
    sessions = _sessions()
    config = DiscoveryConfig(minimum_link_score=0.5)

    link_result = TaskDiscoveryEngine(
        _SyntheticIdFactory(),
        strategies=(_ZeroStrengthStrategy(SignalDirection.SUPPORTS_LINK),),
        config=config,
    ).discover(sessions)
    boundary_result = TaskDiscoveryEngine(
        _SyntheticIdFactory(),
        strategies=(_ZeroStrengthStrategy(SignalDirection.SUPPORTS_BOUNDARY),),
        config=config,
    ).discover(sessions)

    assert len(link_result.candidates) == 1
    assert len(boundary_result.candidates) == 1
    assert link_result.candidates[0].confidence == 0.5
    assert boundary_result.candidates[0].confidence == 0.5
