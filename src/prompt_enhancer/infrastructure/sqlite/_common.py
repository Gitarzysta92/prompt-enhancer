"""Private helpers shared by narrow SQLite repositories."""

from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime, timedelta
import re
import sqlite3
from typing import Protocol


_HEX_64 = re.compile(r"^[a-f0-9]{64}$")
_SAFE_LABEL = re.compile(r"^[a-z0-9][a-z0-9._-]{0,63}$")


class ConnectionScope(Protocol):
    def __call__(
        self, *, readonly: bool = False
    ) -> AbstractContextManager[sqlite3.Connection]: ...


def require_safe_id(value: str) -> str:
    if not _HEX_64.fullmatch(value):
        raise ValueError("identifier must be a 64-character safe identifier")
    return value


def require_safe_label(value: str) -> str:
    if not _SAFE_LABEL.fullmatch(value):
        raise ValueError("value must be a short content-free label")
    return value


def require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must include a timezone")
    return value.astimezone(UTC)


def to_iso(value: datetime) -> str:
    return require_utc(value).isoformat(timespec="microseconds")


def from_iso(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value).astimezone(UTC)


def to_epoch_us(value: datetime) -> int:
    checked = require_utc(value)
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = checked - epoch
    return (
        delta.days * 86_400_000_000
        + delta.seconds * 1_000_000
        + delta.microseconds
    )


def from_epoch_us(value: int) -> datetime:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("epoch microseconds must be an integer")
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    return epoch + timedelta(microseconds=value)
