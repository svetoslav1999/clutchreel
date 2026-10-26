"""Título, descripción y etiquetas sugeridas para YouTube."""

from __future__ import annotations

from dataclasses import dataclass, field

from clutchreel.core.demo.models import Highlight, MatchData

MAP_NAMES = {
    "de_mirage": "Mirage",
    "de_dust2": "Dust II",
    "de_inferno": "Inferno",
    "de_nuke": "Nuke",
    "de_ancient": "Ancient",
    "de_anubis": "Anubis",
    "de_vertigo": "Vertigo",
    "de_overpass": "Overpass",
    "de_train": "Train",
    "de_cache": "Cache",
}


def pretty_map(map_name: str) -> str:
    return MAP_NAMES.get(map_name.lower(), map_name.replace("de_", "").capitalize())


@dataclass
class VideoMetadata:
    title: str
    description: str
    tags: list[str] = field(default_factory=list)


def suggest_metadata(match: MatchData, player_name: str, highlights: list[Highlight], channel: str = "", base_tags: list[str] | None = None) -> VideoMetadata:
    map_label = pretty_map(match.map_name)
    kills = sum(len(h.kills) for h in highlights)
    aces = sum(1 for h in highlights if "ace" in (h.merged_kinds or [h.kind]))
    clutches = sum(1 for h in highlights if "clutch" in (h.merged_kinds or [h.kind]))
    headline = f"{player_name} en {map_label}"
    if aces:
        headline = f"ACE en {map_label}"
    elif clutches:
        headline = f"Clutch en {map_label}"
    title = f"{headline} | CS2 Premier Highlights ({kills} kills)"
    if len(title) > 95:
        title = title[:92] + "…"
    lines = [
        f"Mejores jugadas de {player_name} en {map_label} (Counter-Strike 2, Premier).",
        f"Resultado: {match.score_label()} · {len(match.rounds)} rondas · {match.demo_date}",
        "",
        "Jugadas:",
    ]
    for h in highlights:
        lines.append(f"• Ronda {h.round}: {h.description}")
    lines += ["", "Vídeo creado automáticamente con ClutchReel."]
    if channel:
        lines.append(f"Canal: {channel}")
    tags = list(base_tags or [])
    tags += [map_label, "CS2 highlights", "CS2 clips", player_name]
    if aces:
        tags.append("ACE")
    if clutches:
        tags.append("clutch")
    seen: set[str] = set()
    uniq = []
    for t in tags:
        key = t.lower().strip()
        if key and key not in seen:
            seen.add(key)
            uniq.append(t.strip())
    return VideoMetadata(title=title, description="\n".join(lines), tags=uniq[:30])
