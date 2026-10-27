"""Arranque de la aplicación Qt."""

from __future__ import annotations

import logging
import sys
import traceback
from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QMessageBox

from clutchreel import APP_NAME
from clutchreel.utils.logging_setup import setup_logging
from clutchreel.utils.paths import assets_dir

log = logging.getLogger(__name__)


def make_icon() -> QIcon:
    ico = assets_dir() / "icon.ico"
    if ico.exists():
        return QIcon(str(ico))
    from clutchreel.ui.icons import app_icon_pixmap

    icon = QIcon()
    for size in (16, 24, 32, 48, 64, 128, 256):
        icon.addPixmap(app_icon_pixmap(size))
    return icon


def _install_excepthook(app: QApplication) -> None:
    def hook(exc_type, exc, tb):  # type: ignore[no-untyped-def]
        text = "".join(traceback.format_exception(exc_type, exc, tb))
        log.critical("Excepción no controlada:\n%s", text)
        try:
            box = QMessageBox(QMessageBox.Icon.Critical, "Error inesperado", f"Ha ocurrido un error inesperado:\n{exc}\n\nLa app sigue funcionando; si se repite, copia el registro desde Ajustes → Ver registro.")
            box.setDetailedText(text)
            box.exec()
        except Exception:  # noqa: BLE001
            pass

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    setup_logging()
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setStyle("Fusion")
    _install_excepthook(app)

    from clutchreel.ui.main_window import MainWindow
    from clutchreel.ui.state import AppState
    from clutchreel.ui.theme import stylesheet

    state = AppState()
    app.setStyleSheet(stylesheet(state.config.ui.theme))
    icon = make_icon()
    app.setWindowIcon(icon)
    window = MainWindow(state, icon)
    geo = state.config.ui.window_geometry
    if geo:
        try:
            window.restoreGeometry(QByteArray.fromBase64(geo.encode("ascii")))
        except Exception:  # noqa: BLE001
            pass
    window.show()
    demos = [Path(a) for a in (argv or sys.argv)[1:] if a.lower().endswith(".dem")]
    if demos:
        window.analyze_demos(demos)
    return app.exec()
