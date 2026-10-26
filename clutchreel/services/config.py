"""Configuración persistente en ``%APPDATA%\\ClutchReel\\config.json``.

Se modela con dataclasses anidadas; la serialización ignora claves desconocidas
y rellena las que falten con valores por defecto, de modo que actualizar la app
nunca rompe configuraciones antiguas.
"""

from __future__ import annotations

import dataclasses
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field, fields, is_dataclass
from pathlib import Path
from typing import Any, TypeVar

from clutchreel.utils.paths import appdata_dir, default_output_dir

log = logging.getLogger(__name__)

T = TypeVar("T")

CONFIG_FILE_NAME = "config.json"
CONFIG_VERSION = 3
DEFAULT_HUD_COMMANDS = "cl_draw_only_deathnotices 1; spec_show_xray 0"
# Valor de fábrica hasta la v2: «spec_mode 1» no es primera persona fiable y sv_cheats no hace falta.
OLD_HUD_COMMANDS = "sv_cheats 1; cl_draw_only_deathnotices 1; spec_show_xray 0; cl_showfps 0; spec_mode 1"


# ------------------------------------------------------------ dataclasses ---


@dataclass
class PlayerSettings:
    steamid64: int = 0
    name: str = ""
    remember: bool = True


@dataclass
class PathSettings:
    demo_folder: str = ""
    extra_demo_folders: list[str] = field(default_factory=list)
    output_folder: str = field(default_factory=lambda: str(default_output_dir()))
    ffmpeg_path: str = ""
    obs_path: str = ""
    cs2_path: str = ""
    music_folder: str = ""


@dataclass
class ObsSettings:
    host: str = "127.0.0.1"
    port: int = 4455
    password: str = ""
    scene_name: str = "ClutchReel"
    source_name: str = "ClutchReel - Captura CS2"
    capture_mode: str = "game"  # game | window | display
    recording_format: str = "mkv"
    width: int = 1920
    height: int = 1080
    fps: int = 60
    auto_launch: bool = True
    manage_scene: bool = True
    manage_video_settings: bool = True


@dataclass
class Cs2Settings:
    launch_options: str = "-insecure -novid -console"
    use_netconport: bool = True
    netcon_port: int = 2121
    netcon_tools_workaround: bool = False  # -tools cuelga CS2 al saltar en la demo (verificado 2026-10-26); el puerto abre sin él
    hud_commands: str = DEFAULT_HUD_COMMANDS
    demo_load_wait: float = 25.0
    seek_wait: float = 6.0
    command_latency: float = 0.35
    start_offset: float = 0.0
    keyboard_fallback: bool = True
    cfg_fallback: bool = True
    copy_demo_to_game: bool = False
    close_game_when_done: bool = False
    window_width: int = 0
    window_height: int = 0


@dataclass
class DetectionSettings:
    multikill_window: float = 12.0
    min_multikill: int = 2
    headshot_streak_min: int = 3
    pre_roll: float = 3.0
    post_roll: float = 2.0
    merge_gap: float = 4.0
    clutch_min_enemies: int = 2
    include_lost_clutches: bool = True
    enabled_kinds: list[str] = field(
        default_factory=lambda: [
            "ace",
            "4k",
            "3k",
            "2k",
            "clutch",
            "headshot_streak",
            "entry",
            "awp",
            "noscope",
            "wallbang",
            "smoke",
            "blind",
            "air",
            "knife",
            "decisive",
            "best_round",
        ]
    )


@dataclass
class ScoringWeights:
    kill: float = 10.0
    headshot: float = 4.0
    multikill_2k: float = 15.0
    multikill_3k: float = 35.0
    multikill_4k: float = 60.0
    ace: float = 120.0
    clutch_base: float = 40.0
    clutch_per_enemy: float = 25.0
    clutch_won_bonus: float = 30.0
    headshot_streak: float = 20.0
    entry: float = 12.0
    awp: float = 6.0
    noscope: float = 25.0
    wallbang: float = 18.0
    smoke: float = 20.0
    blind: float = 22.0
    air: float = 15.0
    knife: float = 40.0
    pistol: float = 5.0
    decisive_round: float = 25.0
    distance_per_100u: float = 2.0


