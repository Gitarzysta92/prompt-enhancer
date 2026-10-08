"""Schema-only native export/import path for consumer-subscription models.

There is deliberately no Claude consumer CLI subprocess adapter here. Consumer
subscription output may enter the application only through this explicit,
user-driven, schema-validated import boundary. BYOK/cloud integrations implement
the protocol below in a separately reviewed adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import hashlib
import hmac
import json
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError, field_validator, model_validator

from ...application.estimators import (
    EvidencePacketReceipt,
    ExecutionDestination,
    ExecutionDisclosure,
    ModelExecutionMode,
)
from ...domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, Provider, StrictModel
from .codex import RunnerResponseState, RunnerStructuredResponse
from .subprocess import RunnerInputTooLarge, SafeRunnerError


MANUAL_NATIVE_EXPORT_VERSION = "manual-native-estimator-export-v1"
MANUAL_IMPORT_RECEIPT_VERSION = "manual-estimator-import-receipt-v1"
DEFAULT_MANUAL_IMPORT_LIMIT_BYTES = 2 * 1024 * 1024

CLAUDE_CONSUMER_CLI_AUTOMATION_SUPPORTED: Literal[False] = False


class ManualImportProtocolError(SafeRunnerError):
    pass


class ApprovedByokEstimatorTransport(Protocol):
    """Future adapter seam; implementations require a separate privacy review."""

    def run_approved(
        self,
        *,
        evidence_receipt: EvidencePacketReceipt,
        evidence_packet: bytes,
        execution: ExecutionDisclosure,
    ) -> object:
        """Execute one already-approved packet without retaining raw payloads."""
        ...


class ManualNativeExport(StrictModel):
    """Minimal structured envelope copied from a provider-native interaction."""

    schema_version: Literal[MANUAL_NATIVE_EXPORT_VERSION] = MANUAL_NATIVE_EXPORT_VERSION
    provider: Literal[Provider.CLAUDE_CODE]
    requested_model_id: str
    served_model_id: str
    requested_revision: str
    served_revision: str
    requested_execution_mode: ModelExecutionMode
    served_execution_mode: ModelExecutionMode
    evidence_packet_sha256: str
    exported_at: datetime
    response: RunnerStructuredResponse = Field(repr=False)

    @field_validator(
        "requested_model_id", "served_model_id", "requested_revision", "served_revision"
    )
    @classmethod
    def safe_model_identity(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("manual model identity must be a safe identifier")
        return value

    @field_validator("evidence_packet_sha256")
    @classmethod
    def safe_packet_digest(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("packet identity must be a SHA-256 digest")
        return value

    @field_validator("exported_at")
    @classmethod
    def utc_export_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("manual export timestamp must be UTC")
        return value


class ManualImportReceipt(StrictModel):
    receipt_version: Literal[MANUAL_IMPORT_RECEIPT_VERSION] = (
        MANUAL_IMPORT_RECEIPT_VERSION
    )
    provider: Literal[Provider.CLAUDE_CODE]
    requested_model_id: str
    served_model_id: str
    requested_revision: str
    served_revision: str
    requested_execution_mode: ModelExecutionMode
    served_execution_mode: ModelExecutionMode
    fallback_used: bool
    evidence_packet_sha256: str
    import_payload_sha256: str
    imported_at: datetime
    response_state: RunnerResponseState
    identity_provenance: Literal["manual_native_export_claim"] = (
        "manual_native_export_claim"
    )
    automated_consumer_cli: Literal[False] = False
    activation_eligible: Literal[False] = False
    structured_output_valid: Literal[True] = True
    raw_payload_retained: Literal[False] = False

    @field_validator(
        "requested_model_id", "served_model_id", "requested_revision", "served_revision"
    )
    @classmethod
    def safe_model_identity(cls, value: str) -> str:
        if SAFE_VERSION_PATTERN.fullmatch(value) is None:
            raise ValueError("manual model identity must be a safe identifier")
        return value

    @field_validator("evidence_packet_sha256", "import_payload_sha256")
    @classmethod
    def safe_digest(cls, value: str) -> str:
        if PSEUDONYM_PATTERN.fullmatch(value) is None:
            raise ValueError("manual import identity must be a SHA-256 digest")
        return value

    @field_validator("imported_at")
    @classmethod
    def utc_import_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() != timedelta(0):
            raise ValueError("manual import timestamp must be UTC")
        return value

    @model_validator(mode="after")
    def validate_fallback(self) -> ManualImportReceipt:
        observed = (
            self.requested_model_id != self.served_model_id
            or self.requested_revision != self.served_revision
            or self.requested_execution_mode is not self.served_execution_mode
        )
        if self.fallback_used != observed:
            raise ValueError("manual fallback flag disagrees with the export")
        return self


@dataclass(frozen=True, slots=True, repr=False)
class ManualImportRequest:
    payload: bytes = field(repr=False)
    expected_requested_model_id: str
    expected_evidence_receipt: EvidencePacketReceipt
    execution: ExecutionDisclosure

    def __repr__(self) -> str:
        return (
            "ManualImportRequest("
            f"expected_requested_model_id={self.expected_requested_model_id!r}, "
            "payload=<redacted>, "
            f"evidence_packet_sha256={self.expected_evidence_receipt.packet_sha256!r})"
        )


@dataclass(frozen=True, slots=True, repr=False)
class ManualImportResult:
    response: RunnerStructuredResponse = field(repr=False)
    receipt: ManualImportReceipt

    def __repr__(self) -> str:
        return f"ManualImportResult(receipt={self.receipt!r}, response=<redacted>)"


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate key")
        result[key] = value
    return result


def import_manual_native_export(
    request: ManualImportRequest,
    *,
    max_payload_bytes: int = DEFAULT_MANUAL_IMPORT_LIMIT_BYTES,
    now: datetime | None = None,
) -> ManualImportResult:
    """Validate a native export in memory and return only structured judgments."""

    if not 1 <= max_payload_bytes <= 16 * 1024 * 1024:
        raise ManualImportProtocolError("manual_import_invalid_limit")
    if len(request.payload) > max_payload_bytes:
        raise RunnerInputTooLarge("manual_import_payload_limit")
    if SAFE_VERSION_PATTERN.fullmatch(request.expected_requested_model_id) is None:
        raise ManualImportProtocolError("manual_import_invalid_expected_model")
    if request.execution.destination is not ExecutionDestination.MANUAL_IMPORT:
        raise ManualImportProtocolError("manual_import_destination_mismatch")

    try:
        text = request.payload.decode("utf-8", errors="strict")
        data = json.loads(text, object_pairs_hook=_reject_duplicate_keys)
        exported = ManualNativeExport.model_validate(data)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError, ValidationError) as error:
        raise ManualImportProtocolError("manual_import_invalid_schema") from error

    if not hmac.compare_digest(
        exported.evidence_packet_sha256,
        request.expected_evidence_receipt.packet_sha256,
    ):
        raise ManualImportProtocolError("manual_import_packet_mismatch")
    if not hmac.compare_digest(
        exported.requested_model_id,
        request.expected_requested_model_id,
    ):
        raise ManualImportProtocolError("manual_import_model_mismatch")

    imported_at = datetime.now(UTC) if now is None else now
    if imported_at.tzinfo is None or imported_at.utcoffset() != timedelta(0):
        raise ManualImportProtocolError("manual_import_now_not_utc")
    fallback_used = (
        exported.requested_model_id != exported.served_model_id
        or exported.requested_revision != exported.served_revision
        or exported.requested_execution_mode is not exported.served_execution_mode
    )
    receipt = ManualImportReceipt(
        provider=Provider.CLAUDE_CODE,
        requested_model_id=exported.requested_model_id,
        served_model_id=exported.served_model_id,
        requested_revision=exported.requested_revision,
        served_revision=exported.served_revision,
        requested_execution_mode=exported.requested_execution_mode,
        served_execution_mode=exported.served_execution_mode,
        fallback_used=fallback_used,
        evidence_packet_sha256=exported.evidence_packet_sha256,
        import_payload_sha256=hashlib.sha256(request.payload).hexdigest(),
        imported_at=imported_at,
        response_state=exported.response.state,
    )
    return ManualImportResult(response=exported.response, receipt=receipt)


__all__ = (
    "CLAUDE_CONSUMER_CLI_AUTOMATION_SUPPORTED",
    "DEFAULT_MANUAL_IMPORT_LIMIT_BYTES",
    "MANUAL_IMPORT_RECEIPT_VERSION",
    "MANUAL_NATIVE_EXPORT_VERSION",
    "ApprovedByokEstimatorTransport",
    "ManualImportProtocolError",
    "ManualImportReceipt",
    "ManualImportRequest",
    "ManualImportResult",
    "ManualNativeExport",
    "import_manual_native_export",
)
