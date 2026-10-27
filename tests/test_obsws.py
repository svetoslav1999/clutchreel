"""Cliente obs-websocket propio contra un servidor WebSocket falso (sin OBS real)."""

from __future__ import annotations

import logging
import threading
import time
from pathlib import Path
from typing import Any

import pytest

from clutchreel.core.recorder import obs_client as oc
from clutchreel.core.recorder.obsws import (
    ObsRequestError,
    ObsWebSocket,
    ObsWsAuthError,
    ObsWsCancelledError,
    ObsWsClosedError,
    ObsWsError,
    ObsWsTimeoutError,
    auth_string,
)
from clutchreel.services.config import ObsSettings
from clutchreel.utils.logging_setup import RedactingFilter
from tests.fake_obs_server import CHALLENGE, SALT, CloseNow, Connection, Fail, FakeObsServer, NoResponse

PASSWORD = "supersecretpassword"


def _client(server: FakeObsServer, password: str = "", **kw: Any) -> ObsWebSocket:
    return ObsWebSocket("127.0.0.1", server.port, password, **kw)


# ------------------------------------------------------------------ handshake


def test_auth_string_follows_the_official_procedure() -> None:
    """Vector calculado con el procedimiento de la especificación (password+salt → base64 → +challenge → base64)."""
    assert auth_string(PASSWORD, SALT, CHALLENGE) == "1Ct943GAT+6YQUUX47Ia/ncufilbe6+oD6lY+5kaCu4="


def test_connects_with_correct_password_and_identifies_with_subprotocol() -> None:
    with FakeObsServer(password=PASSWORD) as srv:
        c = _client(srv, PASSWORD)
        c.connect()
        try:
            assert c.connected
            assert c.obs_version == "33.0.0" and c.obs_websocket_version == "5.6.0" and c.rpc_version == 1
            assert srv.identify_payloads[0]["rpcVersion"] == 1
            assert srv.identify_payloads[0]["authentication"] == auth_string(PASSWORD, SALT, CHALLENGE)
            assert srv.identify_payloads[0]["eventSubscriptions"] == 1 << 6
            assert "obswebsocket.json" in srv.handshake_headers[0]["sec-websocket-protocol"]
        finally:
            c.close()
        assert not c.connected


def test_wrong_password_raises_auth_error_from_close_code_4009() -> None:
    with FakeObsServer(password=PASSWORD) as srv:
        c = _client(srv, "incorrecta")
        with pytest.raises(ObsWsAuthError):
            c.connect()
        assert not c.connected


def test_missing_password_when_server_requires_one_is_an_auth_error_without_sending_identify() -> None:
    with FakeObsServer(password=PASSWORD) as srv:
        with pytest.raises(ObsWsAuthError):
            _client(srv, "").connect()
        time.sleep(0.1)
        assert srv.identify_payloads == []


def test_server_without_auth_accepts_identify_without_authentication_field() -> None:
    with FakeObsServer() as srv:
        c = _client(srv, "loquesea")
        c.connect()
        c.close()
        assert "authentication" not in srv.identify_payloads[0]


def test_connection_refused_is_a_plain_error() -> None:
    with FakeObsServer() as srv:
        port = srv.port
    with pytest.raises(ObsWsError):
        ObsWebSocket("127.0.0.1", port, timeout=1.0).connect()


# ------------------------------------------------------------------- requests


def test_request_returns_response_data_and_sends_request_id() -> None:
    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "GetSceneList":
            return {"scenes": [{"sceneName": "A"}, {"sceneName": "ClutchReel"}]}
        return {}

    with FakeObsServer(handler=handler) as srv:
        c = _client(srv)
        c.connect()
        try:
            assert c.request("GetSceneList") == {"scenes": [{"sceneName": "A"}, {"sceneName": "ClutchReel"}]}
            assert c.request("SetCurrentProgramScene", {"sceneName": "ClutchReel"}) == {}
        finally:
            c.close()
    assert srv.requests == [("GetSceneList", {}), ("SetCurrentProgramScene", {"sceneName": "ClutchReel"})]


def test_error_601_resource_already_exists_is_raised_with_code_and_comment() -> None:
    with FakeObsServer(handler=lambda conn, t, d: Fail(601, "Input already exists")) as srv:
        c = _client(srv)
        c.connect()
        try:
            with pytest.raises(ObsRequestError) as info:
                c.request("CreateInput", {"inputName": "x"})
        finally:
            c.close()
    assert info.value.code == 601 and info.value.request_type == "CreateInput" and "already exists" in str(info.value)


