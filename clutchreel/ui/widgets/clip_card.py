"""Tarjeta de jugada para la lista de revisión."""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout

from clutchreel.core.editor.project import Clip
from clutchreel.ui.theme import ACCENT, DANGER, SUCCESS, TEXT_MUTED
from clutchreel.utils.timeutil import format_duration


def recording_status(clip: Clip) -> tuple[str, str, str, str]:
    """Estado de grabación para la tarjeta: (texto corto, color, línea de cámara, tooltip)."""
    if clip.is_recorded:
        who = clip.recorded_player_name or "jugador"
        return "● grabado", SUCCESS, f"🎥 Cámara en {who} ✓", f"Cámara comprobada en {who} ({clip.camera_note})."
    if clip.recording_ok and clip.has_recording:
        return "⚠ regrabar", ACCENT, "🎥 Cámara sin comprobar", "Grabado con una versión anterior que no comprobaba a quién sigue la cámara. Vuelve a grabarlo."
    if clip.camera_note:
        return "✗ falló", DANGER, f"✗ {clip.camera_note}", clip.camera_note
    return "○ sin grabar", TEXT_MUTED, "", ""


class ClipCard(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, clip: Clip, tickrate: float) -> None:
        super().__init__()
        self.clip_id = clip.id
        self.setObjectName("card")
        self.setProperty("selected", False)
        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 10, 12, 10)
        self.check = QCheckBox()
        self.check.setChecked(clip.enabled)
        self.check.toggled.connect(lambda v: self.toggled.emit(self.clip_id, v))
        layout.addWidget(self.check)
        thumb = QLabel(_icon_for(clip))
        thumb.setFixedSize(64, 48)
        thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        thumb.setStyleSheet("background: #0f1216; border-radius: 8px; font-size: 26px;")
        layout.addWidget(thumb)
        text = QVBoxLayout()
        text.setSpacing(2)
        self.lbl_title = QLabel(f"<b>{clip.highlight.label}</b> · Ronda {clip.highlight.round}")
        self.lbl_desc = QLabel(clip.highlight.description)
        self.lbl_desc.setTextFormat(Qt.TextFormat.PlainText)  # los nombres de jugador pueden contener «<»
        self.lbl_desc.setStyleSheet(f"color: {TEXT_MUTED};")
        self.lbl_desc.setWordWrap(False)
        self.lbl_desc.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_title.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.lbl_camera = QLabel("")
        self.lbl_camera.setTextFormat(Qt.TextFormat.PlainText)
        self.lbl_camera.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        text.addWidget(self.lbl_title)
        text.addWidget(self.lbl_desc)
        text.addWidget(self.lbl_camera)
        layout.addLayout(text, 1)
        meta = QVBoxLayout()
        meta.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_score = QLabel(f"{clip.highlight.score:.0f} pts")
        self.lbl_score.setObjectName("badge")
        self.lbl_dur = QLabel(format_duration(clip.duration_seconds(tickrate)))
        self.lbl_dur.setStyleSheet(f"color: {TEXT_MUTED};")
        self.lbl_dur.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_rec = QLabel("")
        self.lbl_rec.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta.addWidget(self.lbl_score, alignment=Qt.AlignmentFlag.AlignRight)
        meta.addWidget(self.lbl_dur)
        meta.addWidget(self.lbl_rec)
        layout.addLayout(meta)
        self._show_recording(clip)

    def _show_recording(self, clip: Clip) -> None:
        text, color, camera, tip = recording_status(clip)
        self.lbl_rec.setText(text)
        self.lbl_rec.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.lbl_camera.setText(camera)
        self.lbl_camera.setStyleSheet(f"color: {color if camera.startswith('✗') else TEXT_MUTED}; font-size: 12px;")
        self.lbl_camera.setVisible(bool(camera))
        self.lbl_camera.setToolTip(tip)
        self.lbl_rec.setToolTip(tip)

    def refresh(self, clip: Clip, tickrate: float) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(clip.enabled)
        self.check.blockSignals(False)
        self.lbl_title.setText(f"<b>{clip.highlight.label}</b> · Ronda {clip.highlight.round}")
        self.lbl_desc.setText(clip.highlight.description)
        self.lbl_score.setText(f"{clip.highlight.score:.0f} pts")
        self.lbl_dur.setText(format_duration(clip.duration_seconds(tickrate)))
        self._show_recording(clip)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)


def _icon_for(clip: Clip) -> str:
    kinds = clip.highlight.merged_kinds or [clip.highlight.kind]
    table = {
        "ace": "👑",
        "clutch": "🧠",
        "4k": "🔥",
        "3k": "💥",
        "2k": "⚡",
        "headshot_streak": "🎯",
        "entry": "🚪",
        "awp": "🔭",
        "noscope": "🙈",
        "wallbang": "🧱",
        "smoke": "🌫️",
        "blind": "😵",
        "air": "🪂",
        "knife": "🔪",
        "decisive": "🏁",
        "best_round": "⭐",
        "kill": "☠️",
    }
    for k in ("ace", "clutch", "4k", "3k", "knife", "noscope", "2k"):
        if k in kinds:
            return table[k]
    return table.get(kinds[0], "🎬")
