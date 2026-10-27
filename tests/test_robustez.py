"""Regresiones de la revisión de errores (fase 1 de mejoras): procesos y ficheros huérfanos,
cancelación, datos dañados y secretos en los registros."""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time
from pathlib import Path

import pytest

from clutchreel.core.demo.models import RoundInfo
from clutchreel.core.demo.parser import DemoError, _round_for_tick, parse_demo
from clutchreel.core.editor.project import Project
from clutchreel.core.export import builder as b
from clutchreel.core.export import exporter as exp_mod
from clutchreel.core.export.ffmpeg import FFmpeg, FFmpegError
from clutchreel.core.recorder import recorder as rec_mod
from clutchreel.core.recorder.cs2_control import Cs2Controller, Cs2Error
from clutchreel.core.recorder.recorder import RecorderError
from clutchreel.services.config import Cs2Settings
from clutchreel.services.history import History, HistoryEntry
from clutchreel.utils.logging_setup import RedactingFilter, read_log_tail, redact, register_secret
from tests.test_recorder import make_recorder, project  # noqa: F401  (fixture)

# ------------------------------------------------------------ grabador -----


def test_failure_mid_recording_stops_obs_and_deletes_partial_file(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    """Antes: si CS2 fallaba con OBS grabando, el fichero a medias se quedaba en el disco."""
    r, obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    r.max_attempts = 1

    def broken_play_ticks(ticks: int) -> None:
        raise Cs2Error("Se perdió la conexión con la consola de CS2")

    cs2.play_ticks = broken_play_ticks  # type: ignore[method-assign]
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0
    assert not obs.recording  # OBS no se queda grabando
    assert obs.calls.count("start") == 1 and obs.calls.count("stop") == 1
    assert not list(tmp_path.glob("rec*.mkv"))  # la grabación incompleta se borró


def test_cancel_during_clip_deletes_partial_recording(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]

    def play_and_cancel(ticks: int) -> None:
        r.cancel.set()  # el usuario pulsa «Cancelar» con la jugada en marcha

    cs2.play_ticks = play_and_cancel  # type: ignore[method-assign]
    with pytest.raises(RecorderError, match="cancelada"):
        r.record_project(project, lambda m, f: None)
    assert not obs.recording
    assert not list(tmp_path.glob("rec*.mkv"))


def test_recording_refuses_to_start_without_disk_space(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    r, obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    monkeypatch.setattr(rec_mod, "free_disk_bytes", lambda _p: 500_000_000)
    with pytest.raises(RecorderError, match="libres"):
        r.record_project(project, lambda m, f: None)
    assert "start" not in obs.calls


def test_recording_status_is_reported_once_per_second(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    """Antes el bucle de grabación avisaba 20 veces por segundo (repintando toda la interfaz)."""
    r, _obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    messages: list[str] = []
    r.record_project(project, lambda m, f: messages.append(m))
    rec = [m for m in messages if m.startswith("Grabando… ")]
    assert rec and len(rec) == len(set(rec))


def test_cs2_waits_stop_when_cancelled() -> None:
    """Antes, cancelar no cortaba los saltos de demo ni las esperas de carga (hasta 2 min)."""
    cs2 = Cs2Controller(Cs2Settings(seek_wait=6.0))
    cs2.channel = "keyboard"  # sin consola legible: espera por reloj
    cs2.send = lambda commands: None  # type: ignore[method-assign]
    cs2.is_running = lambda: True  # type: ignore[method-assign]
    cs2.cancel = threading.Event()
    cs2.cancel.set()
    t0 = time.perf_counter()
    with pytest.raises(Cs2Error, match="cancelada"):
        cs2.goto_tick(1000)
    with pytest.raises(Cs2Error, match="cancelada"):
        cs2.wait_demo_loaded()
    assert time.perf_counter() - t0 < 2.0


# -------------------------------------------------------------- ffmpeg -----


@pytest.mark.skipif(not FFmpeg().available, reason="FFmpeg no instalado")
def test_ffmpeg_is_killed_when_progress_callback_fails(tmp_path: Path) -> None:
    import psutil

    ff = FFmpeg()
    args = ["-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=60", "-c:v", "mpeg4", str(tmp_path / "o.mp4")]

    def boom(_f: float, _m: str) -> None:
        raise RuntimeError("fallo en la interfaz")

    with pytest.raises(RuntimeError):
        ff.run(args, total_duration=60.0, progress=boom)
    time.sleep(0.3)
    children = [p for p in psutil.Process(os.getpid()).children(recursive=True) if "ffmpeg" in (p.name() or "").lower()]
    assert not children  # antes quedaba un ffmpeg huérfano codificando


@pytest.mark.skipif(not FFmpeg().available, reason="FFmpeg no instalado")
def test_ffmpeg_cancel_stops_quickly(tmp_path: Path) -> None:
    ff = FFmpeg()
    cancel = threading.Event()
    threading.Timer(0.8, cancel.set).start()
    t0 = time.perf_counter()
    with pytest.raises(FFmpegError, match="Cancelado"):
        ff.run(["-f", "lavfi", "-i", "testsrc=size=320x240:rate=30:duration=120", "-c:v", "mpeg4", str(tmp_path / "o.mp4")], total_duration=120.0, cancel=cancel)
    assert time.perf_counter() - t0 < 10.0


def test_stale_export_folders_are_removed(tmp_path: Path) -> None:
    old = tmp_path / "export_123"
    old.mkdir()
    (old / "clip_000.mp4").write_bytes(b"x")
    os.utime(old, (time.time() - 10 * 3600, time.time() - 10 * 3600))
    recent = tmp_path / "export_456"
    recent.mkdir()
    exp_mod._remove_stale_exports(tmp_path)
    assert not old.exists() and recent.exists()


def test_xfade_duration_matches_command(tmp_path: Path) -> None:
    durs = [3.0, 0.5, 8.0]
    cmd = b.xfade_command([tmp_path / f"{i}.mp4" for i in range(3)], durs, tmp_path / "o.mp4", b.EncodeSettings(), "wipeleft", 0.4)
    d = b.xfade_duration(durs, 0.4)
    assert d == pytest.approx(0.2)
    assert f"duration={d:.2f}" in " ".join(cmd)


# -------------------------------------------------------------- análisis ---


def _fake_demo(path: Path) -> Path:
    path.write_bytes(b"PBDEMS2\x00" + b"\x00" * 1_100_000)
    return path


def test_parse_demo_honours_cancel(tmp_path: Path) -> None:
    cancel = threading.Event()
    cancel.set()
    with pytest.raises(DemoError, match="cancelado"):
        parse_demo(_fake_demo(tmp_path / "x.dem"), cancel=cancel)


def test_round_for_tick_grace_period_uses_real_tickrate() -> None:
    rounds = [RoundInfo(1, 0, 100, 1000)]
    # 7 s después del final: con 128 ticks son 896 ticks (antes se usaba 64 fijo → 448).
    assert _round_for_tick(rounds, 1000 + 800, 128.0) == 1
    assert _round_for_tick(rounds, 1000 + 800, 64.0) == 0


# ------------------------------------------------------- datos dañados ----


def test_history_with_damaged_entries_does_not_block_startup(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    good = {"demo_path": "a.dem", "fingerprint": "f", "map_name": "de_x", "player_name": "yo", "score": "1-0", "processed_at": 1.0}
    path.write_text(json.dumps([good, "basura", {"demo_path": "solo"}, 3]), encoding="utf-8")
    h = History(path)
    assert [e.demo_path for e in h.entries] == ["a.dem"]
    path.write_text(json.dumps({"no": "lista"}), encoding="utf-8")
    assert History(path).entries == []


def test_history_save_is_atomic(tmp_path: Path) -> None:
    path = tmp_path / "history.json"
    h = History(path)
    h.add(HistoryEntry("a.dem", "f1", "de_x", "yo", "1-0", 1.0))
    assert json.loads(path.read_text(encoding="utf-8"))[0]["demo_path"] == "a.dem"
    assert not list(tmp_path.glob("*.tmp"))


def test_project_file_that_is_not_an_object_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "p.clutchreel.json"
    path.write_text("[1, 2, 3]", encoding="utf-8")
    with pytest.raises(ValueError):
        Project.load(path)


# ------------------------------------------------------------ secretos -----


def test_obs_library_password_line_is_redacted() -> None:
    """Una línea con «password='…'» (como la que registraba la antigua librería obsws-python) se tacha."""
    line = "Connecting with parameters: host='127.0.0.1' port=4455 password='S3cretoDeOBS' subs=0 timeout=4.0"
    out = redact(line)
    assert "S3cretoDeOBS" not in out and "password='***'" in out
    assert redact('{"server_password": "abcd1234"}') == '{"server_password": "***"}'


def test_registered_secret_never_reaches_a_handler(tmp_path: Path) -> None:
    register_secret("Zq9PalabraSecreta")
    logger = logging.getLogger("prueba.secretos")
    logger.propagate = False
    out = tmp_path / "log.txt"
    handler = logging.FileHandler(out, encoding="utf-8")
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    try:
        logger.warning("Conectando con %s", "Zq9PalabraSecreta")
        try:
            raise ValueError("fallo con Zq9PalabraSecreta")
        except ValueError:
            logger.exception("error")
    finally:
        handler.close()
        logger.removeHandler(handler)
    text = out.read_text(encoding="utf-8")
    assert "Zq9PalabraSecreta" not in text and "***" in text


def test_obs_client_does_not_depend_on_obsws_python() -> None:
    import clutchreel.core.recorder.obs_client as mod
    from clutchreel.core.recorder import obsws

    for path in (Path(mod.__file__), Path(obsws.__file__)):
        src = path.read_text(encoding="utf-8")
        assert "import obsws_python" not in src and "from obsws_python" not in src
    assert sys.modules.get("obsws_python") is None


def test_error_report_redacts_old_log_files(monkeypatch, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    from clutchreel.utils import logging_setup

    log_file = tmp_path / "clutchreel.log"
    log_file.write_text("INFO obsws: Connecting with parameters: password='viejaClave99' subs=0\n", encoding="utf-8")
    monkeypatch.setattr(logging_setup, "log_file_path", lambda: log_file)
    assert "viejaClave99" not in read_log_tail()


def test_obs_password_is_never_on_a_command_line() -> None:
    src = (Path(rec_mod.__file__).parent / "obs_client.py").read_text(encoding="utf-8")
    assert "--websocket_password" not in src



def test_capture_cvar_is_applied_even_if_fresh_cs2_does_not_answer_in_time(tmp_path: Path) -> None:
    """Recién abierto, CS2 no contestaba a tiempo la lectura de demo_ui_mode, la app la daba por inexistente
    y la barra del reproductor salía en todos los clips. Las variables guardadas en la config del juego siguen
    sin tocarse si no se puede leer su valor original."""

    class SlowCs2(Cs2Controller):
        def __init__(self) -> None:
            super().__init__(Cs2Settings())
            self.channel = "netcon"
            self.sent: list[str] = []
            self.reads: list[str] = []

        @property
        def can_read_console(self) -> bool:  # type: ignore[override]
            return True

        def get_cvar(self, name: str, attempts: int = 1) -> str | None:
            self.reads.append(f"{name}x{attempts}")
            return None  # ninguna lectura llega a tiempo

        def send(self, commands) -> None:  # type: ignore[no-untyped-def]
            self.sent.extend([commands] if isinstance(commands, str) else list(commands))

    cs2 = SlowCs2()
    cs2.backup_path = tmp_path / "backup.json"
    cs2._backup_and_set([("demo_ui_mode", "0", False), ("engine_no_focus_sleep", "0", True)])
    assert "demo_ui_mode 0" in cs2.sent
    assert not any(c.startswith("engine_no_focus_sleep") for c in cs2.sent)
    assert "demo_ui_modex3" in cs2.reads  # se reintenta antes de rendirse
    # Sin poder leer el original se guarda el valor por defecto, para que la barra del reproductor vuelva al terminar.
    assert json.loads(cs2.backup_path.read_text(encoding="utf-8")) == {"demo_ui_mode": "1"}
    cs2.is_running = lambda: True  # type: ignore[method-assign]
    cs2.sent.clear()
    cs2.restore_cvars()
    assert cs2.sent == ["demo_ui_mode 1"]


@pytest.mark.skipif(not FFmpeg().available, reason="FFmpeg no instalado")
def test_existing_recording_reports_plays_outside_the_video(match, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    """«Ya tengo la grabación»: las jugadas que caen fuera del vídeo se omitían sin avisar."""
    from clutchreel.core.demo.models import Highlight
    from clutchreel.core.editor.project import new_project
    from clutchreel.core.export.exporter import Exporter, ExportError
    from clutchreel.services.config import AppConfig, StyleSettings
    from tests.conftest import ME

    ff = FFmpeg()
    video = tmp_path / "partida ñ.mp4"
    ff.run(["-f", "lavfi", "-i", "testsrc=size=320x180:rate=30:duration=6", "-f", "lavfi", "-i", "sine=duration=6", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(video)])
    style = StyleSettings(music_enabled=False, intro_enabled=False, outro_enabled=False, transitions=False, slow_motion=False)
    inside = Highlight("2k", 1, 64, 64 * 4, 30.0, "dentro", key_tick=128)
    outside = Highlight("3k", 2, 64 * 100, 64 * 104, 50.0, "fuera", key_tick=64 * 101)
    p = new_project(match, ME, "yo", [inside, outside], style)
    p.recording_mode = "existing"
    p.existing_recording = str(video)
    p.export_preset = "youtube_1080p60"
    cfg = AppConfig()
    cfg.paths.output_folder = str(tmp_path / "Vídeos ñ áé con espacios")
    cfg.export.hw_accel = "cpu"
    cfg.export.thumbnail = False
    cfg.export.loudnorm = False
    res = Exporter(cfg, ff).export(p)
    assert res.video.exists() and res.skipped == ["Ronda 2 (3K)"]
    p.clips = p.clips[1:]
    with pytest.raises(ExportError, match="desfase"):
        Exporter(cfg, ff).export(p)


def test_cancelled_clip_is_not_marked_as_failed(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]  # noqa: F811
    """Tras cancelar, la tarjeta del clip quedaba en rojo con «falló: Grabación cancelada»."""
    from clutchreel.ui.widgets.clip_card import recording_status

    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    cs2.play_ticks = lambda ticks: r.cancel.set()  # type: ignore[method-assign]
    with pytest.raises(RecorderError, match="cancelada"):
        r.record_project(project, lambda m, f: None)
    assert recording_status(project.clips[0])[0] == "○ sin grabar"
