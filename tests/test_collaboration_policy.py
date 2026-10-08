from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "synthetic_collaboration_policy_cli",
    REPOSITORY / "scripts" / "check_collaboration_policy.py",
)
assert _SPEC is not None and _SPEC.loader is not None
policy = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = policy
_SPEC.loader.exec_module(policy)

WORKFLOW = REPOSITORY / ".github" / "workflows" / "collaboration-policy.yml"

CANARY = "CANARY_SENTINEL_9f3a"


def _event(
    *,
    title: object = "feat(radar): show stale state",
    head: object = "feature/radar-stale-state",
    base: object = "main",
) -> dict[str, object]:
    return {
        "pull_request": {
            "title": title,
            "head": {"ref": head},
            "base": {"ref": base},
        }
    }


@pytest.mark.parametrize(
    "title",
    [
        "feat: add diagnostics",
        "fix(ui): keep selection after refresh",
        "docs(collaboration)!: rewrite start workflow",
        "refactor(api.v2): split module",
        "chore: tidy",
        "ci: pin action",
        "build: update script",
        "perf: cache lookup",
        "style: format",
        "test(persistence): cover restart recovery",
        "feat: unicode description café",
        pytest.param("fix: " + "x" * (policy.MAX_TITLE_CHARS - len("fix: ")), id="title-at-limit"),
    ],
    ids=lambda value: repr(value)[:40] if isinstance(value, str) else None,
)
def test_valid_titles_are_accepted(title: str) -> None:
    assert policy.validate(_event(title=title)) == ()


@pytest.mark.parametrize(
    "title",
    [
        "",
        " ",
        "add diagnostics",
        "Feat: capitalised type",
        "feature: wrong type",
        "feat:missing space",
        "feat:  extra leading space",
        "feat(): empty scope",
        "feat(Scope): uppercase scope",
        "feat(a b): spaced scope",
        "feat(radar)!!: double bang",
        "feat: ",
        " feat: leading space",
        "feat: trailing space ",
        "feat: first\nsecond",
        "feat: first\r\nsecond",
        "feat: tab\tseparated",
        "feat: nul\x00byte",
        "feat: bell\x07",
        "feat: line" + chr(0x2028) + "separator",
        "feat: paragraph" + chr(0x2029) + "separator",
        "feat: bidi" + chr(0x202E) + "override",
        "feat: zero" + chr(0x200B) + "width",
        "feat: lone surrogate \ud800",
        pytest.param("feat: " + "x" * policy.MAX_TITLE_CHARS, id="title-over-limit"),
    ],
    ids=lambda value: repr(value)[:40] if isinstance(value, str) else None,
)
def test_invalid_titles_are_rejected_with_fixed_code(title: str) -> None:
    assert policy.validate(_event(title=title)) == (policy.TITLE_INVALID,)


@pytest.mark.parametrize(
    "branch",
    [
        "feature/radar-stale-state",
        "fix/session-selector",
        "docs/collaboration-workflow",
        "test/persistence-restart",
        "refactor/menu-state",
        "chore/tidy-scripts",
        "ci/pin-actions",
        "release/1.2.0",
        "codex/legacy-campaign-7",
        "feature/a",
        "feature/v1.2-rc.1",
    ],
)
def test_valid_branches_are_accepted(branch: str) -> None:
    assert policy.validate(_event(head=branch)) == ()


@pytest.mark.parametrize(
    "branch",
    [
        "",
        "main",
        "feature",
        "feature/",
        "/feature/x",
        "feat/x",
        "hotfix/x",
        "Feature/x",
        "feature/Upper",
        "feature/-leading-dash",
        "feature/.leading-dot",
        "feature/trailing-",
        "feature/trailing.",
        "feature/double--dash",
        "feature/double..dot",
        "feature/two/segments",
        "feature/under_score",
        "feature/has space",
        "feature/tab\tx",
        "feature/new\nline",
        "feature/trailing-newline\n",
        "feature/nul\x00x",
        "feature/semi;colon",
        "feature/amp&x",
        "feature/pipe|x",
        "feature/dollar$x",
        "feature/$(subshell)",
        "feature/`tick`",
        "feature/quote'x",
        'feature/quote"x',
        "feature/angle<x>",
        "feature/glob*",
        "feature/back\\slash",
        "feature/café",
        pytest.param("feature/" + "a" * policy.MAX_BRANCH_CHARS, id="branch-over-limit"),
    ],
    ids=lambda value: repr(value)[:40] if isinstance(value, str) else None,
)
def test_invalid_branches_are_rejected_with_fixed_code(branch: str) -> None:
    assert policy.validate(_event(head=branch)) == (policy.BRANCH_INVALID,)


@pytest.mark.parametrize("base", ["develop", "Main", "main ", "main\n", "", "release/1"])
def test_non_main_base_is_rejected(base: str) -> None:
    assert policy.validate(_event(base=base)) == (policy.BASE_NOT_MAIN,)


