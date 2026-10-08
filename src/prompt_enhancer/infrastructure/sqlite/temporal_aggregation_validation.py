"""SQLite repository for bounded synthetic aggregation graph validation.

The adapter enumerates only repository-sealed V22 comparison strata and
persists normalized, content-free lineage.  It never stores aggregate values
or exposes a snapshot/materialization surface.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
import re
import sqlite3
from typing import Protocol

from ...application.history.aggregation import (
    MAX_SUPPLIED_STRATA,
    draft_repository_sealed_synthetic_raw_aggregation,
)
from ...application.history.aggregation_persistence import (
    SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT,
    RepositorySealedSyntheticAggregationValidationV1,
    SyntheticAggregationCollectionEnumerationReceiptV1,
    SyntheticAggregationCollectionPredicateV1,
)
from ...application.history.contracts import TemporalWindowKind, TemporalWindowSpec
from ...database import DatabaseInvariantError
from ._common import ConnectionScope, require_safe_id
from .temporal_comparison_strata import SqliteTemporalComparisonStratumRepository
from .temporal_history import _from_us, _to_us


ADAPTER_VERSION = "sqlite-synthetic-aggregation-validation-v1"
SCHEMA_VERSION = 23
_SAFE_METRIC = re.compile(r"^[a-z][a-z0-9._-]{0,127}$")


class BeginAppendAuthorization(Protocol):
    def __call__(self, *values: object) -> tuple[str, str]: ...


class EndAppendAuthorization(Protocol):
    def __call__(
        self,
        operation_id: str,
        authorization_fingerprint: str,
        tag: str,
    ) -> None: ...


class BeginDeleteAuthorization(Protocol):
    def __call__(
        self,
        operation_id: str,
        validation_receipt_id: str,
        cause_kind: str,
        cause_id: str,
        validation_fingerprint: str,
        authorization_fingerprint: str,
    ) -> str: ...


def _canonical_digest(role: str, payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            {"role": role, "payload": payload},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("ascii", errors="strict")
    ).hexdigest()


def _request_fingerprint(
    anchor_sealed_stratum_id: str,
    metric_key: str,
    window: TemporalWindowSpec,
) -> str:
    return _canonical_digest(
        "synthetic-aggregation-validation-request-v1",
        {
            "anchor_sealed_stratum_id": anchor_sealed_stratum_id,
            "metric_key": metric_key,
            "window": window.model_dump(mode="json"),
        },
    )


def _checked_metric(value: str) -> str:
    if _SAFE_METRIC.fullmatch(value) is None or ".." in value:
        raise ValueError("metric key must be a path-free content code")
    return value


def _checked_window(value: TemporalWindowSpec) -> TemporalWindowSpec:
    if not isinstance(value, TemporalWindowSpec):
        raise ValueError("window must be a temporal window specification")
    return TemporalWindowSpec.model_validate(value.model_dump(mode="python"))


def _checked_clock(value: datetime) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.utcoffset() != timedelta(0)
    ):
        raise DatabaseInvariantError(
            "synthetic aggregation clock must return canonical UTC"
        )
    return value.astimezone(UTC)


def _window_from_row(row: sqlite3.Row) -> TemporalWindowSpec:
    try:
        kind = TemporalWindowKind(str(row["window_kind"]))
        return TemporalWindowSpec(
            kind=kind,
            window_boundary_semantics=row["window_boundary_semantics"],
            last_n=row["window_last_n"],
            days=row["window_days"],
            start_at=(
                None
                if row["window_start_at_us"] is None
                else _from_us(row["window_start_at_us"])
            ),
            end_at=(
                None
                if row["window_end_at_us"] is None
                else _from_us(row["window_end_at_us"])
            ),
        )
    except Exception:
        raise DatabaseInvariantError(
            "stored synthetic aggregation window is invalid"
        ) from None


def _root_values(
    validation: RepositorySealedSyntheticAggregationValidationV1,
    *,
    request_fingerprint: str,
) -> dict[str, object]:
    predicate = validation.predicate
    enumeration = validation.enumeration
    draft = validation.aggregation_draft
    window = predicate.window
    return {
        "schema_version": SCHEMA_VERSION,
        "adapter_version": ADAPTER_VERSION,
        "contract_version": validation.contract_version,
        "validation_fingerprint": validation.fingerprint,
        "idempotency_key_sha256": predicate.idempotency_key_sha256,
        "request_fingerprint": request_fingerprint,
        "anchor_sealed_stratum_id": validation.anchor.sealed_stratum_id,
        "anchor_sealed_stratum_fingerprint": validation.anchor.fingerprint,
        "predicate_contract_version": predicate.contract_version,
        "query_id": predicate.query_id,
        "predicate_fingerprint": predicate.fingerprint,
        "anchor_prepared_stratum_id": predicate.anchor_prepared_stratum_id,
        "anchor_prepared_stratum_fingerprint": (
            predicate.anchor_prepared_stratum_fingerprint
        ),
        "root_receipt_id": predicate.root_receipt_id,
        "root_receipt_fingerprint": predicate.root_receipt_fingerprint,
        "history_floor_at_us": _to_us(predicate.history_floor_at),
        "installation_id": predicate.installation_id,
        "project_id": predicate.project_id,
        "provider": predicate.provider.value,
        "metric_key": predicate.metric_key,
        "window_kind": window.kind.value,
        "window_boundary_semantics": window.window_boundary_semantics,
        "window_last_n": window.last_n,
        "window_days": window.days,
        "window_start_at_us": (
            None if window.start_at is None else _to_us(window.start_at)
        ),
        "window_end_at_us": None if window.end_at is None else _to_us(window.end_at),
        "as_of_us": _to_us(predicate.as_of),
        "query_predicate_version": predicate.query_predicate_version,
        "query_order_version": predicate.query_order_version,
        "maximum_member_count": predicate.maximum_member_count,
        "overflow_probe_limit": predicate.overflow_probe_limit,
        "sealed_at_inclusive": int(predicate.sealed_at_inclusive),
        "enumeration_contract_version": enumeration.contract_version,
        "enumeration_id": enumeration.enumeration_id,
        "enumeration_fingerprint": enumeration.fingerprint,
        "member_count": enumeration.member_count,
        "overflow_detected": int(enumeration.overflow_detected),
        "max_plus_one_probe_performed": int(
            enumeration.max_plus_one_probe_performed
        ),
        "query_verifier_version": enumeration.query_verifier_version,
        "query_verifier_fingerprint": enumeration.query_verifier_fingerprint,
        "aggregation_draft_contract_version": draft.contract_version,
        "aggregation_draft_id": draft.aggregation_draft_id,
        "aggregation_draft_fingerprint": draft.fingerprint,
        "policy_identity_fingerprint": draft.policy_identity_fingerprint,
        "repository_verifier_version": validation.repository_verifier_version,
        "repository_verifier_fingerprint": (
            validation.repository_verifier_fingerprint
        ),
        "sealed_at_us": _to_us(validation.sealed_at),
        "graph_fingerprint_count": len(validation.ordered_graph_fingerprints),
    }


class SqliteTemporalSyntheticAggregationValidationRepository:
    """Issue and rehydrate exact V23 synthetic collection validations."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        comparison_repository: SqliteTemporalComparisonStratumRepository,
        begin_append_authorization: BeginAppendAuthorization,
        end_append_authorization: EndAppendAuthorization,
        begin_delete_authorization: BeginDeleteAuthorization | None = None,
        end_delete_authorization: EndAppendAuthorization | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._comparison = comparison_repository
        self._begin_append_authorization = begin_append_authorization
        self._end_append_authorization = end_append_authorization
        self._begin_delete_authorization = begin_delete_authorization
        self._end_delete_authorization = end_delete_authorization
        self._clock = clock or (lambda: datetime.now(UTC))

    def _delete_for_upstream_privacy_locked(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        cause_kind: str,
        cause_id: str,
    ) -> int:
        """Delete every V23 graph touched by one live upstream capability.

        The caller owns the surrounding privacy transaction and must already
        have inserted the matching run/task authorization bearing
        ``operation_id``.  Each affected multi-input graph is deduplicated and
        removed whole before any V22 parent can be deleted.
        """

        require_safe_id(operation_id)
        require_safe_id(cause_id)
        if cause_kind == "run":
            query = """SELECT DISTINCT root.validation_receipt_id,
                                      root.validation_fingerprint
                       FROM synthetic_aggregation_validation_roots root
                       JOIN synthetic_aggregation_validation_members member
                         ON member.validation_receipt_id=root.validation_receipt_id
                       JOIN comparison_sealed_stratum_roots sealed
                         ON sealed.sealed_stratum_id=member.sealed_stratum_id
                       WHERE sealed.analysis_run_id=?
                       ORDER BY root.validation_receipt_id"""
        elif cause_kind == "task":
            query = """SELECT DISTINCT root.validation_receipt_id,
                                      root.validation_fingerprint
                       FROM synthetic_aggregation_validation_roots root
                       JOIN synthetic_aggregation_validation_members member
                         ON member.validation_receipt_id=root.validation_receipt_id
                       JOIN comparison_task_delete_authorizations upstream
                         ON upstream.operation_id=?
                        AND upstream.task_id=?
                        AND upstream.sealed_stratum_id=member.sealed_stratum_id
                       JOIN comparison_sealed_stratum_roots sealed
                         ON sealed.sealed_stratum_id=upstream.sealed_stratum_id
                        AND sealed.prepared_stratum_id=upstream.prepared_stratum_id
                        AND sealed.analysis_run_id=upstream.expected_analysis_run_id
                       ORDER BY root.validation_receipt_id"""
        else:
            raise ValueError("synthetic aggregation deletion cause is invalid")
        parameters = (
            (cause_id,) if cause_kind == "run" else (operation_id, cause_id)
        )
        rows = connection.execute(query, parameters).fetchall()
        if rows and (
            self._begin_delete_authorization is None
            or self._end_delete_authorization is None
        ):
            raise DatabaseInvariantError(
                "synthetic aggregation privacy deletion is not authorized"
            )
        deleted = 0
        for row in rows:
            validation_receipt_id = str(row["validation_receipt_id"])
            validation_fingerprint = str(row["validation_fingerprint"])
            authorization_fingerprint = _canonical_digest(
                "synthetic-aggregation-delete-authorization-v1",
                {
                    "cause_id": cause_id,
                    "cause_kind": cause_kind,
                    "operation_id": operation_id,
                    "validation_fingerprint": validation_fingerprint,
                    "validation_receipt_id": validation_receipt_id,
                },
            )
            assert self._begin_delete_authorization is not None
            assert self._end_delete_authorization is not None
            tag = self._begin_delete_authorization(
                operation_id,
                validation_receipt_id,
                cause_kind,
                cause_id,
                validation_fingerprint,
                authorization_fingerprint,
            )
            authorization = (operation_id, authorization_fingerprint, tag)
            try:
                connection.execute(
                    """INSERT INTO synthetic_aggregation_delete_authorizations
                       (operation_id,validation_receipt_id,cause_kind,cause_id,
                        validation_fingerprint,authorization_fingerprint,
                        authorization_tag)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        operation_id,
                        validation_receipt_id,
                        cause_kind,
                        cause_id,
                        validation_fingerprint,
                        authorization_fingerprint,
                        tag,
                    ),
                )
                cursor = connection.execute(
                    """DELETE FROM synthetic_aggregation_validation_roots
                       WHERE validation_receipt_id=?""",
                    (validation_receipt_id,),
                )
                if cursor.rowcount != 1:
                    raise DatabaseInvariantError(
                        "synthetic aggregation privacy target disappeared"
                    )
                connection.execute(
                    """DELETE FROM synthetic_aggregation_delete_authorizations
                       WHERE operation_id=?""",
                    (operation_id,),
                )
                deleted += 1
            finally:
                self._end_delete_authorization(*authorization)
        return deleted

    def validate_synthetic_aggregation(
        self,
        anchor_sealed_stratum_id: str,
        metric_key: str,
        window: TemporalWindowSpec,
        *,
        idempotency_key_sha256: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1:
        self._ensure_initialized()
        anchor_id = require_safe_id(anchor_sealed_stratum_id)
        key = require_safe_id(idempotency_key_sha256)
        metric = _checked_metric(metric_key)
        checked_window = _checked_window(window)
        request_fingerprint = _request_fingerprint(
            anchor_id, metric, checked_window
        )
        with self._connection_scope() as connection:
            authorization: tuple[str, str, str] | None = None
            try:
                connection.execute("PRAGMA trusted_schema=ON")
                connection.execute("BEGIN IMMEDIATE")
                replay = connection.execute(
                    """SELECT validation_receipt_id,request_fingerprint
                       FROM synthetic_aggregation_validation_roots
                       WHERE idempotency_key_sha256=?""",
                    (key,),
                ).fetchone()
                if replay is not None:
                    if replay["request_fingerprint"] != request_fingerprint:
                        raise DatabaseInvariantError(
                            "synthetic aggregation idempotency key conflicts"
                        )
                    result = self._hydrate_locked(
                        connection, str(replay["validation_receipt_id"])
                    )
                    connection.commit()
                    connection.execute("PRAGMA trusted_schema=OFF")
                    return result

                anchor = self._comparison._hydrate_sealed_locked(
                    connection, anchor_id
                )
                if metric not in (
                    anchor.prepared_receipt.prepared_scope.selection_revision.selected_metric_keys
                ):
                    raise DatabaseInvariantError(
                        "synthetic aggregation metric is not selected by the anchor"
                    )
                as_of = _checked_clock(self._clock())
                if as_of < anchor.sealed_at:
                    raise DatabaseInvariantError(
                        "synthetic aggregation clock predates the anchor seal"
                    )
                root = anchor.prepared_receipt.prepared_scope.history_root
                dimensions = anchor.prepared_receipt.dimensions
                rows = connection.execute(
                    """SELECT sealed.sealed_stratum_id
                       FROM comparison_sealed_stratum_roots sealed
                       JOIN comparison_prepared_stratum_roots prepared
                         ON prepared.prepared_stratum_id=sealed.prepared_stratum_id
                       JOIN temporal_prepared_scope_roots scope
                         ON scope.prepared_scope_id=prepared.prepared_scope_id
                       JOIN temporal_history_root_drafts history
                         ON history.root_receipt_id=scope.root_receipt_id
                       JOIN temporal_sealed_batch_roots batch
                         ON batch.sealed_batch_id=sealed.sealed_batch_id
                       JOIN temporal_session_revisions revision
                         ON revision.completion_request_id=batch.completion_request_id
                       WHERE history.root_receipt_id=?
                         AND history.root_fingerprint=?
                         AND history.history_floor_at_us=?
                         AND history.project_id=?
                         AND prepared.installation_id=?
                         AND prepared.project_id=?
                         AND prepared.session_provider='synthetic'
                         AND sealed.sealed_at_us<=?
                       ORDER BY revision.effective_at_us,revision.session_id,
                                revision.revision_ordinal,revision.revision_id,
                                sealed.sealed_stratum_id
                       LIMIT ?""",
                    (
                        root.root_receipt_id,
                        root.fingerprint,
                        _to_us(root.history_floor_at),
                        dimensions.project_id,
                        dimensions.installation_id,
                        dimensions.project_id,
                        _to_us(as_of),
                        SYNTHETIC_AGGREGATION_OVERFLOW_PROBE_LIMIT,
                    ),
                ).fetchall()
                if len(rows) > MAX_SUPPLIED_STRATA:
                    raise DatabaseInvariantError(
                        "synthetic aggregation collection exceeds its bound"
                    )
                strata = tuple(
                    self._comparison._hydrate_sealed_locked(
                        connection, str(row["sealed_stratum_id"])
                    )
                    for row in rows
                )
                draft = draft_repository_sealed_synthetic_raw_aggregation(
                    anchor=anchor.prepared_receipt,
                    metric_key=metric,
                    window=checked_window,
                    as_of=as_of,
                    strata=strata,
                )
                predicate = SyntheticAggregationCollectionPredicateV1.from_repository_query(
                    idempotency_key_sha256=key,
                    anchor=anchor,
                    metric_key=metric,
                    window=checked_window,
                    as_of=as_of,
                )
                members = draft.ordered_supplied_stratum_manifest
                enumeration = SyntheticAggregationCollectionEnumerationReceiptV1(
                    enumeration_id=(
                        SyntheticAggregationCollectionEnumerationReceiptV1.enumeration_id_for(
                            predicate=predicate,
                            ordered_members=members,
                        )
                    ),
                    predicate=predicate,
                    predicate_fingerprint=predicate.fingerprint,
                    ordered_members=members,
                    member_count=len(members),
                )
                graph = RepositorySealedSyntheticAggregationValidationV1.ordered_graph_for(
                    anchor=anchor,
                    predicate=predicate,
                    enumeration=enumeration,
                    aggregation_draft=draft,
                )
                receipt_id = RepositorySealedSyntheticAggregationValidationV1.validation_receipt_id_for(
                    anchor=anchor,
                    predicate=predicate,
                    enumeration=enumeration,
                    aggregation_draft=draft,
                    sealed_at=as_of,
                )
                validation = RepositorySealedSyntheticAggregationValidationV1(
                    validation_receipt_id=receipt_id,
                    anchor=anchor,
                    predicate=predicate,
                    enumeration=enumeration,
                    aggregation_draft=draft,
                    aggregation_draft_fingerprint=draft.fingerprint,
                    ordered_graph_fingerprints=graph,
                    sealed_at=as_of,
                )
                authorization = self._insert_locked(
                    connection,
                    validation,
                    request_fingerprint=request_fingerprint,
                )
                verified = self._hydrate_locked(connection, receipt_id)
                if verified != validation:
                    raise DatabaseInvariantError(
                        "stored synthetic aggregation validation differs"
                    )
                connection.commit()
                connection.execute("PRAGMA trusted_schema=OFF")
                return verified
            except DatabaseInvariantError:
                connection.rollback()
                connection.execute("PRAGMA trusted_schema=OFF")
                raise
            except Exception:
                connection.rollback()
                connection.execute("PRAGMA trusted_schema=OFF")
                raise DatabaseInvariantError(
                    "synthetic aggregation validation failed"
                ) from None
            finally:
                if authorization is not None:
                    self._end_append_authorization(*authorization)

    def _insert_locked(
        self,
        connection: sqlite3.Connection,
        validation: RepositorySealedSyntheticAggregationValidationV1,
        *,
        request_fingerprint: str,
    ) -> tuple[str, str, str]:
        values = _root_values(validation, request_fingerprint=request_fingerprint)
        authorization_fingerprint = _canonical_digest(
            "synthetic-aggregation-append-authorization-v1",
            {
                "validation_receipt_id": validation.validation_receipt_id,
                **values,
            },
        )
        lineage = (
            validation.validation_receipt_id,
            validation.predicate.idempotency_key_sha256,
            request_fingerprint,
            validation.anchor.sealed_stratum_id,
            validation.predicate.query_id,
            validation.predicate.fingerprint,
            validation.enumeration.enumeration_id,
            validation.enumeration.fingerprint,
            validation.aggregation_draft.aggregation_draft_id,
            validation.aggregation_draft.fingerprint,
            validation.fingerprint,
            validation.enumeration.member_count,
            len(validation.ordered_graph_fingerprints),
            _to_us(validation.predicate.as_of),
            _to_us(validation.sealed_at),
            authorization_fingerprint,
        )
        operation_id, tag = self._begin_append_authorization(*lineage)
        authorization = (operation_id, authorization_fingerprint, tag)
        try:
            connection.execute(
                """INSERT INTO synthetic_aggregation_append_authorizations
                   VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (operation_id, *lineage, tag),
            )
            for member in validation.enumeration.ordered_members:
                connection.execute(
                    """INSERT INTO synthetic_aggregation_validation_members
                       (validation_receipt_id,operation_id,ordinal,
                        sealed_stratum_id,disposition,member_fingerprint)
                       VALUES(?,?,?,?,?,?)""",
                    (
                        validation.validation_receipt_id,
                        operation_id,
                        member.supplied_ordinal,
                        member.sealed_stratum_id,
                        member.disposition.value,
                        member.fingerprint,
                    ),
                )
            for ordinal, fingerprint in enumerate(
                validation.ordered_graph_fingerprints
            ):
                connection.execute(
                    """INSERT INTO
                       synthetic_aggregation_validation_graph_commitments
                       (validation_receipt_id,operation_id,ordinal,fingerprint)
                       VALUES(?,?,?,?)""",
                    (
                        validation.validation_receipt_id,
                        operation_id,
                        ordinal,
                        fingerprint,
                    ),
                )
            columns = ("validation_receipt_id", "operation_id", *values.keys())
            connection.execute(
                f"""INSERT INTO synthetic_aggregation_validation_roots
                    ({','.join(columns)})
                    VALUES({','.join('?' for _ in columns)})""",
                (
                    validation.validation_receipt_id,
                    operation_id,
                    *values.values(),
                ),
            )
            connection.execute(
                """DELETE FROM synthetic_aggregation_append_authorizations
                   WHERE operation_id=?""",
                (operation_id,),
            )
            return authorization
        except Exception:
            self._end_append_authorization(*authorization)
            raise

    def _hydrate_locked(
        self,
        connection: sqlite3.Connection,
        validation_receipt_id: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1:
        row = connection.execute(
            """SELECT * FROM synthetic_aggregation_validation_roots
               WHERE validation_receipt_id=?""",
            (validation_receipt_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError(
                "stored synthetic aggregation validation is missing"
            )
        try:
            anchor = self._comparison._hydrate_sealed_locked(
                connection, str(row["anchor_sealed_stratum_id"])
            )
            window = _window_from_row(row)
            as_of = _from_us(row["as_of_us"])
            predicate = SyntheticAggregationCollectionPredicateV1.from_repository_query(
                idempotency_key_sha256=str(row["idempotency_key_sha256"]),
                anchor=anchor,
                metric_key=str(row["metric_key"]),
                window=window,
                as_of=as_of,
            )
            member_rows = connection.execute(
                """SELECT * FROM synthetic_aggregation_validation_members
                   WHERE validation_receipt_id=? ORDER BY ordinal""",
                (validation_receipt_id,),
            ).fetchall()
            if tuple(item["ordinal"] for item in member_rows) != tuple(
                range(len(member_rows))
            ):
                raise ValueError("stored member order is invalid")
            strata = tuple(
                self._comparison._hydrate_sealed_locked(
                    connection, str(item["sealed_stratum_id"])
                )
                for item in member_rows
            )
            draft = draft_repository_sealed_synthetic_raw_aggregation(
                anchor=anchor.prepared_receipt,
                metric_key=predicate.metric_key,
                window=window,
                as_of=as_of,
                strata=strata,
            )
            members = draft.ordered_supplied_stratum_manifest
            if len(member_rows) != len(members) or any(
                stored["sealed_stratum_id"] != derived.sealed_stratum_id
                or stored["disposition"] != derived.disposition.value
                or stored["member_fingerprint"] != derived.fingerprint
                for stored, derived in zip(member_rows, members, strict=True)
            ):
                raise ValueError("stored members do not exactly rederive")
            enumeration = SyntheticAggregationCollectionEnumerationReceiptV1(
                enumeration_id=(
                    SyntheticAggregationCollectionEnumerationReceiptV1.enumeration_id_for(
                        predicate=predicate,
                        ordered_members=members,
                    )
                ),
                predicate=predicate,
                predicate_fingerprint=predicate.fingerprint,
                ordered_members=members,
                member_count=len(members),
            )
            graph = RepositorySealedSyntheticAggregationValidationV1.ordered_graph_for(
                anchor=anchor,
                predicate=predicate,
                enumeration=enumeration,
                aggregation_draft=draft,
            )
            sealed_at = _from_us(row["sealed_at_us"])
            validation = RepositorySealedSyntheticAggregationValidationV1(
                validation_receipt_id=(
                    RepositorySealedSyntheticAggregationValidationV1.validation_receipt_id_for(
                        anchor=anchor,
                        predicate=predicate,
                        enumeration=enumeration,
                        aggregation_draft=draft,
                        sealed_at=sealed_at,
                    )
                ),
                anchor=anchor,
                predicate=predicate,
                enumeration=enumeration,
                aggregation_draft=draft,
                aggregation_draft_fingerprint=draft.fingerprint,
                ordered_graph_fingerprints=graph,
                sealed_at=sealed_at,
            )
            request_fingerprint = _request_fingerprint(
                anchor.sealed_stratum_id, predicate.metric_key, window
            )
            expected = _root_values(
                validation, request_fingerprint=request_fingerprint
            )
            if row["validation_receipt_id"] != validation.validation_receipt_id:
                raise ValueError("stored validation identity conflicts")
            if any(row[name] != value for name, value in expected.items()):
                raise ValueError("stored validation lineage conflicts")
            graph_rows = connection.execute(
                """SELECT ordinal,operation_id,fingerprint FROM
                   synthetic_aggregation_validation_graph_commitments
                   WHERE validation_receipt_id=? ORDER BY ordinal""",
                (validation_receipt_id,),
            ).fetchall()
            if (
                tuple(item["ordinal"] for item in graph_rows)
                != tuple(range(len(graph)))
                or tuple(str(item["fingerprint"]) for item in graph_rows) != graph
                or any(item["operation_id"] != row["operation_id"] for item in graph_rows)
                or any(item["operation_id"] != row["operation_id"] for item in member_rows)
            ):
                raise ValueError("stored validation commitments conflict")
            return RepositorySealedSyntheticAggregationValidationV1.revalidate_for_persistence(
                validation
            )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored synthetic aggregation validation failed rehydration"
            ) from None

    def get_synthetic_aggregation_validation(
        self,
        validation_receipt_id: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1 | None:
        self._ensure_initialized()
        receipt_id = require_safe_id(validation_receipt_id)
        return self._get_one(
            "validation_receipt_id", receipt_id
        )

    def get_synthetic_aggregation_validation_for_idempotency(
        self,
        idempotency_key_sha256: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1 | None:
        self._ensure_initialized()
        key = require_safe_id(idempotency_key_sha256)
        return self._get_one("idempotency_key_sha256", key)

    def _get_one(
        self,
        column: str,
        value: str,
    ) -> RepositorySealedSyntheticAggregationValidationV1 | None:
        with self._connection_scope(readonly=True) as connection:
            try:
                connection.execute("BEGIN")
                row = connection.execute(
                    f"""SELECT validation_receipt_id
                        FROM synthetic_aggregation_validation_roots
                        WHERE {column}=?""",
                    (value,),
                ).fetchone()
                if row is None:
                    connection.commit()
                    return None
                result = self._hydrate_locked(
                    connection, str(row["validation_receipt_id"])
                )
                connection.commit()
                return result
            except Exception:
                connection.rollback()
                raise


__all__ = ["ADAPTER_VERSION", "SqliteTemporalSyntheticAggregationValidationRepository"]
