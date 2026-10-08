"""Local language-detection adapters for ephemeral analysis text."""

from .deterministic import (
    DETERMINISTIC_LANGUAGE_DETECTOR_VERSION,
    DeterministicEnglishPolishDetector,
)

__all__ = [
    "DETERMINISTIC_LANGUAGE_DETECTOR_VERSION",
    "DeterministicEnglishPolishDetector",
]
