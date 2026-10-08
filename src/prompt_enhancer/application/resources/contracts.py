"""Content-free resource location results safe for composition roots."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import ConfigDict, Field, model_validator

from ...domain import StrictModel


class ResourceKind(StrEnum):
    DASHBOARD_STATIC = "dashboard_static"
    ACCELERATOR_PROBE = "accelerator_probe"
    THIRD_PARTY_NOTICES = "third_party_notices"
    SOFTWARE_BILL_OF_MATERIALS = "software_bill_of_materials"
    APPLICATION_UPDATE_TRUST = "application_update_trust"


class ResourceShape(StrEnum):
    FILE = "file"
    DIRECTORY = "directory"


class ResourceAvailability(StrEnum):
    AVAILABLE = "available"
    MISSING = "missing"
    REJECTED = "rejected"
    UNSUPPORTED_LAYOUT = "unsupported_layout"


class ResolvedResource(StrictModel):
    model_config = ConfigDict(extra="forbid", frozen=True, hide_input_in_errors=True)

    kind: ResourceKind
    availability: ResourceAvailability
    path: Path | None = Field(default=None, repr=False)
    reason_code: str | None = Field(default=None, pattern=r"^[a-z0-9_]{1,64}$")

    @model_validator(mode="after")
    def validate_availability(self) -> ResolvedResource:
        if self.availability is ResourceAvailability.AVAILABLE:
            if self.path is None or self.reason_code is not None:
                raise ValueError("available resource requires only a path")
        elif self.path is not None or self.reason_code is None:
            raise ValueError("unavailable resource requires only a reason code")
        return self
