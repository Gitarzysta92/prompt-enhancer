"""OpenTelemetry (OTLP/HTTP JSON) capture for Claude Code token usage.

Claude Code can export documented telemetry: ``api_request`` events carrying
per-request token counts, model, duration, and the provider's own cost
estimate, and periodic cumulative counters (tokens, cost, lines of code,
commits, pull requests, active time).  Those exports also carry account,
organization, and user identifiers, and - depending on operator settings -
prompt text, tool parameters, and error text.

This module parses OTLP JSON with a closed attribute allowlist and produces
only :class:`TelemetryUsageRecord` and :class:`TelemetryCounters`, neither of
which has a field able to hold text or an account identifier.  The session
identifier is HMACed under the *same* namespace the hook receiver uses, so
usage joins the hook session without either side learning the raw value.

The receiver is a loopback HTTP endpoint that requires a separate write-only
ingest token, records nothing without an active ``claude_code`` consent grant,
and answers a consent-inactive export with an OTLP ``partialSuccess`` so the
provider's exporter neither retries nor surfaces an error to the user.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
import hmac
import sqlite3
from typing import Any, Literal

from pydantic import Field, field_validator

from ....domain import PSEUDONYM_PATTERN, SAFE_VERSION_PATTERN, StrictModel
from ....privacy import Pseudonymizer
from ...sqlite._common import ConnectionScope, from_iso, to_iso
from .contracts import (
    PSEUDONYM_NAMESPACE_PROJECT,
    PSEUDONYM_NAMESPACE_SESSION,
    project_identity_material,
)
from .ledger import HookLedgerConsentInactive, HookLedgerUnavailable, _consent_active


TELEMETRY_CONTRACT_VERSION = "claude-code-otlp.v1"
TELEMETRY_SCHEMA_VERSION = 46
MAX_TELEMETRY_PAYLOAD_BYTES = 4 * 1024 * 1024
MAX_TELEMETRY_RECORDS_PER_PAYLOAD = 10_000
MAX_TELEMETRY_REQUESTS_PER_SESSION = 250_000
# Real OTLP/JSON nests about 14 levels (resource → scope → metric → sum →
# data point → attribute → value); this bounds pathological input, not real.
MAX_TELEMETRY_DEPTH = 24
USAGE_SEQUENCE_OFFSET = 1_000_000

# The complete set of OTLP attribute keys this module is permitted to read.
# Anything else - including user.email, user.id, user.account_uuid,
# organization.id, terminal.type, prompt, tool_parameters, error, and every
# future key - is never looked at.  A test scans this file for other names.
ALLOWED_ATTRIBUTE_KEYS = frozenset(
    {
        "event.name",
        "session.id",
        "app.version",
        "model",
        "cost_usd",
        "duration_ms",
        "input_tokens",
        "output_tokens",
        "cache_read_tokens",
        "cache_creation_tokens",
        "type",
    }
)

_METRIC_NAMES = frozenset(
    {
        "claude_code.token.usage",
        "claude_code.cost.usage",
        "claude_code.lines_of_code.count",
        "claude_code.commit.count",
        "claude_code.pull_request.count",
        "claude_code.active_time.total",
    }
)


class TelemetryParseError(ValueError):
    code = "invalid_otlp_payload"


def _safe_version(value: object) -> str | None:
    if not isinstance(value, str) or SAFE_VERSION_PATTERN.fullmatch(value) is None:
        return None
    return value


def _pseudonym(value: str) -> str:
    if PSEUDONYM_PATTERN.fullmatch(value) is None:
        raise ValueError("telemetry identifiers must be 64-character HMAC pseudonyms")
    return value


class TelemetryUsageRecord(StrictModel):
    """One ``api_request`` event, minimized.  No field can hold text."""

    contract_version: Literal[TELEMETRY_CONTRACT_VERSION] = TELEMETRY_CONTRACT_VERSION
    hook_session_id: str
    hook_project_id: str
    provider_version: str | None = None
    reported_at: datetime
    model_id: str | None = None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    cache_read_tokens: int | None = Field(default=None, ge=0)
    cache_creation_tokens: int | None = Field(default=None, ge=0)
    duration_ms: int | None = Field(default=None, ge=0)
    cost_micro_usd: int | None = Field(default=None, ge=0)
    outcome: Literal["completed", "error"] = "completed"

    _ids = field_validator("hook_session_id", "hook_project_id")(_pseudonym)

    @field_validator("provider_version", "model_id")
    @classmethod
    def validate_safe(cls, value: str | None) -> str | None:
        return None if value is None else (_safe_version(value) or None)


class TelemetryCounters(StrictModel):
    """Latest cumulative counters for one session, minimized."""

    hook_session_id: str
    hook_project_id: str
    provider_version: str | None = None
    reported_at: datetime
    input_tokens_total: int | None = Field(default=None, ge=0)
    output_tokens_total: int | None = Field(default=None, ge=0)
    cache_read_tokens_total: int | None = Field(default=None, ge=0)
    cache_creation_tokens_total: int | None = Field(default=None, ge=0)
    cost_micro_usd_total: int | None = Field(default=None, ge=0)
    lines_added_total: int | None = Field(default=None, ge=0)
    lines_removed_total: int | None = Field(default=None, ge=0)
    commit_count_total: int | None = Field(default=None, ge=0)
    pull_request_count_total: int | None = Field(default=None, ge=0)
    active_user_ms_total: int | None = Field(default=None, ge=0)
    active_cli_ms_total: int | None = Field(default=None, ge=0)

    _ids = field_validator("hook_session_id", "hook_project_id")(_pseudonym)


class TelemetryBatch(StrictModel):
    usage: tuple[TelemetryUsageRecord, ...] = ()
    counters: tuple[TelemetryCounters, ...] = ()
    rejected: int = Field(default=0, ge=0)


class TelemetryIngestOutcome(StrictModel):
    accepted_usage: int = Field(ge=0)
    accepted_counters: int = Field(ge=0)
    rejected: int = Field(ge=0)


# --- OTLP JSON walking (allowlisted, bounded) ---------------------------------


def _any_value(value: object) -> object:
    """Unwrap an OTLP ``AnyValue`` into a Python scalar; ignore compound values."""

    if not isinstance(value, Mapping):
        return None
    if "stringValue" in value:
        raw = value["stringValue"]
        return raw if isinstance(raw, str) else None
    if "intValue" in value:
        raw = value["intValue"]
        if isinstance(raw, bool):
            return None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.lstrip("-").isdigit():
            return int(raw)
        return None
    if "doubleValue" in value:
        raw = value["doubleValue"]
        return float(raw) if isinstance(raw, (int, float)) and not isinstance(raw, bool) else None
    if "boolValue" in value:
        raw = value["boolValue"]
        return raw if isinstance(raw, bool) else None
    return None


def _attributes(items: object) -> dict[str, object]:
    """Read only allowlisted keys out of an OTLP attribute list."""

    result: dict[str, object] = {}
    if not isinstance(items, list):
        return result
    for item in items:
        if not isinstance(item, Mapping):
            continue
        key = item.get("key")
        if not isinstance(key, str) or key not in ALLOWED_ATTRIBUTE_KEYS:
            continue
        result[key] = _any_value(item.get("value"))
    return result


def _int(value: object) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, float) and value >= 0 and value.is_integer():
        return int(value)
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _micro_usd(value: object) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if value < 0 or value != value or value in (float("inf"), float("-inf")):
        return None
    return int(round(float(value) * 1_000_000))


def _nano_time(value: object) -> datetime | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, str) and value.isdigit():
        value = int(value)
    if not isinstance(value, int) or value <= 0:
        return None
    try:
        return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC)
    except (OverflowError, OSError, ValueError):
        return None


def _raw_session_id(value: object) -> str | None:
    if not isinstance(value, str) or not value or len(value) > 256:
        return None
    if any(character in value for character in "\x00\r\n"):
        return None
    return value


def _check_depth(value: object, depth: int = 0) -> None:
    if depth > MAX_TELEMETRY_DEPTH:
        raise TelemetryParseError("otlp payload is too deeply nested")
    if isinstance(value, Mapping):
        for item in value.values():
            _check_depth(item, depth + 1)
    elif isinstance(value, list):
        for item in value:
            _check_depth(item, depth + 1)


def _identity(
    pseudonymizer: Pseudonymizer, raw_session_id: str
) -> tuple[str, str]:
    session = pseudonymizer.pseudonymize(PSEUDONYM_NAMESPACE_SESSION, raw_session_id)
    # OTLP carries no working directory; the project identity is the same
    # content-free missing-cwd placeholder for this already-pseudonymized
    # provider session.  Basing the placeholder on the pseudonym (not retained
    # raw input) lets the ledger recognize it after restart and replace only
    # that placeholder when the exact hook session supplies a project identity.
    project = _telemetry_placeholder_project_id(pseudonymizer, session)
    return session, project


def _telemetry_placeholder_project_id(
    pseudonymizer: Pseudonymizer, hook_session_id: str
) -> str:
    return pseudonymizer.pseudonymize(
        PSEUDONYM_NAMESPACE_PROJECT,
        project_identity_material(None, hook_session_id),
    )


def parse_logs_export(
    payload: object, *, pseudonymizer: Pseudonymizer, received_at: datetime
) -> TelemetryBatch:
    """Reduce an ``ExportLogsServiceRequest`` to usage records."""

    _check_depth(payload)
    if not isinstance(payload, Mapping):
        raise TelemetryParseError("otlp logs payload must be an object")
    usage: list[TelemetryUsageRecord] = []
    rejected = 0
    seen = 0
    for resource_logs in payload.get("resourceLogs") or []:
        if not isinstance(resource_logs, Mapping):
            continue
        resource = resource_logs.get("resource")
        resource_attributes = _attributes(
            resource.get("attributes") if isinstance(resource, Mapping) else None
        )
        for scope_logs in resource_logs.get("scopeLogs") or []:
            if not isinstance(scope_logs, Mapping):
                continue
            for record in scope_logs.get("logRecords") or []:
                seen += 1
                if seen > MAX_TELEMETRY_RECORDS_PER_PAYLOAD:
                    raise TelemetryParseError("otlp payload exceeds the record bound")
                if not isinstance(record, Mapping):
                    rejected += 1
                    continue
                attributes = {**resource_attributes, **_attributes(record.get("attributes"))}
                body = _any_value(record.get("body"))
                name = attributes.get("event.name")
                if not isinstance(name, str) and isinstance(body, str):
                    name = body.removeprefix("claude_code.")
                if name not in ("api_request", "api_error"):
                    # user_prompt, tool_result, tool_decision and unknown events
                    # carry text or duplicate the hook ledger; never read.
                    continue
                raw_session = _raw_session_id(attributes.get("session.id"))
                if raw_session is None:
                    rejected += 1
                    continue
                reported_at = (
                    _nano_time(record.get("timeUnixNano"))
                    or _nano_time(record.get("observedTimeUnixNano"))
                    or received_at
                )
                session_id, project_id = _identity(pseudonymizer, raw_session)
                usage.append(
                    TelemetryUsageRecord(
                        hook_session_id=session_id,
                        hook_project_id=project_id,
                        provider_version=_safe_version(attributes.get("app.version")),
                        reported_at=reported_at.astimezone(UTC),
                        model_id=_safe_version(attributes.get("model")),
                        input_tokens=_int(attributes.get("input_tokens")),
                        output_tokens=_int(attributes.get("output_tokens")),
                        cache_read_tokens=_int(attributes.get("cache_read_tokens")),
                        cache_creation_tokens=_int(attributes.get("cache_creation_tokens")),
                        duration_ms=_int(attributes.get("duration_ms")),
                        cost_micro_usd=_micro_usd(attributes.get("cost_usd")),
                        outcome="error" if name == "api_error" else "completed",
                    )
                )
    return TelemetryBatch(usage=tuple(usage), rejected=rejected)


def parse_metrics_export(
    payload: object, *, pseudonymizer: Pseudonymizer, received_at: datetime
) -> TelemetryBatch:
    """Reduce an ``ExportMetricsServiceRequest`` to per-session counters.

    Claude Code exports cumulative sums; the latest data point per session and
    counter wins.  Only the six documented counters are read.
    """

    _check_depth(payload)
    if not isinstance(payload, Mapping):
        raise TelemetryParseError("otlp metrics payload must be an object")
    per_session: dict[str, dict[str, Any]] = {}
    rejected = 0
    seen = 0
    for resource_metrics in payload.get("resourceMetrics") or []:
        if not isinstance(resource_metrics, Mapping):
            continue
        resource = resource_metrics.get("resource")
        resource_attributes = _attributes(
            resource.get("attributes") if isinstance(resource, Mapping) else None
        )
        for scope_metrics in resource_metrics.get("scopeMetrics") or []:
            if not isinstance(scope_metrics, Mapping):
                continue
            for metric in scope_metrics.get("metrics") or []:
                if not isinstance(metric, Mapping):
                    continue
                name = metric.get("name")
                if name not in _METRIC_NAMES:
                    continue
                container = metric.get("sum") or metric.get("gauge")
                if not isinstance(container, Mapping):
                    continue
                for point in container.get("dataPoints") or []:
                    seen += 1
                    if seen > MAX_TELEMETRY_RECORDS_PER_PAYLOAD:
                        raise TelemetryParseError("otlp payload exceeds the record bound")
                    if not isinstance(point, Mapping):
                        rejected += 1
                        continue
                    attributes = {**resource_attributes, **_attributes(point.get("attributes"))}
                    raw_session = _raw_session_id(attributes.get("session.id"))
                    if raw_session is None:
                        rejected += 1
                        continue
                    value: object = point.get("asInt", point.get("asDouble"))
                    when = _nano_time(point.get("timeUnixNano")) or received_at
                    session_id, project_id = _identity(pseudonymizer, raw_session)
                    bucket = per_session.setdefault(
                        session_id,
                        {
                            "hook_project_id": project_id,
                            "provider_version": _safe_version(attributes.get("app.version")),
                            "reported_at": when,
                        },
                    )
                    if when > bucket["reported_at"]:
                        bucket["reported_at"] = when
                    if bucket.get("provider_version") is None:
                        bucket["provider_version"] = _safe_version(attributes.get("app.version"))
                    kind = attributes.get("type")
                    if name == "claude_code.token.usage":
                        column = {
                            "input": "input_tokens_total",
                            "output": "output_tokens_total",
                            "cacheRead": "cache_read_tokens_total",
                            "cacheCreation": "cache_creation_tokens_total",
                        }.get(kind if isinstance(kind, str) else "")
                        if column is not None:
                            # Several models may report separately; sum them.
                            bucket[column] = (bucket.get(column) or 0) + (_int(value) or 0)
                    elif name == "claude_code.cost.usage":
                        bucket["cost_micro_usd_total"] = (
                            (bucket.get("cost_micro_usd_total") or 0) + (_micro_usd(value) or 0)
                        )
                    elif name == "claude_code.lines_of_code.count":
                        column = {"added": "lines_added_total", "removed": "lines_removed_total"}.get(
                            kind if isinstance(kind, str) else ""
                        )
                        if column is not None:
                            bucket[column] = _int(value)
                    elif name == "claude_code.commit.count":
                        bucket["commit_count_total"] = _int(value)
                    elif name == "claude_code.pull_request.count":
                        bucket["pull_request_count_total"] = _int(value)
                    elif name == "claude_code.active_time.total":
                        column = {"user": "active_user_ms_total", "cli": "active_cli_ms_total"}.get(
                            kind if isinstance(kind, str) else ""
                        )
                        if column is not None:
                            # Reported in seconds; stored as whole milliseconds.
                            seconds = value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
                            bucket[column] = None if seconds is None or seconds < 0 else int(round(float(seconds) * 1000))
    counters = tuple(
        TelemetryCounters(hook_session_id=session_id, **fields)
        for session_id, fields in per_session.items()
    )
    return TelemetryBatch(counters=counters, rejected=rejected)


# --- ledger writes -----------------------------------------------------------------


def _request_identity(pseudonymizer: Pseudonymizer, session_id: str, sequence: int) -> str:
    return pseudonymizer.pseudonymize(f"claude_code:telemetry-request:{session_id}", f"{sequence}")


def _ensure_session(
    connection: sqlite3.Connection,
    *,
    pseudonymizer: Pseudonymizer,
    hook_session_id: str,
    hook_project_id: str,
    provider_version: str | None,
    received_iso: str,
) -> None:
    placeholder_project_id = _telemetry_placeholder_project_id(
        pseudonymizer, hook_session_id
    )
    hook_row = connection.execute(
        """SELECT hook_project_id FROM claude_code_hook_sessions
           WHERE hook_session_id=?""",
        (hook_session_id,),
    ).fetchone()
    effective_project_id = hook_project_id
    if hook_row is not None:
        authoritative_project_id = str(hook_row["hook_project_id"])
        if not (
            hmac.compare_digest(hook_project_id, placeholder_project_id)
            or hmac.compare_digest(hook_project_id, authoritative_project_id)
        ):
            raise HookLedgerUnavailable(
                "telemetry project identity conflicts with the hook session"
            )
        effective_project_id = authoritative_project_id

    row = connection.execute(
        """SELECT request_count, hook_project_id
           FROM claude_code_telemetry_sessions WHERE hook_session_id=?""",
        (hook_session_id,),
    ).fetchone()
    if row is None:
        connection.execute(
            """INSERT INTO claude_code_telemetry_sessions(
                   hook_session_id, hook_project_id, contract_version, provider_version,
                   first_received_at, last_received_at, request_count)
               VALUES (?,?,?,?,?,?,0)""",
            (
                hook_session_id,
                effective_project_id,
                TELEMETRY_CONTRACT_VERSION,
                provider_version,
                received_iso,
                received_iso,
            ),
        )
    else:
        stored_project_id = str(row["hook_project_id"])
        if not hmac.compare_digest(stored_project_id, effective_project_id):
            if hook_row is None or not hmac.compare_digest(
                stored_project_id, placeholder_project_id
            ):
                raise HookLedgerUnavailable(
                    "telemetry session has a conflicting project identity"
                )
        connection.execute(
            """UPDATE claude_code_telemetry_sessions
               SET hook_project_id=?, last_received_at=?,
                   provider_version=COALESCE(provider_version, ?)
               WHERE hook_session_id=?""",
            (
                effective_project_id,
                received_iso,
                provider_version,
                hook_session_id,
            ),
        )


def append_batch(
    connection: sqlite3.Connection,
    pseudonymizer: Pseudonymizer,
    batch: TelemetryBatch,
    *,
    received_at: datetime,
) -> TelemetryIngestOutcome:
    """Append one parsed batch inside the caller's transaction."""

    received_iso = to_iso(received_at)
    accepted_usage = 0
    for record in batch.usage:
        _ensure_session(
            connection,
            pseudonymizer=pseudonymizer,
            hook_session_id=record.hook_session_id,
            hook_project_id=record.hook_project_id,
            provider_version=record.provider_version,
            received_iso=received_iso,
        )
        count_row = connection.execute(
            "SELECT request_count FROM claude_code_telemetry_sessions WHERE hook_session_id=?",
            (record.hook_session_id,),
        ).fetchone()
        sequence = int(count_row["request_count"])
        if sequence >= MAX_TELEMETRY_REQUESTS_PER_SESSION:
            raise HookLedgerUnavailable("telemetry request bound reached")
        connection.execute(
            """INSERT INTO claude_code_telemetry_requests(
                   request_id, hook_session_id, sequence, received_at, reported_at,
                   model_id, input_tokens, output_tokens, cache_read_tokens,
                   cache_creation_tokens, duration_ms, cost_micro_usd, outcome)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                _request_identity(pseudonymizer, record.hook_session_id, sequence),
                record.hook_session_id,
                sequence,
                received_iso,
                to_iso(record.reported_at),
                record.model_id,
                record.input_tokens,
                record.output_tokens,
                record.cache_read_tokens,
                record.cache_creation_tokens,
                record.duration_ms,
                record.cost_micro_usd,
                record.outcome,
            ),
        )
        connection.execute(
            """UPDATE claude_code_telemetry_sessions
               SET request_count=request_count+1 WHERE hook_session_id=?""",
            (record.hook_session_id,),
        )
        accepted_usage += 1

    accepted_counters = 0
    for counters in batch.counters:
        _ensure_session(
            connection,
            pseudonymizer=pseudonymizer,
            hook_session_id=counters.hook_session_id,
            hook_project_id=counters.hook_project_id,
            provider_version=counters.provider_version,
            received_iso=received_iso,
        )
        connection.execute(
            """UPDATE claude_code_telemetry_sessions SET
                   input_tokens_total=COALESCE(?, input_tokens_total),
                   output_tokens_total=COALESCE(?, output_tokens_total),
                   cache_read_tokens_total=COALESCE(?, cache_read_tokens_total),
                   cache_creation_tokens_total=COALESCE(?, cache_creation_tokens_total),
                   cost_micro_usd_total=COALESCE(?, cost_micro_usd_total),
                   lines_added_total=COALESCE(?, lines_added_total),
                   lines_removed_total=COALESCE(?, lines_removed_total),
                   commit_count_total=COALESCE(?, commit_count_total),
                   pull_request_count_total=COALESCE(?, pull_request_count_total),
                   active_user_ms_total=COALESCE(?, active_user_ms_total),
                   active_cli_ms_total=COALESCE(?, active_cli_ms_total),
                   counters_reported_at=?
               WHERE hook_session_id=?""",
            (
                counters.input_tokens_total,
                counters.output_tokens_total,
                counters.cache_read_tokens_total,
                counters.cache_creation_tokens_total,
                counters.cost_micro_usd_total,
                counters.lines_added_total,
                counters.lines_removed_total,
                counters.commit_count_total,
                counters.pull_request_count_total,
                counters.active_user_ms_total,
                counters.active_cli_ms_total,
                to_iso(counters.reported_at),
                counters.hook_session_id,
            ),
        )
        accepted_counters += 1
    return TelemetryIngestOutcome(
        accepted_usage=accepted_usage,
        accepted_counters=accepted_counters,
        rejected=batch.rejected,
    )


class TelemetryIngestService:
    """Application-side ingest used by the loopback OTLP receiver."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        pseudonymizer: Pseudonymizer,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._pseudonymizer = pseudonymizer

    def ingest_logs(self, payload: object, *, now: datetime | None = None) -> TelemetryIngestOutcome:
        received_at = (now or datetime.now(UTC)).astimezone(UTC)
        batch = parse_logs_export(payload, pseudonymizer=self._pseudonymizer, received_at=received_at)
        return self._commit(batch, received_at)

    def ingest_metrics(self, payload: object, *, now: datetime | None = None) -> TelemetryIngestOutcome:
        received_at = (now or datetime.now(UTC)).astimezone(UTC)
        batch = parse_metrics_export(payload, pseudonymizer=self._pseudonymizer, received_at=received_at)
        return self._commit(batch, received_at)

    def _commit(self, batch: TelemetryBatch, received_at: datetime) -> TelemetryIngestOutcome:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            if not _consent_active(connection):
                raise HookLedgerConsentInactive("claude_code local-history consent is inactive")
            version = int(connection.execute("PRAGMA user_version").fetchone()[0])
            if version < TELEMETRY_SCHEMA_VERSION:
                raise HookLedgerUnavailable("local metadata store predates telemetry capture")
            connection.execute("BEGIN IMMEDIATE")
            try:
                outcome = append_batch(connection, self._pseudonymizer, batch, received_at=received_at)
            except Exception:
                connection.rollback()
                raise
            connection.commit()
            return outcome


# --- read side for the adapter -------------------------------------------------------


class TelemetrySessionView(StrictModel):
    hook_session_id: str
    hook_project_id: str
    provider_version: str | None
    first_received_at: datetime
    last_received_at: datetime
    request_count: int
    counters: TelemetryCounters | None


class TelemetryRequestView(StrictModel):
    request_id: str
    hook_session_id: str
    sequence: int
    reported_at: datetime
    model_id: str | None
    input_tokens: int | None
    output_tokens: int | None
    cache_read_tokens: int | None
    cache_creation_tokens: int | None
    duration_ms: int | None
    cost_micro_usd: int | None
    outcome: str


def _row_counters(row: sqlite3.Row) -> TelemetryCounters | None:
    if row["counters_reported_at"] is None:
        return None
    reported = from_iso(row["counters_reported_at"])
    assert reported is not None
    return TelemetryCounters(
        hook_session_id=row["hook_session_id"],
        hook_project_id=row["hook_project_id"],
        provider_version=row["provider_version"],
        reported_at=reported,
        input_tokens_total=row["input_tokens_total"],
        output_tokens_total=row["output_tokens_total"],
        cache_read_tokens_total=row["cache_read_tokens_total"],
        cache_creation_tokens_total=row["cache_creation_tokens_total"],
        cost_micro_usd_total=row["cost_micro_usd_total"],
        lines_added_total=row["lines_added_total"],
        lines_removed_total=row["lines_removed_total"],
        commit_count_total=row["commit_count_total"],
        pull_request_count_total=row["pull_request_count_total"],
        active_user_ms_total=row["active_user_ms_total"],
        active_cli_ms_total=row["active_cli_ms_total"],
    )


def row_telemetry_session(row: sqlite3.Row) -> TelemetrySessionView:
    first = from_iso(row["first_received_at"])
    last = from_iso(row["last_received_at"])
    assert first is not None and last is not None
    return TelemetrySessionView(
        hook_session_id=row["hook_session_id"],
        hook_project_id=row["hook_project_id"],
        provider_version=row["provider_version"],
        first_received_at=first,
        last_received_at=last,
        request_count=int(row["request_count"]),
        counters=_row_counters(row),
    )


def row_telemetry_request(row: sqlite3.Row) -> TelemetryRequestView:
    reported = from_iso(row["reported_at"])
    assert reported is not None
    return TelemetryRequestView(
        request_id=row["request_id"],
        hook_session_id=row["hook_session_id"],
        sequence=int(row["sequence"]),
        reported_at=reported,
        model_id=row["model_id"],
        input_tokens=row["input_tokens"],
        output_tokens=row["output_tokens"],
        cache_read_tokens=row["cache_read_tokens"],
        cache_creation_tokens=row["cache_creation_tokens"],
        duration_ms=row["duration_ms"],
        cost_micro_usd=row["cost_micro_usd"],
        outcome=row["outcome"],
    )


__all__ = (
    "ALLOWED_ATTRIBUTE_KEYS",
    "MAX_TELEMETRY_PAYLOAD_BYTES",
    "TELEMETRY_CONTRACT_VERSION",
    "TELEMETRY_SCHEMA_VERSION",
    "USAGE_SEQUENCE_OFFSET",
    "TelemetryBatch",
    "TelemetryCounters",
    "TelemetryIngestOutcome",
    "TelemetryIngestService",
    "TelemetryParseError",
    "TelemetryRequestView",
    "TelemetrySessionView",
    "TelemetryUsageRecord",
    "append_batch",
    "parse_logs_export",
    "parse_metrics_export",
    "row_telemetry_request",
    "row_telemetry_session",
)
