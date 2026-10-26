"""Pantalla de inicio: zona de arrastre, demos detectadas, proyectos recientes, historial."""

from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QFrame,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from clutchreel.ui.state import AppState
from clutchreel.ui.widgets.dropzone import DropZone
from clutchreel.utils import paths


class HomePage(QWidget):
    demos_chosen = Signal(list)  # list[Path]
    project_chosen = Signal(str)
    auto_mode_toggled = Signal(bool)

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 28, 32, 28)
        root.setSpacing(18)
        title = QLabel("ClutchReel")
        title.setObjectName("title")
        sub = QLabel("De la demo de CS2 al vídeo de mejores jugadas, sin tocar nada técnico.")
        sub.setObjectName("subtitle")
        root.addWidget(title)
        root.addWidget(sub)

        self.drop = DropZone(self._demo_folder())
        self.drop.files_dropped.connect(self.demos_chosen.emit)
        root.addWidget(self.drop)

        auto_row = QHBoxLayout()
        self.chk_auto = QCheckBox("Modo TODO AUTOMÁTICO: vigilar la carpeta de demos y procesar las nuevas con el perfil guardado")
        self.chk_auto.setChecked(self.state.config.watcher.enabled)
        self.chk_auto.toggled.connect(self.auto_mode_toggled.emit)
        auto_row.addWidget(self.chk_auto)
        auto_row.addStretch()
        root.addLayout(auto_row)

        columns = QHBoxLayout()
        columns.setSpacing(18)
        root.addLayout(columns, 1)

        # Demos encontradas en la carpeta de CS2.
        demos_panel = QFrame()
        demos_panel.setObjectName("panel")
        dl = QVBoxLayout(demos_panel)
        head = QHBoxLayout()
        head.addWidget(QLabel("<b>Demos en tu carpeta de CS2</b>"))
        head.addStretch()
        btn_refresh = QPushButton("Actualizar")
        btn_refresh.setObjectName("flat")
        btn_refresh.clicked.connect(self.refresh)
        head.addWidget(btn_refresh)
        dl.addLayout(head)
        self.lst_demos = QListWidget()
        self.lst_demos.itemDoubleClicked.connect(self._open_demo_item)
        dl.addWidget(self.lst_demos, 1)
        self.lbl_demo_hint = QLabel("")
        self.lbl_demo_hint.setObjectName("muted")
        self.lbl_demo_hint.setWordWrap(True)
        dl.addWidget(self.lbl_demo_hint)
        columns.addWidget(demos_panel, 1)

        # Proyectos recientes + historial.
        right = QFrame()
        right.setObjectName("panel")
        rl = QVBoxLayout(right)
        rl.addWidget(QLabel("<b>Proyectos recientes</b>"))
        self.lst_recent = QListWidget()
        self.lst_recent.itemDoubleClicked.connect(lambda item: self.project_chosen.emit(item.data(Qt.ItemDataRole.UserRole)))
        rl.addWidget(self.lst_recent, 1)
        rl.addWidget(QLabel("<b>Historial de demos procesadas</b>"))
        self.history_area = QScrollArea()
        self.history_area.setWidgetResizable(True)
        self.history_box = QWidget()
        self.history_layout = QVBoxLayout(self.history_box)
        self.history_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.history_area.setWidget(self.history_box)
        rl.addWidget(self.history_area, 1)
        columns.addWidget(right, 1)
        self.refresh()

    def _demo_folder(self) -> str:
        cfg = self.state.config
        if cfg.paths.demo_folder:
            return cfg.paths.demo_folder
        dirs = paths.cs2_demo_dirs()
        return str(dirs[0]) if dirs else ""

    def _demo_dirs(self) -> list[Path]:
        cfg = self.state.config
        dirs: list[Path] = []
        if cfg.paths.demo_folder:
            dirs.append(Path(cfg.paths.demo_folder))
        dirs += [Path(p) for p in cfg.paths.extra_demo_folders if p]
        if not dirs:
            dirs = paths.cs2_demo_dirs()
        return dirs

    def refresh(self) -> None:
        self.drop.start_dir = self._demo_folder()
        self.lst_demos.clear()
        dirs = self._demo_dirs()
        demos = paths.find_demo_files(dirs)
        demos.sort(key=lambda p: p.stat().st_mtime if p.exists() else 0, reverse=True)
        for p in demos[:60]:
            try:
                size_mb = p.stat().st_size / 1e6
                when = time.strftime("%d/%m/%Y %H:%M", time.localtime(p.stat().st_mtime))
            except OSError:
                size_mb, when = 0.0, ""
            done = self.state.history.find(p) is not None
            item = QListWidgetItem(f"{'✅ ' if done else ''}{p.name}   ·   {size_mb:.0f} MB   ·   {when}")
            item.setData(Qt.ItemDataRole.UserRole, str(p))
            item.setToolTip(str(p) + ("\nYa procesada (doble clic para volver a procesar)" if done else "\nDoble clic para analizar"))
            self.lst_demos.addItem(item)
        if not dirs:
            self.lbl_demo_hint.setText("No se encontró la carpeta de demos de CS2. Configúrala en Ajustes → Rutas o arrastra las demos aquí.")
        elif not demos:
            self.lbl_demo_hint.setText(f"No hay demos en {dirs[0]}. Descarga una partida desde CS2 (Ver partidas → Descargar) o arrastra una aquí.")
        else:
            self.lbl_demo_hint.setText(f"Carpeta: {dirs[0]} · doble clic para analizar")

        self.lst_recent.clear()
        for proj in self.state.config.ui.recent_projects:
            if Path(proj).exists():
                item = QListWidgetItem(Path(proj).name.replace(".clutchreel.json", ""))
                item.setData(Qt.ItemDataRole.UserRole, proj)
                item.setToolTip(proj)
                self.lst_recent.addItem(item)
        while self.history_layout.count():
            child = self.history_layout.takeAt(0)
            widget = child.widget() if child is not None else None
            if widget is not None:
                widget.deleteLater()
        for e in self.state.history.entries[:15]:
            when = time.strftime("%d/%m/%Y %H:%M", time.localtime(e.processed_at))
            lbl = QLabel(f"<b>{e.map_name}</b> · {e.player_name} · {e.score} · <span style='color:#8b98a9'>{when}</span>")
            lbl.setToolTip(e.demo_path + (f"\nVídeo: {e.output_video}" if e.output_video else ""))
            self.history_layout.addWidget(lbl)
        if not self.state.history.entries:
            lbl = QLabel("Todavía no has procesado ninguna demo.")
            lbl.setObjectName("muted")
            self.history_layout.addWidget(lbl)
        self.chk_auto.blockSignals(True)
        self.chk_auto.setChecked(self.state.config.watcher.enabled)
        self.chk_auto.blockSignals(False)

    def _open_demo_item(self, item: QListWidgetItem) -> None:
        self.demos_chosen.emit([Path(item.data(Qt.ItemDataRole.UserRole))])
