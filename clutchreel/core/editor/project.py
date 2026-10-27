"""Proyecto ClutchReel (.json): demo analizada, jugadas, clips editables y estilo."""

from __future__ import annotations

import copy
import json
import logging
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from clutchreel.core.demo.models import Highlight, MatchData
from clutchreel.services.config import StyleSettings, from_dict, to_dict
from clutchreel.utils.paths import projects_dir, safe_filename

log = logging.getLogger(__name__)

PROJECT_VERSION = 1


@dataclass
class Clip:
    """Un clip del vídeo final: jugada + ajustes de edición + grabación asociada."""

    id: str
    highlight: Highlight
    enabled: bool = True
    # Recorte relativo a la grabación del clip (segundos). 0 = sin recorte.
    trim_start: float = 0.0
    trim_end: float = 0.0
    slow_motion: bool = True
    overlay_text: str = ""
    transition_in: str = "fade"
    transition_out: str = "fade"
    zoom: float = 1.0
    game_volume: float = 1.0
    # Fichero grabado (ruta absoluta) y desplazamiento del inicio de la jugada dentro de él.
    recording_path: str = ""
    recording_offset: float = 0.0
    # Ticks de demo por segundo de vídeo en la grabación (CS2 reproduce las demos algo más lento que
    # el tiempo real; medido ~58 ticks/s con demos de 64). 0 = se usa el tickrate nominal.
    recording_tickrate: float = 0.0
    recording_ok: bool = False
    # Jugador al que siguió de verdad la cámara (comprobado con la posición de la cámara en CS2).
    recorded_player_steamid: int = 0
    recorded_player_name: str = ""
    camera_verified: bool = False
    camera_note: str = ""  # método de verificación o motivo del último fallo

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["highlight"] = self.highlight.to_dict()
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Clip:
        hl = Highlight.from_dict(data.get("highlight", {}))
        return Clip(
            id=str(data.get("id") or uuid.uuid4().hex),
            highlight=hl,
            enabled=bool(data.get("enabled", True)),
            trim_start=float(data.get("trim_start", 0.0)),
            trim_end=float(data.get("trim_end", 0.0)),
            slow_motion=bool(data.get("slow_motion", True)),
            overlay_text=str(data.get("overlay_text", "")),
            transition_in=str(data.get("transition_in", "fade")),
            transition_out=str(data.get("transition_out", "fade")),
            zoom=float(data.get("zoom", 1.0)),
            game_volume=float(data.get("game_volume", 1.0)),
            recording_path=str(data.get("recording_path", "")),
            recording_offset=float(data.get("recording_offset", 0.0)),
            recording_tickrate=float(data.get("recording_tickrate", 0.0) or 0.0),
            recording_ok=bool(data.get("recording_ok", False)),
            recorded_player_steamid=int(data.get("recorded_player_steamid", 0) or 0),
            recorded_player_name=str(data.get("recorded_player_name", "")),
            camera_verified=bool(data.get("camera_verified", False)),
            camera_note=str(data.get("camera_note", "")),
        )

    def duration_seconds(self, tickrate: float) -> float:
        base = self.highlight.duration_seconds(tickrate)
        return max(0.5, base - self.trim_start - self.trim_end)

    def effective_tickrate(self, tickrate: float) -> float:
        """Ticks por segundo DENTRO de la grabación de este clip (medidos al grabar), o el nominal."""
        return self.recording_tickrate if self.recording_tickrate > 0 else tickrate

    def recorded_duration_seconds(self, tickrate: float) -> float:
        """Duración del clip en segundos de vídeo grabado (con recortes)."""
        return self.duration_seconds(self.effective_tickrate(tickrate))

    @property
    def has_recording(self) -> bool:
        return bool(self.recording_path) and Path(self.recording_path).exists()

    @property
    def is_recorded(self) -> bool:
        """Grabación válida y con la cámara comprobada en el jugador (las de versiones anteriores no lo están)."""
        return self.recording_ok and self.camera_verified and self.has_recording


