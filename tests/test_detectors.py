from __future__ import annotations

import itertools

from clutchreel.core.demo.detectors import DetectionContext, detect_all, detect_clutches, detect_headshot_streaks, detect_multikills, merge_highlights
from clutchreel.core.demo.models import Highlight
from clutchreel.core.demo.selector import select_by_duration
from clutchreel.core.demo.stats import compute_stats
from clutchreel.services.config import DetectionSettings, ScoringWeights
from tests.conftest import ME, TICKRATE


def ctx(match, **kw):  # type: ignore[no-untyped-def]
    settings = DetectionSettings(**kw)
    return DetectionContext(match=match, steamid64=ME, settings=settings, weights=ScoringWeights())


def test_multikill_detects_3k_and_ace(match):  # type: ignore[no-untyped-def]
    found = detect_multikills(ctx(match))
    kinds = {h.round: h.kind for h in found}
    assert kinds[1] == "3k"
    assert kinds[2] == "4k"  # 4 kills en la ronda 2 (ventana 12 s agrupa 3 + 1 separada... se comprueba abajo)
    r1 = next(h for h in found if h.round == 1)
    assert len(r1.kills) == 3
    assert r1.start_tick < r1.kills[0].tick
    assert r1.end_tick > r1.kills[-1].tick


def test_multikill_window_splits_groups(match):  # type: ignore[no-untyped-def]
    found = detect_multikills(ctx(match, multikill_window=2.0))  # 2 s = 128 ticks
    r2 = [h for h in found if h.round == 2]
    # Las tres primeras kills están a 100 ticks: grupo de 3; la cuarta (10200) queda sola → no es multikill
    assert len(r2) == 1 and r2[0].kind == "3k"


def test_clutch_detected_lost_and_scored(match):  # type: ignore[no-untyped-def]
    found = detect_clutches(ctx(match))
    assert len(found) == 1
    h = found[0]
    assert h.round == 2
    assert h.extra["enemies"] == 2
    assert h.extra["won"] is False
    assert "1v2" in h.tags


def test_clutch_excluded_when_lost_not_allowed(match):  # type: ignore[no-untyped-def]
    assert detect_clutches(ctx(match, include_lost_clutches=False)) == []


def test_headshot_streak(match):  # type: ignore[no-untyped-def]
    found = detect_headshot_streaks(ctx(match))
    assert len(found) == 1 and len(found[0].kills) == 3
    assert detect_headshot_streaks(ctx(match, headshot_streak_min=4)) == []


def test_detect_all_merges_overlaps(match):  # type: ignore[no-untyped-def]
    highlights = detect_all(match, ME, DetectionSettings(), ScoringWeights())
    rounds = [h.round for h in highlights]
    assert rounds == sorted(rounds)
    # La ronda 1 debe quedar en un solo clip fusionado (3K + HS streak + entry + AWP + noscope)
    r1 = [h for h in highlights if h.round == 1]
    assert len(r1) == 1
    assert "3k" in r1[0].merged_kinds and "headshot_streak" in r1[0].merged_kinds
    assert all(h.end_tick > h.start_tick for h in highlights)
    # Ningún solape entre clips
    for a, b in itertools.pairwise(highlights):
        assert b.start_tick >= a.end_tick or b.round != a.round


def test_player_without_kills_gives_nothing(match):  # type: ignore[no-untyped-def]
    assert detect_all(match, 76561198000000099, DetectionSettings(), ScoringWeights()) == []


def test_merge_keeps_max_score_plus_fraction():  # type: ignore[no-untyped-def]
    a = Highlight("2k", 1, 100, 500, 50.0, "a")
    b = Highlight("entry", 1, 450, 700, 20.0, "b")
    merged = merge_highlights([a, b], merge_gap_ticks=0)
    assert len(merged) == 1
    assert merged[0].score == 57.0
    assert merged[0].start_tick == 100 and merged[0].end_tick == 700


