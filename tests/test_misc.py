from __future__ import annotations

from pathlib import Path

import numpy as np

from clutchreel.core.export.metadata import suggest_metadata
from clutchreel.core.export.video_check import detect_motion_start
from clutchreel.core.recorder.cs2_control import Cs2Controller
from clutchreel.core.recorder.spectate import spec_name_command, spec_player_command
from clutchreel.services.config import Cs2Settings
from clutchreel.services.history import History, HistoryEntry, demo_fingerprint
from clutchreel.utils.paths import safe_filename, steamid64_to_accountid


def test_spec_commands() -> None:
    # Verificado en CS2 1.41.9: «spec_player N» sigue al slot N-1 (user_id de demoparser2).
    assert spec_player_command(3) == "spec_player 4"
    assert spec_player_command(0) == "spec_player 1"
    assert spec_name_command('Nombre "raro"') == 'spec_player "Nombre raro"'
    assert steamid64_to_accountid(76561197960265729) == 1


def test_launch_args() -> None:
    c = Cs2Controller(Cs2Settings(launch_options="-novid", netcon_port=2121, netcon_tools_workaround=True, window_width=1280, window_height=720))
    args = c.launch_args()
    assert args[0] == "-insecure"
    assert "-netconport" in args and "2121" in args and "-tools" in args
    assert "-w" in args and "1280" in args
    c2 = Cs2Controller(Cs2Settings(use_netconport=False))
    assert "-netconport" not in c2.launch_args()


def test_motion_start() -> None:
    frames = np.zeros((40, 8, 8), dtype=np.uint8)
    frames[20:] = np.arange(20)[:, None, None] * 5 + 10
    assert detect_motion_start(frames, fps=10) == 2.0
    assert detect_motion_start(np.zeros((40, 8, 8), dtype=np.uint8), 10) is None


def test_safe_filename() -> None:
    assert safe_filename('a:b/c*d? "e" ñandú.mp4') == "a_b_c_d_ _e_ ñandú.mp4"
    assert safe_filename("   ") == "sin_nombre"


def test_history(tmp_path: Path) -> None:
    demo = tmp_path / "x.dem"
    demo.write_bytes(b"PBDEMS2" + b"\0" * 200000)
    h = History(tmp_path / "h.json")
    fp = demo_fingerprint(demo)
    assert fp
    h.add(HistoryEntry(str(demo), fp, "de_mirage", "yo", "13-7", 1.0))
    again = History(tmp_path / "h.json")
    assert again.find(demo) is not None
    assert again.find(tmp_path / "otra.dem") is None


def test_metadata(match) -> None:  # type: ignore[no-untyped-def]
    from clutchreel.core.demo.models import Highlight

    hls = [Highlight("ace", 3, 1, 2, 100.0, "ACE en la ronda 3", merged_kinds=["ace", "entry"])]
    meta = suggest_metadata(match, "yo", hls, "MiCanal", ["CS2"])
    assert meta.title.startswith("ACE en Test")
    assert "MiCanal" in meta.description
    assert "ACE" in meta.tags and len(meta.tags) == len({t.lower() for t in meta.tags})


def test_partial_recording_is_reported_once() -> None:
    """Grabación parcial: su diálogo propio ya lo explica; el genérico de «trabajo fallido» no se duplica."""
    from clutchreel.ui.jobs import Job
    from clutchreel.ui.main_window import MainWindow

    partial = Job(id=1, kind="grabar", title="t", fn=lambda: None, status="parcial", result=object(), error="4/5")
    crashed = Job(id=2, kind="grabar", title="t", fn=lambda: None, status="error", result=None, error="OBS no responde")
    export_failed = Job(id=3, kind="exportar", title="t", fn=lambda: None, status="error", result=None, error="ffmpeg")
    assert not MainWindow.should_report_failure(partial)
    assert MainWindow.should_report_failure(crashed)
    assert MainWindow.should_report_failure(export_failed)


def test_clip_uses_measured_playback_rate() -> None:
    """CS2 reproduce a ~57 ticks/s: la duración en el vídeo grabado es mayor que la nominal."""
    from clutchreel.core.demo.models import Highlight
    from clutchreel.core.editor.project import Clip

    hl = Highlight("3k", 1, 1000, 1000 + 640, 10.0, "x", key_tick=1500)  # 10 s nominales a 64
    clip = Clip(id="a", highlight=hl, recording_tickrate=57.6)
    assert abs(clip.duration_seconds(64.0) - 10.0) < 1e-6
    assert abs(clip.recorded_duration_seconds(64.0) - 640 / 57.6) < 1e-6
    assert clip.effective_tickrate(64.0) == 57.6
    plain = Clip(id="b", highlight=hl)
    assert plain.effective_tickrate(64.0) == 64.0 and plain.recorded_duration_seconds(64.0) == 10.0
    assert Clip.from_dict(clip.to_dict()).recording_tickrate == 57.6
    assert Clip.from_dict({"id": "c", "highlight": hl.to_dict()}).recording_tickrate == 0.0  # proyectos antiguos
