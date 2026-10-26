from __future__ import annotations

import pytest

from clutchreel.core.demo.models import Highlight
from clutchreel.utils.timeutil import format_duration, format_timestamp, seconds_to_ticks, ticks_to_seconds


def test_ticks_seconds_roundtrip():  # type: ignore[no-untyped-def]
    assert ticks_to_seconds(640, 64) == 10.0
    assert ticks_to_seconds(1280, 128) == 10.0
    assert seconds_to_ticks(3.0, 64) == 192
    assert seconds_to_ticks(ticks_to_seconds(12345, 64), 64) == 12345


def test_invalid_tickrate():  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        ticks_to_seconds(10, 0)


def test_highlight_duration():  # type: ignore[no-untyped-def]
    h = Highlight("2k", 3, 6400, 7040, 10.0, "x")
    assert h.duration_seconds(64.0) == 10.0
    assert h.start_seconds(64.0) == 100.0


def test_format():  # type: ignore[no-untyped-def]
    assert format_duration(75.4) == "1:15"
    assert format_duration(3725) == "1:02:05"
    assert format_timestamp(61.5) == "00:01:01.500"
