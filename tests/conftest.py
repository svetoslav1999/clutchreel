"""Datos sintéticos compartidos por los tests."""

from __future__ import annotations

import pytest

from clutchreel.core.demo.models import TEAM_CT, TEAM_T, KillEvent, MatchData, PlayerInfo, RoundInfo

ME = 76561198000000001
MATES = [76561198000000002, 76561198000000003, 76561198000000004, 76561198000000005]
ENEMIES = [76561198000000011, 76561198000000012, 76561198000000013, 76561198000000014, 76561198000000015]
TICKRATE = 64.0


def make_round(number: int, start: int, winner: int) -> RoundInfo:
    lineup = {ME: TEAM_CT, **{m: TEAM_CT for m in MATES}, **{e: TEAM_T for e in ENEMIES}}
    return RoundInfo(number=number, start_tick=start, freeze_end_tick=start + 1000, end_tick=start + 7000, winner_team=winner, players_at_start=lineup)


def kill(tick: int, rnd: int, attacker: int, victim: int, weapon: str = "ak47", **kw: object) -> KillEvent:
    att_team = TEAM_CT if attacker == ME or attacker in MATES else TEAM_T
    vic_team = TEAM_CT if victim == ME or victim in MATES else TEAM_T
    return KillEvent(tick=tick, round=rnd, attacker_steamid=attacker, attacker_name=f"p{attacker % 100}", victim_steamid=victim, victim_name=f"p{victim % 100}", weapon=weapon, attacker_team=att_team, victim_team=vic_team, **kw)  # type: ignore[arg-type]


@pytest.fixture
def match() -> MatchData:
    rounds = [make_round(1, 0, TEAM_CT), make_round(2, 8000, TEAM_T), make_round(3, 16000, TEAM_CT)]
    players = [PlayerInfo(ME, "yo", TEAM_CT, user_id=3)] + [PlayerInfo(m, f"mate{m % 10}", TEAM_CT) for m in MATES] + [PlayerInfo(e, f"enemy{e % 10}", TEAM_T) for e in ENEMIES]
    kills = [
        # Ronda 1: 3K rápido del jugador (ventana 12 s = 768 ticks) con un headshot streak de 3
        kill(1500, 1, ME, ENEMIES[0], headshot=True),
        kill(1700, 1, ME, ENEMIES[1], headshot=True),
        kill(1900, 1, ME, ENEMIES[2], headshot=True, weapon="awp", noscope=True),
        kill(2500, 1, ENEMIES[3], MATES[0]),
        # Ronda 2: clutch 1v2: mueren mis 4 compañeros, quedan 2 enemigos, los mato → pero ronda perdida (T) → clutch casi
        kill(9000, 2, ENEMIES[0], MATES[0]),
        kill(9100, 2, ENEMIES[0], MATES[1]),
        kill(9200, 2, ENEMIES[1], MATES[2]),
        kill(9300, 2, ME, ENEMIES[2]),
        kill(9400, 2, ME, ENEMIES[3]),
        kill(9500, 2, ME, ENEMIES[4]),
        kill(9600, 2, ENEMIES[1], MATES[3]),  # ahora estoy solo contra 2
        kill(10200, 2, ME, ENEMIES[0], penetrated=1),
        kill(11000, 2, ENEMIES[1], ME),
        # Ronda 3: entry kill y ronda decisiva (última)
        kill(17200, 3, ME, ENEMIES[0], weapon="deagle", thrusmoke=True),
        kill(20000, 3, MATES[0], ENEMIES[1]),
    ]
    return MatchData(demo_path="synthetic.dem", map_name="de_test", tickrate=TICKRATE, total_ticks=24000, players=players, kills=kills, rounds=rounds, final_score_ct=2, final_score_t=1)


@pytest.fixture(autouse=True)
def _isolated_appdata(tmp_path_factory, monkeypatch):  # type: ignore[no-untyped-def]
    """Los tests nunca escriben en el %APPDATA% real del usuario."""
    monkeypatch.setenv("APPDATA", str(tmp_path_factory.mktemp("appdata")))
