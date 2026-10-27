"""Zona de arrastrar y soltar demos (.dem), con aspecto de claqueta."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QRectF, Qt, QVariantAnimation, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QPainter, QPainterPath, QPen
from PySide6.QtWidgets import QFileDialog, QFrame, QLabel, QPushButton, QVBoxLayout

from clutchreel.ui import icons, theme

BAND = 14  # alto de la franja de claqueta


class DropZone(QFrame):
    files_dropped = Signal(list)  # list[Path]

    def __init__(self, start_dir: str = "") -> None:
        super().__init__()
        self.start_dir = start_dir
        self.setAcceptDrops(True)
        self.setObjectName("dropzone")
        self.setMinimumHeight(220)
        self._glow = 0.0  # 0 = reposo, 1 = arrastrando una demo encima
        self._anim = QVariantAnimation(self)
        self._anim.setDuration(160)
        self._anim.valueChanged.connect(self._set_glow)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, BAND + 18, 24, 22)
        layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.setSpacing(8)
        icon = QLabel()
        icon.setPixmap(icons.pixmap("demo", theme.current().accent, 44))
        icon.setAlignment(Qt.AlignmentFlag.AlignCenter)
        icon.setStyleSheet("background: transparent; border: none;")
        title = QLabel("Arrastra aquí tus demos (.dem)")
        title.setObjectName("section")
        title.setStyleSheet("font-size: 24px; background: transparent; border: none;")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub = QLabel("Puedes soltar varias a la vez. También puedes elegirlas con el botón.")
        sub.setObjectName("muted")
        sub.setStyleSheet("background: transparent; border: none;")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        btn = QPushButton("Elegir demos…")
        btn.setCursor(Qt.CursorShape.PointingHandCursor)
        btn.clicked.connect(self.browse)
        layout.addWidget(icon)
        layout.addWidget(title)
        layout.addWidget(sub)
        layout.addSpacing(6)
        layout.addWidget(btn, alignment=Qt.AlignmentFlag.AlignCenter)

    # ------------------------------------------------------------ dibujo ---

    def _set_glow(self, value: object) -> None:
        self._glow = float(value)  # type: ignore[arg-type]
        self.update()

    def _animate_to(self, target: float) -> None:
        self._anim.stop()
        self._anim.setStartValue(self._glow)
        self._anim.setEndValue(target)
        self._anim.start()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1, 1, -1, -1)
        shape = QPainterPath()
        shape.addRoundedRect(r, 14, 14)
        bg = QColor(theme.current().panel)
        p.fillPath(shape, bg)
        if self._glow > 0:
            wash = QColor(theme.current().accent)
            wash.setAlpha(int(22 * self._glow))
            p.fillPath(shape, wash)
        # Franja diagonal superior, como el brazo de una claqueta.
        p.save()
        p.setClipPath(shape)
        p.setClipRect(QRectF(r.left(), r.top(), r.width(), BAND), Qt.ClipOperation.IntersectClip)
        p.fillRect(QRectF(r.left(), r.top(), r.width(), BAND), QColor(theme.current().raised))
        stripe = QColor(theme.current().accent)
        stripe.setAlpha(int(90 + 120 * self._glow))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(stripe)
        x = r.left() - BAND
        while x < r.right() + BAND:
            band = QPainterPath()
            band.moveTo(x, r.top() + BAND)
            band.lineTo(x + BAND, r.top())
            band.lineTo(x + BAND * 2, r.top())
            band.lineTo(x + BAND, r.top() + BAND)
            band.closeSubpath()
            p.drawPath(band)
            x += BAND * 3
        p.restore()
        border = QColor(theme.current().line) if self._glow <= 0 else QColor(theme.current().accent)
        if 0 < self._glow < 1:
            line = QColor(theme.current().line)
            border = QColor(
                int(line.red() + (QColor(theme.current().accent).red() - line.red()) * self._glow),
                int(line.green() + (QColor(theme.current().accent).green() - line.green()) * self._glow),
                int(line.blue() + (QColor(theme.current().accent).blue() - line.blue()) * self._glow),
            )
        pen = QPen(border, 1.5 + self._glow)
        pen.setStyle(Qt.PenStyle.DashLine if self._glow < 0.5 else Qt.PenStyle.SolidLine)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawPath(shape)

    # ------------------------------------------------------------ eventos ---

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(".dem") for u in event.mimeData().urls()):
            event.acceptProposedAction()
            self._animate_to(1.0)
        else:
            event.ignore()

    def dragLeaveEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        self._animate_to(0.0)
        super().dragLeaveEvent(event)

    def dropEvent(self, event: QDropEvent) -> None:
        self._animate_to(0.0)
        paths = [Path(u.toLocalFile()) for u in event.mimeData().urls() if u.toLocalFile().lower().endswith(".dem")]
        if paths:
            self.files_dropped.emit(paths)
        event.acceptProposedAction()

    def browse(self) -> None:
        files, _ = QFileDialog.getOpenFileNames(self, "Elegir demos de CS2", self.start_dir, "Demos de CS2 (*.dem)")
        if files:
            self.files_dropped.emit([Path(f) for f in files])
