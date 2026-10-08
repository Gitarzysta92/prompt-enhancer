"""SQLite-owned prospective temporal history for synthetic Coaching tests.

The public models in :mod:`prompt_enhancer.application.history.persistence`
are structural data, not write capabilities.  This adapter derives every
repository id, grant snapshot, revision, observation, and seal itself.  Its
only completion entry point is package-private and is called from the existing
session-analysis ``BEGIN IMMEDIATE`` transaction.

This first schema is deliberately source-unverified and product-ineligible.
V21 seals at most one temporal revision per session in the project epoch; that
bounded rule keeps an authorized run deletion from leaving predecessor lineage.
It accepts no legacy backfill, caller graph, product capture, comparison,
snapshot, activation, export, or sharing authority.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
import hashlib
import json
import secrets
import sqlite3
from typing import Any, Final

from ...application.analysis.coaching_baselines import (
    COACHING_METRIC_ALGORITHM_ID,
    COACHING_METRIC_ALGORITHM_VERSION,
    COACHING_METRIC_DEFINITIONS,
    COACHING_METRIC_ENGINE_VERSION,
    COACHING_METRIC_PACK_KEY,
    COACHING_METRIC_PACK_VERSION,
    COACHING_METRIC_RUBRIC_VERSION,
)
from ...application.history.coaching_identity import (
    COACHING_TEMPORAL_CATALOG_SHA256,
    COACHING_TEMPORAL_ENGINE_SHA256,
    COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
    COACHING_TEMPORAL_METRIC_KEYS,
    COACHING_TEMPORAL_PACK_SHA256,
    COACHING_TEMPORAL_PROFILE_KEY,
    COACHING_TEMPORAL_PROFILE_SHA256,
    COACHING_TEMPORAL_PROFILE_VERSION,
    CoachingTemporalIdentityCatalog,
    _SPECS as COACHING_IDENTITY_SPECS,
)
from ...application.history.contracts import (
    AnalysisInputReceiptV2,
    EvidenceCoverageEligibility,
    EvidenceCoverageState,
    FractionObservationValue,
    MetricComparisonIdentity,
    ProjectMetricSelectionAuthorityKind,
    ProjectMetricSelectionRevisionV2,
    ProjectMetricSelectionSource,
    RepositoryTemporalBatchSealDraft,
    RevisionEffectiveTimeBasis,
    SessionRevisionReceiptV3,
    TemporalHistoryRootReceipt,
    TemporalMetricObservationV2,
    TemporalObservationBatchV2,
    TemporalSelectionState,
    TemporalSourceState,
    TemporalValueState,
    TemporalTrendSpec,
    TemporalUncertainty,
)
from ...application.history.persistence import (
    RepositoryPreparedTemporalScopeV1,
    RepositorySealedTemporalBatchV1,
    SyntheticTemporalCompletionRequestV1,
    automation_grant_authority_version,
)
from ...application.persistence import (
    MetricValueState,
    SessionAnalysisCompletionAuthority,
    SessionAnalysisEvidenceRecord,
    SessionAnalysisResultRecord,
    SessionAnalysisSignalRecord,
    SessionEvidenceOrigin,
    SessionMetricAggregation,
    SessionMetricApplicability,
    SessionMetricDirection,
    SessionMetricSignalStatus,
    SESSION_ANALYSIS_RUN_SCHEMA_VERSION,
)
from ...database import DatabaseInvariantError
from ...domain import DataTier, MetricObservation, MetricSource, Provider
from ._common import ConnectionScope, from_iso, require_safe_id, to_iso


REPOSITORY_TEMPORAL_VERIFIER_VERSION: Final[str] = (
    "sqlite-temporal-history-verifier-v1"
)
REPOSITORY_TEMPORAL_VERIFIER_FINGERPRINT: Final[str] = hashlib.sha256(
    b"sqlite-temporal-history-verifier-v1:normalized-coaching-fraction-root-last"
).hexdigest()
ANALYSIS_RUN_BRIDGE_VERSION: Final[str] = "stored-session-analysis-run-bridge-v1"
GRANT_SNAPSHOT_VERSION: Final[str] = "automation-grant-v1"
COACHING_AUTOMATION_JOB_PLAN_VERSION: Final[str] = (
    f"coaching-v{COACHING_METRIC_PACK_VERSION}-"
    f"{COACHING_METRIC_ENGINE_VERSION}-{COACHING_METRIC_RUBRIC_VERSION}"
)

_UTC_MIN_US = -62_135_596_800_000_000
_UTC_MAX_US = 253_402_300_799_999_999
_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_DEFINITIONS = {item.key: item for item in COACHING_METRIC_DEFINITIONS}

BeginAuthorization = Callable[..., tuple[str, str]]
EndAuthorization = Callable[[str, str, str], None]


def _canonical_digest(payload: object) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    ).hexdigest()


def _new_id() -> str:
    return secrets.token_hex(32)


def _to_us(value: datetime) -> int:
    if value.tzinfo is None or value.utcoffset() != timedelta(0):
        raise DatabaseInvariantError("temporal timestamp is not canonical UTC")
    delta = value - _EPOCH
    micros = delta.days * 86_400_000_000 + delta.seconds * 1_000_000 + delta.microseconds
    if not _UTC_MIN_US <= micros <= _UTC_MAX_US:
        raise DatabaseInvariantError("temporal timestamp is outside the supported range")
    return micros


def _from_us(value: object) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise DatabaseInvariantError("stored temporal timestamp is invalid")
    if not _UTC_MIN_US <= value <= _UTC_MAX_US:
        raise DatabaseInvariantError("stored temporal timestamp is invalid")
    return _EPOCH + timedelta(microseconds=value)


def _from_stored_iso(value: object) -> datetime:
    """Parse one required canonical stored UTC timestamp without value leaks."""

    try:
        if not isinstance(value, str):
            raise ValueError
        parsed = from_iso(value)
        if (
            parsed is None
            or parsed.tzinfo is None
            or parsed.utcoffset() != timedelta(0)
            or to_iso(parsed) != value
        ):
            raise ValueError
        return parsed
    except Exception:
        raise DatabaseInvariantError("stored temporal timestamp is invalid") from None


def _enum(value: object) -> object:
    return getattr(value, "value", value)


def analysis_run_bridge_fingerprint(
    *,
    request_fingerprint: str,
    input_fingerprint: str,
    analysis_profile_key: str,
    analysis_profile_version: int,
    metric_pack_key: str,
    metric_pack_version: int,
    selected_metric_keys: tuple[str, ...],
    provider: str,
    provider_version: str,
    adapter_version: str,
    source_schema_version: str,
    content_schema_version: str,
    metric_engine_version: str,
    redactor_version: str,
    model_plan_fingerprint: str,
    schema_version: int,
    analysis_window_fingerprint: str,
) -> str:
    """Bridge one stored immutable run configuration to a V2 input receipt.

    The run id is deliberately a separate lineage role.  Exact reanalysis of
    one request/window may reuse this semantic fingerprint while its run id and
    full input receipt remain distinct.
    """

    return _canonical_digest(
        {
            "analysis_profile_key": analysis_profile_key,
            "analysis_profile_version": analysis_profile_version,
            "analysis_window_fingerprint": analysis_window_fingerprint,
            "bridge_version": ANALYSIS_RUN_BRIDGE_VERSION,
            "content_schema_version": content_schema_version,
            "input_fingerprint": input_fingerprint,
            "metric_engine_version": metric_engine_version,
            "metric_pack_key": metric_pack_key,
            "metric_pack_version": metric_pack_version,
            "model_plan_fingerprint": model_plan_fingerprint,
            "provider": provider,
            "provider_adapter_version": adapter_version,
            "provider_version": provider_version,
            "redactor_version": redactor_version,
            "request_fingerprint": request_fingerprint,
            "schema_version": schema_version,
            "selected_metric_keys": selected_metric_keys,
            "source_schema_version": source_schema_version,
        }
    )


class SqliteTemporalHistoryRepository:
    """Repository-owned, zero-backfill temporal graph persistence."""

    def __init__(
        self,
        connection_scope: ConnectionScope,
        ensure_initialized: Callable[[], None],
        *,
        begin_scope_authorization: BeginAuthorization,
        end_scope_authorization: EndAuthorization,
        begin_history_authorization: BeginAuthorization,
        end_history_authorization: EndAuthorization,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._connection_scope = connection_scope
        self._ensure_initialized = ensure_initialized
        self._begin_scope_authorization = begin_scope_authorization
        self._end_scope_authorization = end_scope_authorization
        self._begin_history_authorization = begin_history_authorization
        self._end_history_authorization = end_history_authorization
        self._clock = clock or (lambda: datetime.now(UTC))
        self._identity_catalog = CoachingTemporalIdentityCatalog()

    @staticmethod
    def _grant_metrics(
        connection: sqlite3.Connection, grant_id: str
    ) -> tuple[str, ...]:
        rows = connection.execute(
            """SELECT ordinal,metric_key FROM automation_grant_metrics
               WHERE grant_id=? ORDER BY ordinal""",
            (grant_id,),
        ).fetchall()
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            raise DatabaseInvariantError("automation grant metric order is invalid")
        return tuple(str(row["metric_key"]) for row in rows)

    @staticmethod
    def _grant_snapshot_payload(
        row: sqlite3.Row, metric_keys: tuple[str, ...]
    ) -> dict[str, object]:
        return {
            "check_interval_seconds": row["check_interval_seconds"],
            "contract_version": GRANT_SNAPSHOT_VERSION,
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "grant_id": row["grant_id"],
            "local_only": bool(row["local_only"]),
            "maximum_session_seconds": row["maximum_session_seconds"],
            "max_cpu_workers": row["max_cpu_workers"],
            "max_gpu_workers": row["max_gpu_workers"],
            "metric_keys": metric_keys,
            "newest_session_limit": row["newest_session_limit"],
            "pause_on_battery": bool(row["pause_on_battery"]),
            "project_id": row["project_id"],
            "provider": row["provider"],
            "remote_requires_fresh_approval": bool(
                row["remote_requires_fresh_approval"]
            ),
            "renewed_at": row["renewed_at"],
            "revision": row["revision"],
            "route": row["route"],
            "snapshot_state": row["state"],
        }

    @classmethod
    def _grant_fingerprint(
        cls, row: sqlite3.Row, metric_keys: tuple[str, ...]
    ) -> str:
        return _canonical_digest(cls._grant_snapshot_payload(row, metric_keys))

    @staticmethod
    def _validate_grant_for_prepare(
        row: sqlite3.Row | None,
        metric_keys: tuple[str, ...],
        now: datetime,
    ) -> None:
        if row is None:
            raise DatabaseInvariantError("automation grant does not exist")
        created_at = _from_stored_iso(row["created_at"])
        renewed_at = _from_stored_iso(row["renewed_at"])
        expires_at = _from_stored_iso(row["expires_at"])
        if (
            row["state"] != "active"
            or row["provider"] != Provider.SYNTHETIC.value
            or row["local_only"] != 1
            or row["remote_requires_fresh_approval"] != 1
            or isinstance(row["revision"], bool)
            or not isinstance(row["revision"], int)
            or row["revision"] < 1
            or not created_at <= renewed_at <= now
            or expires_at <= now
        ):
            raise DatabaseInvariantError("automation grant is not eligible for temporal preparation")
        if (
            not metric_keys
            or tuple(sorted(metric_keys)) != metric_keys
            or len(set(metric_keys)) != len(metric_keys)
            or not set(metric_keys).issubset(COACHING_TEMPORAL_METRIC_KEYS)
        ):
            raise DatabaseInvariantError("automation grant is not an exact Coaching subset")

    def prepare_automation_scope(
        self, grant_id: str
    ) -> RepositoryPreparedTemporalScopeV1:
        self._ensure_initialized()
        require_safe_id(grant_id)
        with self._connection_scope() as connection:
            connection.execute("PRAGMA trusted_schema=ON")
            authorization: tuple[str, str, str] | None = None
            try:
                connection.execute("BEGIN IMMEDIATE")
                now = self._clock()
                _to_us(now)
                grant = connection.execute(
                    "SELECT * FROM automation_grants WHERE grant_id=?", (grant_id,)
                ).fetchone()
                metrics = () if grant is None else self._grant_metrics(connection, grant_id)
                self._validate_grant_for_prepare(grant, metrics, now)
                assert grant is not None
                project = connection.execute(
                    "SELECT provider FROM projects WHERE project_id=?",
                    (grant["project_id"],),
                ).fetchone()
                if project is None or project["provider"] != Provider.SYNTHETIC.value:
                    raise DatabaseInvariantError("automation grant project is invalid")
                grant_fingerprint = self._grant_fingerprint(grant, metrics)

                existing = connection.execute(
                    """SELECT prepared_scope_id FROM temporal_prepared_scope_roots
                       WHERE automation_grant_id=? AND automation_grant_revision=?""",
                    (grant_id, grant["revision"]),
                ).fetchone()
                if existing is not None:
                    scope = self._hydrate_scope_locked(
                        connection, str(existing["prepared_scope_id"])
                    )
                    if scope.automation_grant_fingerprint != grant_fingerprint:
                        raise DatabaseInvariantError("stored grant revision snapshot changed")
                    connection.commit()
                    return scope

                root_row = connection.execute(
                    """SELECT root_receipt_id FROM temporal_history_root_drafts
                       WHERE project_id=? ORDER BY epoch_ordinal DESC LIMIT 1""",
                    (grant["project_id"],),
                ).fetchone()
                root_is_new = root_row is None
                if root_is_new:
                    root = TemporalHistoryRootReceipt(
                        root_receipt_id=_new_id(),
                        project_id=grant["project_id"],
                        epoch_ordinal=1,
                        history_floor_at=now,
                        issued_at=now,
                    )
                else:
                    root = self._hydrate_root_locked(
                        connection, str(root_row["root_receipt_id"])
                    )
                    if root.epoch_ordinal != 1:
                        raise DatabaseInvariantError("unexpected temporal project epoch")

                predecessor_row = connection.execute(
                    """SELECT selection_revision_id FROM temporal_metric_selection_drafts
                       WHERE root_receipt_id=? ORDER BY selection_ordinal DESC LIMIT 1""",
                    (root.root_receipt_id,),
                ).fetchone()
                predecessor = (
                    None
                    if predecessor_row is None
                    else self._hydrate_selection_locked(
                        connection, str(predecessor_row["selection_revision_id"])
                    )
                )
                if predecessor is not None and now < predecessor.recorded_at:
                    raise DatabaseInvariantError(
                        "repository clock moved behind the prior metric selection"
                    )
                selection = ProjectMetricSelectionRevisionV2(
                    selection_revision_id=_new_id(),
                    root_receipt_id=root.root_receipt_id,
                    root_receipt_fingerprint=root.fingerprint,
                    project_id=root.project_id,
                    selection_ordinal=1 if predecessor is None else predecessor.selection_ordinal + 1,
                    compare_and_swap_predecessor_id=(
                        None if predecessor is None else predecessor.selection_revision_id
                    ),
                    compare_and_swap_predecessor_fingerprint=(
                        None if predecessor is None else predecessor.fingerprint
                    ),
                    selected_metric_keys=metrics,
                    source=ProjectMetricSelectionSource.AUTOMATION_GRANT,
                    effective_at=now,
                    recorded_at=now,
                    metric_pack_key=COACHING_METRIC_PACK_KEY,
                    metric_pack_version=COACHING_METRIC_PACK_VERSION,
                    metric_pack_sha256=COACHING_TEMPORAL_PACK_SHA256,
                    metric_catalog_version=COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION,
                    metric_catalog_sha256=COACHING_TEMPORAL_CATALOG_SHA256,
                    source_authority_kind=ProjectMetricSelectionAuthorityKind.AUTOMATION_GRANT,
                    source_authority_id=grant_id,
                    source_authority_fingerprint=grant_fingerprint,
                    source_authority_version=automation_grant_authority_version(
                        int(grant["revision"])
                    ),
                )
                scope = RepositoryPreparedTemporalScopeV1(
                    prepared_scope_id=_new_id(),
                    history_root=root,
                    selection_revision=selection,
                    automation_grant_id=grant_id,
                    automation_grant_fingerprint=grant_fingerprint,
                    automation_grant_revision=grant["revision"],
                    prepared_at=now,
                )
                auth_fingerprint = _canonical_digest(
                    {
                        "grant_fingerprint": grant_fingerprint,
                        "grant_id": grant_id,
                        "grant_revision": grant["revision"],
                        "prepared_scope_fingerprint": scope.fingerprint,
                        "prepared_scope_id": scope.prepared_scope_id,
                        "project_id": root.project_id,
                        "root_fingerprint": root.fingerprint,
                        "root_id": root.root_receipt_id,
                        "selection_fingerprint": selection.fingerprint,
                        "selection_id": selection.selection_revision_id,
                    }
                )
                operation_id, tag = self._begin_scope_authorization(
                    grant_id,
                    grant["revision"],
                    grant_fingerprint,
                    root.project_id,
                    scope.prepared_scope_id,
                    scope.fingerprint,
                    root.root_receipt_id,
                    root.fingerprint,
                    selection.selection_revision_id,
                    selection.fingerprint,
                    auth_fingerprint,
                )
                authorization = (operation_id, auth_fingerprint, tag)
                connection.execute(
                    """INSERT INTO temporal_scope_append_authorizations VALUES
                       (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (
                        operation_id,
                        grant_id,
                        grant["revision"],
                        grant_fingerprint,
                        root.project_id,
                        scope.prepared_scope_id,
                        scope.fingerprint,
                        root.root_receipt_id,
                        root.fingerprint,
                        selection.selection_revision_id,
                        selection.fingerprint,
                        auth_fingerprint,
                        tag,
                    ),
                )
                if root_is_new:
                    self._insert_root_locked(connection, operation_id, root)
                self._insert_grant_snapshot_locked(
                    connection,
                    operation_id,
                    selection.selection_revision_id,
                    grant,
                    metrics,
                    grant_fingerprint,
                )
                self._insert_selection_locked(connection, operation_id, selection)
                self._insert_scope_locked(connection, operation_id, scope)
                verified_scope = self._hydrate_scope_locked(
                    connection, scope.prepared_scope_id
                )
                if verified_scope != scope:
                    raise DatabaseInvariantError(
                        "stored prepared scope did not rederive exactly"
                    )
                connection.execute(
                    "DELETE FROM temporal_scope_append_authorizations WHERE operation_id=?",
                    (operation_id,),
                )
                connection.commit()
                return verified_scope
            except Exception:
                connection.rollback()
                raise
            finally:
                if authorization is not None:
                    self._end_scope_authorization(*authorization)
                connection.execute("PRAGMA trusted_schema=OFF")

    @staticmethod
    def _insert_root_locked(
        connection: sqlite3.Connection,
        operation_id: str,
        root: TemporalHistoryRootReceipt,
    ) -> None:
        connection.execute(
            """INSERT INTO temporal_history_root_drafts VALUES
               (?,?,?,?,?,?,?,?,?,?)""",
            (
                root.root_receipt_id,
                operation_id,
                root.contract_version,
                root.project_id,
                root.epoch_ordinal,
                root.predecessor_root_id,
                root.predecessor_root_fingerprint,
                _to_us(root.history_floor_at),
                _to_us(root.issued_at),
                root.fingerprint,
            ),
        )

    @staticmethod
    def _insert_grant_snapshot_locked(
        connection: sqlite3.Connection,
        operation_id: str,
        selection_revision_id: str,
        grant: sqlite3.Row,
        metrics: tuple[str, ...],
        fingerprint: str,
    ) -> None:
        created = _from_stored_iso(grant["created_at"])
        renewed = _from_stored_iso(grant["renewed_at"])
        expires = _from_stored_iso(grant["expires_at"])
        connection.execute(
            """INSERT INTO temporal_automation_grant_snapshots VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                selection_revision_id,
                operation_id,
                GRANT_SNAPSHOT_VERSION,
                grant["grant_id"],
                grant["revision"],
                grant["provider"],
                grant["project_id"],
                grant["newest_session_limit"],
                grant["check_interval_seconds"],
                grant["route"],
                grant["max_gpu_workers"],
                grant["max_cpu_workers"],
                grant["pause_on_battery"],
                grant["maximum_session_seconds"],
                grant["local_only"],
                grant["remote_requires_fresh_approval"],
                grant["state"],
                _to_us(created),
                _to_us(renewed),
                _to_us(expires),
                len(metrics),
                fingerprint,
            ),
        )
        connection.executemany(
            """INSERT INTO temporal_automation_grant_snapshot_metrics
               (selection_revision_id,ordinal,metric_key) VALUES (?,?,?)""",
            ((selection_revision_id, ordinal, key) for ordinal, key in enumerate(metrics)),
        )

    @staticmethod
    def _insert_selection_locked(
        connection: sqlite3.Connection,
        operation_id: str,
        selection: ProjectMetricSelectionRevisionV2,
    ) -> None:
        connection.execute(
            """INSERT INTO temporal_metric_selection_drafts VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                selection.selection_revision_id,
                operation_id,
                selection.contract_version,
                selection.root_receipt_id,
                selection.root_receipt_fingerprint,
                selection.project_id,
                selection.selection_ordinal,
                selection.compare_and_swap_predecessor_id,
                selection.compare_and_swap_predecessor_fingerprint,
                selection.source.value,
                _to_us(selection.effective_at),
                _to_us(selection.recorded_at),
                selection.metric_pack_key,
                selection.metric_pack_version,
                selection.metric_pack_sha256,
                selection.metric_catalog_version,
                selection.metric_catalog_sha256,
                selection.source_authority_kind.value,
                selection.source_authority_id,
                selection.source_authority_fingerprint,
                selection.source_authority_version,
                len(selection.selected_metric_keys),
                selection.metric_set_fingerprint,
                selection.fingerprint,
            ),
        )
        connection.executemany(
            """INSERT INTO temporal_metric_selection_keys
               (selection_revision_id,ordinal,metric_key) VALUES (?,?,?)""",
            (
                (selection.selection_revision_id, ordinal, key)
                for ordinal, key in enumerate(selection.selected_metric_keys)
            ),
        )

    @staticmethod
    def _insert_scope_locked(
        connection: sqlite3.Connection,
        operation_id: str,
        scope: RepositoryPreparedTemporalScopeV1,
    ) -> None:
        connection.execute(
            """INSERT INTO temporal_prepared_scope_roots VALUES
               (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                scope.prepared_scope_id,
                operation_id,
                scope.contract_version,
                scope.history_root.root_receipt_id,
                scope.selection_revision.selection_revision_id,
                scope.automation_grant_id,
                scope.automation_grant_fingerprint,
                scope.automation_grant_revision,
                _to_us(scope.prepared_at),
                scope.fingerprint,
                1,
                1,
                1,
                1,
                0,
                0,
                0,
                0,
                0,
                0,
            ),
        )

    @staticmethod
    def _hydrate_root_locked(
        connection: sqlite3.Connection, root_id: str
    ) -> TemporalHistoryRootReceipt:
        row = connection.execute(
            "SELECT * FROM temporal_history_root_drafts WHERE root_receipt_id=?",
            (root_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal root is missing")
        try:
            root = TemporalHistoryRootReceipt(
                contract_version=row["contract_version"],
                root_receipt_id=row["root_receipt_id"],
                project_id=row["project_id"],
                epoch_ordinal=row["epoch_ordinal"],
                predecessor_root_id=row["predecessor_root_id"],
                predecessor_root_fingerprint=row["predecessor_root_fingerprint"],
                history_floor_at=_from_us(row["history_floor_at_us"]),
                issued_at=_from_us(row["issued_at_us"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal root failed validation") from None
        if root.fingerprint != row["root_fingerprint"]:
            raise DatabaseInvariantError("stored temporal root fingerprint mismatch")
        return root

    @staticmethod
    def _hydrate_selection_locked(
        connection: sqlite3.Connection, selection_id: str
    ) -> ProjectMetricSelectionRevisionV2:
        row = connection.execute(
            "SELECT * FROM temporal_metric_selection_drafts WHERE selection_revision_id=?",
            (selection_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal selection is missing")
        key_rows = connection.execute(
            """SELECT ordinal,metric_key FROM temporal_metric_selection_keys
               WHERE selection_revision_id=? ORDER BY ordinal""",
            (selection_id,),
        ).fetchall()
        if tuple(item["ordinal"] for item in key_rows) != tuple(
            range(len(key_rows))
        ):
            raise DatabaseInvariantError("stored temporal selection key order is invalid")
        keys = tuple(str(item["metric_key"]) for item in key_rows)
        try:
            selection = ProjectMetricSelectionRevisionV2(
                contract_version=row["contract_version"],
                selection_revision_id=row["selection_revision_id"],
                root_receipt_id=row["root_receipt_id"],
                root_receipt_fingerprint=row["root_receipt_fingerprint"],
                project_id=row["project_id"],
                selection_ordinal=row["selection_ordinal"],
                compare_and_swap_predecessor_id=row["predecessor_selection_id"],
                compare_and_swap_predecessor_fingerprint=row[
                    "predecessor_selection_fingerprint"
                ],
                selected_metric_keys=keys,
                source=row["source"],
                effective_at=_from_us(row["effective_at_us"]),
                recorded_at=_from_us(row["recorded_at_us"]),
                metric_pack_key=row["metric_pack_key"],
                metric_pack_version=row["metric_pack_version"],
                metric_pack_sha256=row["metric_pack_sha256"],
                metric_catalog_version=row["metric_catalog_version"],
                metric_catalog_sha256=row["metric_catalog_sha256"],
                source_authority_kind=row["source_authority_kind"],
                source_authority_id=row["source_authority_id"],
                source_authority_fingerprint=row["source_authority_fingerprint"],
                source_authority_version=row["source_authority_version"],
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal selection failed validation") from None
        if (
            len(keys) != row["metric_count"]
            or selection.metric_set_fingerprint != row["metric_set_fingerprint"]
            or selection.fingerprint != row["selection_fingerprint"]
        ):
            raise DatabaseInvariantError("stored temporal selection fingerprint mismatch")
        return selection

    def _hydrate_scope_locked(
        self,
        connection: sqlite3.Connection,
        prepared_scope_id: str,
        *,
        validate_predecessors: bool = True,
    ) -> RepositoryPreparedTemporalScopeV1:
        row = connection.execute(
            "SELECT * FROM temporal_prepared_scope_roots WHERE prepared_scope_id=?",
            (prepared_scope_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored prepared scope is missing")
        root = self._hydrate_root_locked(connection, row["root_receipt_id"])
        selection = self._hydrate_selection_locked(
            connection, row["selection_revision_id"]
        )
        snapshot = connection.execute(
            """SELECT * FROM temporal_automation_grant_snapshots
               WHERE selection_revision_id=?""",
            (selection.selection_revision_id,),
        ).fetchone()
        root_operation = connection.execute(
            """SELECT operation_id FROM temporal_history_root_drafts
               WHERE root_receipt_id=?""",
            (root.root_receipt_id,),
        ).fetchone()
        selection_operation = connection.execute(
            """SELECT operation_id FROM temporal_metric_selection_drafts
               WHERE selection_revision_id=?""",
            (selection.selection_revision_id,),
        ).fetchone()
        snapshot_metrics = tuple(
            (item["ordinal"], item["metric_key"])
            for item in connection.execute(
                """SELECT ordinal,metric_key
                   FROM temporal_automation_grant_snapshot_metrics
                   WHERE selection_revision_id=? ORDER BY ordinal""",
                (selection.selection_revision_id,),
            ).fetchall()
        )
        registry_rows = connection.execute(
            "SELECT * FROM temporal_coaching_identity_registry ORDER BY registry_ordinal"
        ).fetchall()
        registry_keys = frozenset(str(item["metric_key"]) for item in registry_rows)
        expected_registry = tuple(
            (
                ordinal,
                spec.metric_key,
                spec.metric_definition_version,
                spec.metric_definition_sha256,
                spec.metric_question_version,
                spec.metric_question_sha256,
                spec.unit_code,
                spec.direction.value,
                spec.evidence_contract_version,
                spec.estimator_plan_version,
                spec.estimator_plan_sha256,
                spec.calibration_version,
                spec.calibration_sha256,
            )
            for ordinal, spec in enumerate(COACHING_IDENTITY_SPECS)
        )
        actual_registry = tuple(tuple(item) for item in registry_rows)
        if snapshot is None or selection_operation is None:
            raise DatabaseInvariantError("stored automation grant lineage is missing")
        selection_operation_id = str(selection_operation["operation_id"])
        snapshot_keys = tuple(str(item[1]) for item in snapshot_metrics)
        expected_ordinals = tuple(range(len(snapshot_metrics)))
        created = _from_us(snapshot["created_at_us"])
        renewed = _from_us(snapshot["renewed_at_us"])
        expires = _from_us(snapshot["expires_at_us"])
        snapshot_payload = {
            "check_interval_seconds": snapshot["check_interval_seconds"],
            "contract_version": snapshot["contract_version"],
            "created_at": to_iso(created),
            "expires_at": to_iso(expires),
            "grant_id": snapshot["grant_id"],
            "local_only": bool(snapshot["local_only"]),
            "maximum_session_seconds": snapshot["maximum_session_seconds"],
            "max_cpu_workers": snapshot["max_cpu_workers"],
            "max_gpu_workers": snapshot["max_gpu_workers"],
            "metric_keys": snapshot_keys,
            "newest_session_limit": snapshot["newest_session_limit"],
            "pause_on_battery": bool(snapshot["pause_on_battery"]),
            "project_id": snapshot["project_id"],
            "provider": snapshot["provider"],
            "remote_requires_fresh_approval": bool(
                snapshot["remote_requires_fresh_approval"]
            ),
            "renewed_at": to_iso(renewed),
            "revision": snapshot["revision"],
            "route": snapshot["route"],
            "snapshot_state": snapshot["state"],
        }
        expected_authority_version = automation_grant_authority_version(
            int(snapshot["revision"])
        )
        if (
            snapshot["contract_version"] != GRANT_SNAPSHOT_VERSION
            or snapshot["provider"] != Provider.SYNTHETIC.value
            or snapshot["state"] != "active"
            or snapshot["local_only"] != 1
            or snapshot["remote_requires_fresh_approval"] != 1
            or snapshot["metric_count"] != len(snapshot_metrics)
            or tuple(item[0] for item in snapshot_metrics) != expected_ordinals
            or snapshot_keys != selection.selected_metric_keys
            or not snapshot_keys
            or not set(snapshot_keys).issubset(registry_keys)
            or registry_keys != frozenset(COACHING_TEMPORAL_METRIC_KEYS)
            or actual_registry != expected_registry
            or _canonical_digest(snapshot_payload) != snapshot["grant_fingerprint"]
            or snapshot["grant_id"] != selection.source_authority_id
            or snapshot["grant_fingerprint"]
            != selection.source_authority_fingerprint
            or selection.source_authority_version != expected_authority_version
            or root_operation is None
            or row["operation_id"] != selection_operation_id
            or snapshot["operation_id"] != selection_operation_id
            or snapshot["project_id"] != root.project_id
            or not created <= renewed < expires
            or selection.metric_pack_key != COACHING_METRIC_PACK_KEY
            or selection.metric_pack_version != COACHING_METRIC_PACK_VERSION
            or selection.metric_pack_sha256 != COACHING_TEMPORAL_PACK_SHA256
            or selection.metric_catalog_version
            != COACHING_TEMPORAL_IDENTITY_CATALOG_VERSION
            or selection.metric_catalog_sha256 != COACHING_TEMPORAL_CATALOG_SHA256
        ):
            raise DatabaseInvariantError("stored prepared grant graph is invalid")
        if validate_predecessors:
            current = selection
            seen: set[str] = set()
            first_selection_operation_id: str | None = None
            while True:
                if current.selection_revision_id in seen:
                    raise DatabaseInvariantError("stored selection predecessor cycle")
                seen.add(current.selection_revision_id)
                if (
                    current.root_receipt_id != root.root_receipt_id
                    or current.root_receipt_fingerprint != root.fingerprint
                    or current.project_id != root.project_id
                ):
                    raise DatabaseInvariantError("stored selection chain changes scope")
                if current.selection_ordinal == 1:
                    first_operation = connection.execute(
                        """SELECT operation_id
                           FROM temporal_metric_selection_drafts
                           WHERE selection_revision_id=?""",
                        (current.selection_revision_id,),
                    ).fetchone()
                    if first_operation is None:
                        raise DatabaseInvariantError(
                            "stored first selection append lineage is missing"
                        )
                    first_selection_operation_id = str(
                        first_operation["operation_id"]
                    )
                    if connection.execute(
                        """SELECT 1 FROM temporal_metric_selection_drafts
                           WHERE root_receipt_id=? AND selection_ordinal<1""",
                        (root.root_receipt_id,),
                    ).fetchone() is not None:
                        raise DatabaseInvariantError(
                            "stored first selection is not first"
                        )
                    break
                predecessor_row = connection.execute(
                    """SELECT selection_revision_id
                       FROM temporal_metric_selection_drafts
                       WHERE root_receipt_id=? AND selection_ordinal=?""",
                    (root.root_receipt_id, current.selection_ordinal - 1),
                ).fetchone()
                if predecessor_row is None:
                    raise DatabaseInvariantError(
                        "stored selection predecessor is missing"
                    )
                predecessor = self._hydrate_selection_locked(
                    connection, str(predecessor_row["selection_revision_id"])
                )
                predecessor_scope_row = connection.execute(
                    """SELECT prepared_scope_id
                       FROM temporal_prepared_scope_roots
                       WHERE selection_revision_id=?""",
                    (predecessor.selection_revision_id,),
                ).fetchone()
                if predecessor_scope_row is None:
                    raise DatabaseInvariantError(
                        "stored predecessor prepared scope is missing"
                    )
                predecessor_scope = self._hydrate_scope_locked(
                    connection,
                    str(predecessor_scope_row["prepared_scope_id"]),
                    validate_predecessors=False,
                )
                if (
                    predecessor_scope.selection_revision != predecessor
                    or predecessor_scope.history_root != root
                    or predecessor.selection_revision_id
                    != current.compare_and_swap_predecessor_id
                    or predecessor.fingerprint
                    != current.compare_and_swap_predecessor_fingerprint
                    or predecessor.recorded_at > current.effective_at
                    or predecessor.recorded_at > current.recorded_at
                ):
                    raise DatabaseInvariantError(
                        "stored selection predecessor is invalid"
                    )
                current = predecessor
            if (
                root_operation is None
                or first_selection_operation_id is None
                or root_operation["operation_id"]
                != first_selection_operation_id
            ):
                raise DatabaseInvariantError(
                    "stored root and first selection append lineage differ"
                )
        elif (
            selection.selection_ordinal == 1
            and root_operation["operation_id"] != selection_operation_id
        ):
            raise DatabaseInvariantError(
                "stored root and first selection append lineage differ"
            )
        try:
            scope = RepositoryPreparedTemporalScopeV1(
                contract_version=row["contract_version"],
                prepared_scope_id=row["prepared_scope_id"],
                history_root=root,
                selection_revision=selection,
                automation_grant_id=row["automation_grant_id"],
                automation_grant_fingerprint=row["automation_grant_fingerprint"],
                automation_grant_revision=row["automation_grant_revision"],
                prepared_at=_from_us(row["prepared_at_us"]),
                repository_owned=bool(row["repository_owned"]),
                repository_graph_verified=bool(row["repository_graph_verified"]),
                selection_authority_verified=bool(row["selection_authority_verified"]),
                sealed=bool(row["repository_sealed"]),
                product_history_eligible=bool(row["product_history_eligible"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(
                    row["snapshot_materialization_allowed"]
                ),
                activation_allowed=bool(row["activation_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored prepared scope failed validation") from None
        if scope.fingerprint != row["prepared_scope_fingerprint"]:
            raise DatabaseInvariantError("stored prepared scope fingerprint mismatch")
        if (
            scope.automation_grant_id != snapshot["grant_id"]
            or scope.automation_grant_revision != snapshot["revision"]
            or scope.automation_grant_fingerprint != snapshot["grant_fingerprint"]
            or scope.prepared_at >= expires
            or selection.effective_at < root.history_floor_at
            or selection.recorded_at < root.history_floor_at
            or scope.prepared_at < selection.recorded_at
        ):
            raise DatabaseInvariantError("stored prepared scope lineage is invalid")
        return scope

    def get_prepared_scope(
        self, prepared_scope_id: str
    ) -> RepositoryPreparedTemporalScopeV1 | None:
        self._ensure_initialized()
        require_safe_id(prepared_scope_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM temporal_prepared_scope_roots WHERE prepared_scope_id=?",
                (prepared_scope_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_scope_locked(connection, prepared_scope_id)
            )

    def get_prepared_scope_for_grant(
        self, grant_id: str
    ) -> RepositoryPreparedTemporalScopeV1 | None:
        self._ensure_initialized()
        require_safe_id(grant_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT prepared_scope_id FROM temporal_prepared_scope_roots
                   WHERE automation_grant_id=?
                   ORDER BY automation_grant_revision DESC LIMIT 1""",
                (grant_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_scope_locked(
                    connection, str(row["prepared_scope_id"])
                )
            )

    # Completion and sealed hydration are below; no public graph writer exists.

    @staticmethod
    def _result_map(
        results: tuple[SessionAnalysisResultRecord, ...],
        selected_metric_keys: tuple[str, ...],
        finished_at: datetime,
    ) -> dict[str, SessionAnalysisResultRecord]:
        by_key = {item.observation.key: item for item in results}
        if len(by_key) != len(results) or tuple(sorted(by_key)) != selected_metric_keys:
            raise DatabaseInvariantError("temporal results do not exactly cover selection")
        coverages = {
            (item.observation.observed_count, item.observation.eligible_count)
            for item in results
        }
        if len(coverages) != 1:
            raise DatabaseInvariantError("temporal results have inconsistent input coverage")
        for key in selected_metric_keys:
            result = by_key[key]
            definition = _DEFINITIONS.get(key)
            observation = result.observation
            if definition is None:
                raise DatabaseInvariantError("temporal result metric is not Coaching v3")
            expected_direction = SessionMetricDirection(definition.direction.value)
            if (
                observation.version != definition.version
                or observation.unit != definition.unit
                or observation.source is not MetricSource.DETERMINISTIC
                or observation.confidence is not None
                or result.direction is not expected_direction
                or result.aggregation_method is not SessionMetricAggregation.RATIO_OF_SUMS
                or result.metric_schema_version != 2
                or result.evidence_data_tier is not DataTier.REDACTED_CONTENT
                or result.algorithm_id != COACHING_METRIC_ALGORITHM_ID
                or result.algorithm_version != COACHING_METRIC_ALGORITHM_VERSION
                or result.rubric_version != COACHING_METRIC_RUBRIC_VERSION
                or any(
                    value is not None
                    for value in (
                        result.model_id,
                        result.model_revision,
                        result.model_license,
                        result.tokenizer_id,
                        result.prompt_version,
                    )
                )
                or result.computed_at != finished_at
            ):
                raise DatabaseInvariantError("temporal result provenance is not exact Coaching")
            if result.value_state is MetricValueState.KNOWN:
                if (
                    result.applicability is not SessionMetricApplicability.APPLICABLE
                    or result.fraction_numerator is None
                    or result.fraction_denominator is None
                    or result.explanation_code == ""
                ):
                    raise DatabaseInvariantError("known temporal result is malformed")
            elif result.value_state is MetricValueState.NOT_APPLICABLE:
                if result.applicability is not SessionMetricApplicability.NOT_APPLICABLE:
                    raise DatabaseInvariantError("not-applicable result is malformed")
            elif result.value_state is MetricValueState.EXECUTION_ERROR:
                if result.error_code is None:
                    raise DatabaseInvariantError("failed result requires an error code")
            elif result.applicability is SessionMetricApplicability.NOT_APPLICABLE:
                raise DatabaseInvariantError("temporal applicability conflicts with state")
        return by_key

    @staticmethod
    def _validate_stored_completion_authority(
        connection: sqlite3.Connection,
        *,
        request: SyntheticTemporalCompletionRequestV1,
        completion_authority: SessionAnalysisCompletionAuthority,
        selected_metric_keys: tuple[str, ...],
        finished_at: datetime,
    ) -> tuple[sqlite3.Row, sqlite3.Row, sqlite3.Row, sqlite3.Row, str]:
        run = connection.execute(
            "SELECT * FROM session_analysis_runs WHERE run_id=?",
            (request.analysis_run_id,),
        ).fetchone()
        if run is None:
            raise DatabaseInvariantError("temporal analysis run is missing")
        session = connection.execute(
            "SELECT * FROM sessions WHERE session_id=?", (run["session_id"],)
        ).fetchone()
        job = connection.execute(
            "SELECT * FROM analysis_jobs WHERE job_id=?",
            (completion_authority.job_id,),
        ).fetchone()
        grant = connection.execute(
            "SELECT * FROM automation_grants WHERE grant_id=?",
            (completion_authority.automation_grant_id,),
        ).fetchone()
        if session is None or job is None or grant is None:
            raise DatabaseInvariantError("temporal completion authority is incomplete")
        job_metrics = tuple(
            row["metric_key"]
            for row in connection.execute(
                "SELECT metric_key FROM analysis_job_metrics WHERE job_id=? ORDER BY ordinal",
                (job["job_id"],),
            ).fetchall()
        )
        run_metrics = tuple(
            row["metric_key"]
            for row in connection.execute(
                "SELECT metric_key FROM session_analysis_run_metrics WHERE run_id=? ORDER BY ordinal",
                (run["run_id"],),
            ).fetchall()
        )
        grant_metrics = SqliteTemporalHistoryRepository._grant_metrics(
            connection, grant["grant_id"]
        )
        expires = _from_stored_iso(grant["expires_at"])
        lease_expires = _from_stored_iso(job["lease_expires_at"])
        session_started_at = _from_stored_iso(session["started_at"])
        if (
            run["status"] != "running"
            or run["provider"] != Provider.SYNTHETIC.value
            or run["local_only"] != 1
            or run["metric_scope_state"] != "exact"
            or session["session_id"] != request.analysis_input.session_id
            or session["project_id"] != request.analysis_input.project_id
            or session["provider"] != Provider.SYNTHETIC.value
            or session_started_at
            < request.prepared_scope.history_root.history_floor_at
            or job["automation_grant_id"] != grant["grant_id"]
            or job["session_id"] != run["session_id"]
            or job["project_id"] != session["project_id"]
            or job["provider"] != Provider.SYNTHETIC.value
            or job["kind"] != "session_quality"
            or job["state"] not in {"preprocessing", "stage_n"}
            or job["cancel_requested"] != 0
            or job["estimator_plan_version"] != COACHING_AUTOMATION_JOB_PLAN_VERSION
            or job["redactor_version"] != run["redactor_version"]
            or job["lease_owner"] != completion_authority.lease_owner
            or job["lease_token"] != completion_authority.lease_token
            or lease_expires is None
            or lease_expires <= finished_at
            or grant["state"] != "active"
            or grant["provider"] != Provider.SYNTHETIC.value
            or grant["project_id"] != session["project_id"]
            or expires is None
            or expires <= finished_at
            or grant["local_only"] != 1
            or grant["remote_requires_fresh_approval"] != 1
            or run_metrics != selected_metric_keys
            or job_metrics != selected_metric_keys
            or grant_metrics != selected_metric_keys
        ):
            raise DatabaseInvariantError("temporal completion authority is no longer exact")
        return run, session, job, grant, SqliteTemporalHistoryRepository._grant_fingerprint(
            grant, grant_metrics
        )

    def _validate_stored_sealed_source_locked(
        self,
        connection: sqlite3.Connection,
        request: SyntheticTemporalCompletionRequestV1,
    ) -> None:
        """Revalidate the immutable source bridge behind a sealed graph.

        The temporal graph is not a substitute for its source run. Reads prove
        that the completed run, terminal synthetic session, ordered run scope,
        and immutable prepared grant snapshot still match the exact V2 input.
        Job, lease, and current-grant state are seal-time-only authority and are
        deliberately absent from the durable public graph.
        """

        try:
            request_row = connection.execute(
                """SELECT 1 FROM temporal_completion_requests
                   WHERE completion_request_id=? AND analysis_run_id=?""",
                (request.completion_request_id, request.analysis_run_id),
            ).fetchone()
            run = connection.execute(
                "SELECT * FROM session_analysis_runs WHERE run_id=?",
                (request.analysis_run_id,),
            ).fetchone()
            if request_row is None or run is None:
                raise DatabaseInvariantError("stored temporal source run is missing")
            session = connection.execute(
                "SELECT * FROM sessions WHERE session_id=?", (run["session_id"],)
            ).fetchone()
            snapshot = connection.execute(
                """SELECT * FROM temporal_automation_grant_snapshots
                   WHERE selection_revision_id=?""",
                (
                    request.prepared_scope.selection_revision.selection_revision_id,
                ),
            ).fetchone()
            project = connection.execute(
                "SELECT * FROM projects WHERE project_id=?",
                (request.analysis_input.project_id,),
            ).fetchone()
            if any(
                item is None
                for item in (session, snapshot, project)
            ):
                raise DatabaseInvariantError(
                    "stored temporal source authority is incomplete"
                )

            assert session is not None
            assert snapshot is not None
            assert project is not None
            selected = request.prepared_scope.selection_revision.selected_metric_keys
            run_metrics_rows = connection.execute(
                """SELECT ordinal,metric_key FROM session_analysis_run_metrics
                   WHERE run_id=? ORDER BY ordinal""",
                (run["run_id"],),
            ).fetchall()
            run_metrics = tuple(str(item["metric_key"]) for item in run_metrics_rows)
            expected_ordinals = tuple(range(len(selected)))
            if tuple(item["ordinal"] for item in run_metrics_rows) != expected_ordinals:
                raise DatabaseInvariantError(
                    "stored temporal source metric order is invalid"
                )

            input_receipt = request.analysis_input
            finished_at = _from_stored_iso(run["finished_at"])
            run_started_at = _from_stored_iso(run["started_at"])
            session_started_at = _from_stored_iso(session["started_at"])
            session_ended_at = _from_stored_iso(session["ended_at"])
            expected_run_fingerprint = analysis_run_bridge_fingerprint(
                request_fingerprint=run["request_fingerprint"],
                input_fingerprint=run["input_fingerprint"],
                analysis_profile_key=run["analysis_profile_key"],
                analysis_profile_version=run["analysis_profile_version"],
                metric_pack_key=run["metric_pack_key"],
                metric_pack_version=run["metric_pack_version"],
                selected_metric_keys=selected,
                provider=run["provider"],
                provider_version=run["provider_version"],
                adapter_version=run["adapter_version"],
                source_schema_version=run["source_schema_version"],
                content_schema_version=run["content_schema_version"],
                metric_engine_version=run["metric_engine_version"],
                redactor_version=run["redactor_version"],
                model_plan_fingerprint=run["model_plan_fingerprint"],
                schema_version=run["schema_version"],
                analysis_window_fingerprint=(
                    input_receipt.analysis_window_fingerprint
                ),
            )

            if (
                run["status"] != "completed"
                or run["failure_code"] is not None
                or finished_at != input_receipt.analysis_run_completed_at
                or finished_at != input_receipt.captured_at
                or request.analysis_run_id != run["run_id"]
                or input_receipt.analysis_run_id != run["run_id"]
                or input_receipt.session_id != run["session_id"]
                or input_receipt.analysis_run_request_fingerprint
                != run["request_fingerprint"]
                or input_receipt.analysis_run_fingerprint
                != expected_run_fingerprint
                or input_receipt.analysis_run_fingerprint_version
                != ANALYSIS_RUN_BRIDGE_VERSION
                or input_receipt.analysis_profile_key
                != run["analysis_profile_key"]
                or input_receipt.analysis_profile_version
                != run["analysis_profile_version"]
                or input_receipt.metric_pack_key != run["metric_pack_key"]
                or input_receipt.metric_pack_version != run["metric_pack_version"]
                or run["metric_scope_state"] != "exact"
                or input_receipt.data_tier.value != run["data_tier"]
                or input_receipt.consent_purpose != run["consent_purpose"]
                or input_receipt.consent_policy_version
                != run["consent_policy_version"]
                or input_receipt.provider.value != run["provider"]
                or input_receipt.provider_version != run["provider_version"]
                or input_receipt.provider_adapter_version != run["adapter_version"]
                or input_receipt.source_schema_version
                != run["source_schema_version"]
                or input_receipt.content_schema_version
                != run["content_schema_version"]
                or input_receipt.metric_engine_version
                != run["metric_engine_version"]
                or input_receipt.redactor_version != run["redactor_version"]
                or input_receipt.model_plan_fingerprint
                != run["model_plan_fingerprint"]
                or input_receipt.analysis_run_schema_version
                != run["schema_version"]
                or run["local_only"] != 1
                or run_metrics != selected
                or not request.prepared_scope.prepared_at
                <= run_started_at
                <= finished_at
                or session["session_id"] != input_receipt.session_id
                or session["project_id"] != input_receipt.project_id
                or session["installation_id"] != project["installation_id"]
                or session["provider"] != Provider.SYNTHETIC.value
                or project["provider"] != Provider.SYNTHETIC.value
                or session["provider_version"] != input_receipt.provider_version
                or session["adapter_version"]
                != input_receipt.provider_adapter_version
                or session["source_schema_version"]
                != input_receipt.source_schema_version
                or session["terminal_state"] != "completed"
                or session["events_complete"] != 1
                or session_started_at
                < request.prepared_scope.history_root.history_floor_at
                or not session_started_at
                <= input_receipt.analysis_window_started_at
                <= input_receipt.analysis_window_ended_at
                <= session_ended_at
                or snapshot["grant_id"]
                != request.prepared_scope.automation_grant_id
                or snapshot["revision"]
                != request.prepared_scope.automation_grant_revision
                or snapshot["grant_fingerprint"]
                != request.prepared_scope.automation_grant_fingerprint
                or snapshot["project_id"] != input_receipt.project_id
                or snapshot["provider"] != Provider.SYNTHETIC.value
            ):
                raise DatabaseInvariantError(
                    "stored temporal source lineage no longer revalidates"
                )
        except DatabaseInvariantError:
            raise
        except Exception:
            raise DatabaseInvariantError(
                "stored temporal source lineage failed validation"
            ) from None

    def _complete_locked(
        self,
        connection: sqlite3.Connection,
        *,
        request: SyntheticTemporalCompletionRequestV1,
        results: tuple[SessionAnalysisResultRecord, ...],
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority,
    ) -> RepositorySealedTemporalBatchV1:
        """Append one graph inside the caller's existing IMMEDIATE transaction."""

        checked = SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(
            request
        )
        scope = self._hydrate_scope_locked(
            connection, checked.prepared_scope.prepared_scope_id
        )
        if scope != checked.prepared_scope:
            raise DatabaseInvariantError("completion request scope is not repository-owned")
        selected = scope.selection_revision.selected_metric_keys
        stored_results = self._hydrate_run_results_locked(
            connection, checked.analysis_run_id
        )
        if stored_results != results:
            raise DatabaseInvariantError(
                "stored Coaching results differ from the completion input"
            )
        by_key = self._result_map(stored_results, selected, finished_at)
        run, session, job, grant, grant_fingerprint = (
            self._validate_stored_completion_authority(
                connection,
                request=checked,
                completion_authority=completion_authority,
                selected_metric_keys=selected,
                finished_at=finished_at,
            )
        )
        input_receipt = checked.analysis_input
        expected_run_fingerprint = analysis_run_bridge_fingerprint(
            request_fingerprint=run["request_fingerprint"],
            input_fingerprint=run["input_fingerprint"],
            analysis_profile_key=run["analysis_profile_key"],
            analysis_profile_version=run["analysis_profile_version"],
            metric_pack_key=run["metric_pack_key"],
            metric_pack_version=run["metric_pack_version"],
            selected_metric_keys=selected,
            provider=run["provider"],
            provider_version=run["provider_version"],
            adapter_version=run["adapter_version"],
            source_schema_version=run["source_schema_version"],
            content_schema_version=run["content_schema_version"],
            metric_engine_version=run["metric_engine_version"],
            redactor_version=run["redactor_version"],
            model_plan_fingerprint=run["model_plan_fingerprint"],
            schema_version=run["schema_version"],
            analysis_window_fingerprint=input_receipt.analysis_window_fingerprint,
        )
        if (
            checked.analysis_run_id != run["run_id"]
            or input_receipt.analysis_run_id != run["run_id"]
            or input_receipt.analysis_run_fingerprint != expected_run_fingerprint
            or input_receipt.analysis_run_fingerprint_version
            != ANALYSIS_RUN_BRIDGE_VERSION
            or input_receipt.analysis_run_request_fingerprint
            != run["request_fingerprint"]
            or input_receipt.project_id != session["project_id"]
            or input_receipt.session_id != session["session_id"]
            or input_receipt.analysis_profile_key != run["analysis_profile_key"]
            or input_receipt.analysis_profile_version != run["analysis_profile_version"]
            or input_receipt.metric_pack_key != run["metric_pack_key"]
            or input_receipt.metric_pack_version != run["metric_pack_version"]
            or input_receipt.data_tier.value != run["data_tier"]
            or input_receipt.consent_purpose != run["consent_purpose"]
            or input_receipt.consent_policy_version != run["consent_policy_version"]
            or input_receipt.provider.value != run["provider"]
            or input_receipt.provider_version != run["provider_version"]
            or input_receipt.provider_adapter_version != run["adapter_version"]
            or input_receipt.source_schema_version != run["source_schema_version"]
            or input_receipt.content_schema_version != run["content_schema_version"]
            or input_receipt.metric_engine_version != run["metric_engine_version"]
            or input_receipt.redactor_version != run["redactor_version"]
            or input_receipt.model_plan_fingerprint != run["model_plan_fingerprint"]
            or input_receipt.analysis_run_schema_version
            != SESSION_ANALYSIS_RUN_SCHEMA_VERSION
            or input_receipt.provider_schema_version != job["provider_schema_version"]
            or input_receipt.selected_metric_keys != selected
            or input_receipt.full_run_metric_observation_count != len(results)
            or input_receipt.analysis_run_completed_at != finished_at
            or input_receipt.captured_at != finished_at
            or input_receipt.analysis_window_started_at
            < scope.history_root.history_floor_at
            or input_receipt.captured_at < scope.prepared_at
            or grant["grant_id"] != scope.automation_grant_id
            or grant["revision"] != scope.automation_grant_revision
            or grant_fingerprint != scope.automation_grant_fingerprint
        ):
            raise DatabaseInvariantError("temporal completion request mismatches stored run")

        if connection.execute(
            """SELECT 1 FROM temporal_session_revisions
               WHERE root_receipt_id=? AND session_id=?
               ORDER BY revision_ordinal DESC LIMIT 1""",
            (scope.history_root.root_receipt_id, input_receipt.session_id),
        ).fetchone() is not None:
            raise DatabaseInvariantError(
                "schema v21 supports one temporal revision per session epoch"
            )
        revision = SessionRevisionReceiptV3.from_direct_input(
            revision_id=_new_id(),
            input_receipt=input_receipt,
            revision_ordinal=1,
            effective_time_basis=RevisionEffectiveTimeBasis.REVISION_CAPTURED_AT,
            predecessor=None,
        )
        identities = self._identity_catalog.build_for_synthetic_request(checked)
        observations = tuple(
            self._observation_from_result(
                result=by_key[identity.metric_key],
                identity=identity,
                revision=revision,
                input_receipt=input_receipt,
            )
            for identity in identities
        )
        repository_time = self._clock()
        if repository_time < finished_at:
            raise DatabaseInvariantError("repository clock moved behind capture")
        lease_expires = _from_stored_iso(job["lease_expires_at"])
        grant_expires = _from_stored_iso(grant["expires_at"])
        if (
            lease_expires is None
            or grant_expires is None
            or repository_time >= lease_expires
            or repository_time >= grant_expires
        ):
            raise DatabaseInvariantError(
                "temporal authority expired before repository sealing"
            )
        batch = TemporalObservationBatchV2(
            batch_id=_new_id(),
            project_id=input_receipt.project_id,
            session_id=input_receipt.session_id,
            root_receipt_id=scope.history_root.root_receipt_id,
            root_receipt_fingerprint=scope.history_root.fingerprint,
            revision_id=revision.revision_id,
            revision_fingerprint=revision.fingerprint,
            analysis_run_id=input_receipt.analysis_run_id,
            analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
            analysis_input_receipt_id=input_receipt.input_receipt_id,
            analysis_input_receipt_fingerprint=input_receipt.fingerprint,
            selection_revision_id=scope.selection_revision.selection_revision_id,
            selection_revision_fingerprint=scope.selection_revision.fingerprint,
            selected_metric_keys=selected,
            observations=observations,
            recorded_at=repository_time,
        )
        draft = RepositoryTemporalBatchSealDraft(
            seal_draft_id=_new_id(),
            history_root=scope.history_root,
            selection_revision=scope.selection_revision,
            analysis_input=input_receipt,
            session_revision=revision,
            observation_batch=batch,
            analysis_run_id=input_receipt.analysis_run_id,
            analysis_run_fingerprint=input_receipt.analysis_run_fingerprint,
            ordered_observation_ids=tuple(item.observation_id for item in observations),
            ordered_observation_fingerprints=tuple(
                item.fingerprint for item in observations
            ),
            requested_repository_verifier_version=REPOSITORY_TEMPORAL_VERIFIER_VERSION,
            requested_repository_verifier_fingerprint=(
                REPOSITORY_TEMPORAL_VERIFIER_FINGERPRINT
            ),
            drafted_at=repository_time,
        )
        sealed = RepositorySealedTemporalBatchV1(
            sealed_batch_id=_new_id(),
            completion_request=checked,
            prepared_scope_fingerprint=scope.fingerprint,
            completion_request_fingerprint=checked.fingerprint,
            seal_draft=draft,
            seal_draft_fingerprint=draft.fingerprint,
            ordered_graph_fingerprints=(
                RepositorySealedTemporalBatchV1.ordered_graph_for(checked, draft)
            ),
            repository_verifier_version=REPOSITORY_TEMPORAL_VERIFIER_VERSION,
            repository_verifier_fingerprint=REPOSITORY_TEMPORAL_VERIFIER_FINGERPRINT,
            sealed_at=repository_time,
        )
        auth_fingerprint = _canonical_digest(
            {
                "completion_request_fingerprint": checked.fingerprint,
                "completion_request_id": checked.completion_request_id,
                "grant_fingerprint": grant_fingerprint,
                "grant_id": grant["grant_id"],
                "grant_revision": grant["revision"],
                "job_id": job["job_id"],
                "prepared_scope_fingerprint": scope.fingerprint,
                "prepared_scope_id": scope.prepared_scope_id,
                "root_fingerprint": scope.history_root.fingerprint,
                "root_id": scope.history_root.root_receipt_id,
                "run_fingerprint": input_receipt.analysis_run_fingerprint,
                "run_id": input_receipt.analysis_run_id,
                "seal_draft_fingerprint": draft.fingerprint,
                "seal_draft_id": draft.seal_draft_id,
                "sealed_batch_fingerprint": sealed.fingerprint,
                "sealed_batch_id": sealed.sealed_batch_id,
                "selection_fingerprint": scope.selection_revision.fingerprint,
                "selection_id": scope.selection_revision.selection_revision_id,
            }
        )
        operation_id, tag = self._begin_history_authorization(
            job["job_id"],
            grant["grant_id"],
            grant["revision"],
            grant_fingerprint,
            input_receipt.analysis_run_id,
            input_receipt.analysis_run_fingerprint,
            scope.history_root.root_receipt_id,
            scope.history_root.fingerprint,
            scope.selection_revision.selection_revision_id,
            scope.selection_revision.fingerprint,
            scope.prepared_scope_id,
            scope.fingerprint,
            checked.completion_request_id,
            checked.fingerprint,
            draft.seal_draft_id,
            draft.fingerprint,
            sealed.sealed_batch_id,
            sealed.fingerprint,
            auth_fingerprint,
        )
        authorization = (operation_id, auth_fingerprint, tag)
        try:
            self._insert_history_graph_locked(
                connection,
                operation_id=operation_id,
                tag=tag,
                authorization_fingerprint=auth_fingerprint,
                completion_authority=completion_authority,
                grant=grant,
                grant_fingerprint=grant_fingerprint,
                scope=scope,
                request=checked,
                revision=revision,
                identities=identities,
                batch=batch,
                draft=draft,
                sealed=sealed,
            )
            # The owning run is deliberately still running until its terminal
            # UPDATE proves that this root-last marker exists.  Revalidate the
            # normalized graph now, then let the caller perform a second full
            # source-bridge hydration after that terminal transition.
            verified = self._hydrate_sealed_locked(
                connection,
                sealed.sealed_batch_id,
                validate_source=False,
            )
            if verified != sealed:
                raise DatabaseInvariantError("stored sealed graph did not rederive exactly")
            connection.execute(
                "DELETE FROM temporal_history_append_authorizations WHERE operation_id=?",
                (operation_id,),
            )
            return verified
        finally:
            self._end_history_authorization(*authorization)

    def _replay_completed_locked(
        self,
        connection: sqlite3.Connection,
        *,
        request: SyntheticTemporalCompletionRequestV1,
        results: tuple[SessionAnalysisResultRecord, ...],
        finished_at: datetime,
        completion_authority: SessionAnalysisCompletionAuthority,
    ) -> RepositorySealedTemporalBatchV1:
        """Return only the byte-equivalent committed temporal completion.

        Job/lease authority was consumed at first seal and is not durable
        public lineage. Replay is therefore a read-like exact request/result/
        timestamp check, never a reauthorization of an expired worker lease.
        """

        checked = SyntheticTemporalCompletionRequestV1.revalidate_for_persistence(
            request
        )
        row = connection.execute(
            """SELECT sealed.sealed_batch_id,q.prepared_scope_id,
                      run.finished_at
               FROM temporal_completion_requests q
               JOIN temporal_sealed_batch_roots sealed
                 ON sealed.completion_request_id=q.completion_request_id
               JOIN session_analysis_runs run ON run.run_id=q.analysis_run_id
               WHERE q.analysis_run_id=? AND run.status='completed'""",
            (checked.analysis_run_id,),
        ).fetchone()
        stored_finished_at = (
            None if row is None else _from_stored_iso(row["finished_at"])
        )
        if (
            row is None
            or stored_finished_at != finished_at
            or row["prepared_scope_id"]
            != checked.prepared_scope.prepared_scope_id
        ):
            raise DatabaseInvariantError(
                "completed temporal replay does not match stored authority"
            )
        sealed = self._hydrate_sealed_locked(
            connection, str(row["sealed_batch_id"])
        )
        stored_results = self._hydrate_run_results_locked(
            connection, checked.analysis_run_id
        )
        canonical_results = tuple(
            sorted(results, key=lambda item: (item.observation.key, item.observation.version))
        )
        if (
            sealed.completion_request != checked
            or stored_results != canonical_results
        ):
            raise DatabaseInvariantError(
                "completed temporal replay differs from the committed graph"
            )
        return sealed

    @staticmethod
    def _observation_from_result(
        *,
        result: SessionAnalysisResultRecord,
        identity: MetricComparisonIdentity,
        revision: SessionRevisionReceiptV3,
        input_receipt: AnalysisInputReceiptV2,
        observation_id: str | None = None,
    ) -> TemporalMetricObservationV2:
        value = None
        source_state = TemporalSourceState.PRESENT
        state = {
            MetricValueState.KNOWN: TemporalValueState.KNOWN,
            MetricValueState.UNKNOWN: TemporalValueState.UNKNOWN,
            MetricValueState.ABSTAINED: TemporalValueState.ABSTAINED,
            MetricValueState.NOT_APPLICABLE: TemporalValueState.NOT_APPLICABLE,
            MetricValueState.EXECUTION_ERROR: TemporalValueState.FAILED,
        }[result.value_state]
        if result.value_state is MetricValueState.KNOWN:
            assert result.fraction_numerator is not None
            assert result.fraction_denominator is not None
            value = FractionObservationValue(
                numerator=result.fraction_numerator,
                denominator=result.fraction_denominator,
            )
            reason = None
        elif result.value_state is MetricValueState.EXECUTION_ERROR:
            source_state = TemporalSourceState.SOURCE_FAILED
            reason = result.error_code
        else:
            reason = result.explanation_code
        if source_state is TemporalSourceState.SOURCE_FAILED:
            eligibility = EvidenceCoverageEligibility.UNKNOWN
            coverage_state = EvidenceCoverageState.UNKNOWN
            numerator = denominator = None
        else:
            eligibility = EvidenceCoverageEligibility.ELIGIBLE
            coverage_state = EvidenceCoverageState.KNOWN
            numerator = result.observation.observed_count
            denominator = result.observation.eligible_count
            if numerator is None or denominator is None:
                raise DatabaseInvariantError("Coaching evidence coverage is missing")
        return TemporalMetricObservationV2(
            observation_id=_new_id() if observation_id is None else observation_id,
            revision_id=revision.revision_id,
            analysis_run_id=input_receipt.analysis_run_id,
            analysis_input_receipt_id=input_receipt.input_receipt_id,
            analysis_input_receipt_fingerprint=input_receipt.fingerprint,
            comparison_identity=identity,
            selection_state=TemporalSelectionState.SELECTED,
            source_state=source_state,
            value_state=state,
            value=value,
            unavailable_reason_code=reason,
            evidence_coverage_eligibility=eligibility,
            evidence_coverage_state=coverage_state,
            evidence_numerator=numerator,
            evidence_denominator=denominator,
            observed_at=result.computed_at,
        )

    @staticmethod
    def _insert_row(
        connection: sqlite3.Connection,
        table: str,
        values: dict[str, object],
    ) -> None:
        columns = tuple(values)
        placeholders = ",".join("?" for _ in columns)
        connection.execute(
            f"INSERT INTO {table}({','.join(columns)}) VALUES ({placeholders})",
            tuple(values[column] for column in columns),
        )

    def _insert_history_graph_locked(
        self,
        connection: sqlite3.Connection,
        *,
        operation_id: str,
        tag: str,
        authorization_fingerprint: str,
        completion_authority: SessionAnalysisCompletionAuthority,
        grant: sqlite3.Row,
        grant_fingerprint: str,
        scope: RepositoryPreparedTemporalScopeV1,
        request: SyntheticTemporalCompletionRequestV1,
        revision: SessionRevisionReceiptV3,
        identities: tuple[MetricComparisonIdentity, ...],
        batch: TemporalObservationBatchV2,
        draft: RepositoryTemporalBatchSealDraft,
        sealed: RepositorySealedTemporalBatchV1,
    ) -> None:
        input_receipt = request.analysis_input
        self._insert_row(
            connection,
            "temporal_history_append_authorizations",
            {
                "operation_id": operation_id,
                "job_id": completion_authority.job_id,
                "automation_grant_id": grant["grant_id"],
                "automation_grant_revision": grant["revision"],
                "automation_grant_fingerprint": grant_fingerprint,
                "analysis_run_id": input_receipt.analysis_run_id,
                "analysis_run_fingerprint": input_receipt.analysis_run_fingerprint,
                "root_receipt_id": scope.history_root.root_receipt_id,
                "root_receipt_fingerprint": scope.history_root.fingerprint,
                "selection_revision_id": scope.selection_revision.selection_revision_id,
                "selection_revision_fingerprint": scope.selection_revision.fingerprint,
                "prepared_scope_id": scope.prepared_scope_id,
                "prepared_scope_fingerprint": scope.fingerprint,
                "completion_request_id": request.completion_request_id,
                "completion_request_fingerprint": request.fingerprint,
                "seal_draft_id": draft.seal_draft_id,
                "seal_draft_fingerprint": draft.fingerprint,
                "sealed_batch_id": sealed.sealed_batch_id,
                "sealed_batch_fingerprint": sealed.fingerprint,
                "authorization_fingerprint": authorization_fingerprint,
                "authorization_tag": tag,
            },
        )
        self._insert_row(
            connection,
            "temporal_completion_requests",
            {
                "completion_request_id": request.completion_request_id,
                "operation_id": operation_id,
                "contract_version": request.contract_version,
                "prepared_scope_id": scope.prepared_scope_id,
                "prepared_scope_fingerprint": scope.fingerprint,
                "analysis_input_receipt_id": input_receipt.input_receipt_id,
                "analysis_input_fingerprint": input_receipt.fingerprint,
                "analysis_run_id": input_receipt.analysis_run_id,
                "analysis_run_fingerprint": input_receipt.analysis_run_fingerprint,
                "completion_request_fingerprint": request.fingerprint,
                "captured_at_us": _to_us(input_receipt.captured_at),
                "synthetic_test_only": 1,
                "product_history_eligible": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )
        self._insert_input_locked(connection, request.completion_request_id, input_receipt)
        self._insert_revision_locked(connection, request.completion_request_id, revision)
        for ordinal, identity in enumerate(identities):
            self._insert_identity_locked(
                connection, request.completion_request_id, ordinal, identity
            )
        self._insert_batch_locked(connection, request.completion_request_id, batch)
        for ordinal, observation in enumerate(batch.observations):
            self._insert_observation_locked(
                connection,
                completion_request_id=request.completion_request_id,
                batch_id=batch.batch_id,
                ordinal=ordinal,
                observation=observation,
            )
        self._insert_draft_locked(connection, request.completion_request_id, draft)
        connection.executemany(
            """INSERT INTO temporal_seal_observation_commitments(
                   seal_draft_id,ordinal,observation_id,observation_fingerprint
               ) VALUES (?,?,?,?)""",
            (
                (draft.seal_draft_id, ordinal, observation.observation_id, observation.fingerprint)
                for ordinal, observation in enumerate(batch.observations)
            ),
        )
        connection.executemany(
            """INSERT INTO temporal_seal_graph_commitments(
                   seal_draft_id,ordinal,graph_fingerprint
               ) VALUES (?,?,?)""",
            (
                (draft.seal_draft_id, ordinal, fingerprint)
                for ordinal, fingerprint in enumerate(sealed.ordered_graph_fingerprints)
            ),
        )
        self._insert_row(
            connection,
            "temporal_sealed_batch_roots",
            {
                "sealed_batch_id": sealed.sealed_batch_id,
                "completion_request_id": request.completion_request_id,
                "seal_draft_id": draft.seal_draft_id,
                "contract_version": sealed.contract_version,
                "prepared_scope_fingerprint": sealed.prepared_scope_fingerprint,
                "completion_request_fingerprint": sealed.completion_request_fingerprint,
                "seal_draft_fingerprint": sealed.seal_draft_fingerprint,
                "repository_verifier_version": sealed.repository_verifier_version,
                "repository_verifier_fingerprint": sealed.repository_verifier_fingerprint,
                "sealed_at_us": _to_us(sealed.sealed_at),
                "graph_fingerprint_count": len(sealed.ordered_graph_fingerprints),
                "source_authority_state": sealed.source_authority_state.value,
                "repository_owned": 1,
                "repository_graph_verified": 1,
                "repository_sealed": 1,
                "source_authority_verified": 0,
                "product_history_eligible": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
                "sealed_batch_fingerprint": sealed.fingerprint,
            },
        )

    def _insert_input_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        value: AnalysisInputReceiptV2,
    ) -> None:
        self._insert_row(
            connection,
            "temporal_analysis_inputs",
            {
                "completion_request_id": completion_request_id,
                "contract_version": value.contract_version,
                "input_receipt_id": value.input_receipt_id,
                "input_fingerprint": value.fingerprint,
                "provenance_fingerprint": value.provenance_fingerprint,
                "root_receipt_id": value.root_receipt_id,
                "root_receipt_fingerprint": value.root_receipt_fingerprint,
                "selection_revision_id": value.selection_revision_id,
                "selection_revision_fingerprint": value.selection_revision_fingerprint,
                "selection_scope_fingerprint": value.selection_scope_fingerprint,
                "analysis_run_id": value.analysis_run_id,
                "analysis_run_fingerprint": value.analysis_run_fingerprint,
                "analysis_run_fingerprint_version": value.analysis_run_fingerprint_version,
                "analysis_run_request_fingerprint": value.analysis_run_request_fingerprint,
                "project_id": value.project_id,
                "session_id": value.session_id,
                "selected_metric_count": len(value.selected_metric_keys),
                "analysis_window_fingerprint": value.analysis_window_fingerprint,
                "analysis_window_fingerprint_basis": value.analysis_window_fingerprint_basis.value,
                "analysis_window_fingerprint_version": value.analysis_window_fingerprint_version,
                "selected_window_manifest_root": value.selected_window_manifest_root,
                "selected_window_manifest_version": value.selected_window_manifest_version,
                "selected_window_manifest_entry_count": value.selected_window_manifest_entry_count,
                "selected_window_manifest_identity_fingerprint": value.selected_window_manifest_identity_fingerprint,
                "observed_source_manifest_root": value.post_floor_observed_allowlisted_source_manifest_root,
                "observed_source_manifest_version": value.post_floor_observed_allowlisted_source_manifest_version,
                "observed_source_manifest_entry_count": value.post_floor_observed_allowlisted_source_manifest_entry_count,
                "observed_source_manifest_identity_fingerprint": value.post_floor_observed_allowlisted_source_manifest_identity_fingerprint,
                "successfully_extracted_source_entry_count": value.successfully_extracted_source_entry_count,
                "selection_eligible_entry_count": value.selection_eligible_entry_count,
                "extraction_completeness": value.extraction_completeness.value,
                "selection_coverage": value.selection_coverage.value,
                "analysis_window_started_at_us": _to_us(value.analysis_window_started_at),
                "analysis_window_ended_at_us": _to_us(value.analysis_window_ended_at),
                "analysis_run_completed_at_us": _to_us(value.analysis_run_completed_at),
                "captured_at_us": _to_us(value.captured_at),
                "capture_source": value.capture_source.value,
                "capture_contract_version": value.capture_contract_version,
                "analysis_profile_key": value.analysis_profile_key,
                "analysis_profile_version": value.analysis_profile_version,
                "analysis_profile_sha256": value.analysis_profile_sha256,
                "metric_pack_key": value.metric_pack_key,
                "metric_pack_version": value.metric_pack_version,
                "metric_pack_sha256": value.metric_pack_sha256,
                "metric_engine_version": value.metric_engine_version,
                "metric_engine_sha256": value.metric_engine_sha256,
                "metric_catalog_version": value.metric_catalog_version,
                "metric_catalog_sha256": value.metric_catalog_sha256,
                "data_tier": value.data_tier.value,
                "consent_purpose": value.consent_purpose,
                "consent_policy_version": value.consent_policy_version,
                "consent_receipt_id": value.consent_receipt_id,
                "consent_receipt_fingerprint": value.consent_receipt_fingerprint,
                "privacy_policy_version": value.privacy_policy_version,
                "provider": value.provider.value,
                "provider_version": value.provider_version,
                "provider_adapter_version": value.provider_adapter_version,
                "provider_schema_version": value.provider_schema_version,
                "source_schema_version": value.source_schema_version,
                "content_schema_version": value.content_schema_version,
                "redactor_version": value.redactor_version,
                "redactor_sha256": value.redactor_sha256,
                "preprocessing_version": value.preprocessing_version,
                "preprocessing_sha256": value.preprocessing_sha256,
                "router_version": value.router_version,
                "router_sha256": value.router_sha256,
                "model_plan_fingerprint": value.model_plan_fingerprint,
                "analysis_run_schema_version": value.analysis_run_schema_version,
                "full_run_metric_observation_count": value.full_run_metric_observation_count,
                "full_run_completed": 1,
                "direct_selected_window": 1,
                "legacy_inference_allowed": 0,
                "local_only": 1,
                "repository_sealed": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "contains_local_content": 0,
                "remote_processing_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )
        connection.executemany(
            """INSERT INTO temporal_analysis_input_selected_metrics(
                   completion_request_id,ordinal,metric_key
               ) VALUES (?,?,?)""",
            (
                (completion_request_id, ordinal, key)
                for ordinal, key in enumerate(value.selected_metric_keys)
            ),
        )

    def _insert_revision_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        value: SessionRevisionReceiptV3,
    ) -> None:
        self._insert_row(
            connection,
            "temporal_session_revisions",
            {
                "completion_request_id": completion_request_id,
                "contract_version": value.contract_version,
                "revision_id": value.revision_id,
                "revision_fingerprint": value.fingerprint,
                "root_receipt_id": value.root_receipt_id,
                "root_receipt_fingerprint": value.root_receipt_fingerprint,
                "project_id": value.project_id,
                "session_id": value.session_id,
                "revision_ordinal": value.revision_ordinal,
                "predecessor_revision_id": value.predecessor_revision_id,
                "predecessor_revision_fingerprint": value.predecessor_revision_fingerprint,
                "predecessor_link_fingerprint": value.predecessor_link_fingerprint,
                "analysis_input_receipt_id": value.analysis_input_receipt_id,
                "analysis_input_receipt_fingerprint": value.analysis_input_receipt_fingerprint,
                "input_provenance_fingerprint": value.input_provenance_fingerprint,
                "analysis_run_id": value.analysis_run_id,
                "analysis_run_fingerprint": value.analysis_run_fingerprint,
                "relation": value.relation.value,
                "selected_window_manifest_root": value.selected_window_manifest_root,
                "selected_window_manifest_version": value.selected_window_manifest_version,
                "selected_window_manifest_entry_count": value.selected_window_manifest_entry_count,
                "analysis_window_fingerprint": value.analysis_window_fingerprint,
                "analysis_window_fingerprint_basis": value.analysis_window_fingerprint_basis.value,
                "analysis_window_fingerprint_version": value.analysis_window_fingerprint_version,
                "analysis_window_started_at_us": _to_us(value.analysis_window_started_at),
                "analysis_window_ended_at_us": _to_us(value.analysis_window_ended_at),
                "effective_at_us": _to_us(value.effective_at),
                "captured_at_us": _to_us(value.captured_at),
                "effective_time_basis": value.effective_time_basis.value,
                "provenance": value.provenance.value,
                "provider": value.provider.value,
                "provider_adapter_version": value.provider_adapter_version,
                "provider_schema_version": value.provider_schema_version,
                "source_schema_version": value.source_schema_version,
                "content_schema_version": value.content_schema_version,
                "redactor_version": value.redactor_version,
                "legacy_inference_allowed": 0,
                "repository_verification_required": 1,
                "repository_sealed": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "contains_local_content": 0,
                "remote_processing_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )

    def _insert_identity_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        ordinal: int,
        value: MetricComparisonIdentity,
    ) -> None:
        trend = value.trend
        self._insert_row(
            connection,
            "temporal_comparison_identities",
            {
                "completion_request_id": completion_request_id,
                "metric_ordinal": ordinal,
                "metric_key": value.metric_key,
                "metric_definition_version": value.metric_definition_version,
                "metric_definition_sha256": value.metric_definition_sha256,
                "metric_question_version": value.metric_question_version,
                "metric_question_sha256": value.metric_question_sha256,
                "value_kind": value.value_kind.value,
                "unit_code": value.unit_code,
                "direction": value.direction.value,
                "aggregation_semantics": value.aggregation_semantics.value,
                "exposure_unit_code": value.exposure_unit_code,
                "trend_method": trend.method.value,
                "trend_rolling_observation_count": trend.rolling_observation_count,
                "trend_ewma_alpha": trend.ewma_alpha,
                "interval_method_version": value.interval_method_version,
                "evidence_tier": value.evidence_tier.value,
                "evidence_contract_version": value.evidence_contract_version,
                "estimator_kind": value.estimator_kind.value,
                "estimator_plan_version": value.estimator_plan_version,
                "estimator_plan_sha256": value.estimator_plan_sha256,
                "estimator_lifecycle": value.estimator_lifecycle.value,
                "activation_receipt_sha256": value.activation_receipt_sha256,
                "model_provider": _enum(value.model_provider),
                "requested_model_key": value.requested_model_key,
                "requested_model_revision": value.requested_model_revision,
                "served_model_key": value.served_model_key,
                "served_model_revision": value.served_model_revision,
                "served_model_fallback": (
                    None if value.served_model_fallback is None else int(value.served_model_fallback)
                ),
                "model_weight_identity_state": _enum(value.model_weight_identity_state),
                "model_weight_set_sha256": value.model_weight_set_sha256,
                "tokenizer_key": value.tokenizer_key,
                "tokenizer_revision": value.tokenizer_revision,
                "tokenizer_identity_state": _enum(value.tokenizer_identity_state),
                "tokenizer_sha256": value.tokenizer_sha256,
                "model_license_code": value.model_license_code,
                "reasoning_effort": _enum(value.reasoning_effort),
                "preprocessing_version": value.preprocessing_version,
                "preprocessing_sha256": value.preprocessing_sha256,
                "prompt_template_version": value.prompt_template_version,
                "prompt_template_sha256": value.prompt_template_sha256,
                "rubric_version": value.rubric_version,
                "rubric_sha256": value.rubric_sha256,
                "calibration_version": value.calibration_version,
                "calibration_sha256": value.calibration_sha256,
                "router_version": value.router_version,
                "router_sha256": value.router_sha256,
                "redactor_version": value.redactor_version,
                "redactor_sha256": value.redactor_sha256,
                "provider": value.provider.value,
                "provider_adapter_version": value.provider_adapter_version,
                "provider_schema_version": value.provider_schema_version,
                "source_schema_version": value.source_schema_version,
                "content_schema_version": value.content_schema_version,
                "privacy_policy_version": value.privacy_policy_version,
                "observation_contract_version": value.observation_contract_version,
                "identity_fingerprint": value.fingerprint,
            },
        )

    def _insert_batch_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        value: TemporalObservationBatchV2,
    ) -> None:
        self._insert_row(
            connection,
            "temporal_observation_batches",
            {
                "batch_id": value.batch_id,
                "contract_version": value.contract_version,
                "completion_request_id": completion_request_id,
                "project_id": value.project_id,
                "session_id": value.session_id,
                "root_receipt_id": value.root_receipt_id,
                "root_receipt_fingerprint": value.root_receipt_fingerprint,
                "revision_id": value.revision_id,
                "revision_fingerprint": value.revision_fingerprint,
                "analysis_run_id": value.analysis_run_id,
                "analysis_run_fingerprint": value.analysis_run_fingerprint,
                "analysis_input_receipt_id": value.analysis_input_receipt_id,
                "analysis_input_receipt_fingerprint": value.analysis_input_receipt_fingerprint,
                "selection_revision_id": value.selection_revision_id,
                "selection_revision_fingerprint": value.selection_revision_fingerprint,
                "scope_state": value.scope_state.value,
                "source_state": value.source_state.value,
                "selected_metric_count": len(value.selected_metric_keys),
                "batch_fingerprint": value.fingerprint,
                "recorded_at_us": _to_us(value.recorded_at),
                "observation_count": len(value.observations),
                "direct_receipt_only": 1,
                "legacy_inference_allowed": 0,
                "repository_verification_required": 1,
                "repository_sealed": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "contains_local_content": 0,
                "remote_processing_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )

    def _insert_observation_locked(
        self,
        connection: sqlite3.Connection,
        *,
        completion_request_id: str,
        batch_id: str,
        ordinal: int,
        observation: TemporalMetricObservationV2,
    ) -> None:
        uncertainty = observation.uncertainty
        kind = None if observation.value is None else observation.value.kind.value
        self._insert_row(
            connection,
            "temporal_observations",
            {
                "observation_id": observation.observation_id,
                "contract_version": observation.contract_version,
                "batch_id": batch_id,
                "completion_request_id": completion_request_id,
                "ordinal": ordinal,
                "metric_key": observation.comparison_identity.metric_key,
                "identity_fingerprint": observation.comparison_identity.fingerprint,
                "observation_fingerprint": observation.fingerprint,
                "revision_id": observation.revision_id,
                "analysis_run_id": observation.analysis_run_id,
                "analysis_input_receipt_id": observation.analysis_input_receipt_id,
                "analysis_input_receipt_fingerprint": observation.analysis_input_receipt_fingerprint,
                "selection_state": observation.selection_state.value,
                "source_state": observation.source_state.value,
                "value_state": observation.value_state.value,
                "value_kind": kind,
                "unavailable_reason_code": observation.unavailable_reason_code,
                "evidence_coverage_eligibility": observation.evidence_coverage_eligibility.value,
                "evidence_coverage_state": observation.evidence_coverage_state.value,
                "evidence_numerator": observation.evidence_numerator,
                "evidence_denominator": observation.evidence_denominator,
                "uncertainty_lower": None if uncertainty is None else uncertainty.lower,
                "uncertainty_upper": None if uncertainty is None else uncertainty.upper,
                "uncertainty_confidence": None if uncertainty is None else uncertainty.confidence_level,
                "uncertainty_method_version": None if uncertainty is None else uncertainty.method_version,
                "observed_at_us": _to_us(observation.observed_at),
                "follow_up_window_end_at_us": (
                    None
                    if observation.follow_up_window_end_at is None
                    else _to_us(observation.follow_up_window_end_at)
                ),
                "contains_local_content": 0,
                "remote_processing_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )
        if observation.value is not None:
            if not isinstance(observation.value, FractionObservationValue):
                raise DatabaseInvariantError("v21 can persist only Coaching fractions")
            self._insert_row(
                connection,
                "temporal_fraction_values",
                {
                    "observation_id": observation.observation_id,
                    "numerator": observation.value.numerator,
                    "denominator": observation.value.denominator,
                },
            )

    def _insert_draft_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        value: RepositoryTemporalBatchSealDraft,
    ) -> None:
        self._insert_row(
            connection,
            "temporal_seal_drafts",
            {
                "seal_draft_id": value.seal_draft_id,
                "contract_version": value.contract_version,
                "completion_request_id": completion_request_id,
                "batch_id": value.observation_batch.batch_id,
                "analysis_run_id": value.analysis_run_id,
                "analysis_run_fingerprint": value.analysis_run_fingerprint,
                "seal_draft_fingerprint": value.fingerprint,
                "verifier_version": value.requested_repository_verifier_version,
                "verifier_fingerprint": value.requested_repository_verifier_fingerprint,
                "drafted_at_us": _to_us(value.drafted_at),
                "observation_count": len(value.ordered_observation_ids),
                "direct_receipts_only": 1,
                "legacy_backfill_allowed": 0,
                "repository_verification_required": 1,
                "issuance_required": 1,
                "persistence_state": value.persistence_state,
                "repository_verified": 0,
                "repository_sealed": 0,
                "comparison_allowed": 0,
                "snapshot_materialization_allowed": 0,
                "activation_allowed": 0,
                "contains_local_content": 0,
                "remote_processing_allowed": 0,
                "private_export_allowed": 0,
                "team_share_allowed": 0,
            },
        )

    def _hydrate_input_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
    ) -> AnalysisInputReceiptV2:
        row = connection.execute(
            "SELECT * FROM temporal_analysis_inputs WHERE completion_request_id=?",
            (completion_request_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal analysis input is missing")
        metric_rows = connection.execute(
            """SELECT ordinal,metric_key FROM temporal_analysis_input_selected_metrics
               WHERE completion_request_id=? ORDER BY ordinal""",
            (completion_request_id,),
        ).fetchall()
        keys = tuple(str(item["metric_key"]) for item in metric_rows)
        if tuple(item["ordinal"] for item in metric_rows) != tuple(range(len(keys))):
            raise DatabaseInvariantError("stored temporal input metric order is invalid")
        try:
            value = AnalysisInputReceiptV2(
                contract_version=row["contract_version"],
                input_receipt_id=row["input_receipt_id"],
                root_receipt_id=row["root_receipt_id"],
                root_receipt_fingerprint=row["root_receipt_fingerprint"],
                selection_revision_id=row["selection_revision_id"],
                selection_revision_fingerprint=row["selection_revision_fingerprint"],
                selection_scope_fingerprint=row["selection_scope_fingerprint"],
                analysis_run_id=row["analysis_run_id"],
                analysis_run_fingerprint=row["analysis_run_fingerprint"],
                analysis_run_fingerprint_version=row["analysis_run_fingerprint_version"],
                analysis_run_request_fingerprint=row["analysis_run_request_fingerprint"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                selected_metric_keys=keys,
                analysis_window_fingerprint=row["analysis_window_fingerprint"],
                analysis_window_fingerprint_basis=row["analysis_window_fingerprint_basis"],
                analysis_window_fingerprint_version=row["analysis_window_fingerprint_version"],
                selected_window_manifest_root=row["selected_window_manifest_root"],
                selected_window_manifest_version=row["selected_window_manifest_version"],
                selected_window_manifest_entry_count=row["selected_window_manifest_entry_count"],
                selected_window_manifest_identity_fingerprint=row["selected_window_manifest_identity_fingerprint"],
                post_floor_observed_allowlisted_source_manifest_root=row["observed_source_manifest_root"],
                post_floor_observed_allowlisted_source_manifest_version=row["observed_source_manifest_version"],
                post_floor_observed_allowlisted_source_manifest_entry_count=row["observed_source_manifest_entry_count"],
                post_floor_observed_allowlisted_source_manifest_identity_fingerprint=row["observed_source_manifest_identity_fingerprint"],
                successfully_extracted_source_entry_count=row["successfully_extracted_source_entry_count"],
                selection_eligible_entry_count=row["selection_eligible_entry_count"],
                extraction_completeness=row["extraction_completeness"],
                selection_coverage=row["selection_coverage"],
                analysis_window_started_at=_from_us(row["analysis_window_started_at_us"]),
                analysis_window_ended_at=_from_us(row["analysis_window_ended_at_us"]),
                analysis_run_completed_at=_from_us(row["analysis_run_completed_at_us"]),
                captured_at=_from_us(row["captured_at_us"]),
                capture_source=row["capture_source"],
                capture_contract_version=row["capture_contract_version"],
                analysis_profile_key=row["analysis_profile_key"],
                analysis_profile_version=row["analysis_profile_version"],
                analysis_profile_sha256=row["analysis_profile_sha256"],
                metric_pack_key=row["metric_pack_key"],
                metric_pack_version=row["metric_pack_version"],
                metric_pack_sha256=row["metric_pack_sha256"],
                metric_engine_version=row["metric_engine_version"],
                metric_engine_sha256=row["metric_engine_sha256"],
                metric_catalog_version=row["metric_catalog_version"],
                metric_catalog_sha256=row["metric_catalog_sha256"],
                data_tier=row["data_tier"],
                consent_purpose=row["consent_purpose"],
                consent_policy_version=row["consent_policy_version"],
                consent_receipt_id=row["consent_receipt_id"],
                consent_receipt_fingerprint=row["consent_receipt_fingerprint"],
                privacy_policy_version=row["privacy_policy_version"],
                provider=row["provider"],
                provider_version=row["provider_version"],
                provider_adapter_version=row["provider_adapter_version"],
                provider_schema_version=row["provider_schema_version"],
                source_schema_version=row["source_schema_version"],
                content_schema_version=row["content_schema_version"],
                redactor_version=row["redactor_version"],
                redactor_sha256=row["redactor_sha256"],
                preprocessing_version=row["preprocessing_version"],
                preprocessing_sha256=row["preprocessing_sha256"],
                router_version=row["router_version"],
                router_sha256=row["router_sha256"],
                model_plan_fingerprint=row["model_plan_fingerprint"],
                analysis_run_schema_version=row["analysis_run_schema_version"],
                full_run_metric_observation_count=row["full_run_metric_observation_count"],
                full_run_completed=bool(row["full_run_completed"]),
                direct_selected_window=bool(row["direct_selected_window"]),
                legacy_inference_allowed=bool(row["legacy_inference_allowed"]),
                local_only=bool(row["local_only"]),
                sealed=bool(row["repository_sealed"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(row["snapshot_materialization_allowed"]),
                activation_allowed=bool(row["activation_allowed"]),
                contains_local_content=bool(row["contains_local_content"]),
                remote_processing_allowed=bool(row["remote_processing_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal analysis input failed validation") from None
        if (
            len(keys) != row["selected_metric_count"]
            or value.fingerprint != row["input_fingerprint"]
            or value.provenance_fingerprint != row["provenance_fingerprint"]
        ):
            raise DatabaseInvariantError("stored temporal analysis input fingerprint mismatch")
        return value

    def _hydrate_revision_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
    ) -> SessionRevisionReceiptV3:
        row = connection.execute(
            "SELECT * FROM temporal_session_revisions WHERE completion_request_id=?",
            (completion_request_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal session revision is missing")
        try:
            value = SessionRevisionReceiptV3(
                contract_version=row["contract_version"],
                revision_id=row["revision_id"],
                root_receipt_id=row["root_receipt_id"],
                root_receipt_fingerprint=row["root_receipt_fingerprint"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                revision_ordinal=row["revision_ordinal"],
                predecessor_revision_id=row["predecessor_revision_id"],
                predecessor_revision_fingerprint=row["predecessor_revision_fingerprint"],
                predecessor_link_fingerprint=row["predecessor_link_fingerprint"],
                analysis_input_receipt_id=row["analysis_input_receipt_id"],
                analysis_input_receipt_fingerprint=row["analysis_input_receipt_fingerprint"],
                input_provenance_fingerprint=row["input_provenance_fingerprint"],
                analysis_run_id=row["analysis_run_id"],
                analysis_run_fingerprint=row["analysis_run_fingerprint"],
                relation=row["relation"],
                selected_window_manifest_root=row["selected_window_manifest_root"],
                selected_window_manifest_version=row["selected_window_manifest_version"],
                selected_window_manifest_entry_count=row["selected_window_manifest_entry_count"],
                analysis_window_fingerprint=row["analysis_window_fingerprint"],
                analysis_window_fingerprint_basis=row["analysis_window_fingerprint_basis"],
                analysis_window_fingerprint_version=row["analysis_window_fingerprint_version"],
                analysis_window_started_at=_from_us(row["analysis_window_started_at_us"]),
                analysis_window_ended_at=_from_us(row["analysis_window_ended_at_us"]),
                effective_at=_from_us(row["effective_at_us"]),
                captured_at=_from_us(row["captured_at_us"]),
                effective_time_basis=row["effective_time_basis"],
                provenance=row["provenance"],
                provider=row["provider"],
                provider_adapter_version=row["provider_adapter_version"],
                provider_schema_version=row["provider_schema_version"],
                source_schema_version=row["source_schema_version"],
                content_schema_version=row["content_schema_version"],
                redactor_version=row["redactor_version"],
                legacy_inference_allowed=bool(row["legacy_inference_allowed"]),
                repository_verification_required=bool(row["repository_verification_required"]),
                sealed=bool(row["repository_sealed"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(row["snapshot_materialization_allowed"]),
                activation_allowed=bool(row["activation_allowed"]),
                contains_local_content=bool(row["contains_local_content"]),
                remote_processing_allowed=bool(row["remote_processing_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal session revision failed validation") from None
        if value.fingerprint != row["revision_fingerprint"]:
            raise DatabaseInvariantError("stored temporal session revision fingerprint mismatch")
        return value

    def _validate_revision_chain_locked(
        self,
        connection: sqlite3.Connection,
        leaf: SessionRevisionReceiptV3,
    ) -> None:
        """Recompute every predecessor instead of trusting linked aggregates."""

        current = leaf
        seen = {current.revision_id}
        while current.predecessor_revision_id is not None:
            predecessor_row = connection.execute(
                """SELECT completion_request_id
                   FROM temporal_session_revisions WHERE revision_id=?""",
                (current.predecessor_revision_id,),
            ).fetchone()
            if predecessor_row is None:
                raise DatabaseInvariantError(
                    "stored temporal revision predecessor is missing"
                )
            predecessor = self._hydrate_revision_locked(
                connection, str(predecessor_row["completion_request_id"])
            )
            if (
                predecessor.revision_id in seen
                or predecessor.fingerprint
                != current.predecessor_revision_fingerprint
                or predecessor.root_receipt_id != current.root_receipt_id
                or predecessor.root_receipt_fingerprint
                != current.root_receipt_fingerprint
                or predecessor.project_id != current.project_id
                or predecessor.session_id != current.session_id
                or predecessor.revision_ordinal != current.revision_ordinal - 1
                or current.captured_at < predecessor.captured_at
                or current.effective_at < predecessor.effective_at
                or current.analysis_window_ended_at
                < predecessor.analysis_window_ended_at
            ):
                raise DatabaseInvariantError(
                    "stored temporal revision predecessor chain is invalid"
                )
            seen.add(predecessor.revision_id)
            current = predecessor
        if current.revision_ordinal != 1 or len(seen) != leaf.revision_ordinal:
            raise DatabaseInvariantError(
                "stored temporal revision predecessor chain is incomplete"
            )

    @staticmethod
    def _hydrate_run_results_locked(
        connection: sqlite3.Connection,
        analysis_run_id: str,
    ) -> tuple[SessionAnalysisResultRecord, ...]:
        """Revalidate immutable P1 result rows before trusting observations."""

        rows = connection.execute(
            """SELECT * FROM session_analysis_results
               WHERE run_id=? ORDER BY key,version""",
            (analysis_run_id,),
        ).fetchall()
        results: list[SessionAnalysisResultRecord] = []
        for row in rows:
            evidence_rows = connection.execute(
                """SELECT ordinal,message_id,origin
                   FROM session_analysis_result_evidence
                   WHERE run_id=? AND key=? AND version=? ORDER BY ordinal""",
                (analysis_run_id, row["key"], row["version"]),
            ).fetchall()
            signal_rows = connection.execute(
                """SELECT ordinal,code,status,signal_count
                   FROM session_analysis_result_signals
                   WHERE run_id=? AND key=? AND version=? ORDER BY ordinal""",
                (analysis_run_id, row["key"], row["version"]),
            ).fetchall()
            computed_at = _from_stored_iso(row["computed_at"])
            if tuple(item["ordinal"] for item in evidence_rows) != tuple(
                range(len(evidence_rows))
            ) or tuple(item["ordinal"] for item in signal_rows) != tuple(
                range(len(signal_rows))
            ):
                raise DatabaseInvariantError(
                    "stored temporal source result child order is invalid"
                )
            try:
                results.append(
                    SessionAnalysisResultRecord(
                        observation=MetricObservation(
                            key=row["key"],
                            version=row["version"],
                            numeric_value=row["numeric_value"],
                            unit=row["unit"],
                            source=MetricSource(row["source"]),
                            observed_count=row["observed_count"],
                            eligible_count=row["eligible_count"],
                            coverage=row["coverage"],
                            confidence=row["confidence"],
                        ),
                        value_state=MetricValueState(row["value_state"]),
                        direction=SessionMetricDirection(row["direction"]),
                        applicability=SessionMetricApplicability(
                            row["applicability"]
                        ),
                        aggregation_method=SessionMetricAggregation(
                            row["aggregation_method"]
                        ),
                        metric_schema_version=row["metric_schema_version"],
                        evidence_data_tier=DataTier(row["evidence_data_tier"]),
                        fraction_numerator=row["fraction_numerator"],
                        fraction_denominator=row["fraction_denominator"],
                        evidence=tuple(
                            SessionAnalysisEvidenceRecord(
                                message_id=item["message_id"],
                                origin=SessionEvidenceOrigin(item["origin"]),
                            )
                            for item in evidence_rows
                        ),
                        signals=tuple(
                            SessionAnalysisSignalRecord(
                                code=item["code"],
                                status=SessionMetricSignalStatus(item["status"]),
                                count=item["signal_count"],
                            )
                            for item in signal_rows
                        ),
                        explanation_code=row["explanation_code"],
                        error_code=row["error_code"],
                        algorithm_id=row["algorithm_id"],
                        algorithm_version=row["algorithm_version"],
                        model_id=row["model_id"],
                        model_revision=row["model_revision"],
                        model_license=row["model_license"],
                        tokenizer_id=row["tokenizer_id"],
                        prompt_version=row["prompt_version"],
                        rubric_version=row["rubric_version"],
                        computed_at=computed_at,
                    )
                )
            except Exception:
                raise DatabaseInvariantError(
                    "stored temporal source result failed validation"
                ) from None
        return tuple(results)

    def _hydrate_identities_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
    ) -> tuple[MetricComparisonIdentity, ...]:
        rows = connection.execute(
            """SELECT * FROM temporal_comparison_identities
               WHERE completion_request_id=? ORDER BY metric_ordinal""",
            (completion_request_id,),
        ).fetchall()
        identities: list[MetricComparisonIdentity] = []
        for expected_ordinal, row in enumerate(rows):
            if row["metric_ordinal"] != expected_ordinal:
                raise DatabaseInvariantError("stored comparison identity order is invalid")
            try:
                value = MetricComparisonIdentity(
                    metric_key=row["metric_key"],
                    metric_definition_version=row["metric_definition_version"],
                    metric_definition_sha256=row["metric_definition_sha256"],
                    metric_question_version=row["metric_question_version"],
                    metric_question_sha256=row["metric_question_sha256"],
                    value_kind=row["value_kind"],
                    unit_code=row["unit_code"],
                    direction=row["direction"],
                    aggregation_semantics=row["aggregation_semantics"],
                    exposure_unit_code=row["exposure_unit_code"],
                    trend=TemporalTrendSpec(
                        method=row["trend_method"],
                        rolling_observation_count=row["trend_rolling_observation_count"],
                        ewma_alpha=row["trend_ewma_alpha"],
                    ),
                    interval_method_version=row["interval_method_version"],
                    evidence_tier=row["evidence_tier"],
                    evidence_contract_version=row["evidence_contract_version"],
                    estimator_kind=row["estimator_kind"],
                    estimator_plan_version=row["estimator_plan_version"],
                    estimator_plan_sha256=row["estimator_plan_sha256"],
                    estimator_lifecycle=row["estimator_lifecycle"],
                    activation_receipt_sha256=row["activation_receipt_sha256"],
                    model_provider=row["model_provider"],
                    requested_model_key=row["requested_model_key"],
                    requested_model_revision=row["requested_model_revision"],
                    served_model_key=row["served_model_key"],
                    served_model_revision=row["served_model_revision"],
                    served_model_fallback=(
                        None if row["served_model_fallback"] is None else bool(row["served_model_fallback"])
                    ),
                    model_weight_identity_state=row["model_weight_identity_state"],
                    model_weight_set_sha256=row["model_weight_set_sha256"],
                    tokenizer_key=row["tokenizer_key"],
                    tokenizer_revision=row["tokenizer_revision"],
                    tokenizer_identity_state=row["tokenizer_identity_state"],
                    tokenizer_sha256=row["tokenizer_sha256"],
                    model_license_code=row["model_license_code"],
                    reasoning_effort=row["reasoning_effort"],
                    preprocessing_version=row["preprocessing_version"],
                    preprocessing_sha256=row["preprocessing_sha256"],
                    prompt_template_version=row["prompt_template_version"],
                    prompt_template_sha256=row["prompt_template_sha256"],
                    rubric_version=row["rubric_version"],
                    rubric_sha256=row["rubric_sha256"],
                    calibration_version=row["calibration_version"],
                    calibration_sha256=row["calibration_sha256"],
                    router_version=row["router_version"],
                    router_sha256=row["router_sha256"],
                    redactor_version=row["redactor_version"],
                    redactor_sha256=row["redactor_sha256"],
                    provider=row["provider"],
                    provider_adapter_version=row["provider_adapter_version"],
                    provider_schema_version=row["provider_schema_version"],
                    source_schema_version=row["source_schema_version"],
                    content_schema_version=row["content_schema_version"],
                    privacy_policy_version=row["privacy_policy_version"],
                    observation_contract_version=row["observation_contract_version"],
                )
            except Exception:
                raise DatabaseInvariantError("stored comparison identity failed validation") from None
            if value.fingerprint != row["identity_fingerprint"]:
                raise DatabaseInvariantError("stored comparison identity fingerprint mismatch")
            identities.append(value)
        return tuple(identities)

    def _hydrate_batch_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
        identities: tuple[MetricComparisonIdentity, ...],
    ) -> TemporalObservationBatchV2:
        row = connection.execute(
            "SELECT * FROM temporal_observation_batches WHERE completion_request_id=?",
            (completion_request_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal observation batch is missing")
        identity_by_key = {identity.metric_key: identity for identity in identities}
        observation_rows = connection.execute(
            """SELECT * FROM temporal_observations WHERE batch_id=? ORDER BY ordinal""",
            (row["batch_id"],),
        ).fetchall()
        observations: list[TemporalMetricObservationV2] = []
        for expected_ordinal, stored in enumerate(observation_rows):
            if (
                stored["ordinal"] != expected_ordinal
                or stored["completion_request_id"] != completion_request_id
            ):
                raise DatabaseInvariantError("stored temporal observation order is invalid")
            identity = identity_by_key.get(str(stored["metric_key"]))
            if identity is None or identity.fingerprint != stored["identity_fingerprint"]:
                raise DatabaseInvariantError("stored temporal observation identity is invalid")
            if connection.execute(
                """SELECT 1
                   FROM (
                       SELECT observation_id FROM temporal_count_exposure_values
                       UNION ALL
                       SELECT observation_id FROM temporal_distribution_sample_values
                       UNION ALL
                       SELECT observation_id FROM temporal_sampled_proportion_values
                   ) unsupported
                   WHERE observation_id=? LIMIT 1""",
                (stored["observation_id"],),
            ).fetchone() is not None:
                raise DatabaseInvariantError(
                    "v21 stored an unsupported temporal value subtype"
                )
            value = None
            if stored["value_kind"] is not None:
                if stored["value_kind"] != "fraction":
                    raise DatabaseInvariantError("v21 stored a non-fraction observation")
                fraction = connection.execute(
                    "SELECT numerator,denominator FROM temporal_fraction_values WHERE observation_id=?",
                    (stored["observation_id"],),
                ).fetchone()
                if fraction is None:
                    raise DatabaseInvariantError("stored temporal fraction is missing")
                value = FractionObservationValue(
                    numerator=fraction["numerator"], denominator=fraction["denominator"]
                )
            elif connection.execute(
                "SELECT 1 FROM temporal_fraction_values WHERE observation_id=?",
                (stored["observation_id"],),
            ).fetchone() is not None:
                raise DatabaseInvariantError("unavailable observation carries a fraction")
            uncertainty = None
            if stored["uncertainty_lower"] is not None:
                uncertainty = TemporalUncertainty(
                    lower=stored["uncertainty_lower"],
                    upper=stored["uncertainty_upper"],
                    confidence_level=stored["uncertainty_confidence"],
                    method_version=stored["uncertainty_method_version"],
                )
            try:
                observation = TemporalMetricObservationV2(
                    contract_version=stored["contract_version"],
                    observation_id=stored["observation_id"],
                    revision_id=stored["revision_id"],
                    analysis_run_id=stored["analysis_run_id"],
                    analysis_input_receipt_id=stored["analysis_input_receipt_id"],
                    analysis_input_receipt_fingerprint=stored["analysis_input_receipt_fingerprint"],
                    comparison_identity=identity,
                    selection_state=stored["selection_state"],
                    source_state=stored["source_state"],
                    value_state=stored["value_state"],
                    value=value,
                    unavailable_reason_code=stored["unavailable_reason_code"],
                    evidence_coverage_eligibility=stored["evidence_coverage_eligibility"],
                    evidence_coverage_state=stored["evidence_coverage_state"],
                    evidence_numerator=stored["evidence_numerator"],
                    evidence_denominator=stored["evidence_denominator"],
                    uncertainty=uncertainty,
                    observed_at=_from_us(stored["observed_at_us"]),
                    follow_up_window_end_at=(
                        None
                        if stored["follow_up_window_end_at_us"] is None
                        else _from_us(stored["follow_up_window_end_at_us"])
                    ),
                    contains_local_content=bool(stored["contains_local_content"]),
                    remote_processing_allowed=bool(stored["remote_processing_allowed"]),
                    private_export_allowed=bool(stored["private_export_allowed"]),
                    team_share_allowed=bool(stored["team_share_allowed"]),
                )
            except Exception:
                raise DatabaseInvariantError("stored temporal observation failed validation") from None
            if observation.fingerprint != stored["observation_fingerprint"]:
                raise DatabaseInvariantError("stored temporal observation fingerprint mismatch")
            observations.append(observation)
        try:
            batch = TemporalObservationBatchV2(
                contract_version=row["contract_version"],
                batch_id=row["batch_id"],
                project_id=row["project_id"],
                session_id=row["session_id"],
                root_receipt_id=row["root_receipt_id"],
                root_receipt_fingerprint=row["root_receipt_fingerprint"],
                revision_id=row["revision_id"],
                revision_fingerprint=row["revision_fingerprint"],
                analysis_run_id=row["analysis_run_id"],
                analysis_run_fingerprint=row["analysis_run_fingerprint"],
                analysis_input_receipt_id=row["analysis_input_receipt_id"],
                analysis_input_receipt_fingerprint=row["analysis_input_receipt_fingerprint"],
                selection_revision_id=row["selection_revision_id"],
                selection_revision_fingerprint=row["selection_revision_fingerprint"],
                scope_state=row["scope_state"],
                source_state=row["source_state"],
                selected_metric_keys=tuple(identity.metric_key for identity in identities),
                observations=tuple(observations),
                recorded_at=_from_us(row["recorded_at_us"]),
                direct_receipt_only=bool(row["direct_receipt_only"]),
                legacy_inference_allowed=bool(row["legacy_inference_allowed"]),
                repository_verification_required=bool(row["repository_verification_required"]),
                sealed=bool(row["repository_sealed"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(row["snapshot_materialization_allowed"]),
                activation_allowed=bool(row["activation_allowed"]),
                contains_local_content=bool(row["contains_local_content"]),
                remote_processing_allowed=bool(row["remote_processing_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal batch failed validation") from None
        if (
            len(identities) != row["selected_metric_count"]
            or len(observations) != row["observation_count"]
            or batch.fingerprint != row["batch_fingerprint"]
        ):
            raise DatabaseInvariantError("stored temporal batch fingerprint mismatch")
        return batch

    def _hydrate_request_locked(
        self,
        connection: sqlite3.Connection,
        completion_request_id: str,
    ) -> SyntheticTemporalCompletionRequestV1:
        row = connection.execute(
            "SELECT * FROM temporal_completion_requests WHERE completion_request_id=?",
            (completion_request_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored temporal completion request is missing")
        scope = self._hydrate_scope_locked(connection, row["prepared_scope_id"])
        analysis_input = self._hydrate_input_locked(connection, completion_request_id)
        try:
            request = SyntheticTemporalCompletionRequestV1(
                contract_version=row["contract_version"],
                completion_request_id=row["completion_request_id"],
                prepared_scope=scope,
                analysis_input=analysis_input,
                analysis_run_id=row["analysis_run_id"],
                synthetic_test_only=bool(row["synthetic_test_only"]),
                product_history_eligible=bool(row["product_history_eligible"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(row["snapshot_materialization_allowed"]),
                activation_allowed=bool(row["activation_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal request failed validation") from None
        if (
            request.fingerprint != row["completion_request_fingerprint"]
            or scope.fingerprint != row["prepared_scope_fingerprint"]
            or analysis_input.input_receipt_id != row["analysis_input_receipt_id"]
            or analysis_input.fingerprint != row["analysis_input_fingerprint"]
            or analysis_input.analysis_run_fingerprint != row["analysis_run_fingerprint"]
            or analysis_input.captured_at != _from_us(row["captured_at_us"])
        ):
            raise DatabaseInvariantError("stored temporal request fingerprint mismatch")
        return request

    def _hydrate_sealed_locked(
        self,
        connection: sqlite3.Connection,
        sealed_batch_id: str,
        *,
        validate_source: bool = True,
    ) -> RepositorySealedTemporalBatchV1:
        row = connection.execute(
            "SELECT * FROM temporal_sealed_batch_roots WHERE sealed_batch_id=?",
            (sealed_batch_id,),
        ).fetchone()
        if row is None:
            raise DatabaseInvariantError("stored sealed temporal batch is missing")
        request = self._hydrate_request_locked(
            connection, str(row["completion_request_id"])
        )
        if validate_source:
            self._validate_stored_sealed_source_locked(connection, request)
        revision = self._hydrate_revision_locked(
            connection, request.completion_request_id
        )
        self._validate_revision_chain_locked(connection, revision)
        identities = self._hydrate_identities_locked(
            connection, request.completion_request_id
        )
        expected_identities = self._identity_catalog.build_for_synthetic_request(request)
        if identities != expected_identities:
            raise DatabaseInvariantError("stored identities differ from Coaching catalog")
        batch = self._hydrate_batch_locked(
            connection, request.completion_request_id, identities
        )
        source_results = self._hydrate_run_results_locked(
            connection, request.analysis_run_id
        )
        source_by_key = self._result_map(
            source_results,
            request.prepared_scope.selection_revision.selected_metric_keys,
            request.analysis_input.captured_at,
        )
        expected_observations = tuple(
            self._observation_from_result(
                result=source_by_key[identity.metric_key],
                identity=identity,
                revision=revision,
                input_receipt=request.analysis_input,
                observation_id=batch.observations[ordinal].observation_id,
            )
            for ordinal, identity in enumerate(identities)
        )
        if expected_observations != batch.observations:
            raise DatabaseInvariantError(
                "stored observations differ from immutable Coaching results"
            )
        draft_row = connection.execute(
            "SELECT * FROM temporal_seal_drafts WHERE seal_draft_id=?",
            (row["seal_draft_id"],),
        ).fetchone()
        if draft_row is None:
            raise DatabaseInvariantError("stored temporal seal draft is missing")
        if (
            draft_row["completion_request_id"] != request.completion_request_id
            or draft_row["batch_id"] != batch.batch_id
        ):
            raise DatabaseInvariantError("stored temporal seal draft lineage is invalid")
        commitments = connection.execute(
            """SELECT ordinal,observation_id,observation_fingerprint
               FROM temporal_seal_observation_commitments
               WHERE seal_draft_id=? ORDER BY ordinal""",
            (draft_row["seal_draft_id"],),
        ).fetchall()
        if tuple(item["ordinal"] for item in commitments) != tuple(
            range(len(commitments))
        ):
            raise DatabaseInvariantError("stored observation commitment order is invalid")
        try:
            draft = RepositoryTemporalBatchSealDraft(
                contract_version=draft_row["contract_version"],
                seal_draft_id=draft_row["seal_draft_id"],
                history_root=request.prepared_scope.history_root,
                selection_revision=request.prepared_scope.selection_revision,
                analysis_input=request.analysis_input,
                session_revision=revision,
                observation_batch=batch,
                analysis_run_id=draft_row["analysis_run_id"],
                analysis_run_fingerprint=draft_row["analysis_run_fingerprint"],
                ordered_observation_ids=tuple(
                    str(item["observation_id"]) for item in commitments
                ),
                ordered_observation_fingerprints=tuple(
                    str(item["observation_fingerprint"]) for item in commitments
                ),
                requested_repository_verifier_version=draft_row["verifier_version"],
                requested_repository_verifier_fingerprint=draft_row["verifier_fingerprint"],
                drafted_at=_from_us(draft_row["drafted_at_us"]),
                direct_receipts_only=bool(draft_row["direct_receipts_only"]),
                legacy_backfill_allowed=bool(draft_row["legacy_backfill_allowed"]),
                repository_verification_required=bool(draft_row["repository_verification_required"]),
                issuance_required=bool(draft_row["issuance_required"]),
                persistence_state=draft_row["persistence_state"],
                repository_verified=bool(draft_row["repository_verified"]),
                sealed=bool(draft_row["repository_sealed"]),
                comparison_allowed=bool(draft_row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(draft_row["snapshot_materialization_allowed"]),
                activation_allowed=bool(draft_row["activation_allowed"]),
                contains_local_content=bool(draft_row["contains_local_content"]),
                remote_processing_allowed=bool(draft_row["remote_processing_allowed"]),
                private_export_allowed=bool(draft_row["private_export_allowed"]),
                team_share_allowed=bool(draft_row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored temporal seal draft failed validation") from None
        graph_rows = connection.execute(
            """SELECT ordinal,graph_fingerprint FROM temporal_seal_graph_commitments
               WHERE seal_draft_id=? ORDER BY ordinal""",
            (draft.seal_draft_id,),
        ).fetchall()
        graph = tuple(str(item["graph_fingerprint"]) for item in graph_rows)
        if tuple(item["ordinal"] for item in graph_rows) != tuple(range(len(graph))):
            raise DatabaseInvariantError("stored graph commitment order is invalid")
        try:
            sealed = RepositorySealedTemporalBatchV1(
                contract_version=row["contract_version"],
                sealed_batch_id=row["sealed_batch_id"],
                completion_request=request,
                prepared_scope_fingerprint=row["prepared_scope_fingerprint"],
                completion_request_fingerprint=row["completion_request_fingerprint"],
                seal_draft=draft,
                seal_draft_fingerprint=row["seal_draft_fingerprint"],
                ordered_graph_fingerprints=graph,
                repository_verifier_version=row["repository_verifier_version"],
                repository_verifier_fingerprint=row["repository_verifier_fingerprint"],
                sealed_at=_from_us(row["sealed_at_us"]),
                source_authority_state=row["source_authority_state"],
                repository_owned=bool(row["repository_owned"]),
                repository_graph_verified=bool(row["repository_graph_verified"]),
                sealed=bool(row["repository_sealed"]),
                source_authority_verified=bool(row["source_authority_verified"]),
                product_history_eligible=bool(row["product_history_eligible"]),
                comparison_allowed=bool(row["comparison_allowed"]),
                snapshot_materialization_allowed=bool(row["snapshot_materialization_allowed"]),
                activation_allowed=bool(row["activation_allowed"]),
                private_export_allowed=bool(row["private_export_allowed"]),
                team_share_allowed=bool(row["team_share_allowed"]),
            )
        except Exception:
            raise DatabaseInvariantError("stored sealed temporal graph failed validation") from None
        if (
            draft.fingerprint != draft_row["seal_draft_fingerprint"]
            or len(commitments) != draft_row["observation_count"]
            or len(graph) != row["graph_fingerprint_count"]
            or sealed.fingerprint != row["sealed_batch_fingerprint"]
        ):
            raise DatabaseInvariantError("stored sealed temporal graph fingerprint mismatch")
        return sealed

    def get_sealed_batch(
        self, sealed_batch_id: str
    ) -> RepositorySealedTemporalBatchV1 | None:
        self._ensure_initialized()
        require_safe_id(sealed_batch_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                "SELECT 1 FROM temporal_sealed_batch_roots WHERE sealed_batch_id=?",
                (sealed_batch_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_sealed_locked(connection, sealed_batch_id)
            )

    def get_sealed_batch_for_run(
        self, analysis_run_id: str
    ) -> RepositorySealedTemporalBatchV1 | None:
        self._ensure_initialized()
        require_safe_id(analysis_run_id)
        with self._connection_scope(readonly=True) as connection:
            row = connection.execute(
                """SELECT sealed.sealed_batch_id
                   FROM temporal_sealed_batch_roots sealed
                   JOIN temporal_completion_requests request
                     ON request.completion_request_id=sealed.completion_request_id
                   WHERE request.analysis_run_id=?""",
                (analysis_run_id,),
            ).fetchone()
            return (
                None
                if row is None
                else self._hydrate_sealed_locked(
                    connection, str(row["sealed_batch_id"])
                )
            )


__all__ = [
    "ANALYSIS_RUN_BRIDGE_VERSION",
    "COACHING_AUTOMATION_JOB_PLAN_VERSION",
    "REPOSITORY_TEMPORAL_VERIFIER_FINGERPRINT",
    "REPOSITORY_TEMPORAL_VERIFIER_VERSION",
    "SqliteTemporalHistoryRepository",
    "analysis_run_bridge_fingerprint",
]
