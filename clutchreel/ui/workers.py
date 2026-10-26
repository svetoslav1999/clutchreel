"""Hilos de trabajo para que la interfaz nunca se congele."""

from __future__ import annotations

import logging
import threading
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

    def _progress(self, value: float, message: str = "") -> None:
        pct = round(value * 100) if 0.0 <= value <= 1.0 else int(value)
        self.progress.emit(max(0, min(100, pct)), message or "")

    def run(self) -> None:
        threading.current_thread().name = self.objectName()
        try:
            result = self.fn(*self.args, progress=self._progress, cancel=self.cancel_event, **self.kwargs)
        except Exception as exc:
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

    def wait_all(self, timeout_ms: int = 8000) -> None:
        for w in list(self._workers):
            w.cancel()
            w.wait(timeout_ms)

    @property
    def busy(self) -> bool:
        return any(w.isRunning() for w in self._workers)
