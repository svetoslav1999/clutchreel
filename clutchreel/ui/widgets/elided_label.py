"""Etiqueta de una línea que recorta con «…» cuando no cabe (y muestra el texto entero al pasar el ratón)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QPainter
from PySide6.QtWidgets import QLabel, QSizePolicy


class ElidedLabel(QLabel):
    def __init__(self, text: str = "") -> None:
        super().__init__()
        self._full = ""
        self.setTextFormat(Qt.TextFormat.PlainText)  # los nombres de jugador pueden contener «<»
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.setText(text)

    def setText(self, text: str) -> None:
        self._full = text or ""
        super().setText(self._full)
        self._update_tip()

    def text(self) -> str:
        return self._full

    def _update_tip(self) -> None:
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, max(0, self.width()))
        if elided != self._full:
            if not self.toolTip() or self.toolTip() == self.property("autoTip"):
                self.setToolTip(self._full)
                self.setProperty("autoTip", self._full)
        elif self.toolTip() == self.property("autoTip"):
            self.setToolTip("")

    def minimumSizeHint(self) -> QSize:
        return QSize(20, super().minimumSizeHint().height())

    def resizeEvent(self, event) -> None:  # type: ignore[no-untyped-def]
        super().resizeEvent(event)
        self._update_tip()

    def paintEvent(self, _event) -> None:  # type: ignore[no-untyped-def]
        p = QPainter(self)
        p.setPen(self.palette().color(self.foregroundRole()))
        p.setFont(self.font())
        rect = self.contentsRect()
        elided = self.fontMetrics().elidedText(self._full, Qt.TextElideMode.ElideRight, rect.width())
        p.drawText(rect, int(Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft), elided)
