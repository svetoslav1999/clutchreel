"""Cola de trabajos (analizar, grabar, exportar, subir) con progreso y cancelación."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from PySide6.QtCore import QObject, Signal

from clutchreel.ui.workers import Worker, WorkerPool

log = logging.getLogger(__name__)

STATUS_LABELS = {
    "pendiente": "Pendiente",
    "en curso": "En curso",
    "hecho": "Terminado",
    "parcial": "Parcial",
    "error": "Fallido",
    "cancelado": "Cancelado",
}


@dataclass
class Job:
    id: int
    kind: str  # analizar | grabar | exportar | subir | calibrar
    title: str
    fn: Callable[..., Any]
    status: str = "pendiente"
    progress: int = 0
    message: str = ""
    result: Any = None
    error: str = ""
    started_at: float = 0.0
    finished_at: float = 0.0
    on_done: Callable[[Any], None] | None = None
    on_error: Callable[[str], None] | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def elapsed(self) -> float:
        if not self.started_at:
            return 0.0
        end = self.finished_at or time.time()
        return end - self.started_at

    def eta_seconds(self) -> float | None:
        if self.status != "en curso" or self.progress <= 3:
            return None
        return self.elapsed * (100 - self.progress) / self.progress


class JobQueue(QObject):
    changed = Signal()
    job_finished = Signal(object)
    job_failed = Signal(object)

    def __init__(self, pool: WorkerPool) -> None:
        super().__init__()
        self.pool = pool
        self.jobs: list[Job] = []
        self._next_id = 1
        self._current: Worker | None = None
        self._current_job: Job | None = None

    def add(self, kind: str, title: str, fn: Callable[..., Any], on_done: Callable[[Any], None] | None = None, on_error: Callable[[str], None] | None = None, **extra: Any) -> Job:
        job = Job(id=self._next_id, kind=kind, title=title, fn=fn, on_done=on_done, on_error=on_error, extra=extra)
        self._next_id += 1
        self.jobs.append(job)
        self.changed.emit()
        self._pump()
        return job

    @property
    def busy(self) -> bool:
        return self._current_job is not None

    @property
    def current(self) -> Job | None:
        return self._current_job

    def pending(self) -> list[Job]:
        return [j for j in self.jobs if j.status == "pendiente"]

    def _pump(self) -> None:
        if self._current_job is not None:
            return
        for job in self.jobs:
            if job.status == "pendiente":
                self._start(job)
                return

    def _start(self, job: Job) -> None:
        job.status = "en curso"
        job.started_at = time.time()
        self._current_job = job
        worker = Worker(job.fn, name=f"job-{job.kind}-{job.id}")
        worker.progress.connect(lambda pct, msg, j=job: self._on_progress(j, pct, msg))
        worker.finished_ok.connect(lambda result, j=job: self._on_done(j, result))
        worker.failed.connect(lambda msg, _tb, j=job: self._on_error(j, msg))
        self._current = worker
        self.pool.start(worker)
        self.changed.emit()

    def _on_progress(self, job: Job, pct: int, msg: str) -> None:
        job.progress = pct
        if msg:
            job.message = msg
        self.changed.emit()

    def _on_done(self, job: Job, result: Any) -> None:
        job.status = "hecho"
        job.progress = 100
        job.result = result
        # Un trabajo puede terminar sin excepción pero con fallos (p. ej. clips sin grabar).
        outcome = getattr(result, "job_outcome", None)
        if callable(outcome):
            status, detail = outcome()
            job.status = status
            job.error = detail
        job.finished_at = time.time()
        self._current = None
        self._current_job = None
        self.changed.emit()
        if job.on_done:
            try:
                job.on_done(result)
            except Exception as exc:
                log.exception("on_done de %s falló: %s", job.title, exc)
        self.job_finished.emit(job)
        if job.status in ("parcial", "error"):
            self.job_failed.emit(job)
        self._pump()

    def _on_error(self, job: Job, msg: str) -> None:
        job.status = "cancelado" if "cancel" in msg.lower() else "error"
        job.error = msg
        job.finished_at = time.time()
        self._current = None
        self._current_job = None
        self.changed.emit()
        if job.on_error:
            try:
                job.on_error(msg)
            except Exception as exc:
                log.exception("on_error de %s falló: %s", job.title, exc)
        self.job_failed.emit(job)
        self._pump()

    def cancel_current(self) -> None:
        if self._current:
            self._current.cancel()
        if self._current_job:
            self._current_job.message = "Cancelando…"
            self.changed.emit()

    def cancel_pending(self) -> None:
        for j in self.jobs:
            if j.status == "pendiente":
                j.status = "cancelado"
        self.changed.emit()

    def clear_finished(self) -> None:
        self.jobs = [j for j in self.jobs if j.status in ("pendiente", "en curso")]
        self.changed.emit()