def test_request_error_keeps_connection_usable() -> None:
    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        return Fail(600) if rtype == "RemoveInput" else {"ok": True}

    with FakeObsServer(handler=handler) as srv:
        c = _client(srv)
        c.connect()
        try:
            with pytest.raises(ObsRequestError):
                c.request("RemoveInput", {"inputName": "x"})
            assert c.request("GetVersion") == {"ok": True}
            assert c.connected
        finally:
            c.close()


def test_server_disconnect_mid_request_raises_closed() -> None:
    with FakeObsServer(handler=lambda conn, t, d: CloseNow()) as srv:
        c = _client(srv, timeout=3.0)
        c.connect()
        with pytest.raises(ObsWsClosedError):
            c.request("StartRecord")
        assert not c.connected


def test_request_timeout_is_respected() -> None:
    with FakeObsServer(handler=lambda conn, t, d: NoResponse()) as srv:
        c = _client(srv, timeout=0.6)
        c.connect()
        try:
            t0 = time.monotonic()
            with pytest.raises(ObsWsTimeoutError):
                c.request("GetVersion")
            assert 0.5 < time.monotonic() - t0 < 2.0
        finally:
            c.close()


def test_cancel_event_cuts_a_pending_wait_quickly() -> None:
    cancel = threading.Event()
    with FakeObsServer(handler=lambda conn, t, d: NoResponse()) as srv:
        c = _client(srv, timeout=30.0, cancel=cancel)
        c.connect()
        try:
            threading.Timer(0.3, cancel.set).start()
            t0 = time.monotonic()
            with pytest.raises(ObsWsCancelledError):
                c.request("GetVersion")
            assert time.monotonic() - t0 < 2.0
        finally:
            c.close()


def test_stale_response_from_a_timed_out_request_is_ignored() -> None:
    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "Slow":
            time.sleep(0.8)
            return {"slow": True}
        return {"fast": True}

    with FakeObsServer(handler=handler) as srv:
        c = _client(srv, timeout=0.3)
        c.connect()
        try:
            with pytest.raises(ObsWsTimeoutError):
                c.request("Slow")
            assert c.request("Fast", timeout=3.0) == {"fast": True}
        finally:
            c.close()


# --------------------------------------------------------------------- events


def test_events_received_while_waiting_are_stored_and_can_be_awaited() -> None:
    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "StopRecord":
            conn.send_event("RecordStateChanged", {"outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPING", "outputPath": None})
            threading.Timer(
                0.2,
                conn.send_event,
                args=("RecordStateChanged", {"outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED", "outputPath": "C:/v/clip.mkv"}),
            ).start()
            return {}
        return {}

    with FakeObsServer(handler=handler) as srv:
        c = _client(srv)
        c.connect()
        try:
            assert c.request("StopRecord") == {}
            assert c.pop_events("RecordStateChanged")[0]["outputState"] == "OBS_WEBSOCKET_OUTPUT_STOPPING"
            ev = c.wait_event("RecordStateChanged", lambda e: e.get("outputState") == "OBS_WEBSOCKET_OUTPUT_STOPPED", timeout=3.0)
            assert ev["outputPath"] == "C:/v/clip.mkv"
        finally:
            c.close()


def test_wait_event_times_out() -> None:
    with FakeObsServer() as srv:
        c = _client(srv)
        c.connect()
        try:
            with pytest.raises(ObsWsTimeoutError):
                c.wait_event("RecordStateChanged", timeout=0.4)
        finally:
            c.close()


# ------------------------------------------------------ ObsClient sobre el falso


def _settings(srv: FakeObsServer, password: str = "") -> ObsSettings:
    s = ObsSettings()
    s.host, s.port, s.password = "127.0.0.1", srv.port, password
    return s


