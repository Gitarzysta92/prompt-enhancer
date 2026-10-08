"""Truthful r7 release-readiness audit for the documented Claude hook surface.

This module proves the narrow facts the current integration can prove: one
SQLite transaction enumerates every hook/telemetry row the local receivers
admitted, in dense stable order, and yields exact content-free action-candidate
metadata. It also names the two facts the integration cannot prove: that
Claude Code delivered every eligible hook invocation, and that a long-lived
process retained a complete same-read set of redacted invocation/effect
descriptors for native review.

No receipt in this module contains descriptor text. Descriptor batches are
process-only inputs used solely for exact binding validation; restart or batch
loss therefore fails closed without inventing missing authority.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
import hmac
import unicodedata
from typing import Literal

from pydantic import Field, SecretStr, field_validator, model_validator

from ....application.analysis.provider_evidence import (
    requirement_action_family_for_tool_category,
    requirement_action_state_for_event,
)
from ....application.analysis.evidence_contracts import ActionFamily, ActionState
from ....application.analysis.requirement_action_evidence import (
    MAX_REQUIREMENT_ACTION_CANDIDATES,
    requirement_action_candidate_metadata_fingerprint,
)
from ....application.analysis.text_contracts import (
    ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION,
    ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION,
    EphemeralRedactedActionDescriptor,
)
from ....domain import (
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    EventKind,
    Provider,
    StrictModel,
    ToolCategory,
)
from ...redaction.deterministic import DETERMINISTIC_REDACTOR_VERSION
from .contracts import (
    ADAPTER_VERSION,
    CONTRACT_VERSION,
    RECEIVER_VERSION,
    SOURCE_SCHEMA_VERSION,
    UNKNOWN_PROVIDER_VERSION,
    HookEventName,
)
from .ledger import (
    HookLedgerSnapshotError,
    LedgerSessionSnapshot,
    validate_ledger_session_snapshot,
)


CLAUDE_HOOKS_R7_READINESS_VERSION = "claude-code-hooks.r7-readiness.v1"
CLAUDE_HOOKS_EPHEMERAL_DESCRIPTOR_BATCH_VERSION = (
    "claude-code-hooks.ephemeral-action-descriptors.v1"
)
# No production Claude Code version has been objectively certified against a
# complete-delivery hook boundary. A non-empty provider version is therefore
# unsupported for release authority rather than silently treated as tested.
CLAUDE_HOOKS_R7_TESTED_PROVIDER_VERSIONS: tuple[str, ...] = ()


class ClaudeHooksR7Blocker(StrEnum):
    COMPLETE_DELIVERY_UNPROVEN = "complete_delivery_unproven"
    EPHEMERAL_DESCRIPTORS_UNAVAILABLE = "ephemeral_descriptors_unavailable"
    SOURCE_BOUNDARY_INVALID = "source_boundary_invalid"
    RECEIVER_CLOCK_AMBIGUOUS = "receiver_clock_ambiguous"
    UNKNOWN_EVENT_VARIANT = "unknown_event_variant"
    CANDIDATE_OVERFLOW = "candidate_overflow"
    PROVIDER_VERSION_UNKNOWN = "provider_version_unknown"
    PROVIDER_VERSION_UNSUPPORTED = "provider_version_unsupported"
    DESCRIPTOR_SNAPSHOT_DRIFT = "descriptor_snapshot_drift"
    DESCRIPTOR_SET_INCOMPLETE = "descriptor_set_incomplete"
    CANDIDATE_METADATA_DRIFT = "candidate_metadata_drift"
    DESCRIPTOR_CONTENT_INVALID = "descriptor_content_invalid"
    REDACTOR_VERSION_MISMATCH = "redactor_version_mismatch"


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("Claude hook r7 identities must be pseudonyms")
    return value


def _safe_version(value: str) -> str:
    if SAFE_VERSION_PATTERN.fullmatch(value) is None:
        raise ValueError("Claude hook r7 provenance must use safe versions")
    return value


class ClaudeHookActionCandidateMetadata(StrictModel):
    """Persistable-shape metadata; no invocation/effect content is present."""

    source_reference_id: str
    sequence: int = Field(ge=0, le=4_000_000_000)
    event_kind: EventKind
    tool_category: ToolCategory | None = None
    occurred_at: datetime
    duration_ms: int | None = Field(default=None, ge=0)
    family: ActionFamily
    state: ActionState
    candidate_metadata_fingerprint_version: Literal[
        ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    ] = ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
    candidate_metadata_fingerprint: str

    _ids = field_validator(
        "source_reference_id", "candidate_metadata_fingerprint"
    )(_pseudonym)


class ClaudeHooksR7ReadinessReceipt(StrictModel):
    """Content-free, non-authorizing result for the currently composed path."""

    receipt_version: Literal[CLAUDE_HOOKS_R7_READINESS_VERSION] = (
        CLAUDE_HOOKS_R7_READINESS_VERSION
    )
    provider: Literal[Provider.CLAUDE_CODE] = Provider.CLAUDE_CODE
    provider_version: str
    hook_contract_version: Literal[CONTRACT_VERSION] = CONTRACT_VERSION
    receiver_version: Literal[RECEIVER_VERSION] = RECEIVER_VERSION
    adapter_version: Literal[ADAPTER_VERSION] = ADAPTER_VERSION
    source_schema_version: Literal[SOURCE_SCHEMA_VERSION] = SOURCE_SCHEMA_VERSION
    hook_session_id: str
    source_boundary_fingerprint: str
    admitted_event_count: int = Field(ge=0, le=250_000)
    admitted_action_candidate_count: int = Field(ge=0, le=250_000)
    candidate_metadata: tuple[ClaudeHookActionCandidateMetadata, ...] = Field(
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES
    )
    stable_source_boundary: bool
    admitted_event_enumeration_complete: bool
    admitted_action_enumeration_complete: bool
    receiver_clock_order_unambiguous: bool
    complete_provider_delivery_proven: Literal[False] = False
    same_read_candidate_descriptor_binding_complete: Literal[False] = False
    ephemeral_redacted_descriptors_complete: Literal[False] = False
    release_ready: Literal[False] = False
    operability_promoted: Literal[False] = False
    blockers: tuple[ClaudeHooksR7Blocker, ...] = Field(min_length=2)
    local_only: Literal[True] = True
    raw_content_persisted: Literal[False] = False
    descriptor_content_persisted: Literal[False] = False

    _ids = field_validator(
        "hook_session_id", "source_boundary_fingerprint"
    )(_pseudonym)
    _version = field_validator("provider_version")(_safe_version)

    @model_validator(mode="after")
    def exact_partial_ceiling(self) -> "ClaudeHooksR7ReadinessReceipt":
        if len(set(self.blockers)) != len(self.blockers):
            raise ValueError("Claude hook r7 blockers must be unique")
        required = {
            ClaudeHooksR7Blocker.COMPLETE_DELIVERY_UNPROVEN,
            ClaudeHooksR7Blocker.EPHEMERAL_DESCRIPTORS_UNAVAILABLE,
        }
        if not required.issubset(self.blockers):
            raise ValueError("Claude hook r7 receipt must preserve release blockers")
        if self.admitted_action_enumeration_complete:
            if (
                not self.stable_source_boundary
                or not self.admitted_event_enumeration_complete
                or len(self.candidate_metadata)
                != self.admitted_action_candidate_count
            ):
                raise ValueError("complete admitted actions require an exact boundary")
        elif self.candidate_metadata:
            raise ValueError("incomplete admitted actions cannot expose a partial list")
        return self


class ClaudeHookEphemeralDescriptorBatch(StrictModel):
    """Process-only descriptor input; it has no persistence representation."""

    batch_version: Literal[CLAUDE_HOOKS_EPHEMERAL_DESCRIPTOR_BATCH_VERSION] = (
        CLAUDE_HOOKS_EPHEMERAL_DESCRIPTOR_BATCH_VERSION
    )
    hook_session_id: str
    source_boundary_fingerprint: str
    descriptor_algorithm_version: str
    redactor_version: str
    extraction_complete: bool
    descriptors: tuple[EphemeralRedactedActionDescriptor, ...] = Field(
        repr=False,
        max_length=MAX_REQUIREMENT_ACTION_CANDIDATES,
    )
    local_only: Literal[True] = True
    content_persistence_allowed: Literal[False] = False

    _ids = field_validator(
        "hook_session_id", "source_boundary_fingerprint"
    )(_pseudonym)
    _versions = field_validator(
        "descriptor_algorithm_version", "redactor_version"
    )(_safe_version)


class ClaudeHookDescriptorValidation(StrictModel):
    """Content-free validation result; descriptor strings are never copied."""

    complete: bool
    source_boundary_fingerprint: str
    candidate_count: int = Field(ge=0, le=250_000)
    descriptor_count: int = Field(ge=0, le=MAX_REQUIREMENT_ACTION_CANDIDATES)
    blockers: tuple[ClaudeHooksR7Blocker, ...]
    local_only: Literal[True] = True
    descriptor_content_persisted: Literal[False] = False

    _fingerprint = field_validator("source_boundary_fingerprint")(_pseudonym)

    @model_validator(mode="after")
    def exact_result(self) -> "ClaudeHookDescriptorValidation":
        if len(set(self.blockers)) != len(self.blockers):
            raise ValueError("descriptor validation blockers must be unique")
        if self.complete != (not self.blockers):
            raise ValueError("descriptor validation state disagrees with blockers")
        return self


def _candidate_metadata(
    snapshot: LedgerSessionSnapshot,
) -> tuple[ClaudeHookActionCandidateMetadata, ...]:
    candidates: list[ClaudeHookActionCandidateMetadata] = []
    for event in snapshot.events:
        if event.event_kind not in {EventKind.TOOL_START, EventKind.TOOL_END}:
            continue
        sequence = event.sequence * 4
        family = requirement_action_family_for_tool_category(event.tool_category)
        state = requirement_action_state_for_event(event.event_kind, event.success)
        fingerprint = requirement_action_candidate_metadata_fingerprint(
            source_reference_id=event.hook_event_id,
            sequence=sequence,
            event_kind=event.event_kind,
            tool_category=event.tool_category,
            occurred_at=event.received_at,
            duration_ms=event.duration_ms,
            family=family,
            state=state,
        )
        candidates.append(
            ClaudeHookActionCandidateMetadata(
                source_reference_id=event.hook_event_id,
                sequence=sequence,
                event_kind=event.event_kind,
                tool_category=event.tool_category,
                occurred_at=event.received_at,
                duration_ms=event.duration_ms,
                family=family,
                state=state,
                candidate_metadata_fingerprint=fingerprint,
            )
        )
    return tuple(candidates)


def _provider_version(snapshot: LedgerSessionSnapshot) -> str:
    if snapshot.telemetry is None or snapshot.telemetry.provider_version is None:
        return UNKNOWN_PROVIDER_VERSION
    return snapshot.telemetry.provider_version


def build_claude_hooks_r7_readiness(
    snapshot: LedgerSessionSnapshot,
) -> ClaudeHooksR7ReadinessReceipt:
    """Audit one admitted-row snapshot without upgrading provider authority."""

    blockers: list[ClaudeHooksR7Blocker] = [
        ClaudeHooksR7Blocker.COMPLETE_DELIVERY_UNPROVEN,
        ClaudeHooksR7Blocker.EPHEMERAL_DESCRIPTORS_UNAVAILABLE,
    ]
    try:
        clock_order_unambiguous = validate_ledger_session_snapshot(snapshot)
        boundary_valid = True
    except (HookLedgerSnapshotError, TypeError, ValueError):
        clock_order_unambiguous = False
        boundary_valid = False
        blockers.append(ClaudeHooksR7Blocker.SOURCE_BOUNDARY_INVALID)

    events = snapshot.events if boundary_valid else ()
    action_count = sum(
        item.event_kind in {EventKind.TOOL_START, EventKind.TOOL_END}
        for item in snapshot.events
    )
    candidate_metadata: tuple[ClaudeHookActionCandidateMetadata, ...] = ()
    actions_complete = boundary_valid
    if action_count > MAX_REQUIREMENT_ACTION_CANDIDATES:
        actions_complete = False
        blockers.append(ClaudeHooksR7Blocker.CANDIDATE_OVERFLOW)
    elif boundary_valid:
        candidate_metadata = _candidate_metadata(snapshot)

    if boundary_valid and not clock_order_unambiguous:
        blockers.append(ClaudeHooksR7Blocker.RECEIVER_CLOCK_AMBIGUOUS)
    if any(item.hook_event_name is HookEventName.UNKNOWN for item in events):
        blockers.append(ClaudeHooksR7Blocker.UNKNOWN_EVENT_VARIANT)

    provider_version = _provider_version(snapshot)
    if provider_version == UNKNOWN_PROVIDER_VERSION:
        blockers.append(ClaudeHooksR7Blocker.PROVIDER_VERSION_UNKNOWN)
    elif provider_version not in CLAUDE_HOOKS_R7_TESTED_PROVIDER_VERSIONS:
        blockers.append(ClaudeHooksR7Blocker.PROVIDER_VERSION_UNSUPPORTED)

    return ClaudeHooksR7ReadinessReceipt(
        provider_version=provider_version,
        hook_session_id=snapshot.session.hook_session_id,
        source_boundary_fingerprint=snapshot.boundary.boundary_fingerprint,
        admitted_event_count=len(snapshot.events),
        admitted_action_candidate_count=action_count,
        candidate_metadata=candidate_metadata,
        stable_source_boundary=boundary_valid,
        admitted_event_enumeration_complete=boundary_valid,
        admitted_action_enumeration_complete=actions_complete,
        receiver_clock_order_unambiguous=(
            boundary_valid and clock_order_unambiguous
        ),
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _contains_forbidden_display_character(value: SecretStr | None) -> bool:
    if value is None:
        return False
    return any(
        character in "\r\n\t\x00"
        or unicodedata.category(character) in {"Cc", "Cf", "Zl", "Zp"}
        for character in value.get_secret_value()
    )


def validate_ephemeral_descriptor_batch(
    snapshot: LedgerSessionSnapshot,
    batch: ClaudeHookEphemeralDescriptorBatch,
) -> ClaudeHookDescriptorValidation:
    """Validate exact metadata/content binding, returning no descriptor text."""

    blockers: list[ClaudeHooksR7Blocker] = []
    try:
        validate_ledger_session_snapshot(snapshot)
    except (HookLedgerSnapshotError, TypeError, ValueError):
        blockers.append(ClaudeHooksR7Blocker.SOURCE_BOUNDARY_INVALID)

    candidates = _candidate_metadata(snapshot)
    if len(candidates) > MAX_REQUIREMENT_ACTION_CANDIDATES:
        blockers.append(ClaudeHooksR7Blocker.CANDIDATE_OVERFLOW)
        candidates = ()
    if (
        batch.hook_session_id != snapshot.session.hook_session_id
        or not hmac.compare_digest(
            batch.source_boundary_fingerprint,
            snapshot.boundary.boundary_fingerprint,
        )
    ):
        blockers.append(ClaudeHooksR7Blocker.DESCRIPTOR_SNAPSHOT_DRIFT)
    if (
        not batch.extraction_complete
        or batch.descriptor_algorithm_version
        != ACTION_REVIEW_DESCRIPTOR_ALGORITHM_VERSION
        or len(batch.descriptors) != len(candidates)
    ):
        blockers.append(ClaudeHooksR7Blocker.DESCRIPTOR_SET_INCOMPLETE)
    if batch.redactor_version != DETERMINISTIC_REDACTOR_VERSION or any(
        item.redactor_version != batch.redactor_version
        for item in batch.descriptors
    ):
        blockers.append(ClaudeHooksR7Blocker.REDACTOR_VERSION_MISMATCH)

    by_source = {item.source_reference_id: item for item in batch.descriptors}
    if len(by_source) != len(batch.descriptors):
        blockers.append(ClaudeHooksR7Blocker.DESCRIPTOR_SET_INCOMPLETE)
    for candidate in candidates:
        descriptor = by_source.get(candidate.source_reference_id)
        if (
            descriptor is None
            or descriptor.event_kind is not candidate.event_kind
            or descriptor.candidate_metadata_fingerprint_version
            != ACTION_CANDIDATE_METADATA_FINGERPRINT_VERSION
            or descriptor.candidate_metadata_fingerprint is None
            or not hmac.compare_digest(
                descriptor.candidate_metadata_fingerprint,
                candidate.candidate_metadata_fingerprint,
            )
        ):
            blockers.append(ClaudeHooksR7Blocker.CANDIDATE_METADATA_DRIFT)
            continue
        if (
            descriptor.invocation_truncated
            or descriptor.result_or_effect_truncated
            or _contains_forbidden_display_character(descriptor.tool_name)
            or _contains_forbidden_display_character(descriptor.invocation_preview)
            or _contains_forbidden_display_character(
                descriptor.result_or_effect_preview
            )
        ):
            blockers.append(ClaudeHooksR7Blocker.DESCRIPTOR_CONTENT_INVALID)

    unique_blockers = tuple(dict.fromkeys(blockers))
    return ClaudeHookDescriptorValidation(
        complete=not unique_blockers,
        source_boundary_fingerprint=snapshot.boundary.boundary_fingerprint,
        candidate_count=len(candidates),
        descriptor_count=len(batch.descriptors),
        blockers=unique_blockers,
    )


__all__ = (
    "CLAUDE_HOOKS_EPHEMERAL_DESCRIPTOR_BATCH_VERSION",
    "CLAUDE_HOOKS_R7_READINESS_VERSION",
    "CLAUDE_HOOKS_R7_TESTED_PROVIDER_VERSIONS",
    "ClaudeHookActionCandidateMetadata",
    "ClaudeHookDescriptorValidation",
    "ClaudeHookEphemeralDescriptorBatch",
    "ClaudeHooksR7Blocker",
    "ClaudeHooksR7ReadinessReceipt",
    "build_claude_hooks_r7_readiness",
    "validate_ephemeral_descriptor_batch",
)
