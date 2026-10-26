"""Localización y ejecución de FFmpeg/FFprobe, detección de codificadores por hardware."""

from __future__ import annotations

import json
import logging
import re
import subprocess
import threading
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clutchreel.utils.paths import find_ffmpeg, find_ffprobe
from clutchreel.utils.winutil import subprocess_flags

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class FFmpegError(Exception):
    """Error de FFmpeg con mensaje entendible y cola del log."""


@dataclass
class MediaInfo:
    duration: float = 0.0
    width: int = 0
    height: int = 0
    fps: float = 0.0
    has_audio: bool = False
    has_video: bool = False
    codec: str = ""
    size_bytes: int = 0


class FFmpeg:
    """Envoltorio de FFmpeg con progreso y cancelación."""

    _hw_cache: dict[str, bool] = {}
    _hw_lock = threading.Lock()

    def __init__(self, configured_path: str | None = None) -> None:
        self.path: Path | None = find_ffmpeg(configured_path)
        self.probe_path: Path | None = find_ffprobe(self.path)

    @property
    def available(self) -> bool:
        return self.path is not None

    def version(self) -> str:
        if not self.path:
            return ""
        try:
            out = subprocess.run(
                [str(self.path), "-version"], capture_output=True, text=True, timeout=15, creationflags=subprocess_flags()
            )
            first = (out.stdout or "").splitlines()[0] if out.stdout else ""
            m = re.search(r"ffmpeg version (\S+)", first)
            return m.group(1) if m else first
        except (OSError, subprocess.SubprocessError):
            return ""

    # --------------------------------------------------------------- probe --

    def probe(self, path: Path) -> MediaInfo:
        info = MediaInfo()
        if not self.probe_path or not path.exists():
            return info
        try:
            info.size_bytes = path.stat().st_size
        except OSError:
            pass
        cmd = [
            str(self.probe_path),
            "-v",
            "error",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            str(path),
        ]
        try:
            out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=subprocess_flags())
            data = json.loads(out.stdout or "{}")
        except (OSError, subprocess.SubprocessError, ValueError) as exc:
            log.warning("ffprobe falló en %s: %s", path, exc)
            return info
        fmt = data.get("format", {})
        try:
            info.duration = float(fmt.get("duration", 0.0))
        except (TypeError, ValueError):
            info.duration = 0.0
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video" and not info.has_video:
                info.has_video = True
                info.width = int(stream.get("width", 0) or 0)
                info.height = int(stream.get("height", 0) or 0)
                info.codec = str(stream.get("codec_name", ""))
                rate = str(stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1")
                try:
                    num, den = rate.split("/")
                    info.fps = float(num) / float(den) if float(den) else 0.0
                except (ValueError, ZeroDivisionError):
                    info.fps = 0.0
                if not info.duration:
                    try:
                        info.duration = float(stream.get("duration", 0.0))
                    except (TypeError, ValueError):
                        pass
            elif stream.get("codec_type") == "audio":
                info.has_audio = True
        return info

    # ------------------------------------------------------------ encoders --

    def list_encoders(self) -> set[str]:
        if not self.path:
            return set()
        try:
            out = subprocess.run(
                [str(self.path), "-hide_banner", "-loglevel", "error", "-encoders"], capture_output=True, text=True, timeout=30, creationflags=subprocess_flags()
            )
        except (OSError, subprocess.SubprocessError):
            return set()
        names: set[str] = set()
        for line in (out.stdout or "").splitlines():
            m = re.match(r"\s*[VAS][\.A-Z]{5}\s+(\S+)", line)
            if m:
                names.add(m.group(1))
        return names

    def encoder_works(self, encoder: str) -> bool:
        """Prueba real de codificación de 0,2 s (cacheada)."""
        with self._hw_lock:
            if encoder in self._hw_cache:
                return self._hw_cache[encoder]
        ok = False
        if self.path:
            cmd = [
                str(self.path),
                "-hide_banner",
                "-loglevel",
                "error",
                "-f",
                "lavfi",
                "-i",
                "testsrc=size=256x256:rate=30:duration=0.2",
                "-c:v",
                encoder,
                "-f",
                "null",
                "-",
            ]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=40, creationflags=subprocess_flags())
                ok = res.returncode == 0
            except (OSError, subprocess.SubprocessError):
                ok = False
        with self._hw_lock:
            self._hw_cache[encoder] = ok
        log.info("Codificador %s: %s", encoder, "disponible" if ok else "no disponible")
        return ok

    def pick_video_encoder(self, codec: str = "h264", hw_pref: str = "auto") -> str:
        """Devuelve el codificador a usar: NVENC/AMF/QSV si funcionan, si no CPU."""
        family = "hevc" if codec == "hevc" else "h264"
        candidates: list[str] = []
        order = {"nvenc": [f"{family}_nvenc"], "amf": [f"{family}_amf"], "qsv": [f"{family}_qsv"], "cpu": []}
        if hw_pref == "auto":
            candidates = [f"{family}_nvenc", f"{family}_amf", f"{family}_qsv"]
        else:
            candidates = order.get(hw_pref, [])
        available = self.list_encoders()
        for cand in candidates:
            if cand in available and self.encoder_works(cand):
                return cand
        return "libx265" if family == "hevc" else "libx264"

    # ----------------------------------------------------------------- run --

    def run(
        self,
        args: list[str],
        total_duration: float = 0.0,
        progress: ProgressFn | None = None,
        cancel: threading.Event | None = None,
        timeout: float | None = None,
    ) -> None:
        """Ejecuta FFmpeg con ``-progress`` y lanza :class:`FFmpegError` si falla."""
        if not self.path:
            raise FFmpegError("FFmpeg no está disponible. Ejecuta Iniciar.bat o configura la ruta en Ajustes.")
        cmd = [str(self.path), "-hide_banner", "-y", "-nostdin", "-loglevel", "error", "-progress", "pipe:1", "-stats_period", "0.5", *args]
        log.debug("FFmpeg: %s", subprocess.list2cmdline(cmd))
        try:
            proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=subprocess_flags(),
            )
        except OSError as exc:
            raise FFmpegError(f"No se pudo ejecutar FFmpeg: {exc}") from exc

        stderr_lines: list[str] = []

        def pump_stderr() -> None:
            assert proc.stderr is not None
            for line in proc.stderr:
                stderr_lines.append(line.rstrip())
                if len(stderr_lines) > 200:
                    del stderr_lines[:100]

        thread = threading.Thread(target=pump_stderr, name="ffmpeg-stderr", daemon=True)
        thread.start()
        assert proc.stdout is not None
        try:
            for line in proc.stdout:
                if cancel is not None and cancel.is_set():
                    proc.kill()
                    raise FFmpegError("Cancelado por el usuario.")
                line = line.strip()
                if line.startswith("out_time_ms=") or line.startswith("out_time_us="):
                    try:
                        micro = int(line.split("=", 1)[1])
                    except ValueError:
                        continue
                    if total_duration > 0 and progress:
                        frac = max(0.0, min(1.0, micro / 1_000_000 / total_duration))
                        progress(frac, "")
                elif line.startswith("progress=end") and progress:
                    progress(1.0, "")
            proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired as exc:
            proc.kill()
            raise FFmpegError("FFmpeg tardó demasiado y se canceló.") from exc
        finally:
            thread.join(timeout=2)
        if proc.returncode != 0:
            tail = "\n".join(stderr_lines[-12:])
            if "No space left" in tail or "not enough space" in tail.lower():
                raise FFmpegError("No hay espacio suficiente en el disco de salida.")
            raise FFmpegError(f"FFmpeg terminó con error ({proc.returncode}):\n{tail}")


