"""Opt-in, content-free, crash-recoverable pytest receipt journal.

Load this module explicitly and pass ``--bounded-pytest-receipt-dir``. Merely
importing the module does not create files or register a recorder.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from collections import Counter
from pathlib import Path, PurePosixPath, PureWindowsPath
from typing import Any, Iterable, Mapping

import pytest


JOURNAL_NAME = "bounded-pytest-receipt.jsonl"
MAX_JOURNAL_BYTES = 32 * 1024 * 1024
MAX_RECORD_BYTES = 2 * 1024
MAX_RECORDS = 100_000
MAX_IDENTIFIER_LENGTH = 512

_EVENT_KEYS = {
    "session_started": frozenset({"event"}),
    "collection_failure": frozenset({"event", "id"}),
    "collection_finished": frozenset({"event", "collected"}),
    "test_active": frozenset({"event", "id"}),
    "test_report": frozenset({"event", "id", "phase", "outcome"}),
    "test_finished": frozenset({"event", "id"}),
    "session_interrupted": frozenset({"event"}),
    "interruption_finalized": frozenset(
        {"event", "exit_status", "report_counts", "unique_test_outcomes"}
    ),
    "session_completed": frozenset(
        {"event", "exit_status", "report_counts", "unique_test_outcomes"}
    ),
}
_PHASES = frozenset({"setup", "call", "teardown"})
_OUTCOMES = frozenset({"passed", "failed", "skipped"})
_SAFE_NODEID = re.compile(r"^[A-Za-z0-9_.:/-]+(?:::[A-Za-z0-9_.:/-]+)*$")


class ReceiptError(RuntimeError):
    """A receipt path or journal violates the bounded receipt contract."""


def _is_within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def validate_output_directory(value: str | os.PathLike[str], root: Path) -> Path:
    """Return a resolved, pre-existing directory outside the pytest root."""

    supplied = Path(value)
    if not supplied.is_absolute():
        raise ReceiptError("receipt output directory must be absolute")
    resolved = supplied.resolve(strict=True)
    if not resolved.is_dir():
        raise ReceiptError("receipt output path must be an existing directory")
    if _is_within(resolved, root.resolve(strict=True)):
        raise ReceiptError("receipt output directory must be outside the pytest root")
    return resolved


def _validate_record(record: Mapping[str, Any]) -> None:
    event = record.get("event")
    allowed = _EVENT_KEYS.get(event)
    if allowed is None or set(record) != allowed:
        raise ReceiptError("receipt record does not match the content-free schema")
    identifier = record.get("id")
    if identifier is not None and (
        not isinstance(identifier, str)
        or not identifier
        or len(identifier) > MAX_IDENTIFIER_LENGTH
    ):
        raise ReceiptError("receipt identifier is invalid")
    if event == "test_report":
        if record["phase"] not in _PHASES or record["outcome"] not in _OUTCOMES:
            raise ReceiptError("receipt report value is invalid")
    if event == "collection_finished" and (
        not isinstance(record["collected"], int) or record["collected"] < 0
    ):
        raise ReceiptError("receipt collection count is invalid")
    if event in {"session_completed", "interruption_finalized"}:
        if not isinstance(record["exit_status"], int):
            raise ReceiptError("receipt exit status is invalid")
        for field in ("report_counts", "unique_test_outcomes"):
            counts = record[field]
            if not isinstance(counts, dict) or set(counts) != _OUTCOMES:
                raise ReceiptError("receipt outcome counts are invalid")
            if any(not isinstance(value, int) or value < 0 for value in counts.values()):
                raise ReceiptError("receipt outcome count is invalid")


class JournalWriter:
    """Write bounded JSONL records durably, one complete record at a time."""

    def __init__(self, output_directory: Path) -> None:
        self.path = output_directory / JOURNAL_NAME
        self._stream = self.path.open("x", encoding="utf-8", newline="\n")
        self._bytes_written = 0
        self._records_written = 0

    def append(self, record: Mapping[str, Any]) -> None:
        _validate_record(record)
        encoded = (
            json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            + "\n"
        ).encode("utf-8")
        if len(encoded) > MAX_RECORD_BYTES:
            raise ReceiptError("receipt record exceeds the byte limit")
        if self._records_written >= MAX_RECORDS:
            raise ReceiptError("receipt record limit reached")
        if self._bytes_written + len(encoded) > MAX_JOURNAL_BYTES:
            raise ReceiptError("receipt journal byte limit reached")
        self._stream.write(encoded.decode("utf-8"))
        self._stream.flush()
        os.fsync(self._stream.fileno())
        self._bytes_written += len(encoded)
        self._records_written += 1

    def close(self) -> None:
        if not self._stream.closed:
            self._stream.close()


class IdentifierRegistry:
    """Map unsafe or parameter-bearing IDs to content-free run-local IDs."""

    def __init__(self) -> None:
        self._aliases: dict[tuple[str, str], str] = {}
        self._next: Counter[str] = Counter()

    def safe(self, raw_value: object, kind: str = "test") -> str:
        raw = raw_value if isinstance(raw_value, str) else ""
        key = (kind, raw)
        existing = self._aliases.get(key)
        if existing is not None:
            return existing

        candidate = raw.replace("\\", "/")
        parameterized = "[" in candidate
        if parameterized:
            candidate = candidate.split("[", 1)[0]
        path_part = candidate.split("::", 1)[0]
        absolute = PureWindowsPath(path_part).is_absolute() or PurePosixPath(
            path_part
        ).is_absolute()
        traversal = ".." in PurePosixPath(path_part).parts
        safe_candidate = (
            bool(candidate)
            and len(candidate) <= MAX_IDENTIFIER_LENGTH - 16
            and not absolute
            and not traversal
            and _SAFE_NODEID.fullmatch(candidate) is not None
        )
        if safe_candidate and not parameterized:
            alias = candidate
        elif safe_candidate and parameterized:
            fingerprint = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]
            alias = f"{candidate}[case-{fingerprint}]"
        else:
            self._next[kind] += 1
            suffix = self._next[kind]
            alias = f"{kind}-{suffix}"
        self._aliases[key] = alias
        return alias


def summarize_journal(records: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Compute phase-report and unique-test outcomes from complete records."""

    report_counts = Counter({outcome: 0 for outcome in _OUTCOMES})
    reports_by_test: dict[str, dict[str, str]] = {}
    active: set[str] = set()
    collection_failures: list[str] = []
    termination = "unfinished"
    precedence = {"passed": 1, "skipped": 2, "failed": 3}

    for record in records:
        _validate_record(record)
        event = record["event"]
        if event == "collection_failure":
            collection_failures.append(record["id"])
        elif event == "test_active":
            active.add(record["id"])
        elif event == "test_finished":
            active.discard(record["id"])
        elif event == "test_report":
            outcome = record["outcome"]
            report_counts[outcome] += 1
            identifier = record["id"]
            reports_by_test.setdefault(identifier, {})[record["phase"]] = outcome
        elif event == "session_interrupted":
            termination = "interrupted"
        elif event == "interruption_finalized":
            termination = "interrupted_finalized"
        elif event == "session_completed":
            termination = "completed"

    unique_counts = Counter({outcome: 0 for outcome in _OUTCOMES})
    for identifier, phase_reports in reports_by_test.items():
        strongest = max(phase_reports.values(), key=precedence.__getitem__)
        if strongest == "failed":
            unique_counts["failed"] += 1
        elif identifier not in active and strongest == "skipped":
            unique_counts["skipped"] += 1
        elif (
            identifier not in active
            and phase_reports.get("call") == "passed"
            and phase_reports.get("teardown") == "passed"
        ):
            unique_counts["passed"] += 1
    return {
        "report_counts": dict(report_counts),
        "unique_test_outcomes": dict(unique_counts),
        "collection_failures": collection_failures,
        "active_test_ids": sorted(active),
        "termination": termination,
    }


