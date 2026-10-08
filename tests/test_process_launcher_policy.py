"""Static gate preventing unowned or console-visible production launch paths."""

from __future__ import annotations

import ast
from pathlib import Path


SOURCE_ROOT = Path(__file__).parents[1] / "src" / "prompt_enhancer"


class _ProcessCallVisitor(ast.NodeVisitor):
    def __init__(self, relative_path: str) -> None:
        self.relative_path = relative_path
        self.scope: list[str] = []
        self.calls: set[tuple[str, str, str]] = set()

    def _visit_scope(self, name: str, node: ast.AST) -> None:
        self.scope.append(name)
        self.generic_visit(node)
        self.scope.pop()

    def visit_ClassDef(self, node: ast.ClassDef) -> None:  # noqa: N802
        self._visit_scope(node.name, node)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:  # noqa: N802
        self._visit_scope(node.name, node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:  # noqa: N802
        self._visit_scope(node.name, node)

    def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
        target = node.func
        if (
            isinstance(target, ast.Attribute)
            and target.attr in {"Popen", "run"}
            and isinstance(target.value, ast.Name)
            and target.value.id in {"subprocess", "_subprocess"}
        ):
            self.calls.add(
                (self.relative_path, ".".join(self.scope), target.attr)
            )
        self.generic_visit(node)


def _direct_process_calls() -> set[tuple[str, str, str]]:
    calls: set[tuple[str, str, str]] = set()
    for path in SOURCE_ROOT.rglob("*.py"):
        relative = path.relative_to(SOURCE_ROOT).as_posix()
        visitor = _ProcessCallVisitor(relative)
        visitor.visit(ast.parse(path.read_text(encoding="utf-8")))
        calls.update(visitor.calls)
    return calls


def test_direct_process_creation_is_confined_to_owned_posix_adapters() -> None:
    assert _direct_process_calls() == {
        ("application/local_command_process.py", "_PosixCommandGroup.__init__", "Popen"),
        ("application/local_models.py", "_spawn_owned_runtime", "Popen"),
        ("application/owned_process.py", "_PosixOwnedProcess.__init__", "Popen"),
        ("infrastructure/mcp_stdio_transport.py", "_PosixMcpProcessGroup.__init__", "Popen"),
    }


def test_production_source_has_no_taskkill_or_new_console_escape_hatch() -> None:
    source = "\n".join(
        path.read_text(encoding="utf-8") for path in SOURCE_ROOT.rglob("*.py")
    )
    assert "taskkill.exe" not in source.casefold()
    assert "CREATE_NEW_CONSOLE" not in source


def test_every_helper_launcher_delegates_to_the_shared_owner() -> None:
    required_calls = {
        "application/local_models.py": "run_owned_process(",
        "infrastructure/estimator_runners/subprocess.py": "start_owned_process(",
        "infrastructure/providers/codex_app_server/schema_preflight.py": "run_owned_process(",
        "infrastructure/providers/codex_app_server/transports/stdio_jsonl.py": "start_owned_process(",
        "infrastructure/text_models/compatibility.py": "start_owned_process(",
        "infrastructure/text_models/jobs.py": "start_owned_process(",
        "infrastructure/text_models/model_ensemble.py": "start_owned_process(",
        "infrastructure/text_models/session_links.py": "run_owned_process(",
    }
    for relative, expected_call in required_calls.items():
        source = (SOURCE_ROOT / relative).read_text(encoding="utf-8")
        assert expected_call in source
