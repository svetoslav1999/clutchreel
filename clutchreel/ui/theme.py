"""Tema visual de ClutchReel: TODO el estilo de la app sale de aquí.

Idea: una sala de montaje de torneo. Fondo grafito, un único acento naranja «señal» y, como en
los editores de vídeo, cada tipo de jugada lleva su etiqueta de color (franja de la tarjeta,
etiqueta y miniatura). Títulos y cifras en Bahnschrift (de serie en Windows 10/11, aire de
marcador de retransmisión); textos en Segoe UI. Para cambiar el aspecto basta con tocar los
tokens de este archivo.
"""

from __future__ import annotations

from dataclasses import dataclass

# ---------------------------------------------------------------- tokens ---


@dataclass(frozen=True)
class Palette:
    bg: str  # fondo de la ventana
    panel: str  # paneles y barra lateral
    raised: str  # tarjetas, botones
    raised_hover: str
    line: str  # bordes
    text: str
    muted: str  # texto secundario (contraste ≥ 4,5:1 sobre ``panel``)
    accent: str
    accent_hover: str
    accent_ink: str  # texto sobre el acento
    success: str
    danger: str
    disabled: str


DARK = Palette(
    bg="#111318",
    panel="#181b22",
    raised="#20242d",
    raised_hover="#272c37",
    line="#2e3441",
    text="#eceef2",
    muted="#9aa3b2",
    accent="#ff9f1c",
    accent_hover="#ffb347",
    accent_ink="#1c1204",
    success="#3dd68c",
    danger="#ff5c5c",
    disabled="#5d6575",
)

LIGHT = Palette(
    bg="#f3f4f7",
    panel="#ffffff",
    raised="#eceef3",
    raised_hover="#e2e5ec",
    line="#d5d9e2",
    text="#1b1f27",
    muted="#576071",
    accent="#e07a00",
    accent_hover="#f08a10",
    accent_ink="#1c1204",
    success="#14894f",
    danger="#b42318",
    disabled="#9aa1ad",
)

# Compatibilidad: nombres usados por los widgets (tema oscuro, el de siempre).
ACCENT = DARK.accent
ACCENT_HOVER = DARK.accent_hover
BG = DARK.bg
BG_PANEL = DARK.panel
BG_CARD = DARK.raised
BORDER = DARK.line
TEXT = DARK.text
TEXT_MUTED = DARK.muted
DANGER = DARK.danger
SUCCESS = DARK.success

# Tipografía (familias de serie en Windows; si faltan, Qt usa la siguiente de la lista).
FONT_DISPLAY = '"Bahnschrift SemiBold SemiCondensed", "Bahnschrift", "Segoe UI Semibold"'
FONT_TAG = '"Bahnschrift SemiBold Condensed", "Bahnschrift", "Segoe UI Semibold"'
FONT_BODY = '"Segoe UI Variable Text", "Segoe UI", sans-serif'
DISPLAY_FAMILY = "Bahnschrift SemiBold SemiCondensed"
TAG_FAMILY = "Bahnschrift SemiBold Condensed"

# Escala tipográfica (px): cuerpo 14, pequeño 12, etiquetas 13, subtítulo 15, sección 17, título 28.
SIZE_SMALL = 12
SIZE_BODY = 14
SIZE_TAG = 13
SIZE_SUB = 15
SIZE_SECTION = 17
SIZE_TITLE = 28

# Espaciado (múltiplos de 4) y radios: más redondeado cuanto más «objeto» es el elemento.
SPACE = 4
RADIUS_CONTROL = 6
RADIUS_CARD = 10
RADIUS_PANEL = 12

# ------------------------------------------------- colores por jugada ------

# Etiquetas de color por tipo de jugada, como las de los clips en un editor de vídeo.
KIND_COLORS: dict[str, str] = {
    "ace": "#ffc83d",  # oro
    "4k": "#ff6a3d",
    "3k": "#ff8a3d",
    "2k": "#ffa94d",
    "clutch": "#b18cff",  # violeta
    "headshot_streak": "#ff6fae",
    "entry": "#2fd6c0",  # verde azulado
    "awp": "#5aa8ff",
    "noscope": "#7cc4ff",
    "wallbang": "#38c6f4",
    "smoke": "#a7b6c9",
    "blind": "#f2e05c",
    "air": "#8ee3ff",
    "knife": "#ff5c7a",
    "decisive": "#ffd166",
    "best_round": "#ffe08a",
    "kill": "#9aa3b2",
}

