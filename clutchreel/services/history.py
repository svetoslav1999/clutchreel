"""Historial de demos procesadas (evita reprocesar duplicados)."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from clutchreel.utils.paths import appdata_dir

log = logging.getLogger(__name__)


@dataclass
class HistoryEntry:
    demo_path: str
    fingerprint: str
    map_name: str
    player_name: str
    score: str
    processed_at: float
    project_path: str = ""
    output_video: str = ""
    stats: dict[str, Any] = field(default_factory=dict)


_FP_CACHE: dict[tuple[str, int, int], str] = {}


def demo_fingerprint(path: Path) -> str:
    """Hash rápido: tamaño + primeros/últimos 64 KB (no lee 200 MB enteros).

    Se memoriza por (ruta, tamaño, fecha de modificación): Inicio lo pide para cada demo de la lista
    en cada refresco y antes releía 128 KB de cada una.
    """
    try:
        st = path.stat()
    except OSError:
        return ""
    key = (str(path), st.st_size, st.st_mtime_ns)
    cached = _FP_CACHE.get(key)
    if cached is not None:
        return cached
    fp = _fingerprint(path)
    if fp:
        if len(_FP_CACHE) > 2000:
            _FP_CACHE.clear()
        _FP_CACHE[key] = fp
    return fp


def _fingerprint(path: Path) -> str:
    try:
        size = path.stat().st_size
        h = hashlib.sha1(str(size).encode())  # noqa: S324 - no criptográfico
        with path.open("rb") as fh:
            h.update(fh.read(65536))
            if size > 131072:
                fh.seek(-65536, 2)
                h.update(fh.read(65536))
        return h.hexdigest()
    except OSError:
        return ""


def _entry_from_dict(data: Any) -> HistoryEntry | None:
    if not isinstance(data, dict):
        return None
    try:
        return HistoryEntry(**{k: v for k, v in data.items() if k in HistoryEntry.__dataclass_fields__})
    except TypeError:  # faltan campos obligatorios
        return None


class History:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (appdata_dir() / "history.json")
        self.entries: list[HistoryEntry] = []
        self.load()

    def load(self) -> None:
        if not self.path.exists():
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                raise ValueError("no es una lista")
            # Las entradas dañadas se ignoran una a una (antes, una sola impedía abrir la app).
            self.entries = [entry for entry in (_entry_from_dict(e) for e in raw) if entry is not None]
        except (OSError, ValueError, TypeError) as exc:
            log.warning("Historial ilegible: %s", exc)
            self.entries = []

    def save(self) -> None:
        """Escritura atómica: un corte a mitad no deja el historial vacío ni dañado."""
        tmp = self.path.with_name(self.path.name + ".tmp")
        try:
            tmp.write_text(json.dumps([asdict(e) for e in self.entries], ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, self.path)
        except OSError as exc:
            log.warning("No se pudo guardar el historial: %s", exc)

    def find(self, path: Path) -> HistoryEntry | None:
        fp = demo_fingerprint(path)
        for e in self.entries:
            if (fp and e.fingerprint == fp) or e.demo_path == str(path):
                return e
        return None

    def add(self, entry: HistoryEntry) -> None:
        self.entries = [e for e in self.entries if e.fingerprint != entry.fingerprint]
        self.entries.insert(0, entry)
        del self.entries[200:]
        self.save()

    def update_output(self, demo_path: str, output_video: str) -> None:
        for e in self.entries:
            if e.demo_path == demo_path:
                e.output_video = output_video
                e.processed_at = time.time()
        self.save()
