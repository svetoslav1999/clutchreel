"""Panel de Ajustes."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from clutchreel.core.export.builder import PRESETS
from clutchreel.ui.dialogs import run_obs_autoconfig
from clutchreel.ui.state import AppState
from clutchreel.ui.widgets.iconbutton import icon_button
from clutchreel.utils import paths


class PathRow(QWidget):
    def __init__(self, placeholder: str, folder: bool = True, filter_: str = "") -> None:
        super().__init__()
        self.folder = folder
        self.filter = filter_
        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(placeholder)
        btn = QPushButton("…")
        btn.setFixedWidth(36)
        btn.clicked.connect(self._browse)
        layout.addWidget(self.edit, 1)
        layout.addWidget(btn)

    def _browse(self) -> None:
        if self.folder:
            d = QFileDialog.getExistingDirectory(self, "Elegir carpeta", self.edit.text() or str(Path.home()))
            if d:
                self.edit.setText(d)
        else:
            f, _ = QFileDialog.getOpenFileName(self, "Elegir archivo", self.edit.text() or str(Path.home()), self.filter or "Todos (*)")
            if f:
                self.edit.setText(f)

    def text(self) -> str:
        return self.edit.text().strip()

    def set_text(self, value: str) -> None:
        self.edit.setText(value)


class SettingsPage(QWidget):
    diagnostics_requested = Signal()
    test_recording_requested = Signal()
    logs_requested = Signal()
    theme_changed = Signal(str)

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        root = QVBoxLayout(self)
        root.setContentsMargins(24, 20, 24, 20)
        head = QHBoxLayout()
        title = QLabel("Ajustes")
        title.setObjectName("title")
        head.addWidget(title)
        head.addStretch()
        btn_diag = icon_button("Diagnóstico", "health")
        btn_diag.clicked.connect(self.diagnostics_requested.emit)
        btn_test = icon_button("Probar grabación (calibrar)", "record")
        btn_test.clicked.connect(self.test_recording_requested.emit)
        btn_logs = icon_button("Ver registro", "log")
        btn_logs.clicked.connect(self.logs_requested.emit)
        head.addWidget(btn_diag)
        head.addWidget(btn_test)
        head.addWidget(btn_logs)
        root.addLayout(head)
        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self._build_player_tab()
        self._build_paths_tab()
        self._build_obs_tab()
        self._build_cs2_tab()
        self._build_quality_tab()
        self._build_youtube_tab()
        self._build_auto_tab()
        self._build_ui_tab()
        self._saving = False
        self.state.config_changed.connect(self._on_config_changed)
        foot = QHBoxLayout()
        foot.addStretch()
        self.btn_save = QPushButton("Guardar ajustes")
        self.btn_save.setObjectName("primary")
        self.btn_save.clicked.connect(self.save)
        foot.addWidget(self.btn_save)
        root.addLayout(foot)
        self.load()

    # ------------------------------------------------------------- tabs -----

    def _build_player_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.edt_steamid = QLineEdit()
        self.edt_steamid.setPlaceholderText("SteamID64 (7656…)")
        self.edt_player_name = QLineEdit()
        self.cmb_steam_accounts = QComboBox()
        self.cmb_steam_accounts.addItem("— Cuentas de Steam detectadas —", 0)
        for sid, name, recent in paths.steam_logged_accounts():
            self.cmb_steam_accounts.addItem(f"{name} ({sid}){' · reciente' if recent else ''}", sid)
        self.cmb_steam_accounts.currentIndexChanged.connect(self._pick_account)
        form.addRow("Cuenta de Steam", self.cmb_steam_accounts)
        form.addRow("SteamID64", self.edt_steamid)
        form.addRow("Nombre", self.edt_player_name)
        self.tabs.addTab(w, "Jugador")

    def _build_paths_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.row_demos = PathRow("Carpeta de demos (vacío = detectar en CS2)")
        self.row_output = PathRow("Carpeta de salida de vídeos")
        self.row_ffmpeg = PathRow("ffmpeg.exe (vacío = detectar)", folder=False, filter_="ffmpeg.exe (ffmpeg.exe)")
        self.row_obs = PathRow("obs64.exe (vacío = detectar)", folder=False, filter_="obs64.exe (obs64.exe)")
        self.row_cs2 = PathRow("Carpeta «Counter-Strike Global Offensive» (vacío = detectar)")
        self.row_music = PathRow("Carpeta de música")
        form.addRow("Demos", self.row_demos)
        form.addRow("Salida", self.row_output)
        form.addRow("FFmpeg", self.row_ffmpeg)
        form.addRow("OBS", self.row_obs)
        form.addRow("CS2", self.row_cs2)
        form.addRow("Música", self.row_music)
        self.lbl_detected = QLabel("")
        self.lbl_detected.setObjectName("muted")
        self.lbl_detected.setWordWrap(True)
        form.addRow("Detectado", self.lbl_detected)
        self.tabs.addTab(w, "Rutas")

    def _build_obs_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.edt_obs_host = QLineEdit()
        self.spn_obs_port = QSpinBox()
        self.spn_obs_port.setRange(1, 65535)
        self.edt_obs_pass = QLineEdit()
        self.edt_obs_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self.cmb_capture = QComboBox()
        self.cmb_capture.addItem("Game Capture (recomendado)", "game")
        self.cmb_capture.addItem("Window Capture", "window")
        self.cmb_capture.addItem("Display Capture", "display")
        self.cmb_rec_format = QComboBox()
        self.cmb_rec_format.addItems(["mkv", "mp4", "mov"])
        self.spn_obs_w = QSpinBox()
        self.spn_obs_w.setRange(640, 7680)
        self.spn_obs_h = QSpinBox()
        self.spn_obs_h.setRange(360, 4320)
        self.spn_obs_fps = QSpinBox()
        self.spn_obs_fps.setRange(24, 240)
        self.chk_obs_launch = QCheckBox("Abrir OBS automáticamente si está cerrado")
        self.chk_obs_scene = QCheckBox("Crear/gestionar la escena «ClutchReel» en OBS")
        self.chk_obs_video = QCheckBox("Fijar resolución y FPS de OBS desde aquí")
        form.addRow("Host", self.edt_obs_host)
        form.addRow("Puerto WebSocket", self.spn_obs_port)
        form.addRow("Contraseña", self.edt_obs_pass)
        form.addRow("Captura", self.cmb_capture)
        form.addRow("Formato de grabación", self.cmb_rec_format)
        form.addRow("Ancho", self.spn_obs_w)
        form.addRow("Alto", self.spn_obs_h)
        form.addRow("FPS", self.spn_obs_fps)
        form.addRow(self.chk_obs_launch)
        form.addRow(self.chk_obs_scene)
        form.addRow(self.chk_obs_video)
        btn_auto = QPushButton("Configurar OBS automáticamente")
        btn_auto.setToolTip("Activa el WebSocket de OBS con puerto y contraseña nuevos, los guarda aquí y reabre OBS (avisa antes de cerrarlo).")
        btn_auto.clicked.connect(self._autoconfig_obs)
        form.addRow(btn_auto)
        hint = QLabel("La contraseña se rellena sola desde la configuración de OBS si existe. OBS 28+ incluye obs-websocket.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.tabs.addTab(w, "OBS")

    def _build_cs2_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.edt_launch = QLineEdit()
        self.chk_netcon = QCheckBox("Usar puerto de consola (-netconport)")
        self.spn_netcon = QSpinBox()
        self.spn_netcon.setRange(1024, 65535)
        self.chk_tools = QCheckBox("Añadir -tools (no recomendado: con CS2 1.41 cierra el juego al saltar en la demo)")
        self.edt_hud = QLineEdit()
        self.edt_hud.setToolTip("Variables de consola para grabar (separadas por «;»). Se restauran al terminar.")
        self.spn_load_wait = QDoubleSpinBox()
        self.spn_load_wait.setRange(3, 180)
        self.spn_seek_wait = QDoubleSpinBox()
        self.spn_seek_wait.setRange(0.5, 60)
        self.spn_latency = QDoubleSpinBox()
        self.spn_latency.setRange(0, 5)
        self.spn_latency.setDecimals(2)
        self.spn_latency.setSingleStep(0.05)
        self.spn_start_offset = QDoubleSpinBox()
        self.spn_start_offset.setRange(-5, 5)
        self.spn_start_offset.setDecimals(2)
        self.spn_start_offset.setSingleStep(0.1)
        self.chk_keyboard = QCheckBox("Si el puerto no responde, teclear comandos en la consola del juego")
        self.chk_cfg = QCheckBox("Usar fichero cfg (exec clutchreel) al teclear")
        self.chk_copy_demo = QCheckBox("Copiar la demo a la carpeta replays del juego (si playdemo no acepta rutas)")
        self.chk_close_game = QCheckBox("Cerrar CS2 al terminar de grabar")
        self.spn_win_w = QSpinBox()
        self.spn_win_w.setRange(0, 7680)
        self.spn_win_h = QSpinBox()
        self.spn_win_h.setRange(0, 4320)
        form.addRow("Opciones de lanzamiento", self.edt_launch)
        form.addRow(self.chk_netcon)
        form.addRow("Puerto de consola", self.spn_netcon)
        form.addRow(self.chk_tools)
        form.addRow("Comandos de HUD", self.edt_hud)
        form.addRow("Espera carga demo (s)", self.spn_load_wait)
        form.addRow("Espera tras buscar tick (s)", self.spn_seek_wait)
        form.addRow("Latencia medida (s)", self.spn_latency)
        form.addRow("Ajuste manual de inicio (s)", self.spn_start_offset)
        form.addRow("Ventana forzada ancho/alto (0 = no)", self._pair(self.spn_win_w, self.spn_win_h))
        form.addRow(self.chk_keyboard)
        form.addRow(self.chk_cfg)
        form.addRow(self.chk_copy_demo)
        form.addRow(self.chk_close_game)
        hint = QLabel("Se añade siempre -insecure (sin VAC) y solo se usan comandos normales del visor de demos. Pulsa «Probar grabación» para medir la latencia.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.tabs.addTab(w, "CS2")

    def _build_quality_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.cmb_preset = QComboBox()
        for key, p in PRESETS.items():
            self.cmb_preset.addItem(str(p["label"]), key)
        self.cmb_codec = QComboBox()
        self.cmb_codec.addItem("H.264 (compatible)", "h264")
        self.cmb_codec.addItem("HEVC / H.265 (más pequeño)", "hevc")
        self.cmb_hw = QComboBox()
        for label, key in (("Automático", "auto"), ("NVIDIA NVENC", "nvenc"), ("AMD AMF", "amf"), ("Intel QSV", "qsv"), ("CPU", "cpu")):
            self.cmb_hw.addItem(label, key)
        self.cmb_quality = QComboBox()
        self.cmb_quality.addItems(["alta", "media", "baja"])
        self.spn_bitrate = QSpinBox()
        self.spn_bitrate.setRange(0, 200000)
        self.spn_bitrate.setSuffix(" kbps (0 = auto)")
        self.chk_loudnorm = QCheckBox("Normalizar audio (loudnorm, -14 LUFS)")
        self.chk_thumb = QCheckBox("Generar miniatura automática")
        self.chk_open = QCheckBox("Abrir la carpeta al terminar")
        self.chk_notify = QCheckBox("Notificación de Windows al terminar")
        self.chk_shutdown = QCheckBox("Apagar el PC al terminar la cola")
        self.spn_pre = QDoubleSpinBox()
        self.spn_pre.setRange(0, 15)
        self.spn_post = QDoubleSpinBox()
        self.spn_post.setRange(0, 15)
        self.spn_window = QDoubleSpinBox()
        self.spn_window.setRange(2, 60)
        self.spn_merge = QDoubleSpinBox()
        self.spn_merge.setRange(0, 30)
        form.addRow("Preset", self.cmb_preset)
        form.addRow("Códec", self.cmb_codec)
        form.addRow("Aceleración", self.cmb_hw)
        form.addRow("Calidad", self.cmb_quality)
        form.addRow("Bitrate", self.spn_bitrate)
        form.addRow(self.chk_loudnorm)
        form.addRow(self.chk_thumb)
        form.addRow(self.chk_open)
        form.addRow(self.chk_notify)
        form.addRow(self.chk_shutdown)
        form.addRow("Margen antes de la jugada (s)", self.spn_pre)
        form.addRow("Margen después (s)", self.spn_post)
        form.addRow("Ventana multikill (s)", self.spn_window)
        form.addRow("Fusionar jugadas a menos de (s)", self.spn_merge)
        self.tabs.addTab(w, "Calidad y detección")

    def _build_youtube_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.chk_yt = QCheckBox("Activar subida a YouTube")
        self.row_secrets = PathRow("client_secrets.json", folder=False, filter_="JSON (*.json)")
        self.cmb_privacy = QComboBox()
        self.cmb_privacy.addItem("Privado (borrador)", "private")
        self.cmb_privacy.addItem("Oculto", "unlisted")
        self.cmb_privacy.addItem("Público", "public")
        self.edt_tags = QLineEdit()
        form.addRow(self.chk_yt)
        form.addRow("Credenciales OAuth", self.row_secrets)
        form.addRow("Privacidad por defecto", self.cmb_privacy)
        form.addRow("Etiquetas por defecto", self.edt_tags)
        hint = QLabel("Cómo crear las credenciales: ver README.md → «Subida a YouTube». Sin ellas, la app funciona igual.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        form.addRow(hint)
        self.tabs.addTab(w, "YouTube")

    def _build_auto_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.chk_watch = QCheckBox("Vigilar la carpeta de demos al abrir la app")
        self.cmb_profile = QComboBox()
        self.chk_auto_record = QCheckBox("Grabar automáticamente con OBS")
        self.chk_auto_export = QCheckBox("Exportar automáticamente")
        form.addRow(self.chk_watch)
        form.addRow("Perfil a usar", self.cmb_profile)
        form.addRow(self.chk_auto_record)
        form.addRow(self.chk_auto_export)
        self.tabs.addTab(w, "Modo automático")

    def _build_ui_tab(self) -> None:
        w = QWidget()
        form = QFormLayout(w)
        self.cmb_theme = QComboBox()
        self.cmb_theme.addItems(["oscuro", "claro"])
        self.cmb_lang = QComboBox()
        self.cmb_lang.addItem("Español (España)", "es")
        self.chk_tray = QCheckBox("Minimizar a la bandeja al cerrar la ventana")
        form.addRow("Tema", self.cmb_theme)
        form.addRow("Idioma de textos", self.cmb_lang)
        form.addRow(self.chk_tray)
        self.tabs.addTab(w, "Apariencia")

    @staticmethod
    def _pair(a: QWidget, b: QWidget) -> QWidget:
        w = QWidget()
        lay = QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(a)
        lay.addWidget(b)
        return w

    # ------------------------------------------------------------- data -----

    def _autoconfig_obs(self) -> None:
        if run_obs_autoconfig(self, self.state.store):
            self.state.config_changed.emit()

    def _pick_account(self) -> None:
        sid = self.cmb_steam_accounts.currentData()
        if sid:
            self.edt_steamid.setText(str(sid))
            text = self.cmb_steam_accounts.currentText()
            self.edt_player_name.setText(text.split(" (")[0])

    def load(self) -> None:
        c = self.state.config
        self.edt_steamid.setText(str(c.player.steamid64) if c.player.steamid64 else "")
        self.edt_player_name.setText(c.player.name)
        self.row_demos.set_text(c.paths.demo_folder)
        self.row_output.set_text(c.paths.output_folder)
        self.row_ffmpeg.set_text(c.paths.ffmpeg_path)
        self.row_obs.set_text(c.paths.obs_path)
        self.row_cs2.set_text(c.paths.cs2_path)
        self.row_music.set_text(c.paths.music_folder)
        det = [
            f"Steam: {paths.steam_dir() or 'no encontrado'}",
            f"CS2: {paths.cs2_dir() or 'no encontrado'}",
            f"Demos: {', '.join(str(d) for d in paths.cs2_demo_dirs()) or 'no encontradas'}",
            f"OBS: {paths.obs_exe() or 'no encontrado'}",
            f"FFmpeg: {paths.find_ffmpeg(c.paths.ffmpeg_path) or 'no encontrado'}",
        ]
        self.lbl_detected.setText("\n".join(det))
        self.edt_obs_host.setText(c.obs.host)
        self.spn_obs_port.setValue(c.obs.port)
        self.edt_obs_pass.setText(c.obs.password)
        self.cmb_capture.setCurrentIndex(max(0, self.cmb_capture.findData(c.obs.capture_mode)))
        self.cmb_rec_format.setCurrentText(c.obs.recording_format)
        self.spn_obs_w.setValue(c.obs.width)
        self.spn_obs_h.setValue(c.obs.height)
        self.spn_obs_fps.setValue(c.obs.fps)
        self.chk_obs_launch.setChecked(c.obs.auto_launch)
        self.chk_obs_scene.setChecked(c.obs.manage_scene)
        self.chk_obs_video.setChecked(c.obs.manage_video_settings)
        self.edt_launch.setText(c.cs2.launch_options)
        self.chk_netcon.setChecked(c.cs2.use_netconport)
        self.spn_netcon.setValue(c.cs2.netcon_port)
        self.chk_tools.setChecked(c.cs2.netcon_tools_workaround)
        self.edt_hud.setText(c.cs2.hud_commands)
        self.spn_load_wait.setValue(c.cs2.demo_load_wait)
        self.spn_seek_wait.setValue(c.cs2.seek_wait)
        self.spn_latency.setValue(c.cs2.command_latency)
        self.spn_start_offset.setValue(c.cs2.start_offset)
        self.chk_keyboard.setChecked(c.cs2.keyboard_fallback)
        self.chk_cfg.setChecked(c.cs2.cfg_fallback)
        self.chk_copy_demo.setChecked(c.cs2.copy_demo_to_game)
        self.chk_close_game.setChecked(c.cs2.close_game_when_done)
        self.spn_win_w.setValue(c.cs2.window_width)
        self.spn_win_h.setValue(c.cs2.window_height)
        self.cmb_preset.setCurrentIndex(max(0, self.cmb_preset.findData(c.export.preset)))
        self.cmb_codec.setCurrentIndex(max(0, self.cmb_codec.findData(c.export.codec)))
        self.cmb_hw.setCurrentIndex(max(0, self.cmb_hw.findData(c.export.hw_accel)))
        self.cmb_quality.setCurrentText(c.export.quality)
        self.spn_bitrate.setValue(c.export.bitrate_kbps)
        self.chk_loudnorm.setChecked(c.export.loudnorm)
        self.chk_thumb.setChecked(c.export.thumbnail)
        self.chk_open.setChecked(c.export.open_folder_when_done)
        self.chk_notify.setChecked(c.export.notify_when_done)
        self.chk_shutdown.setChecked(c.export.shutdown_when_done)
        self.spn_pre.setValue(c.detection.pre_roll)
        self.spn_post.setValue(c.detection.post_roll)
        self.spn_window.setValue(c.detection.multikill_window)
        self.spn_merge.setValue(c.detection.merge_gap)
        self.chk_yt.setChecked(c.youtube.enabled)
        self.row_secrets.set_text(c.youtube.client_secrets_path)
        self.cmb_privacy.setCurrentIndex(max(0, self.cmb_privacy.findData(c.youtube.default_privacy)))
        self.edt_tags.setText(", ".join(c.youtube.default_tags))
        self.chk_watch.setChecked(c.watcher.enabled)
        self.cmb_profile.clear()
        for name in c.profiles:
            self.cmb_profile.addItem(name)
        self.cmb_profile.setCurrentText(c.watcher.profile_name)
        self.chk_auto_record.setChecked(c.watcher.auto_record)
        self.chk_auto_export.setChecked(c.watcher.auto_export)
        self.cmb_theme.setCurrentText(c.ui.theme)
        self.chk_tray.setChecked(c.ui.minimize_to_tray)

    def _on_config_changed(self) -> None:
        if not self._saving:
            self.load()

    def save(self) -> None:
        self._saving = True
        try:
            self._save_impl()
        finally:
            self._saving = False

    def _save_impl(self) -> None:
        c = self.state.config
        try:
            c.player.steamid64 = int(self.edt_steamid.text().strip() or 0)
        except ValueError:
            c.player.steamid64 = 0
        c.player.name = self.edt_player_name.text().strip()
        c.paths.demo_folder = self.row_demos.text()
        c.paths.output_folder = self.row_output.text() or str(paths.default_output_dir())
        c.paths.ffmpeg_path = self.row_ffmpeg.text()
        c.paths.obs_path = self.row_obs.text()
        c.paths.cs2_path = self.row_cs2.text()
        c.paths.music_folder = self.row_music.text()
        c.obs.host = self.edt_obs_host.text().strip() or "127.0.0.1"
        c.obs.port = self.spn_obs_port.value()
        c.obs.password = self.edt_obs_pass.text()
        c.obs.capture_mode = self.cmb_capture.currentData()
        c.obs.recording_format = self.cmb_rec_format.currentText()
        c.obs.width = self.spn_obs_w.value()
        c.obs.height = self.spn_obs_h.value()
        c.obs.fps = self.spn_obs_fps.value()
        c.obs.auto_launch = self.chk_obs_launch.isChecked()
        c.obs.manage_scene = self.chk_obs_scene.isChecked()
        c.obs.manage_video_settings = self.chk_obs_video.isChecked()
        c.cs2.launch_options = self.edt_launch.text().strip()
        c.cs2.use_netconport = self.chk_netcon.isChecked()
        c.cs2.netcon_port = self.spn_netcon.value()
        c.cs2.netcon_tools_workaround = self.chk_tools.isChecked()
        c.cs2.hud_commands = self.edt_hud.text().strip()
        c.cs2.demo_load_wait = self.spn_load_wait.value()
        c.cs2.seek_wait = self.spn_seek_wait.value()
        c.cs2.command_latency = self.spn_latency.value()
        c.cs2.start_offset = self.spn_start_offset.value()
        c.cs2.keyboard_fallback = self.chk_keyboard.isChecked()
        c.cs2.cfg_fallback = self.chk_cfg.isChecked()
        c.cs2.copy_demo_to_game = self.chk_copy_demo.isChecked()
        c.cs2.close_game_when_done = self.chk_close_game.isChecked()
        c.cs2.window_width = self.spn_win_w.value()
        c.cs2.window_height = self.spn_win_h.value()
        c.export.preset = self.cmb_preset.currentData()
        c.export.codec = self.cmb_codec.currentData()
        c.export.hw_accel = self.cmb_hw.currentData()
        c.export.quality = self.cmb_quality.currentText()
        c.export.bitrate_kbps = self.spn_bitrate.value()
        c.export.loudnorm = self.chk_loudnorm.isChecked()
        c.export.thumbnail = self.chk_thumb.isChecked()
        c.export.open_folder_when_done = self.chk_open.isChecked()
        c.export.notify_when_done = self.chk_notify.isChecked()
        c.export.shutdown_when_done = self.chk_shutdown.isChecked()
        c.detection.pre_roll = self.spn_pre.value()
        c.detection.post_roll = self.spn_post.value()
        c.detection.multikill_window = self.spn_window.value()
        c.detection.merge_gap = self.spn_merge.value()
        c.youtube.enabled = self.chk_yt.isChecked()
        c.youtube.client_secrets_path = self.row_secrets.text()
        c.youtube.default_privacy = self.cmb_privacy.currentData()
        c.youtube.default_tags = [t.strip() for t in self.edt_tags.text().split(",") if t.strip()]
        c.watcher.enabled = self.chk_watch.isChecked()
        c.watcher.profile_name = self.cmb_profile.currentText()
        c.watcher.auto_record = self.chk_auto_record.isChecked()
        c.watcher.auto_export = self.chk_auto_export.isChecked()
        theme_before = c.ui.theme
        c.ui.theme = self.cmb_theme.currentText()
        c.ui.minimize_to_tray = self.chk_tray.isChecked()
        self.state.save()
        if theme_before != c.ui.theme:
            self.theme_changed.emit(c.ui.theme)
        self.state.status_message.emit("Ajustes guardados.")
        self.load()
