"""Application service for immutable deterministic task-analysis runs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from ...domain import (
    DataTier,
    PSEUDONYM_PATTERN,
    SAFE_VERSION_PATTERN,
    SafeEvent,
    SafeSession,
)
from ..persistence import (
    AnalysisResultRecord,
    AnalysisRunDraft,
    AnalysisRunRepository,
    AnalysisRunStatus,
    MetricValueState,
    PersistenceConflictError,
    TaskRepository,
)
from .task_metrics import (
    DEFAULT_TASK_METRIC_PACK,
    TASK_METRIC_ENGINE_VERSION,
    TaskSessionEvidence,
    compute_task_metrics,
)


class TaskAnalysisError(RuntimeError):
    """Sanitized base error for local task analysis."""


class TaskRevisionNotFoundError(TaskAnalysisError):
    """The reviewed task revision does not exist."""


class TaskAnalysisInputError(TaskAnalysisError):
    """Required safe metadata is unavailable or inconsistent."""


class TaskAnalysisConflictError(TaskAnalysisError):
    """An idempotency key conflicts with immutable analysis provenance."""


class TaskAnalysisExecutionError(TaskAnalysisError):
    """The deterministic metric pack did not complete."""


class TaskAnalysisDataSource(Protocol):
    def get_session(self, session_id: str) -> SafeSession | None: ...

    def get_session_events(self, session_id: str) -> tuple[SafeEvent, ...]: ...


class TaskAnalysisIdFactory(Protocol):
    def analysis_run_id(
        self,
        idempotency_key: str,
        task_id: str,
        task_revision: int,
        metric_pack_key: str,
        metric_pack_version: int,
    ) -> str: ...

    def fingerprint(self, namespace: str, values: tuple[str, ...]) -> str: ...


@dataclass(frozen=True, slots=True)
class TaskAnalysisOutcome:
    run_id: str
    status: AnalysisRunStatus
    result_count: int
    applied: bool


def _draft_matches(left: AnalysisRunDraft, right: AnalysisRunDraft) -> bool:
    return left.model_dump(exclude={"started_at"}) == right.model_dump(
        exclude={"started_at"}
    )


def _optional_scalar(value: object | None) -> str:
    """Encode one already-safe metadata scalar without collapsing missing values."""

    if value is None:
        return "none"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    enum_value = getattr(value, "value", None)
    return str(enum_value if enum_value is not None else value)


def _evidence_fingerprint_values(
    evidence: tuple[TaskSessionEvidence, ...],
) -> tuple[str, ...]:
    """Return a canonical, content-free snapshot of every loaded safe input.

    Task revisions intentionally identify their sessions but do not freeze provider
    metadata. Ingestion may later fill an end time, usage counters, or additional
    events. Including the complete safe snapshot makes an idempotency retry detect
    that drift instead of silently returning results computed from older evidence.
    """

    values: list[str] = ["snapshot-schema", "1", "session-count", str(len(evidence))]
    for item in evidence:
        session = item.session
        values.extend(
            (
                "session",
                session.session_id,
                "provider",
                session.provider.value,
                "installation-id",
                session.installation_id,
                "project-id",
                session.project_id,
                "provider-version",
                session.provider_version,
                "adapter-version",
                session.adapter_version,
                "source-schema-version",
                session.source_schema_version,
                "started-at",
                _optional_scalar(session.started_at),
                "ended-at",
                _optional_scalar(session.ended_at),
                "terminal-state",
                session.terminal_state.value,
                "events-complete",
                _optional_scalar(session.events_complete),
                "event-count",
                str(len(item.events)),
            )
        )
        for event in item.events:
            values.extend(
                (
                    "event",
                    event.event_id,
                    "kind",
                    event.kind.value,
                    "sequence",
                    str(event.sequence),
                    "occurred-at",
                    _optional_scalar(event.occurred_at),
                    "time-basis",
                    event.time_basis.value,
                    "duration-ms",
                    _optional_scalar(event.duration_ms),
                    "success",
                    _optional_scalar(event.success),
                    "tool-category",
                    _optional_scalar(event.tool_category),
                )
            )
            if event.usage is None:
                values.extend(("usage", "none"))
                continue
            usage = event.usage
            values.extend(
                (
                    "usage",
                    "present",
                    "input-tokens",
                    _optional_scalar(usage.input_tokens),
                    "cached-input-tokens",
                    _optional_scalar(usage.cached_input_tokens),
                    "cache-creation-tokens",
                    _optional_scalar(usage.cache_creation_tokens),
                    "output-tokens",
                    _optional_scalar(usage.output_tokens),
                    "reasoning-output-tokens",
                    _optional_scalar(usage.reasoning_output_tokens),
                    "total-tokens",
                    _optional_scalar(usage.total_tokens),
                    "model-id",
                    _optional_scalar(usage.model_id),
                    "model-id-present",
                    _optional_scalar(usage.model_id is not None),
                    "provider-reported",
                    _optional_scalar(usage.provider_reported),
                    "counter-kind",
                    usage.counter_kind.value,
                    "usage-scope",
                    usage.scope.value,
                )
            )
    return tuple(values)


class TaskAnalysisService:
    """Compute one versioned task metric pack and append its results once."""

    def __init__(
        self,
        tasks: TaskRepository,
        analyses: AnalysisRunRepository,
        data_source: TaskAnalysisDataSource,
        identifiers: TaskAnalysisIdFactory,
        *,
        schema_version: int,
        clock: Callable[[], datetime] = lambda: datetime.now(UTC),
    ) -> None:
        if schema_version < 1:
            raise ValueError("analysis schema version must be positive")
        self._tasks = tasks
        self._analyses = analyses
        self._data_source = data_source
        self._identifiers = identifiers
        self._schema_version = schema_version
        self._clock = clock

    def run(
        self,
        task_id: str,
        task_revision: int,
        *,
        idempotency_key: str,
    ) -> TaskAnalysisOutcome:
        if not isinstance(task_id, str) or not PSEUDONYM_PATTERN.fullmatch(task_id):
            raise TaskAnalysisInputError("task identifier must be a safe pseudonym")
        if (
            isinstance(task_revision, bool)
            or not isinstance(task_revision, int)
            or task_revision < 1
        ):
            raise TaskAnalysisInputError("task revision must be positive")
        if (
            not isinstance(idempotency_key, str)
            or not SAFE_VERSION_PATTERN.fullmatch(idempotency_key)
        ):
            raise TaskAnalysisInputError(
                "idempotency key must be a short content-free identifier"
            )
        revision = self._tasks.get_revision(task_id, task_revision)
        if revision is None:
            raise TaskRevisionNotFoundError("task revision does not exist")

        evidence = self._load_evidence(revision.session_ids)
        input_fingerprint = self._identifiers.fingerprint(
            "task-analysis-input-v1",
            (
                revision.input_fingerprint,
                DEFAULT_TASK_METRIC_PACK.key,
                f"i:{DEFAULT_TASK_METRIC_PACK.version}",
                TASK_METRIC_ENGINE_VERSION,
                *revision.session_ids,
                *_evidence_fingerprint_values(evidence),
            ),
        )
        run_id = self._identifiers.analysis_run_id(
            idempotency_key,
            revision.task_id,
            revision.revision,
            DEFAULT_TASK_METRIC_PACK.key,
            DEFAULT_TASK_METRIC_PACK.version,
        )
        draft = AnalysisRunDraft(
            run_id=run_id,
            task_id=revision.task_id,
            task_revision=revision.revision,
            metric_pack_key=DEFAULT_TASK_METRIC_PACK.key,
            metric_pack_version=DEFAULT_TASK_METRIC_PACK.version,
            data_tier=DataTier.METADATA,
            input_fingerprint=input_fingerprint,
            metric_engine_version=TASK_METRIC_ENGINE_VERSION,
            redactor_version="not-applicable",
            schema_version=self._schema_version,
            started_at=self._clock(),
        )
        existing = self._analyses.get(run_id)
        if existing is not None:
            return self._existing_outcome(existing.draft, draft, existing.status)

        try:
            self._analyses.begin(draft)
        except PersistenceConflictError as exc:
            existing = self._analyses.get(run_id)
            if existing is None:
                raise TaskAnalysisConflictError("analysis run conflicts") from exc
            return self._existing_outcome(existing.draft, draft, existing.status)

        try:
            calculated = compute_task_metrics(evidence)
            finished_at = self._clock()
            results = tuple(
                AnalysisResultRecord(
                    observation=item.observation,
                    value_state=(
                        MetricValueState.KNOWN
                        if item.observation.numeric_value is not None
                        or item.observation.text_value is not None
                        else MetricValueState.UNKNOWN
                    ),
                    calculator_version=TASK_METRIC_ENGINE_VERSION,
                    evidence_event_ids=item.evidence_event_ids,
                    computed_at=finished_at,
                )
                for item in calculated
            )
            self._analyses.complete(run_id, results, finished_at=finished_at)
        except PersistenceConflictError as exc:
            raise TaskAnalysisConflictError("analysis run transition conflicts") from exc
        except Exception as exc:
            self._mark_failed(run_id)
            raise TaskAnalysisExecutionError(
                "deterministic task analysis failed"
            ) from exc
        return TaskAnalysisOutcome(
            run_id=run_id,
            status=AnalysisRunStatus.COMPLETED,
            result_count=len(results),
            applied=True,
        )

    def _load_evidence(
        self, session_ids: tuple[str, ...]
    ) -> tuple[TaskSessionEvidence, ...]:
        evidence: list[TaskSessionEvidence] = []
        try:
            for session_id in session_ids:
                session = self._data_source.get_session(session_id)
                if session is None:
                    raise TaskAnalysisInputError("task session does not exist")
                events = tuple(
                    sorted(
                        self._data_source.get_session_events(session_id),
                        key=lambda event: (event.sequence, event.event_id),
                    )
                )
                evidence.append(
                    TaskSessionEvidence(
                        session=session,
                        events=events,
                    )
                )
        except TaskAnalysisInputError:
            raise
        except Exception as exc:
            raise TaskAnalysisInputError("task evidence is unavailable") from exc
        return tuple(evidence)

    def _existing_outcome(
        self,
        existing: AnalysisRunDraft,
        expected: AnalysisRunDraft,
        status: AnalysisRunStatus,
    ) -> TaskAnalysisOutcome:
        if not _draft_matches(existing, expected):
            raise TaskAnalysisConflictError(
                "analysis identifier conflicts with stored provenance"
            )
        return TaskAnalysisOutcome(
            run_id=existing.run_id,
            status=status,
            result_count=len(self._analyses.get_results(existing.run_id)),
            applied=False,
        )

    def _mark_failed(self, run_id: str) -> None:
        try:
            self._analyses.fail(
                run_id,
                finished_at=self._clock(),
                failure_code="deterministic_analysis_failed",
            )
        except Exception:
            # Preserve the original sanitized execution error. A still-running
            # record remains explicit and can be diagnosed or privacy-deleted.
            return
