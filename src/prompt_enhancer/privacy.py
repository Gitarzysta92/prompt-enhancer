"""Local privacy primitives used before any persistence boundary."""

from __future__ import annotations

import hashlib
import hmac
import os
from pathlib import Path
import secrets
import stat


PSEUDONYM_KEY_BYTES = 32


class PrivacyBoundaryError(RuntimeError):
    """Raised when a local privacy invariant cannot be satisfied."""


class Pseudonymizer:
    """Create stable installation-local pseudonyms with domain separation."""

    def __init__(self, key: bytes):
        if len(key) != PSEUDONYM_KEY_BYTES:
            raise ValueError(f"pseudonym key must be {PSEUDONYM_KEY_BYTES} bytes")
        self._key = key

    def pseudonymize(self, namespace: str, value: str) -> str:
        if not namespace or "\x00" in namespace:
            raise ValueError("namespace must be non-empty and cannot contain NUL")
        if not value:
            raise ValueError("source identifier must be non-empty")
        message = namespace.encode("utf-8") + b"\x00" + value.encode("utf-8")
        return hmac.new(self._key, message, hashlib.sha256).hexdigest()


def _restrict_private_file(path: Path) -> None:
    try:
        path.chmod(0o600)
        if os.name != "nt" and stat.S_IMODE(path.stat().st_mode) & 0o077:
            raise PrivacyBoundaryError("private state file permissions are too broad")
    except OSError as exc:
        raise PrivacyBoundaryError(
            "could not restrict private state file permissions"
        ) from exc


def _prepare_private_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.parent.is_symlink():
        raise PrivacyBoundaryError("private state directory cannot be a symlink")
    try:
        path.parent.chmod(0o700)
    except OSError as exc:
        raise PrivacyBoundaryError(
            "could not restrict private state directory permissions"
        ) from exc


def _read_private_file(path: Path) -> bytes:
    if path.is_symlink():
        raise PrivacyBoundaryError("private state file cannot be a symlink")
    if not path.is_file():
        raise PrivacyBoundaryError("private state path must be a regular file")
    _restrict_private_file(path)
    data = path.read_bytes()
    if not data:
        raise PrivacyBoundaryError("private state file cannot be empty")
    return data


def _create_private_file(path: Path, data: bytes) -> None:
    # Windows text-mode descriptors translate LF bytes and corrupt random keys.
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_BINARY", 0)
    descriptor = os.open(path, flags, 0o600)
    try:
        os.write(descriptor, data)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _restrict_private_file(path)


def load_pseudonymizer(path: Path) -> Pseudonymizer:
    """Load an existing local HMAC key; never create one as a side effect.

    Hook receivers and other processes that must not initialize state use
    this instead of :func:`load_or_create_pseudonymizer`.
    """

    if path.is_symlink() or not path.is_file():
        raise PrivacyBoundaryError("local pseudonym key is absent")
    key = _read_private_file(path)
    if len(key) != PSEUDONYM_KEY_BYTES:
        raise PrivacyBoundaryError("local pseudonym key has an unexpected size")
    return Pseudonymizer(key)


def load_or_create_pseudonymizer(path: Path) -> Pseudonymizer:
    """Load or create a local HMAC key without ever logging its value."""

    _prepare_private_parent(path)

    if path.exists():
        key = _read_private_file(path)
    else:
        key = secrets.token_bytes(PSEUDONYM_KEY_BYTES)
        try:
            _create_private_file(path, key)
        except FileExistsError:
            key = _read_private_file(path)

    if len(key) != PSEUDONYM_KEY_BYTES:
        raise PrivacyBoundaryError("private pseudonym key has an invalid length")
    return Pseudonymizer(key)


def write_private_text(path: Path, text: str) -> None:
    """Replace a small private text file with restricted permissions."""

    _prepare_private_parent(path)
    if path.is_symlink():
        raise PrivacyBoundaryError("private state file cannot be a symlink")
    data = (text.strip() + "\n").encode("utf-8")
    try:
        path.unlink(missing_ok=True)
        _create_private_file(path, data)
    except OSError as exc:
        raise PrivacyBoundaryError("could not write private state file") from exc


def write_private_text_atomic(path: Path, text: str) -> None:
    """Atomically replace a small private text file in its private directory.

    The previous file remains authoritative until the replacement has been
    completely written and synced. This is intended for bounded lifecycle and
    receipt records where a crash between unlink and create would erase the
    only diagnostic evidence.
    """

    _prepare_private_parent(path)
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise PrivacyBoundaryError("private state path must be a regular file")
    data = (text.strip() + "\n").encode("utf-8")
    temporary = path.with_name(f".{path.name}.{secrets.token_hex(8)}.tmp")
    try:
        _create_private_file(temporary, data)
        os.replace(temporary, path)
        _restrict_private_file(path)
        if os.name != "nt":
            flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
            directory = os.open(path.parent, flags)
            try:
                os.fsync(directory)
            finally:
                os.close(directory)
    except PrivacyBoundaryError:
        raise
    except OSError as exc:
        raise PrivacyBoundaryError("could not atomically write private state file") from exc
    finally:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def load_or_create_api_token(path: Path) -> str:
    """Load or create a local API token. Callers must never print it."""

    _prepare_private_parent(path)
    if path.exists():
        token = _read_private_file(path).decode("ascii")
    else:
        token = secrets.token_urlsafe(32)
        try:
            _create_private_file(path, token.encode("ascii"))
        except FileExistsError:
            token = _read_private_file(path).decode("ascii")
    if len(token) < 32:
        raise PrivacyBoundaryError("local API token is unexpectedly short")
    return token


def load_api_token(path: Path) -> str:
    """Load an existing local API token without initializing application state.

    External-controller helpers use this read-only boundary so invoking a client
    cannot silently create a second installation or print the secret as setup
    output.
    """

    try:
        token = _read_private_file(path).decode("ascii")
    except UnicodeDecodeError:
        raise PrivacyBoundaryError("local API token is malformed") from None
    if len(token) < 32 or any(character.isspace() for character in token):
        raise PrivacyBoundaryError("local API token is unexpectedly short")
    return token
