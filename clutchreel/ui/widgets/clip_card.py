"""Tarjeta de jugada para la lista de revisión."""

from __future__ import annotations

import hashlib
import logging
import subprocess
from pathlib import Path

from PySide6.QtCore import QObject, QRectF, QRunnable, Qt, QThreadPool, Signal
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QLabel, QSizePolicy, QVBoxLayout, QWidget

from clutchreel.core.editor.project import Clip
from clutchreel.ui import icons, theme
from clutchreel.ui.theme import KIND_TAGS, kind_color, main_kind
from clutchreel.ui.widgets.elided_label import ElidedLabel
from clutchreel.utils.timeutil import format_duration

log = logging.getLogger(__name__)

THUMB_W, THUMB_H = 128, 72


def recording_status(clip: Clip) -> tuple[str, str, str, str]:
    """Estado de grabación para la tarjeta: (texto corto, color, línea de cámara, tooltip)."""
    pal = theme.current()
    SUCCESS, ACCENT, DANGER, TEXT_MUTED = pal.success, pal.accent, pal.danger, pal.muted  # noqa: N806 - mismos nombres que el tema
    if clip.is_recorded:
        who = clip.recorded_player_name or "jugador"
        return "● grabado", SUCCESS, f"🎥 Cámara en {who} ✓", f"Cámara comprobada en {who} ({clip.camera_note})."
    if clip.recording_ok and clip.has_recording:
        return "⚠ regrabar", ACCENT, "🎥 Cámara sin comprobar", "Grabado con una versión anterior que no comprobaba a quién sigue la cámara. Vuelve a grabarlo."
    if clip.camera_note:
        return "✗ falló", DANGER, f"✗ {clip.camera_note}", clip.camera_note
    return "○ sin grabar", TEXT_MUTED, "", ""


# ------------------------------------------------------------ miniaturas ---


class _ThumbSignals(QObject):
    ready = Signal(str, str)  # clave, ruta del jpg


class _ThumbJob(QRunnable):
    def __init__(self, key: str, source: str, at: float, target: Path, signals: _ThumbSignals) -> None:
        super().__init__()
        self.key, self.source, self.at, self.target, self.signals = key, source, at, target, signals

    def run(self) -> None:
        from clutchreel.core.export.ffmpeg import FFmpeg
        from clutchreel.services.config import get_config
        from clutchreel.utils.winutil import subprocess_flags

        ff = FFmpeg(get_config().paths.ffmpeg_path)
        if not ff.path:
            return
        self.target.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.target.with_suffix(".tmp.jpg")
        cmd = [str(ff.path), "-hide_banner", "-loglevel", "error", "-y", "-ss", f"{self.at:.2f}", "-i", self.source, "-frames:v", "1", "-vf", f"scale={THUMB_W * 2}:{THUMB_H * 2}:force_original_aspect_ratio=increase,crop={THUMB_W * 2}:{THUMB_H * 2}", "-q:v", "4", str(tmp)]
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=False, creationflags=subprocess_flags())
            if tmp.exists() and tmp.stat().st_size > 0:
                tmp.replace(self.target)
                self.signals.ready.emit(self.key, str(self.target))
        except (OSError, subprocess.SubprocessError) as exc:
            log.debug("Miniatura no generada para %s: %s", self.source, exc)


