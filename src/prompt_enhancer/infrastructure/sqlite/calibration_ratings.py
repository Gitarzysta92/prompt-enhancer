"""SQLite persistence for the frozen calibration sample and blind ratings."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
import sqlite3

from ...application.analysis.calibration_ratings import (
    CALIBRATION_RATING_VERSION,
    LEGACY_CALIBRATION_RATING_VERSION,
    CalibrationRating,
    CalibrationSample,
    CalibrationSampleMember,
    RatingLabel,
)
from ...application.analysis.calibration_cases import CalibrationCaseIdentity
from ...domain import Provider
from ._common import from_iso, require_utc, to_iso


class SqliteCalibrationRatingRepository:
    def __init__(
        self,
        connection_scope: Callable[..., AbstractContextManager[sqlite3.Connection]],
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def get_sample(self) -> CalibrationSample | None:
        self._ensure_initialized()
        with self._connection_scope(readonly=True) as connection:
            root = connection.execute(
                "SELECT sample_id, sample_version, created_at, target_size FROM calibration_samples ORDER BY created_at LIMIT 1"
            ).fetchone()
            if root is None:
                return None
            members = connection.execute(
                """
                SELECT m.position, m.session_id, m.provider, s.project_id,
                       COALESCE(pdl.manual_value, pdl.provider_value, p.display_name) AS project_display_name,
                       COALESCE(sdl.manual_value, sdl.provider_value, s.display_name) AS session_display_name,
                       s.started_at
                FROM calibration_sample_members m
                LEFT JOIN sessions s ON s.session_id = m.session_id
                LEFT JOIN projects p ON p.project_id = s.project_id
                LEFT JOIN project_display_labels pdl ON pdl.project_id = s.project_id
                LEFT JOIN session_display_labels sdl ON sdl.session_id = s.session_id
                WHERE m.sample_id = ?
                ORDER BY m.position
                """,
                (root["sample_id"],),
            ).fetchall()
        return CalibrationSample(
            sample_id=root["sample_id"],
            sample_version=root["sample_version"],
            created_at=require_utc(from_iso(root["created_at"])),
            target_size=int(root["target_size"]),
            members=tuple(
                CalibrationSampleMember(
                    position=int(row["position"]),
                    session_id=row["session_id"],
                    provider=Provider(row["provider"]),
                    project_id=row["project_id"] or "0" * 64,
                    project_display_name=row["project_display_name"],
                    session_display_name=row["session_display_name"],
                    started_at=from_iso(row["started_at"]) if row["started_at"] else None,
                )
                for row in members
            ),
        )

    def create_sample(self, sample: CalibrationSample) -> None:
        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT 1 FROM calibration_samples LIMIT 1").fetchone() is not None:
                    connection.rollback()
                    return
                connection.execute(
                    "INSERT INTO calibration_samples(sample_id, sample_version, created_at, target_size) VALUES (?, ?, ?, ?)",
                    (sample.sample_id, sample.sample_version, to_iso(require_utc(sample.created_at)), sample.target_size),
                )
                connection.executemany(
                    "INSERT INTO calibration_sample_members(sample_id, position, session_id, provider) VALUES (?, ?, ?, ?)",
                    [(sample.sample_id, member.position, member.session_id, member.provider.value) for member in sample.members],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def replace_sample(self, sample: CalibrationSample) -> None:
        """Replace an under-filled sample; only legal while no rating exists."""

        self._ensure_initialized()
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                if connection.execute("SELECT 1 FROM calibration_ratings LIMIT 1").fetchone() is not None:
                    connection.rollback()
                    raise ValueError("calibration sample cannot change once ratings exist")
                connection.execute("DELETE FROM calibration_sample_members")
                connection.execute("DELETE FROM calibration_samples")
                connection.execute(
                    "INSERT INTO calibration_samples(sample_id, sample_version, created_at, target_size) VALUES (?, ?, ?, ?)",
                    (sample.sample_id, sample.sample_version, to_iso(require_utc(sample.created_at)), sample.target_size),
                )
                connection.executemany(
                    "INSERT INTO calibration_sample_members(sample_id, position, session_id, provider) VALUES (?, ?, ?, ?)",
                    [(sample.sample_id, member.position, member.session_id, member.provider.value) for member in sample.members],
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def upsert_rating(
        self,
        *,
        rater_id: str,
        session_id: str,
        metric_key: str,
        label: RatingLabel,
        rated_at: datetime,
    ) -> CalibrationRating:
        return self.upsert_ratings(
            rater_id=rater_id, session_id=session_id, labels={metric_key: label}, rated_at=rated_at,
        )[0]

    def upsert_ratings(
        self, *, rater_id: str, session_id: str, labels: dict[str, RatingLabel],
        rated_at: datetime, case: CalibrationCaseIdentity | None = None,
    ) -> tuple[CalibrationRating, ...]:
        if not labels or (case is not None and case.session_id != session_id):
            raise ValueError("calibration_rating_case_mismatch")
        self._ensure_initialized()
        stamp = to_iso(require_utc(rated_at))
        provenance = {
            "rating_version": CALIBRATION_RATING_VERSION if case else LEGACY_CALIBRATION_RATING_VERSION,
            "case_fingerprint": case.case_fingerprint if case else None,
            "case_version": case.case_version if case else None,
            "window_fingerprint": case.window_fingerprint if case else None,
        }
        saved: list[CalibrationRating] = []
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                for metric_key, label in labels.items():
                    existing = connection.execute(
                        "SELECT revision FROM calibration_ratings WHERE rater_id = ? AND session_id = ? AND metric_key = ?",
                        (rater_id, session_id, metric_key),
                    ).fetchone()
                    revision = 1 if existing is None else int(existing["revision"]) + 1
                    rating = CalibrationRating(
                        rater_id=rater_id, session_id=session_id, metric_key=metric_key,
                        label=label, rated_at=require_utc(rated_at), revision=revision, **provenance,
                    )
                    connection.execute(
                        """
                        INSERT INTO calibration_ratings(
                            rater_id, session_id, metric_key, label, rating_version, rated_at, revision,
                            case_fingerprint, case_version, window_fingerprint
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        ON CONFLICT(rater_id, session_id, metric_key) DO UPDATE SET
                            label = excluded.label,
                            rating_version = excluded.rating_version,
                            rated_at = excluded.rated_at,
                            revision = excluded.revision,
                            case_fingerprint = excluded.case_fingerprint,
                            case_version = excluded.case_version,
                            window_fingerprint = excluded.window_fingerprint
                        """,
                        (rater_id, session_id, metric_key, rating.label.value, rating.rating_version, stamp, revision,
                         rating.case_fingerprint, rating.case_version, rating.window_fingerprint),
                    )
                    saved.append(rating)
                connection.commit()
            except Exception:
                connection.rollback()
                raise
        return tuple(saved)

    def list_ratings(
        self, *, rater_id: str | None = None, session_id: str | None = None
    ) -> tuple[CalibrationRating, ...]:
        self._ensure_initialized()
        filters: list[str] = []
        parameters: list[object] = []
        if rater_id is not None:
            filters.append("rater_id = ?")
            parameters.append(rater_id)
        if session_id is not None:
            filters.append("session_id = ?")
            parameters.append(session_id)
        where = f"WHERE {' AND '.join(filters)}" if filters else ""
        with self._connection_scope(readonly=True) as connection:
            rows = connection.execute(
                f"SELECT rater_id, session_id, metric_key, label, rated_at, revision, rating_version, case_fingerprint, case_version, window_fingerprint FROM calibration_ratings {where} ORDER BY rated_at, session_id, metric_key",
                tuple(parameters),
            ).fetchall()
        return tuple(
            CalibrationRating(
                rater_id=row["rater_id"],
                session_id=row["session_id"],
                metric_key=row["metric_key"],
                label=RatingLabel(row["label"]),
                rated_at=require_utc(from_iso(row["rated_at"])),
                revision=int(row["revision"]),
                rating_version=row["rating_version"],
                case_fingerprint=row["case_fingerprint"],
                case_version=row["case_version"],
                window_fingerprint=row["window_fingerprint"],
            )
            for row in rows
        )


__all__ = ("SqliteCalibrationRatingRepository",)
