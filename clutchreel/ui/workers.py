"""Hilos de trabajo para que la interfaz nunca se congele."""

from __future__ import annotations

import logging
import threading
import time
import traceback
from collections.abc import Callable
from typing import Any

from PySide6.QtCore import QObject, QThread, Signal

log = logging.getLogger(__name__)


class Worker(QThread):
    """Ejecuta ``fn(progress, cancel_event)`` en segundo plano.

    ``fn`` recibe un callback ``progress(fraction_or_percent, message)`` y un
    ``threading.Event`` de cancelación. Emite ``finished_ok(result)`` o
    ``failed(message, traceback)``.
    """

    progress = Signal(int, str)
    finished_ok = Signal(object)
    failed = Signal(str, str)

    def __init__(self, fn: Callable[..., Any], *args: Any, name: str = "worker", **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.cancel_event = threading.Event()
        self.setObjectName(name)
        self._last_progress: tuple[int, str] = (-1, "")
        self._last_emit = 0.0

    # Avisos de progreso: cada uno cruza al hilo de la interfaz y la repinta. Algunos trabajos avisan
    # decenas de veces por segundo; basta con los cambios de texto y, como mucho, 10 avisos por segundo.
    MIN_PROGRESS_INTERVAL = 0.1

    def _progress(self, value: float, message: str = "") -> None:
        pct = max(0, min(100, round(value * 100) if 0.0 <= value <= 1.0 else int(value)))
        message = message or ""
        now = time.monotonic()
        last_pct, last_msg = self._last_progress
        if message == last_msg or not message:
            if pct == last_pct or now - self._last_emit < self.MIN_PROGRESS_INTERVAL:
                return
        self._last_progress = (pct, message or last_msg)
        self._last_emit = now
        self.progress.emit(pct, message)

    def run(self) -> None:
        threading.current_thread().name = self.objectName()
        try:
            result = self.fn(*self.args, progress=self._progress, cancel=self.cancel_event, **self.kwargs)
        except Exception as exc:
            if self.cancel_event.is_set() and "cancel" in str(exc).lower():
                log.info("Tarea %s cancelada", self.objectName())  # no es un error: sin traza en el registro
            else:
                log.exception("Tarea %s falló", self.objectName())
            self.failed.emit(str(exc) or exc.__class__.__name__, traceback.format_exc())
            return
        self.finished_ok.emit(result)

    def cancel(self) -> None:
        self.cancel_event.set()


class WorkerPool(QObject):
    """Mantiene referencias a los hilos activos para evitar que se destruyan a medias."""

    def __init__(self) -> None:
        super().__init__()
        self._workers: list[Worker] = []

    def start(self, worker: Worker) -> Worker:
        self._workers.append(worker)
        worker.finished.connect(lambda: self._cleanup(worker))
        worker.start()
        return worker

    def _cleanup(self, worker: Worker) -> None:
        if worker in self._workers:
            self._workers.remove(worker)
        worker.deleteLater()

    def cancel_all(self) -> None:
        for w in list(self._workers):
            w.cancel()

    def wait_all(self, timeout_ms: int = 8000, keep_alive: Callable[[], None] | None = None) -> bool:
        """Cancela y espera a todos los hilos. ``True`` si terminaron todos dentro del plazo.

        ``keep_alive`` se llama mientras se espera (p. ej. para procesar eventos de la interfaz:
        un trabajo puede necesitar el hilo principal para terminar limpiamente).
        """
        for w in list(self._workers):
            w.cancel()
        deadline = time.monotonic() + timeout_ms / 1000.0
        for w in list(self._workers):
            while not w.wait(100):
                if keep_alive is not None:
                    keep_alive()
                if time.monotonic() > deadline:
                    log.warning("El hilo %s no terminó en %.0f s", w.objectName(), timeout_ms / 1000.0)
                    return False
        return True

    @property
    def busy(self) -> bool:
        return any(w.isRunning() for w in self._workers)
