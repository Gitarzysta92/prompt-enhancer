"""Explicit, review-gated online dependency preparation; never build an app."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from prompt_enhancer.infrastructure.frontend_dependency_preparation import (
    FrontendDependencyPreparationError,
    prepare_frontend_dependencies,
)


_SAFE_ERROR_CODES = frozenset({
    "dependency_cleanup_unconfirmed",
    "dependency_cli_invalid",
    "dependency_config_changed",
    "dependency_input_invalid",
    "dependency_install_failed",
    "dependency_node_version_invalid",
    "dependency_npm_changed",
    "dependency_preparation_failed",
    "dependency_process_failed",
    "dependency_publication_changed",
    "dependency_required_missing",
    "dependency_source_output_changed",
    "dependency_tree_oversize",
    "owned_process_cleanup_unconfirmed",
    "owned_process_stderr_limit",
    "owned_process_stdout_limit",
    "owned_process_timeout",
})
_FAILURE_JSON = {
    code: f'{{"passed": false, "error_code": "{code}"}}'
    for code in _SAFE_ERROR_CODES
}


class Parser(argparse.ArgumentParser):
    def error(self, message):
        del message
        raise FrontendDependencyPreparationError("dependency_cli_invalid")


def main(argv=None):
    try:
        parser = Parser(allow_abbrev=False)
        for name in ("frontend-root", "source-manifest", "node-executable", "npm-root", "npm-manifest", "destination"):
            parser.add_argument("--" + name, type=Path, required=True)
        for name in ("source-manifest-size", "node-size", "npm-manifest-size"):
            parser.add_argument("--" + name, type=int, required=True)
        for name in ("source-manifest-sha256", "node-sha256", "node-version", "npm-manifest-sha256", "npm-version"):
            parser.add_argument("--" + name, required=True)
        receipt = prepare_frontend_dependencies(**vars(parser.parse_args(argv)))
        output = json.dumps(receipt, sort_keys=True)
    except FrontendDependencyPreparationError as error:
        candidate = error.args[0] if len(error.args) == 1 else None
        code = (
            candidate
            if isinstance(candidate, str) and candidate in _SAFE_ERROR_CODES
            else "dependency_preparation_failed"
        )
        print(_FAILURE_JSON[code])
        return 1
    except Exception:
        print(_FAILURE_JSON["dependency_preparation_failed"])
        return 1
    print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
