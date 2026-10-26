"""Vigilancia de la carpeta de demos (modo TODO AUTOMÁTICO)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path

log = logging.getLogger(__name__)

NewDemoFn = Callable[[Path], None]


class DemoWatcher:
    """Detecta demos nuevas y estables (terminadas de escribir) en varias carpetas."""

    def __init__(self, folders: list[Path], on_new_demo: NewDemoFn, settle_seconds: float = 8.0, poll_seconds: float = 3.0) -> None:
        self.folders = [f for f in folders if f]
        self.on_new_demo = on_new_demo
        self.settle_seconds = settle_seconds
        self.poll_seconds = poll_seconds
        self._known: dict[Path, int] = {}
        self._pending: dict[Path, tuple[int, float]] = {}
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._observer = None

    def start(self) -> None:
        self._stop.clear()
        for f in self.folders:
            try:
                for p in f.glob("*.dem"):
                    self._known[p] = p.stat().st_size
            except OSError:
                continue
        self._thread = threading.Thread(target=self._loop, name="demo-watcher", daemon=True)
        self._thread.start()
        log.info("Vigilando %d carpetas de demos", len(self.folders))

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=5)

    @property
    def running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def _loop(self) -> None:
        while not self._stop.is_set():
            now = time.time()
            for f in self.folders:
                try:
                    files = list(f.glob("*.dem"))
                except OSError:
                    continue
                for p in files:
                    try:
                        size = p.stat().st_size
                    except OSError:
                        continue
                    if p in self._known and self._known[p] == size:
                        continue
                    prev = self._pending.get(p)
                    if prev is None or prev[0] != size:
                        self._pending[p] = (size, now)
                        continue
                    if now - prev[1] >= self.settle_seconds and size > 1_000_000:
                        self._known[p] = size
                        self._pending.pop(p, None)
                        log.info("Demo nueva detectada: %s", p)
                        try:
                            self.on_new_demo(p)
                        except Exception as exc:
                            log.exception("Error procesando demo nueva: %s", exc)
            self._stop.wait(self.poll_seconds)
