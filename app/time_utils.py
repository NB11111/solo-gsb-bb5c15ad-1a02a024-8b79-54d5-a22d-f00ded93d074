"""Timestamp helpers.

All event times are normalised to UTC internally. The API accepts the most
common ISO 8601 forms (``2026-09-21T10:00:00Z``, with offsets, or a naive
timestamp which is assumed to be UTC) and always returns UTC with a ``Z``
suffix.
"""
from __future__ import annotations

from decimal import Decimal, ROUND_FLOOR
from datetime import datetime, timezone
from fractions import Fraction
from typing import Any


class TimestampError(ValueError):
    """Raised when an observed_at value cannot be parsed."""


def seconds_floor_micros(seconds: Any) -> int:
    """Exact floor of a seconds threshold converted to integer microseconds.

    Stored timestamps have microsecond resolution, so every event-time
    distance is an integer number of microseconds ``d``.  Comparing such a
    distance against a seconds threshold ``t`` exactly reduces to an integer
    comparison against ``floor(t * 1_000_000)``:

    * inclusive  ``d <= t``  <=>  ``d <= floor_micros``
    * strict     ``d >  t``  <=>  ``d >  floor_micros``

    The threshold must be judged by the *original* value the request sent,
    not by a rounded microsecond count: ``0.0000015`` seconds (1.5
    microseconds) has floor 1, never the round-half-to-even result 2.
    Query parameters arrive as strings, so strings are parsed as exact
    decimals (``Decimal("0.0000015")`` is exactly 1.5 microseconds); an
    already-parsed ``float`` uses its exact binary value instead.  The caller
    is responsible for having validated that the value is finite.
    """
    if isinstance(seconds, str):
        scaled = Decimal(seconds.strip()) * 1_000_000
        # ROUND_FLOOR (not int(), which rounds toward zero) so the rule also
        # stays exact for any non-negative decimal the callers allow.
        return int(scaled.to_integral_value(rounding=ROUND_FLOOR))
    # Fraction(float) is the float's exact rational value -- no intermediate
    # rounded float multiplication -- and integer division floors.
    scaled = Fraction(float(seconds)) * 1_000_000
    return scaled.numerator // scaled.denominator


def parse_event_time(value: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise TimestampError("observed_at must be a non-empty ISO 8601 string")
    text = value.strip()
    # datetime.fromisoformat in Python 3.11 understands the trailing Z.
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00").replace("z", "+00:00"))
    except ValueError as exc:
        raise TimestampError(f"invalid ISO 8601 timestamp: {value!r}") from exc
    if dt.tzinfo is None:
        # Naive timestamps are treated as UTC so ordering stays unambiguous.
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _utc_iso(dt: datetime, *, timespec: str) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    if timespec == "seconds":
        return dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    # Microsecond precision (6 digits) so every stored timestamp has the same
    # width: this makes lexicographic string comparison in SQLite identical to
    # chronological comparison.
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def store_event_time(dt: datetime) -> str:
    """Fixed-width, sortable UTC form used for all stored/compared times."""
    return _utc_iso(dt, timespec="microseconds")


def format_event_time(dt: datetime) -> str:
    """Human-facing canonical ISO 8601 UTC form.

    Fractional seconds are preserved with trailing zeros removed (e.g.
    ``...:05.000001Z`` keeps its microseconds while ``...:05.000000Z`` is
    rendered as ``...:05Z``).
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    else:
        dt = dt.astimezone(timezone.utc)
    base = dt.strftime("%Y-%m-%dT%H:%M:%S")
    frac = f"{dt.microsecond:06d}".rstrip("0")
    return base + (f".{frac}" if frac else "") + "Z"
