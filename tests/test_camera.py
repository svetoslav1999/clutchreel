"""Grabación con verificación de la cámara (CS2 y OBS falsos)."""

from __future__ import annotations

from clutchreel.core.demo.detectors import DetectionContext, clamp_to_death
from clutchreel.core.demo.models import Highlight
from clutchreel.core.editor.project import new_project
from clutchreel.core.recorder.cs2_control import Cs2Error
from clutchreel.core.recorder.recorder import plan_clip
from clutchreel.core.recorder.spectate import SpectateError
from clutchreel.services.config import DetectionSettings, ScoringWeights, StyleSettings
from clutchreel.ui.widgets.clip_card import recording_status
from tests.conftest import ME
from tests.test_recorder import ON_ENEMY, ON_ME, FakeTimeline, make_recorder, project  # noqa: F401  (fixture)


def test_camera_on_wrong_player_fails_clip_with_reason(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    cs2.cam = ON_ENEMY  # ningún método consigue poner la cámara en mí
    session = r.record_project(project, lambda m, f: None)
    clip = project.clips[0]
    assert session.done == 0 and not clip.recording_ok and not clip.camera_verified
    assert "Cámara en el jugador equivocado" in session.jobs[0].error and "enemy1" in session.jobs[0].error
    assert "start" not in obs.calls  # nunca se graba con la cámara mal
    # Métodos en orden: slot (+1), nombre y recorrido con spec_next
    assert cs2.sent.index("spec_player 4") < cs2.sent.index('spec_player "yo"') < cs2.sent.index("spec_next")
    assert recording_status(clip)[0] == "✗ falló"


def test_camera_recovers_by_name_when_slot_is_wrong(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    cs2.camera_fn = lambda sent: ON_ME if 'spec_player "yo"' in sent else ON_ENEMY
    session = r.record_project(project, lambda m, f: None)
    clip = project.clips[0]
    assert session.done == 1 and clip.camera_verified and clip.camera_note.startswith("nombre")
    text, _color, camera, _tip = recording_status(clip)
    assert text == "● grabado" and "yo" in camera


def test_camera_switching_player_mid_recording_fails_clip(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    def camera(sent: list[str]) -> tuple[float, float, float]:
        # En pausa la cámara está en mí; al reanudar salta a otro jugador.
        last_resume = max((i for i, c in enumerate(sent) if c == "resume"), default=-1)
        last_pause = max((i for i, c in enumerate(sent) if c == "pause"), default=-1)
        return ON_ENEMY if last_resume > last_pause else ON_ME

    cs2.camera_fn = camera
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0
    assert "durante la grabación" in session.jobs[0].error and "enemy1" in session.jobs[0].error
    assert not list(tmp_path.glob("rec*.mkv"))  # la grabación inválida se descarta


def test_unreadable_console_never_marks_clip_as_good(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    cs2.readable = False
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0 and "no se pudo comprobar" in session.jobs[0].error


def test_old_unverified_recording_is_recorded_again(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, _obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    old = tmp_path / "vieja.mkv"
    old.write_bytes(b"x")
    project.clips[0].recording_ok = True
    project.clips[0].recording_path = str(old)  # grabado por una versión sin verificación de cámara
    assert recording_status(project.clips[0])[0] == "⚠ regrabar"
    session = r.record_project(project, lambda m, f: None)
    assert len(session.jobs) == 2 and project.clips[0].is_recorded


def test_plan_ends_clip_one_second_after_player_death(match) -> None:  # type: ignore[no-untyped-def]
    hl = Highlight("clutch", 2, 9200, 11500, 80.0, "clutch", key_tick=10200)
    p = new_project(match, ME, "yo", [hl], StyleSettings())
    plan = plan_clip(p, p.clips[0], 64.0)
    assert plan.death_tick == 11000 and plan.end_tick == 11051  # 0,8 s tras la muerte
    assert plan.start_tick == 9200 - 64 and plan.play_tick == 9200
    # El margen previo no se sale de la ronda (la ronda 2 empieza en 8000).
    p2 = new_project(match, ME, "yo", [Highlight("entry", 2, 8020, 8200, 10.0, "e", key_tick=8100)], StyleSettings())
    assert plan_clip(p2, p2.clips[0], 64.0).start_tick == 8000


def test_dead_player_at_start_is_not_followed(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]

    def dead_timeline(path: str) -> FakeTimeline:
        tl = FakeTimeline(path)
        tl.dead_from = 0
        return tl

    r.timeline_factory = dead_timeline
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0 and "muerto" in session.jobs[0].error and "start" not in obs.calls


def test_spectate_error_is_not_a_console_error() -> None:
    # Se explica como «cámara en el jugador equivocado», no como «CS2 no respondió».
    assert not issubclass(SpectateError, Cs2Error)


def test_highlight_ends_one_second_after_player_death(match) -> None:  # type: ignore[no-untyped-def]
    ctx = DetectionContext(match, ME, DetectionSettings(), ScoringWeights())
    hl = Highlight("clutch", 2, 9200, 11500, 1.0, "x")
    clamp_to_death(ctx, hl)
    assert hl.end_tick == 11000 + 51  # muere en 11000; 0,8 s de animación y la cámara se va al asesino
    alive = Highlight("3k", 1, 1300, 2100, 1.0, "x")
    clamp_to_death(ctx, alive)
    assert alive.end_tick == 2100
