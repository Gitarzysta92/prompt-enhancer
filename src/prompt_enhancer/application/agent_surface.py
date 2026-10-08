"""Allowlisted surface for connected coding agents (MCP, ADR 0014 and ADR 0015).

Everything the read tools return is metadata or a metric value: names the owner
chose to show in the dashboard, pseudonymous identifiers, counts, metric states
and values, calibration progress and model-judge agreement. No transcript text,
file path, token, or raw event ever crosses this boundary; inputs are validated
and every answer is bounded. The one tool that accepts text, ``check_prompt``,
receives the prompt the agent already holds, analyses it locally, stores
metrics only, and returns commentary about that prompt. The surface is the same
for every transport that exposes it.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal, Protocol

from pydantic import Field, ValidationError

from ..domain import PSEUDONYM_PATTERN, Provider, StrictModel
from .prompt_check import PromptCheckRequest, PromptCheckResult


AGENT_SURFACE_CONTRACT_VERSION = "agent-surface.v1"
MAX_SESSIONS_PER_PAGE = 50
MAX_SUMMARY_SESSIONS = 300
MAX_PERIOD_DAYS = 365


class SessionCatalog(Protocol):
    def list_sessions(
        self, *, limit: int = 100, offset: int = 0, provider: Provider | None = None, project_id: str | None = None
    ) -> list[dict[str, object]]: ...

    def list_metric_definitions(self) -> list[dict[str, object]]: ...

    def get_session_metrics(self, session_id: str) -> list[dict[str, object]]: ...


class AgentSurfaceError(ValueError):
    """A closed, content-free failure code for a tool call.

    ``details`` is deliberately opt-in.  Surfaces may use it only for small,
    preselected machine facts (for example an HTTP status and whether retrying
    is safe); exception text and local values must never be copied into it.
    """

    def __init__(
        self,
        code: str,
        *,
        details: Mapping[str, object] | None = None,
    ) -> None:
        super().__init__(code)
        self.code = code
        self.details = dict(details or {})


# ----- tool inputs -----


class ListSessionsInput(StrictModel):
    provider: Literal["codex", "claude_code", "synthetic"] | None = None
    project_id: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    limit: int = Field(default=20, ge=1, le=MAX_SESSIONS_PER_PAGE)
    offset: int = Field(default=0, ge=0, le=100_000)


class SessionMetricsInput(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)


class SummarizePeriodInput(StrictModel):
    days: int = Field(default=30, ge=1, le=MAX_PERIOD_DAYS)
    provider: Literal["codex", "claude_code", "synthetic"] | None = None


class ExplainMetricInput(StrictModel):
    metric_key: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class EmptyInput(StrictModel):
    pass


class CheckPromptInput(PromptCheckRequest):
    """Same contract as the HTTP prompt check; documented here for the tool schema."""


@dataclass(frozen=True, slots=True)
class ToolSpec:
    name: str
    description: str
    input_model: type[StrictModel]

    def input_schema(self) -> dict[str, Any]:
        schema = self.input_model.model_json_schema()
        schema.pop("title", None)
        schema.setdefault("type", "object")
        schema.setdefault("properties", {})
        return schema


# ----- the surface -----


_SESSION_FIELDS = (
    "session_id",
    "project_id",
    "provider",
    "provider_version",
    "started_at",
    "ended_at",
    "terminal_state",
    "events_complete",
    "project_display_name",
    "session_display_name",
)
_METRIC_FIELDS = (
    "key",
    "version",
    "dimension",
    "display_name",
    "numeric_value",
    "text_value",
    "unit",
    "source",
    "observed_count",
    "eligible_count",
    "coverage",
    "confidence",
    "computed_at",
)
_DEFINITION_FIELDS = ("key", "version", "dimension", "display_name", "description", "unit", "source")


def _pick(row: Mapping[str, object], fields: Sequence[str]) -> dict[str, object]:
    return {field: row.get(field) for field in fields if field in row}


class AgentReadSurface:
    """The allowlisted tools. Each returns plain JSON-serializable data."""

    def __init__(
        self,
        catalog: SessionCatalog,
        *,
        calibration_status: Callable[[], dict[str, object]] | None = None,
        prompt_check: Callable[[PromptCheckRequest], PromptCheckResult] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._catalog = catalog
        self._calibration_status = calibration_status
        self._prompt_check = prompt_check
        self._clock = clock or (lambda: datetime.now(UTC))

    # -- catalog --

    def tools(self) -> tuple[ToolSpec, ...]:
        base = (
            ToolSpec(
                name="list_metric_definitions",
                description="The metric catalog: key, dimension, name, description, unit and source of every metric the app computes. No values.",
                input_model=EmptyInput,
            ),
            ToolSpec(
                name="list_sessions",
                description="Recent coding-agent sessions (newest first) with provider, project and session names the owner shows in the dashboard, timestamps and terminal state. Pseudonymous ids; no content. Page with limit/offset.",
                input_model=ListSessionsInput,
            ),
            ToolSpec(
                name="get_session_metrics",
                description="Stored metric results for one session: metric key, value or state, unit, source, coverage and confidence. Unknown metrics are absent or unknown, never zero.",
                input_model=SessionMetricsInput,
            ),
            ToolSpec(
                name="summarize_period",
                description="Content-free summary of the last N days: sessions per provider, sessions per project (top ten), and how many of the most recent sessions have a known value per metric.",
                input_model=SummarizePeriodInput,
            ),
            ToolSpec(
                name="explain_metric",
                description="Definition of one metric plus how to read its states (known / unknown / not applicable) and the rule that objective evidence outranks model judgments.",
                input_model=ExplainMetricInput,
            ),
            ToolSpec(
                name="get_calibration_status",
                description="Progress of the owner's blind calibration ratings and the local model judge's agreement with them (labels only). Judgments are never metric values.",
                input_model=EmptyInput,
            ),
        )
        if self._prompt_check is None:
            return base
        return (
            *base,
            ToolSpec(
                name="check_prompt",
                description=(
                    "Validate a prompt before acting on it. Send the prompt the person just wrote (and, if you have them, the earlier "
                    "turns as prior_messages, oldest first). Returns deterministic prompt metrics with the cues detected or missing, "
                    "content-free context inference (task type, dependence on earlier turns, whether verification was asked for), "
                    "local-model commentary with a reformulated prompt and element-level rewrites when a model is active, and a short "
                    "summary. Use the suggestions to ask the person a clarifying question or to restate the task; nothing but metrics is stored. "
                    "Optional - use it when a prompt looks vague, large, or high-stakes."
                ),
                input_model=CheckPromptInput,
            ),
        )

    def call(self, name: str, arguments: Mapping[str, Any] | None) -> dict[str, Any]:
        spec = next((tool for tool in self.tools() if tool.name == name), None)
        if spec is None:
            raise AgentSurfaceError("unknown_tool")
        try:
            parsed = spec.input_model.model_validate(dict(arguments or {}))
        except ValidationError:
            raise AgentSurfaceError("invalid_arguments") from None
        handler = getattr(self, f"_tool_{name}")
        result = handler(parsed)
        return {"contract_version": AGENT_SURFACE_CONTRACT_VERSION, **result}

    # -- tools --

    def _tool_list_metric_definitions(self, _: EmptyInput) -> dict[str, Any]:
        rows = self._catalog.list_metric_definitions()
        return {"definitions": [_pick(row, _DEFINITION_FIELDS) for row in rows]}

    def _tool_list_sessions(self, payload: ListSessionsInput) -> dict[str, Any]:
        rows = self._catalog.list_sessions(
            limit=payload.limit,
            offset=payload.offset,
            provider=Provider(payload.provider) if payload.provider else None,
            project_id=payload.project_id,
        )
        return {"sessions": [_pick(row, _SESSION_FIELDS) for row in rows], "limit": payload.limit, "offset": payload.offset}

    def _tool_get_session_metrics(self, payload: SessionMetricsInput) -> dict[str, Any]:
        rows = self._catalog.get_session_metrics(payload.session_id)
        return {"session_id": payload.session_id, "metrics": [_pick(row, _METRIC_FIELDS) for row in rows]}

    def _tool_summarize_period(self, payload: SummarizePeriodInput) -> dict[str, Any]:
        since = self._clock() - timedelta(days=payload.days)
        provider = Provider(payload.provider) if payload.provider else None
        recent: list[dict[str, object]] = []
        offset = 0
        while len(recent) < MAX_SUMMARY_SESSIONS:
            page = self._catalog.list_sessions(limit=MAX_SESSIONS_PER_PAGE, offset=offset, provider=provider)
            if not page:
                break
            for row in page:
                started = _parse_timestamp(row.get("started_at"))
                if started is not None and started < since:
                    page = []
                    break
                recent.append(row)
                if len(recent) >= MAX_SUMMARY_SESSIONS:
                    break
            if not page or len(page) < MAX_SESSIONS_PER_PAGE:
                break
            offset += MAX_SESSIONS_PER_PAGE
        by_provider = Counter(str(row.get("provider")) for row in recent)
        by_project = Counter(
            (str(row.get("project_display_name") or row.get("project_id")), str(row.get("project_id")))
            for row in recent
        )
        known_per_metric: Counter[str] = Counter()
        for row in recent:
            for metric in self._catalog.get_session_metrics(str(row.get("session_id"))):
                if metric.get("numeric_value") is not None or metric.get("text_value") is not None:
                    known_per_metric[str(metric.get("key"))] += 1
        return {
            "days": payload.days,
            "since": since.isoformat(timespec="seconds"),
            "sessions": len(recent),
            "truncated": len(recent) >= MAX_SUMMARY_SESSIONS,
            "sessions_by_provider": dict(sorted(by_provider.items())),
            "top_projects": [
                {"project_id": project_id, "project_display_name": name, "sessions": count}
                for (name, project_id), count in by_project.most_common(10)
            ],
            "sessions_with_known_value_by_metric": dict(sorted(known_per_metric.items())),
        }

    def _tool_explain_metric(self, payload: ExplainMetricInput) -> dict[str, Any]:
        rows = [row for row in self._catalog.list_metric_definitions() if row.get("key") == payload.metric_key]
        if not rows:
            raise AgentSurfaceError("metric_not_found")
        latest = max(rows, key=lambda row: int(row.get("version") or 0))
        return {
            "metric": _pick(latest, _DEFINITION_FIELDS),
            "versions": sorted(int(row.get("version") or 0) for row in rows),
            "reading_guide": {
                "known": "a measured value with its coverage (share of eligible events observed) and, when present, a confidence",
                "unknown": "the metric could not be measured for that session; it is never converted to zero",
                "not_applicable": "the session has no eligible events for this metric",
                "authority": "objective evidence (tests, builds, explicit acceptance) outranks model-written claims and model judgments; model judgments are stored apart and never become metric values",
            },
        }

    def _tool_check_prompt(self, payload: CheckPromptInput) -> dict[str, Any]:
        if self._prompt_check is None:
            raise AgentSurfaceError("unknown_tool")
        result = self._prompt_check(PromptCheckRequest.model_validate(payload.model_dump()))
        data = result.model_dump(mode="json")
        data.pop("contract_version", None)
        return data

    def _tool_get_calibration_status(self, _: EmptyInput) -> dict[str, Any]:
        if self._calibration_status is None:
            return {"available": False}
        try:
            status = dict(self._calibration_status())
        except Exception:
            raise AgentSurfaceError("calibration_unavailable") from None
        return {"available": True, **status}


def _parse_timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)


__all__ = (
    "AGENT_SURFACE_CONTRACT_VERSION",
    "AgentReadSurface",
    "AgentSurfaceError",
    "MAX_PERIOD_DAYS",
    "MAX_SESSIONS_PER_PAGE",
    "MAX_SUMMARY_SESSIONS",
    "ToolSpec",
)