# Etiqueta corta (miniatura y etiqueta de la tarjeta).
KIND_TAGS: dict[str, str] = {
    "ace": "ACE",
    "4k": "4K",
    "3k": "3K",
    "2k": "2K",
    "clutch": "Clutch",
    "headshot_streak": "Racha HS",
    "entry": "Entry",
    "awp": "AWP",
    "noscope": "No-scope",
    "wallbang": "Wallbang",
    "smoke": "Humo",
    "blind": "Cegado",
    "air": "Aire",
    "knife": "Cuchillo",
    "decisive": "Decisiva",
    "best_round": "Mejor ronda",
    "kill": "Kill",
}

# Orden de importancia para elegir el tipo principal de una jugada fusionada.
KIND_PRIORITY = ["ace", "clutch", "4k", "3k", "knife", "noscope", "wallbang", "headshot_streak", "2k", "smoke", "blind", "air", "awp", "entry", "decisive", "best_round", "kill"]


def main_kind(kinds: list[str]) -> str:
    for k in KIND_PRIORITY:
        if k in kinds:
            return k
    return kinds[0] if kinds else "kill"


def kind_color(kind: str) -> str:
    return KIND_COLORS.get(kind, DARK.muted)


# Estados de la cola: (color, icono).
STATUS_STYLE: dict[str, tuple[str, str]] = {
    "pendiente": (DARK.muted, "pending"),
    "en curso": (DARK.accent, "running"),
    "hecho": (DARK.success, "check"),
    "parcial": ("#f0a23e", "warning"),
    "error": (DARK.danger, "cross"),
    "cancelado": (DARK.muted, "stop"),
}


def palette(theme: str) -> Palette:
    return LIGHT if theme == "claro" else DARK


_current: Palette = DARK


def current() -> Palette:
    """Paleta del tema activo (para lo que se dibuja a mano: zona de arrastre, tarjetas, iconos)."""
    return _current


# ------------------------------------------------------------------ QSS ----


