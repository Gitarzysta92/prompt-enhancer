"""Untrusted synthetic drafts for a future prospective temporal capture flow.

Nothing in this module reads a provider, verifies repository lineage, or issues
an analysis-input receipt.  The only public constructor is deliberately
synthetic-test-only.  A future documented provider adapter and repository must
independently verify source authority, snapshot boundaries, lineage, and every
commitment before issuing any product-history receipt.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from enum import StrEnum
import hashlib
import hmac
import json
import re
from typing import Any, Final, Literal, Protocol

from pydantic import ConfigDict, Field, field_validator, model_validator

from ...domain import PSEUDONYM_PATTERN, Provider, StrictModel
from ..analysis.text_contracts import (
    MAX_ANALYSIS_MESSAGES,
    MAX_REDACTED_MESSAGE_CHARACTERS,
)
from .contracts import (
    ProjectMetricSelectionRevisionV2,
    TemporalHistoryRootReceipt,
)


PROSPECTIVE_TEMPORAL_CAPTURE_REQUEST_VERSION = (
    "prospective-temporal-capture-request-v1"
)
PROSPECTIVE_TEMPORAL_SOURCE_DRAFT_VERSION = (
    "prospective-temporal-source-draft-v1"
)
TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION = (
    "temporal-source-draft-commitment-v1"
)
TEMPORAL_CAPTURE_CAPABILITY_VERSION = "temporal-capture-capability-v1"

# P1 accepts at most 500 analysis messages with 32,000 redacted characters per
# message.  Prospective history is at least as conservative and also has an
# aggregate UTF-8 budget so a bounded count cannot hide excessive allocation.
MAX_TEMPORAL_SOURCE_ENTRIES = MAX_ANALYSIS_MESSAGES
MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS = MAX_REDACTED_MESSAGE_CHARACTERS
MAX_TEMPORAL_CAPTURE_TOTAL_UTF8_BYTES = 2 * 1024 * 1024

_SAFE_CODE = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$")
# Deliberately exclude both ``:`` and ``@``.  A reference is an opaque local
# token, never a URI scheme, drive-relative path, or email-shaped identifier.
_SAFE_OPAQUE_REFERENCE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,255}$")
_SYNTHETIC_KEY_FACTORY_TOKEN: Final[object] = object()


def _digest(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("value must be a lowercase SHA-256 identifier")
    return value


def _safe_code(value: str) -> str:
    if (
        type(value) is not str
        or _SAFE_CODE.fullmatch(value) is None
        or ".." in value
        or "://" in value
        or "/" in value
        or "\\" in value
    ):
        raise ValueError("value must be a path-free and URI-free content code")
    return value


def _safe_version(value: str) -> str:
    if (
        type(value) is not str
        or _SAFE_VERSION.fullmatch(value) is None
        or ".." in value
        or "://" in value
        or "/" in value
        or "\\" in value
    ):
        raise ValueError("value must be a path-free and URI-free version")
    return value


def _safe_reference(value: str) -> str:
    if (
        type(value) is not str
        or _SAFE_OPAQUE_REFERENCE.fullmatch(value) is None
        or ".." in value
        or "://" in value
        or "/" in value
        or "\\" in value
    ):
        raise ValueError(
            "source reference must be opaque, path-free, URI-free, and email-free"
        )
    return value


def _utc(value: datetime) -> datetime:
    if (
        type(value) is not datetime
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise ValueError("timestamp must be canonical UTC")
    # Replace even a custom zero-offset tzinfo with the immutable stdlib UTC
    # singleton before the value enters a validated snapshot.
    return value.replace(tzinfo=UTC)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=True,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _public_fingerprint(value: Any) -> str:
    return hashlib.sha256(_canonical_json(value)).hexdigest()


def _plain(value: Any) -> Any:
    """Discard trusted Pydantic instances before a public boundary."""

    if isinstance(value, StrictModel):
        return {
            name: _plain(getattr(value, name))
            for name in type(value).model_fields
        }
    if isinstance(value, dict):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, (tuple, list)):
        return tuple(_plain(item) for item in value)
    return value


class RevalidatedCaptureModel(StrictModel):
    """Recursively revalidate frozen-model copies at every public boundary."""

    model_config = ConfigDict(
        extra="forbid",
        frozen=True,
        hide_input_in_errors=True,
        revalidate_instances="always",
    )

    @model_validator(mode="before")
    @classmethod
    def discard_trusted_instances(cls, value: Any) -> Any:
        return _plain(value)

    @classmethod
    def revalidate(cls, value: Any) -> Any:
        return cls.model_validate(_plain(value))


class TemporalCaptureCapabilityState(StrEnum):
    """Public status only; no state grants source or repository authority."""

    UNAVAILABLE_MISSING_AUTHORITATIVE_ITEM_TIMESTAMPS = (
        "unavailable_missing_authoritative_item_timestamps"
    )


class SyntheticEnumerationCompletenessState(StrEnum):
    UNTRUSTED_SYNTHETIC_ENUMERATION = "untrusted_synthetic_enumeration"


class EnumeratedSelectionCoverageState(StrEnum):
    COMPLETE_ENUMERATED_SET = "complete_enumerated_set"
    PARTIAL_ENUMERATED_SET = "partial_enumerated_set"
    NOT_APPLICABLE_EMPTY_ENUMERATED_SET = (
        "not_applicable_empty_enumerated_set"
    )


class TemporalSourceAuthorityState(StrEnum):
    SYNTHETIC_TEST_ONLY = "synthetic_test_only"


class DraftMembershipAuthorityState(StrEnum):
    UNTRUSTED_COMMITMENT_NOT_A_PROOF = "untrusted_commitment_not_a_proof"


class TemporalCaptureCapabilityDescriptor(RevalidatedCaptureModel):
    """Content-free capability status returned by a product adapter port."""

    contract_version: Literal[TEMPORAL_CAPTURE_CAPABILITY_VERSION] = (
        TEMPORAL_CAPTURE_CAPABILITY_VERSION
    )
    provider: Provider
    capability_state: TemporalCaptureCapabilityState
    authoritative_item_timestamps_available: Literal[False] = False
    provider_snapshot_boundary_available: Literal[False] = False
    provider_cursor_boundary_available: Literal[False] = False
    trusted_adapter_issuance_implemented: Literal[False] = False
    trusted_repository_issuance_implemented: Literal[False] = False
    prohibited_timestamp_substitutions: tuple[str, ...] = (
        "capture_timestamp",
        "list_timestamp",
        "read_clock",
        "session_created_at",
        "session_timestamp",
        "session_updated_at",
        "turn_order",
        "turn_timestamp",
    )
    product_capture_allowed: Literal[False] = False
    product_authority: Literal[False] = False
    local_only: Literal[True] = True
    remote_processing_allowed: Literal[False] = False
    fail_closed: Literal[True] = True

    @field_validator("prohibited_timestamp_substitutions")
    @classmethod
    def exact_prohibitions(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        expected = (
            "capture_timestamp",
            "list_timestamp",
            "read_clock",
            "session_created_at",
            "session_timestamp",
            "session_updated_at",
            "turn_order",
            "turn_timestamp",
        )
        if values != expected:
            raise ValueError("timestamp substitution prohibitions are immutable")
        return values


class TemporalCaptureCapabilityPort(Protocol):
    """The only production-facing port in this source-capture foundation."""

    def temporal_capture_capability(self) -> TemporalCaptureCapabilityDescriptor: ...


class ProspectiveTemporalCaptureRequestV1(RevalidatedCaptureModel):
    """Synthetic request bound to exact, still-unverified lineage receipts."""

    contract_version: Literal[PROSPECTIVE_TEMPORAL_CAPTURE_REQUEST_VERSION] = (
        PROSPECTIVE_TEMPORAL_CAPTURE_REQUEST_VERSION
    )
    history_root_receipt: TemporalHistoryRootReceipt
    history_root_fingerprint: str
    selection_revision: ProjectMetricSelectionRevisionV2
    selection_revision_fingerprint: str
    selection_scope_fingerprint: str
    session_id: str
    provider: Literal[Provider.SYNTHETIC] = Provider.SYNTHETIC
    requested_at: datetime
    allowlisted_kind_codes: tuple[str, ...] = Field(min_length=1, max_length=32)
    privacy_policy_version: str
    retention_policy_version: str
    fingerprint_key_version: str
    synthetic_test_only: Literal[True] = True
    product_authority: Literal[False] = False
    repository_lineage_verified: Literal[False] = False
    trusted_adapter_issuance_required: Literal[True] = True
    trusted_repository_issuance_required: Literal[True] = True
    untrusted: Literal[True] = True
    sealed: Literal[False] = False
    prospective_capture_only: Literal[True] = True
    legacy_backfill_allowed: Literal[False] = False
    local_only: Literal[True] = True
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _digests = field_validator(
        "history_root_fingerprint",
        "selection_revision_fingerprint",
        "selection_scope_fingerprint",
        "session_id",
    )(_digest)
    _requested = field_validator("requested_at")(_utc)
    _versions = field_validator(
        "privacy_policy_version",
        "retention_policy_version",
        "fingerprint_key_version",
    )(_safe_version)

    @field_validator("allowlisted_kind_codes")
    @classmethod
    def canonical_allowlist(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        cleaned = tuple(_safe_code(value) for value in values)
        if cleaned != tuple(sorted(set(cleaned))):
            raise ValueError("allowlisted source kinds must be unique and sorted")
        return cleaned

    @model_validator(mode="after")
    def exact_receipt_bindings(self) -> "ProspectiveTemporalCaptureRequestV1":
        root = self.history_root_receipt
        selection = self.selection_revision
        if self.history_root_fingerprint != root.fingerprint:
            raise ValueError("history-root fingerprint must bind the exact receipt")
        if self.selection_revision_fingerprint != selection.fingerprint:
            raise ValueError("selection fingerprint must bind the exact revision")
        if self.selection_scope_fingerprint != selection.metric_set_fingerprint:
            raise ValueError("selection scope must bind keys, pack, catalog, and authority")
        if selection.root_receipt_id != root.root_receipt_id:
            raise ValueError("selection must name the exact history-root receipt")
        if selection.root_receipt_fingerprint != root.fingerprint:
            raise ValueError("selection must name the exact history-root fingerprint")
        if selection.project_id != root.project_id:
            raise ValueError("history root and selection must name one project")
        if selection.effective_at < root.issued_at:
            raise ValueError("selection cannot become effective before its history root")
        if selection.recorded_at < root.issued_at:
            raise ValueError("selection cannot be recorded before its history root")
        if self.requested_at < root.issued_at:
            raise ValueError("capture request cannot predate the prospective root")
        if self.requested_at < selection.recorded_at:
            raise ValueError("capture request cannot predate the recorded selection")
        if self.requested_at < selection.effective_at:
            raise ValueError("capture request cannot predate selection effectiveness")
        if self.session_id in {
            root.root_receipt_id,
            root.project_id,
            selection.selection_revision_id,
            selection.source_authority_id,
        }:
            raise ValueError("session identity must be role-separated from lineage ids")
        return self

    @classmethod
    def for_synthetic_tests(
        cls,
        *,
        history_root_receipt: TemporalHistoryRootReceipt,
        selection_revision: ProjectMetricSelectionRevisionV2,
        session_id: str,
        requested_at: datetime,
        allowlisted_kind_codes: tuple[str, ...],
        privacy_policy_version: str,
        retention_policy_version: str,
        fingerprint_key_version: str,
    ) -> "ProspectiveTemporalCaptureRequestV1":
        """Build an untrusted draft; this is not repository verification."""

        root = TemporalHistoryRootReceipt.revalidate_for_persistence(
            history_root_receipt
        )
        selection = ProjectMetricSelectionRevisionV2.revalidate_for_persistence(
            selection_revision
        )
        return cls(
            history_root_receipt=root,
            history_root_fingerprint=root.fingerprint,
            selection_revision=selection,
            selection_revision_fingerprint=selection.fingerprint,
            selection_scope_fingerprint=selection.metric_set_fingerprint,
            session_id=session_id,
            requested_at=requested_at,
            allowlisted_kind_codes=allowlisted_kind_codes,
            privacy_policy_version=privacy_policy_version,
            retention_policy_version=retention_policy_version,
            fingerprint_key_version=fingerprint_key_version,
        )

    @property
    def fingerprint(self) -> str:
        return _public_fingerprint(self.model_dump(mode="json"))


@dataclass(frozen=True, slots=True, repr=False)
class _TemporalSourceEntry:
    """Transient secret-bearing value used only inside the synthetic builder."""

    source_entry_reference: str = field(repr=False)
    occurred_at: datetime
    source_order: int
    kind_code: str
    normalized_redacted_content: str = field(repr=False)

    def __repr__(self) -> str:
        return "_TemporalSourceEntry(<private synthetic entry>)"

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError("private synthetic temporal entries cannot be pickled")


def synthetic_temporal_source_entry_for_tests(
    *,
    source_entry_reference: str,
    occurred_at: datetime,
    source_order: int,
    kind_code: str,
    normalized_redacted_content: str,
) -> _TemporalSourceEntry:
    """Create a bounded private entry for synthetic contract tests only."""

    reference = _safe_reference(source_entry_reference)
    timestamp = _utc(occurred_at)
    if type(source_order) is not int or not 0 <= source_order <= 2_147_483_647:
        raise ValueError("source order must be a bounded non-negative integer")
    kind = _safe_code(kind_code)
    if (
        type(normalized_redacted_content) is not str
        or not normalized_redacted_content
        or len(normalized_redacted_content)
        > MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS
        or "\x00" in normalized_redacted_content
    ):
        raise ValueError("redacted content must be non-empty and bounded")
    return _TemporalSourceEntry(
        source_entry_reference=reference,
        occurred_at=timestamp,
        source_order=source_order,
        kind_code=kind,
        normalized_redacted_content=normalized_redacted_content,
    )


@dataclass(frozen=True, slots=True, repr=False)
class _LocalHmacKeyMaterial:
    secret: bytes = field(repr=False)
    key_version: str

    def __repr__(self) -> str:
        return "_LocalHmacKeyMaterial(<private>)"


class SyntheticLocalHmacKeyHandle:
    """Concrete local HMAC handle; it cannot delegate content to a callback."""

    __slots__ = ("__material",)

    def __init__(self, material: _LocalHmacKeyMaterial, token: object) -> None:
        if token is not _SYNTHETIC_KEY_FACTORY_TOKEN:
            raise TypeError("use the synthetic-test key-handle factory")
        self.__material = material

    def __init_subclass__(cls, **kwargs: Any) -> None:
        raise TypeError("synthetic local HMAC handles cannot be subclassed")

    @classmethod
    def from_secret_for_tests(
        cls, *, secret: bytes, key_version: str
    ) -> "SyntheticLocalHmacKeyHandle":
        if type(secret) is not bytes or not 32 <= len(secret) <= 128:
            raise ValueError("synthetic HMAC key must contain 32 to 128 local bytes")
        version = _safe_version(key_version)
        return cls(
            _LocalHmacKeyMaterial(secret=bytes(secret), key_version=version),
            _SYNTHETIC_KEY_FACTORY_TOKEN,
        )

    @property
    def key_version(self) -> str:
        return self.__material.key_version

    def _digest(self, *, domain: str, version: str, payload: Any) -> str:
        """Return a framed local digest and suppress secret-bearing failures."""

        try:
            framed = _canonical_json(
                {
                    "domain": _safe_code(domain),
                    "payload": payload,
                    "version": _safe_version(version),
                }
            )
            return hmac.new(
                self.__material.secret,
                framed,
                hashlib.sha256,
            ).hexdigest()
        except Exception:
            # Leave the handler before raising so Python does not retain a
            # secret-bearing provider/crypto exception in ``__context__``.
            pass
        raise RuntimeError("local synthetic commitment failed") from None

    def __repr__(self) -> str:
        return (
            "SyntheticLocalHmacKeyHandle(<private local key>, "
            f"key_version={self.key_version!r})"
        )

    def __reduce__(self) -> Any:
        raise TypeError("synthetic local HMAC handles cannot be pickled")


class ProspectiveTemporalSourceDraftV1(RevalidatedCaptureModel):
    """Content-free, untrusted commitments over one synthetic enumeration."""

    contract_version: Literal[PROSPECTIVE_TEMPORAL_SOURCE_DRAFT_VERSION] = (
        PROSPECTIVE_TEMPORAL_SOURCE_DRAFT_VERSION
    )
    capture_request: ProspectiveTemporalCaptureRequestV1
    capture_request_fingerprint: str
    enumerated_source_entry_count: int = Field(
        strict=True, ge=0, le=MAX_TEMPORAL_SOURCE_ENTRIES
    )
    bounded_eligible_entry_count: int = Field(
        strict=True, ge=0, le=MAX_TEMPORAL_SOURCE_ENTRIES
    )
    selected_entry_count: int = Field(
        strict=True, ge=0, le=MAX_TEMPORAL_SOURCE_ENTRIES
    )
    enumeration_completeness_state: Literal[
        SyntheticEnumerationCompletenessState.UNTRUSTED_SYNTHETIC_ENUMERATION
    ] = SyntheticEnumerationCompletenessState.UNTRUSTED_SYNTHETIC_ENUMERATION
    authoritative_enumeration_complete: Literal[False] = False
    enumerated_selection_coverage: EnumeratedSelectionCoverageState
    selected_window_started_at: datetime | None = None
    selected_window_ended_at: datetime | None = None
    selected_window_draft_commitment: str
    eligible_window_draft_commitment: str
    selected_membership_draft_commitment: str
    analysis_window_draft_commitment: str
    commitment_version: Literal[TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION] = (
        TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION
    )
    commitment_key_version: str
    membership_authority_state: Literal[
        DraftMembershipAuthorityState.UNTRUSTED_COMMITMENT_NOT_A_PROOF
    ] = DraftMembershipAuthorityState.UNTRUSTED_COMMITMENT_NOT_A_PROOF
    captured_at: datetime
    provider_version: str
    provider_adapter_version: str
    provider_schema_version: str
    source_schema_version: str
    content_schema_version: str
    redactor_version: str
    redactor_sha256: str
    source_authority_state: Literal[
        TemporalSourceAuthorityState.SYNTHETIC_TEST_ONLY
    ] = TemporalSourceAuthorityState.SYNTHETIC_TEST_ONLY
    synthetic_test_only: Literal[True] = True
    provider_snapshot_boundary_present: Literal[False] = False
    provider_cursor_boundary_present: Literal[False] = False
    authoritative_item_timestamp_claim: Literal[False] = False
    product_authority: Literal[False] = False
    untrusted: Literal[True] = True
    repository_verified: Literal[False] = False
    repository_issued: Literal[False] = False
    repository_issuance_required: Literal[True] = True
    sealed: Literal[False] = False
    local_only: Literal[True] = True
    prospective_capture_only: Literal[True] = True
    legacy_backfill_allowed: Literal[False] = False
    contains_local_content: Literal[False] = False
    remote_processing_allowed: Literal[False] = False
    private_export_allowed: Literal[False] = False
    team_share_allowed: Literal[False] = False
    comparison_allowed: Literal[False] = False
    snapshot_materialization_allowed: Literal[False] = False
    activation_allowed: Literal[False] = False

    _digests = field_validator(
        "capture_request_fingerprint",
        "selected_window_draft_commitment",
        "eligible_window_draft_commitment",
        "selected_membership_draft_commitment",
        "analysis_window_draft_commitment",
        "redactor_sha256",
    )(_digest)
    _versions = field_validator(
        "commitment_key_version",
        "provider_version",
        "provider_adapter_version",
        "provider_schema_version",
        "source_schema_version",
        "content_schema_version",
        "redactor_version",
    )(_safe_version)
    _captured = field_validator("captured_at")(_utc)

    @field_validator("selected_window_started_at", "selected_window_ended_at")
    @classmethod
    def optional_utc(cls, value: datetime | None) -> datetime | None:
        return None if value is None else _utc(value)

    @model_validator(mode="after")
    def exact_draft_shape(self) -> "ProspectiveTemporalSourceDraftV1":
        request = self.capture_request
        if self.capture_request_fingerprint != request.fingerprint:
            raise ValueError("capture request fingerprint must bind the exact request")
        if self.commitment_key_version != request.fingerprint_key_version:
            raise ValueError("draft commitment key must match the request")
        if self.captured_at < request.requested_at:
            raise ValueError("capture completion cannot predate its request")
        if self.bounded_eligible_entry_count > self.enumerated_source_entry_count:
            raise ValueError("eligible count cannot exceed enumerated count")
        if self.selected_entry_count > self.bounded_eligible_entry_count:
            raise ValueError("selected count cannot exceed eligible count")

        if self.bounded_eligible_entry_count == 0:
            expected_coverage = (
                EnumeratedSelectionCoverageState.NOT_APPLICABLE_EMPTY_ENUMERATED_SET
            )
        elif self.selected_entry_count == self.bounded_eligible_entry_count:
            expected_coverage = (
                EnumeratedSelectionCoverageState.COMPLETE_ENUMERATED_SET
            )
        else:
            expected_coverage = (
                EnumeratedSelectionCoverageState.PARTIAL_ENUMERATED_SET
            )
        if self.enumerated_selection_coverage is not expected_coverage:
            raise ValueError("selection coverage must be derived from exact counts")

        has_window = self.selected_entry_count > 0
        if has_window != (self.selected_window_started_at is not None):
            raise ValueError("selected window start must match selected count")
        if has_window != (self.selected_window_ended_at is not None):
            raise ValueError("selected window end must match selected count")
        if has_window:
            assert self.selected_window_started_at is not None
            assert self.selected_window_ended_at is not None
            if self.selected_window_started_at > self.selected_window_ended_at:
                raise ValueError("selected window timestamps must be ordered")
            if self.selected_window_started_at < request.history_root_receipt.history_floor_at:
                raise ValueError("selected window cannot predate the prospective root")
            if self.selected_window_ended_at > request.requested_at:
                raise ValueError("selected window cannot follow the request boundary")

        commitments = {
            self.selected_window_draft_commitment,
            self.eligible_window_draft_commitment,
            self.selected_membership_draft_commitment,
            self.analysis_window_draft_commitment,
        }
        if len(commitments) != 4:
            raise ValueError("draft commitment roles must remain separated")
        return self

    @property
    def fingerprint(self) -> str:
        return _public_fingerprint(self.model_dump(mode="json"))


class SyntheticTemporalSourceDraftBuilder:
    """Build only an untrusted synthetic draft with a concrete local HMAC."""

    __slots__ = ("__key_handle",)

    def __init__(self, key_handle: SyntheticLocalHmacKeyHandle) -> None:
        if type(key_handle) is not SyntheticLocalHmacKeyHandle:
            raise TypeError("builder requires the concrete synthetic local HMAC handle")
        self.__key_handle = key_handle

    def __repr__(self) -> str:
        return "SyntheticTemporalSourceDraftBuilder(<private local key handle>)"

    @staticmethod
    def _entry_key(entry: _TemporalSourceEntry) -> tuple[datetime, int, str]:
        return (
            entry.occurred_at,
            entry.source_order,
            entry.source_entry_reference,
        )

    @staticmethod
    def _validate_entries(
        entries: Sequence[_TemporalSourceEntry], *, role: str
    ) -> tuple[_TemporalSourceEntry, ...]:
        # Exact tuples provide an immutable enumeration and let us enforce the
        # count bound before copying, sorting, or hashing any content.  Frozen
        # dataclasses can still be modified with ``object.__setattr__``; never
        # let a caller-owned instance cross this boundary.  Read each primitive
        # once, revalidate it, and retain only a newly constructed snapshot.
        if type(entries) is not tuple:
            raise TypeError(f"{role} entries must be an immutable exact tuple")
        if len(entries) > MAX_TEMPORAL_SOURCE_ENTRIES:
            raise ValueError(f"{role} entry count exceeds the local bound")

        total_bytes = 0
        previous_key: tuple[datetime, int, str] | None = None
        references: set[str] = set()
        snapshots: list[_TemporalSourceEntry] = []
        for entry in entries:
            if type(entry) is not _TemporalSourceEntry:
                raise TypeError(f"{role} entries must use the private synthetic type")

            # Tuple construction captures one snapshot of every immutable
            # primitive even if hostile test code mutates the original object
            # concurrently.  The captured combination is then fully validated.
            raw_snapshot = (
                entry.source_entry_reference,
                entry.occurred_at,
                entry.source_order,
                entry.kind_code,
                entry.normalized_redacted_content,
            )
            snapshot = synthetic_temporal_source_entry_for_tests(
                source_entry_reference=raw_snapshot[0],
                occurred_at=raw_snapshot[1],
                source_order=raw_snapshot[2],
                kind_code=raw_snapshot[3],
                normalized_redacted_content=raw_snapshot[4],
            )
            key = SyntheticTemporalSourceDraftBuilder._entry_key(snapshot)
            if previous_key is not None and key <= previous_key:
                raise ValueError(
                    f"{role} entries must use strict canonical timestamp/order/identity order"
                )
            if snapshot.source_entry_reference in references:
                raise ValueError(f"{role} entries cannot duplicate a stable identity")
            references.add(snapshot.source_entry_reference)
            previous_key = key
            total_bytes += len(snapshot.source_entry_reference.encode("utf-8"))
            total_bytes += len(snapshot.kind_code.encode("utf-8"))
            total_bytes += len(
                snapshot.normalized_redacted_content.encode("utf-8")
            )
            if total_bytes > MAX_TEMPORAL_CAPTURE_TOTAL_UTF8_BYTES:
                raise ValueError(f"{role} entries exceed the aggregate local byte bound")
            snapshots.append(snapshot)
        return tuple(snapshots)

    def _entry_leaf(self, *, role: str, entry: _TemporalSourceEntry) -> str:
        return self.__key_handle._digest(
            domain=f"temporal.{role}.entry",
            version=TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION,
            payload={
                "kind_code": entry.kind_code,
                "normalized_redacted_content": entry.normalized_redacted_content,
                "occurred_at": entry.occurred_at.isoformat(),
                "source_entry_reference": entry.source_entry_reference,
                "source_order": entry.source_order,
            },
        )

    def _window_commitment(
        self,
        *,
        role: str,
        request_fingerprint: str,
        entries: tuple[_TemporalSourceEntry, ...],
    ) -> str:
        leaves = tuple(self._entry_leaf(role=role, entry=entry) for entry in entries)
        return self.__key_handle._digest(
            domain=f"temporal.{role}.window",
            version=TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION,
            payload={
                "entry_count": len(entries),
                "keyed_entry_leaves": leaves,
                "request_fingerprint": request_fingerprint,
            },
        )

    def build(
        self,
        *,
        request: ProspectiveTemporalCaptureRequestV1,
        observed_entries: Sequence[_TemporalSourceEntry],
        selected_entries: Sequence[_TemporalSourceEntry],
        captured_at: datetime,
        provider_version: str,
        provider_adapter_version: str,
        provider_schema_version: str,
        source_schema_version: str,
        content_schema_version: str,
        redactor_version: str,
        redactor_sha256: str,
    ) -> ProspectiveTemporalSourceDraftV1:
        """Build a draft; no result from this method is product evidence."""

        bound_request = ProspectiveTemporalCaptureRequestV1.revalidate(request)
        if self.__key_handle.key_version != bound_request.fingerprint_key_version:
            raise ValueError("local key version must match the capture request")
        completion_time = _utc(captured_at)
        if completion_time < bound_request.requested_at:
            raise ValueError("capture completion cannot predate its request")

        observed = self._validate_entries(observed_entries, role="observed")
        selected = self._validate_entries(selected_entries, role="selected")

        floor = bound_request.history_root_receipt.history_floor_at
        ceiling = bound_request.requested_at
        allowlist = frozenset(bound_request.allowlisted_kind_codes)
        eligible = tuple(
            entry
            for entry in observed
            if floor <= entry.occurred_at <= ceiling
            and entry.kind_code in allowlist
        )
        eligible_by_reference = {
            entry.source_entry_reference: entry for entry in eligible
        }
        for entry in selected:
            expected = eligible_by_reference.get(entry.source_entry_reference)
            if expected is None or expected != entry:
                raise ValueError(
                    "selected entries must exactly match the bounded enumerated source"
                )

        request_fingerprint = bound_request.fingerprint
        selected_commitment = self._window_commitment(
            role="selected",
            request_fingerprint=request_fingerprint,
            entries=selected,
        )
        eligible_commitment = self._window_commitment(
            role="eligible",
            request_fingerprint=request_fingerprint,
            entries=eligible,
        )
        membership_commitment = self.__key_handle._digest(
            domain="temporal.selected-membership-draft",
            version=TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION,
            payload={
                "eligible_entry_count": len(eligible),
                "eligible_window_draft_commitment": eligible_commitment,
                "request_fingerprint": request_fingerprint,
                "selected_entry_count": len(selected),
                "selected_window_draft_commitment": selected_commitment,
            },
        )
        analysis_commitment = self.__key_handle._digest(
            domain="temporal.analysis-window-draft",
            version=TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION,
            payload={
                "membership_draft_commitment": membership_commitment,
                "request_fingerprint": request_fingerprint,
                "selection_scope_fingerprint": (
                    bound_request.selection_scope_fingerprint
                ),
            },
        )

        if not eligible:
            coverage = (
                EnumeratedSelectionCoverageState.NOT_APPLICABLE_EMPTY_ENUMERATED_SET
            )
        elif len(selected) == len(eligible):
            coverage = EnumeratedSelectionCoverageState.COMPLETE_ENUMERATED_SET
        else:
            coverage = EnumeratedSelectionCoverageState.PARTIAL_ENUMERATED_SET

        return ProspectiveTemporalSourceDraftV1(
            capture_request=bound_request,
            capture_request_fingerprint=request_fingerprint,
            enumerated_source_entry_count=len(observed),
            bounded_eligible_entry_count=len(eligible),
            selected_entry_count=len(selected),
            enumerated_selection_coverage=coverage,
            selected_window_started_at=(selected[0].occurred_at if selected else None),
            selected_window_ended_at=(selected[-1].occurred_at if selected else None),
            selected_window_draft_commitment=selected_commitment,
            eligible_window_draft_commitment=eligible_commitment,
            selected_membership_draft_commitment=membership_commitment,
            analysis_window_draft_commitment=analysis_commitment,
            commitment_key_version=self.__key_handle.key_version,
            captured_at=completion_time,
            provider_version=provider_version,
            provider_adapter_version=provider_adapter_version,
            provider_schema_version=provider_schema_version,
            source_schema_version=source_schema_version,
            content_schema_version=content_schema_version,
            redactor_version=redactor_version,
            redactor_sha256=redactor_sha256,
        )


__all__ = [
    "DraftMembershipAuthorityState",
    "EnumeratedSelectionCoverageState",
    "MAX_TEMPORAL_CAPTURE_TOTAL_UTF8_BYTES",
    "MAX_TEMPORAL_SOURCE_CONTENT_CHARACTERS",
    "MAX_TEMPORAL_SOURCE_ENTRIES",
    "PROSPECTIVE_TEMPORAL_CAPTURE_REQUEST_VERSION",
    "PROSPECTIVE_TEMPORAL_SOURCE_DRAFT_VERSION",
    "ProspectiveTemporalCaptureRequestV1",
    "ProspectiveTemporalSourceDraftV1",
    "SyntheticEnumerationCompletenessState",
    "SyntheticLocalHmacKeyHandle",
    "SyntheticTemporalSourceDraftBuilder",
    "TEMPORAL_CAPTURE_CAPABILITY_VERSION",
    "TEMPORAL_SOURCE_DRAFT_COMMITMENT_VERSION",
    "TemporalCaptureCapabilityDescriptor",
    "TemporalCaptureCapabilityPort",
    "TemporalCaptureCapabilityState",
    "TemporalSourceAuthorityState",
    "synthetic_temporal_source_entry_for_tests",
]