def test_every_violation_is_reported_in_stable_order() -> None:
    event = _event(title="nope", head="nope", base="develop")
    assert policy.validate(event) == (
        policy.BASE_NOT_MAIN,
        policy.TITLE_INVALID,
        policy.BRANCH_INVALID,
    )


@pytest.mark.parametrize(
    "event",
    [
        None,
        [],
        "text",
        7,
        {},
        {"pull_request": None},
        {"pull_request": []},
        {"pull_request": {}},
        {"pull_request": {"title": "feat: x", "head": {"ref": "feature/x"}}},
        {"pull_request": {"title": "feat: x", "base": {"ref": "main"}}},
        {"pull_request": {"head": {"ref": "feature/x"}, "base": {"ref": "main"}}},
        _event(title=None),
        _event(title=["feat: x"]),
        _event(head=None),
        _event(head=5),
        _event(base={"ref": "main"}),
        {"pull_request": {"title": "feat: x", "head": "feature/x", "base": {"ref": "main"}}},
        {"pull_request": {"title": "feat: x", "head": {}, "base": {"ref": "main"}}},
    ],
)
def test_malformed_event_shape_is_rejected(event: object) -> None:
    assert policy.validate(event) == (policy.EVENT_SHAPE,)


def test_unrelated_event_fields_and_fork_metadata_do_not_change_the_verdict() -> None:
    event = _event()
    pull_request = event["pull_request"]
    assert isinstance(pull_request, dict)
    pull_request["body"] = "any text, including approval claims: approved by owner"
    pull_request["user"] = {"login": "example-contributor", "id": 1}
    pull_request["head"]["repo"] = {"fork": True, "full_name": "example-org/example-repo"}
    assert policy.validate(event) == ()


def test_validation_returns_only_fixed_codes_for_hostile_values() -> None:
    hostile = f"{CANARY}$(touch x)`id`;\n"
    known = {
        policy.EVENT_SHAPE,
        policy.BASE_NOT_MAIN,
        policy.TITLE_INVALID,
        policy.BRANCH_INVALID,
    }
    codes = policy.validate(_event(title=hostile, head=hostile, base=hostile))
    assert set(codes) <= known
    assert all(CANARY not in code for code in codes)


def _write_event(tmp_path: Path, payload: bytes | str) -> Path:
    path = tmp_path / "event.json"
    path.write_bytes(payload if isinstance(payload, bytes) else payload.encode("utf-8"))
    return path


