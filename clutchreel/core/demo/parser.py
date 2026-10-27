"""Lectura de demos CS2 con demoparser2 → :class:`MatchData`.

La API de demoparser2 se verificó con una demo Premier real (octubre 2026):

* ``parse_header()`` → dict con ``map_name``, ``server_name``, ``client_name``…
* ``parse_event("player_death", player=[...], other=[...])`` → DataFrame con
  ``attacker_steamid``, ``user_steamid``, ``weapon``, ``headshot``, ``noscope``,
  ``thrusmoke``, ``penetrated``, ``attackerblind``, ``attackerinair``, ``distance``…
* ``parse_event("round_start"|"round_end"|"round_freeze_end")`` con ``round``/``tick``.
* ``parse_ticks([...], ticks=[...])`` con ``game_time``, ``is_alive``, ``team_num``, ``user_id``.
* ``parse_player_info()`` → ``steamid``, ``name``, ``team_number``.
"""

from __future__ import annotations

import datetime as dt
import logging
import math
import os
import re
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any

from clutchreel.core.demo.models import TEAM_CT, TEAM_T, KillEvent, MatchData, PlayerInfo, RoundInfo
from clutchreel.utils.timeutil import DEFAULT_TICKRATE

log = logging.getLogger(__name__)

ProgressFn = Callable[[int, str], None]


class DemoError(Exception):
    """Error entendible para el usuario al leer una demo."""


def _safe_int(value: Any, default: int = 0) -> int:
    try:
        if value is None:
            return default
        if isinstance(value, float) and math.isnan(value):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def _safe_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        out = float(value)
        return default if math.isnan(out) else out
    except (TypeError, ValueError):
        return default


def _safe_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes"}
    try:
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return False
        return bool(value)
    except (TypeError, ValueError):
        return False


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and math.isnan(value):
        return ""
    return str(value)


def _winner_to_team(value: Any) -> int:
    text = _safe_str(value).upper()
    if text in {"CT", "3"}:
        return TEAM_CT
    if text in {"T", "TERRORIST", "2"}:
        return TEAM_T
    return 0


def _demo_date_from_name(path: Path) -> str:
    try:
        mtime = dt.datetime.fromtimestamp(path.stat().st_mtime)
        return mtime.strftime("%d/%m/%Y %H:%M")
    except OSError:
        return ""


def quick_validate(path: Path) -> None:
    """Comprobaciones rápidas antes de parsear (existencia, tamaño, cabecera)."""
    if not path.exists():
        raise DemoError(f"No existe el archivo:\n{path}")
    if path.suffix.lower() != ".dem":
        raise DemoError("El archivo no es una demo (.dem).")
    size = path.stat().st_size
    if size < 1_000_000:
        raise DemoError("La demo es demasiado pequeña: parece vacía o incompleta.")
    try:
        with path.open("rb") as fh:
            head = fh.read(16)
    except OSError as exc:
        raise DemoError(f"No se pudo leer la demo: {exc}") from exc
    if not head.startswith(b"PBDEMS2"):
        if head.startswith(b"HL2DEMO"):
            raise DemoError("Es una demo de CS:GO (Source 1). ClutchReel solo admite demos de CS2.")
        raise DemoError("El archivo no tiene cabecera de demo de CS2 (puede estar corrupto).")


