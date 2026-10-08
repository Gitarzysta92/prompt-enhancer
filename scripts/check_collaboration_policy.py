"""Check pull request metadata against the collaboration naming policy.

The tool reads one GitHub ``pull_request`` event JSON file and inspects only
the target branch, the source branch name, and the title.  It never runs git,
contacts a network, reads credentials, or inspects the pull request body,
changed files, or author identity.  Untrusted values are never echoed: the
only output is a fixed status line or fixed error codes.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import re
import sys
import unicodedata
from typing import Any, Mapping, NoReturn, Sequence


TARGET_BRANCH = "main"
MAX_EVENT_BYTES = 1024 * 1024
MAX_TITLE_CHARS = 200
MAX_BRANCH_CHARS = 100

EVENT_PATH_MISSING = "EVENT_PATH_MISSING"
EVENT_UNREADABLE = "EVENT_UNREADABLE"
EVENT_TOO_LARGE = "EVENT_TOO_LARGE"
EVENT_MALFORMED = "EVENT_MALFORMED"
EVENT_SHAPE = "EVENT_SHAPE"
BASE_NOT_MAIN = "BASE_NOT_MAIN"
TITLE_INVALID = "TITLE_INVALID"
BRANCH_INVALID = "BRANCH_INVALID"
USAGE_INVALID = "USAGE_INVALID"

_TITLE = re.compile(
    r"(?:feat|fix|docs|test|refactor|chore|ci|build|perf|style)"
    r"(?:\([a-z0-9][a-z0-9._-]{0,39}\))?!?: \S.*"
)
_BRANCH = re.compile(
    r"(?:feature|fix|docs|test|refactor|chore|ci|release|codex)"
    r"/[a-z0-9]+(?:[.-][a-z0-9]+)*",
    re.ASCII,
)
_FORBIDDEN_CATEGORIES = frozenset({"Cc", "Cf", "Cs", "Co", "Cn", "Zl", "Zp"})


def _has_forbidden_character(value: str) -> bool:
    return any(unicodedata.category(ch) in _FORBIDDEN_CATEGORIES for ch in value)


def _title_valid(title: str) -> bool:
    return (
        0 < len(title) <= MAX_TITLE_CHARS
        and title == title.strip()
        and not _has_forbidden_character(title)
        and _TITLE.fullmatch(title) is not None
    )


def _branch_valid(branch: str) -> bool:
    return (
        0 < len(branch) <= MAX_BRANCH_CHARS
        and branch.isascii()
        and _BRANCH.fullmatch(branch) is not None
    )


def _ref(container: Any) -> str | None:
    if not isinstance(container, Mapping):
        return None
    value = container.get("ref")
    return value if isinstance(value, str) else None


def validate(event: Any) -> tuple[str, ...]:
    """Return fixed error codes for a parsed pull request event; empty means valid."""

    pull_request = event.get("pull_request") if isinstance(event, Mapping) else None
    if not isinstance(pull_request, Mapping):
        return (EVENT_SHAPE,)
    title = pull_request.get("title")
    head_ref = _ref(pull_request.get("head"))
    base_ref = _ref(pull_request.get("base"))
    if not isinstance(title, str) or head_ref is None or base_ref is None:
        return (EVENT_SHAPE,)

    errors: list[str] = []
    if base_ref != TARGET_BRANCH:
        errors.append(BASE_NOT_MAIN)
    if not _title_valid(title):
        errors.append(TITLE_INVALID)
    if not _branch_valid(head_ref):
        errors.append(BRANCH_INVALID)
    return tuple(errors)


def load_event(path: Path) -> tuple[Any, str | None]:
    """Read a size-bounded UTF-8 JSON file; return ``(event, error_code)``."""

    try:
        with path.open("rb") as handle:
            payload = handle.read(MAX_EVENT_BYTES + 1)
    except (OSError, ValueError):
        return None, EVENT_UNREADABLE
    if len(payload) > MAX_EVENT_BYTES:
        return None, EVENT_TOO_LARGE
    try:
        return json.loads(payload.decode("utf-8")), None
    except (UnicodeDecodeError, ValueError, RecursionError):
        return None, EVENT_MALFORMED


class _FixedErrorParser(argparse.ArgumentParser):
    def error(self, message: str) -> NoReturn:
        print(f"collaboration-policy: {USAGE_INVALID}", file=sys.stderr)
        raise SystemExit(2)


def _parser() -> argparse.ArgumentParser:
    parser = _FixedErrorParser(
        description="Validate pull request metadata naming policy.",
        allow_abbrev=False,
    )
    parser.add_argument(
        "--event-file",
        help="pull_request event JSON; defaults to the GITHUB_EVENT_PATH variable",
    )
    return parser


def main(
    argv: Sequence[str] | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    args = _parser().parse_args(argv)
    env = os.environ if environ is None else environ
    location = args.event_file or env.get("GITHUB_EVENT_PATH")
    if not location:
        codes: tuple[str, ...] = (EVENT_PATH_MISSING,)
    else:
        event, load_error = load_event(Path(location))
        codes = (load_error,) if load_error else validate(event)
    if codes:
        for code in codes:
            print(f"collaboration-policy: {code}", file=sys.stderr)
        return 1
    print("collaboration-policy: ok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
