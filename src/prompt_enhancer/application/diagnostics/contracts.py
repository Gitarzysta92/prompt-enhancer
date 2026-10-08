"""Content-bounded contracts for manual, local diagnostic export."""

from __future__ import annotations

from enum import StrEnum

from pydantic import ConfigDict, Field, SecretBytes, SecretStr

from ...domain import StrictModel


class DiagnosticSection(StrEnum):
    APPLICATION = "application"
    DATABASE = "database"
    LOCAL_MODELS = "local_models"
    PACKAGED_RESOURCES = "packaged_resources"
    PLATFORM = "platform"


class DiagnosticValueKind(StrEnum):
    BOOLEAN = "boolean"
    COUNT = "count"
    STATE = "state"
    VERSION = "version"


class DiagnosticObservation(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    section: DiagnosticSection
    event_code: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    fact_key: str = Field(pattern=r"^[a-z][a-z0-9_]{2,63}$")
    value_kind: DiagnosticValueKind
    value: SecretStr = Field(repr=False, min_length=1, max_length=256)


class BundleBudget(StrictModel):
    max_total_bytes: int = Field(default=65_536, ge=1_024, le=1_048_576)
    max_section_bytes: int = Field(default=8_192, ge=256, le=262_144)
    max_observations: int = Field(default=256, ge=1, le=2_048)


class BundlePreview(StrictModel):
    schema_version: int = 1
    byte_count: int = Field(ge=0, le=1_048_576)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    included_sections: tuple[DiagnosticSection, ...]
    included_observations: int = Field(ge=0, le=2_048)
    omitted_observations: int = Field(ge=0)
    truncated: bool
    redactor_version: str = Field(pattern=r"^[a-zA-Z0-9_.\-]{1,96}$")


class DiagnosticBundle(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    preview: BundlePreview
    payload: SecretBytes = Field(repr=False)

    def bytes_for_local_write(self) -> bytes:
        """Return exactly the bytes represented by ``preview``."""

        return self.payload.get_secret_value()
