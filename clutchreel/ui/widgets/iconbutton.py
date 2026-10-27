"""Botón con icono de línea (mismo trazo en toda la app)."""

from __future__ import annotations

from PySide6.QtCore import QSize
from PySide6.QtWidgets import QPushButton

from clutchreel.ui import icons, theme


def icon_button(text: str, icon_name: str, primary: bool = False) -> QPushButton:
    pal = theme.current()
    btn = QPushButton(text)
    btn.setIcon(icons.icon(icon_name, pal.accent_ink if primary else pal.text, 18))
    btn.setIconSize(QSize(18, 18))
    if primary:
        btn.setObjectName("primary")
    return btn