def read_complete_journal(path: str | os.PathLike[str]) -> list[dict[str, Any]]:
    """Read complete records, ignoring only a malformed/torn final record."""

    journal = Path(path)
    size = journal.stat().st_size
    if size > MAX_JOURNAL_BYTES:
        raise ReceiptError("receipt journal exceeds the byte limit")
    raw = journal.read_bytes()
    lines = raw.splitlines()
    records: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        if len(line) > MAX_RECORD_BYTES:
            raise ReceiptError("receipt record exceeds the byte limit")
        try:
            decoded = json.loads(line)
            if not isinstance(decoded, dict):
                raise ReceiptError("receipt record must be an object")
            _validate_record(decoded)
        except (UnicodeDecodeError, json.JSONDecodeError, ReceiptError) as exc:
            final_line_is_torn = index == len(lines) - 1 and not raw.endswith(b"\n")
            if final_line_is_torn:
                break
            raise ReceiptError("malformed receipt record before journal tail") from exc
        records.append(decoded)
        if len(records) > MAX_RECORDS:
            raise ReceiptError("receipt record limit exceeded")
    return records


class BoundedReceiptPlugin:
    def __init__(self, writer: JournalWriter) -> None:
        self.writer = writer
        self.identifiers = IdentifierRegistry()
        self.records: list[dict[str, Any]] = []
        self.interrupted = False

    def _append(self, record: dict[str, Any]) -> None:
        self.writer.append(record)
        self.records.append(record)

    def pytest_sessionstart(self, session: object) -> None:
        self._append({"event": "session_started"})

    def pytest_collectreport(self, report: object) -> None:
        if getattr(report, "failed", False):
            identifier = self.identifiers.safe(
                getattr(report, "nodeid", ""), kind="collection"
            )
            self._append({"event": "collection_failure", "id": identifier})

    def pytest_collection_finish(self, session: object) -> None:
        count = len(getattr(session, "items", ()))
        self._append({"event": "collection_finished", "collected": max(count, 0)})

    def pytest_runtest_logstart(self, nodeid: str, location: object) -> None:
        identifier = self.identifiers.safe(nodeid)
        self._append({"event": "test_active", "id": identifier})

    def pytest_runtest_logreport(self, report: object) -> None:
        phase = getattr(report, "when", "")
        outcome = getattr(report, "outcome", "")
        if phase not in _PHASES or outcome not in _OUTCOMES:
            return
        identifier = self.identifiers.safe(getattr(report, "nodeid", ""))
        self._append(
            {
                "event": "test_report",
                "id": identifier,
                "phase": phase,
                "outcome": outcome,
            }
        )

    def pytest_runtest_logfinish(self, nodeid: str, location: object) -> None:
        identifier = self.identifiers.safe(nodeid)
        self._append({"event": "test_finished", "id": identifier})

    def pytest_keyboard_interrupt(self, excinfo: object) -> None:
        if not self.interrupted:
            self.interrupted = True
            self._append({"event": "session_interrupted"})

    def pytest_sessionfinish(self, session: object, exitstatus: object) -> None:
        summary = summarize_journal(self.records)
        record = {
            "event": (
                "interruption_finalized" if self.interrupted else "session_completed"
            ),
            "exit_status": int(exitstatus),
            "report_counts": summary["report_counts"],
            "unique_test_outcomes": summary["unique_test_outcomes"],
        }
        self._append(record)
        self.writer.close()


def pytest_addoption(parser: Any) -> None:
    group = parser.getgroup("bounded receipt")
    group.addoption(
        "--bounded-pytest-receipt-dir",
        action="store",
        default=None,
        metavar="ABSOLUTE_DIRECTORY",
        help="Write a content-free incremental receipt to an existing external directory.",
    )


def pytest_configure(config: Any) -> None:
    value = config.getoption("bounded_pytest_receipt_dir")
    if value is None:
        return
    try:
        output_directory = validate_output_directory(value, Path(config.rootpath))
        writer = JournalWriter(output_directory)
    except ReceiptError as exc:
        raise pytest.UsageError(str(exc)) from exc
    except OSError as exc:
        raise pytest.UsageError("bounded receipt output is unavailable") from exc
    config.pluginmanager.register(BoundedReceiptPlugin(writer), "bounded-pytest-recorder")
