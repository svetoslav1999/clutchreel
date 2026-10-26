"""Rutas de la aplicación y detección de Steam / CS2 / OBS / FFmpeg.

Todas las funciones son tolerantes a fallos: nunca lanzan por una ruta
inexistente, devuelven ``None`` o listas vacías.
"""

from __future__ import annotations

import os
import re
import shutil
import sys
from pathlib import Path

from clutchreel import APP_NAME

CS2_APP_ID = "730"
CS2_FOLDER = "Counter-Strike Global Offensive"
STEAM_ID64_BASE = 76561197960265728


def is_frozen() -> bool:
    """``True`` si se ejecuta empaquetado con PyInstaller."""
    return bool(getattr(sys, "frozen", False))


def project_root() -> Path:
    """Carpeta raíz del proyecto (donde viven ``assets`` y ``Iniciar.bat``)."""
    if is_frozen():
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[2]


def assets_dir() -> Path:
    """Carpeta de recursos (iconos, música incluida, fuentes)."""
    if is_frozen():
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            cand = Path(meipass) / "assets"
            if cand.exists():
                return cand
    return project_root() / "assets"


def appdata_dir() -> Path:
    """``%APPDATA%\\ClutchReel`` (se crea si no existe)."""
    base = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    path = Path(base) / APP_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def logs_dir() -> Path:
    path = appdata_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def projects_dir() -> Path:
    path = appdata_dir() / "proyectos"
    path.mkdir(parents=True, exist_ok=True)
    return path


def cache_dir() -> Path:
    path = appdata_dir() / "cache"
    path.mkdir(parents=True, exist_ok=True)
    return path


def tools_dir() -> Path:
    """Carpeta donde ``Iniciar.bat`` deja FFmpeg descargado."""
    path = project_root() / "tools"
    path.mkdir(parents=True, exist_ok=True)
    return path


def default_output_dir() -> Path:
    videos = Path.home() / "Videos"
    if not videos.exists():
        videos = Path.home()
    path = videos / APP_NAME
    return path


def desktop_dir() -> Path | None:
    for cand in (
        Path.home() / "Desktop",
        Path.home() / "OneDrive" / "Desktop",
        Path.home() / "OneDrive" / "Escritorio",
        Path.home() / "Escritorio",
    ):
        if cand.is_dir():
            return cand
    return None


# ----------------------------------------------------------------- Steam ----


