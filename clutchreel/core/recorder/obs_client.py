"""Cliente de OBS Studio vía obs-websocket v5 (``obsws-python``).

Responsabilidades: conectar, lanzar OBS si no está abierto, preparar la escena
de captura de CS2, fijar carpeta/formato/resolución de grabación y
empezar/parar grabaciones devolviendo la ruta del fichero resultante.
"""

from __future__ import annotations

import base64
import logging
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from clutchreel.services.config import ObsSettings
from clutchreel.utils.paths import obs_exe, obs_websocket_config
from clutchreel.utils.winutil import is_process_running

log = logging.getLogger(__name__)

CS2_WINDOW = "Counter-Strike 2:SDL_app:cs2.exe"
# Formatos de OBS que FFmpeg corta sin problema; con cualquiera de ellos no se toca la configuración del usuario.
GOOD_FORMATS = {"mkv", "mp4", "hybrid_mp4", "fragmented_mp4", "mov", "fragmented_mov"}


def real_suffix(path: Path) -> str | None:
    """Extensión que corresponde al contenido real del fichero (``.mp4``/``.mkv``), o ``None`` si no se reconoce."""
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError:
        return None
    if head.startswith(b"\x1aE\xdf\xa3"):
        return ".mkv"
    if head[4:8] == b"ftyp":
        return ".mp4"
    return None


def fix_extension(path: Path, attempts: int = 20) -> Path:
    """Renombra la grabación si su extensión no coincide con el contenedor real (OBS puede mezclarlos)."""
    suffix = real_suffix(path)
    if suffix is None or suffix == path.suffix.lower():
        return path
    target = path.with_suffix(suffix)
    for _ in range(attempts):
        try:
            if target.exists():
                target.unlink()
            path.rename(target)
            log.info("Grabación renombrada a su formato real: %s", target.name)
            return target
        except PermissionError:
            time.sleep(0.5)  # OBS aún está cerrando el fichero
        except OSError as exc:
            log.warning("No se pudo renombrar %s: %s", path.name, exc)
            return path
    return path


class ObsError(Exception):
    """Error de OBS con mensaje entendible."""


@dataclass
class ObsStatus:
    connected: bool
    version: str = ""
    recording: bool = False
    message: str = ""


