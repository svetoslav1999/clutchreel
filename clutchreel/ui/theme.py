"""Tema oscuro (QSS) y utilidades visuales."""

from __future__ import annotations

ACCENT = "#f5a524"
ACCENT_HOVER = "#ffb74d"
BG = "#0f1216"
BG_PANEL = "#161b22"
BG_CARD = "#1c2330"
BORDER = "#2a3342"
TEXT = "#e6edf3"
TEXT_MUTED = "#8b98a9"
DANGER = "#e5484d"
SUCCESS = "#3fb950"

DARK_QSS = f"""
* {{
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 14px;
    color: {TEXT};
}}
QMainWindow, QDialog, QWidget#root {{
    background: {BG};
}}
QWidget#sidebar {{
    background: {BG_PANEL};
    border-right: 1px solid {BORDER};
}}
QWidget#panel, QFrame#panel {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 12px;
}}
QFrame#card {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 10px;
}}
QFrame#card[selected="true"] {{
    border: 1px solid {ACCENT};
}}
QLabel#title {{
    font-size: 26px;
    font-weight: 700;
}}
QLabel#subtitle {{
    font-size: 15px;
    color: {TEXT_MUTED};
}}
QLabel#muted {{
    color: {TEXT_MUTED};
}}
QLabel#warning {{
    color: {ACCENT};
    font-weight: 600;
}}
QLabel#badge {{
    background: {ACCENT};
    color: #1a1a1a;
    border-radius: 9px;
    padding: 2px 8px;
    font-weight: 600;
    font-size: 12px;
}}
QPushButton {{
    background: {BG_CARD};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 8px 16px;
    min-height: 20px;
}}
QPushButton:hover {{
    border-color: {ACCENT};
    background: #222b3a;
}}
QPushButton:pressed {{
    background: #141a24;
}}
QPushButton:disabled {{
    color: #5c6878;
    border-color: #222a36;
}}
QPushButton#primary {{
    background: {ACCENT};
    color: #171717;
    font-weight: 700;
    border: none;
    padding: 12px 24px;
    font-size: 16px;
}}
QPushButton#primary:hover {{
    background: {ACCENT_HOVER};
}}
QPushButton#primary:disabled {{
    background: #5b4a26;
    color: #a89b85;
}}
QPushButton#danger {{
    background: {DANGER};
    color: white;
    border: none;
}}
QPushButton#nav {{
    background: transparent;
    border: none;
    text-align: left;
    padding: 12px 18px;
    border-radius: 8px;
    font-size: 15px;
}}
QPushButton#nav:hover {{
    background: {BG_CARD};
}}
QPushButton#nav:checked {{
    background: {BG_CARD};
    color: {ACCENT};
    font-weight: 600;
}}
QPushButton#flat {{
    background: transparent;
    border: none;
    color: {ACCENT};
    padding: 4px 8px;
}}
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QTextEdit, QPlainTextEdit {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 8px;
    padding: 6px 10px;
    selection-background-color: {ACCENT};
    selection-color: #111;
}}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus, QTextEdit:focus {{
    border-color: {ACCENT};
}}
QComboBox::drop-down {{
    border: none;
    width: 28px;
}}
QComboBox QAbstractItemView {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    selection-background-color: {BG_CARD};
}}
QCheckBox, QRadioButton {{
    spacing: 8px;
}}
QCheckBox::indicator, QRadioButton::indicator {{
    width: 18px;
    height: 18px;
    border: 1px solid {BORDER};
    border-radius: 4px;
    background: {BG};
}}
QRadioButton::indicator {{
    border-radius: 9px;
}}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{
    background: {ACCENT};
    border-color: {ACCENT};
}}
QProgressBar {{
    background: {BG};
    border: 1px solid {BORDER};
    border-radius: 7px;
    text-align: center;
    height: 16px;
}}
QProgressBar::chunk {{
    background: {ACCENT};
    border-radius: 6px;
}}
QSlider::groove:horizontal {{
    height: 6px;
    background: {BORDER};
    border-radius: 3px;
}}
QSlider::handle:horizontal {{
    background: {ACCENT};
    width: 16px;
    height: 16px;
    margin: -5px 0;
    border-radius: 8px;
}}
QSlider::sub-page:horizontal {{
    background: {ACCENT};
    border-radius: 3px;
}}
QListWidget, QTableWidget, QTreeWidget {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    border-radius: 10px;
    outline: none;
}}
QListWidget::item {{
    padding: 4px;
    border-radius: 8px;
}}
QListWidget::item:selected {{
    background: transparent;
}}
QTableWidget::item:selected {{
    background: {BG_CARD};
}}
QHeaderView::section {{
    background: {BG_PANEL};
    border: none;
    border-bottom: 1px solid {BORDER};
    padding: 6px;
    color: {TEXT_MUTED};
    font-weight: 600;
}}
QTabWidget::pane {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    top: -1px;
}}
QTabBar::tab {{
    background: transparent;
    padding: 10px 18px;
    border-bottom: 2px solid transparent;
    color: {TEXT_MUTED};
}}
QTabBar::tab:selected {{
    color: {ACCENT};
    border-bottom: 2px solid {ACCENT};
}}
QScrollBar:vertical {{
    background: transparent;
    width: 10px;
    margin: 0;
}}
QScrollBar::handle:vertical {{
    background: {BORDER};
    border-radius: 5px;
    min-height: 30px;
}}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
    height: 0;
}}
QScrollBar:horizontal {{
    background: transparent;
    height: 10px;
}}
QScrollBar::handle:horizontal {{
    background: {BORDER};
    border-radius: 5px;
}}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
    width: 0;
}}
QScrollArea {{
    border: none;
    background: transparent;
}}
QToolTip {{
    background: {BG_CARD};
    color: {TEXT};
    border: 1px solid {BORDER};
    padding: 6px;
}}
QGroupBox {{
    border: 1px solid {BORDER};
    border-radius: 10px;
    margin-top: 14px;
    padding: 12px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 12px;
    padding: 0 6px;
    color: {TEXT_MUTED};
}}
QStatusBar {{
    background: {BG_PANEL};
    border-top: 1px solid {BORDER};
    color: {TEXT_MUTED};
}}
QMenu {{
    background: {BG_PANEL};
    border: 1px solid {BORDER};
    padding: 6px;
}}
QMenu::item {{
    padding: 6px 18px;
    border-radius: 6px;
}}
QMenu::item:selected {{
    background: {BG_CARD};
}}
QSplitter::handle {{
    background: {BORDER};
}}
"""

LIGHT_QSS = DARK_QSS.replace(BG, "#f4f6f9").replace(BG_PANEL, "#ffffff").replace(BG_CARD, "#eef2f7").replace(BORDER, "#d7dee8").replace(TEXT, "#1d2430").replace(TEXT_MUTED, "#5b6878").replace("#222b3a", "#e3e9f2").replace("#141a24", "#dde4ee")


def stylesheet(theme: str) -> str:
    return LIGHT_QSS if theme == "claro" else DARK_QSS
