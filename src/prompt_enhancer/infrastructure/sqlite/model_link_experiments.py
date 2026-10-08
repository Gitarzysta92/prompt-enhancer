"""SQLite adapter for content-free local model-link experiments."""

from __future__ import annotations

from collections.abc import Callable

from ...application.analysis.model_link_experiments import (
    MODEL_LINK_EXPERIMENT_KEY,
    MODEL_LINK_EXPERIMENT_VERSION,
    ModelExperimentDevice,
    ModelLinkAnnotationLabel,
    ModelLinkAnnotationRecord,
    ModelLinkCandidateKind,
    ModelLinkExperimentRepository,
    ModelLinkModelIdentity,
    ModelLinkRecommendation,
    ModelLinkRunRecord,
    ModelLinkStoredExperiment,
    ModelLinkStoredLink,
)
from ...database import DatabaseInvariantError
from ...domain import Provider
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


class SqliteModelLinkExperimentRepository(ModelLinkExperimentRepository):
    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized

    def save_completed(
        self,
        run: ModelLinkRunRecord,
        links: tuple[ModelLinkStoredLink, ...],
    ) -> None:
        self._ensure_initialized()
        if (
            run.experiment_key != MODEL_LINK_EXPERIMENT_KEY
            or run.experiment_version != MODEL_LINK_EXPERIMENT_VERSION
            or len(links) != run.link_count
            or any(link.run_id != run.run_id for link in links)
        ):
            raise DatabaseInvariantError("model-link experiment is inconsistent")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                session = connection.execute(
                    "SELECT provider FROM sessions WHERE session_id = ?",
                    (run.session_id,),
                ).fetchone()
                if session is None or session["provider"] != run.provider.value:
                    raise DatabaseInvariantError(
                        "model-link target does not match an indexed session"
                    )
                connection.execute(
                    """
                    INSERT INTO session_model_link_runs(
                        run_id, session_id, request_fingerprint, input_fingerprint,
                        experiment_key, experiment_version, provider, provider_version,
                        adapter_version, source_schema_version, content_schema_version,
                        redactor_version, consent_policy_version, resolved_device,
                        qwen_model_key, qwen_repository_id, qwen_revision, qwen_license,
                        qwen_tokenizer_id, qwen_backend_key, bge_model_key,
                        bge_repository_id, bge_revision, bge_license,
                        bge_tokenizer_id, bge_backend_key, query_count, link_count,
                        agreement_count, started_at, finished_at, local_only
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1
                    )
                    """,
                    (
                        run.run_id,
                        run.session_id,
                        run.request_fingerprint,
                        run.input_fingerprint,
                        run.experiment_key,
                        run.experiment_version,
                        run.provider.value,
                        run.provider_version,
                        run.adapter_version,
                        run.source_schema_version,
                        run.content_schema_version,
                        run.redactor_version,
                        run.consent_policy_version,
                        run.resolved_device.value,
                        run.qwen_model.key,
                        run.qwen_model.repository_id,
                        run.qwen_model.revision,
                        run.qwen_model.license_spdx,
                        run.qwen_model.tokenizer_id,
                        run.qwen_model.backend_key,
                        run.bge_model.key,
                        run.bge_model.repository_id,
                        run.bge_model.revision,
                        run.bge_model.license_spdx,
                        run.bge_model.tokenizer_id,
                        run.bge_model.backend_key,
                        run.query_count,
                        run.link_count,
                        run.agreement_count,
                        to_iso(run.started_at),
                        to_iso(run.finished_at),
                    ),
                )
                connection.executemany(
                    """
                    INSERT INTO session_model_links(
                        run_id, link_id, query_message_id, candidate_message_id,
                        query_sequence, candidate_sequence, candidate_kind,
                        qwen_score, qwen_rank, bge_score, bge_rank, recommended_by
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        (
                            link.run_id,
                            link.link_id,
                            link.query_message_id,
                            link.candidate_message_id,
                            link.query_sequence,
                            link.candidate_sequence,
                            link.candidate_kind.value,
                            link.qwen_score,
                            link.qwen_rank,
                            link.bge_score,
                            link.bge_rank,
                            link.recommended_by.value,
                        )
                        for link in links
                    ),
                )
                connection.commit()
            except Exception:
                connection.rollback()
                raise

    def get(self, run_id: str) -> ModelLinkStoredExperiment | None:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT * FROM session_model_link_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                return None
            return self._hydrate(connection, row)

    def get_latest(self, session_id: str) -> ModelLinkStoredExperiment | None:
        self._ensure_initialized()
        require_safe_id(session_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """
                SELECT * FROM session_model_link_runs
                WHERE session_id = ?
                ORDER BY finished_at DESC, run_id DESC
                LIMIT 1
                """,
                (session_id,),
            ).fetchone()
            if row is None:
                return None
            return self._hydrate(connection, row)

    def append_annotation(
        self,
        annotation: ModelLinkAnnotationRecord,
        *,
        expected_revision: int,
    ) -> bool:
        self._ensure_initialized()
        if isinstance(expected_revision, bool) or expected_revision < 0:
            raise ValueError("expected annotation revision is invalid")
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                link = connection.execute(
                    """
                    SELECT 1 FROM session_model_links
                    WHERE run_id = ? AND link_id = ?
                    """,
                    (annotation.run_id, annotation.link_id),
                ).fetchone()
                if link is None:
                    connection.rollback()
                    return False
                current = int(
                    connection.execute(
                        """
                        SELECT COALESCE(MAX(revision), 0)
                        FROM session_model_link_annotations
                        WHERE run_id = ? AND link_id = ?
                        """,
                        (annotation.run_id, annotation.link_id),
                    ).fetchone()[0]
                )
                if current != expected_revision or annotation.revision != current + 1:
                    connection.rollback()
                    return False
                connection.execute(
                    """
                    INSERT INTO session_model_link_annotations(
                        run_id, link_id, revision, label, annotated_at
                    ) VALUES (?, ?, ?, ?, ?)
                    """,
                    (
                        annotation.run_id,
                        annotation.link_id,
                        annotation.revision,
                        annotation.label.value,
                        to_iso(annotation.annotated_at),
                    ),
                )
                connection.commit()
                return True
            except Exception:
                connection.rollback()
                raise

    def delete_for_privacy(self, run_id: str) -> bool:
        self._ensure_initialized()
        require_safe_id(run_id)
        with self._connection_scope() as connection:
            try:
                connection.execute("BEGIN IMMEDIATE")
                deleted = connection.execute(
                    "DELETE FROM session_model_link_runs WHERE run_id = ?",
                    (run_id,),
                ).rowcount
                connection.commit()
                return bool(deleted)
            except Exception:
                connection.rollback()
                raise

    @staticmethod
    def _identity(row, prefix: str) -> ModelLinkModelIdentity:
        return ModelLinkModelIdentity(
            key=row[f"{prefix}_model_key"],
            repository_id=row[f"{prefix}_repository_id"],
            revision=row[f"{prefix}_revision"],
            license_spdx=row[f"{prefix}_license"],
            tokenizer_id=row[f"{prefix}_tokenizer_id"],
            backend_key=row[f"{prefix}_backend_key"],
        )

    def _hydrate(self, connection, row) -> ModelLinkStoredExperiment:
        run = ModelLinkRunRecord(
            run_id=row["run_id"],
            session_id=row["session_id"],
            request_fingerprint=row["request_fingerprint"],
            input_fingerprint=row["input_fingerprint"],
            experiment_key=row["experiment_key"],
            experiment_version=row["experiment_version"],
            provider=Provider(row["provider"]),
            provider_version=row["provider_version"],
            adapter_version=row["adapter_version"],
            source_schema_version=row["source_schema_version"],
            content_schema_version=row["content_schema_version"],
            redactor_version=row["redactor_version"],
            consent_policy_version=row["consent_policy_version"],
            resolved_device=ModelExperimentDevice(row["resolved_device"]),
            qwen_model=self._identity(row, "qwen"),
            bge_model=self._identity(row, "bge"),
            query_count=row["query_count"],
            link_count=row["link_count"],
            agreement_count=row["agreement_count"],
            started_at=from_iso(row["started_at"]),
            finished_at=from_iso(row["finished_at"]),
            local_only=bool(row["local_only"]),
        )
        link_rows = connection.execute(
            """
            SELECT * FROM session_model_links
            WHERE run_id = ?
            ORDER BY query_sequence, candidate_sequence, link_id
            """,
            (run.run_id,),
        ).fetchall()
        links = tuple(
            ModelLinkStoredLink(
                run_id=item["run_id"],
                link_id=item["link_id"],
                query_message_id=item["query_message_id"],
                candidate_message_id=item["candidate_message_id"],
                query_sequence=item["query_sequence"],
                candidate_sequence=item["candidate_sequence"],
                candidate_kind=ModelLinkCandidateKind(item["candidate_kind"]),
                qwen_score=item["qwen_score"],
                qwen_rank=item["qwen_rank"],
                bge_score=item["bge_score"],
                bge_rank=item["bge_rank"],
                recommended_by=ModelLinkRecommendation(item["recommended_by"]),
            )
            for item in link_rows
        )
        annotation_rows = connection.execute(
            """
            SELECT * FROM session_model_link_annotations
            WHERE run_id = ?
            ORDER BY link_id, revision
            """,
            (run.run_id,),
        ).fetchall()
        annotations = tuple(
            ModelLinkAnnotationRecord(
                run_id=item["run_id"],
                link_id=item["link_id"],
                revision=item["revision"],
                label=ModelLinkAnnotationLabel(item["label"]),
                annotated_at=from_iso(item["annotated_at"]),
            )
            for item in annotation_rows
        )
        return ModelLinkStoredExperiment(run=run, links=links, annotations=annotations)
