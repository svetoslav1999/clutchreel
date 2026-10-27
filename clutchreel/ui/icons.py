"""Iconos de línea dibujados con QPainter: un único trazo y estilo para toda la app (sin ficheros ni
fuentes de emoji, que Windows dibuja con estilos distintos según el sitio)."""

from __future__ import annotations

import functools
import math
from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPainterPath, QPen, QPixmap

from clutchreel.ui import theme

_GRID = 24.0  # los iconos se diseñan en una cuadrícula de 24×24


def _pen(color: str, width: float = 1.8) -> QPen:
    pen = QPen(QColor(color))
    pen.setWidthF(width)
    pen.setCapStyle(Qt.PenCapStyle.RoundCap)
    pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
    return pen


def _draw(name: str, p: QPainter, color: str) -> None:
    p.setPen(_pen(color))
    p.setBrush(Qt.BrushStyle.NoBrush)
    path = QPainterPath()
    if name == "home":
        path.moveTo(4, 11)
        path.lineTo(12, 4)
        path.lineTo(20, 11)
        path.moveTo(6.5, 9.5)
        path.lineTo(6.5, 20)
        path.lineTo(17.5, 20)
        path.lineTo(17.5, 9.5)
        path.moveTo(10, 20)
        path.lineTo(10, 14.5)
        path.lineTo(14, 14.5)
        path.lineTo(14, 20)
    elif name == "wizard":  # pasos de un recorrido: tres hitos unidos
        for x, y in ((5.0, 18.0), (12.0, 12.0), (19.0, 6.0)):
            path.addEllipse(QPointF(x, y), 2.2, 2.2)
        path.moveTo(6.8, 16.6)
        path.lineTo(10.2, 13.4)
        path.moveTo(13.8, 10.6)
        path.lineTo(17.2, 7.4)
    elif name == "review":  # línea de tiempo con clips
        path.addRoundedRect(QRectF(3, 6, 8, 5), 1.2, 1.2)
        path.addRoundedRect(QRectF(13, 6, 8, 5), 1.2, 1.2)
        path.addRoundedRect(QRectF(3, 14, 12, 5), 1.2, 1.2)
        path.moveTo(18, 14)
        path.lineTo(18, 19)
    elif name == "queue":
        for y in (6.5, 12.0, 17.5):
            path.moveTo(9, y)
            path.lineTo(20, y)
        p.drawPath(path)
        p.setBrush(QColor(color))
        for y in (6.5, 12.0, 17.5):
            p.drawEllipse(QPointF(5, y), 1.3, 1.3)
        return
    elif name == "settings":  # engranaje
        cx = cy = 12.0
        for i in range(8):
            a = i * math.pi / 4
            path.moveTo(cx + 6.2 * math.cos(a), cy + 6.2 * math.sin(a))
            path.lineTo(cx + 8.6 * math.cos(a), cy + 8.6 * math.sin(a))
        path.addEllipse(QPointF(cx, cy), 6.2, 6.2)
        path.addEllipse(QPointF(cx, cy), 2.6, 2.6)
    elif name == "demo":  # fichero de demo con flecha de entrada
        path.moveTo(7, 3)
        path.lineTo(15, 3)
        path.lineTo(19, 7)
        path.lineTo(19, 21)
        path.lineTo(5, 21)
        path.lineTo(5, 5)
        path.moveTo(15, 3)
        path.lineTo(15, 7)
        path.lineTo(19, 7)
        path.moveTo(12, 9.5)
        path.lineTo(12, 17)
        path.moveTo(8.8, 14)
        path.lineTo(12, 17)
        path.lineTo(15.2, 14)
    elif name == "record":
        path.addEllipse(QPointF(12, 12), 8, 8)
        p.drawPath(path)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(12, 12), 3.6, 3.6)
        return
    elif name == "film":  # crear vídeo: claqueta
        path.addRoundedRect(QRectF(3.5, 9, 17, 11), 1.5, 1.5)
        path.moveTo(3.5, 9)
        path.lineTo(5, 4.5)
        path.lineTo(20, 4.5)
        path.lineTo(20.5, 9)
        for x in (8.5, 13.0, 17.5):
            path.moveTo(x - 1.5, 4.5)
            path.lineTo(x - 3, 9)
    elif name == "play":
        path.moveTo(8, 5)
        path.lineTo(19, 12)
        path.lineTo(8, 19)
        path.closeSubpath()
    elif name == "pause":
        path.moveTo(9, 5.5)
        path.lineTo(9, 18.5)
        path.moveTo(15, 5.5)
        path.lineTo(15, 18.5)
    elif name == "folder":
        path.moveTo(3, 7)
        path.lineTo(9, 7)
        path.lineTo(11, 9)
        path.lineTo(21, 9)
        path.lineTo(21, 19)
        path.lineTo(3, 19)
        path.closeSubpath()
    elif name == "upload":
        path.moveTo(12, 16)
        path.lineTo(12, 4.5)
        path.moveTo(7.5, 9)
        path.lineTo(12, 4.5)
        path.lineTo(16.5, 9)
        path.moveTo(4.5, 15)
        path.lineTo(4.5, 19.5)
        path.lineTo(19.5, 19.5)
        path.lineTo(19.5, 15)
    elif name == "check":
        path.moveTo(5, 12.5)
        path.lineTo(10, 17)
        path.lineTo(19, 7)
    elif name == "cross":
        path.moveTo(6.5, 6.5)
        path.lineTo(17.5, 17.5)
        path.moveTo(17.5, 6.5)
        path.lineTo(6.5, 17.5)
    elif name == "warning":
        path.moveTo(12, 4)
        path.lineTo(21, 19.5)
        path.lineTo(3, 19.5)
        path.closeSubpath()
        path.moveTo(12, 10)
        path.lineTo(12, 14)
        path.moveTo(12, 16.8)
        path.lineTo(12, 16.9)
    elif name == "pending":  # reloj
        path.addEllipse(QPointF(12, 12), 8, 8)
        path.moveTo(12, 7.5)
        path.lineTo(12, 12)
        path.lineTo(15, 14)
    elif name == "running":  # arco de progreso
        p.drawArc(QRectF(4, 4, 16, 16), 90 * 16, -270 * 16)
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(20, 12), 1.6, 1.6)
        return
    elif name == "stop":
        path.addEllipse(QPointF(12, 12), 8, 8)
        path.moveTo(9, 15)
        path.lineTo(15, 9)
    elif name == "health":  # diagnóstico
        path.moveTo(3, 12)
        path.lineTo(8, 12)
        path.lineTo(10, 7)
        path.lineTo(14, 17)
        path.lineTo(16, 12)
        path.lineTo(21, 12)
    elif name == "log":
        path.addRoundedRect(QRectF(5, 3.5, 14, 17), 1.5, 1.5)
        for y in (8.5, 12.0, 15.5):
            path.moveTo(8.5, y)
            path.lineTo(15.5, y)
    elif name == "undo":
        path.moveTo(9, 6)
        path.lineTo(5, 10)
        path.lineTo(9, 14)
        path.moveTo(5, 10)
        path.cubicTo(13, 10, 19, 10, 19, 16)
        path.lineTo(19, 18)
    elif name == "redo":
        path.moveTo(15, 6)
        path.lineTo(19, 10)
        path.lineTo(15, 14)
        path.moveTo(19, 10)
        path.cubicTo(11, 10, 5, 10, 5, 16)
        path.lineTo(5, 18)
    elif name == "save":
        path.moveTo(5, 4)
        path.lineTo(16, 4)
        path.lineTo(20, 8)
        path.lineTo(20, 20)
        path.lineTo(4, 20)
        path.lineTo(4, 4)
        path.moveTo(8, 4)
        path.lineTo(8, 9)
        path.lineTo(15, 9)
        path.lineTo(15, 4)
    else:  # icono desconocido: punto
        p.setBrush(QColor(color))
        p.drawEllipse(QPointF(12, 12), 3, 3)
        return
    p.drawPath(path)