def test_select_by_duration_respects_limit():  # type: ignore[no-untyped-def]
    hls = [Highlight("kill", i, i * 1000, i * 1000 + 640 * 2, float(i), f"h{i}") for i in range(1, 60)]  # 20 s cada uno
    chosen = select_by_duration(hls, TICKRATE, "1-3 min")
    total = sum(h.duration_seconds(TICKRATE) + 0.5 for h in chosen)
    assert total <= 180.0
    assert chosen == sorted(chosen, key=lambda h: h.start_tick)
    assert max(h.score for h in hls) in {h.score for h in chosen}
    assert len(select_by_duration(hls, TICKRATE, "Sin límite")) == len(hls)


def test_stats(match):  # type: ignore[no-untyped-def]
    stats = {s.steamid64: s for s in compute_stats(match)}
    me = stats[ME]
    assert me.kills == 8
    assert me.deaths == 1
    assert me.multikills == 2
    assert me.clutches_won == 0
    assert round(me.hs_pct, 1) == 37.5


def test_halftime_side_switch_uses_per_round_lineup(match):  # type: ignore[no-untyped-def]
    """Tras el descanso el jugador cambia de bando: el clutch y las rondas decisivas se evalúan con la alineación de ESA ronda."""
    from clutchreel.core.demo.models import TEAM_CT, TEAM_T, RoundInfo
    from tests.conftest import ENEMIES, MATES, kill

    swapped = {ME: TEAM_T, **{m: TEAM_T for m in MATES}, **{e: TEAM_CT for e in ENEMIES}}
    r13 = RoundInfo(number=13, start_tick=100000, freeze_end_tick=101000, end_tick=107000, winner_team=TEAM_T, ct_score_after=6, t_score_after=7, players_at_start=swapped)
    match.rounds.append(r13)
    # Mis 4 compañeros (ahora T) mueren con los 5 enemigos (ahora CT) vivos: clutch 1v5; mato a 2 y la ronda la gana T (mi equipo).
    match.kills += [
        kill(102000, 13, ENEMIES[0], MATES[0]),
        kill(102100, 13, ENEMIES[0], MATES[1]),
        kill(102200, 13, ENEMIES[0], MATES[2]),
        kill(102300, 13, ENEMIES[0], MATES[3]),
        kill(102400, 13, ME, ENEMIES[0]),
        kill(102500, 13, ME, ENEMIES[1]),
    ]
    for k in match.kills:
        if k.round == 13:  # en la ronda 13 los equipos de las kills van al revés que en el resto del fixture
            k.attacker_team = swapped.get(k.attacker_steamid, 0)
            k.victim_team = swapped.get(k.victim_steamid, 0)
    found = detect_clutches(ctx(match))
    r13_clutch = [h for h in found if h.round == 13]
    assert len(r13_clutch) == 1 and r13_clutch[0].extra == {"enemies": 5, "won": True}
    # Y con la alineación de la primera mitad (yo CT) la misma ronda NO sería un clutch ganado.
    r13.players_at_start = dict(match.rounds[0].players_at_start)
    assert not [h for h in detect_clutches(ctx(match)) if h.round == 13 and h.extra.get("won")]


