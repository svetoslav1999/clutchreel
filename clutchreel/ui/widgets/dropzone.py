"""Zona de arrastrar y soltar demos (.dem)."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from clutchreel.ui.theme import ACCENT, BG_PANEL, BORDER, TEXT_MUTED


class DropZone(QFrame):
    files_dropped = Signal(list)  # list[Path]

    def __init__(self, start_dir: str = "") -> None:
        super().__init__()
        self.start_dir = start_dir
        self.setAcceptDrops(True)
        self.setObjectName("dropzone")
        self.setMinimumHeight(220)
        self._base_style()
        layout = QVBoxLayout(self)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(10)
        icon = QLabel("🎯")
        icon.setStyleSheet("font-size: 48px; background: transparent; border: none;")
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title = QLabel("Arrastra aquí tus demos (.dem)")
        title.setStyleSheet("font-size: 22px; font-weight: 700; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Puedes soltar varias a la vez. También puedes elegirlas con el botón.")
        sub.setStyleSheet(f"color: {TEXT_MUTED}; background: transparent; border: none;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Elegir demos…")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.browse)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    def _base_style(self, active: bool = False) -> None:
        color = ACCENT if active else BORDER
        self.setStyleSheet(
            f"QFrame#dropzone {{ background: {BG_PANEL}; border: 2px dashed {color}; border-radius: 16px; }}"
        )

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".dem") for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._base_style(True)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._base_style(False)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._base_style(False)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile().lower().endswith(".dem")]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Elegir demos de CS2", self.start_dir, "Demos de CS2 (*.dem)")
        if files:
            self.files_dropped.emit([Path(f) for f in files])
