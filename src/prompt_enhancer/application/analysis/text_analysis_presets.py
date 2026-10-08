"""Versioned, content-free presets for one-click local text analysis.

Presets live in the application layer so an HTTP client cannot silently redefine
metric applicability, denominators, or provider-read bounds.  Selecting a preset
is still only a content-free scope decision; the separate per-run confirmation
and local consent gates remain authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from .text_baselines import TEXT_METRIC_DEFINITIONS
from .text_baselines import (
    DEFAULT_TEXT_METRIC_PACK_KEY,
    DEFAULT_TEXT_METRIC_PACK_VERSION,
)
from .coaching_baselines import (
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
)
from .text_contracts import (
    ApplicabilityBasis,
    GoalSlot,
    MetricApplicability,
    MetricApplicabilityDecision,
    TextTaskProfile,
)


class TextAnalysisPresetId(StrEnum):
    STANDARD_ENGINEERING_V1 = "standard_engineering_v1"
    COACHING_PROFILE_V1 = "coaching_profile_v1"


@dataclass(frozen=True, slots=True)
class TextAnalysisPreset:
    preset_id: TextAnalysisPresetId
    analysis_profile_key: str
    analysis_profile_version: int
    metric_pack_key: str
    metric_pack_version: int
    task_profile: TextTaskProfile
    max_messages: int
    max_characters: int


STANDARD_ENGINEERING_V1 = TextAnalysisPreset(
    preset_id=TextAnalysisPresetId.STANDARD_ENGINEERING_V1,
    analysis_profile_key="standard_engineering",
    analysis_profile_version=1,
    metric_pack_key=DEFAULT_TEXT_METRIC_PACK_KEY,
    metric_pack_version=DEFAULT_TEXT_METRIC_PACK_VERSION,
    task_profile=TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=definition.key,
                applicability=MetricApplicability.APPLICABLE,
                basis=ApplicabilityBasis.TASK_PROFILE,
            )
            for definition in TEXT_METRIC_DEFINITIONS
        ),
        expected_goal_slots=(
            GoalSlot.ACTION,
            GoalSlot.TARGET,
            GoalSlot.OUTCOME,
        ),
        # Constraint and deliverable denominators are task-specific.  Empty
        # sets deliberately abstain instead of turning absent configuration
        # into a low score.
        expected_constraint_kinds=(),
        expected_deliverable_slots=(),
        # The deterministic engine may form a conservative denominator from
        # detected requirements; if it cannot, it abstains.
        expected_outcome_count=None,
    ),
    max_messages=100,
    max_characters=100_000,
)


COACHING_PROFILE_V1 = TextAnalysisPreset(
    preset_id=TextAnalysisPresetId.COACHING_PROFILE_V1,
    analysis_profile_key="coaching_profile",
    analysis_profile_version=1,
    metric_pack_key=COACHING_METRIC_PACK_KEY,
    metric_pack_version=COACHING_METRIC_PACK_VERSION,
    task_profile=TextTaskProfile(
        applicability=tuple(
            MetricApplicabilityDecision(
                metric_key=definition.key,
                applicability=MetricApplicability.APPLICABLE,
                basis=ApplicabilityBasis.TASK_PROFILE,
            )
            for definition in COACHING_METRIC_DEFINITIONS
        ),
        # These legacy task-profile denominator fields are not used by the
        # coaching calculators. They remain explicit and empty so no hidden
        # task-specific expectation can become a zero score.
        expected_goal_slots=(),
        expected_constraint_kinds=(),
        expected_deliverable_slots=(),
        expected_outcome_count=None,
    ),
    max_messages=100,
    max_characters=100_000,
)


_PRESETS = {
    STANDARD_ENGINEERING_V1.preset_id: STANDARD_ENGINEERING_V1,
    COACHING_PROFILE_V1.preset_id: COACHING_PROFILE_V1,
}


def resolve_text_analysis_preset(
    preset_id: TextAnalysisPresetId,
) -> TextAnalysisPreset:
    """Resolve only the closed, versioned preset vocabulary."""

    if not isinstance(preset_id, TextAnalysisPresetId):
        raise TypeError("analysis preset identifier is invalid")
    return _PRESETS[preset_id]


__all__ = [
    "STANDARD_ENGINEERING_V1",
    "COACHING_PROFILE_V1",
    "TextAnalysisPreset",
    "TextAnalysisPresetId",
    "resolve_text_analysis_preset",
]
