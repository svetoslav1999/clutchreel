"""Orquestación del grabador con OBS y CS2 falsos (sin juego ni OBS reales)."""

from __future__ import annotations

import socket
import threading
import time
from pathlib import Path

import pytest

from clutchreel.core.demo.models import Highlight
from clutchreel.core.editor.project import new_project
from clutchreel.core.export.video_check import ClipCheck
from clutchreel.core.recorder import recorder as rec_mod
from clutchreel.core.recorder.cs2_control import Cs2Controller, Cs2Error, NetconChannel
from clutchreel.core.recorder.recorder import Recorder, RecorderError
from clutchreel.core.recorder.spectate import DemoTimeline, PlayerSample
from clutchreel.services.config import AppConfig, Cs2Settings, StyleSettings
from tests.conftest import ENEMIES, ME


class FakeObs:
    def __init__(self, out_dir: Path) -> None:
        self.out_dir = out_dir
        self.connected = True
        self.recording = False
        self.calls: list[str] = []
        self.n = 0

    def ensure_connected(self, allow_launch: bool = True) -> None:
        self.calls.append("connect")

    def ensure_scene(self) -> str:
        self.calls.append("scene")
        return "game"

    def apply_recording_settings(self, d: Path) -> None:
        self.calls.append("settings")

    def source_brightness(self) -> float | None:
        return 120.0

    def is_recording(self) -> bool:
        return self.recording

    def start_record(self) -> None:
        self.recording = True
        self.calls.append("start")

    def stop_record(self) -> Path | None:
        self.recording = False
        self.n += 1
        p = self.out_dir / f"rec{self.n}.mkv"
        p.write_bytes(b"0" * 100_000)
        self.calls.append("stop")
        return p


class FakeTimeline(DemoTimeline):
    """Posiciones fijas: yo en el origen (slot 3), un enemigo a 1000 unidades (slot 7)."""

    def __init__(self, demo_path: str = "synthetic.dem") -> None:
        super().__init__(demo_path)
        self.dead_from: int | None = None

    def load(self, ticks) -> None:  # type: ignore[no-untyped-def]
        for t in ticks:
            alive = self.dead_from is None or t < self.dead_from
            self._by_tick[int(t)] = [
                PlayerSample(ME, "yo", 3, 0.0, 0.0, 0.0, alive),
                PlayerSample(ENEMIES[0], "enemy1", 7, 1000.0, 0.0, 0.0, True),
            ]


ON_ME = (0.0, 0.0, 64.0)
ON_ENEMY = (1000.0, 0.0, 64.0)


class FakeCs2(Cs2Controller):
    """CS2 falso: registra comandos y simula la posición de la cámara (``getpos``)."""

    def __init__(self) -> None:
        super().__init__(Cs2Settings(seek_wait=0.05, demo_load_wait=0.05, command_latency=0.2))
        self.sent: list[str] = []
        self.running = True
        self.missing: list[str] = []
        self.channel = "netcon"
        self.readable = True
        self.cam = ON_ME
        self.camera_fn = None  # opcional: callable(sent) -> posición

    @property
    def can_read_console(self) -> bool:  # type: ignore[override]
        return self.readable

    def launch(self, wait_seconds: float = 90.0) -> None:
        self.sent.append("launch")

    def connect_channel(self, wait_seconds: float = 60.0) -> str:
        return "netcon"

    def is_running(self) -> bool:
        return self.running

    def missing_launch_options(self) -> list[str]:
        return list(self.missing)

    def restart_game(self, timeout: float = 20.0) -> None:
        self.missing = []
        self.sent.append("restart")

    def play_demo(self, demo: Path) -> None:
        self.sent.append(f"playdemo {demo.name}")

    def setup_hud(self) -> None:
        self.sent.append("hud")

    def restore_cvars(self) -> None:
        self.sent.append("restore")

    def goto_tick(self, tick: int) -> int | None:
        self.sent.append(f"goto {tick}")
        return tick

    def send(self, commands) -> None:  # type: ignore[no-untyped-def]
        self.sent.extend([commands] if isinstance(commands, str) else list(commands))

    def camera_position(self):  # type: ignore[no-untyped-def]
        return self.camera_fn(self.sent) if self.camera_fn else self.cam

    def responsive(self, timeout: float = 3.0) -> bool:
        return True

    def resume(self) -> None:
        self.sent.append("resume")

    def play_ticks(self, ticks: int) -> None:
        self.sent.append(f"step {ticks}")
        self.resume()  # los tests antiguos cuentan «resume»
        # CS2 anuncia la pausa al terminar los ticks; aquí llega enseguida (se reproduce «instantáneo»).
        self.pauses.append((time.perf_counter() + 1.0, 99999, 12345))

    def pause_after(self, t0: float):  # type: ignore[no-untyped-def]
        for t, _engine, demo_tick in self.pauses:
            if t >= t0 and time.perf_counter() >= t:  # la pausa «llega» cuando toca, como en el CS2 real
                if self.sent[-1] != "pause":
                    self.sent.append("pause")  # CS2 queda en pausa al acabar los ticks
                return t, demo_tick
        return None

    def pause(self) -> None:
        self.sent.append("pause")

    def close_game(self) -> None:
        self.sent.append("quit")


