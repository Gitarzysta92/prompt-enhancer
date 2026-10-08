"""Synthetic-only specialist estimator pre-screen.

This package is intentionally separate from product estimator activation and
provider ingestion.  It accepts only the checked-in fictional EN/PL corpus and
never turns a synthetic score into a product metric.
"""

from .contracts import (
    SpecialistAbstentionReason,
    SpecialistCase,
    SpecialistCompatibility,
    SpecialistCorpus,
    SpecialistLabel,
    SpecialistOutcome,
    SpecialistPrediction,
    SpecialistPredictionState,
    SpecialistTaskStratum,
)
from .manifests import (
    MDEBERTA_HISTORICAL_REJECTION,
    MINILMV2_L6_NLI,
    MINILMV2_L12_NLI,
    SPECIALIST_MODEL_MANIFESTS,
)

__all__ = [
    "MDEBERTA_HISTORICAL_REJECTION",
    "MINILMV2_L6_NLI",
    "MINILMV2_L12_NLI",
    "SPECIALIST_MODEL_MANIFESTS",
    "SpecialistAbstentionReason",
    "SpecialistCase",
    "SpecialistCompatibility",
    "SpecialistCorpus",
    "SpecialistLabel",
    "SpecialistOutcome",
    "SpecialistPrediction",
    "SpecialistPredictionState",
    "SpecialistTaskStratum",
]