class ThumbnailLoader:
    """Fotogramas de las grabaciones para las tarjetas: se sacan en segundo plano (uno a la vez, sin
    frenar la interfaz) y se guardan en la caché; la tarjeta muestra mientras tanto su etiqueta."""

    _instance: ThumbnailLoader | None = None

    def __init__(self) -> None:
        self.signals = _ThumbSignals()
        self.pool = QThreadPool()
        self.pool.setMaxThreadCount(1)
        self._pending: set[str] = set()
        self.signals.ready.connect(lambda key, _p: self._pending.discard(key))

    @classmethod
    def get(cls) -> ThumbnailLoader:
        if cls._instance is None:
            cls._instance = ThumbnailLoader()
        return cls._instance

    @staticmethod
    def key_for(clip: Clip) -> tuple[str, Path] | None:
        if not clip.has_recording:
            return None
        src = Path(clip.recording_path)
        try:
            stamp = src.stat().st_mtime_ns
        except OSError:
            return None
        key = hashlib.sha1(f"{src}|{stamp}|{clip.recording_offset:.2f}".encode()).hexdigest()[:20]  # noqa: S324 - no criptográfico
        from clutchreel.utils.paths import cache_dir

        return key, cache_dir() / "miniaturas" / f"{key}.jpg"

    def request(self, clip: Clip) -> tuple[str, Path | None]:
        """Clave y, si ya existe, la ruta de la miniatura; si no, la encarga."""
        found = self.key_for(clip)
        if found is None:
            return "", None
        key, target = found
        if target.exists():
            return key, target
        if key not in self._pending:
            self._pending.add(key)
            at = clip.recording_offset + max(0.5, min(2.0, clip.recorded_duration_seconds(64.0) / 3))
            self.pool.start(_ThumbJob(key, clip.recording_path, at, target, self.signals))
        return key, None