def build_qss(p: Palette, images: dict[str, str] | None = None) -> str:
    img = images or {}
    check_image = img.get("check", "")
    down = img.get("chevron_down", "")
    up = img.get("chevron_up", "")
    return f"""
* {{
    font-family: {FONT_BODY};
    font-size: {SIZE_BODY}px;
    color: {p.text};
}}
QMainWindow, QDialog, QWidget#root {{
    background: {p.bg};
}}
QWidget#sidebar {{
    background: {p.panel};
    border-right: 1px solid {p.line};
}}
QLabel#brand {{
    font-family: {FONT_DISPLAY};
    font-size: 22px;
    color: {p.text};
}}
QLabel#brandSub {{
    color: {p.muted};
    font-size: {SIZE_SMALL}px;
}}
QWidget#panel, QFrame#panel {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: {RADIUS_PANEL}px;
}}
QFrame#card {{
    background: {p.raised};
    border: 1px solid {p.line};
    border-radius: {RADIUS_CARD}px;
}}
QFrame#card:hover {{
    border-color: {p.muted};
}}
QFrame#card[selected="true"] {{
    border: 1px solid {p.accent};
    background: {p.raised_hover};
}}
QLabel#title {{
    font-family: {FONT_DISPLAY};
    font-size: {SIZE_TITLE}px;
}}
QLabel#subtitle {{
    font-size: {SIZE_SUB}px;
    color: {p.muted};
}}
QLabel#section {{
    font-family: {FONT_DISPLAY};
    font-size: {SIZE_SECTION}px;
}}
QLabel#muted {{
    color: {p.muted};
}}
QLabel#warning {{
    color: {p.accent};
    font-weight: 600;
}}
QLabel#badge {{
    background: {p.accent};
    color: {p.accent_ink};
    border-radius: 4px;
    padding: 1px 7px;
    font-family: {FONT_TAG};
    font-size: {SIZE_TAG}px;
}}
QLabel#cardTitle {{
    font-family: {FONT_DISPLAY};
    font-size: 16px;
}}
QLabel#cardMeta {{
    color: {p.muted};
    font-size: {SIZE_SMALL}px;
}}
QLabel#duration {{
    font-family: {FONT_TAG};
    font-size: 15px;
    color: {p.text};
}}
QPushButton {{
    background: {p.raised};
    border: 1px solid {p.line};
    border-radius: {RADIUS_CONTROL}px;
    padding: 7px 14px;
    min-height: 20px;
}}
QPushButton:hover {{
    border-color: {p.accent};
    background: {p.raised_hover};
}}
QPushButton:pressed {{
    background: {p.panel};
}}
QPushButton:focus {{
    border-color: {p.accent};
}}
QPushButton:disabled {{
    color: {p.disabled};
    border-color: {p.line};
    background: {p.panel};
}}
QPushButton#primary {{
    background: {p.accent};
    color: {p.accent_ink};
    border: 1px solid {p.accent};
    padding: 11px 22px;
    font-family: {FONT_DISPLAY};
    font-size: 17px;
}}
QPushButton#primary:hover {{
    background: {p.accent_hover};
    border-color: {p.accent_hover};
}}
QPushButton#primary:focus {{
    border: 2px solid {p.text};
}}
QPushButton#primary:disabled {{
    background: {p.raised};
    color: {p.disabled};
    border-color: {p.line};
}}
QPushButton#danger {{
    background: transparent;
    color: {p.danger};
    border: 1px solid {p.danger};
}}
QPushButton#danger:hover {{
    background: {p.danger};
    color: {p.accent_ink if p is LIGHT else "#1a0606"};
}}
QPushButton#danger:disabled {{
    color: {p.disabled};
    border-color: {p.line};
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    border-left: 3px solid transparent;
    border-radius: 0;
    text-align: left;
    padding: 11px 16px 11px 13px;
    font-size: 15px;
    color: {p.muted};
}}
QPushButton#nav:hover {{
    color: {p.text};
    background: {p.raised};
}}
QPushButton#nav:checked {{
    background: {p.raised};
    color: {p.text};
    border-left: 3px solid {p.accent};
    font-weight: 600;
}}
QPushButton#flat {{
    background: transparent;
    border: none;
    color: {p.accent};
    padding: 4px 8px;
}}
QPushButton#flat:hover {{
    text-decoration: underline;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {p.bg};
    border: 1px solid {p.line};
    border-radius: {RADIUS_CONTROL}px;
    padding: 6px 10px;
    selection-background-color: {p.accent};
    selection-color: {p.accent_ink};
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {{
    border-color: {p.accent};
}}
QComboBox::drop-down {{
    border: none;
    width: 26px;
}}
QComboBox::down-arrow {{
    {f"image: url({down});" if down else ""}
    width: 12px;
    height: 12px;
}}
QAbstractSpinBox {{
    padding-right: 22px;
}}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{
    subcontrol-origin: border;
    width: 20px;
    border: none;
    background: transparent;
}}
QAbstractSpinBox::up-button {{
    subcontrol-position: top right;
}}
QAbstractSpinBox::down-button {{
    subcontrol-position: bottom right;
}}
QAbstractSpinBox::up-button:hover, QAbstractSpinBox::down-button:hover {{
    background: {p.raised};
}}
QAbstractSpinBox::up-arrow {{
    {f"image: url({up});" if up else ""}
    width: 10px;
    height: 10px;
}}
QAbstractSpinBox::down-arrow {{
    {f"image: url({down});" if down else ""}
    width: 10px;
    height: 10px;
}}
QComboBox QAbstractItemView {{
    background: {p.panel};
    border: 1px solid {p.line};
    selection-background-color: {p.raised_hover};
    selection-color: {p.text};
}}
QCheckBox, QRadioButton {{
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {p.muted};
    border-radius: 4px;
    background: {p.bg};
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:hover, QRadioButton::indicator:hover {{
    border-color: {p.accent};
}}
QCheckBox::indicator:checked {{
    background: {p.accent};
    border-color: {p.accent};
{f'    image: url({check_image});' if check_image else ''}
}}
QRadioButton::indicator:checked {{
    background: qradialgradient(cx:0.5, cy:0.5, radius:0.5, fx:0.5, fy:0.5, stop:0 {p.accent_ink}, stop:0.32 {p.accent_ink}, stop:0.4 {p.accent}, stop:1 {p.accent});
    border-color: {p.accent};
}}
QProgressBar {{
    background: {p.bg};
    border: 1px solid {p.line};
    border-radius: 4px;
    text-align: center;
    min-height: 22px;
    font-family: {FONT_TAG};
    font-size: {SIZE_TAG}px;
    color: {p.text};
}}
QProgressBar::chunk {{
    border-radius: 3px;
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #e8730c, stop:1 {p.accent});
}}
QSlider::groove:horizontal {{
    height: 4px;
    background: {p.line};
    border-radius: 2px;
}}
QSlider::handle:horizontal {{
    background: {p.text};
    border: 3px solid {p.accent};
    width: 10px;
    height: 10px;
    margin: -6px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {p.accent};
    border-radius: 2px;
}}
QListWidget, QTableWidget, QTreeWidget {{
    background: {p.panel};
    border: 1px solid {p.line};
    border-radius: {RADIUS_CARD}px;
    outline: none;
}}
QListWidget::item {{
    padding: 2px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: transparent;
}}
QListWidget#plainList::item {{
    padding: 6px 8px;
}}
QListWidget#plainList::item:hover {{
    background: {p.raised};
}}
QListWidget#plainList::item:selected {{
    background: {p.raised_hover};
}}
QTableWidget {{
    gridline-color: transparent;
}}
QTableWidget::item {{
    padding: 4px 6px;
}}
QTableWidget::item:selected {{
    background: {p.raised_hover};
    color: {p.text};
}}
QHeaderView::section {{
    background: {p.panel};
    border: none;
    border-bottom: 1px solid {p.line};
    padding: 6px;
    color: {p.muted};
    font-weight: 600;
}}
QTabWidget::pane {{
    border: 1px solid {p.line};
    border-radius: {RADIUS_CARD}px;
    top: -1px;
    background: {p.panel};
}}
QTabBar::tab {{
    background: transparent;
    padding: 9px 16px;
    border-bottom: 2px solid transparent;
    color: {p.muted};
}}
QTabBar::tab:hover {{
    color: {p.text};
}}
QTabBar::tab:selected {{
    color: {p.text};
    border-bottom: 2px solid {p.accent};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {p.line};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::handle:vertical:hover {{
    background: {p.muted};
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical, QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
    height: 0;
    background: transparent;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {p.line};
    border-radius: 5px;
    min-width: 30px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal, QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal {{
    width: 0;
    background: transparent;
}}
QScrollArea, QScrollArea > QWidget > QWidget#scrollBody {{
    border: none;
    background: transparent;
}}
QToolTip {{
    background: {p.raised};
    color: {p.text};
    border: 1px solid {p.line};
    padding: 6px;
}}
QGroupBox {{
    border: 1px solid {p.line};
    border-radius: {RADIUS_CARD}px;
    margin-top: 14px;
    padding: 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {p.muted};
}}
QStatusBar {{
    background: {p.panel};
    border-top: 1px solid {p.line};
    color: {p.muted};
}}
QMenu {{
    background: {p.panel};
    border: 1px solid {p.line};
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 4px;
}}
QMenu::item:selected {{
    background: {p.raised_hover};
}}
QSplitter::handle {{
    background: transparent;
    width: 8px;
}}
QSplitter::handle:hover {{
    background: {p.line};
}}
QMessageBox QLabel {{
    min-width: 320px;
}}
"""


def stylesheet(theme: str) -> str:
    """Hoja de estilo completa (llamar con la aplicación Qt ya creada: genera el ✓ de las casillas)."""
    global _current
    _current = palette(theme)
    try:
        from clutchreel.ui.icons import ui_image_path

        images = {
            "check": ui_image_path("check", _current.accent_ink),
            "chevron_down": ui_image_path("chevron_down", _current.muted),
            "chevron_up": ui_image_path("chevron_up", _current.muted),
        }
    except Exception:  # noqa: BLE001 - sin imágenes, casillas y desplegables siguen funcionando (solo color)
        images = {}
    return build_qss(_current, images)
