from __future__ import annotations

import pytest
from pydantic import SecretStr

from prompt_enhancer.application.analysis.text_contracts import TextLanguage
from prompt_enhancer.infrastructure.language import (
    DETERMINISTIC_LANGUAGE_DETECTOR_VERSION,
    DeterministicEnglishPolishDetector,
)


@pytest.mark.parametrize(
    ("text", "expected"),
    (
        (
            "Build the local report and verify every result before release.",
            TextLanguage.ENGLISH,
        ),
        (
            "Zbuduj lokalny raport i zweryfikuj każdy wynik przed wydaniem.",
            TextLanguage.POLISH,
        ),
        (
            "Please build the report, ale najpierw sprawdź dane i zweryfikuj wynik.",
            TextLanguage.MIXED,
        ),
        ("API v2 dashboard metrics", TextLanguage.UNKNOWN),
        ("Construire le rapport local avec validation.", TextLanguage.UNKNOWN),
        ("Plan test data model now.", TextLanguage.UNKNOWN),
    ),
)
def test_detector_is_conservative_for_english_polish_and_ambiguous_text(
    text: str,
    expected: TextLanguage,
) -> None:
    detector = DeterministicEnglishPolishDetector()

    assert detector.version == DETERMINISTIC_LANGUAGE_DETECTOR_VERSION
    assert detector.detect(SecretStr(text)) is expected


def test_detector_requires_repr_safe_input() -> None:
    with pytest.raises(TypeError, match="SecretStr"):
        DeterministicEnglishPolishDetector().detect("plain")  # type: ignore[arg-type]
