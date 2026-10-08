"""SQLite persistence for model-judge judgments (labels only)."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
import sqlite3

from ...application.analysis.calibration_ratings import RatingLabel
from ...application.analysis.model_judge import (
    ZERO_WINDOW_FINGERPRINT,
    ModelJudgment,
    rehydrate_persisted_judgment,
)
from ._common import from_iso, require_utc, to_iso


class SqliteModelJudgmentRepository:
    def __init__(
        self,
        connection_scope: Callable[..., AbstractContextManager[sqlite3.Connection]],
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def upsert(self, judgment: ModelJudgment) -> None:
        # A legacy row rehydrated through the read path can still carry the
        # reserved fingerprint; it must never be written back out as if it were
        # provenance a source had sealed.
        if judgment.window_fingerprint == ZERO_WINDOW_FINGERPRINT:
            raise ValueError("refusing to persist the reserved all-zero window_fingerprint")
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    """
                    INSERT INTO model_judgments(session_id, metric_key, model_alias, label, model_identity, prompt_version, window_fingerprint, judged_at, case_fingerprint, case_version)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(session_id, metric_key, model_alias) DO UPDATE SET
                        label = excluded.label,
                        model_identity = excluded.model_identity,
                        prompt_version = excluded.prompt_version,
                        window_fingerprint = excluded.window_fingerprint,
                        judged_at = excluded.judged_at,
                        case_fingerprint = excluded.case_fingerprint,
                        case_version = excluded.case_version
                    """,
                    (
                        judgment.session_id, judgment.metric_key, judgment.model_alias, judgment.label.value,
                        judgment.model_identity, judgment.prompt_version, judgment.window_fingerprint,
                        to_iso(require_utc(judgment.judged_at)),
                        judgment.case_fingerprint, judgment.case_version,
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def list(self, *, session_id: str | None = None, model_alias: str | None = None) -> tuple[ModelJudgment, ...]:
        self._ensure_initialized()
        filters: list[str] = []
        parameters: list[object] = []
        if session_id is not None:
            filters.append("session_id = ?")
            parameters.append(session_id)
        if model_alias is not None:
            filters.append("model_alias = ?")
            parameters.append(model_alias)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                f"SELECT session_id, metric_key, model_alias, label, model_identity, prompt_version, window_fingerprint, judged_at, case_fingerprint, case_version FROM model_judgments {where} ORDER BY judged_at, session_id, metric_key",
                tuple(parameters),
            ).fetchall()
        # Rows written before the annotation surfaces recorded the sealed
        # fingerprint hold the reserved all-zero value; they stay readable and
        # keep that value, so absent provenance stays visible instead of healed.
        return tuple(
            rehydrate_persisted_judgment(
                {
                    "session_id": row["session_id"], "metric_key": row["metric_key"], "model_alias": row["model_alias"],
                    "label": RatingLabel(row["label"]), "model_identity": row["model_identity"], "prompt_version": row["prompt_version"],
                    "window_fingerprint": row["window_fingerprint"], "judged_at": require_utc(from_iso(row["judged_at"])),
                    "case_fingerprint": row["case_fingerprint"], "case_version": row["case_version"],
                }
            )
            for row in rows
        )


__all__ = ("SqliteModelJudgmentRepository",)
