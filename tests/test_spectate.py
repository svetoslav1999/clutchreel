"""Seguimiento y verificación de la cámara (datos reales de CS2 1.41.9 capturados el 26/10/2026)."""

from __future__ import annotations

from clutchreel.core.recorder.spectate import (
    DemoTimeline,
    PlaybackCheck,
    camera_on_target,
    parse_getpos,
    parse_trueview,
)

JUGADOR = 76561198000000101
COMPANERO = 76561198000000102

# Filas con el formato de parse_ticks (coordenadas reales de Mirage, nombres y SteamIDs sintéticos).
ROWS = [
    {"tick": 50000, "steamid": JUGADOR, "name": "♛Jugador Uno♛", "user_id": 3, "X": -1147.066162, "Y": -642.418701, "Z": -167.96875, "is_alive": True},
    {"tick": 50000, "steamid": COMPANERO, "name": "companero2", "user_id": 2, "X": -258.058167, "Y": -1875.141479, "Z": -167.96875, "is_alive": True},
]


def _timeline() -> DemoTimeline:
    tl = DemoTimeline("x.dem")
    tl.add_rows(ROWS)
    return tl


def test_parse_real_console_lines() -> None:
    assert parse_getpos("setpos -1147.066162 -642.418701 -104.000000;setang 0.988637 13.702653 0.000000") == (-1147.066162, -642.418701, -104.0)
    assert parse_getpos("nada") is None
    # Líneas reales: el nombre solo aparece en «Added TrueView prediction…»; «TrueView active» lleva solo el slot.
    real = "TrueView inactive\nAdded TrueView prediction for player slot 3 (♛Jugador Uno♛)\nTrueView active for slot 3\nScanned 873 entities"
    assert parse_trueview(real) == (3, "♛Jugador Uno♛")
    assert parse_trueview("TrueView active for slot 3") is None
    two = real + "\nAdded TrueView prediction for player slot 8 (rival8)\nTrueView active for slot 8"
    assert parse_trueview(two) == (8, "rival8")
    from clutchreel.core.recorder.spectate import parse_trueview_all

    assert parse_trueview_all(two) == [(3, "♛Jugador Uno♛"), (8, "rival8")]


def test_identify_player_from_real_getpos() -> None:
    tl = _timeline()
    # getpos real con la cámara en primera persona sobre JUGADOR (spec_player 4): ojo = Z + 64
    m = tl.identify((-1147.066162, -642.418701, -104.0), 50000, target=JUGADOR)
    assert m is not None and m.steamid64 == JUGADOR and m.distance < 1.0
    assert camera_on_target(m, JUGADOR)
    # El bug original: spec_player 3 (= user_id) ponía la cámara en companero2 (slot 2).
    wrong = tl.identify((-258.058167, -1875.141479, -104.0), 50000, target=JUGADOR)
    assert wrong is not None and wrong.name == "companero2" and not camera_on_target(wrong, JUGADOR)
    # Tercera persona (cámara detrás del jugador, a ~90 u): no se da por buena.
    assert not camera_on_target(tl.identify((-1240.3, -665.2, -102.3), 50000, target=JUGADOR), JUGADOR)


def test_slot_is_resolved_per_tick() -> None:
    tl = _timeline()
    tl.add_rows([{**ROWS[0], "tick": 90000, "user_id": 11}])  # reconexión: otro slot más tarde
    assert tl.slot_of(JUGADOR, 50000) == 3
    assert tl.slot_of(JUGADOR, 90000) == 11
    assert tl.slot_of(12345, 50000) is None


def test_dead_players_are_ignored_and_nan_rows_skipped() -> None:
    tl = DemoTimeline("x.dem")
    tl.add_rows([{**ROWS[0], "is_alive": False}, {**ROWS[1], "X": float("nan")}])
    assert tl.identify((-1147.0, -642.4, -104.0), 50000) is None
    assert not tl.is_alive(JUGADOR, 50000)


def test_playback_check_ratio_and_description() -> None:
    ok = PlaybackCheck(samples=10, on_target=10)
    assert ok.ok() and ok.describe() == ""
    bad = PlaybackCheck(samples=10, on_target=6, off_target=[(3.2, "rival8"), (3.9, "rival8")])
    assert not bad.ok() and "rival8" in bad.describe() and "3.2" in bad.describe()
    assert PlaybackCheck().ok()  # sin muestras (clip muy corto) no se inventa un fallo
    # Un cambio de cámara anunciado por CS2 con el jugador vivo invalida el clip aunque getpos no lo haya pillado.
    sw = PlaybackCheck(samples=4, on_target=4, switches=[(2.5, "rival8")])
    assert not sw.ok() and "rival8" in sw.describe() and "anunciado" in sw.describe() and "2.5" in sw.describe()
