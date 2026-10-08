"""Read-only ``ProviderAdapter`` over the Claude Code hook ledger.

The adapter never touches Claude Code, its settings, or its transcripts.  Its
only source is the local append-only ledger the hook receiver fills, so every
value it yields was already minimized under an active consent grant.  It
speaks the same port as the Codex adapter: probe first, list a bounded
snapshot, then read only sessions that belong to that snapshot.

Identifiers it yields are already installation-local pseudonyms; the ordinary
ingestion service protects them again under the provider namespace exactly as
it does for any other source, so downstream storage cannot tell the sources
apart by shape.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import SecretStr

from ....adapters.base import AdapterHealth, AdapterProbe, ProviderAdapter
from ....application.providers import (
    CapabilityKey,
    CapabilityObservation,
    CapabilityState,
    CompatibilityReason,
    CompatibilityReasonCode,
    CompatibilityState,
    DecoderDescriptor,
    ExtractionCompleteness,
    ExtractionCompletenessState,
    ProviderCompatibilityReport,
    ProviderIdentity,
    ProviderSurface,
    SchemaArtifactKind,
    SchemaArtifactProvenance,
)
from ....domain import (
    DataTier,
    EventKind,
    EventTimeBasis,
    Provider,
    SessionState,
    SourceEvent,
    SourceSession,
    SourceSessionPage,
    SourceSessionSnapshot,
    UsageCounterKind,
    UsageRecord,
    UsageScope,
)
from .contracts import (
    ADAPTER_VERSION,
    HOOK_INSTALLATION_MARKER,
    SOURCE_SCHEMA_VERSION,
    UNKNOWN_PROVIDER_VERSION,
    SessionEndReason,
)
from .ledger import LedgerEvent, LedgerSession, SqliteClaudeHookLedger
from .telemetry import (
    USAGE_SEQUENCE_OFFSET,
    TelemetryCounters,
    TelemetryRequestView,
    TelemetrySessionView,
)


MAX_HOOK_PAGE_SIZE = 500
MAX_HOOK_PAGES = 200

# Every capability the hooks decoder can honestly claim.  It deliberately
# declares no ``*_opportunities`` or ``*_links`` member and no message content
# capability: hooks enumerate no requirements, hypotheses, or verification
# tasks, and the receiver never keeps text.  ``EVENT_TIMING`` is the one claim
# the Codex safe-event decoder cannot make - each hook fires synchronously at
# its event, so the receipt clock orders and times every record.
CLAUDE_CODE_HOOK_CAPABILITIES: tuple[CapabilityKey, ...] = (
    CapabilityKey.SESSION_LIST,
    CapabilityKey.SESSION_LABELS,
    CapabilityKey.OPERATIONAL_EVENTS,
    CapabilityKey.TOOL_EVENTS,
    CapabilityKey.EVENT_TIMING,
    # Supplied by the loopback OTLP receiver when the user enables Claude
    # Code telemetry; without it every usage field stays None, never zero.
    CapabilityKey.TOKEN_USAGE,
)

CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR = DecoderDescriptor(
    provider=ProviderIdentity(key="claude_code"),
    surface=ProviderSurface.OPERATIONAL_EVENTS,
    adapter_version=ADAPTER_VERSION,
    decoder_key="claude-code.hooks.operational-events",
    decoder_version="2",
    wire_schema_family="claude-code.hooks.v1",
    canonical_schema_version=SOURCE_SCHEMA_VERSION,
    schema_artifact=SchemaArtifactProvenance(
        artifact_key="claude-code.hooks.documented-payload",
        artifact_version="1",
        kind=SchemaArtifactKind.DOCUMENTED,
    ),
    capabilities=CLAUDE_CODE_HOOK_CAPABILITIES,
    tested_provider_versions=(),
)


class ClaudeHookAdapterError(RuntimeError):
    """Content-free adapter failure."""


class ClaudeHookScopeError(ClaudeHookAdapterError):
    """A read was requested outside the current listed snapshot."""


class ClaudeHookLifecycleError(ClaudeHookAdapterError):
    """The adapter was used before a successful probe or after close."""


def _terminal_state(session: LedgerSession) -> SessionState:
    """Map only what the provider's end reason actually says.

    ``prompt_input_exit`` is the user closing an idle prompt - the ordinary
    completion of a session's lifecycle.  ``logout`` interrupts it.  ``clear``
    and ``other`` are ambiguous, and a session with no end event may still be
    live, so all of those stay unknown rather than borrowing an outcome.
    """

    if session.ended_at is None or session.session_end_reason is None:
        return SessionState.UNKNOWN
    if session.session_end_reason is SessionEndReason.PROMPT_INPUT_EXIT:
        return SessionState.COMPLETED
    if session.session_end_reason is SessionEndReason.LOGOUT:
        return SessionState.INTERRUPTED
    return SessionState.UNKNOWN


def _source_session(
    session: LedgerSession, telemetry: TelemetrySessionView | None = None
) -> SourceSession:
    provider_version = (
        telemetry.provider_version
        if telemetry is not None and telemetry.provider_version is not None
        else UNKNOWN_PROVIDER_VERSION
    )
    activity = session.last_received_at
    if telemetry is not None and telemetry.last_received_at > activity:
        activity = telemetry.last_received_at
    started = session.first_received_at
    if telemetry is not None and telemetry.first_received_at < started:
        started = telemetry.first_received_at
    return SourceSession(
        provider=Provider.CLAUDE_CODE,
        source_installation_id=SecretStr(HOOK_INSTALLATION_MARKER),
        source_project_id=SecretStr(session.hook_project_id),
        source_session_id=SecretStr(session.hook_session_id),
        provider_version=provider_version,
        adapter_version=ADAPTER_VERSION,
        source_schema_version=SOURCE_SCHEMA_VERSION,
        started_at=started,
        source_activity_at=activity,
        ended_at=session.ended_at,
        terminal_state=_terminal_state(session),
        # A hook configuration cannot prove it covered every event, and the
        # receiver drops rather than blocks under contention, so completeness
        # is never claimed; metrics run at bounded confidence.
        events_complete=False,
        source_project_display_name=(
            None
            if session.project_display_label is None
            else SecretStr(session.project_display_label)
        ),
        source_session_display_name=(
            None
            if session.session_display_label is None
            else SecretStr(session.session_display_label)
        ),
    )


def _source_event(event: LedgerEvent) -> SourceEvent:
    return SourceEvent(
        source_event_id=SecretStr(event.hook_event_id),
        kind=event.event_kind,
        sequence=event.sequence,
        occurred_at=event.received_at,
        # The provider supplies no timestamp; the receiver stamps the receipt
        # of a synchronous hook.  SOURCE_SCHEMA_VERSION names that clock.
        time_basis=EventTimeBasis.RECEIVER_OBSERVED,
        duration_ms=event.duration_ms,
        success=event.success,
        tool_category=event.tool_category,
        usage=None,
    )


def _usage_event(request: TelemetryRequestView) -> SourceEvent:
    """One provider ``api_request`` as a delta usage record at request scope."""

    return SourceEvent(
        source_event_id=SecretStr(request.request_id),
        kind=EventKind.USAGE,
        # Usage records live in their own sequence space so hook sequences stay
        # stable as telemetry arrives; consumers that need time order use
        # occurred_at, which here is the provider's own event timestamp.
        sequence=USAGE_SEQUENCE_OFFSET + request.sequence,
        occurred_at=request.reported_at,
        time_basis=EventTimeBasis.PROVIDER_REPORTED,
        duration_ms=request.duration_ms,
        success=None if request.outcome == "completed" else False,
        usage=UsageRecord(
            input_tokens=request.input_tokens,
            cached_input_tokens=request.cache_read_tokens,
            cache_creation_tokens=request.cache_creation_tokens,
            output_tokens=request.output_tokens,
            model_id=request.model_id,
            provider_reported=True,
            counter_kind=UsageCounterKind.DELTA,
            scope=UsageScope.REQUEST,
        ),
    )


def _cumulative_usage_event(session_id: str, counters: TelemetryCounters) -> SourceEvent:
    """Session-total counters when no per-request events were exported."""

    return SourceEvent(
        source_event_id=SecretStr(f"cumulative:{session_id}"),
        kind=EventKind.USAGE,
        sequence=USAGE_SEQUENCE_OFFSET * 2,
        occurred_at=counters.reported_at,
        time_basis=EventTimeBasis.PROVIDER_REPORTED,
        usage=UsageRecord(
            input_tokens=counters.input_tokens_total,
            cached_input_tokens=counters.cache_read_tokens_total,
            cache_creation_tokens=counters.cache_creation_tokens_total,
            output_tokens=counters.output_tokens_total,
            model_id=None,
            provider_reported=True,
            counter_kind=UsageCounterKind.CUMULATIVE,
            scope=UsageScope.THREAD,
        ),
    )


class ClaudeCodeHookAdapter(ProviderAdapter):
    """Read-only adapter over the local hook ledger; construction reads nothing."""

    provider = Provider.CLAUDE_CODE

    def __init__(
        self,
        ledger: SqliteClaudeHookLedger,
        transcript_coverage: Callable[[str], bool] | None = None,
    ) -> None:
        self._ledger = ledger
        # When the owner's transcript file covers a session, the transcript
        # adapter is its single source of record; the hook adapter skips it.
        self._transcript_coverage = transcript_coverage
        self._health = AdapterHealth.UNAVAILABLE
        self._probed = False
        self._closed = False
        self._page_count = 0
        self._cursor_counter = 0
        self._cursors: dict[str, tuple[datetime, str]] = {}
        self._listed: dict[str, SourceSession] = {}

    @property
    def required_consent_tier(self) -> DataTier:
        # The hook payload transits content in memory before minimization, so
        # capture requires the same tier as the Codex list surface, whose
        # documented preview field puts it in the same position.
        return DataTier.REDACTED_CONTENT

    @property
    def requires_explicit_selection(self) -> bool:
        return False

    def probe(self) -> AdapterProbe:
        if self._closed:
            raise ClaudeHookLifecycleError("Claude Code hook adapter is closed")
        try:
            self._ledger.summary()
            self._health = AdapterHealth.READY
        except Exception:
            self._health = AdapterHealth.UNAVAILABLE
        self._probed = True
        provider_version = UNKNOWN_PROVIDER_VERSION
        if self._health is AdapterHealth.READY:
            try:
                provider_version = (
                    self._ledger.latest_provider_version() or UNKNOWN_PROVIDER_VERSION
                )
            except Exception:
                provider_version = UNKNOWN_PROVIDER_VERSION
        return AdapterProbe(
            provider=self.provider,
            provider_version=provider_version,
            adapter_version=ADAPTER_VERSION,
            source_schema_version=SOURCE_SCHEMA_VERSION,
            supports_metadata=True,
            supports_content=False,
            supports_watch=False,
            health=self._health,
        )

    def _ready(self) -> SqliteClaudeHookLedger:
        if self._closed:
            raise ClaudeHookLifecycleError("Claude Code hook adapter is closed")
        if not self._probed or self._health is not AdapterHealth.READY:
            raise ClaudeHookLifecycleError(
                "a successful probe is required before source access"
            )
        return self._ledger

    def _reset_snapshot(self) -> None:
        self._page_count = 0
        self._cursor_counter = 0
        self._cursors.clear()
        self._listed.clear()

    def list_sessions(
        self, *, cursor: str | None = None, limit: int = 100
    ) -> SourceSessionPage:
        ledger = self._ready()
        if limit < 1 or limit > MAX_HOOK_PAGE_SIZE:
            raise ValueError("limit must be within the configured page bound")
        if cursor is None:
            self._reset_snapshot()
            after: tuple[datetime, str] | None = None
        else:
            try:
                after = self._cursors.pop(cursor)
            except KeyError:
                raise ClaudeHookScopeError(
                    "pagination cursor is not part of this snapshot"
                ) from None
        if self._page_count >= MAX_HOOK_PAGES:
            raise ClaudeHookAdapterError("session listing exceeded the page bound")

        rows = ledger.list_sessions(limit=limit + 1, after=after)
        has_more = len(rows) > limit
        rows = rows[:limit]
        sessions: list[SourceSession] = []
        for row in rows:
            if row.hook_session_id in self._listed:
                raise ClaudeHookAdapterError("ledger repeated a session in one snapshot")
            if self._transcript_coverage is not None and self._transcript_coverage(row.hook_session_id):
                # The transcript adapter owns this session entirely - its row,
                # its events, its provenance. Listing it here would re-stamp the
                # catalog row with hook provenance on every index.
                continue
            session = _source_session(row, ledger.get_telemetry_session(row.hook_session_id))
            self._listed[row.hook_session_id] = session
            sessions.append(session)
        self._page_count += 1

        next_cursor = None
        if has_more and rows:
            last = rows[-1]
            self._cursor_counter += 1
            next_cursor = f"p{self._cursor_counter}"
            self._cursors[next_cursor] = (last.first_received_at, last.hook_session_id)
        return SourceSessionPage(sessions=tuple(sessions), next_cursor=next_cursor)

    def read_session(self, session: SourceSession) -> SourceSessionSnapshot:
        ledger = self._ready()
        hook_session_id = session.source_session_id.get_secret_value()
        listed = self._listed.get(hook_session_id)
        if listed is None or listed != session:
            raise ClaudeHookScopeError("session is not part of the current listed snapshot")
        atomic = ledger.read_session_snapshot(hook_session_id)
        if atomic is None:
            raise ClaudeHookScopeError("session left the admitted source boundary")
        current = _source_session(atomic.session, atomic.telemetry)
        if (
            current.source_installation_id != listed.source_installation_id
            or current.source_project_id != listed.source_project_id
            or current.source_session_id != listed.source_session_id
            or current.started_at != listed.started_at
        ):
            raise ClaudeHookScopeError("session identity changed across the source boundary")
        events = [_source_event(event) for event in atomic.events]
        requests = atomic.telemetry_requests
        if requests:
            events.extend(_usage_event(request) for request in requests)
        else:
            telemetry = atomic.telemetry
            if telemetry is not None and telemetry.counters is not None:
                events.append(_cumulative_usage_event(hook_session_id, telemetry.counters))
        return SourceSessionSnapshot(session=current, events=tuple(events))

    def read_events(self, session: SourceSession) -> Iterator[SourceEvent]:
        yield from self.read_session(session).events

    def health(self) -> AdapterHealth:
        return self._health

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._health = AdapterHealth.UNAVAILABLE
        self._reset_snapshot()


Clock = Callable[[], datetime]


def _utc_now() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class ClaudeCodeHooksCompatibilityProbe:
    """Compatibility report for the hook surface; reads only the local ledger."""

    ledger: SqliteClaudeHookLedger
    _clock: Clock = field(default=_utc_now, repr=False)

    @property
    def descriptor(self) -> DecoderDescriptor:
        return CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR

    def check(self) -> ProviderCompatibilityReport:
        try:
            checked_at = self._clock().astimezone(UTC)
        except Exception:
            checked_at = datetime.now(UTC)
        try:
            summary = self.ledger.summary()
        except Exception:
            return ProviderCompatibilityReport(
                descriptor=self.descriptor,
                provider_version=UNKNOWN_PROVIDER_VERSION,
                state=CompatibilityState.UNAVAILABLE,
                capabilities=tuple(
                    CapabilityObservation(
                        key=capability,
                        state=CapabilityState.UNKNOWN,
                        reason_code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE,
                    )
                    for capability in self.descriptor.capabilities
                ),
                extraction=ExtractionCompleteness(
                    state=ExtractionCompletenessState.NONE, observed_units=0
                ),
                reasons=(
                    CompatibilityReason(code=CompatibilityReasonCode.PROVIDER_UNAVAILABLE),
                ),
                checked_at=checked_at,
            )
        # The decoder fully understands every payload it admits, but it cannot
        # prove that the user's hook configuration delivered every event, and
        # it knows the Claude Code version only when telemetry reported one -
        # and even then that version is not in a tested list.  That is a
        # degraded, unknown-completeness surface, and it says so.
        try:
            provider_version = self.ledger.latest_provider_version() or UNKNOWN_PROVIDER_VERSION
        except Exception:
            provider_version = UNKNOWN_PROVIDER_VERSION
        version_reason = (
            CompatibilityReasonCode.PROVIDER_VERSION_UNKNOWN
            if provider_version == UNKNOWN_PROVIDER_VERSION
            else CompatibilityReasonCode.PROVIDER_VERSION_UNTESTED
        )
        telemetry_observed = int(summary.get("telemetry_sessions", 0)) > 0
        reasons = [
            CompatibilityReason(code=version_reason),
            CompatibilityReason(
                code=CompatibilityReasonCode.COMPLETE_DELIVERY_UNPROVEN
            ),
            CompatibilityReason(
                code=CompatibilityReasonCode.EPHEMERAL_DESCRIPTORS_UNAVAILABLE
            ),
        ]
        if not telemetry_observed:
            reasons.append(
                CompatibilityReason(
                    code=CompatibilityReasonCode.OPTIONAL_CAPABILITY_MISSING
                )
            )
        return ProviderCompatibilityReport(
            descriptor=self.descriptor,
            provider_version=provider_version,
            state=CompatibilityState.DEGRADED,
            capabilities=tuple(
                CapabilityObservation(
                    key=capability,
                    state=(
                        CapabilityState.UNKNOWN
                        if capability is CapabilityKey.TOKEN_USAGE
                        and not telemetry_observed
                        else CapabilityState.SUPPORTED
                    ),
                    reason_code=(
                        CompatibilityReasonCode.OPTIONAL_CAPABILITY_MISSING
                        if capability is CapabilityKey.TOKEN_USAGE
                        and not telemetry_observed
                        else None
                    ),
                )
                for capability in self.descriptor.capabilities
            ),
            extraction=ExtractionCompleteness(
                state=ExtractionCompletenessState.UNKNOWN,
                observed_units=min(int(summary["events"]), 10_000_000),
            ),
            reasons=tuple(reasons),
            checked_at=checked_at,
        )


__all__ = (
    "CLAUDE_CODE_HOOKS_DECODER_DESCRIPTOR",
    "CLAUDE_CODE_HOOK_CAPABILITIES",
    "ClaudeCodeHookAdapter",
    "ClaudeCodeHooksCompatibilityProbe",
    "ClaudeHookAdapterError",
    "ClaudeHookLifecycleError",
    "ClaudeHookScopeError",
    "MAX_HOOK_PAGES",
    "MAX_HOOK_PAGE_SIZE",
)
