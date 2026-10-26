"""Logging a fichero rotativo + consola, y utilidades de informe de errores."""

from __future__ import annotations

import logging
import logging.handlers
import platform
import sys
from pathlib import Path

from clutchreel import APP_NAME, __version__
from clutchreel.utils.paths import logs_dir

LOG_FILE_NAME = "clutchreel.log"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(threadName)s | %(name)s | %(message)s"


def log_file_path() -> Path:
    return logs_dir() / LOG_FILE_NAME


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configura el logger raíz una sola vez (idempotente)."""
    root = logging.getLogger()
    if getattr(root, "_clutchreel_configured", False):
        return root
    root.setLevel(logging.DEBUG)
    formatter = logging.Formatter(_FORMAT)

    try:
        file_handler = logging.handlers.RotatingFileHandler(
            log_file_path(), maxBytes=2_000_000, backupCount=5, encoding="utf-8"
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        root.addHandler(file_handler)
    except OSError:
        pass

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    root.addHandler(console)

    for noisy in ("urllib3", "googleapiclient", "PIL", "obsws_python"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    root._clutchreel_configured = True  # type: ignore[attr-defined]
    logging.getLogger(APP_NAME).info("%s %s iniciado (Python %s, %s)", APP_NAME, __version__, platform.python_version(), platform.platform())
    return root


def read_log_tail(max_chars: int = 60_000) -> str:
    path = log_file_path()
    if not path.exists():
        return "(todavía no hay registro)"
    try:
        data = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return f"No se pudo leer el registro: {exc}"
    return data[-max_chars:]


def build_error_report(extra: dict[str, str] | None = None) -> str:
    """Texto listo para copiar: versión, sistema y últimas líneas del registro."""
    lines = [
        f"{APP_NAME} {__version__}",
        f"Python {platform.python_version()} — {platform.platform()}",
    ]
    for key, value in (extra or {}).items():
        lines.append(f"{key}: {value}")
    lines.append("")
    lines.append("=== Últimas líneas del registro ===")
    lines.append(read_log_tail(20_000))
    return "\n".join(lines)
