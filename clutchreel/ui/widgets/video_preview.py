"""Reproductor de vista previa (QtMultimedia) con barra de posición."""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QVBoxLayout, QWidget

from clutchreel.ui import icons, theme
from clutchreel.utils.timeutil import format_duration

log = logging.getLogger(__name__)


class VideoPreview(QWidget):
    def __init__(self) -> None:
        super().__init__()
        self._player = None
        self._audio = None
        self._video = None
        self._range: tuple[float, float] | None = None
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel("Sin vista previa todavía.\nGraba o selecciona un vídeo para verlo aquí.")
        self.placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.placeholder.setObjectName("muted")
        self.placeholder.setMinimumHeight(200)
        layout.addWidget(self.placeholder, 1)
        try:
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
            from PySide6.QtMultimediaWidgets import QVideoWidget

            self._video = QVideoWidget()
            self._video.setMinimumHeight(200)
            self._video.setStyleSheet("background: black; border-radius: 10px;")
            self._player = QMediaPlayer()
            self._audio = QAudioOutput()
            self._player.setAudioOutput(self._audio)
            self._player.setVideoOutput(self._video)
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
            self._player.errorOccurred.connect(lambda _e, msg: self._show_error(msg))
            layout.addWidget(self._video, 1)
            self._video.hide()
        except Exception as exc:  # noqa: BLE001
            log.warning("QtMultimedia no disponible: %s", exc)
        controls = QHBoxLayout()
        self.btn_play = QPushButton("")
        self.btn_play.setIcon(icons.icon("play", theme.current().text, 16))
        self.btn_play.setToolTip("Reproducir / pausar")
        self.btn_play.setFixedWidth(44)
        self.btn_play.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 1000)
        self.slider.sliderMoved.connect(self._seek_slider)
        self.lbl_time = QLabel("0:00 / 0:00")
        self.lbl_time.setObjectName("muted")
        controls.addWidget(self.btn_play)
        controls.addWidget(self.slider, 1)
        controls.addWidget(self.lbl_time)
        layout.addLayout(controls)
        self._duration_ms = 0

    @property
    def available(self) -> bool:
        return self._player is not None

    def load(self, path: Path | str, start: float = 0.0, end: float = 0.0, autoplay: bool = True) -> None:
        if not self._player or not self._video:
            self.placeholder.setText(f"Vista previa no disponible.\n{path}")
            return
        p = Path(path)
        if not p.exists():
            self._show_error("El fichero no existe")
            return
        self._range = (start, end) if end > start else None
        self.placeholder.hide()
        self._video.show()
        self._player.setSource(QUrl.fromLocalFile(str(p)))
        if start > 0:
            self._player.setPosition(int(start * 1000))
        if autoplay:
            self._player.play()
            self.btn_play.setIcon(icons.icon("pause", theme.current().text, 16))
        else:
            # Reproduce y pausa para que se vea el primer fotograma.
            self._player.play()
            self._player.pause()
            self.btn_play.setIcon(icons.icon("play", theme.current().text, 16))

    def stop(self) -> None:
        if self._player:
            self._player.stop()
            self.btn_play.setIcon(icons.icon("play", theme.current().text, 16))

    def toggle(self) -> None:
        if not self._player:
            return
        from PySide6.QtMultimedia import QMediaPlayer

        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
            self.btn_play.setIcon(icons.icon("play", theme.current().text, 16))
        else:
            if self._range and self._player.position() >= int(self._range[1] * 1000) - 50:
                self._player.setPosition(int(self._range[0] * 1000))
            self._player.play()
            self.btn_play.setIcon(icons.icon("pause", theme.current().text, 16))

    def _on_duration(self, ms: int) -> None:
        self._duration_ms = ms

    def _on_position(self, ms: int) -> None:
        if self._duration_ms > 0:
            self.slider.blockSignals(True)
            self.slider.setValue(int(1000 * ms / self._duration_ms))
            self.slider.blockSignals(False)
        self.lbl_time.setText(f"{format_duration(ms / 1000)} / {format_duration(self._duration_ms / 1000)}")
        if self._range and ms >= int(self._range[1] * 1000) and self._player:
            self._player.pause()
            self.btn_play.setIcon(icons.icon("play", theme.current().text, 16))

    def _seek_slider(self, value: int) -> None:
        if self._player and self._duration_ms:
            self._player.setPosition(int(self._duration_ms * value / 1000))

    def _show_error(self, msg: str) -> None:
        if self._video:
            self._video.hide()
        self.placeholder.setText(f"No se pudo reproducir el vídeo.\n{msg}")
        self.placeholder.show()
