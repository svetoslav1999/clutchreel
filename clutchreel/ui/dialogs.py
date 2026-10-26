"""Diálogos: diagnóstico, registro, primera configuración, instrucciones manuales, errores."""

from __future__ import annotations

from PySide6.QtCore import QEventLoop, Qt, QThread, Signal
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QProgressDialog,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from clutchreel.services.config import AppConfig, ConfigStore
from clutchreel.services.diagnostics import diagnostics_text, run_diagnostics
from clutchreel.services.obs_setup import OBS_AUTOCONFIG_ACTION, ObsSetupError, SetupResult, configure_obs
from clutchreel.utils.logging_setup import build_error_report, log_file_path, read_log_tail
from clutchreel.utils.paths import open_in_explorer
from clutchreel.utils.winutil import is_process_running


class _ObsSetupThread(QThread):
    finished_setup = Signal(object, str)  # (SetupResult | None, mensaje de error)

    def __init__(self, store: ConfigStore) -> None:
        super().__init__()
        self.store = store

    def run(self) -> None:
        try:
            self.finished_setup.emit(configure_obs(self.store, confirm_close=lambda: True), "")
        except ObsSetupError as exc:
            self.finished_setup.emit(None, str(exc))
        except Exception as exc:  # noqa: BLE001
            self.finished_setup.emit(None, f"Error inesperado: {exc}")


def run_obs_autoconfig(parent: QWidget | None, store: ConfigStore) -> bool:
    """Activa el WebSocket de OBS desde la app. Avisa antes de cerrar OBS. ``True`` si quedó listo."""
    if is_process_running("obs64.exe"):
        msg = (
            "OBS está abierto. Para activar el WebSocket hay que cerrarlo (cierre limpio, no forzado) y volver a abrirlo.\n\n"
            "Si estás grabando o emitiendo, cancela y hazlo cuando termines.\n\n¿Cerrar y reabrir OBS ahora?"
        )
    else:
        msg = "Se activará el servidor WebSocket de OBS y se abrirá OBS. ¿Continuar?"
    if not ask_yes_no(parent, "Configurar OBS automáticamente", msg):
        return False
    progress = QProgressDialog("Configurando OBS…", "", 0, 0, parent)
    progress.setCancelButton(None)
    progress.setWindowModality(Qt.WindowModality.WindowModal)
    progress.show()
    thread = _ObsSetupThread(store)
    loop = QEventLoop()
    outcome: list[tuple[SetupResult | None, str]] = []
    thread.finished_setup.connect(lambda res, err: outcome.append((res, err)))
    thread.finished.connect(loop.quit)
    thread.start()
    loop.exec()
    progress.close()
    result, error = outcome[0] if outcome else (None, "La configuración terminó sin resultado.")
    if result is None:
        show_error(parent, "Configurar OBS", error)
        return False
    extra = f" (el puerto 4455 estaba ocupado; se usó el {result.port})" if result.port_changed else ""
    show_info(parent, "Configurar OBS", f"WebSocket activado en el puerto {result.port}{extra}. Puerto y contraseña ya están guardados en Ajustes → OBS.")
    return True


def show_error(parent: QWidget | None, title: str, message: str, detail: str = "") -> None:
    box = QMessageBox(parent)
    box.setIcon(QMessageBox.Icon.Critical)
    box.setWindowTitle(title)
    box.setText(message)
    if detail:
        box.setDetailedText(detail)
    box.exec()


def show_info(parent: QWidget | None, title: str, message: str) -> None:
    QMessageBox.information(parent, title, message)


