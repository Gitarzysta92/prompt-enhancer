"""Canonical reporting periods.

Every published period is one of a fixed set of buckets named by a short key.
Callers cannot choose arbitrary start and end instants, which is what stops an
observer from differencing two overlapping windows to isolate one person's
contribution, and it removes two free-form timestamp fields from the
publication surface.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re

from pydantic import model_validator

from ...domain import StrictModel


MINIMUM_BUCKET_YEAR = 2020
MAXIMUM_BUCKET_YEAR = 2100

ISO_WEEK_KEY = re.compile(r"^(?P<year>\d{4})-W(?P<week>\d{2})$")
CALENDAR_MONTH_KEY = re.compile(r"^(?P<year>\d{4})-(?P<month>\d{2})$")


class ReportingBucketKind(StrEnum):
    ISO_WEEK = "iso_week"
    CALENDAR_MONTH = "calendar_month"


class ReportingBucket(StrictModel):
    """One canonical period, identified by kind and a strict key."""

    kind: ReportingBucketKind
    key: str

    @model_validator(mode="after")
    def canonical_key(self) -> ReportingBucket:
        # Parsing here means an invalid bucket cannot exist as a value at all,
        # so no downstream caller has to re-check it.
        self.period()
        return self

    def period(self) -> tuple[datetime, datetime]:
        """Return the half-open UTC interval this bucket denotes."""

        if self.kind is ReportingBucketKind.ISO_WEEK:
            match = ISO_WEEK_KEY.fullmatch(self.key)
            if match is None:
                raise ValueError("ISO week buckets use a YYYY-Www key")
            year = int(match.group("year"))
            week = int(match.group("week"))
            _require_supported_year(year)
            if not 1 <= week <= 53:
                raise ValueError("ISO week numbers run from 01 to 53")
            try:
                start = datetime.fromisocalendar(year, week, 1)
            except ValueError as error:
                raise ValueError("that ISO week does not exist") from error
            start = start.replace(tzinfo=UTC)
            return start, start + timedelta(days=7)

        match = CALENDAR_MONTH_KEY.fullmatch(self.key)
        if match is None:
            raise ValueError("calendar month buckets use a YYYY-MM key")
        year = int(match.group("year"))
        month = int(match.group("month"))
        _require_supported_year(year)
        if not 1 <= month <= 12:
            raise ValueError("calendar months run from 01 to 12")
        start = datetime(year, month, 1, tzinfo=UTC)
        if month == 12:
            end = datetime(year + 1, 1, 1, tzinfo=UTC)
        else:
            end = datetime(year, month + 1, 1, tzinfo=UTC)
        return start, end

    @property
    def start(self) -> datetime:
        return self.period()[0]

    @property
    def end(self) -> datetime:
        return self.period()[1]


def _require_supported_year(year: int) -> None:
    if not MINIMUM_BUCKET_YEAR <= year <= MAXIMUM_BUCKET_YEAR:
        raise ValueError("reporting years stay inside the supported range")


__all__ = [
    "CALENDAR_MONTH_KEY",
    "ISO_WEEK_KEY",
    "MAXIMUM_BUCKET_YEAR",
    "MINIMUM_BUCKET_YEAR",
    "ReportingBucket",
    "ReportingBucketKind",
]
