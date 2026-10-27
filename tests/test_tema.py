"""Tema visual: contraste legible y estilo centralizado."""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from clutchreel.ui import theme


def _lum(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    rgb = [int(h[i : i + 2], 16) / 255 for i in (0, 2, 4)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a: str, b: str) -> float:
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


@pytest.mark.parametrize("pal", [theme.DARK, theme.LIGHT], ids=["oscuro", "claro"])
def test_text_pairs_meet_wcag_aa(pal: theme.Palette) -> None:
    for fg, bg in (
        (pal.text, pal.bg),
        (pal.text, pal.panel),
        (pal.text, pal.raised),
        (pal.muted, pal.panel),
        (pal.muted, pal.bg),
        (pal.accent_ink, pal.accent),
        (pal.danger, pal.raised),
    ):
        assert contrast(fg, bg) >= 4.5, (fg, bg)
    assert contrast(pal.success, pal.raised) >= 3.0  # «● grabado» (texto pequeño en negrita de estado)


def test_kind_colors_are_readable_on_dark_cards() -> None:
    for kind, color in theme.KIND_COLORS.items():
        assert contrast(color, theme.DARK.raised) >= 4.5, kind


def test_every_detected_kind_has_color_and_tag() -> None:
    from clutchreel.core.demo.models import KIND_LABELS

    for kind in KIND_LABELS:
        if kind == "all_kills":
            continue
        assert kind in theme.KIND_COLORS and kind in theme.KIND_TAGS, kind
    assert theme.main_kind(["2k", "ace", "entry"]) == "ace"


def test_no_hard_coded_colors_outside_the_theme() -> None:
    """El estilo vive en theme.py: ningún otro módulo de la interfaz define colores hexadecimales."""
    ui = Path(theme.__file__).parent
    offenders = []
    for path in ui.rglob("*.py"):
        if path.name == "theme.py":
            continue
        if re.search(r"#[0-9a-fA-F]{6}\b", path.read_text(encoding="utf-8")):
            offenders.append(path.name)
    assert offenders == []


def test_stylesheet_builds_for_both_themes(tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for name in ("oscuro", "claro"):
        qss = theme.stylesheet(name)
        assert theme.palette(name).accent in qss and "url(" in qss  # flechas y ✓ dibujados
    assert theme.current() is theme.LIGHT
    theme.stylesheet("oscuro")