def _read_registry_steam_path() -> Path | None:
    if sys.platform != "win32":
        return None
    try:
        import winreg

        for hive, key in (
            (winreg.HKEY_CURRENT_USER, r"Software\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Valve\Steam"),
            (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Valve\Steam"),
        ):
            try:
                with winreg.OpenKey(hive, key) as handle:
                    for value_name in ("SteamPath", "InstallPath"):
                        try:
                            value, _ = winreg.QueryValueEx(handle, value_name)
                        except OSError:
                            continue
                        path = Path(str(value))
                        if path.is_dir():
                            return path
            except OSError:
                continue
    except Exception:  # noqa: BLE001 - winreg ausente o inaccesible
        return None
    return None


def steam_dir() -> Path | None:
    """Carpeta de instalación de Steam (registro de Windows + rutas típicas)."""
    reg = _read_registry_steam_path()
    if reg:
        return reg
    for cand in (
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "Steam",
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "Steam",
        Path("C:/Steam"),
        Path("D:/Steam"),
    ):
        if (cand / "steam.exe").exists():
            return cand
    return None


def steam_exe() -> Path | None:
    base = steam_dir()
    if base and (base / "steam.exe").exists():
        return base / "steam.exe"
    return None


_VDF_PATH_RE = re.compile(r'"path"\s+"([^"]+)"')


def steam_library_dirs() -> list[Path]:
    """Todas las bibliotecas de Steam según ``libraryfolders.vdf``."""
    base = steam_dir()
    if not base:
        return []
    libs: list[Path] = [base]
    vdf = base / "steamapps" / "libraryfolders.vdf"
    if vdf.exists():
        try:
            text = vdf.read_text(encoding="utf-8", errors="replace")
        except OSError:
            text = ""
        for raw in _VDF_PATH_RE.findall(text):
            path = Path(raw.replace("\\\\", "\\"))
            if path.is_dir() and path not in libs:
                libs.append(path)
    return libs


def cs2_dir() -> Path | None:
    """Carpeta ``Counter-Strike Global Offensive`` de CS2."""
    for lib in steam_library_dirs():
        cand = lib / "steamapps" / "common" / CS2_FOLDER
        if (cand / "game" / "bin" / "win64" / "cs2.exe").exists():
            return cand
    return None


def cs2_exe() -> Path | None:
    base = cs2_dir()
    if base:
        exe = base / "game" / "bin" / "win64" / "cs2.exe"
        if exe.exists():
            return exe
    return None


def cs2_csgo_dir() -> Path | None:
    base = cs2_dir()
    if base:
        return base / "game" / "csgo"
    return None


def cs2_demo_dirs() -> list[Path]:
    """Carpetas donde CS2 deja demos descargadas (``game/csgo`` y ``replays``)."""
    csgo = cs2_csgo_dir()
    if not csgo:
        return []
    dirs = [csgo]
    replays = csgo / "replays"
    if replays.is_dir():
        dirs.insert(0, replays)
    return dirs


def find_demo_files(folders: list[Path]) -> list[Path]:
    """Lista de ficheros ``.dem`` en las carpetas dadas (sin recursión profunda)."""
    out: list[Path] = []
    for folder in folders:
        try:
            if folder.is_dir():
                out.extend(sorted(folder.glob("*.dem")))
        except OSError:
            continue
    return out


def steam_logged_accounts() -> list[tuple[int, str, bool]]:
    """Cuentas en ``loginusers.vdf``: ``(steamid64, nombre, es_la_mas_reciente)``."""
    base = steam_dir()
    if not base:
        return []
    vdf = base / "config" / "loginusers.vdf"
    if not vdf.exists():
        return []
    try:
        text = vdf.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    out: list[tuple[int, str, bool]] = []
    block_re = re.compile(r'"(7656\d{13})"\s*\{(.*?)\}', re.S)
    for match in block_re.finditer(text):
        sid = int(match.group(1))
        body = match.group(2)
        name_m = re.search(r'"PersonaName"\s+"([^"]*)"', body)
        recent_m = re.search(r'"MostRecent"\s+"(\d)"', body)
        out.append((sid, name_m.group(1) if name_m else "", bool(recent_m and recent_m.group(1) == "1")))
    return out


def steam_userdata_ids() -> list[int]:
    """SteamID64 de los perfiles presentes en ``Steam/userdata``."""
    base = steam_dir()
    if not base:
        return []
    userdata = base / "userdata"
    ids: list[int] = []
    if userdata.is_dir():
        for child in userdata.iterdir():
            if child.is_dir() and child.name.isdigit() and child.name != "0":
                ids.append(STEAM_ID64_BASE + int(child.name))
    return ids


def steamid64_to_accountid(steamid64: int) -> int:
    return int(steamid64) - STEAM_ID64_BASE


# ------------------------------------------------------------------- OBS ----


def obs_exe() -> Path | None:
    cands = [
        Path(os.environ.get("ProgramFiles", r"C:\Program Files")) / "obs-studio" / "bin" / "64bit" / "obs64.exe",
        Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")) / "obs-studio" / "bin" / "64bit" / "obs64.exe",
    ]
    if sys.platform == "win32":
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\OBS Studio") as handle:
                value, _ = winreg.QueryValueEx(handle, "")
                cands.insert(0, Path(str(value)) / "bin" / "64bit" / "obs64.exe")
        except Exception:  # noqa: BLE001
            pass
    for cand in cands:
        if cand.exists():
            return cand
    return None


def obs_websocket_config() -> dict[str, object]:
    """Lee la configuración del plugin obs-websocket (puerto/contraseña/activado)."""
    base = os.environ.get("APPDATA")
    if not base:
        return {}
    cfg = Path(base) / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"
    if not cfg.exists():
        return {}
    try:
        import json

        data = json.loads(cfg.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:  # noqa: BLE001
        return {}


# ---------------------------------------------------------------- FFmpeg ----


def _ffmpeg_candidates() -> list[Path]:
    cands: list[Path] = []
    local = tools_dir()
    cands.append(local / "ffmpeg" / "bin" / "ffmpeg.exe")
    cands.append(local / "ffmpeg.exe")
    for sub in local.glob("ffmpeg*/bin/ffmpeg.exe"):
        cands.append(sub)
    which = shutil.which("ffmpeg")
    if which:
        cands.append(Path(which))
    winget = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if winget.is_dir():
        for sub in winget.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"):
            cands.append(sub)
    for cand in (Path("C:/ffmpeg/bin/ffmpeg.exe"), Path(os.environ.get("ProgramFiles", "")) / "ffmpeg" / "bin" / "ffmpeg.exe"):
        cands.append(cand)
    return cands


def find_ffmpeg(configured: str | None = None) -> Path | None:
    if configured:
        path = Path(configured)
        if path.is_file():
            return path
        if path.is_dir():
            for sub in (path / "ffmpeg.exe", path / "bin" / "ffmpeg.exe"):
                if sub.exists():
                    return sub
    for cand in _ffmpeg_candidates():
        try:
            if cand.is_file():
                return cand
        except OSError:
            continue
    return None


def find_ffprobe(ffmpeg_path: Path | None) -> Path | None:
    if ffmpeg_path:
        sibling = ffmpeg_path.with_name("ffprobe.exe")
        if sibling.exists():
            return sibling
    which = shutil.which("ffprobe")
    return Path(which) if which else None


def safe_filename(name: str, max_len: int = 80) -> str:
    """Nombre de fichero seguro en Windows (tildes permitidas, símbolos no)."""
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" .")
    cleaned = re.sub(r"\s+", " ", cleaned)
    return (cleaned or "sin_nombre")[:max_len]


def open_in_explorer(path: Path) -> None:
    """Abre una carpeta o selecciona un fichero en el Explorador."""
    try:
        if sys.platform != "win32":
            return
        import subprocess

        if path.is_file():
            subprocess.Popen(["explorer", "/select,", str(path)])
        else:
            os.startfile(str(path))  # type: ignore[attr-defined]  # noqa: S606
    except Exception:  # noqa: BLE001
        pass
