"""Optimizaciones (fase 2 de mejoras): mismas salidas, menos trabajo."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from clutchreel.core.demo import parser as parser_mod
from clutchreel.core.demo.parser import _EventReader, parse_demo_cached


def _demo(path: Path, payload: bytes = b"A") -> Path:
    path.write_bytes(b"PBDEMS2\x00" + payload * 1_100_000)
    return path


def test_analysis_cache_returns_the_same_match_for_a_copy(match, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []

    def fake_parse(path, progress=None, cancel=None):  # type: ignore[no-untyped-def]
        calls.append(str(path))
        match.demo_path = str(path)
        return match

    monkeypatch.setattr(parser_mod, "parse_demo", fake_parse)
    first = _demo(tmp_path / "a.dem")
    m1 = parse_demo_cached(first)
    copy = tmp_path / "carpeta ñ" / "copia.dem"
    copy.parent.mkdir()
    copy.write_bytes(first.read_bytes())
    m2 = parse_demo_cached(copy)
    assert len(calls) == 1  # la copia se reconoce: no se vuelve a leer la demo
    assert m2.demo_path == str(copy)  # pero apunta a la copia, no al original
    d1, d2 = m1.to_dict(), m2.to_dict()
    for d in (d1, d2):
        d.pop("demo_path")
        d.pop("demo_date")
    assert json.dumps(d1, sort_keys=True) == json.dumps(d2, sort_keys=True)


def test_analysis_cache_never_mixes_different_demos(match, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    monkeypatch.setattr(parser_mod, "parse_demo", lambda path, progress=None, cancel=None: calls.append(str(path)) or match)
    parse_demo_cached(_demo(tmp_path / "a.dem", b"A"))
    parse_demo_cached(_demo(tmp_path / "b.dem", b"B"))
    assert len(calls) == 2


def test_analysis_cache_is_invalidated_by_a_new_analysis_version(match, tmp_path: Path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    calls: list[str] = []
    monkeypatch.setattr(parser_mod, "parse_demo", lambda path, progress=None, cancel=None: calls.append(str(path)) or match)
    demo = _demo(tmp_path / "a.dem")
    parse_demo_cached(demo)
    monkeypatch.setattr(parser_mod, "ANALYSIS_VERSION", parser_mod.ANALYSIS_VERSION + 1)
    parse_demo_cached(demo)
    assert len(calls) == 2


class _FakeParser:
    def __init__(self, multi_ok: bool) -> None:
        self.multi_ok = multi_ok
        self.single: list[str] = []

    def parse_events(self, names: list[str], player: list[str], other: list[str]) -> list[tuple[str, Any]]:
        if not self.multi_ok:
            raise RuntimeError("parse_events no disponible")
        return [(n, pd.DataFrame([{"tick": 1, "name": n}])) for n in names if n != "cs_win_panel_match"]

    def parse_event(self, name: str, **_kw: Any) -> Any:
        self.single.append(name)
        return pd.DataFrame([{"tick": 2, "name": name}])


def test_events_are_read_in_one_pass_with_fallback() -> None:
    fast = _FakeParser(multi_ok=True)
    reader = _EventReader(fast)
    assert reader.records("player_death") == [{"tick": 1, "name": "player_death"}]
    assert fast.single == []
    assert reader.records("cs_win_panel_match") == [{"tick": 2, "name": "cs_win_panel_match"}]  # ausente → lectura suelta
    old = _FakeParser(multi_ok=False)
    reader = _EventReader(old)
    assert reader.records("round_end") == [{"tick": 2, "name": "round_end"}]
    assert old.single == ["round_end"]


def test_numpy_is_not_imported_at_startup() -> None:
    """numpy (~0,25 s) solo hace falta al comprobar un clip, no al abrir la app."""
    import subprocess
    import sys

    code = "import sys, clutchreel.ui.main_window; print('numpy' in sys.modules)"
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, cwd=str(Path(__file__).resolve().parents[1]), env={**__import__("os").environ, "QT_QPA_PLATFORM": "offscreen"})
    assert out.stdout.strip() == "False", out.stderr[-500:]


@pytest.mark.parametrize("close_game", [False, True])
def test_game_is_minimized_after_recording_unless_closed(project, tmp_path, monkeypatch, close_game: bool) -> None:  # type: ignore[no-untyped-def]  # noqa: F811
    from tests.test_recorder import make_recorder

    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    r.config.cs2.close_game_when_done = close_game
    project.clips = project.clips[:1]
    r.record_project(project, lambda m, f: None)
    assert ("minimize" in cs2.sent) is (not close_game)
    assert ("quit" in cs2.sent) is close_game


from tests.test_recorder import project  # noqa: E402, F401  (fixture)
