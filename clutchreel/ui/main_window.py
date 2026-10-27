"""Ventana principal: navegación, orquestación de trabajos y modo automático."""

from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from clutchreel import APP_NAME, __version__
from clutchreel.core.demo.detectors import detect_all
from clutchreel.core.demo.models import MatchData
from clutchreel.core.demo.parser import parse_demo
from clutchreel.core.demo.selector import select_by_duration
from clutchreel.core.editor.project import Project, new_project
from clutchreel.core.export.exporter import Exporter, ExportResult
from clutchreel.core.export.metadata import suggest_metadata
from clutchreel.core.recorder.obs_client import detect_obs_settings
from clutchreel.core.recorder.recorder import Recorder
from clutchreel.services.config import DetectionSettings, StyleSettings, from_dict, to_dict
from clutchreel.services.history import HistoryEntry, demo_fingerprint
from clutchreel.services.watcher import DemoWatcher
from clutchreel.services.youtube import upload_video
from clutchreel.ui import dialogs
from clutchreel.ui.jobs import Job, JobQueue
from clutchreel.ui.pages.export_page import ExportPage
from clutchreel.ui.pages.home_page import HomePage
from clutchreel.ui.pages.review_page import ReviewPage
from clutchreel.ui.pages.settings_page import SettingsPage
from clutchreel.ui.pages.wizard_page import WizardPage, WizardResult
from clutchreel.ui.state import AppState
from clutchreel.ui.theme import stylesheet
from clutchreel.ui.tray import install_tray
from clutchreel.utils import paths
from clutchreel.utils.winutil import notify, shutdown_windows

log = logging.getLogger(__name__)


class _Bridge(QObject):
    """Puente hilo de trabajo → hilo de interfaz (diálogos modales, demos nuevas)."""

    ask_manual = Signal(str, object)  # texto, holder(dict) con Event
    ask_yes_no = Signal(str, object)  # pregunta Sí/No desde el grabador (reiniciar CS2)
    new_demo = Signal(str)