def test_overtime_rounds_are_decisive_and_use_their_own_side(match):  # type: ignore[no-untyped-def]
    """Prórroga (MR3 tras 12-12): rondas > 24 con cambio de bando a mitad de la prórroga."""
    from clutchreel.core.demo.detectors import _is_decisive_round, detect_all
    from clutchreel.core.demo.models import TEAM_CT, TEAM_T, RoundInfo
    from clutchreel.services.config import DetectionSettings, ScoringWeights
    from tests.conftest import ENEMIES, MATES, kill

    ct_side = {ME: TEAM_CT, **{m: TEAM_CT for m in MATES}, **{e: TEAM_T for e in ENEMIES}}
    t_side = {ME: TEAM_T, **{m: TEAM_T for m in MATES}, **{e: TEAM_CT for e in ENEMIES}}
    # 12-12 → prórroga: rondas 25-27 en un bando y 28 en el otro (el marcador sigue acumulando).
    r25 = RoundInfo(25, 200000, 201000, 207000, TEAM_CT, ct_score_after=13, t_score_after=12, players_at_start=ct_side)
    r28 = RoundInfo(28, 230000, 231000, 237000, TEAM_T, ct_score_after=14, t_score_after=14, players_at_start=t_side)
    match.rounds += [r25, r28]
    match.kills += [
        kill(202000, 25, ME, ENEMIES[0], headshot=True),
        kill(202300, 25, ME, ENEMIES[1], headshot=True),
        kill(202600, 25, ME, ENEMIES[2]),
        kill(232000, 28, ME, ENEMIES[0]),
        kill(232200, 28, ME, ENEMIES[1]),
    ]
    for k in match.kills:
        if k.round == 28:
            k.attacker_team = t_side.get(k.attacker_steamid, 0)
            k.victim_team = t_side.get(k.victim_steamid, 0)
    assert _is_decisive_round(match, r25) and _is_decisive_round(match, r28)
    found = detect_all(match, ME, DetectionSettings(), ScoringWeights())
    ot = {h.round: h for h in found if h.round >= 25}
    assert set(ot) == {25, 28}
    assert "3k" in (ot[25].merged_kinds or [ot[25].kind]) and "decisive" in (ot[25].merged_kinds or [ot[25].kind])
    # La ronda 28 la gana T, que en esa mitad de la prórroga es MI bando: cuenta como decisiva ganada.
    assert "decisive" in (ot[28].merged_kinds or [ot[28].kind])
    assert all(r25.start_tick <= h.start_tick and h.end_tick <= r28.end_tick + 64 * 5 for h in ot.values())


def test_five_kills_without_ace_enabled_are_labelled_5k_everywhere():  # type: ignore[no-untyped-def]
    """Con ACE desactivado, 5 kills seguidas quedaban con la etiqueta «4K» pero la descripción decía «5K»."""
    from clutchreel.core.demo.models import TEAM_CT, MatchData, PlayerInfo
    from clutchreel.core.export.exporter import thumbnail_title
    from tests.conftest import ENEMIES, MATES, kill, make_round

    rounds = [make_round(1, 0, TEAM_CT)]
    players = [PlayerInfo(ME, "yo", TEAM_CT, user_id=3)] + [PlayerInfo(m, f"mate{m % 10}", TEAM_CT) for m in MATES] + [PlayerInfo(e, f"enemy{e % 10}", 2) for e in ENEMIES]
    kills = [kill(1500 + i * 200, 1, ME, e) for i, e in enumerate(ENEMIES)]
    match = MatchData(demo_path="synthetic.dem", map_name="de_test", tickrate=TICKRATE, total_ticks=8000, players=players, kills=kills, rounds=rounds)
    kinds = [k for k in DetectionSettings().enabled_kinds if k != "ace"]
    found = detect_all(match, ME, DetectionSettings(enabled_kinds=kinds), ScoringWeights())
    hl = next(h for h in found if h.round == 1 and "4k" in (h.merged_kinds or [h.kind]))
    assert hl.kind == "4k"  # el tipo sigue siendo 4k (pesos y filtros no cambian)
    assert hl.label.startswith("5K") and "4K" not in hl.label
    assert hl.description.startswith("5K en la ronda 1")
    assert "5K" in hl.tags and thumbnail_title(hl) == "5K"
    restored = Highlight.from_dict(hl.to_dict())
    assert restored.label == hl.label
    # Con ACE activado sigue siendo un ACE.
    ace = next(h for h in detect_multikills(ctx(match)) if h.round == 1)
    assert ace.kind == "ace" and ace.label == "ACE"
