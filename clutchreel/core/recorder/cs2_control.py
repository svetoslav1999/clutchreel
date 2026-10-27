"""Control de Counter-Strike 2 para reproducir demos.

Canales de envío de comandos, en orden de preferencia:

1. **Puerto de consola** (``-netconport N``): socket TCP local. Con CS2 1.41.9
   (octubre 2026) el puerto abre sin ``-tools`` (con ``-tools`` el juego se
   cerraba al saltar en la demo). Es el único canal que permite **leer** la
   consola y, por tanto, comprobar a quién sigue la cámara.
2. **Teclado**: abre la consola del juego y teclea los comandos (SendInput).
   Si ``cfg_fallback`` está activo, los comandos se escriben en
   ``game/csgo/cfg/clutchreel.cfg`` y solo se teclea ``exec clutchreel``.
3. **Semiautomático**: la app muestra los comandos y el usuario los teclea.

Solo se usan comandos de consola normales del visor de demos (``playdemo``,
``demo_gototick``, ``demo_pause``, ``spec_player``, ``getpos``…). Nunca se
inyecta código ni se toca la memoria del juego. Las variables de consola que se
cambian para grabar limpio se guardan antes y se restauran al terminar.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import threading
import time
from collections.abc import Callable
from pathlib import Path

from clutchreel.core.recorder.spectate import (
    TRUEVIEW_RE as _TRUEVIEW_ANY_RE,
)
from clutchreel.core.recorder.spectate import (
    CameraMatch,
    DemoTimeline,
    SpectateError,
    camera_on_target,
    spec_name_command,
    spec_player_command,
)
from clutchreel.services.config import Cs2Settings
from clutchreel.utils.paths import appdata_dir, cache_dir, cs2_csgo_dir, cs2_dir, steam_exe
from clutchreel.utils.winutil import find_process, is_process_running, kill_process

log = logging.getLogger(__name__)

CS2_EXE = "cs2.exe"
CFG_NAME = "clutchreel"
CVAR_BACKUP_FILE = "cs2_cvars_backup.json"

AskFn = Callable[[str], bool]

# Variables para una captura limpia: (valor durante la grabación, ¿se guarda en la config del usuario?).
# Las "archive" solo se cambian si se puede leer su valor original para restaurarlo después.
CAPTURE_CVARS: dict[str, tuple[str, bool]] = {
    "r_show_build_info": ("0", True),  # texto de versión abajo a la izquierda
    "cl_hud_telemetry_frametime_show": ("0", True),  # FPS arriba a la derecha
    "cl_hud_telemetry_ping_show": ("0", True),
    "cl_hud_telemetry_net_misdelivery_show": ("0", True),
    "cl_trueview_show_status": ("0", False),  # «TrueView: Activado»
    "engine_no_focus_sleep": ("0", True),  # sin foco CS2 duerme 20 ms por fotograma → vídeo a tirones
    "snd_mute_losefocus": ("0", True),  # sin foco CS2 se silencia → clips sin audio
}

# Valor por defecto de CS2 (1.41.9) de las variables no guardadas que se cambian para grabar. Si no se pudo
# leer el valor original (CS2 recién abierto no contesta a tiempo), se restaura este al terminar; sin él,
# demo_ui_mode se quedaba a 0 y la barra del reproductor no volvía hasta reiniciar el juego.
CVAR_DEFAULTS: dict[str, str] = {"demo_ui_mode": "1"}

# Solo la *entrada* en partida: «INGAME -> MAINMENU» sale al descargar la demo anterior y no vale.
_LOADED_RE = re.compile(r"-> CSGO_GAME_UI_STATE_INGAME|Host activate: Playing Demo|OnSwitchLoopModeFinished\( game : success \)")
# Al descargar la demo anterior (playdemo con otra ya abierta).
_UNLOADING_RE = re.compile(r"NETWORK_DISCONNECT_LOOPDEACTIVATE|CSGO_GAME_UI_STATE_INGAME -> CSGO_GAME_UI_STATE_MAINMENU")
_INCOMPATIBLE_RE = re.compile(r"NETWORK_DISCONNECT_REPLAY_INCOMPATIBLE|Network version (\d+) is incompatible")
_OPEN_FAIL_RE = re.compile(r"couldn't open file|doesn't exist in pathid|invalid pBuffer")
_SEEK_DONE_RE = re.compile(r"Demo Skipping finished at tick (\d+)")
# Al terminar ``demo_step_tick N`` (o ``demo_pause``) CS2 imprime la pausa; la segunda línea solo tras step_tick.
_PAUSED_RE = re.compile(r"CGameRules - paused on tick (\d+)")
_DEMO_PAUSED_RE = re.compile(r"Demo paused at engine time (\d+), demo tick (\d+)")
# Tras cargar, CS2 hace por su cuenta un salto al principio de la demo (~3 s después;
# verificado en CS2 de octubre de 2026). Un demo_gototick enviado antes queda anulado.
INITIAL_SKIP_WAIT = 8.0
# Diferencia máxima (ticks) entre el tick pedido y el que confirma CS2.
SEEK_TOLERANCE = 64
# El «;setang» final garantiza que la coordenada Z llegó completa.
_GETPOS_RE = re.compile(r"setpos\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s*;")


class Cs2Error(Exception):
    pass


def split_commands(text: str) -> list[str]:
    return [c.strip() for c in (text or "").split(";") if c.strip()]


def cvar_assignment(command: str) -> tuple[str, str] | None:
    """``("nombre", "valor")`` si el comando es una asignación simple de variable."""
    parts = command.split()
    if len(parts) == 2 and re.fullmatch(r"[a-z_][a-z0-9_]*", parts[0]) and not parts[0].startswith(("spec_mode", "demo_")):
        return parts[0], parts[1]
    return None


class NetconChannel:
    """Socket al puerto de consola de CS2."""

    def __init__(self, port: int, host: str = "127.0.0.1") -> None:
        self.port = port
        self.host = host
        self._sock: socket.socket | None = None
        self.echo_works: bool | None = None
        # Se llama con todo el texto que llega de la consola (para seguir los cambios de cámara).
        self.on_text: Callable[[str], None] | None = None

    def connect(self, timeout: float = 2.0) -> bool:
        self.close()
        try:
            sock = socket.create_connection((self.host, self.port), timeout=timeout)
            sock.settimeout(0.5)
            self._sock = sock
            return True
        except OSError:
            self._sock = None
            return False

    @property
    def connected(self) -> bool:
        return self._sock is not None

    def close(self) -> None:
        if self._sock:
            try:
                self._sock.close()
            except OSError:
                pass
        self._sock = None

    def send(self, command: str) -> None:
        if not self._sock:
            raise Cs2Error("El puerto de consola de CS2 no está conectado.")
        try:
            self._sock.sendall((command.strip() + "\n").encode("utf-8", errors="replace"))
        except OSError as exc:
            self.close()
            raise Cs2Error(f"Se perdió la conexión con la consola de CS2: {exc}") from exc

    def read(self, timeout: float = 0.5, max_time: float | None = None) -> str:
        """Lee lo que haya llegado. Termina tras ``timeout`` sin datos o, como mucho, a los ``max_time`` s.

        CS2 escribe sin parar en la consola mientras la demo está en pausa
        (avisos de TrueView), así que sin el tope ``max_time`` la lectura no acabaría nunca.
        """
        if not self._sock:
            return ""
        chunks: list[bytes] = []
        deadline = time.monotonic() + (max_time if max_time is not None else max(timeout, 0.05) * 4)
        self._sock.settimeout(timeout)
        try:
            while time.monotonic() < deadline:
                data = self._sock.recv(65536)
                if not data:
                    self.close()
                    break
                chunks.append(data)
                # Da una pequeña oportunidad a que llegue el resto.
                self._sock.settimeout(min(timeout, 0.15))
        except (TimeoutError, OSError):
            pass
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if text and self.on_text is not None:
            try:
                self.on_text(text)
            except Exception as exc:  # noqa: BLE001
                log.debug("on_text falló: %s", exc)
        return text

    def probe_echo(self) -> bool:
        """Comprueba si la consola devuelve salida por el socket (``echo``)."""
        marker = f"CLUTCHREEL_PING_{int(time.time() * 1000)}"
        try:
            self.read(0.05, 0.3)
            self.send(f"echo {marker}")
            out = ""
            deadline = time.monotonic() + 2.0
            while time.monotonic() < deadline and marker not in out:
                out += self.read(0.3, 0.6)
            self.echo_works = marker in out
        except Cs2Error:
            self.echo_works = False
        return bool(self.echo_works)


class Cs2Controller:
    def __init__(self, settings: Cs2Settings, cs2_path: str = "") -> None:
        self.settings = settings
        self.cs2_path = cs2_path
        self.netcon = NetconChannel(settings.netcon_port)
        self.netcon.on_text = self._on_console_text
        self.channel: str = "none"  # netcon | keyboard | manual
        self.ask_user: AskFn | None = None
        self.loaded_demo: str = ""
        self._last_pos: tuple[float, float, float] | None = None
        self.backup_path = appdata_dir() / CVAR_BACKUP_FILE
        # Cambios de cámara leídos de la consola: (momento perf_counter, slot, nombre).
        self.camera_changes: list[tuple[float, int, str]] = []
        # Pausas anunciadas por CS2: (momento perf_counter, tick de motor, tick de demo o None).
        self.pauses: list[tuple[float, int, int | None]] = []
        self._tail = ""  # cola del último texto leído, por si una línea llega partida en dos lecturas
        # Lo fija el grabador: las esperas largas (arranque, carga, saltos) terminan en cuanto se cancela.
        self.cancel: threading.Event | None = None

    def _check_cancel(self) -> None:
        if self.cancel is not None and self.cancel.is_set():
            raise Cs2Error("Grabación cancelada.")

    # ------------------------------------------------------------- camera ---

    def _on_console_text(self, text: str) -> None:
        """Se llama con cada trozo de texto que llega de la consola (desde cualquier lectura)."""
        now = time.perf_counter()
        combined = self._tail + text
        start = len(self._tail)
        for m in _TRUEVIEW_ANY_RE.finditer(combined):
            if m.end() > start:
                self.camera_changes.append((now, int(m.group(1)), m.group(2)))
        engine_ticks_with_demo = {int(m.group(1)): int(m.group(2)) for m in _DEMO_PAUSED_RE.finditer(combined) if m.end() > start}
        for m in _PAUSED_RE.finditer(combined):
            if m.end() > start:
                engine = int(m.group(1))
                self.pauses.append((now, engine, engine_ticks_with_demo.get(engine)))
        for m in _DEMO_PAUSED_RE.finditer(combined):
            if m.end() > start and not any(p[1] == int(m.group(1)) and p[2] is not None for p in self.pauses[-3:]):
                self.pauses.append((now, int(m.group(1)), int(m.group(2))))
        self._tail = combined[-400:]
        if len(self.camera_changes) > 2000:
            del self.camera_changes[:1000]
        if len(self.pauses) > 500:
            del self.pauses[:250]

    def pause_after(self, t0: float) -> tuple[float, int | None] | None:
        """Primera pausa anunciada por CS2 desde ``t0``: (instante, tick de demo si se imprimió)."""
        for t, _engine, demo_tick in self.pauses:
            if t >= t0:
                return t, demo_tick
        return None

    @property
    def camera_slot_name(self) -> tuple[int, str] | None:
        """Último jugador anunciado por CS2 como objetivo de la cámara en primera persona."""
        if not self.camera_changes:
            return None
        _t, slot, name = self.camera_changes[-1]
        return slot, name

    def camera_changes_since(self, t0: float) -> list[tuple[float, int, str]]:
        return [c for c in self.camera_changes if c[0] >= t0]

    # ------------------------------------------------------------- launch ---

    def game_dir(self) -> Path | None:
        if self.cs2_path:
            p = Path(self.cs2_path)
            if (p / "game" / "bin" / "win64" / CS2_EXE).exists():
                return p
        return cs2_dir()

    def launch_args(self) -> list[str]:
        args = self.settings.launch_options.split()
        if "-insecure" not in args:
            args.insert(0, "-insecure")
        if self.settings.use_netconport:
            args += ["-netconport", str(self.settings.netcon_port)]
            if self.settings.netcon_tools_workaround and "-tools" not in args:
                args.append("-tools")
        if self.settings.window_width and self.settings.window_height:
            args += ["-sw", "-w", str(self.settings.window_width), "-h", str(self.settings.window_height)]
        return args

    def is_running(self) -> bool:
        return is_process_running(CS2_EXE)

    def running_args(self) -> list[str] | None:
        """Opciones con las que se lanzó el ``cs2.exe`` en marcha (``None`` si no se pueden leer)."""
        proc = find_process(CS2_EXE)
        if proc is None:
            return None
        try:
            return [str(a) for a in proc.cmdline()]
        except Exception:  # noqa: BLE001
            return None

    def missing_launch_options(self) -> list[str]:
        """Opciones necesarias que le faltan al CS2 ya abierto (vacío si todo bien o no se sabe)."""
        args = self.running_args()
        if args is None:
            return []
        needed = ["-insecure"]
        if self.settings.use_netconport:
            needed.append("-netconport")
        return [opt for opt in needed if opt not in args]

    def restart_game(self, timeout: float = 20.0) -> None:
        """Cierra CS2 y lo reabre con las opciones de ClutchReel. Solo llamar con permiso del usuario."""
        self.netcon.close()
        self.channel = "none"
        proc = find_process(CS2_EXE)
        if proc is not None:
            subprocess.run(["taskkill", "/PID", str(proc.pid)], check=False, capture_output=True)  # cierre limpio (WM_CLOSE)
            deadline = time.time() + timeout
            while time.time() < deadline and self.is_running():
                time.sleep(0.5)
            if self.is_running():
                kill_process(CS2_EXE)  # el usuario ya aceptó cerrarlo
                time.sleep(2.0)
        self.launch()

    def launch(self, wait_seconds: float = 90.0) -> None:
        """Lanza CS2 a través de Steam con las opciones necesarias y espera al proceso."""
        if self.is_running():
            log.info("CS2 ya está en ejecución")
            return
        steam = steam_exe()
        if not steam:
            raise Cs2Error("No se encontró Steam. Instálalo o abre CS2 manualmente.")
        if not self.game_dir():
            raise Cs2Error("No se encontró Counter-Strike 2 instalado en ninguna biblioteca de Steam.")
        args = [str(steam), "-applaunch", "730", *self.launch_args()]
        log.info("Lanzando CS2: %s", subprocess.list2cmdline(args))
        try:
            subprocess.Popen(args)
        except OSError as exc:
            raise Cs2Error(f"No se pudo lanzar CS2 mediante Steam: {exc}") from exc
        deadline = time.time() + wait_seconds
        while time.time() < deadline:
            self._check_cancel()
            if self.is_running():
                log.info("Proceso cs2.exe detectado")
                return
            time.sleep(1.0)
        raise Cs2Error("CS2 no arrancó en el tiempo esperado. Comprueba que Steam está abierto y con sesión iniciada.")

    def close_game(self) -> None:
        try:
            if self.channel == "netcon" and self.netcon.connected:
                self.netcon.send("quit")
                time.sleep(3.0)
        except Cs2Error:
            pass
        if self.is_running():
            kill_process(CS2_EXE)
        self.netcon.close()
        self.channel = "none"

    # ------------------------------------------------------------ channel ---

    def connect_channel(self, wait_seconds: float = 60.0) -> str:
        """Elige el canal de comandos disponible. Devuelve ``netcon``/``keyboard``/``manual``."""
        if self.settings.use_netconport and "-netconport" in self.missing_launch_options():
            log.warning("CS2 está abierto sin -netconport: no hay puerto de consola que esperar")
        elif self.settings.use_netconport:
            deadline = time.time() + wait_seconds
            while time.time() < deadline:
                self._check_cancel()
                if not self.is_running():
                    raise Cs2Error("CS2 se cerró antes de poder conectar con su consola.")
                if self.netcon.connect():
                    # Recién abierto, CS2 acepta la conexión antes de procesar comandos: se insiste un poco.
                    # Recién lanzado, CS2 tarda en llegar al menú (hasta ~1 min en frío).
                    echo_deadline = time.time() + max(45.0, deadline - time.time())
                    while not self.netcon.probe_echo() and time.time() < echo_deadline:
                        self._check_cancel()
                        time.sleep(1.0)
                    self.channel = "netcon"
                    log.info("Consola de CS2 conectada por puerto %d (eco=%s)", self.settings.netcon_port, self.netcon.echo_works)
                    return self.channel
                time.sleep(2.0)
            log.warning("El puerto de consola %d no respondió", self.settings.netcon_port)
        if self.settings.keyboard_fallback:
            self.channel = "keyboard"
            log.info("Usando teclado simulado para enviar comandos a CS2")
            return self.channel
        self.channel = "manual"
        return self.channel

    @property
    def can_read_console(self) -> bool:
        """``True`` si se puede leer la salida de la consola (necesario para verificar la cámara)."""
        return self.channel == "netcon" and self.netcon.connected and bool(self.netcon.echo_works)

    def _ensure_netcon(self) -> None:
        """Reconecta el puerto de consola si CS2 lo cerró (p. ej. durante una carga)."""
        if self.channel != "netcon" or self.netcon.connected:
            return
        deadline = time.time() + 30.0
        while time.time() < deadline:
            self._check_cancel()
            if not self.is_running():
                raise Cs2Error("CS2 se cerró.")
            if self.netcon.connect():
                self.netcon.probe_echo()
                return
            time.sleep(1.0)
        raise Cs2Error("Se perdió la conexión con la consola de CS2 y no se pudo recuperar.")

    def send(self, commands: str | list[str]) -> None:
        cmds = [commands] if isinstance(commands, str) else list(commands)
        cmds = [c.strip() for c in cmds if c and c.strip()]
        if not cmds:
            return
        if self.channel == "netcon":
            self._ensure_netcon()
            for c in cmds:
                self.netcon.send(c)
            time.sleep(0.05)
            return
        if self.channel == "keyboard":
            self._send_keyboard(cmds)
            return
        if self.channel == "manual":
            if self.ask_user is None:
                raise Cs2Error("No hay canal para enviar comandos a CS2.")
            text = "Escribe en la consola de CS2:\n\n" + "\n".join(cmds)
            if not self.ask_user(text):
                raise Cs2Error("Grabación cancelada por el usuario.")
            return
        raise Cs2Error("No hay canal para enviar comandos a CS2.")

    def query(self, command: str, pattern: re.Pattern[str] | str, timeout: float = 2.0) -> re.Match[str] | None:
        """Envía ``command`` y espera en la salida de la consola una línea que case con ``pattern``."""
        if not self.can_read_console:
            return None
        regex = re.compile(pattern) if isinstance(pattern, str) else pattern
        self.netcon.read(0.02, 0.2)  # descarta lo acumulado
        self.netcon.send(command)
        buf = ""
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            buf += self.netcon.read(0.1, 0.3)
            m = regex.search(buf)
            if m:
                return m
        return None

    def get_cvar(self, name: str, attempts: int = 1) -> str | None:
        for _ in range(max(1, attempts)):
            m = self.query(name, re.compile(rf"(?m)^{re.escape(name)} = (\S*)"), timeout=1.5)
            if m:
                return m.group(1)
        return None

    def camera_position(self) -> tuple[float, float, float] | None:
        m = self.query("getpos", _GETPOS_RE, timeout=1.5)
        return (float(m.group(1)), float(m.group(2)), float(m.group(3))) if m else None

    def _send_keyboard(self, cmds: list[str]) -> None:
        from clutchreel.core.recorder import win_input

        if not win_input.focus_window("Counter-Strike 2", CS2_EXE):
            raise Cs2Error("No se encontró la ventana de CS2 para teclear comandos.")
        lines = cmds
        if self.settings.cfg_fallback:
            cfg = self.write_cfg(cmds)
            if cfg:
                lines = [f"exec {CFG_NAME}"]
        win_input.press_scancode("`")
        time.sleep(0.4)
        for line in lines:
            win_input.type_text(line)
            time.sleep(0.05)
            win_input.press_scancode("enter")
            time.sleep(0.15)
        time.sleep(0.2)
        win_input.press_scancode("`")
        time.sleep(0.2)

    def write_cfg(self, cmds: list[str]) -> Path | None:
        """Escribe los comandos en ``cfg/clutchreel.cfg`` (solo un fichero de configuración)."""
        csgo = cs2_csgo_dir() if not self.cs2_path else Path(self.cs2_path) / "game" / "csgo"
        if not csgo:
            return None
        target = csgo / "cfg" / f"{CFG_NAME}.cfg"
        try:
            target.write_text("\n".join(cmds) + "\n", encoding="utf-8")
            return target
        except OSError as exc:
            log.warning("No se pudo escribir %s: %s", target, exc)
            return None

    def focus_game(self) -> bool:
        """Trae la ventana de CS2 al frente (para que renderice a tope y con sonido)."""
        from clutchreel.core.recorder import win_input

        try:
            return win_input.focus_window("Counter-Strike 2", CS2_EXE)
        except OSError:
            return False

    # ------------------------------------------------------- cvars limpias ---

    def _load_backup(self) -> dict[str, str]:
        try:
            data = json.loads(self.backup_path.read_text(encoding="utf-8"))
            return {str(k): str(v) for k, v in data.items()} if isinstance(data, dict) else {}
        except (OSError, ValueError):
            return {}

    def _save_backup(self, backup: dict[str, str]) -> None:
        try:
            self.backup_path.write_text(json.dumps(backup, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError as exc:
            log.warning("No se pudo guardar la copia de las variables de CS2: %s", exc)

    def _backup_and_set(self, assignments: list[tuple[str, str, bool]]) -> None:
        """Guarda el valor original de cada variable (si se puede leer) y aplica el nuevo."""
        backup = self._load_backup()  # si una sesión anterior no restauró, se conservan sus originales
        cmds: list[str] = []
        for name, value, archive in assignments:
            if self.can_read_console:
                if name not in backup:
                    current = self.get_cvar(name, attempts=3)
                    if current is not None:
                        backup[name] = current
                    elif archive:
                        log.info("No se pudo leer %s; no se cambia (se guarda en la configuración del juego)", name)
                        continue
                    else:
                        # Recién abierto, CS2 tarda en contestar y la lectura caduca. Antes se daba la variable
                        # por inexistente y no se aplicaba (con demo_ui_mode, la barra del reproductor salía en
                        # todos los clips). Las no guardadas vuelven a su valor por defecto al cerrar el juego.
                        default = CVAR_DEFAULTS.get(name)
                        if default is not None:
                            backup[name] = default
                            log.info("No se pudo leer %s; se aplica igualmente y al terminar se restaurará su valor por defecto (%s)", name, default)
                        else:
                            log.info("No se pudo leer %s; se aplica igualmente (no se guarda en la configuración del juego)", name)
            elif archive:
                continue  # sin poder leer el original no se toca la configuración guardada del usuario
            cmds.append(f"{name} {value}")
        if backup:
            self._save_backup(backup)
        self.send(cmds)

    def setup_hud(self) -> None:
        """Interfaz limpia para grabar: variables fijas de captura + comandos de HUD del usuario."""
        assignments = [(name, value, archive) for name, (value, archive) in CAPTURE_CVARS.items()]
        extra: list[str] = []
        for cmd in split_commands(self.settings.hud_commands):
            pair = cvar_assignment(cmd)
            if pair and pair[0] not in CAPTURE_CVARS:
                assignments.append((pair[0], pair[1], False))
            elif not pair:
                extra.append(cmd)
        self._backup_and_set(assignments)
        self.send(extra)

    def restore_cvars(self) -> None:
        """Devuelve a su valor original las variables cambiadas para grabar."""
        backup = self._load_backup()
        if not backup:
            return
        if self.channel not in ("netcon", "keyboard") or not self.is_running():
            return  # se restaurarán en la próxima sesión
        try:
            self.send([f"{k} {v}" for k, v in backup.items()])
        except Cs2Error as exc:
            log.warning("No se pudieron restaurar las variables de CS2: %s", exc)
            return
        try:
            self.backup_path.unlink()
        except OSError:
            pass
        log.info("Variables de CS2 restauradas (%d)", len(backup))

    # ---------------------------------------------------------- demo ctrl ---

    def demo_path_for_game(self, demo: Path) -> str:
        """Ruta que recibe ``playdemo``. Copia a ``replays`` si está activado o si la ruta no se puede escribir en la consola."""
        text = str(demo).replace("\\", "/")
        if self.settings.copy_demo_to_game:
            csgo = cs2_csgo_dir()
            if csgo:
                replays = csgo / "replays"
                try:
                    replays.mkdir(exist_ok=True)
                    target = replays / demo.name
                    if not target.exists() or target.stat().st_size != demo.stat().st_size:
                        shutil.copy2(demo, target)
                    return f"replays/{demo.name}"
                except OSError as exc:
                    log.warning("No se pudo copiar la demo a replays: %s", exc)
        if ";" in text or '"' in text:
            # «;» separa comandos en la consola de CS2: se usa una copia con nombre seguro.
            target = cache_dir() / "demo_actual.dem"
            try:
                if not target.exists() or target.stat().st_size != demo.stat().st_size or target.stat().st_mtime < demo.stat().st_mtime:
                    shutil.copy2(demo, target)
                return str(target).replace("\\", "/")
            except OSError as exc:
                raise Cs2Error(f"La ruta de la demo contiene «;» y no se pudo copiar a una ruta segura: {exc}") from exc
        return text

    def ensure_console_readable(self, timeout: float = 45.0) -> bool:
        """Vuelve a probar el eco de la consola si al conectar aún no respondía (CS2 arrancando)."""
        if self.channel != "netcon" or self.netcon.echo_works:
            return self.can_read_console
        deadline = time.time() + timeout
        while time.time() < deadline:
            self._check_cancel()
            if not self.is_running():
                raise Cs2Error("CS2 se cerró antes de poder leer su consola.")
            self._ensure_netcon()
            if self.netcon.probe_echo():
                log.info("La consola de CS2 ya responde")
                return True
            time.sleep(1.0)
        log.warning("La consola de CS2 no devuelve salida: no se podrá comprobar la cámara")
        return False

    def play_demo(self, demo: Path) -> None:
        self.ensure_console_readable()
        path = self.demo_path_for_game(demo)
        # demo_ui_mode 0 antes de cargar: así no aparece la barra del reproductor en el vídeo
        # (cambiarlo con la demo ya cargada no tiene efecto; verificado en CS2 1.41.9).
        self._backup_and_set([("demo_ui_mode", "0", False)])
        if self.can_read_console:
            self.netcon.read(0.02, 0.3)
        self.send(f'playdemo "{path}"')
        self.loaded_demo = str(demo)
        self.wait_demo_loaded()

    def wait_demo_loaded(self) -> None:
        wait = max(5.0, float(self.settings.demo_load_wait))
        if self.channel == "netcon" and self.netcon.echo_works:
            deadline = time.time() + max(wait, 120.0)
            buf = ""
            while time.time() < deadline:
                self._check_cancel()
                if not self.is_running():
                    raise Cs2Error("CS2 se cerró mientras cargaba la demo.")
                if not self.netcon.connected:
                    self.netcon.connect(timeout=1.0)  # durante la carga el puerto puede cerrarse un momento
                    time.sleep(0.5)
                    continue
                buf = (buf + self.netcon.read(0.3, 1.0))[-200_000:]
                m = _INCOMPATIBLE_RE.search(buf)
                if m:
                    raise Cs2Error(
                        "CS2 no puede reproducir esta demo porque es de una versión anterior del juego"
                        + (f" (versión de red {m.group(1)})" if m.group(1) else "")
                        + ". Valve no mantiene la compatibilidad de las demos antiguas; usa el modo «Ya tengo la grabación»."
                    )
                if _OPEN_FAIL_RE.search(buf):
                    raise Cs2Error("CS2 no pudo abrir el fichero de la demo (¿se movió o borró?).")
                m_loaded = _LOADED_RE.search(buf)
                if m_loaded:
                    log.info("Demo cargada (CS2 en partida)")
                    self._wait_initial_skip(buf[m_loaded.end() :])
                    return
            raise Cs2Error("La demo no terminó de cargar en CS2 en 2 minutos. Revisa el juego (¿una ventana de error?) y vuelve a intentarlo.")
        log.info("Esperando %.0f s a que cargue la demo", wait)
        deadline = time.time() + wait
        while time.time() < deadline:
            self._check_cancel()
            if not self.is_running():
                raise Cs2Error("CS2 se cerró mientras cargaba la demo.")
            time.sleep(0.5)

    def _wait_initial_skip(self, already: str = "") -> None:
        """Espera al salto automático que hace CS2 nada más cargar la demo (o a que pase su plazo)."""
        buf = already
        deadline = time.time() + INITIAL_SKIP_WAIT
        while time.time() < deadline and not _SEEK_DONE_RE.search(buf):
            self._check_cancel()
            if not self.is_running():
                raise Cs2Error("CS2 se cerró mientras cargaba la demo.")
            buf = (buf + self.netcon.read(0.2, 0.6))[-100_000:]
        if _SEEK_DONE_RE.search(buf):
            log.info("Salto inicial de CS2 completado")
        time.sleep(0.8)
        self.netcon.read(0.05, 0.3)

    def responsive(self, timeout: float = 3.0) -> bool:
        """``True`` si la consola contesta a un ``echo`` (CS2 no está colgado ni cargando)."""
        if not self.can_read_console:
            return True
        marker = f"CLUTCHREEL_OK_{int(time.time() * 1000)}"
        return self.query(f"echo {marker}", re.escape(marker), timeout=timeout) is not None

    def goto_tick(self, tick: int, attempts: int = 3) -> int | None:
        """Salta al tick indicado y deja la demo en pausa. Devuelve el tick confirmado por CS2 (si se pudo leer).

        Solo se acepta la confirmación de un salto que llegue cerca del tick pedido:
        CS2 también imprime «Skipping finished» en sus saltos propios.
        """
        readable = self.can_read_console
        wait = max(1.0, float(self.settings.seek_wait))
        reached: int | None = None
        for attempt in range(1, attempts + 1 if readable else 2):
            if readable:
                self.netcon.read(0.02, 0.2)
            # Tras una pausa de ``demo_step_tick`` un salto corto hacia delante no se mueve (CS2 se queda
            # «Demo paused at engine time…»; verificado en 1.41.9). Reanudar y pausar lo deja en pausa normal.
            self.send("demo_resume")
            time.sleep(0.3)
            self.send(["demo_pause", f"demo_gototick {int(tick)}"])
            if not readable:
                break
            buf = ""
            deadline = time.time() + max(20.0, wait * 3)
            while time.time() < deadline and reached is None:
                self._check_cancel()
                if not self.is_running():
                    raise Cs2Error("CS2 se cerró durante la búsqueda en la demo.")
                buf = (buf + self.netcon.read(0.2, 0.6))[-100_000:]
                for m in _SEEK_DONE_RE.finditer(buf):
                    if abs(int(m.group(1)) - int(tick)) <= SEEK_TOLERANCE:
                        reached = int(m.group(1))
                        break
            if reached is not None:
                break
            log.warning("CS2 no confirmó el salto al tick %d (intento %d)", tick, attempt)
            if not self.responsive():
                raise Cs2Error("CS2 no responde por la consola (¿se ha quedado colgado?).")
        if reached is None:
            # Sin confirmación (consola no legible o CS2 no la imprimió) se espera el tiempo configurado. (Antes este bloque
            # colgaba de un for…else que el «break» anterior se saltaba: se grababa sin esperar al salto.)
            deadline = time.time() + wait
            while time.time() < deadline:
                self._check_cancel()
                if not self.is_running():
                    raise Cs2Error("CS2 se cerró durante la búsqueda en la demo.")
                time.sleep(0.25)
        self.send("demo_pause")
        time.sleep(0.3)
        return reached

    def follow_player(self, steamid64: int, name: str, slot: int | None, timeline: DemoTimeline | None, tick: int) -> tuple[str, CameraMatch | None]:
        """Pone la cámara en primera persona sobre el jugador y lo comprueba.

        Dos pruebas independientes, ambas leídas de la consola de CS2:

        * la posición de la cámara (``getpos``) coincide con el ojo del jugador en la demo;
        * CS2 anuncia «Added TrueView prediction for player slot N (nombre)» con su nombre.

        Devuelve ``(método, coincidencia)``. Métodos: ``slot``, ``nombre``, ``spec_next``
        o ``sin verificar`` (cuando no se puede leer la consola). Lanza
        :class:`SpectateError` si ningún método consigue seguir al jugador.
        """
        attempts: list[tuple[str, list[str]]] = []
        if slot is not None and slot >= 0:
            attempts.append(("slot", [spec_player_command(slot), "spec_mode 2"]))
        if name:
            attempts.append(("nombre", [spec_name_command(name), "spec_mode 2"]))
        if not attempts:
            raise SpectateError(f"No se sabe qué slot ocupa {name or steamid64} en la demo.")
        if not (self.can_read_console and timeline is not None):
            self.send(attempts[0][1])
            time.sleep(0.3)
            return "sin verificar", None
        last: CameraMatch | None = None
        got_position = False
        announced = ""
        t_start = time.perf_counter()
        for method, cmds in attempts:
            t_sent = time.perf_counter()
            self.send(cmds)
            time.sleep(0.4)
            match = self._identify(timeline, tick, steamid64)
            got_position = got_position or self._last_pos is not None
            last = match or last
            if self._verified(match, steamid64, name, slot, since=t_sent):
                return method, match
            announced = self._announced_name(since=t_sent)
            log.warning("Cámara tras «%s»: %s (consola: %s)", cmds[0], match, announced or "sin anuncio")
        if not got_position and not self.responsive():
            # Sin respuesta a getpos ni a echo: recorrer jugadores no serviría de nada.
            raise Cs2Error("CS2 no responde por la consola (¿se ha quedado colgado o sigue cargando?).")
        # Último recurso: recorrer a los jugadores con spec_next hasta dar con él.
        for _ in range(12):
            t_sent = time.perf_counter()
            self.send(["spec_next", "spec_mode 2"])
            time.sleep(0.35)
            match = self._identify(timeline, tick, steamid64)
            last = match or last
            if self._verified(match, steamid64, name, slot, since=t_sent):
                return "spec_next", match
        announced = self._announced_name(since=t_start)
        if announced and announced != name:
            seen = f"CS2 anuncia que sigue a {announced}"
        elif last and last.name and last.distance < 48:
            seen = f"sigue a {last.name}"
        else:
            seen = "no se pudo situar la cámara sobre ningún jugador"
        raise SpectateError(f"La cámara no sigue a {name}: {seen}.")

    def _announced_name(self, since: float = 0.0) -> str:
        """Último jugador anunciado por CS2 desde el instante ``since`` ("" si no hubo anuncio)."""
        for t, _slot, who in reversed(self.camera_changes):
            if t >= since:
                return who
            break
        return ""

    def _verified(self, match: CameraMatch | None, steamid64: int, name: str, slot: int | None, since: float = 0.0) -> bool:
        """Cámara en el jugador según la posición; si CS2 anunció otro nombre tras el comando, no se da por buena."""
        if not camera_on_target(match, steamid64):
            return False
        announced = [(s, who) for t, s, who in self.camera_changes if t >= since]
        if announced and name:
            cur_slot, cur_name = announced[-1]
            if cur_name != name and (slot is None or cur_slot != slot):
                return False
        return True

    def _identify(self, timeline: DemoTimeline, tick: int, target: int) -> CameraMatch | None:
        pos = self.camera_position()
        self._last_pos = pos
        if pos is None:
            # Sin posición (consola saturada): al menos se vacía lo acumulado para leer los anuncios de cámara.
            self.netcon.read(0.05, 0.3)
            return None
        return timeline.identify(pos, tick, window=24, target=target)

    def resume(self) -> None:
        self.send(["demo_timescale 1", "demo_resume"])

    def play_ticks(self, ticks: int) -> None:
        """Desde la pausa, reproduce exactamente ``ticks`` ticks y vuelve a pausar (``demo_step_tick``).

        CS2 reproduce las demos más lento que el tiempo real (~57 ticks/s con 64 de tickrate,
        medido en CS2 1.41.9), así que esperar por reloj cortaría el final de las jugadas largas.
        Al terminar imprime «Demo paused at engine time X, demo tick Y», que se recoge en :attr:`pauses`.
        """
        if self.can_read_console:
            self.netcon.read(0.02, 0.2)
        self.send(["demo_timescale 1", f"demo_step_tick {max(1, int(ticks))}"])

    def pause(self) -> None:
        self.send("demo_pause")

    def set_timescale(self, scale: float) -> None:
        self.send(f"demo_timescale {scale:g}")

