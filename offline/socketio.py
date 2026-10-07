"""Servidor Socket.IO mínimo (Engine.IO v4 sobre websocket) para el backend local.

El juego (BestHTTP.SocketIO, en Rilisoft.WebSocket.WebSocketManager) se conecta a
la `url` de la respuesta de /auth_v2/ con ?EIO=4&transport=websocket y usa el
namespace "/sio". Aquí se implementa justo lo necesario de cada capa:

  websocket   handshake RFC 6455, tramas de texto/binarias, ping y cierre.
  Engine.IO   paquete open (0), ping (2) / pong (3), message (4).
  Socket.IO   connect (0), event (2), ack (3) y binarios (5/6) en el namespace.

Los eventos que llegan se registran en launcher-data/socketio-log.jsonl. Los que
ya sabemos contestar están en EVENTS.
"""
from __future__ import annotations

import base64
import datetime as _dt
import hashlib
import json
import socket
import struct
import threading
import uuid

from offline.patch import DATA

LOG = DATA / "socketio-log.jsonl"
GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
NAMESPACE = "/sio"
PING_INTERVAL = 25000
PING_TIMEOUT = 20000

_log_lock = threading.Lock()

# evento -> función(conn, args) -> lista de argumentos del ack (o None si no hay ack)
EVENTS: dict[str, callable] = {}


def log(entry: dict) -> None:
    entry = {"time": _dt.datetime.now().isoformat(timespec="seconds"), **entry}
    with _log_lock, LOG.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    text = json.dumps(entry, ensure_ascii=False)
    print("sio", text[:300])


# --------------------------------------------------------------- websocket

class WebSocket:
    def __init__(self, sock: socket.socket):
        self.sock = sock
        self.lock = threading.Lock()

    def _recv_exact(self, n: int) -> bytes:
        buf = b""
        while len(buf) < n:
            chunk = self.sock.recv(n - len(buf))
            if not chunk:
                raise ConnectionError("websocket cerrado")
            buf += chunk
        return buf

    def recv(self) -> tuple[int, bytes]:
        """Devuelve (opcode, datos) de un mensaje completo."""
        data, first_op = b"", None
        while True:
            b1, b2 = self._recv_exact(2)
            fin, op = b1 & 0x80, b1 & 0x0F
            n = b2 & 0x7F
            if n == 126:
                n = struct.unpack(">H", self._recv_exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._recv_exact(8))[0]
            mask = self._recv_exact(4) if b2 & 0x80 else b"\0\0\0\0"
            payload = bytes(c ^ mask[i % 4] for i, c in enumerate(self._recv_exact(n)))
            if op >= 8:  # control: se responde aquí y se sigue leyendo
                if op == 8:
                    raise ConnectionError("cierre del cliente")
                if op == 9:
                    self.send(payload, 10)
                continue
            if first_op is None:
                first_op = op
            data += payload
            if fin:
                return first_op, data

    def send(self, data: bytes | str, op: int | None = None) -> None:
        if isinstance(data, str):
            data, op = data.encode(), op or 1
        op = op or 2
        n = len(data)
        head = bytes([0x80 | op])
        if n < 126:
            head += bytes([n])
        elif n < 65536:
            head += bytes([126]) + struct.pack(">H", n)
        else:
            head += bytes([127]) + struct.pack(">Q", n)
        with self.lock:
            self.sock.sendall(head + data)


def accept_key(key: str) -> str:
    return base64.b64encode(hashlib.sha1((key + GUID).encode()).digest()).decode()


# ------------------------------------------------------- Engine/Socket.IO

class Connection:
    def __init__(self, ws: WebSocket, query: str):
        self.ws = ws
        self.query = query
        self.sid = uuid.uuid4().hex[:20]
        self.alive = True
        self.pending_binary: tuple[str, list, int] | None = None

    # -- envío
    def emit(self, event: str, *args) -> None:
        self.ws.send("42" + NAMESPACE + "," + json.dumps([event, *args], separators=(",", ":")))
        log({"dir": "out", "event": event, "args": args})

    def ack(self, ack_id: int, args: list) -> None:
        self.ws.send(f"43{NAMESPACE},{ack_id}" + json.dumps(args, separators=(",", ":")))
        log({"dir": "out", "ack": ack_id, "args": args})

    # -- recepción
    def handle_text(self, text: str) -> None:
        kind, rest = text[:1], text[1:]
        if kind == "2":    # ping de Engine.IO
            self.ws.send("3" + rest)
        elif kind == "3":  # pong
            pass
        elif kind == "4":
            self.handle_socketio(rest)
        elif kind == "1":
            self.alive = False
        else:
            log({"dir": "in", "engineio": text[:2000]})

    def handle_socketio(self, packet: str) -> None:
        ptype, body = packet[:1], packet[1:]
        nsp = "/"
        if body.startswith("/"):
            nsp, _, body = body.partition(",")
        if ptype == "0":  # connect
            auth = json.loads(body) if body else None
            log({"dir": "in", "connect": nsp, "auth": auth, "query": self.query})
            self.ws.send(f"40{nsp}," + json.dumps({"sid": self.sid}))
            return
        if ptype == "1":
            log({"dir": "in", "disconnect": nsp})
            return
        if ptype in "56":  # evento/ack binario: llegan adjuntos aparte
            count, _, body = body.partition("-")
            self.pending_binary = (ptype, body, int(count))
            log({"dir": "in", "binary_header": packet[:2000]})
            return
        ack_id = ""
        while body[:1].isdigit():
            ack_id, body = ack_id + body[0], body[1:]
        try:
            args = json.loads(body) if body else []
        except ValueError:
            args = [body]
        if ptype == "2":
            event, params = (args[0], args[1:]) if args else ("?", [])
            handler = EVENTS.get(event)
            log({"dir": "in", "event": event, "ack": ack_id or None, "args": params,
                 "handled": bool(handler)})
            if handler:
                reply = handler(self, params)
                if ack_id and reply is not None:
                    self.ack(int(ack_id), reply)
        elif ptype == "3":
            log({"dir": "in", "ack_reply": ack_id, "args": args})
        else:
            log({"dir": "in", "socketio": packet[:2000]})

    def handle_binary(self, data: bytes) -> None:
        log({"dir": "in", "binary_attachment_b64": base64.b64encode(data[:100000]).decode(),
             "size": len(data)})


def serve(sock: socket.socket, query: str) -> None:
    """Atiende una conexión ya actualizada a websocket hasta que se cierre."""
    ws = WebSocket(sock)
    conn = Connection(ws, query)
    log({"dir": "in", "open": query})
    ws.send("0" + json.dumps({"sid": conn.sid, "upgrades": [], "pingInterval": PING_INTERVAL,
                              "pingTimeout": PING_TIMEOUT, "maxPayload": 10_000_000}))
    # El cliente es el BestHTTP.SocketIO antiguo (protocolo Socket.IO v2): espera que
    # el servidor confirme solo la conexión al namespace raíz antes de abrir "/sio".
    ws.send("40")

    def pinger():
        while conn.alive:
            threading.Event().wait(PING_INTERVAL / 1000)
            try:
                ws.send("2")
            except OSError:
                return

    threading.Thread(target=pinger, daemon=True).start()
    try:
        while conn.alive:
            op, data = ws.recv()
            if op == 1:
                conn.handle_text(data.decode("utf-8", "replace"))
            else:
                conn.handle_binary(data)
    except (ConnectionError, OSError):
        pass
    finally:
        conn.alive = False
        log({"dir": "in", "closed": conn.sid})
