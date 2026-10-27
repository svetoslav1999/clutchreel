"""Actualizar de 1.0.0 a 1.1.0: configuración guardada por la 1.0.0 y sincronización de dependencias."""

from __future__ import annotations

import importlib.util
import json
import shutil
import sys
from pathlib import Path
from types import ModuleType

import pytest

from clutchreel.services.config import CONFIG_VERSION, ConfigStore

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = Path(__file__).parent / "data" / "config_1_0_0.json"


def test_config_saved_by_1_0_0_loads_and_keeps_user_values(tmp_path: Path) -> None:
    """``tests/data/config_1_0_0.json`` lo escribió el código de la 1.0.0 (con valores de usuario ficticios)."""
    path = tmp_path / "ClutchReel" / "config.json"
    path.parent.mkdir(parents=True)
    shutil.copy(FIXTURE, path)
    original = json.loads(FIXTURE.read_text(encoding="utf-8"))
    store = ConfigStore(path)
    store.load()
    cfg = store.config
    assert cfg.player.steamid64 == 76561198000000001 and cfg.player.name == "yo"
    assert cfg.obs.password == "ClaveDePrueba123" and cfg.obs.port == 4460 and cfg.obs.fps == 30
    assert cfg.paths.output_folder == original["paths"]["output_folder"]
    assert cfg.version >= int(original["version"]) and cfg.version == CONFIG_VERSION
    store.save()
    again = json.loads(path.read_text(encoding="utf-8"))
    assert again["obs"]["password"] == "ClaveDePrueba123" and again["player"]["steamid64"] == 76561198000000001
    assert set(original) <= set(again)  # no se pierde ninguna sección


def _deps() -> ModuleType:
    spec = importlib.util.spec_from_file_location("dependencias", ROOT / "scripts" / "dependencias.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_requirements_names_are_normalised() -> None:
    deps = _deps()
    text = "# comentario\nPySide6==6.12.0\nobsws_python==1.8.0  # viejo\n-r otro.txt\n\nwebsocket-client==1.9.2\n"
    assert deps.req_names(text) == {"pyside6", "obsws-python", "websocket-client"}


@pytest.fixture
def fake_project(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> tuple[ModuleType, list[tuple[str, ...]], set[str]]:
    deps = _deps()
    (tmp_path / ".venv").mkdir()
    req = tmp_path / "requirements.txt"
    req.write_text("PySide6==6.12.0\nwebsocket-client==1.9.2\n", encoding="utf-8")
    monkeypatch.setattr(deps, "REQ", req)
    monkeypatch.setattr(deps, "STAMP", tmp_path / ".venv" / ".instalado")
    monkeypatch.setattr(deps, "SNAPSHOT", tmp_path / ".venv" / ".requirements_instalados.txt")
    calls: list[tuple[str, ...]] = []
    present = {"obsws-python", "pyside6", "websocket-client", "paquete-viejo"}

    def pip(*args: str) -> int:
        calls.append(args)
        if args[0] == "uninstall":
            present.discard(args[-1])
        return 0

    monkeypatch.setattr(deps, "pip", pip)
    monkeypatch.setattr(deps, "installed", lambda name: name in present)
    monkeypatch.setattr(sys, "argv", ["dependencias.py"])
    return deps, calls, present


def test_venv_from_1_0_0_reinstalls_and_removes_obsws_python(fake_project) -> None:  # type: ignore[no-untyped-def]
    deps, calls, present = fake_project
    deps.STAMP.write_text("instalado\n", encoding="utf-8")  # marca que dejaba Iniciar.bat de la 1.0.0
    assert deps.main() == 0
    assert any(c[:2] == ("install", "-r") for c in calls)
    assert "obsws-python" not in present
    assert "paquete-viejo" in present  # sin lista anterior solo se quitan los retirados conocidos
    calls.clear()
    assert deps.main() == 0
    assert calls == []  # mismo requirements.txt: no se reinstala


def test_package_removed_from_requirements_is_uninstalled(fake_project) -> None:  # type: ignore[no-untyped-def]
    deps, _calls, present = fake_project
    deps.SNAPSHOT.write_text("PySide6==6.12.0\npaquete-viejo==1.0\nwebsocket-client==1.9.2\n", encoding="utf-8")
    deps.STAMP.write_text("huella-anterior\n", encoding="utf-8")
    assert deps.main() == 0
    assert "paquete-viejo" not in present and "pyside6" in present and "websocket-client" in present


def test_failed_install_keeps_old_stamp(fake_project, monkeypatch: pytest.MonkeyPatch) -> None:  # type: ignore[no-untyped-def]
    deps, _calls, _present = fake_project
    deps.STAMP.write_text("instalado\n", encoding="utf-8")
    monkeypatch.setattr(deps, "pip", lambda *a: 1 if a[0] == "install" and a[1] == "-r" else 0)
    assert deps.main() == 1
    assert deps.STAMP.read_text(encoding="utf-8") == "instalado\n"  # se volverá a intentar


def test_windows_scripts_use_crlf_and_never_discard_changes() -> None:
    for name in ("Iniciar.bat", "Actualizar.bat"):
        data = (ROOT / name).read_bytes()
        assert b"\r\n" in data and b"\n" not in data.replace(b"\r\n", b""), name
        assert b"\x0c" not in data
    text = (ROOT / "Actualizar.bat").read_text(encoding="utf-8")
    assert "git pull --ff-only" in text
    # El único «reset --hard» es el que se le muestra al usuario como texto, nunca se ejecuta.
    for line in text.splitlines():
        if "reset --hard" in line:
            assert line.strip().lower().startswith("echo")
    assert "scripts\\dependencias.py" in (ROOT / "Iniciar.bat").read_text(encoding="utf-8")
