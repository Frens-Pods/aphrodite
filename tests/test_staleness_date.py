"""`_date_epoch` parses systemd/ISO timestamps in pure Python so live-service
staleness works off-Linux (macOS/BSD lack GNU `date -d`).
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from aphrodite.readiness import _date_epoch  # noqa: E402

_EXPECTED = datetime(2026, 6, 17, 12, 34, 56, tzinfo=timezone.utc).timestamp()


def test_parses_systemd_timestamp_without_gnu_date():
    # systemd ExecMainStartTimestamp form; leading weekday is dropped.
    assert _date_epoch("Wed 2026-06-17 12:34:56 UTC") == _EXPECTED


def test_parses_iso8601():
    assert _date_epoch("2026-06-17T12:34:56+00:00") == _EXPECTED


def test_blank_and_na_and_none_return_none():
    assert _date_epoch("") is None
    assert _date_epoch("n/a") is None
    assert _date_epoch(None) is None


def test_naive_timestamp_is_utc_and_monotonic():
    earlier = _date_epoch("2026-06-17 12:00:00")
    later = _date_epoch("2026-06-17 12:00:05")
    assert earlier is not None and later is not None
    assert later - earlier == 5
