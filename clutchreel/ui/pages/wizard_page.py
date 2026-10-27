"""Asistente de pocas preguntas tras analizar una demo (máx. 5 pasos)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QStackedWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from clutchreel.core.demo.models import KIND_LABELS, MatchData
from clutchreel.core.demo.selector import DURATION_PRESETS
from clutchreel.core.demo.stats import compute_stats
from clutchreel.core.editor.music import list_tracks
from clutchreel.core.export.builder import PRESETS
from clutchreel.core.export.metadata import pretty_map
from clutchreel.ui.state import AppState
from clutchreel.utils import paths

KIND_ORDER = ["ace", "4k", "3k", "2k", "clutch", "headshot_streak", "entry", "awp", "noscope", "wallbang", "smoke", "blind", "air", "knife", "decisive", "best_round", "all_kills"]
RECOMMENDED_KINDS = ["ace", "4k", "3k", "2k", "clutch", "headshot_streak", "entry", "noscope", "wallbang", "smoke", "blind", "air", "knife", "decisive"]


@dataclass
class WizardResult:
    steamid: int
    player_name: str
    kinds: list[str]
    duration: str
    style: dict[str, Any]
    export_preset: str
    recording_mode: str
    existing_recording: str = ""
    existing_offset: float = 0.0
    remember_player: bool = True
    extra: dict[str, Any] = field(default_factory=dict)


class WizardPage(QWidget):
    finished = Signal(object)  # WizardResult
    cancelled = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self.match: MatchData | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(32, 24, 32, 24)
        root.setSpacing(14)
        self.lbl_header = QLabel("Asistente")
        self.lbl_header.setObjectName("title")
        root.addWidget(self.lbl_header)
        self.lbl_match = QLabel("")
        self.lbl_match.setObjectName("subtitle")
        self.lbl_match.setWordWrap(True)
        root.addWidget(self.lbl_match)
        self.lbl_step = QLabel("")
        self.lbl_step.setObjectName("muted")
        root.addWidget(self.lbl_step)
        self.stack = QStackedWidget()
        root.addWidget(self.stack, 1)
        self.stack.addWidget(self._build_player_step())
        self.stack.addWidget(self._build_kinds_step())
        self.stack.addWidget(self._build_duration_step())
        self.stack.addWidget(self._build_style_step())
        self.stack.addWidget(self._build_recording_step())

        nav = QHBoxLayout()
        self.btn_cancel = QPushButton("Cancelar")
        self.btn_cancel.clicked.connect(self.cancelled.emit)
        self.btn_recommended = QPushButton("✨ Usar recomendado y terminar")
        self.btn_recommended.setToolTip("Aplica los valores recomendados en todos los pasos y pasa a la revisión")
        self.btn_recommended.clicked.connect(self._use_recommended)
        self.btn_back = QPushButton("← Atrás")
        self.btn_back.clicked.connect(self._back)
        self.btn_next = QPushButton("Siguiente →")
        self.btn_next.setObjectName("primary")
        self.btn_next.clicked.connect(self._next)
        nav.addWidget(self.btn_cancel)
        nav.addStretch()
        nav.addWidget(self.btn_recommended)
        nav.addWidget(self.btn_back)
        nav.addWidget(self.btn_next)
        root.addLayout(nav)
        self._update_nav()

    # ----------------------------------------------------------- steps ------

    def _build_player_step(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("<b>1. ¿De qué jugador quieres las jugadas?</b>"))
        hint = QLabel("Se detecta automáticamente con tu cuenta de Steam. Doble clic para elegir otro.")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        self.lbl_player_warning = QLabel("")
        self.lbl_player_warning.setObjectName("warning")
        self.lbl_player_warning.setWordWrap(True)
        self.lbl_player_warning.hide()
        layout.addWidget(self.lbl_player_warning)
        self.tbl_players = QTableWidget(0, 7)
        self.tbl_players.setHorizontalHeaderLabels(["Jugador", "Equipo", "K", "D", "A", "HS %", "ADR"])
        self.tbl_players.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.tbl_players.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.tbl_players.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.tbl_players.verticalHeader().setVisible(False)
        self.tbl_players.horizontalHeader().setStretchLastSection(True)
        self.tbl_players.itemDoubleClicked.connect(lambda _i: self._next())
        layout.addWidget(self.tbl_players, 1)
        self.chk_remember = QCheckBox("Recordar este jugador para las próximas demos")
        self.chk_remember.setChecked(True)
        layout.addWidget(self.chk_remember)
        return w

    def _build_kinds_step(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("<b>2. ¿Qué quieres sacar?</b>"))
        grid = QGridLayout()
        grid.setHorizontalSpacing(24)
        self.kind_checks: dict[str, QCheckBox] = {}
        for i, kind in enumerate(KIND_ORDER):
            cb = QCheckBox(KIND_LABELS.get(kind, kind))
            cb.setChecked(kind in RECOMMENDED_KINDS)
            self.kind_checks[kind] = cb
            grid.addWidget(cb, i // 3, i % 3)
        layout.addLayout(grid)
        row = QHBoxLayout()
        b_all = QPushButton("Marcar todo")
        b_all.clicked.connect(lambda: self._set_kinds(list(self.kind_checks)))
        b_rec = QPushButton("Recomendado")
        b_rec.clicked.connect(lambda: self._set_kinds(RECOMMENDED_KINDS))
        b_none = QPushButton("Desmarcar todo")
        b_none.clicked.connect(lambda: self._set_kinds([]))
        row.addWidget(b_rec)
        row.addWidget(b_all)
        row.addWidget(b_none)
        row.addStretch()
        layout.addLayout(row)
        layout.addStretch()
        return w

    def _set_kinds(self, kinds: list[str]) -> None:
        for k, cb in self.kind_checks.items():
            cb.setChecked(k in kinds)

    def _build_duration_step(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("<b>3. ¿Cuánto debe durar el vídeo?</b>"))
        hint = QLabel("ClutchReel elegirá las mejores jugadas por puntuación hasta llenar esa duración.")
        hint.setObjectName("muted")
        layout.addWidget(hint)
        self.duration_radios: dict[str, QRadioButton] = {}
        for name in DURATION_PRESETS:
            rb = QRadioButton(name)
            self.duration_radios[name] = rb
            layout.addWidget(rb)
        self.duration_radios["3-5 min"].setChecked(True)
        layout.addStretch()
        return w

    def _build_style_step(self) -> QWidget:
        w = QWidget()
        outer = QVBoxLayout(w)
        outer.addWidget(QLabel("<b>4. Estilo del vídeo</b>"))
        area = QScrollArea()
        area.setWidgetResizable(True)
        inner = QWidget()
        layout = QGridLayout(inner)
        layout.setVerticalSpacing(10)
        st = self.state.config.style
        self.chk_music = QCheckBox("Música de fondo")
        self.chk_music.setChecked(st.music_enabled)
        self.cmb_music = QComboBox()
        self.btn_music_folder = QPushButton("Carpeta…")
        self.btn_music_folder.clicked.connect(self._choose_music_folder)
        self.chk_transitions = QCheckBox("Transiciones entre clips")
        self.chk_transitions.setChecked(st.transitions)
        self.chk_intro = QCheckBox("Intro con título")
        self.chk_intro.setChecked(st.intro_enabled)
        self.chk_outro = QCheckBox("Cierre (outro)")
        self.chk_outro.setChecked(st.outro_enabled)
        self.chk_counter = QCheckBox("Marcador de kills en pantalla")
        self.chk_counter.setChecked(st.kill_counter)
        self.chk_slowmo = QCheckBox("Cámara lenta en el momento clave")
        self.chk_slowmo.setChecked(st.slow_motion)
        self.edt_channel = QLineEdit(st.channel_name)
        self.edt_channel.setPlaceholderText("Nombre de tu canal (para intro/outro)")
        self.edt_title = QLineEdit(st.intro_title)
        self.edt_title.setPlaceholderText("Título de la intro (vacío = automático)")
        self.cmb_format = QComboBox()
        for key, p in PRESETS.items():
            self.cmb_format.addItem(str(p["label"]), key)
        idx = self.cmb_format.findData(self.state.config.export.preset)
        self.cmb_format.setCurrentIndex(max(0, idx))
        self.cmb_profile = QComboBox()
        self.cmb_profile.addItem("— Perfil guardado —", "")
        for name in self.state.config.profiles:
            self.cmb_profile.addItem(name, name)
        self.cmb_profile.currentIndexChanged.connect(self._apply_profile)
        layout.addWidget(QLabel("Perfil"), 0, 0)
        layout.addWidget(self.cmb_profile, 0, 1, 1, 2)
        layout.addWidget(QLabel("Formato"), 1, 0)
        layout.addWidget(self.cmb_format, 1, 1, 1, 2)
        layout.addWidget(self.chk_music, 2, 0)
        layout.addWidget(self.cmb_music, 2, 1)
        layout.addWidget(self.btn_music_folder, 2, 2)
        layout.addWidget(self.chk_transitions, 3, 0)
        layout.addWidget(self.chk_counter, 3, 1)
        layout.addWidget(self.chk_intro, 4, 0)
        layout.addWidget(self.chk_outro, 4, 1)
        layout.addWidget(self.chk_slowmo, 5, 0)
        layout.addWidget(QLabel("Canal"), 6, 0)
        layout.addWidget(self.edt_channel, 6, 1, 1, 2)
        layout.addWidget(QLabel("Título intro"), 7, 0)
        layout.addWidget(self.edt_title, 7, 1, 1, 2)
        layout.setRowStretch(8, 1)
        area.setWidget(inner)
        outer.addWidget(area, 1)
        self._reload_music()
        return w

    def _build_recording_step(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel("<b>5. ¿Cómo se graban las jugadas?</b>"))
        self.rb_obs = QRadioButton("Automático con OBS (recomendado): ClutchReel abre CS2, reproduce la demo y graba cada jugada")
        self.rb_obs.setChecked(True)
        self.rb_existing = QRadioButton("Ya tengo la grabación de la partida completa (selecciona el vídeo y sincroniza)")
        layout.addWidget(self.rb_obs)
        layout.addWidget(self.rb_existing)
        box = QFrame()
        box.setObjectName("card")
        bl = QGridLayout(box)
        self.edt_existing = QLineEdit()
        self.edt_existing.setPlaceholderText("Vídeo de la partida (mp4, mkv…)")
        btn = QPushButton("Elegir…")
        btn.clicked.connect(self._choose_existing)
        self.edt_offset = QLineEdit("0")
        self.edt_offset.setToolTip("Segundo del vídeo en el que la demo está en el tick 0 (inicio). Puede ser negativo si el vídeo empezó después.")
        bl.addWidget(QLabel("Vídeo"), 0, 0)
        bl.addWidget(self.edt_existing, 0, 1)
        bl.addWidget(btn, 0, 2)
        bl.addWidget(QLabel("Desfase (s) del inicio de la demo en el vídeo"), 1, 0)
        bl.addWidget(self.edt_offset, 1, 1)
        hint = QLabel("Consejo: en la revisión podrás ajustar el desfase viendo la vista previa de cualquier jugada.")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        bl.addWidget(hint, 2, 0, 1, 3)
        layout.addWidget(box)
        box.setEnabled(False)
        self.rb_existing.toggled.connect(box.setEnabled)
        info = QLabel(
            "Con OBS: necesitas OBS Studio instalado y CS2 en Steam. ClutchReel los abre solos.\n"
            "La primera vez conviene pulsar «Probar grabación» en Ajustes para calibrar."
        )
        info.setObjectName("muted")
        info.setWordWrap(True)
        layout.addWidget(info)
        layout.addStretch()
        return w

    # --------------------------------------------------------- behaviour ----

    def load_match(self, match: MatchData) -> None:
        self.match = match
        cfg = self.state.config
        self.lbl_header.setText(f"{pretty_map(match.map_name)} · {match.score_label()}")
        self.lbl_match.setText(
            f"{Path(match.demo_path).name} · {match.demo_date} · {len(match.rounds)} rondas · {len(match.kills)} bajas · {match.game_mode} · tickrate {match.tickrate:g}"
            + (" · ⚠ " + " ".join(match.warnings) if match.warnings else "")
        )
        stats = {s.steamid64: s for s in compute_stats(match)}
        self.tbl_players.setRowCount(0)
        detected = self._detect_player(match)
        select_row = -1
        self.lbl_player_warning.setText("No se ha reconocido tu cuenta de Steam en esta demo: elige tu jugador en la lista.")
        self.lbl_player_warning.setVisible(not detected)
        for row, p in enumerate(match.players):
            s = stats.get(p.steamid64)
            self.tbl_players.insertRow(row)
            name = p.name + ("   ← tú" if p.steamid64 == detected else "")
            vals = [name, p.team_label, str(p.kills), str(p.deaths), str(p.assists), f"{s.hs_pct:.0f}" if s else "", f"{s.adr:.0f}" if s else ""]
            for col, v in enumerate(vals):
                item = QTableWidgetItem(v)
                if col == 0:
                    item.setData(Qt.ItemDataRole.UserRole, p.steamid64)
                self.tbl_players.setItem(row, col, item)
            if p.steamid64 == detected:
                select_row = row
        self.tbl_players.resizeColumnsToContents()
        self.tbl_players.clearSelection()
        if select_row >= 0:
            self.tbl_players.selectRow(select_row)  # sin cuenta reconocida no se preselecciona a nadie
        last = cfg.ui.last_wizard
        if last:
            kinds = last.get("kinds")
            if isinstance(kinds, list):
                for k, cb in self.kind_checks.items():
                    cb.setChecked(k in kinds)
            dur = last.get("duration")
            if isinstance(dur, str) and dur in self.duration_radios:
                self.duration_radios[dur].setChecked(True)
        self.stack.setCurrentIndex(0)
        self._update_nav()

    def _detect_player(self, match: MatchData) -> int:
        cfg = self.state.config
        ids = {p.steamid64 for p in match.players}
        if cfg.player.steamid64 in ids:
            return cfg.player.steamid64
        for sid, _name, recent in paths.steam_logged_accounts():
            if recent and sid in ids:
                return sid
        for sid, _name, _recent in paths.steam_logged_accounts():
            if sid in ids:
                return sid
        for sid in paths.steam_userdata_ids():
            if sid in ids:
                return sid
        return 0  # no se adivina: marcar al mejor fragger como «tú» llevaría a grabar al jugador equivocado

    def _reload_music(self) -> None:
        self.cmb_music.clear()
        self.cmb_music.addItem("Aleatoria de la carpeta", "")
        folder = self.state.config.paths.music_folder
        for t in list_tracks(folder):
            self.cmb_music.addItem(t.name, str(t))
        cur = self.state.config.style.music_track
        idx = self.cmb_music.findData(cur)
        if idx >= 0:
            self.cmb_music.setCurrentIndex(idx)
        if self.cmb_music.count() == 1:
            self.cmb_music.addItem("(no hay pistas: elige una carpeta)", "")

    def _choose_music_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Carpeta con música", self.state.config.paths.music_folder or str(Path.home()))
        if folder:
            self.state.config.paths.music_folder = folder
            self.state.save()
            self._reload_music()

    def _choose_existing(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Vídeo de la partida", str(Path.home() / "Videos"), "Vídeo (*.mp4 *.mkv *.mov *.avi *.webm)")
        if f:
            self.edt_existing.setText(f)

    def _apply_profile(self) -> None:
        name = self.cmb_profile.currentData()
        if not name:
            return
        prof = self.state.config.profiles.get(name, {})
        style = prof.get("style", {})
        export = prof.get("export", {})
        if style:
            self.chk_music.setChecked(bool(style.get("music_enabled", True)))
            self.chk_transitions.setChecked(bool(style.get("transitions", True)))
            self.chk_intro.setChecked(bool(style.get("intro_enabled", True)))
            self.chk_outro.setChecked(bool(style.get("outro_enabled", True)))
            self.chk_counter.setChecked(bool(style.get("kill_counter", True)))
            self.chk_slowmo.setChecked(bool(style.get("slow_motion", True)))
        if export:
            idx = self.cmb_format.findData(export.get("preset", "youtube_1080p60"))
            if idx >= 0:
                self.cmb_format.setCurrentIndex(idx)
        wizard = prof.get("wizard", {})
        dur = wizard.get("duration") or wizard.get("duration_target")
        if isinstance(dur, str) and dur in self.duration_radios:
            self.duration_radios[dur].setChecked(True)

    def _update_nav(self) -> None:
        i = self.stack.currentIndex()
        n = self.stack.count()
        self.lbl_step.setText(f"Paso {i + 1} de {n}")
        self.btn_back.setEnabled(i > 0)
        self.btn_next.setText("Terminar y revisar jugadas" if i == n - 1 else "Siguiente →")

    def _back(self) -> None:
        self.stack.setCurrentIndex(max(0, self.stack.currentIndex() - 1))
        self._update_nav()

    def _next(self) -> None:
        i = self.stack.currentIndex()
        if i < self.stack.count() - 1:
            self.stack.setCurrentIndex(i + 1)
            self._update_nav()
        else:
            self._finish()

    def _use_recommended(self) -> None:
        for k, cb in self.kind_checks.items():
            cb.setChecked(k in RECOMMENDED_KINDS)
        self.duration_radios["3-5 min"].setChecked(True)
        self.rb_obs.setChecked(True)
        self._finish()

    def _selected_player(self) -> tuple[int, str]:
        rows = self.tbl_players.selectionModel().selectedRows()
        if not rows or not self.match:
            return 0, ""
        item = self.tbl_players.item(rows[0].row(), 0)
        if item is None:
            return 0, ""
        sid = int(item.data(Qt.ItemDataRole.UserRole))
        p = self.match.player_by_steamid(sid)
        return sid, p.name if p else ""

    def _finish(self) -> None:
        sid, name = self._selected_player()
        if not sid:
            self.stack.setCurrentIndex(0)
            self._update_nav()
            QMessageBox.information(self, "Elige tu jugador", "Selecciona en la lista el jugador del que quieres las jugadas.")
            return
        if self.rb_existing.isChecked():
            video = self.edt_existing.text().strip()
            if not video or not Path(video).is_file():
                self.stack.setCurrentIndex(self.stack.count() - 1)
                self._update_nav()
                QMessageBox.information(self, "Falta el vídeo", "Elige el vídeo de la partida completa (o marca «Automático con OBS»).")
                return
        kinds = [k for k, cb in self.kind_checks.items() if cb.isChecked()]
        duration = next((n for n, rb in self.duration_radios.items() if rb.isChecked()), "3-5 min")
        style = {
            "music_enabled": self.chk_music.isChecked(),
            "music_track": self.cmb_music.currentData() or "",
            "transitions": self.chk_transitions.isChecked(),
            "intro_enabled": self.chk_intro.isChecked(),
            "outro_enabled": self.chk_outro.isChecked(),
            "kill_counter": self.chk_counter.isChecked(),
            "slow_motion": self.chk_slowmo.isChecked(),
            "channel_name": self.edt_channel.text().strip(),
            "intro_title": self.edt_title.text().strip(),
        }
        preset = self.cmb_format.currentData() or "youtube_1080p60"
        try:
            offset = float(self.edt_offset.text().replace(",", ".") or 0)
        except ValueError:
            offset = 0.0
        result = WizardResult(
            steamid=sid,
            player_name=name,
            kinds=kinds,
            duration=duration,
            style=style,
            export_preset=preset,
            recording_mode="existing" if self.rb_existing.isChecked() else "obs",
            existing_recording=self.edt_existing.text().strip(),
            existing_offset=offset,
            remember_player=self.chk_remember.isChecked(),
        )
        self.finished.emit(result)
