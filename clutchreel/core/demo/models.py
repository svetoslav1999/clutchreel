"""Modelos de datos del análisis de demos (independientes de demoparser2)."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from clutchreel.utils.timeutil import ticks_to_seconds

TEAM_T = 2
TEAM_CT = 3

KIND_LABELS: dict[str, str] = {
    "ace": "ACE",
    "4k": "4K",
    "3k": "3K",
    "2k": "2K",
    "clutch": "Clutch",
    "headshot_streak": "Racha de headshots",
    "entry": "Primera baja",
    "awp": "AWP",
    "noscope": "No-scope",
    "wallbang": "Wallbang",
    "smoke": "A través de humo",
    "blind": "Cegado",
    "air": "En el aire",
    "knife": "Cuchillo",
    "decisive": "Ronda decisiva",
    "best_round": "Mejor ronda",
    "kill": "Kill",
    "all_kills": "Todas las kills",
}


@dataclass
class PlayerInfo:
    steamid64: int
    name: str
    team_num: int = 0
    user_id: int = -1
    kills: int = 0
    deaths: int = 0
    assists: int = 0
    headshots: int = 0
    damage: int = 0

    @property
    def team_label(self) -> str:
        return {TEAM_T: "T", TEAM_CT: "CT"}.get(self.team_num, "?")


@dataclass
class KillEvent:
    tick: int
    round: int
    attacker_steamid: int
    attacker_name: str
    victim_steamid: int
    victim_name: str
    weapon: str
    headshot: bool = False
    noscope: bool = False
    thrusmoke: bool = False
    penetrated: int = 0
    attackerblind: bool = False
    attackerinair: bool = False
    distance: float = 0.0
    assister_steamid: int = 0
    attacker_team: int = 0
    victim_team: int = 0

    @property
    def is_teamkill(self) -> bool:
        return self.attacker_team != 0 and self.attacker_team == self.victim_team

    @property
    def is_suicide(self) -> bool:
        return self.attacker_steamid == self.victim_steamid or self.attacker_steamid == 0

    @property
    def is_knife(self) -> bool:
        w = self.weapon.lower()
        return "knife" in w or "bayonet" in w or w in {"karambit", "m9_bayonet"}

    @property
    def is_awp(self) -> bool:
        return self.weapon.lower() in {"awp", "weapon_awp"}

    @property
    def is_pistol(self) -> bool:
        return self.weapon.lower() in {
            "glock",
            "usp_silencer",
            "hkp2000",
            "p250",
            "fiveseven",
            "tec9",
            "cz75a",
            "deagle",
            "elite",
            "revolver",
        }


@dataclass
class RoundInfo:
    number: int
    start_tick: int
    freeze_end_tick: int
    end_tick: int
    winner_team: int = 0
    reason: str = ""
    ct_score_after: int = 0
    t_score_after: int = 0
    # steamid64 → team_num de jugadores vivos al comenzar la ronda
    players_at_start: dict[int, int] = field(default_factory=dict)

    @property
    def duration_ticks(self) -> int:
        return max(0, self.end_tick - self.start_tick)


@dataclass
class Highlight:
    """Una jugada detectada, en ticks de la demo."""

    kind: str
    round: int
    start_tick: int
    end_tick: int
    score: float
    description: str
    kills: list[KillEvent] = field(default_factory=list)
    key_tick: int = 0  # tick del momento clave (última kill)
    tags: list[str] = field(default_factory=list)
    merged_kinds: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def duration_seconds(self, tickrate: float) -> float:
        return ticks_to_seconds(self.end_tick - self.start_tick, tickrate)

    def start_seconds(self, tickrate: float) -> float:
        return ticks_to_seconds(self.start_tick, tickrate)

    def kind_label(self, kind: str) -> str:
        """Texto de un tipo. Con ACE desactivado, 5 o más kills quedan como «4k» pero se muestran por su número («5K»)."""
        if kind == "4k":
            n = int(self.extra.get("kills", 0) or 0)
            if n >= 5:
                return f"{n}K"
        return KIND_LABELS.get(kind, kind)

    @property
    def label(self) -> str:
        kinds = self.merged_kinds or [self.kind]
        return " + ".join(self.kind_label(k) for k in kinds)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data

    @staticmethod
    def from_dict(data: dict[str, Any]) -> Highlight:
        kills = [KillEvent(**k) for k in data.get("kills", [])]
        return Highlight(
            kind=str(data.get("kind", "kill")),
            round=int(data.get("round", 0)),
            start_tick=int(data.get("start_tick", 0)),
            end_tick=int(data.get("end_tick", 0)),
            score=float(data.get("score", 0.0)),
            description=str(data.get("description", "")),
            kills=kills,
            key_tick=int(data.get("key_tick", 0)),
            tags=list(data.get("tags", [])),
            merged_kinds=list(data.get("merged_kinds", [])),
            extra=dict(data.get("extra", {})),
        )


@dataclass
class MatchData:
    """Resultado completo del análisis de una demo."""

    demo_path: str
    map_name: str
    tickrate: float
    total_ticks: int
    server_name: str = ""
    demo_date: str = ""
    players: list[PlayerInfo] = field(default_factory=list)
    kills: list[KillEvent] = field(default_factory=list)
    rounds: list[RoundInfo] = field(default_factory=list)
    final_score_ct: int = 0
    final_score_t: int = 0
    game_mode: str = ""
    warnings: list[str] = field(default_factory=list)

    @property
    def duration_seconds(self) -> float:
        return ticks_to_seconds(self.total_ticks, self.tickrate)

    def player_by_steamid(self, steamid64: int) -> PlayerInfo | None:
        for p in self.players:
            if p.steamid64 == steamid64:
                return p
        return None

    def player_team_in_round(self, steamid64: int, round_number: int) -> int:
        rnd = self.round_by_number(round_number)
        if rnd and steamid64 in rnd.players_at_start:
            return rnd.players_at_start[steamid64]
        p = self.player_by_steamid(steamid64)
        return p.team_num if p else 0

    def round_by_number(self, number: int) -> RoundInfo | None:
        for r in self.rounds:
            if r.number == number:
                return r
        return None

    def score_label(self) -> str:
        return f"CT {self.final_score_ct} – {self.final_score_t} T"

    def to_dict(self) -> dict[str, Any]:
        return {
            "demo_path": self.demo_path,
            "map_name": self.map_name,
            "tickrate": self.tickrate,
            "total_ticks": self.total_ticks,
            "server_name": self.server_name,
            "demo_date": self.demo_date,
            "players": [asdict(p) for p in self.players],
            "kills": [asdict(k) for k in self.kills],
            "rounds": [asdict(r) for r in self.rounds],
            "final_score_ct": self.final_score_ct,
            "final_score_t": self.final_score_t,
            "game_mode": self.game_mode,
            "warnings": list(self.warnings),
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> MatchData:
        rounds = []
        for r in data.get("rounds", []):
            r = dict(r)
            r["players_at_start"] = {int(k): int(v) for k, v in r.get("players_at_start", {}).items()}
            rounds.append(RoundInfo(**r))
        return MatchData(
            demo_path=str(data.get("demo_path", "")),
            map_name=str(data.get("map_name", "")),
            tickrate=float(data.get("tickrate", 64.0)),
            total_ticks=int(data.get("total_ticks", 0)),
            server_name=str(data.get("server_name", "")),
            demo_date=str(data.get("demo_date", "")),
            players=[PlayerInfo(**p) for p in data.get("players", [])],
            kills=[KillEvent(**k) for k in data.get("kills", [])],
            rounds=rounds,
            final_score_ct=int(data.get("final_score_ct", 0)),
            final_score_t=int(data.get("final_score_t", 0)),
            game_mode=str(data.get("game_mode", "")),
            warnings=list(data.get("warnings", [])),
        )