class ObsClient:
    def __init__(self, settings: ObsSettings, obs_path: str = "") -> None:
        self.settings = settings
        self.obs_path = obs_path
        self._client: Any = None

    # ------------------------------------------------------------ connect ---

    @property
    def connected(self) -> bool:
        return self._client is not None

    def connect(self, timeout: float = 4.0) -> None:
        try:
            import obsws_python as obs
        except ImportError as exc:  # pragma: no cover
            raise ObsError("Falta la librería obsws-python. Ejecuta Iniciar.bat.") from exc
        try:
            self._client = obs.ReqClient(
                host=self.settings.host, port=int(self.settings.port), password=self.settings.password or "", timeout=timeout
            )
            ver = self._client.get_version()
            log.info("Conectado a OBS %s (obs-websocket %s)", ver.obs_version, ver.obs_web_socket_version)
        except Exception as exc:
            self._client = None
            text = str(exc)
            if "authentication" in text.lower() or "auth" in text.lower():
                raise ObsError("OBS rechazó la contraseña del WebSocket. Revísala en Ajustes → OBS.") from exc
            if is_process_running("obs64.exe"):
                raise ObsError(
                    "OBS está abierto pero el servidor WebSocket no responde.\n"
                    "En OBS: Herramientas → Ajustes del servidor WebSocket → activa el servidor "
                    f"en el puerto {self.settings.port} (o deja que ClutchReel reinicie OBS)."
                ) from exc
            raise ObsError("OBS no está abierto o no responde en el puerto configurado.") from exc

    def disconnect(self) -> None:
        if self._client is not None:
            try:
                self._client.disconnect()
            except Exception:  # noqa: BLE001
                pass
        self._client = None

    def status(self) -> ObsStatus:
        try:
            if not self._client:
                self.connect(timeout=2.0)
            assert self._client is not None
            ver = self._client.get_version()
            rec = self._client.get_record_status()
            return ObsStatus(True, str(ver.obs_version), bool(rec.output_active))
        except ObsError as exc:
            return ObsStatus(False, message=str(exc))
        except Exception as exc:  # noqa: BLE001
            self._client = None
            return ObsStatus(False, message=str(exc))

    # ------------------------------------------------------------- launch ---

    def launch_obs(self, wait_seconds: float = 40.0) -> None:
        """Abre OBS con el servidor WebSocket forzado por línea de comandos y espera a conectar."""
        exe = Path(self.obs_path) if self.obs_path else obs_exe()
        if not exe or not exe.exists():
            raise ObsError("No se encontró OBS Studio. Instálalo desde obsproject.com o indica la ruta en Ajustes.")
        # La contraseña NO se pasa por línea de comandos: quedaría visible en la lista de procesos.
        # OBS la lee de su propia configuración (plugin_config/obs-websocket/config.json).
        args = [
            str(exe),
            "--websocket_port",
            str(self.settings.port),
            "--disable-shutdown-check",
            "--disable-updater",
            "--minimize-to-tray",
        ]
        log.info("Lanzando OBS: %s", exe)
        try:
            subprocess.Popen(args, cwd=str(exe.parent))
        except OSError as exc:
            raise ObsError(f"No se pudo abrir OBS: {exc}") from exc
        deadline = time.time() + wait_seconds
        last_error = ""
        while time.time() < deadline:
            time.sleep(1.5)
            try:
                self.connect(timeout=2.0)
                return
            except ObsError as exc:
                last_error = str(exc)
        raise ObsError(f"OBS se abrió pero no se pudo conectar al WebSocket.\n{last_error}")

    def ensure_connected(self, allow_launch: bool = True) -> None:
        if self.connected:
            try:
                assert self._client is not None
                self._client.get_version()
                return
            except Exception:  # noqa: BLE001
                self._client = None
        try:
            self.connect()
            return
        except ObsError:
            if not allow_launch or is_process_running("obs64.exe"):
                raise
        self.launch_obs()

    # ------------------------------------------------------------- scene ----

    def ensure_scene(self) -> str:
        """Crea/verifica la escena y la fuente de captura de CS2. Devuelve el modo usado."""
        assert self._client is not None, "OBS no conectado"
        c = self._client
        scene = self.settings.scene_name
        source = self.settings.source_name
        scenes = {s["sceneName"] for s in c.get_scene_list().scenes}
        if scene not in scenes:
            c.create_scene(scene)
            log.info("Escena OBS creada: %s", scene)
        kinds = set(c.get_input_kind_list(False).input_kinds)
        inputs = {i["inputName"]: i["inputKind"] for i in c.get_input_list().inputs}
        mode = self.settings.capture_mode
        kind, settings = self._capture_settings(mode, kinds)
        if source in inputs and inputs[source] != kind:
            c.remove_input(source)
            inputs.pop(source, None)
            self._wait_input_gone(source)
        if source not in inputs:
            c.create_input(scene, source, kind, settings, True)
            log.info("Fuente OBS creada: %s (%s)", source, kind)
        else:
            c.set_input_settings(source, settings, True)
            items = c.get_scene_item_list(scene).scene_items
            if not any(i["sourceName"] == source for i in items):
                c.create_scene_item(scene, source, True)
        # Deja la fuente a pantalla completa (bounds = lienzo).
        try:
            items = c.get_scene_item_list(scene).scene_items
            for item in items:
                if item["sourceName"] == source:
                    vs = c.get_video_settings()
                    c.set_scene_item_transform(
                        scene,
                        item["sceneItemId"],
                        {"boundsType": "OBS_BOUNDS_SCALE_INNER", "boundsWidth": vs.base_width, "boundsHeight": vs.base_height, "positionX": 0, "positionY": 0},
                    )
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo ajustar la transformación: %s", exc)
        c.set_current_program_scene(scene)
        return mode

    def _wait_input_gone(self, name: str, timeout: float = 5.0) -> None:
        """OBS libera el nombre de una fuente borrada de forma asíncrona; sin esperar, CreateInput da error 601."""
        assert self._client is not None
        deadline = time.time() + timeout
        while time.time() < deadline:
            if name not in {i["inputName"] for i in self._client.get_input_list().inputs}:
                break
            time.sleep(0.1)
        time.sleep(0.3)

    @staticmethod
    def _capture_settings(mode: str, kinds: set[str]) -> tuple[str, dict[str, object]]:
        if mode == "game" and "game_capture" in kinds:
            return "game_capture", {"capture_mode": "window", "window": CS2_WINDOW, "capture_cursor": False, "anti_cheat_hook": True, "priority": 2}
        if mode in ("game", "window") and "window_capture" in kinds:
            return "window_capture", {"window": CS2_WINDOW, "method": 2, "cursor": False, "capture_audio": False}
        if "monitor_capture" in kinds:
            return "monitor_capture", {"capture_cursor": False}
        raise ObsError("OBS no dispone de fuentes de captura (game/window/monitor).")

    def switch_capture_mode(self, mode: str) -> None:
        previous = self.settings.capture_mode
        self.settings.capture_mode = mode
        try:
            self.ensure_scene()
        except Exception:
            self.settings.capture_mode = previous  # no dejar en la config un modo que no se pudo aplicar
            raise

    # ----------------------------------------------------------- settings ---

    def apply_recording_settings(self, output_dir: Path) -> None:
        assert self._client is not None
        c = self._client
        output_dir.mkdir(parents=True, exist_ok=True)
        try:
            c.set_record_directory(str(output_dir))
        except Exception as exc:  # noqa: BLE001
            log.debug("set_record_directory no soportado (%s); se usa el perfil", exc)
        for category, name in (("SimpleOutput", "FilePath"), ("AdvOut", "RecFilePath")):
            try:
                c.set_profile_parameter(category, name, str(output_dir))
            except Exception as exc:  # noqa: BLE001
                log.debug("set_profile_parameter %s/%s: %s", category, name, exc)
        # Formato: solo se cambia si el del usuario no sirve para cortar con FFmpeg. Cambiarlo con OBS
        # abierto hace que OBS use la extensión nueva pero siga muxeando con el formato anterior
        # (verificado con OBS 33: ficheros .mkv que en realidad eran MP4), así que se toca lo mínimo
        # y además la extensión real se corrige al terminar cada grabación (:func:`real_suffix`).
        fmt = self.settings.recording_format or "mkv"
        for category in ("SimpleOutput", "AdvOut"):
            try:
                current = str(c.get_profile_parameter(category, "RecFormat2").parameter_value or "")
            except Exception:  # noqa: BLE001
                current = ""
            if current in GOOD_FORMATS:
                continue
            try:
                c.set_profile_parameter(category, "RecFormat2", fmt)
                log.info("Formato de grabación de OBS (%s) cambiado de «%s» a «%s»", category, current or "?", fmt)
            except Exception as exc:  # noqa: BLE001
                log.debug("RecFormat2 %s: %s", category, exc)
        if self.settings.manage_video_settings:
            try:
                rec = c.get_record_status()
                if not rec.output_active:
                    c.set_video_settings(int(self.settings.fps), 1, int(self.settings.width), int(self.settings.height), int(self.settings.width), int(self.settings.height))
            except Exception as exc:  # noqa: BLE001
                log.warning("No se pudieron fijar resolución/FPS en OBS: %s", exc)

    # ------------------------------------------------------------ record ----

    def is_recording(self) -> bool:
        assert self._client is not None
        return bool(self._client.get_record_status().output_active)

    def start_record(self) -> None:
        assert self._client is not None
        if self.is_recording():
            self._client.stop_record()
            time.sleep(1.0)
        self._client.start_record()
        deadline = time.time() + 8.0
        while time.time() < deadline:
            if self.is_recording():
                return
            time.sleep(0.1)
        raise ObsError("OBS no empezó a grabar. Revisa el codificador y la carpeta de salida en OBS.")

    def stop_record(self) -> Path | None:
        assert self._client is not None
        try:
            resp = self._client.stop_record()
        except Exception as exc:
            raise ObsError(f"OBS no pudo parar la grabación: {exc}") from exc
        path_text = getattr(resp, "output_path", "") or ""
        deadline = time.time() + 10.0
        while time.time() < deadline and self.is_recording():
            time.sleep(0.2)
        if not path_text:
            return None
        path = Path(path_text)
        deadline = time.time() + 15.0
        while time.time() < deadline and not path.exists():
            time.sleep(0.3)
        return fix_extension(path)

    def source_brightness(self) -> float | None:
        """Brillo medio (0-255) de la fuente de captura; ``None`` si no se pudo capturar."""
        assert self._client is not None
        try:
            resp = self._client.get_source_screenshot(self.settings.source_name, "png", 32, 32, 50)
            data = resp.image_data
            if "," in data:
                data = data.split(",", 1)[1]
            raw = base64.b64decode(data)
        except Exception as exc:  # noqa: BLE001
            log.debug("Captura de pantalla de la fuente no disponible: %s", exc)
            return None
        try:
            from PySide6.QtGui import QImage

            img = QImage.fromData(raw)
            if img.isNull():
                return None
            img = img.convertToFormat(QImage.Format.Format_Grayscale8)
            total = 0
            for y in range(img.height()):
                for x in range(img.width()):
                    total += img.pixelColor(x, y).red()
            return total / float(img.width() * img.height())
        except Exception:  # noqa: BLE001
            return None


def detect_obs_settings(settings: ObsSettings) -> ObsSettings:
    """Rellena puerto/contraseña desde la configuración del plugin si están vacíos."""
    cfg = obs_websocket_config()
    if cfg:
        if not settings.password and isinstance(cfg.get("server_password"), str) and cfg.get("auth_required", True):
            settings.password = str(cfg["server_password"])
        port = cfg.get("server_port")
        if isinstance(port, int) and port > 0 and settings.port == 4455:
            settings.port = port
    return settings
