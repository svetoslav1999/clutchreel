"""Activa y configura el servidor obs-websocket de OBS Studio (v5, OBS 28+).

OBS reescribe ``config.json`` del plugin al cerrarse, así que solo se edita con
OBS cerrado. El flujo completo (:func:`configure_obs`) cierra OBS de forma
limpia (previa confirmación), edita el fichero conservando el resto de campos,
guarda puerto/contraseña en ClutchReel, reabre OBS y espera al puerto.
"""

from __future__ import annotations

import json
import logging
import os
import secrets
import socket
import string
import subprocess
import tempfile
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any

from clutchreel.services.config import ConfigStore
from clutchreel.utils.paths import obs_exe
from clutchreel.utils.winutil import find_process, is_process_running

log = logging.getLogger(__name__)

OBS_PROCESS = "obs64.exe"
PASSWORD_LENGTH = 20
OBS_AUTOCONFIG_ACTION = "obs_autoconfig"

# Estructura que escribe obs-websocket v5 la primera vez que se carga.
DEFAULT_WEBSOCKET_CONFIG: dict[str, Any] = {
    "alerts_enabled": False,
    "auth_required": True,
    "first_load": False,
    "server_enabled": False,
    "server_password": "",
    "server_port": 4455,
}


class ObsSetupError(Exception):
    """Fallo al configurar OBS, con un mensaje entendible."""


@dataclass
class WebsocketState:
    """Estado del config.json del plugin."""

    exists: bool
    corrupt: bool = False
    enabled: bool = False
    port: int = 4455
    auth_required: bool = True


@dataclass
class SetupResult:
    port: int
    password: str  # solo para mostrarla una vez; no se registra en logs
    backup: Path | None
    port_changed: bool
    reopened: bool


# ---------------------------------------------------------------- helpers ---


def websocket_config_path() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    return Path(base) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"


def generate_password(length: int = PASSWORD_LENGTH) -> str:
    alphabet = string.ascii_letters + string.digits
    return "".join(secrets.choice(alphabet) for _ in range(length))


def port_is_free(port: int, host: str = "127.0.0.1") -> bool:
    """``True`` si nadie escucha ya en ``host:port``."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.5)
        return sock.connect_ex((host, port)) != 0


def pick_port(preferred: int = 4455) -> int:
    """Devuelve ``preferred`` si está libre; si no, el siguiente puerto libre."""
    for port in range(preferred, preferred + 50):
        if port_is_free(port):
            return port
    raise ObsSetupError(f"No hay ningún puerto libre entre {preferred} y {preferred + 49}.")


def wait_for_port(port: int, host: str = "127.0.0.1", timeout: float = 60.0) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not port_is_free(port, host):
            return True
        time.sleep(1.0)
    return False


# ------------------------------------------------------------ config.json ---


def read_state(path: Path | None = None) -> WebsocketState:
    path = path or websocket_config_path()
    if not path.exists():
        return WebsocketState(exists=False)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return WebsocketState(exists=True, corrupt=True)
    if not isinstance(data, dict):
        return WebsocketState(exists=True, corrupt=True)
    port = data.get("server_port")
    return WebsocketState(
        exists=True,
        enabled=bool(data.get("server_enabled", False)),
        port=port if isinstance(port, int) and port > 0 else 4455,
        auth_required=bool(data.get("auth_required", True)),
    )


def _backup(path: Path) -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    dest = path.with_name(f"{path.name}.{stamp}.bak")
    dest.write_bytes(path.read_bytes())
    return dest


def apply_websocket_config(path: Path, port: int, password: str) -> Path | None:
    """Activa el servidor en ``path`` conservando el resto de campos.

    Devuelve la ruta de la copia de seguridad (``None`` si el archivo no existía).
    Un archivo corrupto se respalda y se recrea con la estructura por defecto.
    """
    data: dict[str, Any] = dict(DEFAULT_WEBSOCKET_CONFIG)
    backup: Path | None = None
    if path.exists():
        backup = _backup(path)
        try:
            loaded = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(loaded, dict):
                data = loaded
            else:
                log.warning("config.json de obs-websocket no es un objeto; se recrea")
        except (OSError, ValueError):
            log.warning("config.json de obs-websocket ilegible; se recrea (copia en %s)", backup)
    data.update(
        {
            "server_enabled": True,
            "server_port": port,
            "auth_required": True,
            "server_password": password,
            "alerts_enabled": False,
            "first_load": False,
        }
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix="config_", suffix=".json", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=4)
        os.replace(tmp_name, path)
    except OSError:
        try:
            os.unlink(tmp_name)
        except OSError:
            pass
        raise
    return backup


# ---------------------------------------------------------------- OBS proc --


def close_obs(timeout: float = 30.0) -> bool:
    """Pide a OBS que se cierre (WM_CLOSE, sin ``/F``). ``True`` si terminó."""
    proc = find_process(OBS_PROCESS)
    if proc is None:
        return True
    subprocess.run(["taskkill", "/PID", str(proc.pid)], check=False, capture_output=True)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not is_process_running(OBS_PROCESS):
            return True
        time.sleep(0.5)
    return False


def launch_obs(exe: Path) -> None:
    try:
        subprocess.Popen([str(exe)], cwd=str(exe.parent))
    except OSError as exc:
        raise ObsSetupError(f"No se pudo abrir OBS: {exc}") from exc


# ------------------------------------------------------------------ flow ----


def configure_obs(
    store: ConfigStore,
    confirm_close: Callable[[], bool],
    obs_path: str = "",
    ws_config: Path | None = None,
    reopen: bool = True,
) -> SetupResult:
    """Activa obs-websocket, guarda puerto/contraseña en ClutchReel y reabre OBS.

    ``confirm_close`` se llama solo si OBS está abierto; si devuelve ``False`` no
    se toca nada.
    """
    ws_config = ws_config or websocket_config_path()
    exe = Path(obs_path) if obs_path else obs_exe()
    was_running = is_process_running(OBS_PROCESS)
    if was_running:
        if not confirm_close():
            raise ObsSetupError("Cancelado: OBS sigue abierto y no se ha modificado nada.")
        if not close_obs():
            raise ObsSetupError("OBS no respondió al cierre limpio. Ciérralo a mano (no se fuerza) y reintenta.")
    state = read_state(ws_config)
    preferred = state.port if state.exists and not state.corrupt else 4455
    port = pick_port(preferred)
    password = generate_password()
    backup = apply_websocket_config(ws_config, port, password)
    store.config.obs.port = port
    store.config.obs.password = password
    store.save()
    log.info("obs-websocket activado en el puerto %d (copia: %s)", port, backup)
    reopened = False
    if reopen and (was_running or store.config.obs.auto_launch):
        if exe is None or not exe.exists():
            raise ObsSetupError("Configuración guardada, pero no se encontró OBS para reabrirlo.")
        launch_obs(exe)
        if not wait_for_port(port):
            raise ObsSetupError(f"OBS se abrió pero el puerto {port} no escucha. Revisa el firewall de Windows.")
        reopened = True
    return SetupResult(port, password, backup, port != preferred, reopened)
