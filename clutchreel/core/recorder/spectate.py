"""Seguir al jugador correcto en el visor de demos de CS2 y comprobarlo.

Hechos verificados en CS2 1.41.9.2 (octubre 2026) por el puerto de consola:

* ``spec_player N`` usa el **slot + 1** del jugador (``spec_player 4`` sigue al
  slot 3). El slot es el ``user_id`` que da demoparser2 y puede cambiar a lo
  largo de la partida (reconexiones), así que se resuelve en el tick de cada clip.
* ``spec_player_by_accountid`` y ``spec_lock_to_accountid`` **no existen**.
* ``spec_mode 2`` = primera persona (in-eye); 3 y 4 = tercera persona.
* Con la cámara en primera persona, ``getpos`` devuelve exactamente la posición
  del ojo del jugador observado (X, Y de la demo y Z + 64 de pie / + 46
  agachado). Comparándola con las posiciones de la demo en ese tick se sabe
  con certeza a quién sigue la cámara, sin leer la pantalla.
"""

from __future__ import annotations

import logging
import math
import re
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Altura del ojo sobre el origen del jugador (de pie, agachado) en unidades de Source 2.
EYE_HEIGHTS = (64.0, 46.0)
# Distancia máxima cámara-ojo para dar por bueno que la cámara está en un jugador.
MAX_MATCH_DISTANCE = 48.0
# Paso entre ticks muestreados para verificar durante la reproducción.
SAMPLE_STRIDE = 4

_SETPOS_RE = re.compile(r"setpos\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)\s+(-?\d+(?:\.\d+)?)")
# Línea real de la consola cada vez que la cámara en primera persona cambia de jugador
# (CS2 1.41.9): «Added TrueView prediction for player slot 3 (♛Jugador Uno♛)».
TRUEVIEW_RE = re.compile(r"Added TrueView prediction for player slot (\d+) \((.*)\)")
_TRUEVIEW_RE = TRUEVIEW_RE


class SpectateError(Exception):
    """La cámara no sigue al jugador pedido (mensaje entendible)."""


@dataclass(frozen=True)
class PlayerSample:
    steamid64: int
    name: str
    slot: int
    x: float
    y: float
    z: float
    alive: bool


@dataclass
class CameraMatch:
    """A quién sigue la cámara según su posición."""

    steamid64: int
    name: str
    distance: float
    target_distance: float = math.inf


def spec_player_command(slot: int) -> str:
    """Comando que sigue al jugador del slot indicado (``user_id`` de la demo)."""
    if slot < 0:
        raise ValueError("slot negativo")
    return f"spec_player {slot + 1}"


def spec_name_command(name: str) -> str:
    return 'spec_player "{}"'.format(name.replace('"', ""))


def parse_getpos(text: str) -> tuple[float, float, float] | None:
    """Última posición ``setpos x y z`` impresa por ``getpos``/``spec_pos``."""
    found = _SETPOS_RE.findall(text or "")
    if not found:
        return None
    x, y, z = found[-1]
    return float(x), float(y), float(z)


def parse_trueview(text: str) -> tuple[int, str] | None:
    """Slot y nombre del último cambio de cámara («Added TrueView prediction for player slot N (nombre)»)."""
    found = parse_trueview_all(text)
    return found[-1] if found else None


def parse_trueview_all(text: str) -> list[tuple[int, str]]:
    """Todos los cambios de cámara del texto, en orden."""
    return [(int(slot), name) for slot, name in _TRUEVIEW_RE.findall(text or "")]


def eye_distance(cam: tuple[float, float, float], sample: PlayerSample) -> float:
    """Distancia entre la cámara y el ojo del jugador (la menor de pie/agachado)."""
    dx = cam[0] - sample.x
    dy = cam[1] - sample.y
    best = math.inf
    for h in EYE_HEIGHTS:
        dz = cam[2] - (sample.z + h)
        best = min(best, math.sqrt(dx * dx + dy * dy + dz * dz))
    return best


