"""Tests de la edición de config.json de obs-websocket. Nunca tocan el archivo real."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import pytest

from clutchreel.services import obs_setup
from clutchreel.services.config import ConfigStore
from clutchreel.services.diagnostics import run_diagnostics
from clutchreel.services.obs_setup import (
    DEFAULT_WEBSOCKET_CONFIG,
    ObsSetupError,
    apply_websocket_config,
    configure_obs,
    generate_password,
    pick_port,
    read_state,
)


@pytest.fixture
def ws_path(tmp_path: Path) -> Path:
    return tmp_path / "obs-studio" / "plugin_config" / "obs-websocket" / "config.json"


def _write(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data) if not isinstance(data, str) else data, encoding="utf-8")


def test_generate_password_is_alnum_and_random() -> None:
    a, b = generate_password(), generate_password()
    assert len(a) == 20 and a.isalnum()
    assert a != b


def test_edit_existing_keeps_other_fields_and_makes_backup(ws_path: Path) -> None:
    _write(ws_path, {**DEFAULT_WEBSOCKET_CONFIG, "alerts_enabled": True, "campo_futuro": {"x": 1}, "server_password": "vieja"})
    backup = apply_websocket_config(ws_path, 4460, "NuevaClave123")
    data = json.loads(ws_path.read_text(encoding="utf-8"))
    assert data["server_enabled"] is True
    assert data["server_port"] == 4460
    assert data["auth_required"] is True
    assert data["server_password"] == "NuevaClave123"
    assert data["alerts_enabled"] is False
    assert data["first_load"] is False
    assert data["campo_futuro"] == {"x": 1}
    assert backup is not None and backup.name.endswith(".bak")
    assert json.loads(backup.read_text(encoding="utf-8"))["server_password"] == "vieja"


def test_missing_file_is_created_with_default_structure(ws_path: Path) -> None:
    assert read_state(ws_path).exists is False
    backup = apply_websocket_config(ws_path, 4455, "abc")
    assert backup is None
    data = json.loads(ws_path.read_text(encoding="utf-8"))
    assert set(DEFAULT_WEBSOCKET_CONFIG) <= set(data)
    assert data["server_enabled"] is True and data["server_password"] == "abc"


@pytest.mark.parametrize("content", ["{esto no es json", "[1, 2, 3]", ""])
def test_corrupt_file_is_backed_up_and_recreated(ws_path: Path, content: str) -> None:
    _write(ws_path, content)
    assert read_state(ws_path).corrupt is True
    backup = apply_websocket_config(ws_path, 4455, "abc")
    assert backup is not None and backup.read_text(encoding="utf-8") == content
    state = read_state(ws_path)
    assert state.enabled and not state.corrupt


def test_read_state_reports_disabled(ws_path: Path) -> None:
    _write(ws_path, {**DEFAULT_WEBSOCKET_CONFIG, "server_port": 4500})
    state = read_state(ws_path)
    assert state.exists and not state.enabled and state.port == 4500


def test_pick_port_skips_busy_port() -> None:
    with socket.socket() as srv:
        srv.bind(("127.0.0.1", 0))
        srv.listen()
        busy = srv.getsockname()[1]
        assert pick_port(busy) != busy


def _store(tmp_path: Path) -> ConfigStore:
    store = ConfigStore(tmp_path / "clutchreel" / "config.json")
    store.load()
    return store


def test_configure_obs_saves_credentials_without_touching_real_files(ws_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs_setup, "is_process_running", lambda _name: False)
    store = _store(tmp_path)
    result = configure_obs(store, confirm_close=lambda: True, ws_config=ws_path, reopen=False)
    data = json.loads(ws_path.read_text(encoding="utf-8"))
    assert data["server_enabled"] is True
    assert data["server_password"] == result.password == store.config.obs.password
    assert data["server_port"] == result.port == store.config.obs.port
    saved = json.loads(store.path.read_text(encoding="utf-8"))
    assert saved["obs"]["password"] == result.password
    assert result.reopened is False


def test_configure_obs_does_nothing_if_user_declines_close(ws_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs_setup, "is_process_running", lambda _name: True)
    closed: list[bool] = []
    monkeypatch.setattr(obs_setup, "close_obs", lambda *a, **k: closed.append(True) or True)
    with pytest.raises(ObsSetupError):
        configure_obs(_store(tmp_path), confirm_close=lambda: False, ws_config=ws_path, reopen=False)
    assert closed == []
    assert not ws_path.exists()


def test_configure_obs_aborts_if_obs_does_not_close(ws_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(obs_setup, "is_process_running", lambda _name: True)
    monkeypatch.setattr(obs_setup, "close_obs", lambda *a, **k: False)
    with pytest.raises(ObsSetupError):
        configure_obs(_store(tmp_path), confirm_close=lambda: True, ws_config=ws_path, reopen=False)
    assert not ws_path.exists()


def test_diagnostics_flags_disabled_websocket_with_one_click_fix(ws_path: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(ws_path, DEFAULT_WEBSOCKET_CONFIG)  # server_enabled False
    monkeypatch.setattr(obs_setup, "websocket_config_path", lambda: ws_path)
    results = run_diagnostics(_store(tmp_path).config)
    ws = next(r for r in results if r.name == "OBS WebSocket")
    assert not ws.ok
    assert ws.fix_action == obs_setup.OBS_AUTOCONFIG_ACTION
    assert "automáticamente" in ws.fix
