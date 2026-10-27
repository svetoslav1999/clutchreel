"""Servidor WebSocket falso que habla obs-websocket 5 (solo lo necesario para los tests).

RFC 6455 a mano (handshake HTTP, tramas con máscara del cliente, tramas de cierre) sin
dependencias externas. Guarda las peticiones recibidas y deja al test decidir cada respuesta.
"""

from __future__ import annotations

import base64
import hashlib
import json
import socket
import struct
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from clutchreel.core.recorder.obsws import auth_string

WS_GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
SALT = "lM1GncleQOaCu9lT1yeUZhFYnqhsLLP1G5lAGo3ixaI="
CHALLENGE = "+IxH4CnCiqpX1rM9scsNynZzbOe4KhDeYcTNS3PDaeY="

OPCODE_TEXT = 0x1
OPCODE_CLOSE = 0x8
OPCODE_PING = 0x9
OPCODE_PONG = 0xA


@dataclass
class Fail:
    """Respuesta de error: ``requestStatus.result = false`` con este código."""

    code: int
    comment: str = ""


class NoResponse:
    """El servidor no contesta (para probar tiempo agotado y cancelación)."""


class CloseNow:
    """El servidor cierra el socket sin contestar (desconexión a mitad)."""


Handler = Callable[["Connection", str, dict[str, Any]], Any]


def _default_handler(conn: Connection, request_type: str, data: dict[str, Any]) -> Any:
    if request_type == "GetVersion":
        return {"obsVersion": "33.0.0", "obsWebSocketVersion": "5.6.0", "rpcVersion": 1}
    return {}