def ask_yes_no(parent: QWidget | None, title: str, message: str) -> bool:
    res = QMessageBox.question(parent, title, message, QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    return res == QMessageBox.StandardButton.Yes


class DiagnosticsDialog(QDialog):
    def __init__(self, config: AppConfig, parent: QWidget | None = None, store: ConfigStore | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self.config = config
        self.setWindowTitle("Diagnóstico")
        self.resize(760, 520)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        btn_again = QPushButton("Volver a comprobar")
        btn_again.clicked.connect(lambda: self.run(config))
        self.btn_fix_obs = QPushButton("Configurar OBS automáticamente")
        self.btn_fix_obs.clicked.connect(self._fix_obs)
        self.btn_fix_obs.hide()
        btn_copy = QPushButton("Copiar")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.text.toPlainText()))
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_again)
        row.addWidget(self.btn_fix_obs)
        row.addWidget(btn_copy)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)
        self.run(config)

    def run(self, config: AppConfig) -> None:
        self.text.setPlainText("Comprobando…")
        QApplication.processEvents()
        results = run_diagnostics(config)
        missing = [r for r in results if not r.ok and not r.warning]
        head = "Todo listo para crear vídeos." if not missing else f"Faltan {len(missing)} cosas por resolver:"
        self.text.setPlainText(head + "\n\n" + diagnostics_text(results))
        self.btn_fix_obs.setVisible(self.store is not None and any(r.fix_action == OBS_AUTOCONFIG_ACTION for r in results))

    def _fix_obs(self) -> None:
        if self.store is not None and run_obs_autoconfig(self, self.store):
            self.run(self.store.config)


class LogsDialog(QDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Registro de la aplicación")
        self.resize(900, 600)
        layout = QVBoxLayout(self)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        self.text.setPlainText(read_log_tail())
        self.text.moveCursor(self.text.textCursor().MoveOperation.End)
        layout.addWidget(self.text, 1)
        row = QHBoxLayout()
        btn_copy = QPushButton("Copiar informe de errores")
        btn_copy.clicked.connect(self._copy_report)
        btn_open = QPushButton("Abrir carpeta de registros")
        btn_open.clicked.connect(lambda: open_in_explorer(log_file_path()))
        btn_refresh = QPushButton("Actualizar")
        btn_refresh.clicked.connect(lambda: self.text.setPlainText(read_log_tail()))
        btn_close = QPushButton("Cerrar")
        btn_close.clicked.connect(self.accept)
        row.addWidget(btn_copy)
        row.addWidget(btn_open)
        row.addWidget(btn_refresh)
        row.addStretch()
        row.addWidget(btn_close)
        layout.addLayout(row)

    def _copy_report(self) -> None:
        QApplication.clipboard().setText(build_error_report())
        QMessageBox.information(self, "Copiado", "El informe de errores se copió al portapapeles.")


class ManualStepDialog(QDialog):
    """Modo semiautomático: muestra comandos y espera a que el usuario los teclee."""

    def __init__(self, text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Paso manual en CS2")
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint, True)
        self.resize(560, 360)
        layout = QVBoxLayout(self)
        lbl = QLabel("ClutchReel no pudo enviar los comandos automáticamente. Abre la consola de CS2 (tecla º o `) y teclea:")
        lbl.setWordWrap(True)
        layout.addWidget(lbl)
        box = QPlainTextEdit(text)
        box.setReadOnly(True)
        layout.addWidget(box, 1)
        btn_copy = QPushButton("Copiar comandos")
        btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(text))
        layout.addWidget(btn_copy)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Hecho, continuar")
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Cancelar grabación")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


class FirstRunDialog(QDialog):
    """Asistente de primera configuración: muestra lo detectado y pide lo mínimo."""

    def __init__(self, config: AppConfig, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Bienvenido a ClutchReel")
        self.resize(720, 520)
        layout = QVBoxLayout(self)
        title = QLabel("Primera configuración")
        title.setObjectName("title")
        layout.addWidget(title)
        sub = QLabel("ClutchReel ha detectado esto en tu PC. Puedes cambiarlo luego en Ajustes.")
        sub.setObjectName("subtitle")
        layout.addWidget(sub)
        self.text = QPlainTextEdit()
        self.text.setReadOnly(True)
        layout.addWidget(self.text, 1)
        self.chk_watch = QCheckBox("Activar el modo automático (vigilar la carpeta de demos)")
        self.chk_watch.setChecked(False)
        layout.addWidget(self.chk_watch)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Empezar")
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)
        results = run_diagnostics(config)
        self.text.setPlainText(diagnostics_text(results))
