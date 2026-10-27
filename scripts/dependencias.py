"""Instala o actualiza las dependencias del entorno virtual cuando cambia ``requirements.txt``.

Se ejecuta desde ``Iniciar.bat`` y ``Actualizar.bat`` con el Python del ``.venv`` y ``-I`` (sin
depender del proyecto). Guarda en ``.venv/.instalado`` la huella SHA-256 de ``requirements.txt`` y
en ``.venv/.requirements_instalados.txt`` la lista instalada, para:

* reinstalar solo cuando el contenido de ``requirements.txt`` cambie (no por la fecha del fichero);
* desinstalar los paquetes que una versión nueva ya no usa (en 1.1.0, ``obsws-python``).

Uso: python -I scripts/dependencias.py [--forzar]
Sale con 0 si las dependencias quedan instaladas, 1 si falla.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQ = ROOT / "requirements.txt"
VENV = ROOT / ".venv"
STAMP = VENV / ".instalado"
SNAPSHOT = VENV / ".requirements_instalados.txt"
# Paquetes que dejaron de usarse y deben desaparecer aunque no haya lista anterior (venv de la 1.0.0).
RETIRED = ["obsws-python"]


def norm(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


def req_names(text: str) -> set[str]:
    names: set[str] = set()
    for line in text.splitlines():
        line = line.split("#", 1)[0].strip()
        if not line or line.startswith("-"):
            continue
        m = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", line)
        if m:
            names.add(norm(m.group(0)))
    return names


def pip(*args: str) -> int:
    return subprocess.call([sys.executable, "-m", "pip", *args, "--disable-pip-version-check"])


def installed(name: str) -> bool:
    return subprocess.call([sys.executable, "-m", "pip", "show", "-q", name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL) == 0


def main() -> int:
    force = "--forzar" in sys.argv[1:]
    text = REQ.read_text(encoding="utf-8")
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    previous = STAMP.read_text(encoding="utf-8").strip() if STAMP.exists() else ""
    if previous == digest and not force:
        print("[OK] Dependencias al dia")
        return 0
    print("[..] Instalando o actualizando dependencias (puede tardar unos minutos)...")
    pip("install", "--upgrade", "pip", "--quiet")
    if pip("install", "-r", str(REQ), "--quiet") != 0:
        print("[X] Fallo la instalacion de dependencias. Comprueba la conexion a Internet y vuelve a intentarlo.")
        return 1
    wanted = req_names(text)
    old = req_names(SNAPSHOT.read_text(encoding="utf-8")) if SNAPSHOT.exists() else set()
    for name in sorted((old | {norm(r) for r in RETIRED}) - wanted):
        if installed(name):
            print(f"[..] Quitando {name} (ya no se usa)")
            pip("uninstall", "-y", "--quiet", name)
    SNAPSHOT.write_text(text, encoding="utf-8")
    STAMP.write_text(digest + "\n", encoding="utf-8")
    print("[OK] Dependencias instaladas")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