def _rounded(pix: QPixmap, w: int, h: int, radius: float = 6.0) -> QPixmap:
    dpr = 2.0
    out = QPixmap(int(w * dpr), int(h * dpr))
    out.setDevicePixelRatio(dpr)
    out.fill(Qt.GlobalColor.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    path = QPainterPath()
    path.addRoundedRect(QRectF(0, 0, w, h), radius, radius)
    p.setClipPath(path)
    p.drawPixmap(QRectF(0, 0, w, h), pix, QRectF(pix.rect()))
    p.end()
    return out


# ---------------------------------------------------------------- tarjeta ---


class _KindStrip(QWidget):
    """Franja de color a la izquierda de la tarjeta (como la etiqueta de color de un clip)."""

    def __init__(self, color: str) -> None:
        super().__init__()
        self.color = QColor(color)
        self.setFixedWidth(4)

    def set_color(self, color: str) -> None:
        self.color = QColor(color)
        self.update()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(self.color)
        p.drawRoundedRect(QRectF(0, 6, 4, self.height() - 12), 2, 2)


def _tag_style(color: str) -> str:
    c = QColor(color)
    text = color if theme.current() is theme.DARK else c.darker(190).name()  # sobre fondo claro, el color en oscuro
    return (
        f"background: rgba({c.red()}, {c.green()}, {c.blue()}, {40 if theme.current() is theme.DARK else 70}); color: {text}; border-radius: 4px; padding: 1px 6px;"
        f" font-family: 'Bahnschrift SemiBold Condensed', 'Bahnschrift'; font-size: 13px;"
    )


class ClipCard(QFrame):
    toggled = Signal(str, bool)

    def __init__(self, clip: Clip, tickrate: float) -> None:
        super().__init__()
        self.clip_id = clip.id
        self.setObjectName("card")
        self.setProperty("selected", False)
        self._thumb_key = ""
        layout = QHBoxLayout(self)
        layout.setContentsMargins(6, 8, 12, 8)
        layout.setSpacing(10)
        kinds = clip.highlight.merged_kinds or [clip.highlight.kind]
        self.kind = main_kind(kinds)
        self.strip = _KindStrip(kind_color(self.kind))
        layout.addWidget(self.strip)
        self.check = QCheckBox()
        self.check.setChecked(clip.enabled)
        self.check.setToolTip("Incluir esta jugada en el vídeo")
        self.check.toggled.connect(lambda v: self.toggled.emit(self.clip_id, v))
        layout.addWidget(self.check)
        self.thumb = QLabel()
        self.thumb.setFixedSize(THUMB_W, THUMB_H)
        layout.addWidget(self.thumb)

        text = QVBoxLayout()
        text.setSpacing(3)
        top = QHBoxLayout()
        top.setSpacing(8)
        self.lbl_tag = QLabel(KIND_TAGS.get(self.kind, self.kind))
        self.lbl_tag.setStyleSheet(_tag_style(kind_color(self.kind)))
        self.lbl_tag.setSizePolicy(QSizePolicy.Policy.Fixed, QSizePolicy.Policy.Fixed)
        self.lbl_title = ElidedLabel(clip.highlight.label)
        self.lbl_title.setObjectName("cardTitle")
        top.addWidget(self.lbl_tag)
        top.addWidget(self.lbl_title, 1)
        self.lbl_desc = ElidedLabel(clip.highlight.description)
        self.lbl_desc.setObjectName("cardMeta")
        self.lbl_camera = ElidedLabel("")
        text.addLayout(top)
        text.addWidget(self.lbl_desc)
        text.addWidget(self.lbl_camera)
        text.addStretch()
        layout.addLayout(text, 1)

        meta = QVBoxLayout()
        meta.setSpacing(4)
        self.lbl_score = QLabel(f"{clip.highlight.score:.0f} pts")
        self.lbl_score.setObjectName("badge")
        self.lbl_score.setToolTip("Puntuación de la jugada")
        self.lbl_dur = QLabel(format_duration(clip.duration_seconds(tickrate)))
        self.lbl_dur.setObjectName("duration")
        self.lbl_dur.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_round = QLabel(f"Ronda {clip.highlight.round}")
        self.lbl_round.setObjectName("cardMeta")
        self.lbl_round.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.lbl_rec = QLabel("")
        self.lbl_rec.setAlignment(Qt.AlignmentFlag.AlignRight)
        meta.addWidget(self.lbl_score, alignment=Qt.AlignmentFlag.AlignRight)
        meta.addWidget(self.lbl_dur)
        meta.addWidget(self.lbl_round)
        meta.addWidget(self.lbl_rec)
        meta.addStretch()
        layout.addLayout(meta)
        ThumbnailLoader.get().signals.ready.connect(self._on_thumb_ready)
        self._show_recording(clip)
        self._show_thumb(clip)

    # ------------------------------------------------------------ estado ---

    def _show_thumb(self, clip: Clip) -> None:
        key, path = ThumbnailLoader.get().request(clip)
        self._thumb_key = key
        if path is not None:
            self._set_thumb_file(str(path))
        else:
            self.thumb.setPixmap(icons.kind_placeholder(self.kind, KIND_TAGS.get(self.kind, self.kind), THUMB_W, THUMB_H))

    def _set_thumb_file(self, path: str) -> None:
        pix = QPixmap(path)
        if not pix.isNull():
            self.thumb.setPixmap(_rounded(pix, THUMB_W, THUMB_H))

    def _on_thumb_ready(self, key: str, path: str) -> None:
        if key and key == self._thumb_key:
            self._set_thumb_file(path)

    def _show_recording(self, clip: Clip) -> None:
        text, color, camera, tip = recording_status(clip)
        self.lbl_rec.setText(text)
        self.lbl_rec.setStyleSheet(f"color: {color}; font-size: 12px;")
        self.lbl_camera.setText(camera)
        self.lbl_camera.setStyleSheet(f"color: {color if camera.startswith('✗') else theme.current().muted}; font-size: 12px;")
        self.lbl_camera.setVisible(bool(camera))
        self.lbl_camera.setToolTip(tip)
        self.lbl_rec.setToolTip(tip)

    def refresh(self, clip: Clip, tickrate: float) -> None:
        self.check.blockSignals(True)
        self.check.setChecked(clip.enabled)
        self.check.blockSignals(False)
        self.lbl_title.setText(clip.highlight.label)
        self.lbl_desc.setText(clip.highlight.description)
        self.lbl_score.setText(f"{clip.highlight.score:.0f} pts")
        self.lbl_dur.setText(format_duration(clip.duration_seconds(tickrate)))
        self.lbl_round.setText(f"Ronda {clip.highlight.round}")
        self._show_recording(clip)
        key = ThumbnailLoader.key_for(clip)
        if (key[0] if key else "") != self._thumb_key:
            self._show_thumb(clip)

    def set_selected(self, selected: bool) -> None:
        self.setProperty("selected", selected)
        self.style().unpolish(self)
        self.style().polish(self)