@functools.lru_cache(maxsize=256)
def pixmap(name: str, color: str = theme.DARK.text, size: int = 20) -> QPixmap:
    dpr = 2.0  # nítido también con escalado de pantalla
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    p.scale(size / _GRID, size / _GRID)
    _draw(name, p, color)
    p.end()
    return pix


def icon(name: str, color: str = theme.DARK.text, size: int = 20, active_color: str | None = None) -> QIcon:
    """Icono con versión «activa» (p. ej. botón de navegación seleccionado) en otro color."""
    ic = QIcon()
    ic.addPixmap(pixmap(name, color, size), QIcon.Mode.Normal, QIcon.State.Off)
    if active_color:
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Mode.Normal, QIcon.State.On)
        ic.addPixmap(pixmap(name, active_color, size), QIcon.Mode.Active, QIcon.State.Off)
    ic.addPixmap(pixmap(name, theme.DARK.disabled, size), QIcon.Mode.Disabled, QIcon.State.Off)
    return ic


def brand_mark(size: int = 36) -> QPixmap:
    """Monograma de ClutchReel: bobina de película estilizada sobre el acento (sin logos de terceros)."""
    dpr = 2.0
    pix = QPixmap(int(size * dpr), int(size * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    s = float(size)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.DARK.accent))
    p.drawRoundedRect(QRectF(0, 0, s, s), s * 0.24, s * 0.24)
    ink = QColor(theme.DARK.accent_ink)
    p.setPen(_pen(theme.DARK.accent_ink, s * 0.075))
    c = QPointF(s * 0.5, s * 0.5)
    p.drawEllipse(c, s * 0.3, s * 0.3)
    p.setBrush(ink)
    p.setPen(Qt.PenStyle.NoPen)
    for i in range(5):  # perforaciones de la bobina
        a = -math.pi / 2 + i * 2 * math.pi / 5
        p.drawEllipse(QPointF(c.x() + s * 0.16 * math.cos(a), c.y() + s * 0.16 * math.sin(a)), s * 0.045, s * 0.045)
    p.drawEllipse(c, s * 0.04, s * 0.04)
    p.end()
    return pix