@pytest.fixture
def project(match, tmp_path):  # type: ignore[no-untyped-def]
    hls = [Highlight("3k", 1, 1400, 1400 + 64 * 2, 50.0, "3K", key_tick=1500), Highlight("entry", 3, 17000, 17000 + 64, 20.0, "entry", key_tick=17050)]
    p = new_project(match, ME, "yo", hls, StyleSettings())
    p.path = str(tmp_path / "p.json")
    return p


def make_recorder(tmp_path: Path, monkeypatch, check_ok: bool = True) -> tuple[Recorder, FakeObs, FakeCs2]:  # type: ignore[no-untyped-def]
    cfg = AppConfig()
    cfg.paths.output_folder = str(tmp_path)
    r = Recorder(cfg)
    obs = FakeObs(tmp_path)
    cs2 = FakeCs2()
    r.obs = obs  # type: ignore[assignment]
    r.cs2 = cs2
    r.config.cs2 = cs2.settings
    r.timeline_factory = FakeTimeline
    results = iter([False, True]) if not check_ok else None

    def fake_check(_ff, path, expected_duration=0.0):  # type: ignore[no-untyped-def]
        ok = True if results is None else next(results)
        return ClipCheck(ok, "" if ok else "negro", 5.0, 100.0, 0.4)

    monkeypatch.setattr(rec_mod, "check_clip", fake_check)
    return r, obs, cs2