class MainWindow(QMainWindow):
    def __init__(self, state: AppState, icon: QIcon) -> None:
        super().__init__()
        self.state = state
        self.queue = JobQueue(state.pool)
        self.bridge = _Bridge()
        self.bridge.ask_manual.connect(self._on_ask_manual)
        self.bridge.ask_yes_no.connect(self._on_ask_yes_no)
        self.bridge.new_demo.connect(self._on_new_demo)
        self.watcher: DemoWatcher | None = None
        self._pending_matches: list[MatchData] = []
        self._auto_pipeline: dict[str, Any] = {}
        self._quitting = False
        self._cards_timer = QTimer(self)
        self._cards_timer.setSingleShot(True)
        self._cards_timer.setInterval(1000)
        self._cards_timer.timeout.connect(self._refresh_cards)
        self.setWindowTitle(f"{APP_NAME} {__version__}")
        self.setWindowIcon(icon)
        self.resize(1280, 820)
        self.setMinimumSize(1180, 680)

        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        layout = QHBoxLayout(root)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)

        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(220)
        sl = QVBoxLayout(sidebar)
        sl.setContentsMargins(14, 22, 14, 18)
        sl.setSpacing(6)
        brand = QLabel("🎯 ClutchReel")
        brand.setStyleSheet("font-size: 20px; font-weight: 800; padding: 6px 8px 18px 8px;")
        sl.addWidget(brand)
        self.nav_buttons: list[QPushButton] = []
        self.stack = QStackedWidget()
        self.home = HomePage(state)
        self.wizard = WizardPage(state)
        self.review = ReviewPage(state)
        self.export_page = ExportPage(state, self.queue)
        self.settings = SettingsPage(state)
        for name, page in (("🏠  Inicio", self.home), ("🧭  Asistente", self.wizard), ("✂️  Revisión", self.review), ("📦  Cola y resultado", self.export_page), ("⚙️  Ajustes", self.settings)):
            idx = self.stack.addWidget(page)
            btn = QPushButton(name)
            btn.setObjectName("nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _c=False, i=idx: self.go(i))
            sl.addWidget(btn)
            self.nav_buttons.append(btn)
        sl.addStretch()
        self.lbl_version = QLabel(f"v{__version__}")
        self.lbl_version.setObjectName("muted")
        sl.addWidget(self.lbl_version)
        layout.addWidget(sidebar)
        layout.addWidget(self.stack, 1)
        self.statusBar().showMessage("Listo")
        self.go(0)

        # Señales de páginas.
        self.home.demos_chosen.connect(self.analyze_demos)
        self.home.project_chosen.connect(self.open_project)
        self.home.auto_mode_toggled.connect(self.set_auto_mode)
        self.wizard.finished.connect(self._on_wizard_finished)
        self.wizard.cancelled.connect(lambda: self.go(0))
        self.review.record_clips.connect(self.start_recording)
        self.review.create_video.connect(self.create_video)
        self.export_page.upload_requested.connect(self.upload_to_youtube)
        self.export_page.retry_failed_requested.connect(self.start_recording)
        self.export_page.logs_requested.connect(lambda: dialogs.LogsDialog(self).exec())
        self.settings.diagnostics_requested.connect(lambda: dialogs.DiagnosticsDialog(self.state.config, self, self.state.store).exec())
        self.settings.logs_requested.connect(lambda: dialogs.LogsDialog(self).exec())
        self.settings.test_recording_requested.connect(self.test_recording)
        self.settings.theme_changed.connect(self._apply_theme)
        self.state.status_message.connect(lambda m: self.statusBar().showMessage(m, 6000))
        self.state.project_changed.connect(self._on_project_changed)
        self.queue.job_failed.connect(self._on_job_failed)
        self.queue.changed.connect(self._on_queue_changed)

        act_undo = QAction("Deshacer", self)
        act_undo.setShortcut(QKeySequence.StandardKey.Undo)
        act_undo.triggered.connect(self.review._undo)
        act_redo = QAction("Rehacer", self)
        act_redo.setShortcut(QKeySequence.StandardKey.Redo)
        act_redo.triggered.connect(self.review._redo)
        self.addAction(act_undo)
        self.addAction(act_redo)

        self.tray = install_tray(icon, self.show_from_tray, self.quit_app, self.set_auto_mode)
        detect_obs_settings(self.state.config.obs)
        QTimer.singleShot(300, self._first_run)
        if self.state.config.watcher.enabled:
            QTimer.singleShot(1500, lambda: self.set_auto_mode(True))

    # ------------------------------------------------------------ nav -------

    @staticmethod
    def _apply_theme(theme: str) -> None:
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(stylesheet(theme))

    def go(self, index: int) -> None:
        self.stack.setCurrentIndex(index)
        for i, b in enumerate(self.nav_buttons):
            b.setChecked(i == index)
        if index == 0:
            self.home.refresh()

    def _first_run(self) -> None:
        cfg = self.state.config
        if cfg.ui.first_run_done:
            return
        dlg = dialogs.FirstRunDialog(cfg, self)
        dlg.exec()
        cfg.ui.first_run_done = True
        cfg.watcher.enabled = dlg.chk_watch.isChecked()
        if not cfg.player.steamid64:
            for sid, name, recent in paths.steam_logged_accounts():
                if recent:
                    cfg.player.steamid64, cfg.player.name = sid, name
        self.state.save()
        self.settings.load()
        if cfg.watcher.enabled:
            self.set_auto_mode(True)

    def _on_project_changed(self) -> None:
        self.review.load_project()

    def _on_queue_changed(self) -> None:
        cur = self.queue.current
        if cur:
            self.statusBar().showMessage(f"{cur.title}: {cur.message} ({cur.progress}%)")
        # Las tarjetas reflejan el estado de grabación de cada clip; con refrescarlas una vez por segundo
        # basta (antes se repintaban todas con cada aviso de progreso).
        if not self._cards_timer.isActive():
            self._cards_timer.start()

    def _refresh_cards(self) -> None:
        self.review.refresh_cards()

    def _on_job_failed(self, job: Job) -> None:
        if job.status == "cancelado":
            self.statusBar().showMessage(f"{job.title}: cancelado", 8000)
            return
        if not self.should_report_failure(job):
            return
        dialogs.show_error(self, f"Error en «{job.title}»", job.error, "Consulta Ajustes → Ver registro para más detalles.")

    @staticmethod
    def should_report_failure(job: Job) -> bool:
        """Una grabación parcial ya la explica su propio diálogo (con los clips fallidos); no se duplica."""
        return not (job.kind == "grabar" and job.result is not None)

    # ------------------------------------------------------- analyze --------

    def analyze_demos(self, demos: list[Path], auto: bool = False) -> None:
        queued = 0
        for demo in demos:
            prev = self.state.history.find(demo)
            if prev and not auto:
                if prev.project_path and Path(prev.project_path).exists():
                    if not dialogs.ask_yes_no(self, "Demo ya procesada", f"Esta demo ya se procesó ({prev.map_name}, {prev.player_name}).\n¿Quieres volver a analizarla? (No = abrir el proyecto anterior)"):
                        self.open_project(prev.project_path)
                        continue
            title = f"Analizar {demo.name}"

            def run(progress, cancel, _demo=demo):  # type: ignore[no-untyped-def]
                return parse_demo(_demo, progress=lambda p, m: progress(p / 100.0, m), cancel=cancel)

            def done(match: MatchData, _auto: bool = auto) -> None:
                self._on_analyzed(match, _auto)

            self.queue.add("analizar", title, run, on_done=done)
            queued += 1
        if queued:  # si solo se abrieron proyectos anteriores, se queda en Revisión
            self.go(3)

    def _on_analyzed(self, match: MatchData, auto: bool) -> None:
        if auto:
            self._auto_build_project(match)
            return
        if self.stack.currentIndex() == 1 and self.wizard.match is not None and self.wizard.match is not match:
            self._pending_matches.append(match)
            self.statusBar().showMessage(f"Demo analizada ({match.map_name}); se mostrará al terminar el asistente actual.", 8000)
            return
        self.wizard.load_match(match)
        self.go(1)
        self.show_from_tray()

    def _detection_settings(self, kinds: list[str]) -> DetectionSettings:
        det = from_dict(DetectionSettings, to_dict(self.state.config.detection))
        det.enabled_kinds = kinds
        return det

    def _on_wizard_finished(self, result: WizardResult) -> None:
        match = self.wizard.match
        if not match:
            return
        cfg = self.state.config
        if result.remember_player:
            cfg.player.steamid64 = result.steamid
            cfg.player.name = result.player_name
        cfg.ui.last_wizard = {"kinds": result.kinds, "duration": result.duration}
        style = from_dict(StyleSettings, {**to_dict(cfg.style), **result.style})
        style.aspect = "9:16" if result.export_preset.startswith("shorts") else "16:9"
        cfg.style = style
        cfg.export.preset = result.export_preset
        self.state.save()
        det = self._detection_settings(result.kinds)
        highlights = detect_all(match, result.steamid, det, cfg.scoring)
        if not highlights:
            dialogs.show_info(self, "Sin jugadas", f"{result.player_name} no tiene jugadas de los tipos elegidos en esta demo.\nPrueba a marcar más tipos (por ejemplo «Todas las kills»).")
            return
        chosen = select_by_duration(highlights, match.tickrate, result.duration)
        project = new_project(match, result.steamid, result.player_name, chosen, style)
        project.duration_target = result.duration
        project.export_preset = result.export_preset
        project.recording_mode = result.recording_mode
        project.existing_recording = result.existing_recording
        project.existing_recording_offset = result.existing_offset
        project.wizard = {"kinds": result.kinds, "duration": result.duration}
        try:
            project.save()
        except OSError as exc:
            dialogs.show_error(self, "No se pudo guardar el proyecto", str(exc))
        self.state.history.add(
            HistoryEntry(
                demo_path=match.demo_path,
                fingerprint=demo_fingerprint(Path(match.demo_path)),
                map_name=match.map_name,
                player_name=result.player_name,
                score=match.score_label(),
                processed_at=project.created_at,
                project_path=project.path,
            )
        )
        self.state.set_project(project)
        self.go(2)
        self.statusBar().showMessage(f"{len(highlights)} jugadas detectadas, {len(chosen)} seleccionadas para {result.duration}.", 8000)
        if self._pending_matches:
            nxt = self._pending_matches.pop(0)
            QTimer.singleShot(400, lambda: self._show_wizard_for(nxt))

    def _show_wizard_for(self, match: MatchData) -> None:
        self.wizard.load_match(match)
        self.go(1)

    def open_project(self, path: str) -> None:
        try:
            project = Project.load(Path(path))
        except (OSError, ValueError, TypeError, AttributeError, KeyError) as exc:  # fichero dañado o de otra cosa
            dialogs.show_error(self, "No se pudo abrir el proyecto", str(exc))
            return
        self.state.set_project(project)
        self.go(2)

    # ---------------------------------------------------------- record ------

    def _ask_manual_from_worker(self, text: str) -> bool:
        holder: dict[str, Any] = {"event": threading.Event(), "result": False}
        self.bridge.ask_manual.emit(text, holder)
        holder["event"].wait()
        return bool(holder["result"])

    def _on_ask_manual(self, text: str, holder: dict[str, Any]) -> None:
        dlg = dialogs.ManualStepDialog(text, self)
        holder["result"] = dlg.exec() == dlg.DialogCode.Accepted
        holder["event"].set()

    def _ask_yes_no_from_worker(self, text: str) -> bool:
        holder: dict[str, Any] = {"event": threading.Event(), "result": False}
        self.bridge.ask_yes_no.emit(text, holder)
        holder["event"].wait()
        return bool(holder["result"])

    def _on_ask_yes_no(self, text: str, holder: dict[str, Any]) -> None:
        self.show_from_tray()
        holder["result"] = dialogs.ask_yes_no(self, "Counter-Strike 2", text)
        holder["event"].set()

    def _make_recorder(self) -> Recorder:
        return Recorder(self.state.config, ask_user=self._ask_manual_from_worker, ask_yes_no=self._ask_yes_no_from_worker)

    def start_recording(self, then_export: bool = False) -> None:
        project = self.state.project
        if not project:
            return
        if project.recording_mode == "existing":
            dialogs.show_info(self, "Grabación existente", "Este proyecto usa un vídeo ya grabado; no hace falta grabar.")
            return
        if not project.enabled_clips():
            dialogs.show_info(self, "Nada que grabar", "Activa al menos una jugada.")
            return
        recorder = self._make_recorder()

        def run(progress, cancel):  # type: ignore[no-untyped-def]
            recorder.cancel = cancel
            recorder.on_clip_done = lambda _c: None
            return recorder.record_project(project, lambda msg, frac: progress(frac, msg))

        def done(session):  # type: ignore[no-untyped-def]
            self.state.autosave()
            self.review.load_project()
            ok = session.done
            total = len(session.jobs)
            self.state.save()  # guarda latencias/ajustes que haya tocado el grabador
            if ok < total:
                failed = [j for j in session.jobs if j.result is None]
                detail = "\n".join(f"• Ronda {j.clip.highlight.round} ({j.clip.highlight.label}): {j.error}" for j in failed)
                dialogs.show_error(
                    self,
                    "Algunos clips no se grabaron",
                    f"{ok}/{total} clips grabados. Los fallidos aparecen en rojo en Revisión con el motivo; pulsa «Crear vídeo» para reintentar solo esos.",
                    detail,
                )
            elif then_export:
                self.create_video()
            else:
                dialogs.show_info(self, "Grabación terminada", f"{ok}/{total} clips grabados. Revisa las vistas previas y pulsa «Crear vídeo».")

        self.queue.add("grabar", f"Grabar {len(project.enabled_clips())} jugadas con OBS", run, on_done=done)
        self.go(3)

    def test_recording(self) -> None:
        project = self.state.project
        if not project:
            dialogs.show_info(self, "Probar grabación", "Primero analiza una demo (arrástrala en Inicio) para poder grabar un clip de prueba.")
            return
        recorder = self._make_recorder()

        def run(progress, cancel):  # type: ignore[no-untyped-def]
            recorder.cancel = cancel
            return recorder.calibrate(project, lambda msg, frac: progress(frac, msg))

        def done(result):  # type: ignore[no-untyped-def]
            latency, path = result
            self.state.save()
            self.settings.load()
            self.export_page.preview.load(path, autoplay=True)
            dialogs.show_info(self, "Calibración completada", f"Latencia medida: {latency:.2f} s (guardada en Ajustes → CS2).\nClip de prueba: {path}\nComprueba en la vista previa que la cámara sigue al jugador correcto.")

        self.queue.add("calibrar", "Probar grabación y calibrar", run, on_done=done)
        self.go(3)

    # ---------------------------------------------------------- export ------

    def create_video(self) -> None:
        project = self.state.project
        if not project:
            return
        enabled = project.enabled_clips()
        if not enabled:
            dialogs.show_info(self, "Nada que exportar", "Activa al menos una jugada.")
            return
        if project.recording_mode != "existing":
            missing = [c for c in enabled if not c.is_recorded]
            if missing:
                if dialogs.ask_yes_no(self, "Faltan grabaciones", f"{len(missing)} de {len(enabled)} jugadas no están grabadas.\n¿Grabarlas ahora con OBS y crear el vídeo al terminar?"):
                    self.start_recording(then_export=True)
                return
        elif not project.existing_recording or not Path(project.existing_recording).exists():
            dialogs.show_error(self, "Vídeo no encontrado", "El vídeo de la partida no existe. Elige otro en el asistente.")
            return
        exporter = Exporter(self.state.config, self.state.ffmpeg)

        def run(progress, cancel):  # type: ignore[no-untyped-def]
            exporter.cancel = cancel
            return exporter.export(project, progress=lambda f, m: progress(f, m))

        self.queue.add("exportar", f"Crear vídeo: {project.name}", run, on_done=lambda res: self._on_exported(project, res))
        self.go(3)

    def _on_exported(self, project: Project, result: ExportResult) -> None:
        cfg = self.state.config
        self.state.autosave()
        meta = suggest_metadata(project.match, project.player_name, [c.highlight for c in project.enabled_clips()], project.style.channel_name, cfg.youtube.default_tags)
        self.export_page.show_result(result.video, result.thumbnail, result.duration, meta.title, meta.description, meta.tags)
        self.state.history.update_output(project.match.demo_path, str(result.video))
        self.go(3)
        if result.skipped:
            where = "no están dentro del vídeo de la partida (revisa el desfase)" if project.recording_mode == "existing" else "quedaban demasiado cortas tras recortar"
            dialogs.show_info(
                self,
                "Jugadas omitidas",
                f"El vídeo se creó, pero {len(result.skipped)} jugada(s) {where}:" + "".join(f"\n• {s}" for s in result.skipped),
            )
        if cfg.export.notify_when_done:
            notify("ClutchReel", f"Vídeo listo: {result.video.name}")
        if cfg.export.open_folder_when_done:
            paths.open_in_explorer(result.video)
        if cfg.export.shutdown_when_done and not self.queue.pending():
            if shutdown_windows(60):
                self.statusBar().showMessage("El PC se apagará en 60 s (ejecuta «shutdown /a» para cancelar).", 60000)

    def upload_to_youtube(self, video: str, title: str, description: str, tags: list[str]) -> None:
        cfg = self.state.config
        if not cfg.youtube.enabled or not cfg.youtube.client_secrets_path:
            dialogs.show_info(self, "YouTube no configurado", "Activa YouTube en Ajustes e indica el fichero client_secrets.json (ver README).")
            return
        thumb = Path(video).with_suffix(".jpg")

        def run(progress, cancel):  # type: ignore[no-untyped-def]
            return upload_video(cfg.youtube.client_secrets_path, Path(video), title, description, tags, cfg.youtube.default_privacy, thumb if thumb.exists() else None, progress=lambda f, m: progress(f, m))

        self.queue.add("subir", f"Subir a YouTube: {Path(video).name}", run, on_done=lambda vid: dialogs.show_info(self, "Subido", f"Vídeo subido como {cfg.youtube.default_privacy}: https://youtu.be/{vid}"))

    # ------------------------------------------------------- auto mode ------

    def set_auto_mode(self, enabled: bool) -> None:
        cfg = self.state.config
        cfg.watcher.enabled = enabled
        self.state.save()
        if self.tray is not None:
            act = getattr(self.tray, "auto_action", None)
            if act is not None:
                act.blockSignals(True)
                act.setChecked(enabled)
                act.blockSignals(False)
        if self.watcher:
            self.watcher.stop()
            self.watcher = None
        if enabled:
            folders = [Path(cfg.paths.demo_folder)] if cfg.paths.demo_folder else paths.cs2_demo_dirs()
            folders += [Path(p) for p in cfg.paths.extra_demo_folders if p]
            if not folders:
                dialogs.show_info(self, "Modo automático", "No se encontró la carpeta de demos. Configúrala en Ajustes → Rutas.")
                cfg.watcher.enabled = False
                self.state.save()
                self.home.refresh()
                return
            self.watcher = DemoWatcher(folders, lambda p: self.bridge.new_demo.emit(str(p)))
            self.watcher.start()
            self.statusBar().showMessage(f"Modo automático activo: vigilando {folders[0]}", 8000)
        self.home.refresh()

    def _on_new_demo(self, path: str) -> None:
        demo = Path(path)
        if self.state.history.find(demo):
            return
        notify("ClutchReel", f"Demo nueva detectada: {demo.name}. Procesando…")
        self.analyze_demos([demo], auto=True)

    def _auto_build_project(self, match: MatchData) -> None:
        cfg = self.state.config
        if cfg.watcher.profile_name in cfg.profiles:
            self.state.store.apply_profile(cfg.watcher.profile_name)
        sid = cfg.player.steamid64
        if not match.player_by_steamid(sid):
            sid = self.wizard._detect_player(match)  # 0 si tu cuenta no está en la demo: se omite, no se adivina
        player = match.player_by_steamid(sid) if sid else None
        if not player:
            notify("ClutchReel", "No se encontró tu jugador en la demo; se omite.")
            return
        kinds = cfg.ui.last_wizard.get("kinds") or cfg.detection.enabled_kinds
        duration = cfg.ui.last_wizard.get("duration") or "3-5 min"
        highlights = detect_all(match, sid, self._detection_settings(list(kinds)), cfg.scoring)
        if not highlights:
            notify("ClutchReel", f"Sin jugadas destacadas de {player.name} en {match.map_name}.")
            return
        chosen = select_by_duration(highlights, match.tickrate, str(duration))
        project = new_project(match, sid, player.name, chosen, cfg.style)
        project.duration_target = str(duration)
        project.export_preset = cfg.export.preset
        try:
            project.save()
        except OSError:
            pass
        self.state.history.add(HistoryEntry(match.demo_path, demo_fingerprint(Path(match.demo_path)), match.map_name, player.name, match.score_label(), project.created_at, project.path))
        self.state.set_project(project)
        if cfg.watcher.auto_record:
            self.start_recording(then_export=cfg.watcher.auto_export)
        elif cfg.watcher.auto_export:
            self.create_video()

    # ------------------------------------------------------------ close -----

    def show_from_tray(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_app(self) -> None:
        self._quitting = True
        self.close()

    def closeEvent(self, event: QCloseEvent) -> None:
        cfg = self.state.config
        if not self._quitting and cfg.ui.minimize_to_tray and self.tray is not None and (self.queue.busy or self.watcher):
            self.hide()
            if self.queue.busy:
                notify("ClutchReel", "Sigo trabajando en segundo plano. Ábreme desde la bandeja.")
            event.ignore()
            return
        if self.queue.busy and not dialogs.ask_yes_no(self, "Trabajo en curso", "Hay un trabajo en curso. ¿Cancelarlo y salir?"):
            event.ignore()
            self._quitting = False
            return
        self.queue.cancel_pending()
        self.state.pool.cancel_all()
        if self.watcher:
            self.watcher.stop()
        self.review.flush_save()
        self.state.autosave()
        cfg.ui.window_geometry = bytes(self.saveGeometry().toBase64().data()).decode("ascii")
        self.state.save()
        if self.state.pool.busy:
            # Una grabación cancelada todavía tiene que parar OBS y devolver CS2 a su estado: se le da tiempo
            # (antes, a los 6 s la app salía y OBS se quedaba grabando).
            self.statusBar().showMessage("Cancelando el trabajo en curso (parando OBS y restaurando CS2)…")
            self.setEnabled(False)
            self.state.pool.wait_all(45000, keep_alive=QApplication.processEvents)
        if self.tray is not None:
            self.tray.hide()
        event.accept()
        app = QApplication.instance()
        if app is not None:
            app.quit()
