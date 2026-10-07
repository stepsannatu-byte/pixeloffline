"""Servidor local para el modo offline.

    py -m offline.server

Escucha HTTPS en el puerto 443 de cada IP de loopback del mapa de hosts
(launcher-data/offline-hosts.json), así que sabe qué host original pedía el
juego por la IP a la que llega la conexión. El certificado es autofirmado: el
validador del juego acepta cualquiera.

Por ahora solo registra lo que pide el juego (launcher-data/server-log.jsonl)
y responde 404. Las rutas que ya entiende están en ROUTES.
"""
from __future__ import annotations

import base64
import datetime as _dt
import json
import socket
import ssl
import struct
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from offline.patch import DATA, HOSTS_FILE

CERT = DATA / "server-cert.pem"
KEY = DATA / "server-key.pem"
LOG = DATA / "server-log.jsonl"
OPENSSL_CANDIDATES = ["openssl", r"C:\Program Files\Git\usr\bin\openssl.exe",
                      r"C:\Program Files\Git\mingw64\bin\openssl.exe"]

_log_lock = threading.Lock()


def ensure_cert(hosts: dict[str, str]) -> None:
    """Certificado autofirmado con todas las IPs del mapa como nombres alternativos
    (UnityTls comprueba que el nombre coincida con la IP de la URL)."""
    ips = sorted({addr.partition(":")[0] for addr in hosts.values()} | {"127.0.0.1"})
    san = "subjectAltName=" + ",".join(f"IP:{ip}" for ip in ips)
    stamp = DATA / "server-cert.san"
    if CERT.is_file() and KEY.is_file() and stamp.is_file() and stamp.read_text() == san:
        return
    DATA.mkdir(parents=True, exist_ok=True)
    for exe in OPENSSL_CANDIDATES:
        try:
            subprocess.run([exe, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "3650",
                            "-subj", f"/CN={ips[0]}", "-addext", san,
                            "-keyout", str(KEY), "-out", str(CERT)],
                           check=True, capture_output=True)
            stamp.write_text(san)
            return
        except (OSError, subprocess.CalledProcessError):
            continue
    raise SystemExit("No se encuentra openssl para crear el certificado del servidor local.")


