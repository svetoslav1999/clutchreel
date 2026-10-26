"""Gestión de música: pistas disponibles y detección básica de beats (opcional)."""

from __future__ import annotations

import logging
import random
from pathlib import Path

from clutchreel.utils.paths import assets_dir

log = logging.getLogger(__name__)

AUDIO_EXT = {".mp3", ".wav", ".ogg", ".flac", ".m4a", ".aac", ".opus"}


def bundled_music_dir() -> Path:
    return assets_dir() / "music"


def list_tracks(folder: str | Path | None) -> list[Path]:
    """Pistas de la carpeta del usuario + las incluidas en ``assets/music``."""
    tracks: list[Path] = []
    folders: list[Path] = []
    if folder:
        folders.append(Path(folder))
    folders.append(bundled_music_dir())
    for f in folders:
        try:
            if f.is_dir():
                tracks.extend(sorted(p for p in f.iterdir() if p.suffix.lower() in AUDIO_EXT))
        except OSError:
            continue
    return tracks


def pick_track(folder: str | Path | None, chosen: str = "") -> Path | None:
    if chosen:
        p = Path(chosen)
        if p.is_file():
            return p
        if p.is_dir():
            inside = list_tracks(p)
            return random.choice(inside) if inside else None
    tracks = list_tracks(folder)
    return random.choice(tracks) if tracks else None


def detect_beats(track: Path) -> list[float]:
    """Tiempos de beat (s) con librosa si está instalada; si no, lista vacía."""
    try:
        import librosa  # type: ignore[import-not-found]
    except ImportError:
        log.info("librosa no instalada: sincronización al ritmo no disponible")
        return []
    try:
        y, sr = librosa.load(str(track), mono=True)
        _tempo, frames = librosa.beat.beat_track(y=y, sr=sr)
        return [float(t) for t in librosa.frames_to_time(frames, sr=sr)]
    except Exception as exc:  # noqa: BLE001
        log.warning("Detección de beats falló: %s", exc)
        return []


def snap_durations_to_beats(durations: list[float], beats: list[float]) -> list[float]:
    """Ajusta cada duración de clip al beat más cercano acumulado (±0,6 s máximo)."""
    if not beats:
        return durations
    out: list[float] = []
    elapsed = 0.0
    for d in durations:
        target = elapsed + d
        nearest = min(beats, key=lambda b: abs(b - target))
        if abs(nearest - target) <= 0.6 and nearest - elapsed > 0.8:
            d = nearest - elapsed
        out.append(d)
        elapsed += d
    return out
