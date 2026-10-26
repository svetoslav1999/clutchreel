"""Comprueba FFmpeg y, si falta, lo descarga (build oficial de gyan.dev) en ``tools/``.

Se ejecuta desde ``Iniciar.bat`` con ``python -I`` (sin depender del proyecto).
Sale con 0 si FFmpeg está disponible al terminar, 1 en caso contrario.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"


def find_local() -> Path | None:
    cands = [TOOLS / "ffmpeg" / "bin" / "ffmpeg.exe"]
    cands += list(TOOLS.glob("ffmpeg*/bin/ffmpeg.exe"))
    which = shutil.which("ffmpeg")
    if which:
        cands.append(Path(which))
    local = Path(os.environ.get("LOCALAPPDATA", "")) / "Microsoft" / "WinGet" / "Packages"
    if local.is_dir():
        cands += list(local.glob("Gyan.FFmpeg*/**/bin/ffmpeg.exe"))
    for c in cands:
        if c.is_file():
            return c
    return None


def works(path: Path) -> bool:
    try:
        return subprocess.run([str(path), "-version"], capture_output=True, timeout=20).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def download() -> Path | None:
    TOOLS.mkdir(exist_ok=True)
    print("[..] Descargando FFmpeg (unos 90 MB)...")
    tmp = Path(tempfile.mkdtemp(prefix="ffmpeg_"))
    zip_path = tmp / "ffmpeg.zip"

    def hook(blocks: int, block_size: int, total: int) -> None:
        if total > 0:
            pct = min(100, blocks * block_size * 100 // total)
            print(f"\r     {pct:3d}%", end="", flush=True)

    try:
        urllib.request.urlretrieve(URL, zip_path, hook)
        print()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(tmp)
        extracted = next(tmp.glob("ffmpeg*/bin/ffmpeg.exe"), None)
        if not extracted:
            print("[X] El paquete descargado no contiene ffmpeg.exe")
            return None
        target = TOOLS / "ffmpeg"
        if target.exists():
            shutil.rmtree(target, ignore_errors=True)
        shutil.move(str(extracted.parents[1]), str(target))
        return target / "bin" / "ffmpeg.exe"
    except Exception as exc:  # noqa: BLE001
        print(f"\n[X] No se pudo descargar FFmpeg: {exc}")
        return None
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def main() -> int:
    found = find_local()
    if found and works(found):
        print(f"[OK] FFmpeg: {found}")
        return 0
    got = download()
    if got and works(got):
        print(f"[OK] FFmpeg instalado en {got}")
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
