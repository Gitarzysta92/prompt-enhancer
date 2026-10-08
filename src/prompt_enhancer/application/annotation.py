"""Annotation paths (ADR 0017): agents through the app's endpoint, and the central annotation server.

Path A (agent): after the person flips the allowance, any model they drive
(Codex, Claude Code, a local model) fetches the prepared metaprompt and the
sessions' redacted windows from the app's API and posts labels back; stored as
ordinary model judgments (``agent:<name>``).

Path B (central): a separate, explicit action submits redacted windows plus
pseudonymous ids to the central server (embedded locally today, VPS later,
same code as login will use). The central side annotates with its configured
active model and stores submission + labels - the dataset the owner's SaaS
collects from consenting, logged-in users. Labels come back locally as
``central:<model>`` judgments.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
import json
import os
import re
import sqlite3
import threading
from pathlib import Path
from typing import Literal

from pydantic import Field

from ..config import lexical_absolute_path, path_has_symlink_component
from ..domain import PSEUDONYM_PATTERN, Provider, StrictModel
from ..sqlite_migration_integrity import SqliteMigrationIntegrity
from .model_reply import completed_chat_content, model_json_object
from .analysis.calibration_cases import CALIBRATION_CASE_VERSION, CalibrationReviewError, PreparedCalibrationCase, prepare_calibration_case
from .analysis.calibration_ratings import CALIBRATION_METRIC_KEYS, RatingLabel
from .analysis.model_judge import (
    JUDGE_PROMPT_VERSION,
    JUDGE_WINDOW_SCHEMA_VERSION,
    MAX_WINDOW_CHARACTERS,
    ZERO_WINDOW_FINGERPRINT,
    ModelJudgeError,
    ModelJudgeService,
    ModelJudgment,
    _QUESTIONS,
    _SYSTEM_PROMPT,
    _judge_user_prompt,
    parse_judge_reply,
    render_window,
    eligible_model_judgment,
)


ANNOTATION_CONTRACT_VERSION = "annotation.v1"
CENTRAL_ANNOTATION_DATABASE_FILENAME = "central-annotations.sqlite3"
CENTRAL_ANNOTATION_SCHEMA_VERSION = 3
MAX_WORK_PAGE = 100
MAX_BATCH = 25
_MODEL_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9 ._:/+-]{0,119}$")


class AnnotationError(ValueError):
    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


class AllowanceState(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    agent_allowed: bool
    note: str = (
        "While on, models you drive may read sessions' redacted windows through this API and write labels back. "
        "Whatever model the agent runs on will see that content."
    )


class Metaprompt(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    system_prompt: str
    questions: dict[str, str]
    labels: tuple[str, ...]
    prompt_version: str
    reply_format: str


class WorkItem(StrictModel):
    session_id: str
    project_id: str | None = None
    provider: str


class WorkList(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    model_name: str
    items: tuple[WorkItem, ...]
    remaining: int = Field(ge=0)


class WorkWindow(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    session_id: str
    provider: str
    window: str
    #: Identity of the exact analysis window sealed by the source and rendered
    #: above. The agent must echo it back when it submits labels.
    window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    case_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    case_version: str = CALIBRATION_CASE_VERSION
    questions: dict[str, str]
    prompt_version: str


class SubmitAnnotation(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    model_name: str = Field(pattern=_MODEL_NAME.pattern)
    #: The ``window_fingerprint`` handed out with the window that was judged.
    #: Labels for a window that has since changed are rejected, not re-pointed.
    window_fingerprint: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    case_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_version: str | None = Field(default=None, min_length=1, max_length=64)
    labels: dict[str, RatingLabel]


class SubmitResult(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    session_id: str
    model_alias: str
    stored: int = Field(ge=0)


class RemoteSubmitRequest(StrictModel):
    limit: int = Field(default=5, ge=1, le=MAX_BATCH)


class RemoteAnnotationDisclosure(StrictModel):
    """Closed pre-send disclosure for the explicit remote annotation action."""

    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    destination: str = Field(min_length=1, max_length=2_048)
    redacted_windows_retained: Literal[True] = True
    pseudonymous_session_ids_retained: Literal[True] = True
    pseudonymous_project_ids_retained: Literal[True] = True
    raw_transcripts_sent: Literal[False] = False
    model_policy: Literal["configured_active_model_at_submission"] = "configured_active_model_at_submission"
    active_model_alias: str | None = Field(default=None, pattern=_MODEL_NAME.pattern)


class RemoteSubmitResult(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    destination: str
    submitted: int = Field(ge=0)
    annotated: int = Field(ge=0)
    model_identity: str | None = None
    stored_locally_as: str | None = None


def _sealed_window_fingerprint(context: object, *, session_id: str, provider: Provider) -> str:
    """The authoritative window identity, taken from the sealed source's own context.

    It is never recomputed from the rendered text: the source seals the window
    it read, and a judgment may only name that. The context must also own the
    session and provider it was requested for, so labels cannot be bound to a
    window belonging to some other session or run.
    """

    if getattr(context, "session_id", None) != session_id:
        raise AnnotationError("window_session_mismatch")
    try:
        if Provider(getattr(context, "provider")) is not provider:
            raise AnnotationError("window_provider_mismatch")
    except ValueError:
        raise AnnotationError("window_provider_mismatch") from None
    fingerprint = getattr(context, "analysis_window_fingerprint", None)
    if not isinstance(fingerprint, str) or PSEUDONYM_PATTERN.fullmatch(fingerprint) is None:
        raise AnnotationError("window_fingerprint_unavailable")
    if fingerprint == ZERO_WINDOW_FINGERPRINT:
        raise AnnotationError("window_fingerprint_unavailable")
    return fingerprint


def metaprompt() -> Metaprompt:
    return Metaprompt(
        system_prompt=_SYSTEM_PROMPT,
        questions=dict(_QUESTIONS),
        labels=tuple(label.value for label in RatingLabel),
        prompt_version=JUDGE_PROMPT_VERSION,
        reply_format='Reply with strict JSON only: {"<metric_key>": "<label>", ...} covering every question.',
    )


def _complete_case_sessions(rows: tuple[ModelJudgment, ...]) -> set[str]:
    grouped: dict[tuple[str, str, str, str, str], set[str]] = {}
    for row in rows:
        if eligible_model_judgment(row):
            key = (row.session_id, row.model_alias, row.model_identity, row.window_fingerprint, row.case_fingerprint)
            grouped.setdefault(key, set()).add(row.metric_key)
    return {key[0] for key, metrics in grouped.items() if metrics == set(CALIBRATION_METRIC_KEYS)}


class AnnotationService:
    """Path A: the allowance switch and the agent-facing work/submit surface."""

    def __init__(
        self,
        judge: ModelJudgeService,
        *,
        list_sessions: Callable[..., list[dict[str, object]]],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._judge = judge
        self._list_sessions = list_sessions
        self._clock = clock or (lambda: datetime.now(UTC))
        self._agent_allowed = False
        self._lock = threading.Lock()

    def allowance(self) -> AllowanceState:
        return AllowanceState(agent_allowed=self._agent_allowed)

    def set_allowance(self, agent_allowed: bool) -> AllowanceState:
        with self._lock:
            self._agent_allowed = bool(agent_allowed)
        return self.allowance()

    def _require_allowance(self) -> None:
        if not self._agent_allowed:
            raise AnnotationError("allowance_required")

    def work(self, model_name: str, limit: int = 25) -> WorkList:
        self._require_allowance()
        if _MODEL_NAME.fullmatch(model_name or "") is None:
            raise AnnotationError("model_name_invalid")
        limit = max(1, min(int(limit), MAX_WORK_PAGE))
        alias = f"agent:{model_name}"
        done = _complete_case_sessions(self._judge.repository.list(model_alias=alias))
        pending: list[WorkItem] = []
        offset = 0
        while True:
            rows = self._list_sessions(limit=200, offset=offset)
            if not rows:
                break
            for row in rows:
                sid = str(row.get("session_id"))
                if sid in done:
                    continue
                pending.append(WorkItem(session_id=sid, project_id=str(row.get("project_id")) if row.get("project_id") else None, provider=str(row.get("provider"))))
            offset += len(rows)
            if len(rows) < 200 or offset >= 2000:
                break
        return WorkList(model_name=model_name, items=tuple(pending[:limit]), remaining=len(pending))

    def window(self, session_id: str) -> WorkWindow:
        self._require_allowance()
        session = self._judge.session_lookup(session_id)
        if session is None:
            raise AnnotationError("session_not_found")
        provider = Provider(getattr(session, "provider"))
        try:
            context = self._judge.window_for(provider, session_id)
        except ModelJudgeError as error:
            raise AnnotationError(error.code) from None
        window = render_window(context)
        fingerprint = _sealed_window_fingerprint(context, session_id=session_id, provider=provider)
        try:
            case = prepare_calibration_case(session_id=session_id, provider=provider, window_fingerprint=fingerprint, rendered_window=window)
        except CalibrationReviewError:
            raise AnnotationError("window_unavailable") from None
        return WorkWindow(
            session_id=session_id,
            provider=provider.value,
            window=window,
            window_fingerprint=fingerprint,
            case_fingerprint=case.case_fingerprint,
            questions=dict(_QUESTIONS),
            prompt_version=JUDGE_PROMPT_VERSION,
        )

    def submit(self, request: SubmitAnnotation) -> SubmitResult:
        self._require_allowance()
        session = self._judge.session_lookup(request.session_id)
        if session is None:
            raise AnnotationError("session_not_found")
        unknown = set(request.labels) - set(CALIBRATION_METRIC_KEYS)
        if unknown or not request.labels:
            raise AnnotationError("labels_invalid")
        if request.window_fingerprint == ZERO_WINDOW_FINGERPRINT:
            raise AnnotationError("window_fingerprint_invalid")
        provider = Provider(getattr(session, "provider"))
        try:
            context = self._judge.window_for(provider, request.session_id)
        except ModelJudgeError as error:
            raise AnnotationError(error.code) from None
        except Exception:  # noqa: BLE001 - an unreadable window cannot be annotated
            raise AnnotationError("window_unavailable") from None
        fingerprint = _sealed_window_fingerprint(context, session_id=request.session_id, provider=provider)
        if fingerprint != request.window_fingerprint:
            # The session grew, or was re-read under a different run, since the
            # agent read it. Its labels describe a window that no longer exists.
            raise AnnotationError("window_fingerprint_mismatch")
        case = None
        if request.case_fingerprint is not None or request.case_version is not None:
            try:
                case = prepare_calibration_case(
                    session_id=request.session_id, provider=provider, window_fingerprint=fingerprint,
                    rendered_window=render_window(context),
                )
            except (CalibrationReviewError, ModelJudgeError):
                raise AnnotationError("window_unavailable") from None
            if request.case_version != case.case_version or request.case_fingerprint != case.case_fingerprint:
                raise AnnotationError("case_fingerprint_mismatch")
        alias = f"agent:{request.model_name}"[:64]
        now = self._clock()
        stored = 0
        for key, label in request.labels.items():
            self._judge.repository.upsert(
                ModelJudgment(
                    session_id=request.session_id,
                    metric_key=key,
                    label=label,
                    model_alias=alias,
                    model_identity=request.model_name[:200],
                    prompt_version=JUDGE_PROMPT_VERSION,
                    window_fingerprint=fingerprint,
                    judged_at=now,
                    case_fingerprint=case.case_fingerprint if case else None,
                    case_version=case.case_version if case else None,
                )
            )
            stored += 1
        return SubmitResult(session_id=request.session_id, model_alias=alias, stored=stored)


# ----- Path B: the central annotation server (embedded locally; same code later on the VPS) -----


class CentralBatchItem(StrictModel):
    session_id: str = Field(pattern=PSEUDONYM_PATTERN.pattern)
    project_id: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    provider: str = Field(max_length=32)
    window: str = Field(min_length=1, max_length=60_000)
    window_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_version: str | None = Field(default=None, min_length=1, max_length=64)


class CentralBatch(StrictModel):
    user_label: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$")
    items: tuple[CentralBatchItem, ...] = Field(min_length=1, max_length=MAX_BATCH)


class CentralAnnotation(StrictModel):
    session_id: str
    labels: dict[str, RatingLabel]
    window_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_fingerprint: str | None = Field(default=None, pattern=PSEUDONYM_PATTERN.pattern)
    case_version: str | None = Field(default=None, min_length=1, max_length=64)


class CentralBatchResult(StrictModel):
    contract_version: Literal[ANNOTATION_CONTRACT_VERSION] = ANNOTATION_CONTRACT_VERSION
    stored: int = Field(ge=0)
    annotations: tuple[CentralAnnotation, ...]
    model_identity: str | None = None
    prompt_version: str = JUDGE_PROMPT_VERSION


def _is_canonical_judge_window(value: str) -> bool:
    """Accept only the bounded JSON envelope produced by ``render_window``."""

    if len(value) > MAX_WINDOW_CHARACTERS or not value.lstrip().startswith("{"):
        return False
    payload = model_json_object(value, max_characters=MAX_WINDOW_CHARACTERS)
    if not isinstance(payload, dict) or set(payload) != {
        "schema",
        "authority",
        "available",
        "task_anchor_retained",
        "earlier_records_omitted",
        "records",
    }:
        return False
    records = payload.get("records")
    if (
        payload.get("schema") != JUDGE_WINDOW_SCHEMA_VERSION
        or payload.get("authority") != "untrusted_evidence"
        or payload.get("available") is not True
        or payload.get("task_anchor_retained") is not True
        or not isinstance(payload.get("earlier_records_omitted"), bool)
        or not isinstance(records, list)
        or not records
        or len(records) > 120
    ):
        return False
    sequences: list[int] = []
    for record in records:
        if not isinstance(record, dict) or set(record) != {
            "sequence",
            "role",
            "content",
        }:
            return False
        sequence = record.get("sequence")
        if (
            isinstance(sequence, bool)
            or not isinstance(sequence, int)
            or sequence < 0
            or record.get("role") not in {"user", "agent", "plan"}
            or not isinstance(record.get("content"), str)
            or not str(record["content"]).strip()
        ):
            return False
        sequences.append(sequence)
    return (
        records[0]["role"] == "user"
        and sequences == sorted(sequences)
        and len(sequences) == len(set(sequences))
    )


_CENTRAL_ANNOTATION_SCHEMA_V1 = (
    """
    CREATE TABLE central_annotations (
        user_label TEXT NOT NULL,
        session_id TEXT NOT NULL,
        project_id TEXT,
        provider TEXT NOT NULL,
        window_chars INTEGER NOT NULL,
        redacted_window TEXT NOT NULL,
        labels_json TEXT NOT NULL,
        model_identity TEXT,
        prompt_version TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        PRIMARY KEY (user_label, session_id, prompt_version)
    )
    """,
)

_CENTRAL_ANNOTATION_SCHEMA_V2 = (
    "ALTER TABLE central_annotations ADD COLUMN window_fingerprint TEXT",
    "ALTER TABLE central_annotations ADD COLUMN case_fingerprint TEXT",
    "ALTER TABLE central_annotations ADD COLUMN case_version TEXT",
)

_CENTRAL_ANNOTATION_SCHEMA_V3 = (
    """
    CREATE TABLE central_annotation_migration_checksums (
        version INTEGER PRIMARY KEY
            REFERENCES central_annotation_schema_migrations(version) ON DELETE RESTRICT
            CHECK(version > 0),
        checksum TEXT NOT NULL CHECK(
            length(checksum)=64 AND checksum NOT GLOB '*[^0-9a-f]*'
        )
    ) STRICT
    """,
)

_CENTRAL_ANNOTATION_COLUMNS_V1 = (
    "user_label",
    "session_id",
    "project_id",
    "provider",
    "window_chars",
    "redacted_window",
    "labels_json",
    "model_identity",
    "prompt_version",
    "submitted_at",
)
_CENTRAL_ANNOTATION_COLUMNS_V2 = _CENTRAL_ANNOTATION_COLUMNS_V1 + (
    "window_fingerprint",
    "case_fingerprint",
    "case_version",
)


def _normalized_central_schema_sql(value: str) -> str:
    return " ".join(value.casefold().split()).replace(
        "create table if not exists ", "create table ", 1
    )


_CENTRAL_ANNOTATION_SQL_V1 = _normalized_central_schema_sql(
    _CENTRAL_ANNOTATION_SCHEMA_V1[0]
)
_CENTRAL_ANNOTATION_SQL_V2 = _normalized_central_schema_sql(
    """
    CREATE TABLE central_annotations (
        user_label TEXT NOT NULL,
        session_id TEXT NOT NULL,
        project_id TEXT,
        provider TEXT NOT NULL,
        window_chars INTEGER NOT NULL,
        redacted_window TEXT NOT NULL,
        labels_json TEXT NOT NULL,
        model_identity TEXT,
        prompt_version TEXT NOT NULL,
        submitted_at TEXT NOT NULL,
        window_fingerprint TEXT,
        case_fingerprint TEXT,
        case_version TEXT,
        PRIMARY KEY (user_label, session_id, prompt_version)
    )
    """
)
_CENTRAL_ANNOTATION_MIGRATION_INTEGRITY = SqliteMigrationIntegrity(
    scope="central_annotation",
    ledger_table="central_annotation_schema_migrations",
    checksum_table="central_annotation_migration_checksums",
    schema_version=CENTRAL_ANNOTATION_SCHEMA_VERSION,
    checksum_introduced_version=3,
    migrations=(
        (1, _CENTRAL_ANNOTATION_SCHEMA_V1),
        (2, _CENTRAL_ANNOTATION_SCHEMA_V2),
        (3, _CENTRAL_ANNOTATION_SCHEMA_V3),
    ),
    application_tables=frozenset({"central_annotations"}),
)


class CentralAnnotationStore:
    """The central dataset: submissions + labels, one versioned SQLite file."""

    def __init__(self, path: Path) -> None:
        self._path = lexical_absolute_path(path)
        self._lock = threading.Lock()
        self._initialize()

    def _validated_path(self) -> Path:
        path = lexical_absolute_path(self._path)
        if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
            raise AnnotationError("central_annotation_database_path_unsafe")
        return path

    @staticmethod
    def _configure(connection: sqlite3.Connection) -> None:
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA trusted_schema=OFF")
        connection.execute("PRAGMA busy_timeout=5000")
        connection.execute("PRAGMA secure_delete=ON")
        connection.execute("PRAGMA synchronous=FULL")

    @staticmethod
    def _legacy_version(connection: sqlite3.Connection) -> int | None:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        if tables != {"central_annotations"}:
            return None
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                'PRAGMA table_info("central_annotations")'
            ).fetchall()
        )
        sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='central_annotations'"
        ).fetchone()
        if sql_row is None:
            return None
        sql = _normalized_central_schema_sql(str(sql_row[0]))
        if columns == _CENTRAL_ANNOTATION_COLUMNS_V1 and sql == _CENTRAL_ANNOTATION_SQL_V1:
            return 1
        if columns == _CENTRAL_ANNOTATION_COLUMNS_V2 and sql == _CENTRAL_ANNOTATION_SQL_V2:
            return 2
        return None

    @staticmethod
    def _verify_current_structure(connection: sqlite3.Connection) -> None:
        tables = {
            str(row[0])
            for row in connection.execute(
                """
                SELECT name FROM sqlite_master
                WHERE type='table' AND name NOT LIKE 'sqlite_%'
                """
            ).fetchall()
        }
        if tables != {
            "central_annotations",
            "central_annotation_schema_migrations",
            "central_annotation_migration_checksums",
        }:
            raise AnnotationError("central_annotation_schema_integrity_invalid")
        columns = tuple(
            str(row[1])
            for row in connection.execute(
                'PRAGMA table_info("central_annotations")'
            ).fetchall()
        )
        if columns != _CENTRAL_ANNOTATION_COLUMNS_V2:
            raise AnnotationError("central_annotation_schema_integrity_invalid")
        sql_row = connection.execute(
            "SELECT sql FROM sqlite_master WHERE type='table' AND name='central_annotations'"
        ).fetchone()
        if (
            sql_row is None
            or _normalized_central_schema_sql(str(sql_row[0]))
            != _CENTRAL_ANNOTATION_SQL_V2
        ):
            raise AnnotationError("central_annotation_schema_integrity_invalid")
        if connection.execute("PRAGMA integrity_check").fetchone() != ("ok",):
            raise AnnotationError("central_annotation_schema_integrity_invalid")
        if connection.execute("PRAGMA foreign_key_check").fetchall():
            raise AnnotationError("central_annotation_schema_integrity_invalid")

    def _initialize(self) -> None:
        path = self._validated_path()
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if path_has_symlink_component(path.parent) or path_has_symlink_component(path):
            raise AnnotationError("central_annotation_database_path_unsafe")
        connection = sqlite3.connect(path, isolation_level=None, timeout=5.0)
        try:
            self._configure(connection)
            connection.execute("BEGIN IMMEDIATE")
            database_version = int(
                connection.execute("PRAGMA user_version").fetchone()[0]
            )
            ledger_exists = _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.table_exists(
                connection,
                "central_annotation_schema_migrations",
            )
            if not ledger_exists:
                if database_version != 0:
                    raise _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.error(
                        "schema_version_mismatch"
                    )
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        """
                        SELECT name FROM sqlite_master
                        WHERE type='table' AND name NOT LIKE 'sqlite_%'
                        """
                    ).fetchall()
                }
                if not tables:
                    _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.create_ledger(connection)
                else:
                    legacy_version = self._legacy_version(connection)
                    if legacy_version is None:
                        raise _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.error(
                            "migration_history_incomplete"
                        )
                    _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.adopt_legacy(
                        connection,
                        through_version=legacy_version,
                        applied_at=datetime.now(UTC)
                        .replace(microsecond=0)
                        .isoformat(),
                    )
            current = _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.validate(
                connection,
                database_version=database_version,
                allow_legacy_zero_head=True,
            )
            _CENTRAL_ANNOTATION_MIGRATION_INTEGRITY.apply_pending(
                connection,
                current=current,
                applied_at=datetime.now(UTC).replace(microsecond=0).isoformat(),
            )
            self._verify_current_structure(connection)
            connection.execute("COMMIT")
        except Exception:
            if connection.in_transaction:
                connection.execute("ROLLBACK")
            raise
        finally:
            connection.close()
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
        if path_has_symlink_component(path):
            raise AnnotationError("central_annotation_database_path_unsafe")

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self._validated_path(), timeout=5.0)
        connection.row_factory = sqlite3.Row
        try:
            self._configure(connection)
            yield connection
        finally:
            connection.close()

    def store(self, user_label: str, item: CentralBatchItem, labels: dict[str, RatingLabel], model_identity: str | None, submitted_at: datetime) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO central_annotations(
                    user_label, session_id, project_id, provider, window_chars, redacted_window,
                    labels_json, model_identity, prompt_version, submitted_at,
                    window_fingerprint, case_fingerprint, case_version
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    user_label, item.session_id, item.project_id, item.provider, len(item.window), item.window,
                    json.dumps({k: v.value for k, v in labels.items()}), model_identity, JUDGE_PROMPT_VERSION, submitted_at.isoformat(),
                    item.window_fingerprint, item.case_fingerprint, item.case_version,
                ),
            )
            connection.commit()

    def count(self) -> int:
        with self._connect() as connection:
            return int(connection.execute("SELECT COUNT(*) FROM central_annotations").fetchone()[0])


class CentralAnnotationServer:
    """Annotates submitted windows with the configured active model and stores the dataset."""

    def __init__(
        self,
        store: CentralAnnotationStore,
        *,
        chat: Callable[[str, bytes], tuple[int, bytes, str]],
        active_model: Callable[[], str | None],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._store = store
        self._chat = chat
        self._active_model = active_model
        self._clock = clock or (lambda: datetime.now(UTC))

    def annotate_batch(self, batch: CentralBatch) -> CentralBatchResult:
        alias = self._active_model()
        if alias is None:
            raise AnnotationError("no_central_model")
        annotations: list[CentralAnnotation] = []
        stored = 0
        for item in batch.items:
            if not _is_canonical_judge_window(item.window):
                continue
            case = None
            if item.case_fingerprint is not None or item.case_version is not None or item.window_fingerprint is not None:
                try:
                    case = prepare_calibration_case(
                        session_id=item.session_id, provider=Provider(item.provider),
                        window_fingerprint=item.window_fingerprint, rendered_window=item.window,
                    )
                except (CalibrationReviewError, ValueError):
                    continue
                if item.case_version != case.case_version or item.case_fingerprint != case.case_fingerprint:
                    continue
            body = json.dumps(
                {
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {
                            "role": "user",
                            "content": _judge_user_prompt(item.window),
                        },
                    ],
                    "temperature": 0,
                    "max_tokens": 220,
                    "chat_template_kwargs": {"enable_thinking": False},
                }
            ).encode("utf-8")
            try:
                status, payload, _ = self._chat(alias, body)
                text = completed_chat_content(payload) if status == 200 else None
            except Exception:  # noqa: BLE001 - one bad window must not sink the batch
                text = None
            labels = parse_judge_reply(text)
            if not labels:
                continue
            self._store.store(batch.user_label, item, labels, alias, self._clock())
            annotations.append(CentralAnnotation(
                session_id=item.session_id, labels=labels,
                window_fingerprint=case.window_fingerprint if case else None,
                case_fingerprint=case.case_fingerprint if case else None,
                case_version=case.case_version if case else None,
            ))
            stored += 1
        return CentralBatchResult(stored=stored, annotations=tuple(annotations), model_identity=alias)


class RemoteAnnotationClient:
    """The app-side 'Annotate remotely' action: build the batch, send it, record returned labels locally."""

    def __init__(
        self,
        service: AnnotationService,
        *,
        submit: Callable[[CentralBatch], CentralBatchResult],
        destination: str,
        user_label: str,
        list_sessions: Callable[..., list[dict[str, object]]],
        active_model: Callable[[], str | None] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._service = service
        self._submit = submit
        self._destination = destination
        self._user_label = user_label
        self._list_sessions = list_sessions
        self._active_model = active_model or (lambda: None)
        self._clock = clock or (lambda: datetime.now(UTC))

    def disclosure(self) -> RemoteAnnotationDisclosure:
        """Describe the exact remote boundary without reading or submitting session data."""

        return RemoteAnnotationDisclosure(
            destination=self._destination,
            active_model_alias=self._active_model(),
        )

    def submit_batch(self, request: RemoteSubmitRequest) -> RemoteSubmitResult:
        judge = self._service._judge  # noqa: SLF001 - same composition unit
        central_done = _complete_case_sessions(tuple(j for j in judge.repository.list() if j.model_alias.startswith("central:")))
        items: list[CentralBatchItem] = []
        # Window identity of each window this run actually sealed and sent, so the
        # labels that come back are recorded against that window and no other.
        sealed: dict[str, PreparedCalibrationCase] = {}
        offset = 0
        while len(items) < request.limit:
            rows = self._list_sessions(limit=100, offset=offset)
            if not rows:
                break
            for row in rows:
                if len(items) >= request.limit:
                    break
                sid = str(row.get("session_id"))
                if sid in central_done:
                    continue
                session = judge.session_lookup(sid)
                if session is None:
                    continue
                provider = Provider(getattr(session, "provider"))
                try:
                    context = judge.window_for(provider, sid)
                except Exception:  # noqa: BLE001 - unreadable windows are skipped
                    continue
                try:
                    fingerprint = _sealed_window_fingerprint(context, session_id=sid, provider=provider)
                    window = render_window(context)
                    case = prepare_calibration_case(session_id=sid, provider=provider, window_fingerprint=fingerprint, rendered_window=window)
                    sealed[sid] = case
                except (AnnotationError, CalibrationReviewError, ModelJudgeError):
                    continue
                items.append(CentralBatchItem(
                    session_id=sid, project_id=str(row.get("project_id")) if row.get("project_id") else None,
                    provider=provider.value, window=window, window_fingerprint=case.window_fingerprint,
                    case_fingerprint=case.case_fingerprint, case_version=case.case_version,
                ))
            offset += len(rows)
            if len(rows) < 100:
                break
        if not items:
            return RemoteSubmitResult(destination=self._destination, submitted=0, annotated=0)
        result = self._submit(CentralBatch(user_label=self._user_label, items=tuple(items)))
        alias = f"central:{result.model_identity}"[:64] if result.model_identity else "central:unknown"
        now = self._clock()
        recorded = 0
        recorded_sessions: set[str] = set()
        seen: set[str] = set()
        for annotation in result.annotations:
            case = sealed.get(annotation.session_id)
            if case is None or annotation.session_id in seen:
                # Labels for a session this run did not seal and send. Nothing
                # local can vouch for which window they describe, so they are
                # dropped rather than stored against a guessed one.
                continue
            seen.add(annotation.session_id)
            bound = annotation.case_fingerprint is not None or annotation.case_version is not None or annotation.window_fingerprint is not None
            if bound and (
                annotation.case_fingerprint != case.case_fingerprint or annotation.case_version != case.case_version
                or annotation.window_fingerprint != case.window_fingerprint
            ):
                continue
            if set(annotation.labels) != set(CALIBRATION_METRIC_KEYS):
                continue
            identified = bound and bool(result.model_identity and result.model_identity.strip())
            for key, label in annotation.labels.items():
                if key not in CALIBRATION_METRIC_KEYS:
                    continue
                judge.repository.upsert(
                    ModelJudgment(
                        session_id=annotation.session_id, metric_key=key, label=label, model_alias=alias,
                        model_identity=result.model_identity or "unknown", prompt_version=result.prompt_version,
                        window_fingerprint=case.window_fingerprint, judged_at=now,
                        case_fingerprint=case.case_fingerprint if identified else None,
                        case_version=case.case_version if identified else None,
                    )
                )
                recorded += 1
            recorded_sessions.add(annotation.session_id)
        return RemoteSubmitResult(destination=self._destination, submitted=len(items), annotated=len(recorded_sessions), model_identity=result.model_identity, stored_locally_as=alias if recorded else None)


__all__ = (
    "ANNOTATION_CONTRACT_VERSION",
    "CENTRAL_ANNOTATION_DATABASE_FILENAME",
    "CENTRAL_ANNOTATION_SCHEMA_VERSION",
    "AllowanceState",
    "AnnotationError",
    "AnnotationService",
    "CentralAnnotationServer",
    "CentralAnnotationStore",
    "CentralBatch",
    "CentralBatchItem",
    "CentralBatchResult",
    "Metaprompt",
    "RemoteAnnotationDisclosure",
    "RemoteAnnotationClient",
    "RemoteSubmitRequest",
    "RemoteSubmitResult",
    "SubmitAnnotation",
    "SubmitResult",
    "WorkList",
    "WorkWindow",
    "metaprompt",
)