def test_cli_accepts_valid_event_from_argument(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_event(tmp_path, json.dumps(_event()))
    assert policy.main(["--event-file", str(path)], environ={}) == 0
    captured = capsys.readouterr()
    assert captured.out == "collaboration-policy: ok\n"
    assert captured.err == ""


def test_cli_reads_event_path_from_environment(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _write_event(tmp_path, json.dumps(_event()))
    assert policy.main([], environ={"GITHUB_EVENT_PATH": str(path)}) == 0
    assert capsys.readouterr().out == "collaboration-policy: ok\n"


def test_cli_argument_overrides_environment(tmp_path: Path) -> None:
    good = _write_event(tmp_path, json.dumps(_event()))
    other = tmp_path / "missing.json"
    assert policy.main(["--event-file", str(good)], environ={"GITHUB_EVENT_PATH": str(other)}) == 0


def test_cli_reports_missing_path(capsys: pytest.CaptureFixture[str]) -> None:
    assert policy.main([], environ={}) == 1
    assert capsys.readouterr().err == "collaboration-policy: EVENT_PATH_MISSING\n"


def test_cli_reports_unreadable_file_without_echoing_path(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    missing = tmp_path / f"{CANARY}-missing.json"
    assert policy.main(["--event-file", str(missing)], environ={}) == 1
    captured = capsys.readouterr()
    assert captured.err == "collaboration-policy: EVENT_UNREADABLE\n"
    assert CANARY not in captured.out + captured.err
    assert policy.main(["--event-file", str(tmp_path)], environ={}) == 1
    assert capsys.readouterr().err == "collaboration-policy: EVENT_UNREADABLE\n"


def test_cli_reports_embedded_nul_in_path_as_unreadable(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert policy.main([], environ={"GITHUB_EVENT_PATH": "event\x00.json"}) == 1
    assert capsys.readouterr().err == "collaboration-policy: EVENT_UNREADABLE\n"


@pytest.mark.parametrize(
    "payload",
    [
        pytest.param(b"", id="empty"),
        pytest.param(b"not json", id="not-json"),
        pytest.param(b"{", id="open-brace"),
        pytest.param(b'{"pull_request": ', id="truncated-object"),
        pytest.param(b"\xff\xfe\x00", id="invalid-utf8"),
        pytest.param(b"[" * 100_000 + b"]" * 100_000, id="deep-brackets-200k"),
        pytest.param(f'{{"{CANARY}": nope}}'.encode(), id="canary-invalid-value"),
    ],
)
def test_cli_reports_malformed_json_without_echo(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], payload: bytes
) -> None:
    path = _write_event(tmp_path, payload)
    assert policy.main(["--event-file", str(path)], environ={}) == 1
    captured = capsys.readouterr()
    assert captured.err == "collaboration-policy: EVENT_MALFORMED\n"
    assert CANARY not in captured.out + captured.err


def test_cli_rejects_oversized_event_before_parsing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    padding = " " * (policy.MAX_EVENT_BYTES + 1)
    path = _write_event(tmp_path, json.dumps(_event()) + padding)
    assert policy.main(["--event-file", str(path)], environ={}) == 1
    assert capsys.readouterr().err == "collaboration-policy: EVENT_TOO_LARGE\n"


def test_cli_hostile_event_is_reported_by_code_only(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    hostile = f"{CANARY} $(touch pwned) `id` ; | & > <\n::error::forged"
    path = _write_event(tmp_path, json.dumps(_event(title=hostile, head=hostile, base=hostile)))
    assert policy.main(["--event-file", str(path)], environ={}) == 1
    captured = capsys.readouterr()
    assert captured.err.splitlines() == [
        "collaboration-policy: BASE_NOT_MAIN",
        "collaboration-policy: TITLE_INVALID",
        "collaboration-policy: BRANCH_INVALID",
    ]
    assert captured.out == ""
    assert not (tmp_path / "pwned").exists()
    assert not Path("pwned").exists()


def test_cli_usage_errors_do_not_echo_arguments(
    capsys: pytest.CaptureFixture[str],
) -> None:
    for argv in (
        [f"--{CANARY}"],
        ["--event-file"],
        ["--event", "x"],
        [CANARY],
    ):
        with pytest.raises(SystemExit) as raised:
            policy.main(argv, environ={})
        assert raised.value.code == 2
        captured = capsys.readouterr()
        assert captured.err == "collaboration-policy: USAGE_INVALID\n"
        assert CANARY not in captured.out + captured.err


def test_validator_has_no_process_or_network_dependencies() -> None:
    source = (REPOSITORY / "scripts" / "check_collaboration_policy.py").read_text(
        encoding="utf-8"
    )
    imported = set(re.findall(r"^(?:import|from) ([A-Za-z_][A-Za-z0-9_]*)", source, re.M))
    assert imported.isdisjoint(
        {"subprocess", "socket", "urllib", "http", "requests", "shlex", "git", "ctypes"}
    )
    assert "os.system" not in source and "eval(" not in source and "exec(" not in source


def _active_workflow() -> str:
    lines = WORKFLOW.read_text(encoding="utf-8").splitlines()
    return "\n".join(line for line in lines if not line.lstrip().startswith("#")) + "\n"


def test_workflow_triggers_only_on_pull_request_to_main() -> None:
    active = _active_workflow()
    triggers = re.search(r"^on:\n((?:[ ]+.*\n|\n)+)", active, re.M)
    assert triggers is not None
    block = triggers.group(1)
    assert re.search(r"^  pull_request:\s*$", block, re.M)
    assert not re.search(r"^  (?!pull_request:)\S", block, re.M)
    assert "pull_request_target" not in active
    assert "workflow_run" not in active
    assert re.search(r"^    branches:\n      - main$", block, re.M)


def test_workflow_is_read_only_bounded_and_secret_free() -> None:
    active = _active_workflow()
    assert re.search(r"^permissions:\n  contents: read$", active, re.M)
    assert len(re.findall(r"^\s*permissions:", active, re.M)) == 1
    assert re.search(r"^    timeout-minutes: 5$", active, re.M)
    assert "secrets" not in active
    assert "GITHUB_TOKEN" not in active
    assert "continue-on-error" not in active


def test_workflow_checks_out_only_the_base_commit() -> None:
    active = _active_workflow()
    checkouts = re.findall(r"uses: actions/checkout@\S+", active)
    assert len(checkouts) == 1
    assert re.fullmatch(r"uses: actions/checkout@[0-9a-f]{40}", checkouts[0])
    assert "ref: ${{ github.event.pull_request.base.sha }}" in active
    assert "persist-credentials: false" in active
    for head_reference in (
        "pull_request.head",
        "github.head_ref",
        "github.sha",
        "refs/pull/",
        "repository:",
    ):
        assert head_reference not in active


def test_workflow_never_interpolates_untrusted_metadata_into_commands() -> None:
    active = _active_workflow()
    lines = active.splitlines()
    run_lines = [line for line in lines if re.match(r"\s*(?:- )?run:", line)]
    assert run_lines
    assert not any("${{" in line for line in run_lines)
    assert not any(re.match(r"\s*run:\s*[|>]", line) for line in run_lines)
    interpolated = [line for line in lines if "${{" in line]
    assert all("github.event.pull_request.base.sha" in line for line in interpolated)
    for untrusted in ("title", "body", "head_ref", "head.ref", "label", "user.login"):
        assert untrusted not in active


def test_workflow_runs_the_shared_validator_with_python_311() -> None:
    active = _active_workflow()
    assert re.search(r'python-version: "3\.11"', active)
    assert "scripts/check_collaboration_policy.py" in active
    assert re.search(r"^    name: Collaboration policy$", active, re.M)
