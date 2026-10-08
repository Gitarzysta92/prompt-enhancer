"""Conservative local English/Polish detection for analysis eligibility.

The detector is deliberately an abstaining lexical baseline, not a general
language-identification model. It performs no filesystem or network access and
returns ``UNKNOWN`` when there is not enough discriminative evidence.
"""

from __future__ import annotations

import re
import unicodedata

from pydantic import SecretStr

from ...application.analysis.text_contracts import TextLanguage


DETERMINISTIC_LANGUAGE_DETECTOR_VERSION = "deterministic-en-pl-lexicon-v1"

_WORD = re.compile(r"[^\W\d_]+", re.UNICODE)
_POLISH_DIACRITICS = frozenset("ąćęłńóśźż")

# Exact, discriminative function words and common prompt verbs. Very short
# shared forms (for example Polish ``i`` and English ``to``) are omitted.
_ENGLISH_MARKERS = frozenset(
    {
        "add",
        "after",
        "and",
        "before",
        "because",
        "build",
        "change",
        "check",
        "choose",
        "could",
        "create",
        "each",
        "ensure",
        "every",
        "fix",
        "for",
        "from",
        "has",
        "have",
        "implement",
        "improve",
        "into",
        "is",
        "make",
        "must",
        "need",
        "only",
        "please",
        "should",
        "show",
        "that",
        "the",
        "then",
        "these",
        "this",
        "those",
        "update",
        "validate",
        "verify",
        "when",
        "where",
        "which",
        "while",
        "with",
        "without",
        "would",
        "you",
        "your",
    }
)
_POLISH_MARKERS = frozenset(
    {
        "aby",
        "ale",
        "bez",
        "będzie",
        "chcę",
        "dla",
        "dodaj",
        "gdzie",
        "gdy",
        "jeśli",
        "jesli",
        "jak",
        "każda",
        "każde",
        "każdy",
        "kazda",
        "kazde",
        "kazdy",
        "która",
        "które",
        "który",
        "musi",
        "najpierw",
        "należy",
        "nalezy",
        "napraw",
        "następnie",
        "nastepnie",
        "nie",
        "oraz",
        "pokaż",
        "pokaz",
        "ponieważ",
        "poniewaz",
        "powinien",
        "powinna",
        "powinno",
        "przed",
        "proszę",
        "prosze",
        "sprawdź",
        "sprawdz",
        "stwórz",
        "stworz",
        "teraz",
        "tylko",
        "utwórz",
        "utworz",
        "użyj",
        "uzyj",
        "zaimplementuj",
        "zanim",
        "zbuduj",
        "zmień",
        "zmien",
        "zweryfikuj",
        "żeby",
        "zeby",
    }
)


class DeterministicEnglishPolishDetector:
    """Return EN, PL, MIXED, or an honest UNKNOWN abstention."""

    version = DETERMINISTIC_LANGUAGE_DETECTOR_VERSION

    def detect(self, value: SecretStr) -> TextLanguage:
        if not isinstance(value, SecretStr):
            raise TypeError("language detector accepts SecretStr input only")
        normalized = unicodedata.normalize("NFKC", value.get_secret_value()).casefold()
        tokens = tuple(_WORD.findall(normalized))
        if len(tokens) < 4:
            return TextLanguage.UNKNOWN

        unique_tokens = frozenset(tokens)
        english_score = len(unique_tokens & _ENGLISH_MARKERS)
        polish_score = len(unique_tokens & _POLISH_MARKERS)
        if any(character in _POLISH_DIACRITICS for character in normalized):
            polish_score += 1

        if english_score >= 2 and polish_score >= 2:
            return TextLanguage.MIXED
        if english_score >= 2:
            return TextLanguage.ENGLISH
        if polish_score >= 2:
            return TextLanguage.POLISH
        return TextLanguage.UNKNOWN
