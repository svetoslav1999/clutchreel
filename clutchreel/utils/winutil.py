"""Integración con Windows: notificaciones, procesos, apagado, espacio en disco."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

log = logging.getLogger(__name__)


def is_process_running(exe_name: str) -> bool:
    """``True`` si existe un proceso con ese nombre de ejecutable (p. ej. ``cs2.exe``)."""
    try:
        import psutil

        target = exe_name.lower()
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info.get("name") or "").lower() == target:
                    return True
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception as exc:  # noqa: BLE001
        log.debug("psutil no disponible: %s", exc)
    return False


def find_process(exe_name: str):  # type: ignore[no-untyped-def]
    try:
        import psutil

        target = exe_name.lower()
        for proc in psutil.process_iter(["name"]):
            try:
                if (proc.info.get("name") or "").lower() == target:
                    return proc
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
    except Exception:  # noqa: BLE001
        return None
    return None


def kill_process(exe_name: str) -> bool:
    proc = find_process(exe_name)
    if proc is None:
        return False
    try:
        proc.terminate()
        proc.wait(timeout=10)
        return True
    except Exception:  # noqa: BLE001
        try:
            proc.kill()
            return True
        except Exception:  # noqa: BLE001
            return False


def free_disk_bytes(path: Path) -> int:
    try:
        probe = path
        while not probe.exists() and probe.parent != probe:
            probe = probe.parent
        return shutil.disk_usage(str(probe)).free
    except OSError:
        return 0


def shutdown_windows(delay_seconds: int = 60) -> bool:
    """Programa el apagado del PC (``shutdown /s``). Devuelve ``True`` si se ordenó."""
    if sys.platform != "win32":
        return False
    try:
        subprocess.run(["shutdown", "/s", "/t", str(delay_seconds)], check=False, capture_output=True)
        return True
    except OSError as exc:
        log.warning("No se pudo programar el apagado: %s", exc)
        return False


def cancel_shutdown() -> None:
    if sys.platform == "win32":
        subprocess.run(["shutdown", "/a"], check=False, capture_output=True)


def notify(title: str, message: str) -> None:
    """Notificación de Windows. Usa el icono de bandeja si está disponible, si no, PowerShell."""
    try:
        from clutchreel.ui.tray import tray_notify

        if tray_notify(title, message):
            return
    except Exception:  # noqa: BLE001
        pass
    if sys.platform != "win32":
        return
    script = (
        "[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
        "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
        "$x=$t.GetElementsByTagName('text');$x.Item(0).AppendChild($t.CreateTextNode($env:CR_TITLE))|Out-Null;"
        "$x.Item(1).AppendChild($t.CreateTextNode($env:CR_MSG))|Out-Null;"
        "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('ClutchReel').Show([Windows.UI.Notifications.ToastNotification]::new($t))"
    )
    env = dict(os.environ, CR_TITLE=title, CR_MSG=message)
    try:
        subprocess.Popen(
            ["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", script],
            env=env,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except OSError as exc:
        log.debug("Notificación no enviada: %s", exc)


def subprocess_flags() -> int:
    """Flags para ocultar ventanas de consola de procesos hijos en Windows."""
    return getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