def test_obs_client_maps_auth_failure_to_a_friendly_message(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(oc, "is_process_running", lambda _n: True)
    with FakeObsServer(password=PASSWORD) as srv:
        client = oc.ObsClient(_settings(srv, "mala"))
        with pytest.raises(oc.ObsError, match="contraseña"):
            client.connect()
        assert not client.connected


def test_obs_client_ensure_scene_creates_scene_and_input_and_retries_on_601() -> None:
    state: dict[str, Any] = {"inputs": [], "creates": 0}

    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "GetSceneList":
            return {"scenes": []}
        if rtype == "GetInputKindList":
            return {"inputKinds": ["game_capture", "window_capture", "monitor_capture"]}
        if rtype == "GetInputList":
            return {"inputs": state["inputs"]}
        if rtype == "CreateInput":
            state["creates"] += 1
            if state["creates"] == 1:
                return Fail(601, "Input already exists")
            state["inputs"] = [{"inputName": data["inputName"], "inputKind": data["inputKind"]}]
            return {"sceneItemId": 7, "inputUuid": "u"}
        if rtype == "GetSceneItemList":
            return {"sceneItems": [{"sourceName": "ClutchReel - Captura CS2", "sceneItemId": 7}]}
        if rtype == "GetVideoSettings":
            return {"baseWidth": 1920, "baseHeight": 1080}
        return {}

    with FakeObsServer(handler=handler) as srv:
        client = oc.ObsClient(_settings(srv))
        client.connect()
        try:
            assert client.ensure_scene() == "game"
        finally:
            client.disconnect()
    types = [t for t, _ in srv.requests]
    assert types.count("CreateScene") == 1 and types.count("CreateInput") == 2
    create = next(d for t, d in srv.requests if t == "CreateInput")
    assert create["inputKind"] == "game_capture" and create["inputSettings"]["window"] == oc.CS2_WINDOW and create["sceneItemEnabled"] is True
    transform = next(d for t, d in srv.requests if t == "SetSceneItemTransform")
    assert transform["sceneItemId"] == 7 and transform["sceneItemTransform"]["boundsWidth"] == 1920
    assert types[-1] == "SetCurrentProgramScene"


def test_obs_client_stop_record_takes_path_from_event_when_response_lacks_it(tmp_path: Path) -> None:
    clip = tmp_path / "clip.mkv"
    clip.write_bytes(b"\x1aE\xdf\xa3" + b"\0" * 12)

    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "StopRecord":
            threading.Timer(
                0.2,
                conn.send_event,
                args=("RecordStateChanged", {"outputActive": False, "outputState": "OBS_WEBSOCKET_OUTPUT_STOPPED", "outputPath": str(clip)}),
            ).start()
            return {}
        if rtype == "GetRecordStatus":
            return {"outputActive": False}
        return {}

    with FakeObsServer(handler=handler) as srv:
        client = oc.ObsClient(_settings(srv))
        client.connect()
        try:
            assert client.stop_record() == clip
        finally:
            client.disconnect()


def test_obs_client_apply_recording_settings_sends_directory_format_and_video(tmp_path: Path) -> None:
    def handler(conn: Connection, rtype: str, data: dict[str, Any]) -> Any:
        if rtype == "GetProfileParameter":
            return {"parameterValue": "flv" if data["parameterCategory"] == "SimpleOutput" else "mkv"}
        if rtype == "GetRecordStatus":
            return {"outputActive": False}
        return {}

    with FakeObsServer(handler=handler) as srv:
        s = _settings(srv)
        s.manage_video_settings = True
        client = oc.ObsClient(s)
        client.connect()
        try:
            client.apply_recording_settings(tmp_path / "grab")
        finally:
            client.disconnect()
    reqs = dict(((t, d.get("parameterCategory", ""), d.get("parameterName", "")), d) for t, d in srv.requests)
    assert reqs[("SetRecordDirectory", "", "")]["recordDirectory"] == str(tmp_path / "grab")
    assert reqs[("SetProfileParameter", "SimpleOutput", "RecFormat2")]["parameterValue"] == "mkv"
    assert ("SetProfileParameter", "AdvOut", "RecFormat2") not in reqs  # ya era bueno
    video = reqs[("SetVideoSettings", "", "")]
    assert video["fpsDenominator"] == 1 and video["baseWidth"] == video["outputWidth"] == int(s.width)


def test_obs_client_cancel_cuts_connect_wait() -> None:
    cancel = threading.Event()
    with FakeObsServer(handler=lambda conn, t, d: NoResponse()) as srv:
        client = oc.ObsClient(_settings(srv))
        client.cancel = cancel
        client.connect()
        threading.Timer(0.3, cancel.set).start()
        with pytest.raises(oc.ObsError, match="cancelada"):
            client.is_recording()


def test_password_never_appears_in_logs_or_errors(caplog: pytest.LogCaptureFixture) -> None:
    caplog.set_level(logging.DEBUG)
    caplog.handler.addFilter(RedactingFilter())
    secret = "ClaveMuySecreta42"
    with FakeObsServer(password=secret) as srv:
        client = oc.ObsClient(_settings(srv, secret))
        client.connect()
        client.disconnect()
        bad = oc.ObsClient(_settings(srv, secret + "x"))
        with pytest.raises(oc.ObsError) as info:
            bad.connect()
    assert secret not in caplog.text
    assert secret not in str(info.value) and secret not in repr(info.value.__cause__)