@dataclass
class Connection:
    sock: socket.socket
    server: FakeObsServer
    send_lock: threading.Lock = field(default_factory=threading.Lock)
    identified: bool = False
    closed: bool = False

    # ------------------------------------------------------------- frames ---

    def _send_frame(self, opcode: int, payload: bytes) -> None:
        head = bytes([0x80 | opcode])
        n = len(payload)
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack("!H", n)
        else:
            head += bytes([127]) + struct.pack("!Q", n)
        with self.send_lock:
            try:
                self.sock.sendall(head + payload)
            except OSError:
                self.closed = True

    def send_json(self, op: int, d: dict[str, Any]) -> None:
        self._send_frame(OPCODE_TEXT, json.dumps({"op": op, "d": d}).encode("utf-8"))

    def send_event(self, event_type: str, data: dict[str, Any], intent: int = 1 << 6) -> None:
        self.send_json(5, {"eventType": event_type, "eventIntent": intent, "eventData": data})

    def send_close(self, code: int, reason: str = "") -> None:
        self._send_frame(OPCODE_CLOSE, struct.pack("!H", code) + reason.encode("utf-8"))

    def drop(self) -> None:
        self.closed = True
        try:
            self.sock.shutdown(socket.SHUT_RDWR)
        except OSError:
            pass
        self.sock.close()

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("cliente cerrado")
            buf += chunk
        return buf

    def recv_frame(self) -> tuple[int, bytes]:
        b1, b2 = self._recv_exact(2)
        opcode = b1 & 0x0F
        masked = bool(b2 & 0x80)
        length = b2 & 0x7F
        if length == 126:
            length = struct.unpack("!H", self._recv_exact(2))[0]
        elif length == 127:
            length = struct.unpack("!Q", self._recv_exact(8))[0]
        mask = self._recv_exact(4) if masked else b""
        payload = self._recv_exact(length)
        if masked:
            payload = bytes(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, payload

    # ----------------------------------------------------------- protocol ---

    def handshake(self) -> None:
        raw = b""
        while b"\r\n\r\n" not in raw:
            chunk = self.sock.recv(4096)
            if not chunk:
                raise ConnectionError("sin cabeceras")
            raw += chunk
        headers: dict[str, str] = {}
        for line in raw.split(b"\r\n")[1:]:
            if b":" in line:
                k, v = line.split(b":", 1)
                headers[k.strip().decode().lower()] = v.strip().decode()
        self.server.handshake_headers.append(headers)
        key = headers.get("sec-websocket-key", "")
        accept = base64.b64encode(hashlib.sha1((key + WS_GUID).encode()).digest()).decode()  # SHA-1: lo exige RFC 6455
        resp = ["HTTP/1.1 101 Switching Protocols", "Upgrade: websocket", "Connection: Upgrade", f"Sec-WebSocket-Accept: {accept}"]
        if "obswebsocket.json" in headers.get("sec-websocket-protocol", ""):
            resp.append("Sec-WebSocket-Protocol: obswebsocket.json")
        self.sock.sendall(("\r\n".join(resp) + "\r\n\r\n").encode())

    def serve(self) -> None:
        srv = self.server
        try:
            self.handshake()
            hello: dict[str, Any] = {"obsStudioVersion": "33.0.0", "obsWebSocketVersion": "5.6.0", "rpcVersion": 1}
            if srv.password:
                hello["authentication"] = {"challenge": CHALLENGE, "salt": SALT}
            self.send_json(0, hello)
            while not self.closed:
                opcode, payload = self.recv_frame()
                if opcode == OPCODE_CLOSE:
                    self.send_close(1000)
                    break
                if opcode == OPCODE_PING:
                    self._send_frame(OPCODE_PONG, payload)
                    continue
                if opcode != OPCODE_TEXT:
                    continue
                msg = json.loads(payload.decode("utf-8"))
                op, d = msg.get("op"), msg.get("d") or {}
                if not self.identified:
                    if op != 1:
                        self.send_close(4007, "NotIdentified")
                        break
                    srv.identify_payloads.append(d)
                    if srv.password and d.get("authentication") != auth_string(srv.password, SALT, CHALLENGE):
                        self.send_close(4009, "Authentication failed.")
                        break
                    self.identified = True
                    self.send_json(2, {"negotiatedRpcVersion": 1})
                    continue
                if op != 6:
                    continue
                self._handle_request(d)
        except (ConnectionError, OSError, ValueError):
            pass
        finally:
            self.closed = True
            try:
                self.sock.close()
            except OSError:
                pass

    def _handle_request(self, d: dict[str, Any]) -> None:
        request_type = str(d.get("requestType"))
        data = d.get("requestData") or {}
        self.server.requests.append((request_type, data))
        result = self.server.handler(self, request_type, data)
        if isinstance(result, NoResponse):
            return
        if isinstance(result, CloseNow):
            self.drop()
            return
        response: dict[str, Any] = {"requestType": request_type, "requestId": d.get("requestId")}
        if isinstance(result, Fail):
            response["requestStatus"] = {"result": False, "code": result.code}
            if result.comment:
                response["requestStatus"]["comment"] = result.comment
        else:
            response["requestStatus"] = {"result": True, "code": 100}
            if result:
                response["responseData"] = result
        self.send_json(7, response)


class FakeObsServer:
    def __init__(self, password: str = "", handler: Handler | None = None) -> None:
        self.password = password
        self.handler: Handler = handler or _default_handler
        self.requests: list[tuple[str, dict[str, Any]]] = []
        self.identify_payloads: list[dict[str, Any]] = []
        self.handshake_headers: list[dict[str, str]] = []
        self.connections: list[Connection] = []
        self._sock = socket.socket()
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.listen(4)
        self.port: int = self._sock.getsockname()[1]
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._accept_loop, name="fake-obs", daemon=True)

    def __enter__(self) -> FakeObsServer:
        self._thread.start()
        return self

    def __exit__(self, *exc: object) -> None:
        self.stop()

    def _accept_loop(self) -> None:
        self._sock.settimeout(0.2)
        while not self._stop.is_set():
            try:
                client, _ = self._sock.accept()
            except TimeoutError:
                continue
            except OSError:
                break
            conn = Connection(client, self)
            self.connections.append(conn)
            threading.Thread(target=conn.serve, name="fake-obs-conn", daemon=True).start()

    def stop(self) -> None:
        self._stop.set()
        for conn in self.connections:
            conn.drop()
        try:
            self._sock.close()
        except OSError:
            pass
        self._thread.join(timeout=2.0)

    def wait_requests(self, count: int, timeout: float = 3.0) -> None:
        deadline = time.monotonic() + timeout
        while len(self.requests) < count and time.monotonic() < deadline:
            time.sleep(0.01)
