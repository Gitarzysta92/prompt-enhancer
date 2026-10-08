"""SQLite history for prompt checks: metrics and counters only, never text (ADR 0015)."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import AbstractContextManager
from datetime import datetime
import json
import sqlite3

from ...application.prompt_check import PromptCheckRecord, PromptMetricReading
from ...domain import PSEUDONYM_PATTERN


class SqlitePromptCheckRepository:
    def __init__(self, connection_factory: Callable[..., AbstractContextManager[sqlite3.Connection]], ensure_initialized: Callable[[], None]) -> None:
        self._connection = connection_factory
        self._ensure_initialized = ensure_initialized

    def insert(self, record: PromptCheckRecord) -> None:
        self._ensure_initialized()
        metrics = json.dumps([reading.model_dump(mode="json") for reading in record.metrics], separators=(",", ":"))
        with self._connection() as connection:
            connection.execute(
                """
                INSERT INTO prompt_checks(
                    check_id, created_at, provider, agent_model, language, task_type, prompt_chars,
                    prior_message_count, depends_on_prior_context, verification_requested, metrics_json,
                    commentary_state, commentary_model_alias, prompt_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.check_id,
                    record.created_at.isoformat(),
                    record.provider,
                    record.agent_model,
                    record.language,
                    record.task_type,
                    record.prompt_chars,
                    record.prior_message_count,
                    int(record.depends_on_prior_context),
                    int(record.verification_requested),
                    metrics,
                    record.commentary_state,
                    record.commentary_model_alias,
                    record.prompt_fingerprint,
                ),
            )
            connection.commit()

    def list(self, *, limit: int, offset: int) -> tuple[PromptCheckRecord, ...]:
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            rows = connection.execute(
                "SELECT * FROM prompt_checks ORDER BY created_at DESC, check_id LIMIT ? OFFSET ?",
                (max(1, min(limit, 500)), max(0, offset)),
            ).fetchall()
        return tuple(_record(row) for row in rows)

    def get(self, check_id: str) -> PromptCheckRecord | None:
        if PSEUDONYM_PATTERN.fullmatch(check_id) is None:
            return None
        self._ensure_initialized()
        with self._connection(readonly=True) as connection:
            row = connection.execute("SELECT * FROM prompt_checks WHERE check_id = ?", (check_id,)).fetchone()
        return _record(row) if row is not None else None


def _record(row: sqlite3.Row) -> PromptCheckRecord:
    metrics = tuple(PromptMetricReading.model_validate(item) for item in json.loads(row["metrics_json"]))
    return PromptCheckRecord(
        check_id=row["check_id"],
        created_at=datetime.fromisoformat(row["created_at"]),
        provider=row["provider"],
        agent_model=row["agent_model"],
        language=row["language"],
        task_type=row["task_type"],
        prompt_chars=int(row["prompt_chars"]),
        prior_message_count=int(row["prior_message_count"]),
        depends_on_prior_context=bool(row["depends_on_prior_context"]),
        verification_requested=bool(row["verification_requested"]),
        metrics=metrics,
        commentary_state=row["commentary_state"],
        commentary_model_alias=row["commentary_model_alias"],
        prompt_fingerprint=row["prompt_fingerprint"],
    )


__all__ = ("SqlitePromptCheckRepository",)