@dataclass
class StyleSettings:
    music_enabled: bool = True
    music_track: str = ""
    music_volume: float = 0.35
    game_volume: float = 1.0
    ducking: bool = True
    fade_seconds: float = 1.5
    beat_sync: bool = False
    transitions: bool = True
    transition_type: str = "fade"
    transition_duration: float = 0.4
    intro_enabled: bool = True
    outro_enabled: bool = True
    channel_name: str = ""
    intro_title: str = ""
    kill_counter: bool = True
    slow_motion: bool = True
    slow_motion_factor: float = 0.5
    slow_motion_seconds: float = 1.2
    watermark_path: str = ""
    aspect: str = "16:9"  # 16:9 | 9:16
    font_family: str = "Segoe UI"


@dataclass
class ExportSettings:
    preset: str = "youtube_1080p60"
    codec: str = "h264"  # h264 | hevc
    hw_accel: str = "auto"  # auto | nvenc | amf | qsv | cpu
    quality: str = "alta"  # alta | media | baja
    bitrate_kbps: int = 0  # 0 = automático según calidad
    loudnorm: bool = True
    thumbnail: bool = True
    open_folder_when_done: bool = True
    notify_when_done: bool = True
    shutdown_when_done: bool = False


@dataclass
class YouTubeSettings:
    enabled: bool = False
    client_secrets_path: str = ""
    default_privacy: str = "private"
    default_tags: list[str] = field(default_factory=lambda: ["CS2", "Counter-Strike 2", "highlights", "Premier"])


@dataclass
class WatcherSettings:
    enabled: bool = False
    profile_name: str = "Highlights YouTube"
    auto_record: bool = True
    auto_export: bool = True


@dataclass
class UiSettings:
    theme: str = "oscuro"
    language: str = "es"
    first_run_done: bool = False
    minimize_to_tray: bool = True
    window_geometry: str = ""
    recent_projects: list[str] = field(default_factory=list)
    last_wizard: dict[str, Any] = field(default_factory=dict)


@dataclass
class AppConfig:
    version: int = CONFIG_VERSION
    player: PlayerSettings = field(default_factory=PlayerSettings)
    paths: PathSettings = field(default_factory=PathSettings)
    obs: ObsSettings = field(default_factory=ObsSettings)
    cs2: Cs2Settings = field(default_factory=Cs2Settings)
    detection: DetectionSettings = field(default_factory=DetectionSettings)
    scoring: ScoringWeights = field(default_factory=ScoringWeights)
    style: StyleSettings = field(default_factory=StyleSettings)
    export: ExportSettings = field(default_factory=ExportSettings)
    youtube: YouTubeSettings = field(default_factory=YouTubeSettings)
    watcher: WatcherSettings = field(default_factory=WatcherSettings)
    ui: UiSettings = field(default_factory=UiSettings)
    profiles: dict[str, dict[str, Any]] = field(default_factory=dict)


# ------------------------------------------------------------ (de)serialize --


def to_dict(obj: Any) -> Any:
    if is_dataclass(obj) and not isinstance(obj, type):
        return {f.name: to_dict(getattr(obj, f.name)) for f in fields(obj)}
    if isinstance(obj, list):
        return [to_dict(x) for x in obj]
    if isinstance(obj, dict):
        return {str(k): to_dict(v) for k, v in obj.items()}
    return obj


def from_dict(cls: type[T], data: Any) -> T:
    """Construye ``cls`` desde ``data`` ignorando claves desconocidas y tipos inválidos."""
    if not isinstance(data, dict):
        return cls()
    kwargs: dict[str, Any] = {}
    for f in fields(cls):  # type: ignore[arg-type]
        if f.name not in data:
            continue
        value = data[f.name]
        ftype = f.type
        default = f.default if f.default is not dataclasses.MISSING else (f.default_factory() if f.default_factory is not dataclasses.MISSING else None)  # type: ignore[misc]
        if is_dataclass(default):
            kwargs[f.name] = from_dict(type(default), value)
        elif isinstance(default, bool):
            kwargs[f.name] = bool(value) if isinstance(value, (bool, int)) else default
        elif isinstance(default, int):
            try:
                kwargs[f.name] = int(value)
            except (TypeError, ValueError):
                kwargs[f.name] = default
        elif isinstance(default, float):
            try:
                kwargs[f.name] = float(value)
            except (TypeError, ValueError):
                kwargs[f.name] = default
        elif isinstance(default, str):
            kwargs[f.name] = str(value) if value is not None else default
        elif isinstance(default, list):
            kwargs[f.name] = list(value) if isinstance(value, list) else default
        elif isinstance(default, dict):
            kwargs[f.name] = dict(value) if isinstance(value, dict) else default
        else:
            _ = ftype
            kwargs[f.name] = value
    return cls(**kwargs)  # type: ignore[call-arg]


