"""Estadísticas de partida por jugador (K/D, ADR, HS%, clutches)."""

from __future__ import annotations

from dataclasses import dataclass

from clutchreel.core.demo.models import TEAM_CT, TEAM_T, MatchData


@dataclass
class PlayerStats:
    steamid64: int
    name: str
    kills: int
    deaths: int
    assists: int
    headshots: int
    damage: int
    rounds: int
    clutches_won: int
    multikills: int

    @property
    def kd(self) -> float:
        return self.kills / self.deaths if self.deaths else float(self.kills)

    @property
    def adr(self) -> float:
        return self.damage / self.rounds if self.rounds else 0.0

    @property
    def hs_pct(self) -> float:
        return 100.0 * self.headshots / self.kills if self.kills else 0.0


def compute_stats(match: MatchData) -> list[PlayerStats]:
    rounds = len(match.rounds)
    out: list[PlayerStats] = []
    kills_by: dict[int, int] = {}
    deaths_by: dict[int, int] = {}
    assists_by: dict[int, int] = {}
    hs_by: dict[int, int] = {}
    for k in match.kills:
        deaths_by[k.victim_steamid] = deaths_by.get(k.victim_steamid, 0) + 1
        if k.is_teamkill or k.is_suicide:
            continue
        kills_by[k.attacker_steamid] = kills_by.get(k.attacker_steamid, 0) + 1
        if k.headshot:
            hs_by[k.attacker_steamid] = hs_by.get(k.attacker_steamid, 0) + 1
        if k.assister_steamid:
            assists_by[k.assister_steamid] = assists_by.get(k.assister_steamid, 0) + 1
    for p in match.players:
        clutches = 0
        multikills = 0
        for rnd in match.rounds:
            my_team = rnd.players_at_start.get(p.steamid64, 0)
            if my_team not in (TEAM_T, TEAM_CT):
                continue
            kills_in_round = [k for k in match.kills if k.round == rnd.number and k.attacker_steamid == p.steamid64 and not k.is_teamkill]
            if len(kills_in_round) >= 3:
                multikills += 1
            alive = dict(rnd.players_at_start)
            enemy_team = TEAM_CT if my_team == TEAM_T else TEAM_T
            clutch_started = False
            for k in match.kills:
                if k.round != rnd.number:
                    continue
                alive.pop(k.victim_steamid, None)
                mine = [s for s, t in alive.items() if t == my_team]
                enemies = [s for s, t in alive.items() if t == enemy_team]
                if p.steamid64 in mine and len(mine) == 1 and len(enemies) >= 2:
                    clutch_started = True
                    break
            if clutch_started and rnd.winner_team == my_team:
                clutches += 1
        out.append(
            PlayerStats(
                steamid64=p.steamid64,
                name=p.name,
                kills=kills_by.get(p.steamid64, p.kills),
                deaths=deaths_by.get(p.steamid64, p.deaths),
                assists=assists_by.get(p.steamid64, p.assists),
                headshots=hs_by.get(p.steamid64, p.headshots),
                damage=p.damage,
                rounds=rounds,
                clutches_won=clutches,
                multikills=multikills,
            )
        )
    out.sort(key=lambda s: (-s.kills, s.name.lower()))
    return out
