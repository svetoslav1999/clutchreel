from __future__ import annotations

import json
from pathlib import Path

from clutchreel.core.demo.models import Highlight
from clutchreel.core.editor.project import Clip, Project, UndoStack, new_project
from clutchreel.services.config import AppConfig, ConfigStore, StyleSettings, ensure_default_profiles, from_dict, to_dict


def test_roundtrip(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "config.json")
    cfg = store.load()
    cfg.player.steamid64 = 76561198000000001
    cfg.obs.password = "secreta"
    cfg.detection.enabled_kinds = ["ace"]
    store.save()
    again = ConfigStore(tmp_path / "config.json").load()
    assert again.player.steamid64 == 76561198000000001
    assert again.obs.password == "secreta"
    assert again.detection.enabled_kinds == ["ace"]


def test_unknown_keys_and_bad_types_are_tolerated(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text(json.dumps({"player": {"steamid64": "no-es-numero", "extra": 1}, "obs": {"port": "4455"}, "desconocido": {}}), encoding="utf-8")
    cfg = ConfigStore(p).load()
    assert cfg.player.steamid64 == 0
    assert cfg.obs.port == 4455
    assert cfg.export.preset == "youtube_1080p60"


def test_corrupt_file_falls_back(tmp_path: Path) -> None:
    p = tmp_path / "config.json"
    p.write_text("{not json", encoding="utf-8")
    cfg = ConfigStore(p).load()
    assert isinstance(cfg, AppConfig)


def test_profiles(tmp_path: Path) -> None:
    store = ConfigStore(tmp_path / "c.json")
    store.load()
    ensure_default_profiles(store)
    assert "Highlights YouTube" in store.config.profiles and "Shorts" in store.config.profiles
    assert store.apply_profile("Shorts")
    assert store.config.style.aspect == "9:16"
    assert store.config.export.preset == "shorts_1080x1920"
    assert not store.apply_profile("no existe")


def test_project_roundtrip(tmp_path: Path, match) -> None:  # type: ignore[no-untyped-def]
    hl = Highlight("3k", 1, 1000, 2000, 50.0, "3K", key_tick=1900, tags=["3K"])
    project = new_project(match, 76561198000000001, "yo", [hl], StyleSettings())
    project.clips[0].trim_start = 1.5
    project.clips[0].recording_path = "C:/x/clip.mkv"
    path = project.save(tmp_path / "p.json")
    loaded = Project.load(path)
    assert loaded.clips[0].trim_start == 1.5
    assert loaded.clips[0].highlight.key_tick == 1900
    assert loaded.match.map_name == "de_test"
    assert loaded.match.rounds[0].players_at_start == match.rounds[0].players_at_start
    assert loaded.total_duration() > 0


def test_undo_redo(match) -> None:  # type: ignore[no-untyped-def]
    hl = Highlight("3k", 1, 1000, 2000, 50.0, "3K")
    project = new_project(match, 76561198000000001, "yo", [hl], StyleSettings())
    stack = UndoStack()
    stack.push(project)
    project.clips[0].enabled = False
    assert stack.undo(project)
    assert project.clips[0].enabled is True
    assert stack.redo(project)
    assert project.clips[0].enabled is False
    assert not stack.redo(project)


def test_clip_dict_roundtrip() -> None:
    hl = Highlight("clutch", 5, 10, 20, 1.0, "c", extra={"won": True})
    clip = Clip(id="abc", highlight=hl, zoom=1.3)
    again = Clip.from_dict(json.loads(json.dumps(clip.to_dict())))
    assert again.zoom == 1.3 and again.highlight.extra["won"] is True


def test_to_from_dict_nested() -> None:
    cfg = AppConfig()
    cfg.style.music_volume = 0.5
    data = to_dict(cfg)
    assert data["style"]["music_volume"] == 0.5
    back = from_dict(AppConfig, data)
    assert back.style.music_volume == 0.5


def test_tools_flag_is_off_by_default_and_migrated_from_old_configs(tmp_path):  # type: ignore[no-untyped-def]
    import json

    from clutchreel.core.recorder.cs2_control import Cs2Controller
    from clutchreel.services.config import ConfigStore, Cs2Settings

    assert Cs2Settings().netcon_tools_workaround is False
    assert "-tools" not in Cs2Controller(Cs2Settings()).launch_args()
    old = tmp_path / "config.json"
    old.write_text(json.dumps({"version": 1, "cs2": {"netcon_tools_workaround": True}}), encoding="utf-8")
    store = ConfigStore(old)
    cfg = store.load()
    assert cfg.cs2.netcon_tools_workaround is False and cfg.version == 3
    # Una config ya migrada respeta la elección explícita del usuario.
    old.write_text(json.dumps({"version": 2, "cs2": {"netcon_tools_workaround": True}}), encoding="utf-8")
    assert store.load().cs2.netcon_tools_workaround is True


def test_migration_v3_replaces_old_hud_commands_but_keeps_custom_ones(tmp_path):  # type: ignore[no-untyped-def]
    import json

    from clutchreel.services.config import DEFAULT_HUD_COMMANDS, OLD_HUD_COMMANDS, ConfigStore

    path = tmp_path / "config.json"
    path.write_text(json.dumps({"version": 2, "cs2": {"hud_commands": OLD_HUD_COMMANDS, "spec_strategy": "by_accountid"}}), encoding="utf-8")
    cfg = ConfigStore(path).load()
    assert cfg.cs2.hud_commands == DEFAULT_HUD_COMMANDS and "spec_mode 1" not in cfg.cs2.hud_commands
    assert cfg.version == 3 and not hasattr(cfg.cs2, "spec_strategy")
    path.write_text(json.dumps({"version": 2, "cs2": {"hud_commands": "cl_draw_only_deathnotices 0"}}), encoding="utf-8")
    assert ConfigStore(path).load().cs2.hud_commands == "cl_draw_only_deathnotices 0"