def font_file_for(family: str) -> Path | None:
    """Fichero TTF de Windows para la familia indicada (Segoe UI, Arial…)."""
    fonts = Path("C:/Windows/Fonts")
    table = {
        "segoe ui": ["segoeuib.ttf", "segoeui.ttf"],
        "arial": ["arialbd.ttf", "arial.ttf"],
        "impact": ["impact.ttf"],
        "verdana": ["verdanab.ttf", "verdana.ttf"],
        "consolas": ["consolab.ttf", "consola.ttf"],
        "bahnschrift": ["bahnschrift.ttf"],
    }
    for name in [*table.get(family.lower(), []), "segoeuib.ttf", "arialbd.ttf", "arial.ttf"]:
        cand = fonts / name
        if cand.exists():
            return cand
    return None


def escape_drawtext(text: str) -> str:
    """Escapa texto para el filtro ``drawtext`` de FFmpeg."""
    out = text.replace("\\", "\\\\")
    for ch in ("'", ":", "%", ",", ";", "[", "]"):
        out = out.replace(ch, "\\" + ch)
    return out


def escape_filter_path(path: Path) -> str:
    """Ruta usable dentro de un filtro (``C\\:/Windows/Fonts/x.ttf``)."""
    text = str(path).replace("\\", "/")
    return text.replace(":", "\\:").replace("'", "\\'")
