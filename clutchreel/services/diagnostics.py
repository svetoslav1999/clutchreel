"""Diagnóstico del sistema: qué falta y cómo arreglarlo."""

from __future__ import annotations

import platform
import socket
import sys
from dataclasses import dataclass

from clutchreel.core.export.ffmpeg import FFmpeg
from clutchreel.services.config import AppConfig
from clutchreel.services.obs_setup import OBS_AUTOCONFIG_ACTION, read_state
from clutchreel.utils import paths
from clutchreel.utils.winutil import free_disk_bytes, is_process_running


@dataclass
class CheckResult:
    name: str
    ok: bool
    detail: str
    fix: str = ""
    warning: bool = False
    fix_action: str = ""  # p. ej. "obs_autoconfig": la UI ofrece arreglarlo con un clic

    @property
    def icon(self) -> str:
        if self.ok:
            return "✅"
        return "⚠️" if self.warning else "❌"


def run_diagnostics(config: AppConfig) -> list[CheckResult]:
    out: list[CheckResult] = []
    ver = platform.python_version()
    out.append(CheckResult("Python", sys.version_info >= (3, 11), f"Python {ver}", "Instala Python 3.11 o superior (Iniciar.bat lo explica)."))

    ff = FFmpeg(config.paths.ffmpeg_path)
    if ff.available:
        out.append(CheckResult("FFmpeg", True, f"{ff.path} ({ff.version()})"))
        enc = ff.pick_video_encoder(config.export.codec, config.export.hw_accel)
        hw = not enc.startswith("lib")
        out.append(CheckResult("Codificador por hardware", True, f"Se usará {enc}" + ("" if hw else " (CPU: más lento)"), warning=not hw))
    else:
        out.append(CheckResult("FFmpeg", False, "No encontrado", "Ejecuta Iniciar.bat (lo descarga solo) o indica la ruta en Ajustes → Rutas."))

    steam = paths.steam_dir()
    out.append(CheckResult("Steam", steam is not None, str(steam) if steam else "No encontrado", "Instala Steam o indica la ruta de CS2 en Ajustes."))
    cs2 = paths.cs2_dir() if not config.paths.cs2_path else paths.Path(config.paths.cs2_path)
    out.append(CheckResult("Counter-Strike 2", bool(cs2 and cs2.exists()), str(cs2) if cs2 else "No encontrado", "Instala CS2 en Steam o indica la carpeta en Ajustes."))
    demo_dirs = [paths.Path(config.paths.demo_folder)] if config.paths.demo_folder else paths.cs2_demo_dirs()
    demos = paths.find_demo_files(demo_dirs)
    out.append(CheckResult("Carpeta de demos", bool(demo_dirs), f"{len(demos)} demos en {demo_dirs[0] if demo_dirs else '—'}", "Configura la carpeta de demos en Ajustes.", warning=bool(demo_dirs) and not demos))

    obs = paths.obs_exe() if not config.paths.obs_path else paths.Path(config.paths.obs_path)
    out.append(CheckResult("OBS Studio", bool(obs and obs.exists()), str(obs) if obs else "No encontrado", "Instala OBS Studio 28+ desde obsproject.com (incluye obs-websocket)."))
    running = is_process_running("obs64.exe")
    ws_ok = False
    try:
        with socket.create_connection((config.obs.host, int(config.obs.port)), timeout=1.0):
            ws_ok = True
    except OSError:
        ws_ok = False
    ws_state = read_state()
    if not ws_state.exists or ws_state.corrupt or not ws_state.enabled:
        reason = "no existe" if not ws_state.exists else "está dañado" if ws_state.corrupt else "está desactivado"
        out.append(
            CheckResult(
                "OBS WebSocket",
                False,
                f"El servidor WebSocket de OBS {reason} (config.json del plugin obs-websocket)",
                "Pulsa «Configurar OBS automáticamente»: lo activa, guarda puerto y contraseña y reabre OBS.",
                fix_action=OBS_AUTOCONFIG_ACTION,
            )
        )
    elif running:
        out.append(
            CheckResult(
                "OBS WebSocket",
                ws_ok,
                f"Puerto {config.obs.port} " + ("abierto" if ws_ok else "cerrado"),
                "En OBS: Herramientas → Ajustes del servidor WebSocket → Activar. O cierra OBS y deja que ClutchReel lo abra.",
            )
        )
    else:
        out.append(CheckResult("OBS WebSocket", True, f"Activado en el puerto {ws_state.port}; OBS cerrado (ClutchReel lo abrirá)", warning=True))

    out.append(
        CheckResult(
            "Jugador",
            config.player.steamid64 > 0,
            f"{config.player.name} ({config.player.steamid64})" if config.player.steamid64 else "Sin configurar",
            "Elige tu jugador en el asistente o en Ajustes → Jugador.",
        )
    )
    out_dir = paths.Path(config.paths.output_folder) if config.paths.output_folder else paths.default_output_dir()
    free_gb = free_disk_bytes(out_dir) / 1e9
    out.append(CheckResult("Espacio en disco", free_gb >= 5, f"{free_gb:.1f} GB libres en {out_dir}", "Libera espacio o cambia la carpeta de salida.", warning=5 > free_gb >= 2))
    try:
        from PySide6.QtMultimedia import QMediaPlayer  # noqa: F401

        out.append(CheckResult("Vista previa de vídeo", True, "QtMultimedia disponible"))
    except Exception as exc:  # noqa: BLE001
        out.append(CheckResult("Vista previa de vídeo", False, f"QtMultimedia no disponible: {exc}", "Reinstala dependencias con Iniciar.bat.", warning=True))
    if config.youtube.enabled:
        ok = bool(config.youtube.client_secrets_path and paths.Path(config.youtube.client_secrets_path).exists())
        out.append(CheckResult("YouTube", ok, "Credenciales encontradas" if ok else "Falta client_secrets.json", "Sigue el README para crear credenciales OAuth.", warning=True))
    return out


def diagnostics_text(results: list[CheckResult]) -> str:
    lines = []
    for r in results:
        lines.append(f"{r.icon} {r.name}: {r.detail}")
        if not r.ok and r.fix:
            lines.append(f"    → {r.fix}")
    return "\n".join(lines)
