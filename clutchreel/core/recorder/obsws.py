"""Cliente mínimo del protocolo obs-websocket 5.x sobre ``websocket-client`` (Apache-2.0).

Implementa solo lo que ClutchReel necesita, siguiendo la especificación oficial
(docs/generated/protocol.md del repositorio obsproject/obs-websocket):

* handshake ``Hello`` (op 0) → ``Identify`` (op 1) → ``Identified`` (op 2), con la cadena de
  autenticación SHA-256 + base64 de la especificación;
* peticiones ``Request`` (op 6) con ``requestId`` y respuestas ``RequestResponse`` (op 7) con
  ``requestStatus`` (``result``/``code``/``comment``);
* eventos ``Event`` (op 5) almacenados para consultarlos (p. ej. ``RecordStateChanged``);
* códigos de cierre (4009 = autenticación fallida) y de estado (601 = el recurso ya existe).

La contraseña solo se usa para calcular la cadena de autenticación: no se registra ni se incluye
en ningún mensaje de error.
"""

from __future__ import annotations

import base64
import hashlib
import json
import logging
import struct
import threading
import time
import uuid
from collections import deque
from collections.abc import Callable
from typing import Any

import websocket
from websocket import ABNF

log = logging.getLogger(__name__)

RPC_VERSION = 1
SUBPROTOCOL = "obswebsocket.json"

# WebSocketOpCode
OP_HELLO = 0
OP_IDENTIFY = 1
OP_IDENTIFIED = 2
OP_REIDENTIFY = 3
OP_EVENT = 5
OP_REQUEST = 6
OP_REQUEST_RESPONSE = 7

# WebSocketCloseCode
CLOSE_NOT_IDENTIFIED = 4007
CLOSE_AUTHENTICATION_FAILED = 4009
CLOSE_UNSUPPORTED_RPC_VERSION = 4010
CLOSE_SESSION_INVALIDATED = 4011

# EventSubscription
EVENTS_NONE = 0
EVENTS_OUTPUTS = 1 << 6

# RequestStatus
STATUS_SUCCESS = 100
STATUS_RESOURCE_NOT_FOUND = 600
STATUS_RESOURCE_ALREADY_EXISTS = 601

# Cada cuánto se comprueba la cancelación mientras se espera un mensaje.
_POLL_SECONDS = 0.25
_EVENT_BUFFER = 256


class ObsWsError(Exception):
    """Error de comunicación con obs-websocket."""


class ObsWsAuthError(ObsWsError):
    """OBS rechazó la contraseña (o exige una y no hay)."""


class ObsWsClosedError(ObsWsError):
    """La conexión está cerrada o se cerró a mitad de una operación."""

    def __init__(self, message: str, code: int | None = None) -> None:
        super().__init__(message)
        self.code = code


class ObsWsTimeoutError(ObsWsError):
    """OBS no contestó dentro del tiempo máximo."""


class ObsWsCancelledError(ObsWsError):
    """La espera se cortó porque el usuario canceló."""


class ObsRequestError(ObsWsError):
    """OBS contestó a una petición con ``result: false``."""

    def __init__(self, request_type: str, code: int, comment: str = "") -> None:
        text = f"{request_type} falló con el código {code}"
        if comment:
            text += f": {comment}"
        super().__init__(text)
        self.request_type = request_type
        self.code = code
        self.comment = comment


def auth_string(password: str, salt: str, challenge: str) -> str:
    """Cadena ``authentication`` de ``Identify`` según la especificación.

    base64(sha256(password + salt)) = secreto; base64(sha256(secreto + challenge)) = resultado.
    """
    secret = base64.b64encode(hashlib.sha256((password + salt).encode("utf-8")).digest())
    return base64.b64encode(hashlib.sha256(secret + challenge.encode("utf-8")).digest()).decode("ascii")