def log_request(entry: dict) -> None:
    line = json.dumps(entry, ensure_ascii=False)
    with _log_lock, LOG.open("a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(f"{entry['time']} {entry['host']} {entry['method']} {entry['path']} -> {entry['status']}")


WS_PORT = 9001  # websocket del backend local (lo anuncia la respuesta de auth)


def _decode_with(u: tuple, shift: int) -> dict[str, str]:
    fields, i = {}, 0
    while i + 1 < len(u):
        nk, nv = u[i] // 2, u[i + 1] // 2
        if i + 2 + nk + nv > len(u):
            break
        text = "".join(chr(max(c - shift, 0)) for c in u[i + 2:i + 2 + nk + nv])
        fields[text[:nk]] = text[nk:].rstrip("\0")
        i += 2 + nk + nv
    return fields


def decode_fields(body: bytes, known: str = "version") -> tuple[dict[str, str], int]:
    """Cuerpo binario de /auth_v2/: UTF-16LE. Cada campo es
    [long. clave][long. valor][clave][valor], longitudes en bytes sin desplazar y
    cada carácter desplazado una cantidad que cambia en cada petición (sale de
    id_seed). Se prueba cada desplazamiento hasta que aparece una clave conocida.
    Devuelve (campos, desplazamiento)."""
    u = struct.unpack(f"<{len(body) // 2}H", body[:len(body) // 2 * 2])
    for shift in range(65536):
        fields = _decode_with(u, shift)
        if known in fields:
            return fields, shift
    return {}, 0


def encode_fields(fields: dict[str, str], shift: int) -> bytes:
    """Inverso de decode_fields. El último valor lleva un carácter 0 al final, como en las peticiones."""
    out: list[int] = []
    items = list(fields.items())
    for n, (key, value) in enumerate(items):
        value = str(value) + ("\0" if n == len(items) - 1 else "")
        out += [2 * len(key), 2 * len(value)]
        out += [(ord(c) + shift) & 0xFFFF for c in key + value]
    return struct.pack(f"<{len(out)}H", *out)


def auth_v2(handler, body: bytes):
    fields, shift = decode_fields(body)
    ticket = bytes.fromhex(fields.get("steam_ticket", "")).rstrip(b"\0").decode("utf-8", "replace")
    print(f"auth_v2: shift={shift} ticket={ticket!r} uniq_id={fields.get('uniq_id')}")
    now = int(_dt.datetime.now().timestamp())
    reply = {
        "url": f"ws://127.0.0.1:{WS_PORT}",
        "token": "offline-token",
        "hash": fields.get("hash", ""),
        "player_id": fields.get("uniq_id") or "1",
        "server_time": now,
        "check_version": 0,
        "end_time": now + 86400,
    }
    return 200, encode_fields({k: str(v) for k, v in reply.items()}, shift), "application/octet-stream"


# Cada ruta: (host original, método, ruta sin query) -> función(handler, body) -> (status, bytes, tipo)
ROUTES: dict[tuple[str, str, str], callable] = {
    ("server-v2.pixelgun3dserver.com", "POST", "/auth_v2/"): auth_v2,
}


class Server(ThreadingHTTPServer):
    """HTTP y HTTPS en el mismo puerto: si el primer byte es un saludo TLS, se cifra."""
    daemon_threads = True
    tls: ssl.SSLContext | None = None

    def server_bind(self) -> None:
        # HTTPServer.server_bind hace un DNS inverso (getfqdn): lento e inútil aquí.
        self.socket.bind(self.server_address)
        self.server_address = self.socket.getsockname()
        self.server_name, self.server_port = self.server_address[:2]

    def finish_request(self, request, client_address) -> None:
        try:
            first = request.recv(1, socket.MSG_PEEK)
            if first == b"\x16" and self.tls:
                request = self.tls.wrap_socket(request, server_side=True)
        except (OSError, ssl.SSLError):
            return
        super().finish_request(request, client_address)


def make_handler(host: str):
    class Handler(BaseHTTPRequestHandler):
        server_version = "pg3d-offline"
        protocol_version = "HTTP/1.1"

        def _handle(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else b""
            path = urlsplit(self.path).path
            route = ROUTES.get((host, self.command, path))
            if route:
                status, data, ctype = route(self, body)
            else:
                status, data, ctype = 404, b'{"error":"not implemented offline"}', "application/json"
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)
            log_request({
                "time": _dt.datetime.now().isoformat(timespec="seconds"),
                "host": host, "method": self.command, "path": self.path,
                "headers": dict(self.headers), "status": status,
                "body": body.decode("utf-8", "replace")[:20000],
                "body_b64": base64.b64encode(body[:200000]).decode(),
            })

        do_GET = do_POST = do_PUT = do_DELETE = do_PATCH = _handle

        def log_message(self, fmt, *args) -> None:  # el registro propio ya lo cubre
            pass

    return Handler


def main() -> int:
    hosts = json.loads(HOSTS_FILE.read_text(encoding="utf-8")) if HOSTS_FILE.is_file() else {}
    if not hosts:
        print("No hay mapa de hosts: pon antes la copia en modo offline.")
        return 1
    ensure_cert(hosts)
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    ctx.load_cert_chain(CERT, KEY)
    servers = []
    for host, addr in hosts.items():
        ip, _, port = addr.partition(":")
        try:
            srv = Server((ip, int(port or 443)), make_handler(host))
        except OSError as e:
            print(f"No se pudo escuchar en {addr} ({host}): {e}")
            continue
        srv.tls = ctx
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        servers.append(srv)
    print(f"Servidor local escuchando en {len(servers)} puertos. Registro: {LOG}")
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
