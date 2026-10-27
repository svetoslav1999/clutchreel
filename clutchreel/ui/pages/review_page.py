"""Pantalla de revisión/edición: tarjetas de jugadas, edición por clip, vista previa."""

from __future__ import annotations

import html
import uuid
from pathlib import Path

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from clutchreel.core.demo.selector import ORDER_CHRONO, ORDER_CRESCENDO, ORDER_SCORE, order_highlights
from clutchreel.core.editor.music import list_tracks
from clutchreel.core.editor.project import Clip, Project
from clutchreel.core.export.builder import PRESETS
from clutchreel.ui.state import AppState
from clutchreel.ui.theme import TEXT_MUTED
from clutchreel.ui.widgets.clip_card import ClipCard, recording_status
from clutchreel.ui.widgets.iconbutton import icon_button
from clutchreel.ui.widgets.video_preview import VideoPreview
from clutchreel.utils.timeutil import format_duration

CARD_HEIGHT = 104


def _section(text: str) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName("section")
    return lbl


class ReviewPage(QWidget):
    create_video = Signal()
    record_clips = Signal()

    def __init__(self, state: AppState) -> None:
        super().__init__()
        self.state = state
        self._current_id: str | None = None
        self._loading = False
        self._dragging = False  # arrastrando un deslizador: una sola entrada de deshacer por gesto
        # Guardado agrupado: editar no escribe el proyecto (~100 KB) en disco con cada paso de un deslizador.
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(600)
        self._save_timer.timeout.connect(self._do_save)
        self._pending_save: Project | None = None
        root = QVBoxLayout(self)
        root.setContentsMargins(20, 18, 20, 18)
        root.setSpacing(12)

        head = QHBoxLayout()
        self.lbl_title = QLabel("Revisión de jugadas")
        self.lbl_title.setObjectName("title")
        head.addWidget(self.lbl_title)
        head.addStretch()
        self.btn_undo = icon_button("Deshacer", "undo")
        self.btn_undo.clicked.connect(self._undo)
        self.btn_redo = icon_button("Rehacer", "redo")
        self.btn_redo.clicked.connect(self._redo)
        self.btn_save_profile = icon_button("Guardar como perfil…", "save")
        self.btn_save_profile.clicked.connect(self._save_profile)
        head.addWidget(self.btn_undo)
        head.addWidget(self.btn_redo)
        head.addWidget(self.btn_save_profile)
        root.addLayout(head)
        self.lbl_summary = QLabel("")
        self.lbl_summary.setObjectName("subtitle")
        root.addWidget(self.lbl_summary)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(splitter, 1)

        # Columna izquierda: lista de clips.
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        order_row = QHBoxLayout()
        order_row.addWidget(QLabel("Ordenar por:"))
        self.cmb_order = QComboBox()
        self.cmb_order.addItems([ORDER_CHRONO, ORDER_SCORE, ORDER_CRESCENDO])
        self.cmb_order.currentTextChanged.connect(self._reorder)
        order_row.addWidget(self.cmb_order)
        order_row.addStretch()
        self.btn_all = QPushButton("Todas")
        self.btn_all.clicked.connect(lambda: self._toggle_all(True))
        self.btn_none = QPushButton("Ninguna")
        self.btn_none.clicked.connect(lambda: self._toggle_all(False))
        order_row.addWidget(self.btn_all)
        order_row.addWidget(self.btn_none)
        ll.addLayout(order_row)
        hint = QLabel("Arrastra para reordenar · casilla para incluir/excluir · clic para editar")
        hint.setObjectName("muted")
        hint.setWordWrap(True)
        ll.addWidget(hint)
        self.lst = QListWidget()
        self.lst.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.lst.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.lst.setSpacing(4)
        self.lst.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.lst.setResizeMode(QListView.ResizeMode.Adjust)  # las tarjetas se reajustan al encoger la ventana
        self.lst.currentItemChanged.connect(self._on_select)
        self.lst.model().rowsMoved.connect(self._on_rows_moved)
        ll.addWidget(self.lst, 1)
        splitter.addWidget(left)

        # Columna derecha: vista previa + edición por clip + estilo global.
        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        rbox = QWidget()
        rl = QVBoxLayout(rbox)
        rl.setContentsMargins(6, 0, 0, 0)
        self.preview = VideoPreview()
        rl.addWidget(self.preview)

        clip_box = QFrame()
        clip_box.setObjectName("panel")
        # El texto del clip va en una caja vertical, fuera de la rejilla: con varias líneas la rejilla le
        # daba menos alto del que necesitaba y se montaba sobre la fila siguiente.
        clip_v = QVBoxLayout(clip_box)
        clip_v.addWidget(_section("Clip seleccionado"))
        self.lbl_clip = QLabel("—")
        self.lbl_clip.setWordWrap(True)
        clip_v.addWidget(self.lbl_clip)
        cg = QGridLayout()
        clip_v.addLayout(cg)
        cg.addWidget(QLabel("Recortar inicio (s)"), 2, 0)
        self.sld_start = QSlider(Qt.Orientation.Horizontal)
        self.sld_start.setRange(0, 100)
        self.sld_start.sliderPressed.connect(self._begin_drag)
        self.sld_start.sliderReleased.connect(self._end_drag)
        self.sld_start.valueChanged.connect(self._on_trim_changed)
        self.lbl_start = QLabel("0,0")
        cg.addWidget(self.sld_start, 2, 1, 1, 2)
        cg.addWidget(self.lbl_start, 2, 3)
        cg.addWidget(QLabel("Recortar final (s)"), 3, 0)
        self.sld_end = QSlider(Qt.Orientation.Horizontal)
        self.sld_end.setRange(0, 100)
        self.sld_end.sliderPressed.connect(self._begin_drag)
        self.sld_end.sliderReleased.connect(self._end_drag)
        self.sld_end.valueChanged.connect(self._on_trim_changed)
        self.lbl_end = QLabel("0,0")
        cg.addWidget(self.sld_end, 3, 1, 1, 2)
        cg.addWidget(self.lbl_end, 3, 3)
        self.chk_slow = QCheckBox("Cámara lenta en la kill")
        self.chk_slow.toggled.connect(lambda v: self._edit_clip("slow_motion", v))
        cg.addWidget(self.chk_slow, 4, 0, 1, 2)
        cg.addWidget(QLabel("Zoom"), 4, 2)
        self.spn_zoom = QDoubleSpinBox()
        self.spn_zoom.setRange(1.0, 2.0)
        self.spn_zoom.setSingleStep(0.1)
        self.spn_zoom.valueChanged.connect(lambda v: self._edit_clip("zoom", float(v)))
        cg.addWidget(self.spn_zoom, 4, 3)
        cg.addWidget(QLabel("Texto"), 5, 0)
        self.edt_text = QLineEdit()
        self.edt_text.setPlaceholderText("Texto superpuesto (vacío = automático)")
        self.edt_text.editingFinished.connect(lambda: self._edit_clip("overlay_text", self.edt_text.text()))
        cg.addWidget(self.edt_text, 5, 1, 1, 3)
        cg.addWidget(QLabel("Transición entrada"), 6, 0)
        self.cmb_tin = QComboBox()
        self.cmb_tin.addItems(["fade", "none"])
        self.cmb_tin.currentTextChanged.connect(lambda v: self._edit_clip("transition_in", v))
        cg.addWidget(self.cmb_tin, 6, 1)
        cg.addWidget(QLabel("salida"), 6, 2)
        self.cmb_tout = QComboBox()
        self.cmb_tout.addItems(["fade", "none"])
        self.cmb_tout.currentTextChanged.connect(lambda v: self._edit_clip("transition_out", v))
        cg.addWidget(self.cmb_tout, 6, 3)
        cg.addWidget(QLabel("Volumen juego"), 7, 0)
        self.sld_vol = QSlider(Qt.Orientation.Horizontal)
        self.sld_vol.setRange(0, 150)
        self.sld_vol.sliderPressed.connect(self._begin_drag)
        self.sld_vol.sliderReleased.connect(self._end_drag)
        self.sld_vol.valueChanged.connect(lambda v: self._edit_clip("game_volume", v / 100.0))
        cg.addWidget(self.sld_vol, 7, 1, 1, 3)
        btn_row = QHBoxLayout()
        self.btn_preview = icon_button("Vista previa", "play")
        self.btn_preview.clicked.connect(self._preview_clip)
        self.btn_dup = QPushButton("Duplicar")
        self.btn_dup.clicked.connect(self._duplicate)
        self.btn_del = QPushButton("Borrar")
        self.btn_del.setObjectName("danger")
        self.btn_del.clicked.connect(self._delete)
        btn_row.addWidget(self.btn_preview)
        btn_row.addWidget(self.btn_dup)
        btn_row.addWidget(self.btn_del)
        cg.addLayout(btn_row, 8, 0, 1, 4)
        rl.addWidget(clip_box)

        style_box = QFrame()
        style_box.setObjectName("panel")
        sg = QGridLayout(style_box)
        sg.addWidget(_section("Vídeo completo"), 0, 0, 1, 4)
        self.chk_music = QCheckBox("Música")
        self.chk_music.toggled.connect(lambda v: self._edit_style("music_enabled", v))
        self.cmb_music = QComboBox()
        self.cmb_music.currentIndexChanged.connect(lambda _i: self._edit_style("music_track", self.cmb_music.currentData() or ""))
        self.btn_music = QPushButton("Pista…")
        self.btn_music.clicked.connect(self._choose_music)
        sg.addWidget(self.chk_music, 1, 0)
        sg.addWidget(self.cmb_music, 1, 1, 1, 2)
        sg.addWidget(self.btn_music, 1, 3)
        sg.addWidget(QLabel("Volumen música"), 2, 0)
        self.sld_music = QSlider(Qt.Orientation.Horizontal)
        self.sld_music.setRange(0, 100)
        self.sld_music.sliderPressed.connect(self._begin_drag)
        self.sld_music.sliderReleased.connect(self._end_drag)
        self.sld_music.valueChanged.connect(lambda v: self._edit_style("music_volume", v / 100.0))
        sg.addWidget(self.sld_music, 2, 1, 1, 3)
        self.chk_duck = QCheckBox("Bajar la música cuando suena el juego")
        self.chk_duck.toggled.connect(lambda v: self._edit_style("ducking", v))
        self.chk_beats = QCheckBox("Cortes al ritmo (requiere librosa)")
        self.chk_beats.toggled.connect(lambda v: self._edit_style("beat_sync", v))
        sg.addWidget(self.chk_duck, 3, 0, 1, 4)
        sg.addWidget(self.chk_beats, 4, 0, 1, 4)
        self.chk_intro = QCheckBox("Intro")
        self.chk_intro.toggled.connect(lambda v: self._edit_style("intro_enabled", v))
        self.chk_outro = QCheckBox("Outro")
        self.chk_outro.toggled.connect(lambda v: self._edit_style("outro_enabled", v))
        self.chk_counter = QCheckBox("Marcador de kills")
        self.chk_counter.toggled.connect(lambda v: self._edit_style("kill_counter", v))
        self.chk_trans = QCheckBox("Transiciones")
        self.chk_trans.toggled.connect(lambda v: self._edit_style("transitions", v))
        sg.addWidget(self.chk_intro, 5, 0)
        sg.addWidget(self.chk_outro, 5, 1)
        sg.addWidget(self.chk_counter, 5, 2)
        sg.addWidget(self.chk_trans, 5, 3)
        sg.addWidget(QLabel("Transición"), 6, 0)
        self.cmb_trans = QComboBox()
        self.cmb_trans.addItems(["fade", "fadeblack", "wipeleft", "slideleft", "circleopen", "dissolve"])
        self.cmb_trans.currentTextChanged.connect(lambda v: self._edit_style("transition_type", v))
        sg.addWidget(self.cmb_trans, 6, 1)
        sg.addWidget(QLabel("Formato"), 6, 2)
        self.cmb_format = QComboBox()
        for key, p in PRESETS.items():
            self.cmb_format.addItem(str(p["label"]), key)
        self.cmb_format.currentIndexChanged.connect(self._on_format)
        sg.addWidget(self.cmb_format, 6, 3)
        sg.addWidget(QLabel("Título intro"), 7, 0)
        self.edt_title = QLineEdit()
        self.edt_title.editingFinished.connect(lambda: self._edit_style("intro_title", self.edt_title.text()))
        sg.addWidget(self.edt_title, 7, 1, 1, 3)
        sg.addWidget(QLabel("Canal"), 8, 0)
        self.edt_channel = QLineEdit()
        self.edt_channel.editingFinished.connect(lambda: self._edit_style("channel_name", self.edt_channel.text()))
        sg.addWidget(self.edt_channel, 8, 1, 1, 3)
        sg.addWidget(QLabel("Logo"), 9, 0)
        self.edt_logo = QLineEdit()
        self.edt_logo.setPlaceholderText("PNG opcional")
        self.edt_logo.editingFinished.connect(lambda: self._edit_style("watermark_path", self.edt_logo.text()))
        btn_logo = QPushButton("…")
        btn_logo.setFixedWidth(36)
        btn_logo.clicked.connect(self._choose_logo)
        sg.addWidget(self.edt_logo, 9, 1, 1, 2)
        sg.addWidget(btn_logo, 9, 3)
        # Modo "ya tengo grabación": desfase.
        self.existing_row = QWidget()
        er = QHBoxLayout(self.existing_row)
        er.setContentsMargins(0, 0, 0, 0)
        er.addWidget(QLabel("Desfase del vídeo (s)"))
        self.spn_offset = QDoubleSpinBox()
        self.spn_offset.setRange(-36000, 36000)
        self.spn_offset.setDecimals(2)
        self.spn_offset.valueChanged.connect(self._on_offset)
        er.addWidget(self.spn_offset)
        er.addStretch()
        sg.addWidget(self.existing_row, 10, 0, 1, 4)
        rl.addWidget(style_box)
        rl.addStretch()
        for combo in rbox.findChildren(QComboBox):
            combo.setSizeAdjustPolicy(QComboBox.SizeAdjustPolicy.AdjustToMinimumContentsLengthWithIcon)
            combo.setMinimumContentsLength(6)
        for edit in rbox.findChildren(QLineEdit):
            edit.setMinimumWidth(60)
        right.setWidget(rbox)
        splitter.addWidget(right)
        splitter.setChildrenCollapsible(False)
        # Mínimos explícitos: con la ventana al mínimo (1180 px) caben las tarjetas y el panel de edición
        # sin cortarse; el sobrante se reparte casi a partes iguales.
        left.setMinimumWidth(392)
        right.setMinimumWidth(rbox.minimumSizeHint().width() + right.verticalScrollBar().sizeHint().width() + 4)
        splitter.setStretchFactor(0, 45)
        splitter.setStretchFactor(1, 55)
        splitter.setSizes([520, 600])

        bottom = QHBoxLayout()
        self.lbl_total = QLabel("")
        self.lbl_total.setObjectName("muted")
        bottom.addWidget(self.lbl_total)
        bottom.addStretch()
        self.btn_record = icon_button("Grabar jugadas con OBS", "record")
        self.btn_record.clicked.connect(self._on_record_clicked)
        self.btn_create = icon_button("Crear vídeo", "film", primary=True)
        self.btn_create.setObjectName("primary")
        self.btn_create.clicked.connect(self._on_create_clicked)
        bottom.addWidget(self.btn_record)
        bottom.addWidget(self.btn_create)
        root.addLayout(bottom)

    # ------------------------------------------------------------ loading ---

    @property
    def project(self) -> Project | None:
        return self.state.project

    def load_project(self) -> None:
        self.flush_save()
        p = self.project
        self._loading = True
        self.lst.clear()
        if not p:
            self.lbl_summary.setText("No hay proyecto abierto.")
            self._loading = False
            return
        self.lbl_title.setText(f"{p.player_name} · {p.match.map_name}")
        self._fill_music()
        st = p.style
        self.chk_music.setChecked(st.music_enabled)
        idx = self.cmb_music.findData(st.music_track)
        self.cmb_music.setCurrentIndex(max(0, idx))
        self.sld_music.setValue(int(st.music_volume * 100))
        self.chk_duck.setChecked(st.ducking)
        self.chk_beats.setChecked(st.beat_sync)
        self.chk_intro.setChecked(st.intro_enabled)
        self.chk_outro.setChecked(st.outro_enabled)
        self.chk_counter.setChecked(st.kill_counter)
        self.chk_trans.setChecked(st.transitions)
        self.cmb_trans.setCurrentText(st.transition_type if st.transition_type in [self.cmb_trans.itemText(i) for i in range(self.cmb_trans.count())] else "fade")
        fidx = self.cmb_format.findData(p.export_preset)
        self.cmb_format.setCurrentIndex(max(0, fidx))
        self.edt_title.setText(st.intro_title)
        self.edt_channel.setText(st.channel_name)
        self.edt_logo.setText(st.watermark_path)
        self.cmb_order.blockSignals(True)
        self.cmb_order.setCurrentText(p.order_mode)
        self.cmb_order.blockSignals(False)
        self.existing_row.setVisible(p.recording_mode == "existing")
        self.spn_offset.setValue(p.existing_recording_offset)
        self.btn_record.setVisible(p.recording_mode != "existing")
        for clip in p.clips:
            self._add_card(clip)
        if p.clips:
            self.lst.setCurrentRow(0)
        self._loading = False
        self._refresh_summary()
        self._update_undo_buttons()

    def _fill_music(self) -> None:
        self.cmb_music.blockSignals(True)
        self.cmb_music.clear()
        self.cmb_music.addItem("Aleatoria de la carpeta", "")
        for t in list_tracks(self.state.config.paths.music_folder):
            self.cmb_music.addItem(t.name, str(t))
        self.cmb_music.blockSignals(False)

    def _add_card(self, clip: Clip) -> None:
        assert self.project
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, clip.id)
        card = ClipCard(clip, self.project.tickrate)
        card.toggled.connect(self._on_toggle)
        card.setFixedHeight(CARD_HEIGHT)
        item.setSizeHint(QSize(10, CARD_HEIGHT + 6))
        self.lst.addItem(item)
        self.lst.setItemWidget(item, card)

    def refresh_cards(self) -> None:
        p = self.project
        if not p:
            return
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            clip = p.clip_by_id(item.data(Qt.ItemDataRole.UserRole))
            card = self.lst.itemWidget(item)
            if clip and isinstance(card, ClipCard):
                card.refresh(clip, p.tickrate)
        self._refresh_summary()

    def _refresh_card(self, clip: Clip) -> None:
        """Repinta solo la tarjeta del clip editado (y el resumen)."""
        p = self.project
        if not p:
            return
        for i in range(self.lst.count()):
            item = self.lst.item(i)
            if item.data(Qt.ItemDataRole.UserRole) == clip.id:
                card = self.lst.itemWidget(item)
                if isinstance(card, ClipCard):
                    card.refresh(clip, p.tickrate)
                break
        self._refresh_summary()

    def _refresh_summary(self) -> None:
        p = self.project
        if not p:
            return
        n = len(p.enabled_clips())
        recorded = sum(1 for c in p.enabled_clips() if c.is_recorded or p.recording_mode == "existing")
        self.lbl_summary.setText(f"{len(p.clips)} jugadas detectadas · {n} incluidas · duración estimada {format_duration(p.total_duration())}")
        self.lbl_total.setText(f"Clips grabados: {recorded}/{n}" if p.recording_mode != "existing" else f"Vídeo existente: {Path(p.existing_recording).name if p.existing_recording else '—'}")
        self.btn_create.setEnabled(n > 0)

    # ------------------------------------------------------------ editing ---

    def _push_undo(self) -> None:
        if self.project and not self._loading and not (self._dragging and self._drag_pushed):
            self.state.undo.push(self.project)
            self._drag_pushed = self._dragging
            self._update_undo_buttons()

    _drag_pushed = False

    def _begin_drag(self) -> None:
        self._dragging = True
        self._drag_pushed = False

    def _end_drag(self) -> None:
        self._dragging = False
        self._drag_pushed = False
        self.flush_save()

    def _on_record_clicked(self) -> None:
        self.flush_save()
        self.record_clips.emit()

    def _on_create_clicked(self) -> None:
        self.flush_save()
        self.create_video.emit()

    def _schedule_save(self) -> None:
        self._pending_save = self.project
        self._save_timer.start()

    def _do_save(self) -> None:
        pending, self._pending_save = self._pending_save, None
        if pending is None:
            return
        if pending is self.state.project:
            self.state.autosave()
            return
        try:  # se cambió de proyecto con cambios sin guardar: se guardan en el suyo
            pending.save()
        except OSError as exc:
            self.state.status_message.emit(f"No se pudo guardar el proyecto: {exc}")

    def flush_save(self) -> None:
        """Guarda ya lo pendiente (antes de grabar/exportar o al cambiar de proyecto)."""
        self._save_timer.stop()
        self._do_save()

    def _update_undo_buttons(self) -> None:
        self.btn_undo.setEnabled(self.state.undo.can_undo)
        self.btn_redo.setEnabled(self.state.undo.can_redo)

    def _undo(self) -> None:
        if self.project and self.state.undo.undo(self.project):
            self.load_project()
            self.state.autosave()

    def _redo(self) -> None:
        if self.project and self.state.undo.redo(self.project):
            self.load_project()
            self.state.autosave()

    def _current_clip(self) -> Clip | None:
        if not self.project or not self._current_id:
            return None
        return self.project.clip_by_id(self._current_id)

    def _on_select(self, current: QListWidgetItem | None, previous: QListWidgetItem | None) -> None:
        if previous is not None:
            w = self.lst.itemWidget(previous)
            if isinstance(w, ClipCard):
                w.set_selected(False)
        if current is None or not self.project:
            self._current_id = None
            return
        w = self.lst.itemWidget(current)
        if isinstance(w, ClipCard):
            w.set_selected(True)
        self._current_id = current.data(Qt.ItemDataRole.UserRole)
        clip = self._current_clip()
        if not clip:
            return
        self._loading = True
        hl = clip.highlight
        dur = hl.duration_seconds(self.project.tickrate)
        camera = recording_status(clip)[3]
        self.lbl_clip.setText(
            f"<b>{html.escape(hl.label)}</b> · Ronda {hl.round} · {hl.score:.0f} pts · {format_duration(dur)}<br>{html.escape(hl.description)}"
            + (f"<br><span style='color:{TEXT_MUTED}'>{html.escape(camera)}</span>" if camera else "")
        )
        max_trim = int(max(0.0, dur - 1.0) * 10)
        self.sld_start.setRange(0, max_trim)
        self.sld_end.setRange(0, max_trim)
        self.sld_start.setValue(int(clip.trim_start * 10))
        self.sld_end.setValue(int(clip.trim_end * 10))
        self.lbl_start.setText(f"{clip.trim_start:.1f}")
        self.lbl_end.setText(f"{clip.trim_end:.1f}")
        self.chk_slow.setChecked(clip.slow_motion)
        self.spn_zoom.setValue(clip.zoom)
        self.edt_text.setText(clip.overlay_text)
        self.cmb_tin.setCurrentText(clip.transition_in)
        self.cmb_tout.setCurrentText(clip.transition_out)
        self.sld_vol.setValue(int(clip.game_volume * 100))
        self._loading = False

    def _on_trim_changed(self) -> None:
        clip = self._current_clip()
        if not clip or self._loading:
            return
        self._push_undo()
        clip.trim_start = self.sld_start.value() / 10.0
        clip.trim_end = self.sld_end.value() / 10.0
        self.lbl_start.setText(f"{clip.trim_start:.1f}")
        self.lbl_end.setText(f"{clip.trim_end:.1f}")
        self._refresh_card(clip)
        self._schedule_save()

    def _edit_clip(self, attr: str, value: object) -> None:
        clip = self._current_clip()
        if not clip or self._loading:
            return
        if getattr(clip, attr) == value:
            return
        self._push_undo()
        setattr(clip, attr, value)
        self._refresh_card(clip)
        self._schedule_save()

    def _edit_style(self, attr: str, value: object) -> None:
        p = self.project
        if not p or self._loading:
            return
        if getattr(p.style, attr) == value:
            return
        self._push_undo()
        setattr(p.style, attr, value)
        self._refresh_summary()
        self._schedule_save()

    def _on_format(self) -> None:
        p = self.project
        if not p or self._loading:
            return
        key = self.cmb_format.currentData()
        if key and key != p.export_preset:
            self._push_undo()
            p.export_preset = key
            p.style.aspect = "9:16" if key.startswith("shorts") else "16:9"
            self._schedule_save()

    def _on_offset(self, value: float) -> None:
        p = self.project
        if p and not self._loading and p.existing_recording_offset != value:
            p.existing_recording_offset = value
            self._schedule_save()

    def _on_toggle(self, clip_id: str, enabled: bool) -> None:
        p = self.project
        if not p:
            return
        clip = p.clip_by_id(clip_id)
        if clip and clip.enabled != enabled:
            self._push_undo()
            clip.enabled = enabled
            self._refresh_summary()
            self._schedule_save()

    def _toggle_all(self, enabled: bool) -> None:
        p = self.project
        if not p:
            return
        self._push_undo()
        for c in p.clips:
            c.enabled = enabled
        self.refresh_cards()
        self._schedule_save()

    def _on_rows_moved(self, *_args: object) -> None:
        p = self.project
        if not p:
            return
        self._push_undo()
        ids = [self.lst.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.lst.count())]
        by_id = {c.id: c for c in p.clips}
        p.clips = [by_id[i] for i in ids if i in by_id]
        self._schedule_save()

    def _reorder(self, mode: str) -> None:
        p = self.project
        if not p or self._loading:
            return
        self._push_undo()
        p.order_mode = mode
        hls = order_highlights([c.highlight for c in p.clips], mode)
        order = {id(h): i for i, h in enumerate(hls)}
        p.clips.sort(key=lambda c: order.get(id(c.highlight), 0))
        self.load_project()
        self._schedule_save()

    def _duplicate(self) -> None:
        p = self.project
        clip = self._current_clip()
        if not p or not clip:
            return
        self._push_undo()
        new = Clip.from_dict(clip.to_dict())
        new.id = uuid.uuid4().hex
        idx = p.clips.index(clip) + 1
        p.clips.insert(idx, new)
        self.load_project()
        self.lst.setCurrentRow(idx)
        self._schedule_save()

    def _delete(self) -> None:
        p = self.project
        clip = self._current_clip()
        if not p or not clip:
            return
        self._push_undo()
        p.clips.remove(clip)
        self.load_project()
        self._schedule_save()

    def _preview_clip(self) -> None:
        p = self.project
        clip = self._current_clip()
        if not p or not clip:
            return
        if p.recording_mode == "existing" and p.existing_recording:
            start = p.existing_recording_offset + clip.highlight.start_seconds(p.tickrate) + clip.trim_start
            end = start + clip.duration_seconds(p.tickrate)
            self.preview.load(p.existing_recording, start, end)
        elif clip.has_recording:
            start = clip.recording_offset + clip.trim_start
            end = start + clip.recorded_duration_seconds(p.tickrate)
            self.preview.load(clip.recording_path, start, end)
        else:
            self.preview.placeholder.setText("Este clip todavía no está grabado.\nPulsa «Grabar jugadas con OBS».")

    def _choose_music(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Pista de música", self.state.config.paths.music_folder or str(Path.home() / "Music"), "Audio (*.mp3 *.wav *.ogg *.flac *.m4a)")
        if f:
            folder = str(Path(f).parent)
            self.state.config.paths.music_folder = folder
            self.state.save()
            self._fill_music()
            idx = self.cmb_music.findData(f)
            if idx < 0:
                self.cmb_music.addItem(Path(f).name, f)
                idx = self.cmb_music.count() - 1
            self.cmb_music.setCurrentIndex(idx)

    def _choose_logo(self) -> None:
        f, _ = QFileDialog.getOpenFileName(self, "Logo o marca de agua", str(Path.home()), "Imagen (*.png *.jpg)")
        if f:
            self.edt_logo.setText(f)
            self._edit_style("watermark_path", f)

    def _save_profile(self) -> None:
        p = self.project
        if not p:
            return
        name, ok = QInputDialog.getText(self, "Guardar perfil", "Nombre del perfil:")
        if not ok or not name.strip():
            return
        cfg = self.state.config
        cfg.style = Project.from_dict(p.to_dict()).style
        cfg.export.preset = p.export_preset
        cfg.ui.last_wizard = dict(p.wizard)
        self.state.store.save_profile(name.strip())
        self.state.save()
        self.state.status_message.emit(f"Perfil «{name.strip()}» guardado.")
