"""Explicit plan/open-loop episodes for the r3 ``logic.open_loop_closure`` contract.

This extractor is *ephemeral*.  It never writes a semantic-unit receipt and it
never changes what the persisted ``semantic-units.v1`` receipt set means: the
built-in reconciler owns no ``open_loop`` unit kind today, and this module does
not add one.  It reads the same bounded, redacted analysis window the metric
projector already holds and returns content-free episode statistics that live
exactly as long as one local run.

The contract is deliberately structural and high precision:

* **Opportunity.**  One episode per documented ``AGENT`` + ``PLAN`` message.
  That message kind is a provider-declared structure, not a guess about what a
  sentence meant.  Exactly one episode owns exactly one plan message, so a
  chunked, duplicated, or re-read window cannot inflate the denominator.
* **Closure.**  An episode is closed only when a *later* ``AGENT`` ``ACTION``
  or ``VERIFICATION`` message names that exact plan message in its
  ``supersedes_message_ids``.  The link is an explicit identifier the source
  declared, never token overlap, topical similarity, adjacency, or a shared
  event identity.  An unrelated later action therefore leaves the plan open.
* **Censoring.**  An episode with no such link is right-censored, not failed.
  It stays ``pending`` and contributes to the published bounds instead of
  manufacturing a zero at the right edge of the window.

Absence is never authority.  If the window declares no plan-message capability,
or declares it and contains no plan message, the metric returns a named
actionable unknown rather than "not applicable" or zero: a session with no
observed plan proves nothing about whether the agent left loops open.

Nothing here is a neural inference, a factor score, or a calibrated estimate.
``product_metric_eligible`` stays false and calibration stays unassessed for
this metric exactly as for every other contract in the registry.
"""

from __future__ import annotations

from dataclasses import dataclass

from .semantic_units import SemanticUnitIdFactory, semantic_source_digest
from .text_contracts import (
    EphemeralRedactedMessage,
    P1TextAnalysisInput,
    TextMessageKind,
    TextRole,
)


OPEN_LOOP_LIFECYCLE_V3_KEY = "logic.open-loop-closure.explicit-plan-link"
OPEN_LOOP_LIFECYCLE_V3_VERSION = "open-loop-lifecycle-v3-1"
#: The message kind that opens an episode and the kinds that may close one.
OPEN_LOOP_EPISODE_KIND = TextMessageKind.PLAN
OPEN_LOOP_CLOSING_KINDS = frozenset(
    {TextMessageKind.ACTION, TextMessageKind.VERIFICATION}
)
#: Content-free reasons, mirrored by the readiness catalog.
REASON_OPEN_LOOP_PLAN_CAPABILITY_ABSENT = "open_loop_plan_capability_absent"
REASON_OPEN_LOOP_PLAN_EPISODE_ABSENT = "open_loop_plan_episode_absent"
REASON_OPEN_LOOP_EXPLICIT_PLAN_LINKS = "open_loop_explicit_plan_links"


@dataclass(frozen=True, slots=True)
class OpenLoopEpisode:
    """One plan message and the explicit link that closed it, if any.

    ``owner_source_digest`` is the same keyed digest the semantic-unit
    reconciler computes for a message, so an episode joins to the rest of the
    projection without carrying a reversible message identifier.
    """

    episode_id: str
    owner_source_digest: str
    opened_at_sequence: int
    closed_at_sequence: int | None

    @property
    def closed(self) -> bool:
        return self.closed_at_sequence is not None


@dataclass(frozen=True, slots=True)
class OpenLoopLifecycleProjection:
    """Content-free episode set for one analysis window.

    ``capability_available`` is false in two distinct situations that a metric
    must treat identically and a *reader* must be able to tell apart: the
    provider surface never declared plan messages, or it declared them and this
    window contains none.  ``reason_code`` carries that distinction.
    """

    episodes: tuple[OpenLoopEpisode, ...]
    capability_available: bool
    reason_code: str
    extractor_key: str = OPEN_LOOP_LIFECYCLE_V3_KEY
    extractor_version: str = OPEN_LOOP_LIFECYCLE_V3_VERSION

    @property
    def closed_count(self) -> int:
        return sum(1 for item in self.episodes if item.closed)

    @property
    def pending_count(self) -> int:
        return sum(1 for item in self.episodes if not item.closed)


