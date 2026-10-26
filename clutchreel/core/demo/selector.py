"""Selección de las mejores jugadas según duración objetivo y orden."""

from __future__ import annotations

from clutchreel.core.demo.models import Highlight

DURATION_PRESETS: dict[str, tuple[float, float]] = {
    "1-3 min": (60.0, 180.0),
    "3-5 min": (180.0, 300.0),
    "5-10 min": (300.0, 600.0),
    "Sin límite": (0.0, float("inf")),
}

ORDER_CHRONO = "cronológico"
ORDER_SCORE = "mejor puntuación"
ORDER_CRESCENDO = "crescendo"


def select_by_duration(highlights: list[Highlight], tickrate: float, preset: str, per_clip_overhead: float = 0.5) -> list[Highlight]:
    """Elige por puntuación hasta llenar el máximo del preset; devuelve en orden cronológico."""
    lo, hi = DURATION_PRESETS.get(preset, DURATION_PRESETS["Sin límite"])
    if hi == float("inf"):
        return sorted(highlights, key=lambda h: h.start_tick)
    ranked = sorted(highlights, key=lambda h: h.score, reverse=True)
    chosen: list[Highlight] = []
    total = 0.0
    for h in ranked:
        dur = h.duration_seconds(tickrate) + per_clip_overhead
        if total + dur <= hi:
            chosen.append(h)
            total += dur
    # Si no alcanzamos el mínimo, añadimos lo que quepa aunque excedamos un poco.
    if total < lo:
        for h in ranked:
            if h in chosen:
                continue
            dur = h.duration_seconds(tickrate) + per_clip_overhead
            chosen.append(h)
            total += dur
            if total >= lo:
                break
    return sorted(chosen, key=lambda h: h.start_tick)


def order_highlights(highlights: list[Highlight], mode: str) -> list[Highlight]:
    if mode == ORDER_SCORE:
        return sorted(highlights, key=lambda h: h.score, reverse=True)
    if mode == ORDER_CRESCENDO:
        # De menor a mayor puntuación, pero la mejor jugada cierra el vídeo.
        return sorted(highlights, key=lambda h: h.score)
    return sorted(highlights, key=lambda h: h.start_tick)
