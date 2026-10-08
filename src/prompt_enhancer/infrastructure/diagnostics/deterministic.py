"""Adapter over the existing deterministic local redactor."""

from __future__ import annotations

from pydantic import SecretStr

from ..redaction.deterministic import DeterministicLocalRedactor


class DeterministicDiagnosticRedactor:
    def __init__(self, redactor: DeterministicLocalRedactor | None = None) -> None:
        self._redactor = redactor or DeterministicLocalRedactor(max_input_characters=256)
        self.version = self._redactor.version

    def redact_value(self, value: SecretStr) -> SecretStr:
        return self._redactor.redact(value).text
