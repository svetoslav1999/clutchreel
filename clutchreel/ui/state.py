"""Estado compartido de la aplicación (configuración, proyecto actual, historial)."""

from __future__ import annotations

from PySide6.QtCore import QObject, Signal

from clutchreel.core.editor.project import Project, UndoStack
from clutchreel.core.export.ffmpeg import FFmpeg
from clutchreel.services.config import AppConfig, ConfigStore, get_store, save_config
from clutchreel.services.history import History
from clutchreel.ui.workers import WorkerPool
from clutchreel.utils.logging_setup import register_secret


class AppState(QObject):
    project_changed = Signal()
    config_changed = Signal()
    status_message = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.store: ConfigStore = get_store()
        self.history = History()
        self.project: Project | None = None
        self.undo = UndoStack()
        self.pool = WorkerPool()
        self.ffmpeg = FFmpeg(self.config.paths.ffmpeg_path)
        register_secret(self.config.obs.password)

    @property
    def config(self) -> AppConfig:
        return self.store.config

    def save(self) -> None:
        register_secret(self.config.obs.password)  # por si se cambió en Ajustes
        save_config()
        self.ffmpeg = FFmpeg(self.config.paths.ffmpeg_path)
        self.config_changed.emit()

    def set_project(self, project: Project | None) -> None:
        self.project = project
        self.undo = UndoStack()
        if project and project.path:
            recent = [p for p in self.config.ui.recent_projects if p != project.path]
            recent.insert(0, project.path)
            self.config.ui.recent_projects = recent[:10]
            save_config()
        self.project_changed.emit()

    def autosave(self) -> None:
        if self.project:
            try:
                path = self.project.save()
                if str(path) not in self.config.ui.recent_projects:
                    self.config.ui.recent_projects.insert(0, str(path))
                    self.config.ui.recent_projects = self.config.ui.recent_projects[:10]
                    save_config()
            except OSError as exc:
                self.status_message.emit(f"No se pudo guardar el proyecto: {exc}")
