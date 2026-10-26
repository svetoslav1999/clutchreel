"""Icono de bandeja y notificaciones."""

from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

_tray: QSystemTrayIcon | None = None


def install_tray(icon: QIcon, on_show, on_quit, on_toggle_auto):  # type: ignore[no-untyped-def]
    global _tray
    if not QSystemTrayIcon.isSystemTrayAvailable():
        return None
    tray = QSystemTrayIcon(icon)
    tray.setToolTip("ClutchReel")
    menu = QMenu()
    act_show = menu.addAction("Abrir ClutchReel")
    act_show.triggered.connect(on_show)
    act_auto = menu.addAction("Modo automático")
    act_auto.setCheckable(True)
    act_auto.toggled.connect(on_toggle_auto)
    menu.addSeparator()
    act_quit = menu.addAction("Salir")
    act_quit.triggered.connect(on_quit)
    tray.setContextMenu(menu)
    tray.activated.connect(lambda reason: on_show() if reason == QSystemTrayIcon.ActivationReason.Trigger else None)
    tray.show()
    _tray = tray
    tray.auto_action = act_auto  # type: ignore[attr-defined]
    return tray


def tray_notify(title: str, message: str) -> bool:
    if _tray is None or not _tray.isVisible():
        return False
    _tray.showMessage(title, message, QSystemTrayIcon.MessageIcon.Information, 8000)
    return True
