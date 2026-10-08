"""Fail-closed temporal capture status for documented Codex inputs.

The current documented Codex adapter boundary does not expose an authoritative
UTC timestamp and a stable snapshot boundary for every source item.  Session,
turn, ordering, listing, read-clock, and local capture values are deliberately
not substitutes.  This module only reports that limitation; it neither reads a
provider nor exposes a product source builder.
"""

from __future__ import annotations

from ...application.history.source_capture import (
    TemporalCaptureCapabilityDescriptor,
    TemporalCaptureCapabilityState,
)
from ...domain import Provider


def codex_temporal_capture_capability() -> TemporalCaptureCapabilityDescriptor:
    """Return immutable product-disabled status, never source authority."""

    return TemporalCaptureCapabilityDescriptor(
        provider=Provider.CODEX,
        capability_state=(
            TemporalCaptureCapabilityState.UNAVAILABLE_MISSING_AUTHORITATIVE_ITEM_TIMESTAMPS
        ),
        authoritative_item_timestamps_available=False,
    )


CODEX_TEMPORAL_CAPTURE_CAPABILITY = codex_temporal_capture_capability()


__all__ = [
    "CODEX_TEMPORAL_CAPTURE_CAPABILITY",
    "codex_temporal_capture_capability",
]
