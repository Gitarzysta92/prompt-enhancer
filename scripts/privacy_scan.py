"""Fail closed on common secrets, personal emails, and private home paths.

This scanner is intentionally dependency-free so it can run before installing the
project. It is defense in depth, not a replacement for reviewing staged changes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import re
import struct
import sys
from typing import Iterable, Sequence
import zlib


_ALWAYS_SKIPPED_PARTS = frozenset({".git"})
_PROHIBITED_PRIVATE_PARTS = frozenset(
    {
        ".claude",
        ".codex",
        ".secrets",
        "archived_sessions",
        "data",
        "exports",
        "logs",
        "models",
        "secrets",
        "sessions",
        "var",
    }
)
_SKIPPED_GENERATED_PARTS = frozenset(
    {
        ".cache",
        ".mypy_cache",
        ".next",
        ".pytest_cache",
        ".ruff_cache",
        ".svelte-kit",
        ".venv",
        "__pycache__",
        "build",
        "coverage",
        "dist",
        "htmlcov",
        "node_modules",
        "runtime",
        "venv",
    }
)
_SKIPPED_GENERATED_PREFIXES = (
    ("src", "prompt_enhancer", "_resources", "dashboard"),
)
_PROHIBITED_NAMES = frozenset(
    {
        ".claude.json",
        "auth.json",
        "credentials.json",
        "history.jsonl",
    }
)
_PROHIBITED_SUFFIXES = (
    ".arrow",
    ".bin",
    ".db",
    ".db-shm",
    ".db-wal",
    ".duckdb",
    ".duckdb.wal",
    ".feather",
    ".gguf",
    ".index",
    ".key",
    ".ndjson",
    ".onnx",
    ".parquet",
    ".pem",
    ".pfx",
    ".p12",
    ".pyc",
    ".safetensors",
    ".sqlite",
    ".sqlite-shm",
    ".sqlite-wal",
    ".sqlite3",
    ".sqlite3-shm",
    ".sqlite3-wal",
    ".transcript.json",
    ".transcript.jsonl",
    ".vault",
)
_MAX_TEXT_BYTES = 2 * 1024 * 1024

# Each entry was added only after a maintainer visually approved that synthetic
# gallery capture.  An unreviewed image has no entry and therefore remains
# prohibited.  Every entry must be a repository-relative
# ``docs/images/<fixed-name>.png`` path and the SHA-256 of that exact reviewed
# file.  Do not add a glob, a directory exception, or a filename supplied at
# scan time: public screenshots are binary and need a tighter boundary than
# text fixtures.
_APPROVED_SYNTHETIC_GALLERY_PNG_SHA256: dict[str, str] = {
    # Source-derived architecture diagrams, visually reviewed 2026-10-08.
    "docs/images/architecture-agent.png": "21ba293a01f8368aa9ebb6a856739b069960473a0689aa2d4de7ad3c0a3fb6ff",
    "docs/images/architecture-composer.png": "29c3c3346ac80e6ac452497774758a753abd28d57fef03cb1095b78f6ea0aa91",
    "docs/images/architecture-contracts.png": "13ce828818bbffbb3fab94c9f6a4781878fff55af298ed06dc7c33ce8a59b69e",
    "docs/images/architecture-metrics.png": "afd4e45445efbdc93122c98357aae50ba2681da9dd5500517ee9dc94c944e226",
    "docs/images/architecture-overview.png": "342993449025a6397f6965df9077a66c7402ccf5b157a129eaf9ed720fd96402",
    "docs/images/architecture-release.png": "d2dff57c3e2bfb2d93abf696f4a3f5a6e4a2be0b9e1c429a3b1ac1be6eaa643f",
    "docs/images/architecture-workflows.png": "d95b9f5d977d4fac397bcc7a18f45f8aa5c387a0787703c0511db15cb69db3f5",
    "docs/images/agent-chat.png": "c35e40ab326728e641ef20457d87705cb13fa3b094e9ba70bb226585ae69b80f",
    "docs/images/ensemble-overlay.png": "c0648beb8880308a043f95b76ad347f9204667b653326402ce74bbaad6ac7b9f",
    "docs/images/live-mini-window.png": "4703548a31a45dda9d0c95f6d84ff3a67bc88e4bcbe205006a9bf50db7219369",
    "docs/images/mcp-cards.png": "cd473baf61122eefe3f1a6c1f5b9115fbb62fd69720f4faaf67623d038727d24",
    "docs/images/overview-models.png": "de3eeb8c5a46a2e2fe590fdb3e5ae3d996593a8fd247cca340121fc4f9388d7c",
    "docs/images/session-radar.png": "f5e5c69a12ae8fd6e2658ee32a21cd40ed75eeb31642e5bfb8b26609a0824cf8",
}
_PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"
_MAX_GALLERY_PNG_BYTES = 8 * 1024 * 1024
_MAX_GALLERY_PNG_DIMENSION = 4_096
_MAX_GALLERY_PNG_CHUNKS = 512

_EMAIL = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"(?P<local>[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+)@"
    r"(?P<domain>[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+)"
)
_WINDOWS_HOME = re.compile(
    r"(?i)(?<![A-Za-z0-9])(?:[A-Z]:[\\/])Users[\\/]"
    r"(?P<name>[^\\/\s`\"'<>:]+)"
)
_UNIX_HOME = re.compile(
    ("/" + r"(?:home|Users)/") + r"(?P<name>[^/\s`\"'<>:]+)"
)
_GENERIC_SECRET = re.compile(
    r"(?ix)\b(?:api[_-]?key|access[_-]?token|auth[_-]?token|client[_-]?secret|"
    r"password|passwd|private[_-]?key|refresh[_-]?token)\b\s*(?:=|:)\s*"
    r"[\"']?(?P<value>[^\s\"'`,;]{8,})"
)
_TOKEN_PATTERNS = (
    re.compile(r"\bsk-(?:ant-[A-Za-z0-9_-]+-)?[A-Za-z0-9_-]{20,}\b"),
    re.compile(r"\b(?:gh[opusr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{20,}\b"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
)
_PRIVATE_KEY = re.compile(
    "-----BEGIN " + r"(?:RSA |EC |OPENSSH )?" + "PRIVATE KEY-----"
)

_RESERVED_USERNAMES = frozenset(
    {"default", "example", "example-user", "public", "runner", "test", "user", "username"}
)
_RESERVED_EMAIL_DOMAINS = frozenset(
    {
        "example.com",
        "example.net",
        "example.org",
        "users.noreply.github.com",
    }
)
_SAFE_SECRET_MARKERS = ("example", "fake", "invalid", "placeholder", "redacted", "do_not_use")


@dataclass(frozen=True, slots=True)
class Finding:
    path: str
    line: int | None
    kind: str

    def render(self) -> str:
        location = self.path if self.line is None else f"{self.path}:{self.line}"
        return f"{location}: {self.kind}"


def _reserved_email(domain: str) -> bool:
    normalized = domain.casefold().rstrip(".")
    return normalized in _RESERVED_EMAIL_DOMAINS or normalized.endswith(
        (".example", ".invalid", ".localhost", ".test")
    )


def _safe_example_secret(value: str) -> bool:
    normalized = value.casefold()
    return any(marker in normalized for marker in _SAFE_SECRET_MARKERS)


def _line_findings(relative_path: str, number: int, line: str) -> list[Finding]:
    findings: list[Finding] = []

    for match in _EMAIL.finditer(line):
        if not _reserved_email(match.group("domain")):
            findings.append(Finding(relative_path, number, "possible personal email"))

    for pattern in (_WINDOWS_HOME, _UNIX_HOME):
        for match in pattern.finditer(line):
            if match.group("name").casefold() not in _RESERVED_USERNAMES:
                findings.append(Finding(relative_path, number, "possible private home path"))

    generic = _GENERIC_SECRET.search(line)
    if generic and not _safe_example_secret(generic.group("value")):
        findings.append(Finding(relative_path, number, "possible assigned secret"))

    if _PRIVATE_KEY.search(line):
        findings.append(Finding(relative_path, number, "private key material"))

    if any(pattern.search(line) for pattern in _TOKEN_PATTERNS):
        findings.append(Finding(relative_path, number, "possible access token"))

    return findings


def _lexical_relative(path: Path, root: Path) -> Path:
    absolute = Path(os.path.abspath(os.fspath(path)))
    return absolute.relative_to(root)


def _valid_synthetic_gallery_png(payload: bytes) -> bool:
    """Accept the smallest safe PNG envelope used for approved screenshots.

    PNG metadata can carry arbitrary strings.  Gallery captures therefore use
    only IHDR, IDAT, and IEND; a checksum pin binds the remaining image bytes.
    """

    if (len(payload) < len(_PNG_SIGNATURE) + 12
            or len(payload) > _MAX_GALLERY_PNG_BYTES
            or not payload.startswith(_PNG_SIGNATURE)):
        return False
    cursor = len(_PNG_SIGNATURE)
    chunks = 0
    seen_header = False
    seen_data = False
    while cursor < len(payload):
        if len(payload) - cursor < 12 or chunks >= _MAX_GALLERY_PNG_CHUNKS:
            return False
        length = struct.unpack(">I", payload[cursor:cursor + 4])[0]
        chunk_type = payload[cursor + 4:cursor + 8]
        end = cursor + 12 + length
        if end > len(payload):
            return False
        data = payload[cursor + 8:cursor + 8 + length]
        expected_crc = struct.unpack(">I", payload[cursor + 8 + length:end])[0]
        if zlib.crc32(chunk_type + data) & 0xFFFFFFFF != expected_crc:
            return False
        chunks += 1
        if not seen_header:
            if chunk_type != b"IHDR" or length != 13:
                return False
            width, height, bit_depth, color_type, compression, filter_method, interlace = struct.unpack(
                ">IIBBBBB", data
            )
            if (
                width == 0
                or height == 0
                or width > _MAX_GALLERY_PNG_DIMENSION
                or height > _MAX_GALLERY_PNG_DIMENSION
                or (bit_depth, color_type) not in {
                    (1, 0), (2, 0), (4, 0), (8, 0), (16, 0),
                    (8, 2), (16, 2), (1, 3), (2, 3), (4, 3), (8, 3),
                    (8, 4), (16, 4), (8, 6), (16, 6),
                }
                or compression != 0
                or filter_method != 0
                or interlace not in {0, 1}
            ):
                return False
            seen_header = True
        elif chunk_type == b"IDAT":
            if length == 0:
                return False
            seen_data = True
        elif chunk_type == b"IEND":
            return length == 0 and seen_data and end == len(payload)
        else:
            return False
        cursor = end
    return False


def _gallery_png_finding(relative_path: str, payload: bytes) -> Finding | None:
    """Return a fail-closed result for the one explicitly approved PNG class."""

    expected_hash = _APPROVED_SYNTHETIC_GALLERY_PNG_SHA256.get(relative_path)
    if expected_hash is None:
        return Finding(relative_path, None, "gallery PNG is not allowlisted")
    if len(payload) > _MAX_GALLERY_PNG_BYTES:
        return Finding(relative_path, None, "gallery PNG exceeds size limit")
    if not _valid_synthetic_gallery_png(payload):
        return Finding(relative_path, None, "gallery PNG envelope invalid")
    if (
        re.fullmatch(r"[0-9a-f]{64}", expected_hash) is None
        or hashlib.sha256(payload).hexdigest() != expected_hash
    ):
        return Finding(relative_path, None, "gallery PNG is not an approved hash")
    return None


def _candidate_files(root: Path, paths: Iterable[Path] | None) -> Iterable[Path]:
    ignore_generated_directories = paths is None
    candidates = root.rglob("*") if ignore_generated_directories else paths
    for candidate in candidates:
        path = candidate if candidate.is_absolute() else root / candidate
        try:
            relative = _lexical_relative(path, root)
        except ValueError:
            continue
        folded_relative_parts = tuple(part.casefold() for part in relative.parts)
        directory_parts = {part.casefold() for part in relative.parts[:-1]}
        if directory_parts & _ALWAYS_SKIPPED_PARTS:
            continue
        if (
            ignore_generated_directories
            and (
                directory_parts & _SKIPPED_GENERATED_PARTS
                or any(
                    folded_relative_parts[: len(prefix)] == prefix
                    for prefix in _SKIPPED_GENERATED_PREFIXES
                )
            )
        ):
            continue
        if path.is_symlink() or path.is_file():
            yield path


def scan_repository(root: Path, paths: Iterable[Path] | None = None) -> list[Finding]:
    """Return privacy findings using paths relative to ``root`` only."""

    resolved_root = root.resolve(strict=True)
    findings: list[Finding] = []
    for path in _candidate_files(resolved_root, paths):
        relative_path = _lexical_relative(path, resolved_root).as_posix()
        if path.is_symlink():
            findings.append(
                Finding(relative_path, None, "prohibited repository symlink")
            )
            continue

        relative_parts = {part.casefold() for part in Path(relative_path).parts[:-1]}
        normalized_name = path.name.casefold()
        if relative_parts & _PROHIBITED_PRIVATE_PARTS:
            findings.append(
                Finding(relative_path, None, "prohibited private-data path")
            )
            continue
        if (
            normalized_name in _PROHIBITED_NAMES
            or normalized_name == ".env"
            or normalized_name.startswith(".env.")
            or normalized_name.endswith(_PROHIBITED_SUFFIXES)
        ):
            findings.append(
                Finding(relative_path, None, "prohibited repository artifact")
            )
            continue

        try:
            size = path.stat().st_size
        except OSError:
            findings.append(
                Finding(relative_path, None, "file metadata could not be read")
            )
            continue
        approved_gallery_png = relative_path in _APPROVED_SYNTHETIC_GALLERY_PNG_SHA256
        if approved_gallery_png and size > _MAX_GALLERY_PNG_BYTES:
            findings.append(
                Finding(relative_path, None, "gallery PNG exceeds size limit")
            )
            continue
        if size > _MAX_TEXT_BYTES and not approved_gallery_png:
            findings.append(
                Finding(relative_path, None, "file exceeds privacy scan size limit")
            )
            continue

        try:
            payload = path.read_bytes()
        except OSError:
            findings.append(
                Finding(relative_path, None, "file content could not be read")
            )
            continue
        if approved_gallery_png:
            gallery_finding = _gallery_png_finding(relative_path, payload)
            if gallery_finding is not None:
                findings.append(gallery_finding)
            continue
        if b"\x00" in payload:
            findings.append(
                Finding(relative_path, None, "binary or non-UTF-8 file")
            )
            continue
        try:
            text = payload.decode("utf-8")
        except UnicodeDecodeError:
            findings.append(
                Finding(relative_path, None, "binary or non-UTF-8 file")
            )
            continue

        for number, line in enumerate(text.splitlines(), start=1):
            findings.extend(_line_findings(relative_path, number, line))
    return findings


def main(argv: Sequence[str] | None = None) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(arguments[0]) if arguments else Path(__file__).resolve().parents[1]
    findings = scan_repository(root)
    if findings:
        for finding in findings:
            print(finding.render())
        print(f"privacy scan failed with {len(findings)} finding(s)")
        return 1
    print("privacy scan passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
