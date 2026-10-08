"""The wheel entry point must not claim a clean source tree by default."""

from __future__ import annotations

from scripts import prepare_application_wheel as cli


def _args() -> list[str]:
    return [
        "--project-root", "D:/example-project",
        "--source-manifest", "D:/example-source.json",
        "--dashboard-manifest", "D:/example-dashboard.json",
        "--python-executable", "D:/example-python.exe",
        "--python-sha256", "a" * 64,
        "--python-size-bytes", "10",
        "--python-version", "3.13.0",
        "--setuptools-wheel", "D:/example-setuptools.whl",
        "--setuptools-sha256", "b" * 64,
        "--setuptools-size-bytes", "10",
        "--setuptools-version", "80.0.0",
        "--destination", "D:/example-output",
    ]


def test_source_state_is_explicit_and_parser_errors_do_not_echo_values(capsys, monkeypatch) -> None:
    monkeypatch.setattr(cli, "prepare_application_wheel", lambda **kwargs: (_ for _ in ()).throw(AssertionError("launched")))
    assert cli.main(_args()) == 2
    assert "example-project" not in capsys.readouterr().err
    invalid = _args()
    invalid[invalid.index("--python-size-bytes") + 1] = "private-like-value"
    assert cli.main(invalid + ["--source-tree-clean"]) == 2
    captured = capsys.readouterr()
    assert "private-like-value" not in captured.err + captured.out
    assert "application_wheel_preparation_failed" in captured.err


def test_explicit_source_state_is_forwarded_without_running_builder(capsys, monkeypatch) -> None:
    observed = []
    monkeypatch.setattr(cli, "prepare_application_wheel", lambda **kwargs: observed.append(kwargs) or object())
    monkeypatch.setattr(cli, "asdict", lambda result: {"review_only": True})
    assert cli.main(_args() + ["--source-tree-dirty"]) == 0
    assert observed[-1]["source_tree_dirty"] is True
    assert cli.main(_args() + ["--source-tree-clean"]) == 0
    assert observed[-1]["source_tree_dirty"] is False
    assert "review_only" in capsys.readouterr().out


def test_builder_failure_is_content_free(capsys, monkeypatch) -> None:
    def fail(**kwargs):
        raise cli.ApplicationWheelPreparationError("private-like builder diagnostic")
    monkeypatch.setattr(cli, "prepare_application_wheel", fail)
    assert cli.main(_args() + ["--source-tree-dirty"]) == 2
    captured = capsys.readouterr()
    assert "private-like" not in captured.err + captured.out
    assert captured.err.strip() == "application_wheel_preparation_failed"