class ObsWebSocket:
    """Conexión síncrona a obs-websocket. Un ``request`` a la vez (con cerrojo); los eventos se van guardando."""

    def __init__(
        self,
        host: str,
        port: int,
        password: str = "",
        timeout: float = 4.0,
        cancel: threading.Event | None = None,
        event_subscriptions: int = EVENTS_OUTPUTS,
    ) -> None:
        self.host = host
        self.port = int(port)
        self._password = password or ""
        self.timeout = float(timeout)
        self.cancel = cancel
        self.event_subscriptions = event_subscriptions
        self.obs_version = ""
        self.obs_websocket_version = ""
        self.rpc_version = RPC_VERSION
        self.on_event: Callable[[str, dict[str, Any]], None] | None = None
        self._ws: websocket.WebSocket | None = None
        self._lock = threading.RLock()
        self._events: deque[tuple[str, dict[str, Any]]] = deque(maxlen=_EVENT_BUFFER)

    # ---------------------------------------------------------------- state --

    @property
    def connected(self) -> bool:
        return self._ws is not None

    @property
    def url(self) -> str:
        return f"ws://{self.host}:{self.port}"

    # -------------------------------------------------------------- connect --

    def connect(self) -> None:
        """Abre el WebSocket y completa Hello → Identify → Identified."""
        with self._lock:
            self.close()
            deadline = time.monotonic() + self.timeout
            try:
                ws = websocket.create_connection(
                    self.url,
                    timeout=self.timeout,
                    subprotocols=[SUBPROTOCOL],
                    suppress_origin=True,
                    enable_multithread=True,
                )
            except (OSError, websocket.WebSocketException) as exc:
                raise ObsWsError(f"No se pudo conectar a {self.url}: {exc}") from exc
            self._ws = ws
            try:
                hello = self._read_message(deadline, want_op=OP_HELLO)["d"]
                identify: dict[str, Any] = {"rpcVersion": RPC_VERSION, "eventSubscriptions": int(self.event_subscriptions)}
                auth = hello.get("authentication")
                if isinstance(auth, dict):
                    if not self._password:
                        raise ObsWsAuthError("OBS exige contraseña para el WebSocket y no hay ninguna configurada.")
                    identify["authentication"] = auth_string(self._password, str(auth.get("salt", "")), str(auth.get("challenge", "")))
                self._send(OP_IDENTIFY, identify)
                try:
                    identified = self._read_message(deadline, want_op=OP_IDENTIFIED)["d"]
                except ObsWsClosedError as exc:
                    if exc.code == CLOSE_AUTHENTICATION_FAILED:
                        raise ObsWsAuthError("OBS rechazó la contraseña del WebSocket.") from exc
                    if exc.code == CLOSE_UNSUPPORTED_RPC_VERSION:
                        raise ObsWsError("La versión del protocolo obs-websocket de OBS no es compatible (se necesita obs-websocket 5).") from exc
                    raise
            except BaseException:
                self._drop()
                raise
            self.obs_version = str(hello.get("obsStudioVersion", ""))
            self.obs_websocket_version = str(hello.get("obsWebSocketVersion", ""))
            self.rpc_version = int(identified.get("negotiatedRpcVersion", RPC_VERSION))
            log.debug("Identificado en obs-websocket %s (rpc %s)", self.obs_websocket_version, self.rpc_version)

    def close(self) -> None:
        with self._lock:
            ws, self._ws = self._ws, None
            if ws is not None:
                try:
                    ws.close(timeout=1)
                except Exception:  # noqa: BLE001 - cerrar nunca debe fallar hacia fuera
                    pass

    def _drop(self) -> None:
        """Olvida el socket sin negociar el cierre (ya está roto o a medio abrir)."""
        ws, self._ws = self._ws, None
        if ws is not None:
            try:
                ws.shutdown()
            except Exception:  # noqa: BLE001
                pass

    # -------------------------------------------------------------- request --

    def request(self, request_type: str, data: dict[str, Any] | None = None, timeout: float | None = None) -> dict[str, Any]:
        """Envía una petición y devuelve su ``responseData`` (``{}`` si no hay). Lanza ``ObsRequestError`` si falla."""
        with self._lock:
            if self._ws is None:
                raise ObsWsClosedError("No hay conexión con OBS.")
            request_id = uuid.uuid4().hex
            payload: dict[str, Any] = {"requestType": request_type, "requestId": request_id}
            if data is not None:
                payload["requestData"] = data
            self._send(OP_REQUEST, payload)
            deadline = time.monotonic() + (self.timeout if timeout is None else float(timeout))
            response = self._read_message(deadline, request_id=request_id)["d"]
            status = response.get("requestStatus") or {}
            if not status.get("result"):
                raise ObsRequestError(request_type, int(status.get("code", 0) or 0), str(status.get("comment", "") or ""))
            result = response.get("responseData")
            return result if isinstance(result, dict) else {}

    # --------------------------------------------------------------- events --

    def pop_events(self, event_type: str | None = None) -> list[dict[str, Any]]:
        """Devuelve (y retira) los eventos guardados, opcionalmente solo los de un tipo."""
        with self._lock:
            kept: list[tuple[str, dict[str, Any]]] = []
            out: list[dict[str, Any]] = []
            for kind, data in self._events:
                if event_type is None or kind == event_type:
                    out.append(data)
                else:
                    kept.append((kind, data))
            self._events.clear()
            self._events.extend(kept)
            return out

    def wait_event(self, event_type: str, predicate: Callable[[dict[str, Any]], bool] | None = None, timeout: float = 10.0) -> dict[str, Any]:
        """Espera un evento del tipo dado (ya recibido o por llegar). Lanza ``ObsWsTimeoutError`` si no llega."""
        with self._lock:
            for data in self.pop_events(event_type):
                if predicate is None or predicate(data):
                    return data
            if self._ws is None:
                raise ObsWsClosedError("No hay conexión con OBS.")
            deadline = time.monotonic() + timeout
            while True:
                msg = self._read_message(deadline, want_op=OP_EVENT)["d"]
                if msg.get("eventType") != event_type:
                    continue
                data = msg.get("eventData") or {}
                if predicate is None or predicate(data):
                    self.pop_events(event_type)  # ya consumido
                    return data

    def _store_event(self, d: dict[str, Any]) -> None:
        kind = str(d.get("eventType", ""))
        data = d.get("eventData") or {}
        if not isinstance(data, dict):
            data = {}
        self._events.append((kind, data))
        if self.on_event is not None:
            try:
                self.on_event(kind, data)
            except Exception:
                log.exception("Error en el oyente de eventos de OBS")

    # ------------------------------------------------------------------ io ---

    def _send(self, op: int, d: dict[str, Any]) -> None:
        assert self._ws is not None
        try:
            self._ws.send(json.dumps({"op": op, "d": d}))
        except (OSError, websocket.WebSocketException) as exc:
            self._drop()
            raise ObsWsClosedError(f"Se perdió la conexión con OBS al enviar: {type(exc).__name__}") from exc

    def _read_message(self, deadline: float, want_op: int | None = None, request_id: str | None = None) -> dict[str, Any]:
        """Lee mensajes hasta dar con el esperado. Los eventos intermedios se guardan; pings/pongs se ignoran.

        Comprueba la cancelación cada ``_POLL_SECONDS`` y respeta ``deadline`` (reloj monotónico).
        """
        while True:
            if self.cancel is not None and self.cancel.is_set():
                raise ObsWsCancelledError("Operación cancelada.")
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise ObsWsTimeoutError(f"OBS no contestó en {self.timeout:.0f} s.")
            ws = self._ws
            if ws is None:
                raise ObsWsClosedError("No hay conexión con OBS.")
            ws.settimeout(min(_POLL_SECONDS, remaining))
            try:
                opcode, frame = ws.recv_data_frame(True)
            except websocket.WebSocketTimeoutException:
                continue
            except (OSError, websocket.WebSocketException) as exc:
                self._drop()
                raise ObsWsClosedError(f"Se perdió la conexión con OBS: {type(exc).__name__}") from exc
            if opcode == ABNF.OPCODE_CLOSE:
                code: int | None = None
                reason = ""
                payload = bytes(frame.data or b"")
                if len(payload) >= 2:
                    code = struct.unpack("!H", payload[:2])[0]
                    reason = payload[2:].decode("utf-8", errors="replace")
                self._drop()
                detail = f" ({code}{': ' + reason if reason else ''})" if code is not None else ""
                raise ObsWsClosedError(f"OBS cerró la conexión{detail}.", code)
            if opcode != ABNF.OPCODE_TEXT:
                continue  # ping/pong ya atendidos por websocket-client; binario no se usa con obswebsocket.json
            try:
                msg = json.loads(frame.data)
            except (ValueError, TypeError):
                log.debug("Mensaje de OBS no es JSON válido; se ignora")
                continue
            if not isinstance(msg, dict):
                continue
            op = msg.get("op")
            d = msg.get("d")
            if not isinstance(d, dict):
                d = {}
                msg["d"] = d
            if op == OP_EVENT:
                self._store_event(d)
                if want_op == OP_EVENT:
                    return msg
                continue
            if op == OP_REQUEST_RESPONSE:
                if request_id is not None and d.get("requestId") == request_id:
                    return msg
                continue  # respuesta de una petición anterior que caducó
            if want_op is not None and op == want_op:
                return msg