@dataclass
class DemoTimeline:
    """Posición, slot y estado de cada jugador en ticks concretos de la demo."""

    demo_path: str
    _by_tick: dict[int, list[PlayerSample]] = field(default_factory=dict)
    _parser: Any = None

    # ----------------------------------------------------------- carga ---

    def _get_parser(self) -> Any:
        if self._parser is None:
            from demoparser2 import DemoParser  # import tardío: carga nativa lenta

            self._parser = DemoParser(str(Path(self.demo_path)))
        return self._parser

    def load(self, ticks: Iterable[int]) -> None:
        """Lee de la demo los ticks pedidos que aún no estén en memoria."""
        wanted = sorted({int(t) for t in ticks if int(t) >= 0} - set(self._by_tick))
        if not wanted:
            return
        df = self._get_parser().parse_ticks(["X", "Y", "Z", "user_id", "is_alive"], ticks=wanted)
        self.add_rows(df.to_dict("records"))
        for t in wanted:
            self._by_tick.setdefault(t, [])

    def add_rows(self, rows: Iterable[dict[str, Any]]) -> None:
        for row in rows:
            try:
                tick = int(row["tick"])
                sample = PlayerSample(
                    steamid64=int(row.get("steamid") or 0),
                    name=str(row.get("name") or ""),
                    slot=int(row.get("user_id", -1) if row.get("user_id") is not None else -1),
                    x=float(row["X"]),
                    y=float(row["Y"]),
                    z=float(row["Z"]),
                    alive=bool(row.get("is_alive", True)),
                )
            except (KeyError, TypeError, ValueError):
                continue
            if sample.steamid64 <= 0 or any(math.isnan(v) for v in (sample.x, sample.y, sample.z)):
                continue
            self._by_tick.setdefault(tick, []).append(sample)

    def load_ranges(self, ranges: Iterable[tuple[int, int]], stride: int = SAMPLE_STRIDE) -> None:
        ticks: set[int] = set()
        for start, end in ranges:
            ticks.update(range(int(start), int(end) + 1, max(1, stride)))
            ticks.add(int(end))
        self.load(ticks)

    # -------------------------------------------------------- consultas ---

    def _nearest_tick(self, tick: int) -> int | None:
        if tick in self._by_tick:
            return tick
        if not self._by_tick:
            return None
        return min(self._by_tick, key=lambda t: abs(t - tick))

    def samples(self, tick: int) -> list[PlayerSample]:
        near = self._nearest_tick(tick)
        return list(self._by_tick.get(near, [])) if near is not None else []

    def sample_of(self, steamid64: int, tick: int) -> PlayerSample | None:
        for s in self.samples(tick):
            if s.steamid64 == steamid64:
                return s
        return None

    def slot_of(self, steamid64: int, tick: int) -> int | None:
        s = self.sample_of(steamid64, tick)
        return s.slot if s is not None and s.slot >= 0 else None

    def is_alive(self, steamid64: int, tick: int) -> bool:
        s = self.sample_of(steamid64, tick)
        return bool(s and s.alive)

    def identify(self, cam: tuple[float, float, float], tick: int, window: int = 16, target: int = 0) -> CameraMatch | None:
        """Jugador vivo cuyo ojo está más cerca de la cámara en ``tick ± window``."""
        best: dict[int, tuple[float, str]] = {}
        ticks = [t for t in self._by_tick if abs(t - tick) <= window]
        if not ticks:
            near = self._nearest_tick(tick)
            ticks = [near] if near is not None else []
        for t in ticks:
            for s in self._by_tick.get(t, []):
                if not s.alive:
                    continue
                d = eye_distance(cam, s)
                if s.steamid64 not in best or d < best[s.steamid64][0]:
                    best[s.steamid64] = (d, s.name)
        if not best:
            return None
        sid, (dist, name) = min(best.items(), key=lambda kv: kv[1][0])
        target_dist = best.get(target, (math.inf, ""))[0] if target else math.inf
        return CameraMatch(sid, name, dist, target_dist)


def camera_on_target(match: CameraMatch | None, target: int, tolerance: float = MAX_MATCH_DISTANCE) -> bool:
    """La cámara está en ``target`` si su ojo es el más cercano (o empatado) y está a menos de ``tolerance``."""
    if match is None:
        return False
    if match.target_distance > tolerance:
        return False
    return match.steamid64 == target or match.target_distance - match.distance < 8.0


@dataclass
class PlaybackCheck:
    """Resultado de comprobar la cámara durante la grabación."""

    samples: int = 0
    on_target: int = 0
    off_target: list[tuple[float, str]] = field(default_factory=list)  # (segundo, nombre visto) según getpos
    switches: list[tuple[float, str]] = field(default_factory=list)  # (segundo, nombre) anunciados por CS2 en la consola
    # Proporción mínima de muestras en el jugador. Si además se vigilaron los anuncios de cámara de CS2
    # (que avisan de cualquier cambio de jugador) basta con menos, porque las muestras de posición
    # también fallan por el desfase entre el reloj del PC y el de la demo.
    min_ratio: float = 0.85

    @property
    def ratio(self) -> float:
        return self.on_target / self.samples if self.samples else 1.0

    def ok(self, min_ratio: float | None = None) -> bool:
        if self.switches:
            return False  # CS2 dijo explícitamente que la cámara pasó a otro jugador con el nuestro aún vivo
        need = self.min_ratio if min_ratio is None else min_ratio
        return self.samples == 0 or self.ratio >= need

    def describe(self) -> str:
        entries = self.off_target + self.switches
        if not entries:
            return ""
        names = sorted({n for _t, n in entries if n})
        first = min(t for t, _n in entries)
        who = ", ".join(names) if names else "otro jugador"
        parts: list[str] = []
        if self.switches:
            parts.append("cambio anunciado por CS2")
        if self.off_target:
            parts.append(f"{self.samples - self.on_target}/{self.samples} muestras fuera")
        return f"la cámara pasó a {who} (desde el segundo {first:.1f}; {'; '.join(parts)})"
