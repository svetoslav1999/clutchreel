"""Comprobación de grabaciones: clip vacío/negro y detección de inicio de movimiento."""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from clutchreel.core.export.ffmpeg import FFmpeg
from clutchreel.utils.winutil import subprocess_flags

log = logging.getLogger(__name__)


@dataclass
class ClipCheck:
    ok: bool
    reason: str = ""
    duration: float = 0.0
    mean_brightness: float = 0.0
    motion_start: float | None = None


def _frames_gray(ffmpeg: FFmpeg, path: Path, fps: int = 10, size: int = 64, max_seconds: float = 120.0) -> np.ndarray:
    """Fotogramas en gris ``(n, size, size)`` muestreados a ``fps``."""
    if not ffmpeg.path:
        return np.zeros((0, size, size), dtype=np.uint8)
    cmd = [
        str(ffmpeg.path),
        "-hide_banner",
        "-loglevel",
        "error",
        "-t",
        f"{max_seconds:.1f}",
        "-i",
        str(path),
        "-vf",
        f"fps={fps},scale={size}:{size}",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "gray",
        "-",
    ]
    try:
        out = subprocess.run(cmd, capture_output=True, timeout=180, creationflags=subprocess_flags())
    except (OSError, subprocess.SubprocessError) as exc:
        log.warning("No se pudieron extraer fotogramas: %s", exc)
        return np.zeros((0, size, size), dtype=np.uint8)
    buf = np.frombuffer(out.stdout, dtype=np.uint8)
    n = buf.size // (size * size)
    return buf[: n * size * size].reshape(n, size, size)


def check_clip(ffmpeg: FFmpeg, path: Path, expected_duration: float = 0.0) -> ClipCheck:
    """Comprueba que el clip existe, tiene duración y no es negro/estático."""
    if not path.exists():
        return ClipCheck(False, "El fichero de grabación no existe.")
    if path.stat().st_size < 50_000:
        return ClipCheck(False, "La grabación está vacía (menos de 50 KB).")
    info = ffmpeg.probe(path)
    if not info.has_video or info.duration <= 0.3:
        return ClipCheck(False, "La grabación no contiene vídeo.", info.duration)
    if expected_duration > 0 and info.duration < expected_duration * 0.5:
        return ClipCheck(False, f"La grabación dura {info.duration:.1f} s, menos de la mitad de lo esperado.", info.duration)
    frames = _frames_gray(ffmpeg, path)
    if frames.shape[0] == 0:
        return ClipCheck(True, "No se pudo analizar el contenido; se da por válida.", info.duration)
    brightness = float(frames.mean())
    if brightness < 6.0:
        return ClipCheck(False, "La grabación es negra: OBS no capturó el juego.", info.duration, brightness)
    if frames.shape[0] > 3:
        diffs = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
        if float(np.max(diffs)) < 0.5:
            return ClipCheck(False, "La grabación es una imagen estática: la demo no avanzó.", info.duration, brightness)
    return ClipCheck(True, "", info.duration, brightness, detect_motion_start(frames, 10))


def detect_motion_start(frames: np.ndarray, fps: int, threshold: float = 1.5) -> float | None:
    """Segundo en que empieza el movimiento sostenido (para calibrar latencia)."""
    if frames.shape[0] < 3:
        return None
    diffs = np.abs(np.diff(frames.astype(np.int16), axis=0)).mean(axis=(1, 2))
    for i, d in enumerate(diffs):
        if d > threshold and i + 2 < len(diffs) and diffs[i + 1] > threshold * 0.5:
            return (i + 1) / fps
    return None
