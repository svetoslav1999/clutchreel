"""Cola de trabajos, progreso y resultado (abrir carpeta, previsualizar, subir)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from clutchreel.ui import icons
from clutchreel.ui.jobs import STATUS_LABELS, JobQueue
from clutchreel.ui.state import AppState
from clutchreel.ui.theme import STATUS_STYLE
from clutchreel.ui.widgets.iconbutton import icon_button
from clutchreel.ui.widgets.video_preview import VideoPreview
from clutchreel.utils.paths import open_in_explorer
from clutchreel.utils.timeutil import format_duration

STATUS_COLORS = {status: color for status, (color, _icon) in STATUS_STYLE.items()}


class ExportPage(QWidget):
    upload_requested = Signal(str, str, str, list)  # video, title, description, tags
    retry_failed_requested = Signal()
    logs_requested = Signal()

    def __init__(self, state: AppState, queue: JobQueue) -> None:
        super().__init__()
        self.state = state
        self.queue = queue
        self.queue.changed.connect(self.refresh)
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        root.setSpacing(12)
        title = QLabel("Cola de trabajos")
        title.setObjectName("title")
        root.addWidget(title)
        root.addSpacing(4)

        cur = QFrame()
        cur.setObjectName("panel")
        cl = QVBoxLayout(cur)
        cl.setContentsMargins(16, 14, 16, 14)
        cl.setSpacing(10)
        self.lbl_current = QLabel("Sin trabajos en curso.")
        self.lbl_current.setWordWrap(True)
        self.lbl_current.setObjectName("section")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setFormat("%p %")
        self.lbl_eta = QLabel("")
        self.lbl_eta.setObjectName("muted")
        row = QHBoxLayout()
        row.addWidget(self.lbl_eta)
        row.addStretch()
        self.btn_cancel = QPushButton("Cancelar trabajo actual")
        self.btn_cancel.setObjectName("danger")
        self.btn_cancel.clicked.connect(self.queue.cancel_current)
        self.btn_cancel.setEnabled(False)
        row.addWidget(self.btn_cancel)
        cl.addWidget(self.lbl_current)
        cl.addWidget(self.bar)
        cl.addLayout(row)
        root.addWidget(cur)

        self.tbl = QTableWidget(0, 4)
        self.tbl.setHorizontalHeaderLabels(["Trabajo", "Estado", "Progreso", "Detalle"])
        self.tbl.horizontalHeader().setStretchLastSection(True)
        self.tbl.verticalHeader().setVisible(False)
        self.tbl.setShowGrid(False)
        self.tbl.setAlternatingRowColors(False)
        self.tbl.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl.setMaximumHeight(200)
        root.addWidget(self.tbl)
        tools = QHBoxLayout()
        btn_clear = QPushButton("Limpiar terminados")
        btn_clear.clicked.connect(self.queue.clear_finished)
        tools.addWidget(btn_clear)
        self.btn_retry = QPushButton("Reintentar clips fallidos")
        self.btn_retry.clicked.connect(self.retry_failed_requested.emit)
        self.btn_retry.setEnabled(False)
        btn_logs = QPushButton("Ver registro")
        btn_logs.clicked.connect(self.logs_requested.emit)
        tools.addWidget(self.btn_retry)
        tools.addWidget(btn_logs)
        tools.addStretch()
        root.addLayout(tools)

        # Resultado.
        res = QFrame()
        res.setObjectName("panel")
        rl = QGridLayout(res)
        rl.setContentsMargins(16, 14, 16, 14)
        rl.setHorizontalSpacing(12)
        rl.setVerticalSpacing(8)
        last = QLabel("Último vídeo creado")
        last.setObjectName("section")
        rl.addWidget(last, 0, 0, 1, 3)
        self.preview = VideoPreview()
        rl.addWidget(self.preview, 1, 0, 6, 1)
        self.lbl_result = QLabel("Todavía no hay vídeo.")
        self.lbl_result.setWordWrap(True)
        rl.addWidget(self.lbl_result, 1, 1, 1, 2)
        self.btn_open = icon_button("Abrir carpeta", "folder")
        self.btn_open.clicked.connect(self._open_folder)
        self.btn_play = icon_button("Previsualizar", "play")
        self.btn_play.clicked.connect(self._play)
        rl.addWidget(self.btn_open, 2, 1)
        rl.addWidget(self.btn_play, 2, 2)
        rl.addWidget(QLabel("Título"), 3, 1)
        self.edt_title = QLineEdit()
        rl.addWidget(self.edt_title, 3, 2)
        rl.addWidget(QLabel("Etiquetas"), 4, 1)
        self.edt_tags = QLineEdit()
        rl.addWidget(self.edt_tags, 4, 2)
        rl.addWidget(QLabel("Descripción"), 5, 1, Qt.AlignmentFlag.AlignTop)
        self.txt_desc = QPlainTextEdit()
        self.txt_desc.setMaximumHeight(120)
        rl.addWidget(self.txt_desc, 5, 2)
        self.btn_upload = icon_button("Subir a YouTube (privado)", "upload")
        self.btn_upload.clicked.connect(self._upload)
        self.btn_copy = QPushButton("Copiar título y descripción")
        self.btn_copy.clicked.connect(self._copy_meta)
        rl.addWidget(self.btn_copy, 6, 1)
        rl.addWidget(self.btn_upload, 6, 2)
        rl.setColumnStretch(0, 1)
        rl.setColumnStretch(2, 1)
        root.addWidget(res, 1)
        self.result_video: Path | None = None
        self.refresh()

    def refresh(self) -> None:
        cur = self.queue.current
        if cur:
            self.lbl_current.setText(f"<b>{cur.title}</b><br>{cur.message}")
            self.bar.setValue(cur.progress)
            eta = cur.eta_seconds()
            self.lbl_eta.setText(f"Transcurrido {format_duration(cur.elapsed)}" + (f" · quedan ≈ {format_duration(eta)}" if eta else ""))
            self.btn_cancel.setEnabled(True)
        else:
            self.lbl_current.setText("Sin trabajos en curso.")
            self.bar.setValue(0)
            self.lbl_eta.setText("")
            self.btn_cancel.setEnabled(False)
        jobs = list(self.queue.jobs)[-30:]
        self.tbl.setRowCount(len(jobs))
        for row, job in enumerate(reversed(jobs)):
            self.tbl.setItem(row, 0, QTableWidgetItem(job.title))
            state_item = QTableWidgetItem(STATUS_LABELS.get(job.status, job.status))
            color, icon_name = STATUS_STYLE.get(job.status, ("", ""))
            if color:
                state_item.setForeground(QColor(color))
                state_item.setIcon(icons.icon(icon_name, color, 16))
            self.tbl.setItem(row, 1, state_item)
            self.tbl.setItem(row, 2, QTableWidgetItem(f"{job.progress}%"))
            detail = QTableWidgetItem(job.error or job.message)
            detail.setToolTip(job.error or job.message)
            self.tbl.setItem(row, 3, detail)
        self.tbl.resizeColumnsToContents()
        last_rec = next((j for j in reversed(self.queue.jobs) if j.kind == "grabar"), None)
        self.btn_retry.setEnabled(last_rec is not None and last_rec.status in ("parcial", "error") and not self.queue.busy)
        self.btn_upload.setEnabled(self.result_video is not None)

    def show_result(self, video: Path, thumbnail: Path | None, duration: float, title: str, description: str, tags: list[str]) -> None:
        self.result_video = video
        self.lbl_result.setText(f"<b>{video.name}</b><br>{format_duration(duration)} · {video.stat().st_size / 1e6:.0f} MB" + (f"<br>Miniatura: {thumbnail.name}" if thumbnail else ""))
        self.edt_title.setText(title)
        self.txt_desc.setPlainText(description)
        self.edt_tags.setText(", ".join(tags))
        self.edt_title.setCursorPosition(0)  # que se vea el principio, no el final
        self.edt_tags.setCursorPosition(0)
        self.preview.load(video, autoplay=False)
        self.refresh()

    def _open_folder(self) -> None:
        if self.result_video:
            open_in_explorer(self.result_video)
        else:
            open_in_explorer(Path(self.state.config.paths.output_folder))

    def _play(self) -> None:
        if self.result_video:
            self.preview.load(self.result_video, autoplay=True)

    def _copy_meta(self) -> None:
        from PySide6.QtWidgets import QApplication

        QApplication.clipboard().setText(f"{self.edt_title.text()}\n\n{self.txt_desc.toPlainText()}\n\n{self.edt_tags.text()}")
        self.state.status_message.emit("Título, descripción y etiquetas copiados.")

    def _upload(self) -> None:
        if not self.result_video:
            return
        tags = [t.strip() for t in self.edt_tags.text().split(",") if t.strip()]
        self.upload_requested.emit(str(self.result_video), self.edt_title.text(), self.txt_desc.toPlainText(), tags)