@dataclass
class Project:
    name: str
    match: MatchData
    player_steamid: int
    player_name: str
    clips: list[Clip] = field(default_factory=list)
    style: StyleSettings = field(default_factory=StyleSettings)
    export_preset: str = "youtube_1080p60"
    order_mode: str = "cronológico"
    duration_target: str = "3-5 min"
    recording_mode: str = "obs"  # obs | existing
    existing_recording: str = ""
    existing_recording_offset: float = 0.0  # segundos del vídeo que corresponden al tick 0 de la demo
    output_video: str = ""
    thumbnail: str = ""
    created_at: float = field(default_factory=time.time)
    path: str = ""
    wizard: dict[str, Any] = field(default_factory=dict)

    # --------------------------------------------------------------- helpers --

    @property
    def tickrate(self) -> float:
        return self.match.tickrate

    def enabled_clips(self) -> list[Clip]:
        return [c for c in self.clips if c.enabled]

    def total_duration(self) -> float:
        total = sum(c.duration_seconds(self.tickrate) for c in self.enabled_clips())
        if self.style.intro_enabled:
            total += 3.0
        if self.style.outro_enabled:
            total += 3.0
        return total

    def clip_by_id(self, clip_id: str) -> Clip | None:
        for c in self.clips:
            if c.id == clip_id:
                return c
        return None

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": PROJECT_VERSION,
            "name": self.name,
            "match": self.match.to_dict(),
            "player_steamid": self.player_steamid,
            "player_name": self.player_name,
            "clips": [c.to_dict() for c in self.clips],
            "style": to_dict(self.style),
            "export_preset": self.export_preset,
            "order_mode": self.order_mode,
            "duration_target": self.duration_target,
            "recording_mode": self.recording_mode,
            "existing_recording": self.existing_recording,
            "existing_recording_offset": self.existing_recording_offset,
            "output_video": self.output_video,
            "thumbnail": self.thumbnail,
            "created_at": self.created_at,
            "wizard": self.wizard,
        }

    @staticmethod
    def from_dict(data: dict[str, Any], path: str = "") -> Project:
        return Project(
            name=str(data.get("name", "Proyecto")),
            match=MatchData.from_dict(data.get("match", {})),
            player_steamid=int(data.get("player_steamid", 0)),
            player_name=str(data.get("player_name", "")),
            clips=[Clip.from_dict(c) for c in data.get("clips", [])],
            style=from_dict(StyleSettings, data.get("style")),
            export_preset=str(data.get("export_preset", "youtube_1080p60")),
            order_mode=str(data.get("order_mode", "cronológico")),
            duration_target=str(data.get("duration_target", "3-5 min")),
            recording_mode=str(data.get("recording_mode", "obs")),
            existing_recording=str(data.get("existing_recording", "")),
            existing_recording_offset=float(data.get("existing_recording_offset", 0.0)),
            output_video=str(data.get("output_video", "")),
            thumbnail=str(data.get("thumbnail", "")),
            created_at=float(data.get("created_at", time.time())),
            path=path,
            wizard=dict(data.get("wizard", {})),
        )

    # ------------------------------------------------------------- persist --

    def default_path(self) -> Path:
        base = safe_filename(f"{self.name}")
        return projects_dir() / f"{base}.clutchreel.json"

    def save(self, path: Path | None = None) -> Path:
        target = path or (Path(self.path) if self.path else self.default_path())
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(prefix="proj_", suffix=".json", dir=str(target.parent))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.to_dict(), fh, ensure_ascii=False, indent=1)
            os.replace(tmp_name, target)
        except OSError:
            try:
                os.unlink(tmp_name)
            except OSError:
                pass
            raise
        self.path = str(target)
        return target

    @staticmethod
    def load(path: Path) -> Project:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("El fichero no es un proyecto de ClutchReel.")
        return Project.from_dict(data, path=str(path))

    def snapshot(self) -> dict[str, Any]:
        return copy.deepcopy(self.to_dict())

    def restore(self, snap: dict[str, Any]) -> None:
        other = Project.from_dict(copy.deepcopy(snap), path=self.path)
        self.clips = other.clips
        self.style = other.style
        self.order_mode = other.order_mode
        self.export_preset = other.export_preset


def new_project(match: MatchData, steamid: int, player_name: str, highlights: list[Highlight], style: StyleSettings) -> Project:
    stem = Path(match.demo_path).stem[:24]
    name = f"{safe_filename(player_name)} - {match.map_name} - {stem}"
    clips = [Clip(id=uuid.uuid4().hex, highlight=h, slow_motion=style.slow_motion) for h in highlights]
    return Project(name=name, match=match, player_steamid=steamid, player_name=player_name, clips=clips, style=copy.deepcopy(style))


class UndoStack:
    """Pila de instantáneas del proyecto (deshacer/rehacer)."""

    def __init__(self, limit: int = 60) -> None:
        self._undo: list[dict[str, Any]] = []
        self._redo: list[dict[str, Any]] = []
        self.limit = limit

    def push(self, project: Project) -> None:
        self._undo.append(project.snapshot())
        if len(self._undo) > self.limit:
            del self._undo[0]
        self._redo.clear()

    def undo(self, project: Project) -> bool:
        if not self._undo:
            return False
        self._redo.append(project.snapshot())
        project.restore(self._undo.pop())
        return True

    def redo(self, project: Project) -> bool:
        if not self._redo:
            return False
        self._undo.append(project.snapshot())
        project.restore(self._redo.pop())
        return True

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)
