"""Detectores de jugadas con puntuación configurable.

Entrada: :class:`MatchData` + SteamID del jugador + ajustes. Salida: lista de
:class:`Highlight` ya fusionadas (sin solapes) y ordenadas por tick.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from dataclasses import dataclass

from clutchreel.core.demo.models import TEAM_CT, TEAM_T, Highlight, KillEvent, MatchData, RoundInfo
from clutchreel.services.config import DetectionSettings, ScoringWeights
from clutchreel.utils.timeutil import seconds_to_ticks

log = logging.getLogger(__name__)


@dataclass
class DetectionContext:
    match: MatchData
    steamid64: int
    settings: DetectionSettings
    weights: ScoringWeights

    @property
    def tickrate(self) -> float:
        return self.match.tickrate

    def player_kills(self) -> list[KillEvent]:
        return [
            k
            for k in self.match.kills
            if k.attacker_steamid == self.steamid64 and not k.is_teamkill and not k.is_suicide
        ]

    def kills_by_round(self) -> dict[int, list[KillEvent]]:
        out: dict[int, list[KillEvent]] = defaultdict(list)
        for k in self.player_kills():
            out[k.round].append(k)
        for lst in out.values():
            lst.sort(key=lambda k: k.tick)
        return out


# ------------------------------------------------------------- scoring ------


def kill_base_score(kill: KillEvent, w: ScoringWeights) -> float:
    score = w.kill
    if kill.headshot:
        score += w.headshot
    if kill.is_awp:
        score += w.awp
    if kill.noscope:
        score += w.noscope
    if kill.penetrated > 0:
        score += w.wallbang
    if kill.thrusmoke:
        score += w.smoke
    if kill.attackerblind:
        score += w.blind
    if kill.attackerinair:
        score += w.air
    if kill.is_knife:
        score += w.knife
    if kill.is_pistol:
        score += w.pistol
    if kill.distance > 0:
        score += min(kill.distance, 60.0) / 100.0 * 100.0 * (w.distance_per_100u / 100.0)
    return score


def kill_tags(kill: KillEvent) -> list[str]:
    tags: list[str] = []
    if kill.headshot:
        tags.append("HS")
    if kill.is_awp:
        tags.append("AWP")
    if kill.noscope:
        tags.append("no-scope")
    if kill.penetrated > 0:
        tags.append("wallbang")
    if kill.thrusmoke:
        tags.append("humo")
    if kill.attackerblind:
        tags.append("cegado")
    if kill.attackerinair:
        tags.append("aire")
    if kill.is_knife:
        tags.append("cuchillo")
    return tags


def weapon_label(weapon: str) -> str:
    w = weapon.lower().replace("weapon_", "")
    names = {
        "ak47": "AK-47",
        "m4a1": "M4A4",
        "m4a1_silencer": "M4A1-S",
        "awp": "AWP",
        "usp_silencer": "USP-S",
        "hkp2000": "P2000",
        "glock": "Glock",
        "deagle": "Desert Eagle",
        "ssg08": "Scout",
        "galilar": "Galil",
        "famas": "FAMAS",
        "aug": "AUG",
        "sg556": "SG 553",
        "mac10": "MAC-10",
        "mp9": "MP9",
        "ump45": "UMP-45",
        "p90": "P90",
        "fiveseven": "Five-SeveN",
        "tec9": "Tec-9",
        "cz75a": "CZ75",
        "p250": "P250",
        "elite": "Dual Berettas",
        "revolver": "R8",
        "hegrenade": "HE",
        "inferno": "Molotov",
        "taser": "Zeus",
        "nova": "Nova",
        "xm1014": "XM1014",
        "mag7": "MAG-7",
        "sawedoff": "Sawed-Off",
        "m249": "M249",
        "negev": "Negev",
        "bizon": "PP-Bizon",
        "mp7": "MP7",
        "mp5sd": "MP5-SD",
        "scar20": "SCAR-20",
        "g3sg1": "G3SG1",
    }
    if "knife" in w or "bayonet" in w or "karambit" in w:
        return "cuchillo"
    return names.get(w, w.upper())


# ------------------------------------------------------------ detectors -----


def _mk_highlight(ctx: DetectionContext, kind: str, kills: list[KillEvent], score: float, desc: str, tags: list[str] | None = None) -> Highlight:
    first = kills[0].tick
    last = kills[-1].tick
    pre = seconds_to_ticks(ctx.settings.pre_roll, ctx.tickrate)
    post = seconds_to_ticks(ctx.settings.post_roll, ctx.tickrate)
    rnd = ctx.match.round_by_number(kills[0].round)
    start = max(0, first - pre)
    end = last + post
    if rnd:
        start = max(start, rnd.start_tick)
        end = min(end, rnd.end_tick + seconds_to_ticks(5, ctx.tickrate))
    return Highlight(
        kind=kind,
        round=kills[0].round,
        start_tick=start,
        end_tick=max(end, start + seconds_to_ticks(1.0, ctx.tickrate)),
        score=round(score, 1),
        description=desc,
        kills=list(kills),
        key_tick=last,
        tags=tags or [],
    )


def detect_multikills(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    window = seconds_to_ticks(ctx.settings.multikill_window, ctx.tickrate)
    w = ctx.weights
    for rnd, kills in ctx.kills_by_round().items():
        # Un ACE es 5 kills en la ronda, sin importar la ventana.
        if len(kills) >= 5 and "ace" in ctx.settings.enabled_kinds:
            score = w.ace + sum(kill_base_score(k, w) for k in kills)
            out.append(_mk_highlight(ctx, "ace", kills, score, f"ACE en la ronda {rnd}", ["ACE"]))
            continue
        groups: list[list[KillEvent]] = []
        current: list[KillEvent] = []
        for k in kills:
            if current and k.tick - current[-1].tick > window:
                groups.append(current)
                current = []
            current.append(k)
        if current:
            groups.append(current)
        for g in groups:
            n = len(g)
            if n < max(2, ctx.settings.min_multikill):
                continue
            kind = {2: "2k", 3: "3k", 4: "4k"}.get(min(n, 4), "4k")
            if kind not in ctx.settings.enabled_kinds:
                continue
            bonus = {2: w.multikill_2k, 3: w.multikill_3k, 4: w.multikill_4k}[min(n, 4)]
            score = bonus + sum(kill_base_score(k, w) for k in g)
            hs = sum(1 for k in g if k.headshot)
            desc = f"{n}K en la ronda {rnd} con {weapon_label(g[-1].weapon)}"
            if hs:
                desc += f" ({hs} HS)"
            out.append(_mk_highlight(ctx, kind, g, score, desc, [f"{n}K"]))
    return out


def _alive_timeline(ctx: DetectionContext, rnd: RoundInfo) -> list[tuple[int, dict[int, int]]]:
    """Devuelve [(tick, {steamid: team}) de vivos] tras cada muerte de la ronda."""
    alive: dict[int, int] = dict(rnd.players_at_start)
    timeline: list[tuple[int, dict[int, int]]] = [(rnd.start_tick, dict(alive))]
    for k in ctx.match.kills:
        if k.round != rnd.number:
            continue
        alive.pop(k.victim_steamid, None)
        timeline.append((k.tick, dict(alive)))
    return timeline


def detect_clutches(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    if "clutch" not in ctx.settings.enabled_kinds:
        return out
    w = ctx.weights
    for rnd in ctx.match.rounds:
        my_team = rnd.players_at_start.get(ctx.steamid64, 0)
        if my_team not in (TEAM_T, TEAM_CT):
            continue
        enemy_team = TEAM_CT if my_team == TEAM_T else TEAM_T
        timeline = _alive_timeline(ctx, rnd)
        clutch_start_tick = 0
        enemies_at_start = 0
        for tick, alive in timeline:
            mine = [s for s, t in alive.items() if t == my_team]
            enemies = [s for s, t in alive.items() if t == enemy_team]
            if ctx.steamid64 in mine and len(mine) == 1 and len(enemies) >= ctx.settings.clutch_min_enemies:
                clutch_start_tick = tick
                enemies_at_start = len(enemies)
                break
        if not clutch_start_tick:
            continue
        kills_after = [
            k
            for k in ctx.match.kills
            if k.round == rnd.number and k.tick >= clutch_start_tick and k.attacker_steamid == ctx.steamid64 and not k.is_teamkill
        ]
        won = rnd.winner_team == my_team
        if not kills_after:
            continue
        if not won and not ctx.settings.include_lost_clutches:
            continue
        if not won and len(kills_after) < max(1, enemies_at_start - 1):
            continue
        score = w.clutch_base + w.clutch_per_enemy * enemies_at_start + sum(kill_base_score(k, w) for k in kills_after)
        if won:
            score += w.clutch_won_bonus
        else:
            score *= 0.6
        desc = f"Clutch 1v{enemies_at_start} {'ganado' if won else 'casi'} en la ronda {rnd.number} ({len(kills_after)} kills)"
        hl = _mk_highlight(ctx, "clutch", kills_after, score, desc, [f"1v{enemies_at_start}", "ganado" if won else "perdido"])
        hl.start_tick = max(rnd.start_tick, min(hl.start_tick, clutch_start_tick - seconds_to_ticks(1.0, ctx.tickrate)))
        if won:
            hl.end_tick = min(max(hl.end_tick, rnd.end_tick + seconds_to_ticks(1.5, ctx.tickrate)), rnd.end_tick + seconds_to_ticks(4, ctx.tickrate))
        hl.extra = {"enemies": enemies_at_start, "won": won}
        out.append(hl)
    return out


def detect_headshot_streaks(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    if "headshot_streak" not in ctx.settings.enabled_kinds:
        return out
    need = max(2, ctx.settings.headshot_streak_min)
    w = ctx.weights
    for rnd, kills in ctx.kills_by_round().items():
        streak: list[KillEvent] = []
        for k in [*kills, None]:  # type: ignore[list-item]
            if k is not None and k.headshot:
                streak.append(k)
                continue
            if len(streak) >= need:
                score = w.headshot_streak * len(streak) + sum(kill_base_score(s, w) for s in streak)
                out.append(_mk_highlight(ctx, "headshot_streak", streak, score, f"{len(streak)} headshots seguidos en la ronda {rnd}", [f"HS x{len(streak)}"]))
            streak = []
    return out


def detect_entries(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    if "entry" not in ctx.settings.enabled_kinds:
        return out
    w = ctx.weights
    for rnd in ctx.match.rounds:
        round_kills = [k for k in ctx.match.kills if k.round == rnd.number and not k.is_teamkill and not k.is_suicide]
        if not round_kills:
            continue
        first = round_kills[0]
        if first.attacker_steamid == ctx.steamid64:
            score = w.entry + kill_base_score(first, w)
            out.append(_mk_highlight(ctx, "entry", [first], score, f"Primera baja de la ronda {rnd.number} ({weapon_label(first.weapon)})", kill_tags(first)))
    return out


_SPECIAL_KINDS = {
    "awp": lambda k: k.is_awp,
    "noscope": lambda k: k.noscope,
    "wallbang": lambda k: k.penetrated > 0,
    "smoke": lambda k: k.thrusmoke,
    "blind": lambda k: k.attackerblind,
    "air": lambda k: k.attackerinair,
    "knife": lambda k: k.is_knife,
}


def detect_special_kills(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    w = ctx.weights
    for k in ctx.player_kills():
        for kind, pred in _SPECIAL_KINDS.items():
            if kind in ctx.settings.enabled_kinds and pred(k):
                score = kill_base_score(k, w)
                if kind == "awp":
                    score *= 1.0
                label = {
                    "awp": "Kill con AWP",
                    "noscope": "No-scope",
                    "wallbang": "Wallbang",
                    "smoke": "Kill a través del humo",
                    "blind": "Kill cegado",
                    "air": "Kill en el aire",
                    "knife": "Kill con cuchillo",
                }[kind]
                out.append(_mk_highlight(ctx, kind, [k], score, f"{label} a {k.victim_name} en la ronda {k.round}", kill_tags(k)))
    return out


def detect_all_kills(ctx: DetectionContext) -> list[Highlight]:
    if "all_kills" not in ctx.settings.enabled_kinds:
        return []
    w = ctx.weights
    return [
        _mk_highlight(ctx, "kill", [k], kill_base_score(k, w), f"Kill a {k.victim_name} con {weapon_label(k.weapon)} (ronda {k.round})", kill_tags(k))
        for k in ctx.player_kills()
    ]


def _is_decisive_round(match: MatchData, rnd: RoundInfo) -> bool:
    before_ct = rnd.ct_score_after - (1 if rnd.winner_team == TEAM_CT else 0)
    before_t = rnd.t_score_after - (1 if rnd.winner_team == TEAM_T else 0)
    last = match.rounds[-1] if match.rounds else None
    if last and rnd.number == last.number:
        return True
    # Punto de partida (12) o empate avanzado / prórroga.
    return max(before_ct, before_t) >= 12 or (before_ct == before_t and before_ct >= 10)


def detect_decisive_rounds(ctx: DetectionContext) -> list[Highlight]:
    out: list[Highlight] = []
    if "decisive" not in ctx.settings.enabled_kinds:
        return out
    w = ctx.weights
    by_round = ctx.kills_by_round()
    for rnd in ctx.match.rounds:
        kills = by_round.get(rnd.number, [])
        if not kills or not _is_decisive_round(ctx.match, rnd):
            continue
        my_team = rnd.players_at_start.get(ctx.steamid64, 0)
        won = rnd.winner_team == my_team
        if not won:
            continue
        score = w.decisive_round + sum(kill_base_score(k, w) for k in kills)
        out.append(_mk_highlight(ctx, "decisive", kills, score, f"Ronda decisiva {rnd.number} ({len(kills)} kills)", ["decisiva"]))
    return out


def detect_best_round(ctx: DetectionContext) -> list[Highlight]:
    if "best_round" not in ctx.settings.enabled_kinds:
        return []
    w = ctx.weights
    best: tuple[float, list[KillEvent]] | None = None
    for kills in ctx.kills_by_round().values():
        total = sum(kill_base_score(k, w) for k in kills) + len(kills) * 5
        if best is None or total > best[0]:
            best = (total, kills)
    if not best or not best[1]:
        return []
    kills = best[1]
    hl = _mk_highlight(ctx, "best_round", kills, best[0] * 0.5, f"Mejor ronda: ronda {kills[0].round} con {len(kills)} kills", ["mejor ronda"])
    return [hl]


# -------------------------------------------------------------- merging -----


def merge_highlights(highlights: list[Highlight], merge_gap_ticks: int) -> list[Highlight]:
    """Fusiona jugadas solapadas o cercanas (misma ronda) en un único clip."""
    if not highlights:
        return []
    ordered = sorted(highlights, key=lambda h: (h.start_tick, -h.score))
    merged: list[Highlight] = []
    for h in ordered:
        if merged and h.round == merged[-1].round and h.start_tick <= merged[-1].end_tick + merge_gap_ticks:
            base = merged[-1]
            base.start_tick = min(base.start_tick, h.start_tick)
            base.end_tick = max(base.end_tick, h.end_tick)
            kinds = base.merged_kinds or [base.kind]
            if h.kind not in kinds:
                kinds.append(h.kind)
            base.merged_kinds = kinds
            # Puntuación: la mayor + 35 % de la otra (evita inflar por solapes).
            hi, lo = max(base.score, h.score), min(base.score, h.score)
            base.score = round(hi + lo * 0.35, 1)
            seen = {k.tick for k in base.kills}
            for k in h.kills:
                if k.tick not in seen:
                    base.kills.append(k)
                    seen.add(k.tick)
            base.kills.sort(key=lambda k: k.tick)
            base.key_tick = max(base.key_tick, h.key_tick)
            if h.score > base.score * 0.8 and h.kind not in ("kill",):
                base.description = f"{base.description} · {h.description}"
            for t in h.tags:
                if t not in base.tags:
                    base.tags.append(t)
        else:
            merged.append(
                Highlight(
                    kind=h.kind,
                    round=h.round,
                    start_tick=h.start_tick,
                    end_tick=h.end_tick,
                    score=h.score,
                    description=h.description,
                    kills=list(h.kills),
                    key_tick=h.key_tick,
                    tags=list(h.tags),
                    merged_kinds=list(h.merged_kinds),
                    extra=dict(h.extra),
                )
            )
    return merged


DEATH_PAD_SECONDS = 0.8


def clamp_to_death(ctx: DetectionContext, hl: Highlight) -> None:
    """Termina la jugada 0,8 s después de que muera el jugador.

    En el visor de demos, al morir el jugador seguido se ve 0,8 s su animación de
    muerte, después la cámara viaja hasta el asesino y a los ~3 s pasa a seguirlo
    (medido en CS2 1.41.9), así que más allá no se le puede seguir.
    """
    death = next(
        (k.tick for k in ctx.match.kills if k.victim_steamid == ctx.steamid64 and k.round == hl.round and hl.start_tick <= k.tick < hl.end_tick),
        None,
    )
    if death is None:
        return
    end = death + seconds_to_ticks(DEATH_PAD_SECONDS, ctx.tickrate)
    if end < hl.end_tick:
        hl.end_tick = max(end, hl.start_tick + seconds_to_ticks(1.0, ctx.tickrate))


def detect_all(match: MatchData, steamid64: int, settings: DetectionSettings, weights: ScoringWeights) -> list[Highlight]:
    ctx = DetectionContext(match=match, steamid64=steamid64, settings=settings, weights=weights)
    found: list[Highlight] = []
    for detector in (
        detect_multikills,
        detect_clutches,
        detect_headshot_streaks,
        detect_entries,
        detect_special_kills,
        detect_decisive_rounds,
        detect_best_round,
        detect_all_kills,
    ):
        try:
            found.extend(detector(ctx))
        except Exception as exc:
            log.exception("Detector %s falló: %s", detector.__name__, exc)
    for h in found:
        clamp_to_death(ctx, h)
    merged = merge_highlights(found, seconds_to_ticks(settings.merge_gap, match.tickrate))
    merged.sort(key=lambda h: h.start_tick)
    log.info("Detectadas %d jugadas (%d antes de fusionar) para %s", len(merged), len(found), steamid64)
    return merged
