from __future__ import annotations

import importlib
import os
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

import tests.support.bounded_pytest_receipt as receipt_module
from prompt_enhancer.application.owned_process import run_owned_process
from tests.support.bounded_pytest_receipt import (
    JOURNAL_NAME,
    BoundedReceiptPlugin,
    JournalWriter,
    ReceiptError,
    read_complete_journal,
    summarize_journal,
    validate_output_directory,
)


def _plugin(output_directory: Path) -> BoundedReceiptPlugin:
    return BoundedReceiptPlugin(JournalWriter(output_directory))


def _report(nodeid: str, when: str, outcome: str, **private: object) -> object:
    return SimpleNamespace(nodeid=nodeid, when=when, outcome=outcome, **private)


def test_incremental_ids_survive_without_sessionfinish(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)

    plugin.pytest_sessionstart(object())
    plugin.pytest_collectreport(
        SimpleNamespace(failed=True, nodeid="tests/test_collect.py")
    )
    plugin.pytest_runtest_logstart(
        "tests/test_example.py::test_failure", ("ignored", 1, "ignored")
    )
    plugin.pytest_runtest_logreport(
        _report("tests/test_example.py::test_failure", "call", "failed")
    )

    records = read_complete_journal(receipt_dir / JOURNAL_NAME)
    assert records[-3:] == [
        {"event": "collection_failure", "id": "tests/test_collect.py"},
        {"event": "test_active", "id": "tests/test_example.py::test_failure"},
        {
            "event": "test_report",
            "id": "tests/test_example.py::test_failure",
            "phase": "call",
            "outcome": "failed",
        },
    ]
    summary = summarize_journal(records)
    assert summary["active_test_ids"] == ["tests/test_example.py::test_failure"]
    assert summary["collection_failures"] == ["tests/test_collect.py"]
    assert summary["termination"] == "unfinished"
    plugin.writer.close()


def test_collection_finish_uses_current_items_before_pytest_assigns_total(
    tmp_path: Path,
) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)

    plugin.pytest_collection_finish(
        SimpleNamespace(items=[object(), object()], testscollected=0)
    )
    plugin.writer.close()

    assert read_complete_journal(receipt_dir / JOURNAL_NAME) == [
        {"event": "collection_finished", "collected": 2}
    ]


def test_reader_recovers_complete_records_after_torn_tail(tmp_path: Path) -> None:
    journal = tmp_path / JOURNAL_NAME
    journal.write_bytes(
        b'{"event":"session_started"}\n'
        b'{"event":"test_active","id":"tests/test_ok.py::test_ok"}\n'
        b'{"event":"test_report","id":'
    )

    assert read_complete_journal(journal) == [
        {"event": "session_started"},
        {"event": "test_active", "id": "tests/test_ok.py::test_ok"},
    ]

    journal.write_bytes(
        b'{"event":"session_started"}\nnot-json\n'
        b'{"event":"test_active","id":"tests/test_ok.py::test_ok"}\n'
    )
    with pytest.raises(ReceiptError, match="before journal tail"):
        read_complete_journal(journal)

    journal.write_bytes(b'{"event":"session_started"}\nnot-json\n')
    with pytest.raises(ReceiptError, match="before journal tail"):
        read_complete_journal(journal)


def test_normal_completion_separates_report_and_unique_counts(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)
    failing = "tests/test_example.py::test_failure"
    skipped = "tests/test_example.py::test_skip"

    plugin.pytest_sessionstart(object())
    plugin.pytest_runtest_logstart(failing, ("ignored", 1, "ignored"))
    for phase, outcome in (
        ("setup", "passed"),
        ("call", "failed"),
        ("teardown", "passed"),
    ):
        plugin.pytest_runtest_logreport(_report(failing, phase, outcome))
    plugin.pytest_runtest_logfinish(failing, ("ignored", 1, "ignored"))
    plugin.pytest_runtest_logstart(skipped, ("ignored", 1, "ignored"))
    plugin.pytest_runtest_logreport(_report(skipped, "setup", "skipped"))
    plugin.pytest_runtest_logfinish(skipped, ("ignored", 1, "ignored"))
    plugin.pytest_sessionfinish(object(), 1)

    records = read_complete_journal(receipt_dir / JOURNAL_NAME)
    completed = records[-1]
    assert completed == {
        "event": "session_completed",
        "exit_status": 1,
        "report_counts": {"failed": 1, "passed": 2, "skipped": 1},
        "unique_test_outcomes": {"failed": 1, "passed": 0, "skipped": 1},
    }
    assert summarize_journal(records)["termination"] == "completed"


def test_active_setup_pass_is_not_a_unique_pass(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)
    nodeid = "tests/test_example.py::test_interrupted"

    plugin.pytest_runtest_logstart(nodeid, ("ignored", 1, "ignored"))
    plugin.pytest_runtest_logreport(_report(nodeid, "setup", "passed"))
    plugin.writer.close()

    summary = summarize_journal(read_complete_journal(receipt_dir / JOURNAL_NAME))
    assert summary["report_counts"] == {"failed": 0, "passed": 1, "skipped": 0}
    assert summary["unique_test_outcomes"] == {
        "failed": 0,
        "passed": 0,
        "skipped": 0,
    }
    assert summary["active_test_ids"] == [nodeid]


def test_interruption_is_recorded_separately_from_completion(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)

    plugin.pytest_keyboard_interrupt(object())
    plugin.pytest_sessionfinish(object(), 2)

    records = read_complete_journal(receipt_dir / JOURNAL_NAME)
    assert [record["event"] for record in records] == [
        "session_interrupted",
        "interruption_finalized",
    ]
    assert summarize_journal(records)["termination"] == "interrupted_finalized"