def _closing_link(
    plan: EphemeralRedactedMessage,
    messages: tuple[EphemeralRedactedMessage, ...],
) -> EphemeralRedactedMessage | None:
    """The one message that explicitly closes ``plan``, or ``None``.

    Several later messages may each declare the link.  The earliest by
    ``(sequence, message_id)`` wins, which is the same total order the
    semantic-unit reconciler uses to pick a replacement, so two producers never
    disagree about which message owns a closure.
    """

    candidates = tuple(
        message
        for message in messages
        if message.sequence > plan.sequence
        and message.role is TextRole.AGENT
        and message.kind in OPEN_LOOP_CLOSING_KINDS
        and plan.message_id in message.supersedes_message_ids
    )
    return min(
        candidates,
        key=lambda item: (item.sequence, item.message_id),
        default=None,
    )


def project_open_loop_lifecycle_v3(
    context: P1TextAnalysisInput,
    id_factory: SemanticUnitIdFactory,
) -> OpenLoopLifecycleProjection:
    """Extract the explicit plan episodes of one bounded analysis window."""

    if OPEN_LOOP_EPISODE_KIND not in context.available_message_kinds:
        # The provider surface never promised plan messages.  An empty episode
        # set is then a statement about the adapter, not about the session.
        return OpenLoopLifecycleProjection(
            episodes=(),
            capability_available=False,
            reason_code=REASON_OPEN_LOOP_PLAN_CAPABILITY_ABSENT,
        )
    messages = context.messages
    plans = tuple(
        message
        for message in messages
        if message.role is TextRole.AGENT
        and message.kind is OPEN_LOOP_EPISODE_KIND
    )
    if not plans:
        # Plan messages are observable but this window has none.  There is no
        # denominator to publish, and an absent classifier input must not
        # become an authoritative "no opportunity" or a zero.
        return OpenLoopLifecycleProjection(
            episodes=(),
            capability_available=False,
            reason_code=REASON_OPEN_LOOP_PLAN_EPISODE_ABSENT,
        )
    episodes: list[OpenLoopEpisode] = []
    for plan in plans:
        closer = _closing_link(plan, messages)
        episodes.append(
            OpenLoopEpisode(
                episode_id=id_factory.fingerprint(
                    "open-loop-episode-v3",
                    (
                        OPEN_LOOP_LIFECYCLE_V3_VERSION,
                        context.provider.value,
                        context.session_id,
                        plan.message_id,
                    ),
                ),
                owner_source_digest=semantic_source_digest(
                    id_factory,
                    provider=context.provider,
                    session_id=context.session_id,
                    message_id=plan.message_id,
                ),
                opened_at_sequence=plan.sequence,
                closed_at_sequence=None if closer is None else closer.sequence,
            )
        )
    ordered = tuple(
        sorted(episodes, key=lambda item: (item.opened_at_sequence, item.episode_id))
    )
    owners = {item.owner_source_digest for item in ordered}
    if len(owners) != len(ordered):
        raise ValueError("open-loop episodes must have exactly one owner each")
    return OpenLoopLifecycleProjection(
        episodes=ordered,
        capability_available=True,
        reason_code=REASON_OPEN_LOOP_EXPLICIT_PLAN_LINKS,
    )


__all__ = [
    "OPEN_LOOP_CLOSING_KINDS",
    "OPEN_LOOP_EPISODE_KIND",
    "OPEN_LOOP_LIFECYCLE_V3_KEY",
    "OPEN_LOOP_LIFECYCLE_V3_VERSION",
    "OpenLoopEpisode",
    "OpenLoopLifecycleProjection",
    "REASON_OPEN_LOOP_EXPLICIT_PLAN_LINKS",
    "REASON_OPEN_LOOP_PLAN_CAPABILITY_ABSENT",
    "REASON_OPEN_LOOP_PLAN_EPISODE_ABSENT",
    "project_open_loop_lifecycle_v3",
]
