"""Repository-sealed, non-activating calibration-report receipts.

The models in this module remain constructible Python values.  Construction is
not proof of repository authority: callers must obtain a receipt through a
``CalibrationReportRepository`` and that repository must recursively hydrate
and rederive the complete v16/v17/v19 lineage before returning it.
"""

from __future__ import annotations

from datetime import datetime, timedelta
import hashlib
import json
import math
from typing import Literal, Protocol

from pydantic import field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, StrictModel
from .calibration_report_contracts import UntrustedCalibrationReportV1


REPOSITORY_SEALED_CALIBRATION_REPORT_V1 = (
    "repository-sealed-calibration-report-v1"
)


def _canonical_payload_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise ValueError("timestamp must be UTC")
    return value


def _contains_negative_zero(value: object) -> bool:
    if isinstance(value, float):
        return value == 0.0 and math.copysign(1.0, value) < 0.0
    if isinstance(value, dict):
        return any(_contains_negative_zero(item) for item in value.values())
    if isinstance(value, (tuple, list)):
        return any(_contains_negative_zero(item) for item in value)
    return False


def repository_calibration_receipt_id(
    report_fingerprint: str, derived_at: datetime
) -> str:
    """Return the deterministic identity of one repository seal."""

    _digest(report_fingerprint)
    _utc(derived_at)
    return _canonical_payload_digest(
        {
            "domain": REPOSITORY_SEALED_CALIBRATION_REPORT_V1,
            "report_fingerprint": report_fingerprint,
            "derived_at": derived_at.isoformat(timespec="microseconds"),
        }
    )


class RepositorySealedCalibrationReportV1(StrictModel):
    """Exact repository seal over an unchanged untrusted report value.

    ``repository_owned`` describes what a successfully hydrated repository
    value represents; it is not a capability bit.  Recursive rederivation at
    the repository boundary is the authority check.
    """

    contract_version: Literal[
        REPOSITORY_SEALED_CALIBRATION_REPORT_V1
    ] = REPOSITORY_SEALED_CALIBRATION_REPORT_V1
    receipt_id: str
    report: UntrustedCalibrationReportV1
    report_fingerprint: str
    definition_fingerprint: str
    metric_report_fingerprints: tuple[str, ...]
    derived_at: datetime
    repository_owned: Literal[True] = True
    repository_sealed: Literal[True] = True
    persistence_state: Literal["repository_sealed"] = "repository_sealed"
    comparison_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False

    _digests = field_validator(
        "receipt_id", "report_fingerprint", "definition_fingerprint"
    )(_digest)
    _time = field_validator("derived_at")(_utc)

    @field_validator("metric_report_fingerprints")
    @classmethod
    def canonical_metric_roots(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        checked = tuple(_digest(value) for value in values)
        if not checked:
            raise ValueError("sealed report requires metric roots")
        return checked

    @model_validator(mode="after")
    def validate_exact_seal(self) -> RepositorySealedCalibrationReportV1:
        # Reconstruct every nested contract.  This deliberately defeats
        # ``model_copy`` and ``model_construct`` validator bypasses.
        report = UntrustedCalibrationReportV1.model_validate(
            self.report.model_dump(mode="python")
        )
        if _contains_negative_zero(report.model_dump(mode="python")):
            raise ValueError("negative zero is not a canonical stored scalar")
        if self.report_fingerprint != report.fingerprint:
            raise ValueError("seal does not bind the complete report fingerprint")
        if self.definition_fingerprint != report.definition.fingerprint:
            raise ValueError("seal does not bind the fixed report definition")
        expected_metric_roots = tuple(
            item.fingerprint for item in report.metric_reports
        )
        if self.metric_report_fingerprints != expected_metric_roots:
            raise ValueError("seal does not bind every ordered metric report")
        if self.derived_at != report.source_observed_at:
            raise ValueError("one repository timestamp must bind observation and seal")
        if self.receipt_id != repository_calibration_receipt_id(
            self.report_fingerprint, self.derived_at
        ):
            raise ValueError("repository receipt identifier is not reproducible")
        return self

    @property
    def fingerprint(self) -> str:
        return _canonical_payload_digest(self.model_dump(mode="json"))


def revalidate_repository_sealed_calibration_report_v1(
    receipt: RepositorySealedCalibrationReportV1,
) -> RepositorySealedCalibrationReportV1:
    """Recursively rebuild a receipt at a trust boundary."""

    return RepositorySealedCalibrationReportV1.model_validate(
        receipt.model_dump(mode="python")
    )


class CalibrationReportRepository(Protocol):
    """Narrow repository-owned derivation surface."""

    def derive_calibration_report(
        self, submission_id: str
    ) -> RepositorySealedCalibrationReportV1: ...

    def get_calibration_report_for_submission(
        self, submission_id: str
    ) -> RepositorySealedCalibrationReportV1 | None: ...


__all__ = [
    "REPOSITORY_SEALED_CALIBRATION_REPORT_V1",
    "CalibrationReportRepository",
    "RepositorySealedCalibrationReportV1",
    "repository_calibration_receipt_id",
    "revalidate_repository_sealed_calibration_report_v1",
]