def app_icon_pixmap(size: int = 128) -> QPixmap:
    return brand_mark(size)


def kind_placeholder(kind: str, label: str, width: int, height: int) -> QPixmap:
    """Miniatura de una jugada sin grabar: fondo tintado con el color de su tipo y la etiqueta grande."""
    dpr = 2.0
    pix = QPixmap(int(width * dpr), int(height * dpr))
    pix.setDevicePixelRatio(dpr)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    color = QColor(theme.kind_color(kind))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor(theme.DARK.bg))
    p.drawRoundedRect(QRectF(0, 0, width, height), 6, 6)
    tint = QColor(color)
    tint.setAlpha(38)
    p.setBrush(tint)
    p.drawRoundedRect(QRectF(0, 0, width, height), 6, 6)
    # Diagonales finas, como el patrón de una claqueta.
    stripe = QColor(color)
    stripe.setAlpha(28)
    p.setPen(_pen(stripe.name(QColor.NameFormat.HexArgb), 6))
    p.setClipRect(QRectF(0, 0, width, height))
    for x in range(-height, width + height, 22):
        p.drawLine(QPointF(x, height), QPointF(x + height, 0))
    p.setClipping(False)
    font = QFont(theme.TAG_FAMILY)
    font.setPixelSize(max(14, int(height * (0.42 if len(label) <= 4 else 0.26))))
    p.setFont(font)
    p.setPen(color)
    p.drawText(QRectF(0, 0, width, height), Qt.AlignmentFlag.AlignCenter, label)
    p.end()
    return pix


def ui_image_path(name: str, color: str) -> str:
    """PNG para la hoja de estilo (✓ de las casillas, flechas de desplegables): QSS necesita un fichero.
    Se generan una vez en la caché."""
    from clutchreel.utils.paths import cache_dir

    target = cache_dir() / "ui" / f"{name}_{color.lstrip('#')}_v1.png"
    if not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        pix = QPixmap(36, 36)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.scale(36 / _GRID, 36 / _GRID)
        p.setPen(_pen(color, 3.0 if name == "check" else 2.4))
        path = QPainterPath()
        if name == "check":
            path.moveTo(5.5, 12.5)
            path.lineTo(10, 17)
            path.lineTo(18.5, 7.5)
        elif name == "chevron_down":
            path.moveTo(7, 9.5)
            path.lineTo(12, 14.5)
            path.lineTo(17, 9.5)
        elif name == "chevron_up":
            path.moveTo(7, 14.5)
            path.lineTo(12, 9.5)
            path.lineTo(17, 14.5)
        p.drawPath(path)
        p.end()
        pix.save(str(target))
    return Path(target).as_posix()
