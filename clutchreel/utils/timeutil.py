"""Conversión ticks ⇄ segundos y formato de duraciones."""

from __future__ import annotations

DEFAULT_TICKRATE = 64.0


def ticks_to_seconds(ticks: int | float, tickrate: float = DEFAULT_TICKRATE) -> float:
    if tickrate <= 0:
        raise ValueError("tickrate debe ser positivo")
    return float(ticks) / float(tickrate)


def seconds_to_ticks(seconds: float, tickrate: float = DEFAULT_TICKRATE) -> int:
    if tickrate <= 0:
        raise ValueError("tickrate debe ser positivo")
    return round(float(seconds) * float(tickrate))


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def format_duration(seconds: float) -> str:
    """``75.4`` → ``"1:15"``; ``3725`` → ``"1:02:05"``."""
    total = round(max(0.0, seconds))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def format_timestamp(seconds: float) -> str:
    """Formato ``HH:MM:SS.mmm`` aceptado por FFmpeg."""
    total = max(0.0, float(seconds))
    hours = int(total // 3600)
    minutes = int((total % 3600) // 60)
    secs = total % 60
    return f"{hours:02d}:{minutes:02d}:{secs:06.3f}"
