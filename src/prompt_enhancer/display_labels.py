"""Local-only minimization for sensitive project and session display names."""

from __future__ import annotations

import re
import unicodedata


PROJECT_DISPLAY_NAME_MAX_LENGTH = 120
SESSION_DISPLAY_NAME_MAX_LENGTH = 160
_REJECTED_BIDI_CLASSES = frozenset(
    {"RLE", "LRE", "RLO", "LRO", "PDF", "RLI", "LRI", "FSI", "PDI"}
)
_ABSOLUTE_PATH_PATTERN = re.compile(
    r"(?ix)(?:^|[\s(\[{\"'<:=,;])"
    r"(?:[a-z]:[\\/]|\\\\[^\\/\s]+[\\/]|//[^/\s]+/|"
    r"/[^/\s][^\s]*|file://)"
)


def minimize_private_display_name(value: str, *, max_length: int) -> str | None:
    """Return a bounded one-line label, or None for unsafe input."""

    if max_length < 1:
        raise ValueError("display-name bound must be positive")
    normalized = unicodedata.normalize("NFKC", value)
    if _ABSOLUTE_PATH_PATTERN.search(normalized) is not None:
        return None
    if any(
        unicodedata.category(character) in {"Cc", "Cf", "Cs"}
        or unicodedata.bidirectional(character) in _REJECTED_BIDI_CLASSES
        for character in normalized
    ):
        return None
    compact = " ".join(normalized.split())
    if not compact:
        return None
    bounded = compact[:max_length].rstrip()
    return bounded or None


def require_private_display_name(
    value: str | None,
    *,
    max_length: int,
) -> str | None:
    """Validate an already-minimized label without echoing it in failures."""

    if value is None:
        return None
    if minimize_private_display_name(value, max_length=max_length) != value:
        raise ValueError("private display name is not safely minimized")
    return value