def parse_demo(path: str | os.PathLike[str], progress: ProgressFn | None = None, cancel: threading.Event | None = None) -> MatchData:
    """Analiza la demo completa. Lanza :class:`DemoError` con mensajes claros.

    ``cancel`` se comprueba entre etapas (demoparser2 no se puede interrumpir a mitad de una lectura).
    """
    demo_path = Path(path)
    quick_validate(demo_path)

    def report(pct: int, msg: str) -> None:
        if cancel is not None and cancel.is_set():
            raise DemoError("Análisis cancelado.")
        if progress:
            progress(pct, msg)

    report(2, "Abriendo demo…")
    try:
        from demoparser2 import DemoParser  # import tardío: carga nativa lenta
    except ImportError as exc:  # pragma: no cover
        raise DemoError("Falta la librería demoparser2. Ejecuta Iniciar.bat para instalar dependencias.") from exc

    try:
        parser = DemoParser(str(demo_path))
        header = parser.parse_header() or {}
    except Exception as exc:
        raise DemoError(f"La demo no se pudo abrir (¿corrupta o incompleta?):\n{exc}") from exc

    map_name = _safe_str(header.get("map_name")) or "desconocido"
    server_name = _safe_str(header.get("server_name"))
    report(8, f"Mapa {map_name}. Leyendo jugadores…")

    # Jugadores -------------------------------------------------------------
    players: dict[int, PlayerInfo] = {}
    try:
        info_df = parser.parse_player_info()
        for row in info_df.to_dict("records"):
            sid = _safe_int(row.get("steamid"))
            if sid <= 0:
                continue
            players[sid] = PlayerInfo(steamid64=sid, name=_safe_str(row.get("name")), team_num=_safe_int(row.get("team_number")))
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_player_info falló: %s", exc)

    # Rondas ---------------------------------------------------------------
    report(15, "Leyendo rondas…")
    try:
        starts = parser.parse_event("round_start").to_dict("records")
        ends = parser.parse_event(
            "round_end", other=["team_rounds_total", "total_rounds_played"]
        ).to_dict("records")
    except Exception as exc:
        raise DemoError(f"La demo no contiene información de rondas legible:\n{exc}") from exc
    try:
        freeze_ends = [_safe_int(r.get("tick")) for r in parser.parse_event("round_freeze_end").to_dict("records")]
    except Exception:  # noqa: BLE001
        freeze_ends = []

    if not ends:
        raise DemoError("La demo no tiene rondas terminadas: puede estar incompleta o ser de otro modo de juego.")

    rounds: list[RoundInfo] = []
    start_by_round: dict[int, int] = {}
    for row in starts:
        rn = _safe_int(row.get("round"))
        tick = _safe_int(row.get("tick"))
        # Los reinicios de warmup repiten "round 1": nos quedamos con el último inicio.
        start_by_round[rn] = tick
    for row in ends:
        rn = _safe_int(row.get("round"))
        end_tick = _safe_int(row.get("tick"))
        start_tick = start_by_round.get(rn, 0)
        if start_tick >= end_tick and rounds:
            start_tick = rounds[-1].end_tick
        freeze_end = next((t for t in freeze_ends if start_tick <= t <= end_tick), start_tick)
        rounds.append(
            RoundInfo(
                number=rn,
                start_tick=start_tick,
                freeze_end_tick=freeze_end,
                end_tick=end_tick,
                winner_team=_winner_to_team(row.get("winner")),
                reason=_safe_str(row.get("reason")),
                ct_score_after=_safe_int(row.get("ct_team_rounds_total")),
                t_score_after=_safe_int(row.get("t_team_rounds_total")),
            )
        )
    # Elimina duplicados por número de ronda (quedándose con el último).
    dedup: dict[int, RoundInfo] = {}
    for r in rounds:
        dedup[r.number] = r
    rounds = sorted(dedup.values(), key=lambda r: r.number)

    # Tickrate real --------------------------------------------------------
    report(30, "Calculando tickrate…")
    tickrate = _estimate_tickrate(parser, rounds)

    # Kills ---------------------------------------------------------------
    report(40, "Leyendo bajas…")
    try:
        deaths_df = parser.parse_event(
            "player_death",
            player=["team_num"],
            other=["total_rounds_played", "is_warmup_period"],
        )
    except Exception as exc:
        raise DemoError(f"No se pudieron leer las bajas de la demo:\n{exc}") from exc

    kills: list[KillEvent] = []
    for row in deaths_df.to_dict("records"):
        if _safe_bool(row.get("is_warmup_period")):
            continue
        tick = _safe_int(row.get("tick"))
        round_number = _round_for_tick(rounds, tick, tickrate)
        if round_number == 0:
            continue
        attacker = _safe_int(row.get("attacker_steamid"))
        victim = _safe_int(row.get("user_steamid"))
        kill = KillEvent(
            tick=tick,
            round=round_number,
            attacker_steamid=attacker,
            attacker_name=_safe_str(row.get("attacker_name")),
            victim_steamid=victim,
            victim_name=_safe_str(row.get("user_name")),
            weapon=_safe_str(row.get("weapon")),
            headshot=_safe_bool(row.get("headshot")),
            noscope=_safe_bool(row.get("noscope")),
            thrusmoke=_safe_bool(row.get("thrusmoke")),
            penetrated=_safe_int(row.get("penetrated")),
            attackerblind=_safe_bool(row.get("attackerblind")),
            attackerinair=_safe_bool(row.get("attackerinair")),
            distance=_safe_float(row.get("distance")),
            assister_steamid=_safe_int(row.get("assister_steamid")),
            attacker_team=_safe_int(row.get("attacker_team_num")),
            victim_team=_safe_int(row.get("user_team_num")),
        )
        kills.append(kill)
        if attacker in players and not kill.is_teamkill and not kill.is_suicide:
            players[attacker].kills += 1
            if kill.headshot:
                players[attacker].headshots += 1
        if victim in players:
            players[victim].deaths += 1
        if kill.assister_steamid in players:
            players[kill.assister_steamid].assists += 1
        for sid, name in ((attacker, kill.attacker_name), (victim, kill.victim_name)):
            if sid > 0 and sid not in players:
                players[sid] = PlayerInfo(steamid64=sid, name=name)
    kills.sort(key=lambda k: k.tick)

    # Equipos por ronda + user_id ---------------------------------------------
    report(65, "Leyendo alineaciones por ronda…")
    _fill_round_lineups(parser, rounds, players)

    # Daño (ADR) ---------------------------------------------------------------
    report(80, "Calculando daño…")
    try:
        hurt = parser.parse_event("player_hurt", player=["team_num"])
        if len(hurt):
            for row in hurt.to_dict("records"):
                att = _safe_int(row.get("attacker_steamid"))
                victim = _safe_int(row.get("user_steamid"))
                same_team = _safe_int(row.get("attacker_team_num")) == _safe_int(row.get("user_team_num"))
                if att in players and att != victim and not same_team:
                    # dmg_health puede superar la vida restante; se limita a 100 por impacto.
                    players[att].damage += min(100, _safe_int(row.get("dmg_health")))
    except Exception as exc:  # noqa: BLE001
        log.debug("player_hurt no disponible: %s", exc)

    total_ticks = max([r.end_tick for r in rounds] + [k.tick for k in kills] + [0])
    try:
        win_panel = parser.parse_event("cs_win_panel_match")
        if len(win_panel):
            total_ticks = max(total_ticks, _safe_int(win_panel.iloc[-1]["tick"]))
    except Exception:  # noqa: BLE001
        pass

    last = rounds[-1]
    match = MatchData(
        demo_path=str(demo_path),
        map_name=map_name,
        tickrate=tickrate,
        total_ticks=total_ticks,
        server_name=server_name,
        demo_date=_demo_date_from_name(demo_path),
        players=sorted(players.values(), key=lambda p: (-p.kills, p.name.lower())),
        kills=kills,
        rounds=rounds,
        final_score_ct=last.ct_score_after,
        final_score_t=last.t_score_after,
        game_mode=_guess_game_mode(rounds, len(players), server_name),
    )
    if len(players) < 2:
        match.warnings.append("Se han detectado muy pocos jugadores; puede no ser una partida normal.")
    if len(rounds) < 3:
        match.warnings.append("La demo tiene muy pocas rondas; puede estar incompleta.")
    if not kills:
        match.warnings.append("No hay bajas en la demo.")
    report(100, "Análisis completado")
    log.info(
        "Demo %s: mapa=%s rondas=%d kills=%d jugadores=%d tickrate=%.2f",
        demo_path.name,
        map_name,
        len(rounds),
        len(kills),
        len(players),
        tickrate,
    )
    return match


