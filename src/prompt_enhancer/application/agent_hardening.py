"""Content-free release-hardening status for the authored Agent workspace.

The Agent catalog contains sensitive owner-authored names, paths, messages,
artifacts, and attachments.  This module deliberately exposes none of them.
It reports only bounded counts, closed states, and schema/integrity facts so an
owner can verify restart readiness without creating a diagnostic data leak.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Literal, Protocol

from pydantic import Field, model_validator

from ..domain import StrictModel
from .agent_catalog import AgentCatalogError


AGENT_HARDENING_CONTRACT_VERSION = "agent-hardening.v1"
AGENT_NATIVE_ACCEPTANCE_START_CONTRACT_VERSION = (
    "agent-native-acceptance-start.v1"
)
AGENT_NATIVE_ACCEPTANCE_CONFIRMATION = "begin_guarded_agent_native_acceptance"
MAX_OBSERVED_INTEGRITY_VIOLATIONS = 100


class BeginAgentNativeAcceptance(StrictModel):
    """Exact native-owner intent required to arm the in-window smoke guide."""

    confirmation: Literal["begin_guarded_agent_native_acceptance"] = (
        AGENT_NATIVE_ACCEPTANCE_CONFIRMATION
    )


class AgentNativeAcceptanceStartReceipt(StrictModel):
    """Content-free proof that only the owner gate was opened.

    The endpoint deliberately performs no model, process, workspace, chat, or
    persistence operation.  The browser observes later actions through the
    existing strict runtime and Agent contracts and keeps that evidence only in
    the current page's memory.
    """

    contract_version: Literal["agent-native-acceptance-start.v1"] = (
        AGENT_NATIVE_ACCEPTANCE_START_CONTRACT_VERSION
    )
    owner_presence_confirmed: Literal[True] = True
    model_execution_started: Literal[False] = False
    process_spawn_requested: Literal[False] = False
    workspace_access_requested: Literal[False] = False
    content_persisted: Literal[False] = False
    expires_on_reload: Literal[True] = True


class AgentHardeningState(StrEnum):
    READY = "ready"
    DEGRADED = "degraded"
    UNAVAILABLE = "unavailable"


class AgentRecoveryState(StrEnum):
    CLEAN = "clean"
    ATTENTION_REQUIRED = "attention_required"
    UNKNOWN = "unknown"


class AgentHardeningReason(StrEnum):
    CATALOG_PATH_INVALID = "catalog_path_invalid"
    CATALOG_PATH_UNSAFE = "catalog_path_unsafe"
    CATALOG_SCHEMA_NEWER = "catalog_schema_newer"
    CATALOG_MIGRATION_INVALID = "catalog_migration_invalid"
    CATALOG_STORAGE_UNAVAILABLE = "catalog_storage_unavailable"
    CATALOG_QUICK_CHECK_FAILED = "catalog_quick_check_failed"
    CATALOG_FOREIGN_KEY_VIOLATION = "catalog_foreign_key_violation"
    CATALOG_PROJECTION_MISMATCH = "catalog_projection_mismatch"
    CATALOG_DIAGNOSTIC_UNAVAILABLE = "catalog_diagnostic_unavailable"


class AgentRecoveryAction(StrEnum):
    INSPECT_LOCAL_CATALOG = "inspect_local_catalog"
    RESUME_INTERRUPTED_READ_ONLY = "resume_interrupted_read_only"
    REVALIDATE_RECOVERED_AUTHORITY = "revalidate_recovered_authority"
    RESTART_AFTER_CLEANUP_UNCERTAIN = "restart_after_cleanup_uncertain"
    RETRY_AFTER_HISTORY_WRITE_FAILURE = "retry_after_history_write_failure"
    VERIFY_LIVE_STATE = "verify_live_state"


class AgentPersistenceCounts(StrictModel):
    """Exact aggregate counts from fixed Agent catalog tables."""

    projects: int = Field(ge=0)
    archived_projects: int = Field(ge=0)
    sessions: int = Field(ge=0)
    archived_sessions: int = Field(ge=0)
    metadata_only_sessions: int = Field(ge=0)
    retained_sessions: int = Field(ge=0)
    history_events: int = Field(ge=0)
    interrupted_retained_sessions: int = Field(ge=0)
    artifacts: int = Field(ge=0)
    artifact_versions: int = Field(ge=0)
    staged_attachments: int = Field(ge=0)
    attached_attachments: int = Field(ge=0)

    @model_validator(mode="after")
    def validate_subtotals(self) -> "AgentPersistenceCounts":
        if self.archived_projects > self.projects:
            raise ValueError("archived project count exceeds projects")
        if self.archived_sessions > self.sessions:
            raise ValueError("archived session count exceeds sessions")
        if self.metadata_only_sessions + self.retained_sessions != self.sessions:
            raise ValueError("retention counts do not cover sessions")
        if self.interrupted_retained_sessions > self.retained_sessions:
            raise ValueError("interrupted count exceeds retained sessions")
        return self


class AgentLiveHardeningFacts(StrictModel):
    """Content-free state observed from the current in-memory Agent service."""

    sessions: int = Field(ge=0)
    running_turns: int = Field(ge=0)
    closing_sessions: int = Field(ge=0)
    pending_approvals: int = Field(ge=0)
    cleanup_unconfirmed: int = Field(ge=0)
    command_cleanup_quarantined: bool
    recovered_read_only: int = Field(ge=0)
    history_write_failures: int = Field(ge=0)
    shutting_down: bool

    @model_validator(mode="after")
    def validate_subtotals(self) -> "AgentLiveHardeningFacts":
        for value in (
            self.running_turns,
            self.closing_sessions,
            self.pending_approvals,
            self.cleanup_unconfirmed,
            self.recovered_read_only,
            self.history_write_failures,
        ):
            if value > self.sessions:
                raise ValueError("live Agent subcount exceeds sessions")
        return self


class AgentCatalogProbeResult(StrictModel):
    """Internal content-free result returned by a catalog compatibility probe."""

    schema_version: int = Field(ge=1)
    quick_check_passed: bool
    foreign_key_violations_observed: int = Field(
        ge=0, le=MAX_OBSERVED_INTEGRITY_VIOLATIONS
    )
    foreign_key_scan_truncated: bool
    projection_violations: int = Field(ge=0)
    counts: AgentPersistenceCounts


class AgentCatalogHardeningStatus(StrictModel):
    state: AgentHardeningState
    reason_code: AgentHardeningReason | None = None
    schema_version: int | None = Field(default=None, ge=1)
    quick_check_passed: bool | None = None
    foreign_key_violations_observed: int | None = Field(
        default=None, ge=0, le=MAX_OBSERVED_INTEGRITY_VIOLATIONS
    )
    foreign_key_scan_truncated: bool = False
    projection_violations: int | None = Field(default=None, ge=0)
    counts: AgentPersistenceCounts | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "AgentCatalogHardeningStatus":
        observed = (
            self.schema_version,
            self.quick_check_passed,
            self.foreign_key_violations_observed,
            self.projection_violations,
            self.counts,
        )
        if self.state is AgentHardeningState.UNAVAILABLE:
            if self.reason_code is None or any(value is not None for value in observed):
                raise ValueError("unavailable catalog status must not claim observations")
            if self.foreign_key_scan_truncated:
                raise ValueError("unavailable catalog status cannot claim a scan")
        else:
            if any(value is None for value in observed):
                raise ValueError("observed catalog status is incomplete")
            expected_reason: AgentHardeningReason | None
            if self.quick_check_passed is not True:
                expected_reason = AgentHardeningReason.CATALOG_QUICK_CHECK_FAILED
            elif self.foreign_key_violations_observed:
                expected_reason = AgentHardeningReason.CATALOG_FOREIGN_KEY_VIOLATION
            elif self.projection_violations:
                expected_reason = AgentHardeningReason.CATALOG_PROJECTION_MISMATCH
            else:
                expected_reason = None
            expected_state = (
                AgentHardeningState.READY
                if expected_reason is None
                else AgentHardeningState.DEGRADED
            )
            if self.state is not expected_state or self.reason_code is not expected_reason:
                raise ValueError("catalog integrity state is incoherent")
        return self


class AgentLiveHardeningStatus(StrictModel):
    state: Literal["ready", "unavailable"]
    reason_code: Literal["live_state_unavailable"] | None = None
    counts: AgentLiveHardeningFacts | None = None

    @model_validator(mode="after")
    def validate_state(self) -> "AgentLiveHardeningStatus":
        if self.state == "ready":
            if self.reason_code is not None or self.counts is None:
                raise ValueError("ready live status is incomplete")
        elif self.reason_code != "live_state_unavailable" or self.counts is not None:
            raise ValueError("unavailable live status is inconsistent")
        return self


class AgentHardeningSnapshot(StrictModel):
    """Owner-invoked diagnostic snapshot with no sensitive Agent content."""

    contract_version: Literal["agent-hardening.v1"] = AGENT_HARDENING_CONTRACT_VERSION
    generated_on_demand: Literal[True] = True
    contains_content: Literal[False] = False
    recovery_state: AgentRecoveryState
    recovery_actions: tuple[AgentRecoveryAction, ...] = Field(default=(), max_length=6)
    catalog: AgentCatalogHardeningStatus
    live: AgentLiveHardeningStatus

    @model_validator(mode="after")
    def validate_recovery(self) -> "AgentHardeningSnapshot":
        if len(set(self.recovery_actions)) != len(self.recovery_actions):
            raise ValueError("recovery actions must be unique")
        expected_actions: list[AgentRecoveryAction] = []
        if self.catalog.state is AgentHardeningState.DEGRADED:
            expected_actions.append(AgentRecoveryAction.INSPECT_LOCAL_CATALOG)
        if (
            self.catalog.counts is not None
            and self.catalog.counts.interrupted_retained_sessions
        ):
            expected_actions.append(AgentRecoveryAction.RESUME_INTERRUPTED_READ_ONLY)
        if self.live.counts is None:
            expected_actions.append(AgentRecoveryAction.VERIFY_LIVE_STATE)
        else:
            if self.live.counts.recovered_read_only:
                expected_actions.append(
                    AgentRecoveryAction.REVALIDATE_RECOVERED_AUTHORITY
                )
            if (
                self.live.counts.cleanup_unconfirmed
                or self.live.counts.command_cleanup_quarantined
            ):
                expected_actions.append(
                    AgentRecoveryAction.RESTART_AFTER_CLEANUP_UNCERTAIN
                )
            if self.live.counts.history_write_failures:
                expected_actions.append(
                    AgentRecoveryAction.RETRY_AFTER_HISTORY_WRITE_FAILURE
                )
        expected_recovery = (
            AgentRecoveryState.UNKNOWN
            if self.catalog.state is AgentHardeningState.UNAVAILABLE
            else AgentRecoveryState.ATTENTION_REQUIRED
            if expected_actions
            else AgentRecoveryState.CLEAN
        )
        if self.recovery_actions != tuple(expected_actions):
            raise ValueError("recovery actions are incoherent")
        if self.recovery_state is not expected_recovery:
            raise ValueError("recovery state is incoherent")
        return self


class AgentCatalogHardeningProbe(Protocol):
    def inspect(self) -> AgentCatalogProbeResult: ...


class AgentLiveHardeningSource(Protocol):
    def hardening_facts(self) -> AgentLiveHardeningFacts: ...


class AgentHardeningService:
    """Combine persistence and live state without retaining diagnostic output."""

    _CATALOG_REASONS = {
        "agent_catalog_path_invalid": AgentHardeningReason.CATALOG_PATH_INVALID,
        "agent_catalog_path_unsafe": AgentHardeningReason.CATALOG_PATH_UNSAFE,
        "agent_catalog_schema_newer": AgentHardeningReason.CATALOG_SCHEMA_NEWER,
        "agent_catalog_migration_history_incomplete": (
            AgentHardeningReason.CATALOG_MIGRATION_INVALID
        ),
        "agent_catalog_migration_checksum_mismatch": (
            AgentHardeningReason.CATALOG_MIGRATION_INVALID
        ),
        "agent_catalog_schema_version_mismatch": (
            AgentHardeningReason.CATALOG_MIGRATION_INVALID
        ),
        "agent_catalog_storage_unavailable": AgentHardeningReason.CATALOG_STORAGE_UNAVAILABLE,
    }

    def __init__(
        self,
        catalog_probe: AgentCatalogHardeningProbe,
        live_source: AgentLiveHardeningSource,
    ) -> None:
        self._catalog_probe = catalog_probe
        self._live_source = live_source

    def snapshot(self) -> AgentHardeningSnapshot:
        catalog = self._catalog_status()
        live = self._live_status()
        actions: list[AgentRecoveryAction] = []

        if catalog.state is AgentHardeningState.DEGRADED:
            actions.append(AgentRecoveryAction.INSPECT_LOCAL_CATALOG)
        if catalog.counts is not None and catalog.counts.interrupted_retained_sessions:
            actions.append(AgentRecoveryAction.RESUME_INTERRUPTED_READ_ONLY)
        if live.counts is not None:
            if live.counts.recovered_read_only:
                actions.append(AgentRecoveryAction.REVALIDATE_RECOVERED_AUTHORITY)
            if (
                live.counts.cleanup_unconfirmed
                or live.counts.command_cleanup_quarantined
            ):
                actions.append(AgentRecoveryAction.RESTART_AFTER_CLEANUP_UNCERTAIN)
            if live.counts.history_write_failures:
                actions.append(AgentRecoveryAction.RETRY_AFTER_HISTORY_WRITE_FAILURE)
        else:
            actions.append(AgentRecoveryAction.VERIFY_LIVE_STATE)

        if catalog.state is AgentHardeningState.UNAVAILABLE:
            recovery = AgentRecoveryState.UNKNOWN
        elif actions:
            recovery = AgentRecoveryState.ATTENTION_REQUIRED
        else:
            recovery = AgentRecoveryState.CLEAN
        return AgentHardeningSnapshot(
            recovery_state=recovery,
            recovery_actions=tuple(actions),
            catalog=catalog,
            live=live,
        )

    def _catalog_status(self) -> AgentCatalogHardeningStatus:
        try:
            result = self._catalog_probe.inspect()
        except AgentCatalogError as error:
            return AgentCatalogHardeningStatus(
                state=AgentHardeningState.UNAVAILABLE,
                reason_code=self._CATALOG_REASONS.get(
                    error.code,
                    AgentHardeningReason.CATALOG_DIAGNOSTIC_UNAVAILABLE,
                ),
            )
        except Exception:
            return AgentCatalogHardeningStatus(
                state=AgentHardeningState.UNAVAILABLE,
                reason_code=AgentHardeningReason.CATALOG_DIAGNOSTIC_UNAVAILABLE,
            )

        state = AgentHardeningState.READY
        reason: AgentHardeningReason | None = None
        if not result.quick_check_passed:
            state = AgentHardeningState.DEGRADED
            reason = AgentHardeningReason.CATALOG_QUICK_CHECK_FAILED
        elif result.foreign_key_violations_observed:
            state = AgentHardeningState.DEGRADED
            reason = AgentHardeningReason.CATALOG_FOREIGN_KEY_VIOLATION
        elif result.projection_violations:
            state = AgentHardeningState.DEGRADED
            reason = AgentHardeningReason.CATALOG_PROJECTION_MISMATCH
        return AgentCatalogHardeningStatus(
            state=state,
            reason_code=reason,
            schema_version=result.schema_version,
            quick_check_passed=result.quick_check_passed,
            foreign_key_violations_observed=result.foreign_key_violations_observed,
            foreign_key_scan_truncated=result.foreign_key_scan_truncated,
            projection_violations=result.projection_violations,
            counts=result.counts,
        )

    def _live_status(self) -> AgentLiveHardeningStatus:
        try:
            return AgentLiveHardeningStatus(
                state="ready",
                counts=self._live_source.hardening_facts(),
            )
        except Exception:
            return AgentLiveHardeningStatus(
                state="unavailable",
                reason_code="live_state_unavailable",
            )


__all__ = (
    "AGENT_HARDENING_CONTRACT_VERSION",
    "AGENT_NATIVE_ACCEPTANCE_CONFIRMATION",
    "AGENT_NATIVE_ACCEPTANCE_START_CONTRACT_VERSION",
    "MAX_OBSERVED_INTEGRITY_VIOLATIONS",
    "AgentNativeAcceptanceStartReceipt",
    "AgentCatalogHardeningProbe",
    "AgentCatalogHardeningStatus",
    "AgentCatalogProbeResult",
    "AgentHardeningService",
    "AgentHardeningSnapshot",
    "AgentLiveHardeningFacts",
    "AgentLiveHardeningSource",
    "AgentPersistenceCounts",
    "AgentRecoveryAction",
    "AgentRecoveryState",
    "BeginAgentNativeAcceptance",
)
