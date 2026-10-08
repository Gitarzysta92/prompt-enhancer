"""Redaction port for local diagnostic facts."""

from __future__ import annotations

from typing import Protocol

from pydantic import SecretStr


class DiagnosticRedactor(Protocol):
    version: str

    def redact_value(self, value: SecretStr) -> SecretStr: ...