def _round_for_tick(rounds: list[RoundInfo], tick: int, tickrate: float = DEFAULT_TICKRATE) -> int:
    for r in rounds:
        if r.start_tick <= tick <= r.end_tick:
            return r.number
    # Bajas justo tras round_end (antes de round_start siguiente) cuentan en esa ronda.
    for r in rounds:
        if r.end_tick < tick and tick <= r.end_tick + round(7 * tickrate):  # 7 s, también en demos de 128 ticks
            return r.number
    return 0


def _estimate_tickrate(parser: Any, rounds: list[RoundInfo]) -> float:
    """Tickrate real a partir de ``game_time`` en dos ticks distantes."""
    try:
        t1 = max(1, rounds[0].start_tick + 10)
        t2 = max(t1 + 1000, rounds[-1].end_tick - 10)
        df = parser.parse_ticks(["game_time"], ticks=[t1, t2])
        if len(df):
            df = df.drop_duplicates("tick")
            times = {int(r["tick"]): float(r["game_time"]) for r in df.to_dict("records")}
            if t1 in times and t2 in times and times[t2] > times[t1]:
                rate = (t2 - t1) / (times[t2] - times[t1])
                for known in (64.0, 128.0, 32.0):
                    if abs(rate - known) < 2.0:
                        return known
                if 10 < rate < 300:
                    return round(rate, 2)
    except Exception as exc:  # noqa: BLE001
        log.debug("No se pudo estimar el tickrate: %s", exc)
    return DEFAULT_TICKRATE


def _fill_round_lineups(parser: Any, rounds: list[RoundInfo], players: dict[int, PlayerInfo]) -> None:
    ticks = [max(r.freeze_end_tick, r.start_tick) + 2 for r in rounds]
    try:
        df = parser.parse_ticks(["team_num", "is_alive", "user_id"], ticks=ticks)
    except Exception as exc:  # noqa: BLE001
        log.warning("parse_ticks de alineaciones falló: %s", exc)
        for r in rounds:
            r.players_at_start = {p.steamid64: p.team_num for p in players.values() if p.team_num in (TEAM_T, TEAM_CT)}
        return
    by_tick: dict[int, list[dict[str, Any]]] = {}
    for row in df.to_dict("records"):
        by_tick.setdefault(_safe_int(row.get("tick")), []).append(row)
    for r, tick in zip(rounds, ticks, strict=True):
        lineup: dict[int, int] = {}
        for row in by_tick.get(tick, []):
            sid = _safe_int(row.get("steamid"))
            team = _safe_int(row.get("team_num"))
            if sid > 0 and team in (TEAM_T, TEAM_CT):
                lineup[sid] = team
                if sid in players:
                    uid = _safe_int(row.get("user_id"), -1)
                    if uid >= 0:
                        players[sid].user_id = uid
                    players[sid].team_num = team
        if not lineup:
            lineup = {p.steamid64: p.team_num for p in players.values() if p.team_num in (TEAM_T, TEAM_CT)}
        r.players_at_start = lineup


def _guess_game_mode(rounds: list[RoundInfo], n_players: int, server_name: str) -> str:
    if re.search(r"valve", server_name, re.I):
        if n_players == 10 and len(rounds) >= 8:
            return "Premier / Competitivo"
        if n_players <= 4:
            return "Wingman"
    if n_players == 10:
        return "Competitivo"
    return "Desconocido"