def test_records_all_clips_and_sets_offsets(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, obs, cs2 = make_recorder(tmp_path, monkeypatch)
    messages: list[str] = []
    session = r.record_project(project, lambda m, f: messages.append(m))
    assert session.done == 2
    assert all(c.recording_ok and c.has_recording for c in project.clips)
    # CS2 ya abierto con las opciones correctas: no se relanza. Orden: demo → hud → (goto → spec → start → resume → pause → stop) × 2
    assert cs2.sent[:2] == ["playdemo synthetic.dem", "hud"]
    # spec_player usa slot + 1 y primera persona (spec_mode 2), nunca comandos inexistentes
    assert cs2.sent.count("spec_player 4") == 2 and "spec_mode 2" in cs2.sent
    assert not any("accountid" in c for c in cs2.sent)
    for c in project.clips:
        assert c.camera_verified and c.recorded_player_steamid == ME and c.recorded_player_name == "yo"
    assert cs2.sent[-1] == "restore"  # variables de captura restauradas al terminar
    assert cs2.sent.count("resume") == 2 and obs.calls.count("start") == 2 and obs.calls.count("stop") == 2
    # El tick de inicio incluye 1 s de margen previo (64 ticks)
    assert "goto 1336" in cs2.sent
    for c in project.clips:
        assert 0.6 + 0.2 + 1.0 <= c.recording_offset <= 0.6 + 0.2 + 1.0 + 0.5
        assert c.recording_tickrate == 64.0  # el falso reproduce «instantáneo»: velocidad fuera de rango → nominal
    assert any(c.startswith("step ") for c in cs2.sent)  # se reproducen ticks exactos, no segundos de reloj
    assert Path(project.path).exists()  # autoguardado tras cada clip


def test_retries_failed_clip_then_succeeds(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, _cs2 = make_recorder(tmp_path, monkeypatch, check_ok=False)
    project.clips = project.clips[:1]
    session = r.record_project(project, lambda m, f: None)
    assert session.jobs[0].attempts == 2
    assert session.done == 1


def test_skips_already_recorded_and_cancel(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    done = tmp_path / "ya.mkv"
    done.write_bytes(b"x")
    project.clips[0].recording_ok = True
    project.clips[0].recording_path = str(done)
    r.cancel.set()
    with pytest.raises(RecorderError):
        r.record_project(project, lambda m, f: None)
    assert "start" not in obs.calls


def test_game_closed_mid_clip_is_recovered(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]
    state = {"first": True}

    def resume() -> None:
        cs2.sent.append("resume")
        if state["first"]:
            state["first"] = False
            cs2.running = False

    cs2.resume = resume  # type: ignore[method-assign]
    orig_launch = cs2.launch

    def launch() -> None:
        cs2.running = True
        orig_launch()

    cs2.launch = launch  # type: ignore[method-assign]
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 1
    assert cs2.sent.count("launch") == 1  # solo la recuperación; al inicio CS2 ya estaba abierto
    assert cs2.sent.count("playdemo synthetic.dem") == 2


# ------------------------------------------------------------- netcon -----


class FakeConsole:
    """Puerto de consola falso que imita la salida real de CS2 1.41.9 (capturada el 26/10/2026)."""

    def __init__(self, incompatible: bool = False, spam: bool = False) -> None:
        self.incompatible = incompatible
        self.spam = spam
        self.cvars = {"snd_mute_losefocus": "true", "engine_no_focus_sleep": "20", "r_show_build_info": "true", "demo_ui_mode": "2"}
        self.stepped = False  # pausa dejada por demo_step_tick: los saltos cortos hacia delante no se mueven
        self.received: list[str] = []
        self.port = 0
        self.stop = threading.Event()
        self._ready = threading.Event()
        self.thread = threading.Thread(target=self._serve, daemon=True)
        self.thread.start()
        self._ready.wait(5)

    def _reply(self, text: str) -> str:
        if text.startswith("echo "):
            return text[5:] + "\n"
        if text.startswith("playdemo"):
            if self.incompatible:
                return "playing demo from 'x.dem'\nDisconnected from server: NETWORK_DISCONNECT_REPLAY_INCOMPATIBLE (Network version 14141 is incompatible.)\n"
            # Tras entrar en partida CS2 hace por su cuenta un salto al tick 0 (~3 s después).
            return (
                "playing demo from 'x.dem'\nChangeGameUIState: CSGO_GAME_UI_STATE_LOADINGSCREEN -> CSGO_GAME_UI_STATE_INGAME\n"
                "Added TrueView prediction for player slot 0 (jugador0)\nDemo Skipping finished at tick 0\n"
            )
        if text.startswith("demo_gototick"):
            if self.stepped:
                return f"Demo Skipping: skipping forward to demo tick {text.split()[1]}\nDemo paused at engine time 38675, demo tick 36713\n"
            return f"Demo Skipping: skipping to demo tick {text.split()[1]}\nDemo Skipping finished at tick {text.split()[1]}\nCGameRules - paused on tick {int(text.split()[1]) + 1962}\n"
        if text == "demo_resume":
            self.stepped = False
            return "CGameRules - unpaused on tick 38611, pause duration was 0 ticks\n"
        if text.startswith("demo_step_tick"):
            n = int(text.split()[1])
            self.stepped = True
            return f"CGameRules - unpaused on tick 38611, pause duration was 0 ticks\nCGameRules - paused on tick {38611 + n}\nDemo paused at engine time {38611 + n}, demo tick {36649 + n}\n"
        if text.startswith("spec_player 4"):
            return "TrueView inactive\nAdded TrueView prediction for player slot 3 (♛Jugador Uno♛)\nTrueView active for slot 3\n"
        if text == "getpos":
            return "setpos -1147.066162 -642.418701 -104.000000;setang 0.988637 13.702653 0.000000\n"
        parts = text.split()
        if len(parts) == 1 and parts[0] in self.cvars:
            return f"{parts[0]} = {self.cvars[parts[0]]}\n"
        if len(parts) == 2 and parts[0] in self.cvars:
            self.cvars[parts[0]] = parts[1]
        return ""

    def _serve(self) -> None:
        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        self.port = srv.getsockname()[1]
        self._ready.set()
        srv.settimeout(5)
        try:
            conn, _ = srv.accept()
        except OSError:
            return
        conn.settimeout(0.05)
        buf = b""
        while not self.stop.is_set():
            if self.spam:
                try:
                    conn.sendall(b"Not enough TrueSpectate command lookahead.\n")
                except OSError:
                    break
            try:
                data = conn.recv(4096)
            except TimeoutError:
                continue
            except OSError:
                break
            if not data:
                break
            buf += data
            while b"\n" in buf:
                line, buf = buf.split(b"\n", 1)
                text = line.decode()
                self.received.append(text)
                out = self._reply(text)
                if out:
                    conn.sendall(out.encode())
        conn.close()
        srv.close()


def _controller(console: FakeConsole, monkeypatch) -> Cs2Controller:  # type: ignore[no-untyped-def]
    ctl = Cs2Controller(Cs2Settings(netcon_port=console.port, demo_load_wait=1.0, keyboard_fallback=False))
    monkeypatch.setattr(ctl, "is_running", lambda: True)
    monkeypatch.setattr(ctl, "running_args", lambda: ["-netconport", "-insecure"])  # no mirar el CS2 real del PC
    assert ctl.connect_channel(wait_seconds=3) == "netcon"
    return ctl


def test_netcon_echo_load_seek_and_getpos(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    console = FakeConsole(spam=True)
    ctl = _controller(console, monkeypatch)
    assert ctl.netcon.echo_works is True and ctl.can_read_console
    t0 = time.time()
    ctl.play_demo(Path("C:/Demos con ñ/partida añeja.dem"))  # termina en cuanto CS2 dice que está en partida
    assert time.time() - t0 < 6.0
    assert "demo_ui_mode 0" in console.received  # sin barra del reproductor en el vídeo
    assert any(c.startswith('playdemo "C:/Demos con ñ/partida añeja.dem"') for c in console.received)
    assert ctl.goto_tick(5000) == 5000
    assert ctl.camera_position() == (-1147.066162, -642.418701, -104.0)
    # Los anuncios de cámara de la consola se registran con slot y nombre.
    ctl.send("spec_player 4")
    deadline = time.time() + 2
    while time.time() < deadline and (ctl.camera_slot_name or (0, ""))[1] != "♛Jugador Uno♛":
        ctl.netcon.read(0.1, 0.3)
    assert ctl.camera_slot_name == (3, "♛Jugador Uno♛")
    # demo_step_tick: CS2 pausa solo y anuncia el tick de demo alcanzado.
    t0 = time.perf_counter()
    ctl.play_ticks(640)
    deadline = time.time() + 2
    while time.time() < deadline and ctl.pause_after(t0) is None:
        ctl.netcon.read(0.1, 0.3)
    paused = ctl.pause_after(t0)
    assert paused is not None and paused[1] == 36649 + 640
    assert "demo_step_tick 640" in console.received
    # Tras la pausa de step_tick, un salto corto hacia delante solo funciona si antes se reanuda y pausa.
    assert ctl.goto_tick(37400) == 37400
    idx = len(console.received) - 1 - console.received[::-1].index("demo_gototick 37400")
    assert "demo_resume" in console.received[:idx]
    console.stop.set()
    ctl.netcon.close()


def test_incompatible_demo_fails_fast_with_clear_message(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    console = FakeConsole(incompatible=True)
    ctl = _controller(console, monkeypatch)
    t0 = time.time()
    with pytest.raises(Cs2Error, match="versión anterior del juego"):
        ctl.play_demo(Path("vieja.dem"))
    assert time.time() - t0 < 6.0
    console.stop.set()
    ctl.netcon.close()


def test_capture_cvars_are_backed_up_and_restored(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    console = FakeConsole()
    ctl = _controller(console, monkeypatch)
    ctl.setup_hud()
    deadline = time.time() + 3
    while time.time() < deadline and console.cvars["snd_mute_losefocus"] != "0":
        time.sleep(0.05)
    assert console.cvars["snd_mute_losefocus"] == "0" and console.cvars["engine_no_focus_sleep"] == "0"
    assert ctl.backup_path.exists()
    ctl.restore_cvars()
    deadline = time.time() + 3
    while time.time() < deadline and console.cvars["snd_mute_losefocus"] != "true":
        time.sleep(0.05)
    assert console.cvars["snd_mute_losefocus"] == "true" and console.cvars["engine_no_focus_sleep"] == "20"
    assert not ctl.backup_path.exists()
    console.stop.set()
    ctl.netcon.close()


def test_archived_cvars_untouched_when_console_is_unreadable() -> None:
    ctl = Cs2Controller(Cs2Settings())
    sent: list[str] = []
    ctl.channel = "keyboard"
    ctl.send = lambda cmds: sent.extend([cmds] if isinstance(cmds, str) else cmds)  # type: ignore[method-assign]
    ctl.setup_hud()
    assert "cl_trueview_show_status 0" in sent  # no se guarda en la config del usuario
    assert not any(c.startswith(("snd_mute_losefocus", "engine_no_focus_sleep", "r_show_build_info")) for c in sent)


def test_netcon_read_stops_despite_console_spam() -> None:
    console = FakeConsole(spam=True)
    ch = NetconChannel(console.port)
    assert ch.connect()
    t0 = time.time()
    out = ch.read(0.2, 0.6)
    assert time.time() - t0 < 1.5 and "TrueSpectate" in out
    console.stop.set()
    ch.close()


def test_netcon_unavailable_falls_back(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    settings = Cs2Settings(netcon_port=1, keyboard_fallback=False)
    ctl = Cs2Controller(settings)
    monkeypatch.setattr(ctl, "is_running", lambda: True)
    monkeypatch.setattr(ctl, "running_args", lambda: ["-netconport", "-insecure"])  # no mirar el CS2 real del PC
    assert ctl.connect_channel(wait_seconds=0.1) == "manual"
    with pytest.raises(Cs2Error):
        ctl.send("demo_pause")
    ctl.ask_user = lambda text: "demo_pause" in text
    ctl.send("demo_pause")


# --------------------------------------------------- fallos y estado -----


def test_black_clip_is_reported_with_clear_reason(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]

    def black(_ff, path, expected_duration=0.0):  # type: ignore[no-untyped-def]
        return ClipCheck(False, "La grabación es negra: OBS no capturó el juego.", 5.0, 0.0)

    monkeypatch.setattr(rec_mod, "check_clip", black)
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0 and not project.clips[0].recording_ok
    status, detail = session.job_outcome()
    assert status == "error"
    assert "OBS grabó imagen negra" in detail and "0/1" in detail


def test_outcome_partial_and_ok(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, _cs2 = make_recorder(tmp_path, monkeypatch)
    session = r.record_project(project, lambda m, f: None)
    assert session.job_outcome() == ("hecho", "")
    session.jobs[1].result = None
    session.jobs[1].error = "CS2 no respondió por la consola: x"
    status, detail = session.job_outcome()
    assert status == "parcial" and "1/2" in detail and "ronda 3" in detail


def test_explain_failure_messages() -> None:
    from clutchreel.core.recorder.recorder import explain_failure

    assert "imagen negra" in explain_failure(RecorderError("La grabación es negra: OBS no capturó el juego."))
    static = explain_failure(RecorderError("La grabación es una imagen estática: la demo no avanzó."), "keyboard")
    assert "no recibió los comandos" in static and "teclado simulado" in static
    assert explain_failure(Cs2Error("sin canal")).startswith("CS2 no respondió por la consola")


def test_running_cs2_without_options_asks_before_restarting(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    cs2.missing = ["-netconport", "-insecure"]
    asked: list[str] = []
    manual: list[str] = []
    cs2.ask_user = lambda text: manual.append(text) or False  # type: ignore[assignment,func-returns-value]  # diálogo de comandos manuales
    r.ask_yes_no = lambda text: asked.append(text) or False  # type: ignore[func-returns-value]  # diálogo Sí/No
    r.prepare(lambda m, f: None)
    assert len(asked) == 1 and "-netconport" in asked[0] and "¿Cerrar CS2" in asked[0]
    assert not manual  # la pregunta de reinicio nunca sale como «paso manual» con comandos
    assert "restart" not in cs2.sent  # el usuario dijo que no: no se toca CS2
    r.ask_yes_no = lambda text: True
    r.prepare(lambda m, f: None)
    assert "restart" in cs2.sent


def test_recorder_uses_yes_no_callback_for_restart_questions(tmp_path):  # type: ignore[no-untyped-def]
    cfg = AppConfig()
    yes_no: list[str] = []
    manual: list[str] = []
    r = Recorder(cfg, ask_user=lambda t: manual.append(t) or True, ask_yes_no=lambda t: yes_no.append(t) or False)  # type: ignore[func-returns-value]
    assert r._may_relaunch() is False and len(yes_no) == 1 and not manual
    # Sin callback Sí/No se usa el manual (compatibilidad); sin ninguno, se reabre una sola vez.
    r2 = Recorder(cfg)
    assert r2._may_relaunch() is True and r2._may_relaunch() is False


def test_camera_switch_announced_by_console_fails_clip(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    project.clips = project.clips[:1]

    def resume() -> None:
        cs2.sent.append("resume")
        # getpos sigue diciendo que estamos en mí, pero CS2 anuncia que la cámara pasó a otro jugador.
        cs2.camera_changes.append((time.perf_counter() + 0.3, 7, "enemy1"))

    cs2.resume = resume  # type: ignore[method-assign]
    session = r.record_project(project, lambda m, f: None)
    assert session.done == 0
    assert "enemy1" in session.jobs[0].error and "anunciado por CS2" in session.jobs[0].error


def test_recording_extension_follows_real_container(tmp_path):  # type: ignore[no-untyped-def]
    from clutchreel.core.recorder.obs_client import fix_extension, real_suffix

    mp4 = tmp_path / "clip.mkv"
    mp4.write_bytes(b"\x00\x00\x00\x28ftypiso4" + b"\x00" * 100)  # OBS 33: nombre .mkv con contenido MP4
    assert real_suffix(mp4) == ".mp4"
    fixed = fix_extension(mp4)
    assert fixed.suffix == ".mp4" and fixed.exists() and not mp4.exists()
    mkv = tmp_path / "ok.mkv"
    mkv.write_bytes(b"\x1aE\xdf\xa3\xa3B\x86\x81matroska" + b"\x00" * 100)
    assert fix_extension(mkv) == mkv
    unknown = tmp_path / "raro.mkv"
    unknown.write_bytes(b"\x00" * 50)
    assert fix_extension(unknown) == unknown


def test_running_cs2_without_options_never_restarts_without_a_way_to_ask(project, tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    r, _obs, cs2 = make_recorder(tmp_path, monkeypatch)
    cs2.missing = ["-netconport"]
    r.prepare(lambda m, f: None)
    assert "restart" not in cs2.sent


def test_job_queue_marks_failed_recording_not_done() -> None:
    from clutchreel.ui.jobs import STATUS_LABELS, Job, JobQueue

    class Outcome:
        def __init__(self, status: str, detail: str) -> None:
            self._o = (status, detail)

        def job_outcome(self) -> tuple[str, str]:
            return self._o

    q = JobQueue(pool=None)  # type: ignore[arg-type]
    failed: list[str] = []
    q.job_failed.connect(lambda job: failed.append(job.status))
    for outcome, expected in ((("error", "0/1 clips correctos. x"), "error"), (("parcial", "1/2"), "parcial"), (("hecho", ""), "hecho")):
        job = Job(id=1, kind="grabar", title="t", fn=lambda: None)
        q.jobs = [job]
        q._on_done(job, Outcome(*outcome))
        assert job.status == expected
        assert job.error == outcome[1]
    assert failed == ["error", "parcial"]
    assert STATUS_LABELS["error"] == "Fallido" and STATUS_LABELS["parcial"] == "Parcial"
    plain = Job(id=2, kind="analizar", title="t", fn=lambda: None)
    q.jobs = [plain]
    q._on_done(plain, object())
    assert plain.status == "hecho"
