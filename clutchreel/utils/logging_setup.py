"""Logging a fichero rotativo + consola, y utilidades de informe de errores."""

from __future__ import annotations

import logging
import logging.handlers
import platform
import re
import sys
import threading
from pathlib import Path

from clutchreel import APP_NAME, __version__
from clutchreel.utils.paths import logs_dir

LOG_FILE_NAME = "clutchreel.log"
_FORMAT = "%(asctime)s | %(levelname)-7s | %(threadName)s | %(name)s | %(message)s"


# --- Secretos: nunca llegan a la consola, al fichero de registro ni al informe de errores ---
_SECRETS: set[str] = set()
_SECRETS_LOCK = threading.Lock()
# «password='x'», «password: x», «"server_password": "x"», «token=x»…
_SECRET_KV_RE = re.compile(r"""(?i)((?:server_)?(?:password|passwd|secret|token|authorization)["']?\s*[:=]\s*)(["']?)([^\s"',;)}]+)(["']?)""")
REDACTED = "***"


def register_secret(value: str | None) -> None:
    """Añade un valor (contraseña de OBS, token…) que debe tacharse de cualquier mensaje registrado."""
    if value and len(value) >= 4:
        with _SECRETS_LOCK:
            _SECRETS.add(value)


def redact(text: str) -> str:
    with _SECRETS_LOCK:
        secrets = sorted(_SECRETS, key=len, reverse=True)
    for s in secrets:
        text = text.replace(s, REDACTED)
    return _SECRET_KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{REDACTED}{m.group(4)}", text)


class RedactingFilter(logging.Filter):
    """Tacha secretos del mensaje ya formateado (también los que llegan de librerías de terceros)."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            message = record.getMessage()
        except Exception:  # noqa: BLE001 - un mensaje mal formado no debe romper el registro
            return True
        clean = redact(message)
        if record.exc_info and not record.exc_text:
            record.exc_text = logging.Formatter().formatException(record.exc_info)
        if record.exc_text:
            record.exc_text = redact(record.exc_text)
        if clean != message:
            record.msg = clean
            record.args = None
        return True


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
        file_handler.addFilter(RedactingFilter())
        root.addHandler(file_handler)
    except OSError:
        pass

    console = logging.StreamHandler(sys.stderr)
    console.setLevel(level)
    console.setFormatter(formatter)
    console.addFilter(RedactingFilter())
    root.addHandler(console)

    for noisy in ("urllib3", "googleapiclient", "PIL", "websocket"):
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
    return redact(data[-max_chars:])  # por si el fichero viene de una versión anterior sin filtro


def build_error_report(extra: dict[str, str] | None = None) -> str:
    """Texto listo para copiar: versión, sistema y últimas líneas del registro."""
    lines = [
        f"{APP_NAME} {__version__}",
        f"Python {platform.python_version()} — {platform.platform()}",
    ]
    for key, value in (extra or {}).items():
        lines.append(redact(f"{key}: {value}"))
    lines.append("")
    lines.append("=== Últimas líneas del registro ===")
    lines.append(read_log_tail(20_000))
    return "\n".join(lines)