def test_journal_uses_allowlisted_fields_and_redacts_unsafe_ids(tmp_path: Path) -> None:
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    plugin = _plugin(receipt_dir)
    private_path = "Z:\\example\\private\\test_fixture.py::test_value"
    parameterized = "tests/test_safe.py::test_value[secret-token@example.invalid]"

    plugin.pytest_runtest_logstart(private_path, (private_path, 9, "private"))
    plugin.pytest_runtest_logreport(
        _report(
            parameterized,
            "call",
            "failed",
            longrepr="assert private payload",
            capstdout="secret stdout",
            capstderr="secret stderr",
            user_properties=[("payload", "secret")],
        )
    )
    plugin.writer.close()

    raw = (receipt_dir / JOURNAL_NAME).read_text(encoding="utf-8")
    for forbidden in (
        "Z:\\\\example",
        "secret-token",
        "private payload",
        "secret stdout",
        "secret stderr",
        "user_properties",
    ):
        assert forbidden not in raw
    records = read_complete_journal(receipt_dir / JOURNAL_NAME)
    assert records[0] == {"event": "test_active", "id": "test-1"}
    assert records[1]["id"].startswith("tests/test_safe.py::test_value[case-")
    assert records[1]["id"].endswith("]")
    assert records[1]["id"] == plugin.identifiers.safe(parameterized)
    assert set(records[1]) == {"event", "id", "phase", "outcome"}


def test_import_is_inert_and_output_directory_is_explicit_external(
    tmp_path: Path,
) -> None:
    module = importlib.import_module("tests.support.bounded_pytest_receipt")
    assert module.JOURNAL_NAME == JOURNAL_NAME
    assert list(tmp_path.iterdir()) == []

    repository_root = Path(__file__).resolve().parents[1]
    with pytest.raises(ReceiptError, match="must be absolute"):
        validate_output_directory("relative", repository_root)
    with pytest.raises(ReceiptError, match="outside the pytest root"):
        validate_output_directory(repository_root / "tests", repository_root)

    external = tmp_path / "external"
    external.mkdir()
    assert validate_output_directory(external, repository_root) == external.resolve()


def test_configuration_os_error_is_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    private_message = "Z:\\example\\private\\receipt denied"

    def fail_writer(output_directory: Path) -> JournalWriter:
        raise OSError(private_message)

    monkeypatch.setattr(receipt_module, "JournalWriter", fail_writer)
    config = SimpleNamespace(
        rootpath=Path(__file__).resolve().parents[1],
        getoption=lambda name: str(tmp_path),
    )
    with pytest.raises(pytest.UsageError) as caught:
        receipt_module.pytest_configure(config)
    assert str(caught.value) == "bounded receipt output is unavailable"
    assert "Z:\\example" not in str(caught.value)


def test_owned_process_recovers_failure_and_active_ids_after_hard_exit(
    tmp_path: Path,
) -> None:
    fixture_root = tmp_path / "synthetic-pytest-project"
    fixture_root.mkdir()
    receipt_dir = tmp_path / "receipt"
    receipt_dir.mkdir()
    pytest_temp = tmp_path / "pytest-temp"
    fixture = fixture_root / "test_crash_fixture.py"
    fixture.write_text(
        """import os


def test_a_failure():
    print("sensitive-stdout-payload")
    assert False, "sensitive-assertion-payload"


def test_b_hard_exit():
    os._exit(23)
""",
        encoding="utf-8",
    )
    allowed_environment = {
        "SYSTEMROOT",
        "WINDIR",
        "COMSPEC",
        "PATH",
        "PATHEXT",
        "SYSTEMDRIVE",
        "NUMBER_OF_PROCESSORS",
    }
    environment = {
        key: value
        for key, value in os.environ.items()
        if key.upper() in allowed_environment
    }
    environment.update(
        {
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_ADDOPTS": "",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
            "PYTHONPATH": str(Path(receipt_module.__file__).resolve().parent),
        }
    )

    result = run_owned_process(
        [
            sys.executable,
            "-B",
            "-m",
            "pytest",
            fixture.name,
            "-q",
            "--tb=no",
            "--maxfail=3",
            "--rootdir=.",
            "-p",
            "no:cacheprovider",
            "-p",
            "bounded_pytest_receipt",
            "--bounded-pytest-receipt-dir",
            str(receipt_dir),
            "--basetemp",
            str(pytest_temp),
        ],
        cwd=fixture_root,
        env=environment,
        timeout=30,
        stdout_limit=64 * 1024,
        stderr_limit=64 * 1024,
        maximum_active_processes=4,
    )

    # A normal result proves the owner observed exit and confirmed tree/handle cleanup.
    assert result.returncode == 23
    journal = receipt_dir / JOURNAL_NAME
    records = read_complete_journal(journal)
    summary = summarize_journal(records)
    assert summary["unique_test_outcomes"] == {
        "failed": 1,
        "passed": 0,
        "skipped": 0,
    }
    assert summary["active_test_ids"] == [
        "test_crash_fixture.py::test_b_hard_exit"
    ]
    assert any(
        record == {
            "event": "test_report",
            "id": "test_crash_fixture.py::test_a_failure",
            "phase": "call",
            "outcome": "failed",
        }
        for record in records
    )
    assert not any(
        record["event"] in {"session_completed", "interruption_finalized"}
        for record in records
    )
    journal_text = journal.read_text(encoding="utf-8")
    assert "sensitive-assertion-payload" not in journal_text
    assert "sensitive-stdout-payload" not in journal_text
