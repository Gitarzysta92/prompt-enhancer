"""Deterministic, local, best-effort redaction for ephemeral analysis text.

This is a privacy reduction layer, not an anonymizer.  It targets common
credentials and structured identifiers before text enters local analysis.  It
cannot reliably identify personal names, organization-specific identifiers,
business facts, source-code secrets without recognizable syntax, or every
language-specific form of personal data.  Its output remains sensitive and must
not be persisted or sent to a network service.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import StrEnum
import re
import unicodedata

from pydantic import ConfigDict, Field, SecretStr

from ...application.analysis.text_contracts import (
    MAX_REDACTED_MESSAGE_CHARACTERS,
)
from ...domain import StrictModel


DETERMINISTIC_REDACTOR_VERSION = "deterministic-local-redactor-v1"


class LocalRedactionError(RuntimeError):
    """A sanitized local-redaction failure."""


class LocalRedactionLimitError(LocalRedactionError):
    """The private input exceeded the explicit in-memory text bound."""


class RedactionCategory(StrEnum):
    SECRET = "secret"
    EMAIL = "email"
    URL = "url"
    PATH = "path"
    IP_ADDRESS = "ip_address"
    PHONE = "phone"
    TOKEN = "token"
    CONTROL = "control"


class RedactionCount(StrictModel):
    category: RedactionCategory
    count: int = Field(ge=1)


class RedactedText(StrictModel):
    """Repr-safe ephemeral output; ``SecretStr`` is masking, not encryption."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
    )

    text: SecretStr = Field(
        repr=False,
        min_length=1,
        max_length=MAX_REDACTED_MESSAGE_CHARACTERS,
    )
    replacements: tuple[RedactionCount, ...] = ()


_PatternReplacement = str | Callable[[re.Match[str]], str]
_Rule = tuple[RedactionCategory, re.Pattern[str], _PatternReplacement]


def _credential_assignment(match: re.Match[str]) -> str:
    return f"{match.group('key')}{match.group('separator')}[SECRET]"


_RULES: tuple[_Rule, ...] = (
    (
        RedactionCategory.SECRET,
        re.compile(
            r"(?i)(?P<key>\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|"
            r"client[_-]?secret|password|passwd|secret|token))"
            r"(?P<separator>\s*[:=]\s*)(?:['\"]?)[^\s,'\";}]+"
        ),
        _credential_assignment,
    ),
    (
        RedactionCategory.SECRET,
        re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]{8,}"),
        "Bearer [SECRET]",
    ),
    (
        RedactionCategory.SECRET,
        re.compile(
            r"\b[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\."
            r"[A-Za-z0-9_-]{8,}\b"
        ),
        "[SECRET]",
    ),
    (
        RedactionCategory.SECRET,
        re.compile(
            r"\b(?:AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9_-]{16,}|"
            r"gh[opusr]_[A-Za-z0-9]{16,})\b"
        ),
        "[SECRET]",
    ),
    (
        RedactionCategory.EMAIL,
        re.compile(
            r"(?i)(?<![A-Z0-9._%+-])[A-Z0-9._%+-]+@"
            r"[A-Z0-9.-]+\.[A-Z]{2,}(?![A-Z0-9._%+-])"
        ),
        "[EMAIL]",
    ),
    (
        RedactionCategory.URL,
        re.compile(r"(?i)\b(?:https?|ftp)://[^\s<>\"']+"),
        "[URL]",
    ),
    (
        RedactionCategory.PATH,
        re.compile(
            r"(?i)(?<![A-Z0-9_])[A-Z]:\\(?:[^\\\s:*?\"<>|]+\\)*"
            r"[^\\\s:*?\"<>|]*"
        ),
        "[PATH]",
    ),
    (
        RedactionCategory.PATH,
        re.compile(r"(?<!\w)\\\\[^\s\\]+\\[^\s]+"),
        "[PATH]",
    ),
    (
        RedactionCategory.PATH,
        re.compile(
            r"(?<![:\w])/(?:[A-Za-z0-9._-]+/)+[A-Za-z0-9._-]+"
        ),
        "[PATH]",
    ),
    (
        RedactionCategory.IP_ADDRESS,
        re.compile(
            r"(?<!\d)(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}"
            r"(?:25[0-5]|2[0-4]\d|1?\d?\d)(?!\d)"
        ),
        "[IP_ADDRESS]",
    ),
    (
        RedactionCategory.IP_ADDRESS,
        re.compile(r"\b(?:[0-9A-Fa-f]{1,4}:){2,7}[0-9A-Fa-f]{1,4}\b"),
        "[IP_ADDRESS]",
    ),
    (
        RedactionCategory.PHONE,
        re.compile(r"(?<!\w)\+\d(?:[\s().-]?\d){7,14}\b"),
        "[PHONE]",
    ),
    (
        RedactionCategory.TOKEN,
        re.compile(r"(?<![A-Za-z0-9_-])[A-Za-z0-9_-]{32,}(?![A-Za-z0-9_-])"),
        "[TOKEN]",
    ),
)

_CONTROL_CHARACTERS = re.compile(r"[\x01-\x08\x0b\x0c\x0e-\x1f\x7f]")


class DeterministicLocalRedactor:
    """Apply a fixed ordered ruleset without filesystem or network access."""

    version = DETERMINISTIC_REDACTOR_VERSION

    def __init__(
        self,
        *,
        max_input_characters: int = MAX_REDACTED_MESSAGE_CHARACTERS,
    ) -> None:
        if (
            isinstance(max_input_characters, bool)
            or not isinstance(max_input_characters, int)
            or max_input_characters < 1
            or max_input_characters > MAX_REDACTED_MESSAGE_CHARACTERS
        ):
            raise ValueError("redactor input bound is invalid")
        self._max_input_characters = max_input_characters

    def redact(self, value: SecretStr) -> RedactedText:
        if not isinstance(value, SecretStr):
            raise TypeError("redactor accepts SecretStr input only")
        private_text = value.get_secret_value()
        if not private_text:
            raise LocalRedactionError("redaction input cannot be empty")
        if "\x00" in private_text:
            raise LocalRedactionError("redaction input contains an unsupported control")
        if len(private_text) > self._max_input_characters:
            raise LocalRedactionLimitError("redaction input exceeded the character bound")

        redacted = unicodedata.normalize("NFKC", private_text)
        redacted = redacted.replace("\r\n", "\n").replace("\r", "\n")
        counts: dict[RedactionCategory, int] = {}

        redacted, control_count = _CONTROL_CHARACTERS.subn(" ", redacted)
        if control_count:
            counts[RedactionCategory.CONTROL] = control_count

        for category, pattern, replacement in _RULES:
            redacted, count = pattern.subn(replacement, redacted)
            if count:
                counts[category] = counts.get(category, 0) + count

        if not redacted or not redacted.strip():
            raise LocalRedactionError("redaction produced no analyzable text")
        if len(redacted) > self._max_input_characters:
            raise LocalRedactionLimitError("redacted text exceeded the character bound")
        return RedactedText(
            text=SecretStr(redacted),
            replacements=tuple(
                RedactionCount(category=category, count=count)
                for category, count in sorted(counts.items(), key=lambda pair: pair[0].value)
            ),
        )