# ------------------------------------------------------------------ store ----


def migrate(cfg: AppConfig, from_version: int) -> None:
    """Actualiza configuraciones guardadas por versiones anteriores."""
    if from_version < 2:
        cfg.cs2.netcon_tools_workaround = False  # -tools provocaba el cierre de CS2
    if from_version < 3:
        if cfg.cs2.hud_commands.strip() == OLD_HUD_COMMANDS:
            cfg.cs2.hud_commands = DEFAULT_HUD_COMMANDS
    cfg.version = max(cfg.version, CONFIG_VERSION)


class ConfigStore:
    """Carga/guarda ``AppConfig`` de forma atómica."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (appdata_dir() / CONFIG_FILE_NAME)
        self.config: AppConfig = AppConfig()

    def load(self) -> AppConfig:
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                self.config = from_dict(AppConfig, raw)
                migrate(self.config, int(raw.get("version", 1) or 1) if isinstance(raw, dict) else 1)
                log.info("Configuración cargada de %s", self.path)
            except (OSError, ValueError) as exc:
                log.warning("Configuración ilegible (%s); se usan valores por defecto", exc)
                self.config = AppConfig()
        else:
            self.config = AppConfig()
        return self.config

    def save(self) -> None:
        data = to_dict(self.config)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="config_", suffix=".json", dir=str(self.path.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, ensure_ascii=False, indent=2)
            os.replace(tmp_name, self.path)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise

    # Perfiles: instantáneas de detection/style/export/scoring con nombre.
    def save_profile(self, name: str) -> None:
        self.config.profiles[name] = {
            "detection": to_dict(self.config.detection),
            "style": to_dict(self.config.style),
            "export": to_dict(self.config.export),
            "scoring": to_dict(self.config.scoring),
            "wizard": dict(self.config.ui.last_wizard),
        }

    def apply_profile(self, name: str) -> bool:
        prof = self.config.profiles.get(name)
        if not prof:
            return False
        self.config.detection = from_dict(DetectionSettings, prof.get("detection"))
        self.config.style = from_dict(StyleSettings, prof.get("style"))
        self.config.export = from_dict(ExportSettings, prof.get("export"))
        self.config.scoring = from_dict(ScoringWeights, prof.get("scoring"))
        wizard = prof.get("wizard")
        if isinstance(wizard, dict):
            self.config.ui.last_wizard = dict(wizard)
        return True

    def delete_profile(self, name: str) -> None:
        self.config.profiles.pop(name, None)


def ensure_default_profiles(store: ConfigStore) -> None:
    """Crea los perfiles de fábrica si no existen todavía."""
    cfg = store.config
    if "Highlights YouTube" not in cfg.profiles:
        store.save_profile("Highlights YouTube")
    if "Shorts" not in cfg.profiles:
        shorts_style = dataclasses.replace(cfg.style, aspect="9:16", intro_enabled=False, outro_enabled=False)
        shorts_export = dataclasses.replace(cfg.export, preset="shorts_1080x1920")
        cfg.profiles["Shorts"] = {
            "detection": to_dict(cfg.detection),
            "style": to_dict(shorts_style),
            "export": to_dict(shorts_export),
            "scoring": to_dict(cfg.scoring),
            "wizard": {"duration_target": "1-3 min"},
        }


_store: ConfigStore | None = None


def get_store() -> ConfigStore:
    global _store
    if _store is None:
        _store = ConfigStore()
        _store.load()
        ensure_default_profiles(_store)
    return _store


def get_config() -> AppConfig:
    return get_store().config


def save_config() -> None:
    try:
        get_store().save()
    except OSError as exc:
        log.error("No se pudo guardar la configuración: %s", exc)
