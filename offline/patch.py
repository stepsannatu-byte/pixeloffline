"""Modo offline: desconecta la copia del juego de todos los servidores externos.

    py -m offline.patch status
    py -m offline.patch plan       (qué hosts se redirigen y a qué IP)
    py -m offline.patch apply      (pone la copia en modo offline)
    py -m offline.patch restore    (devuelve los archivos originales)

Cada host externo que el juego contacta por su cuenta (backend, contenido,
telemetría, pagos, cuentas, multijugador, Unity Cloud y Firebase) pasa a
127.0.0.1 con un puerto propio (8001, 8002...). El servidor local sabe qué host
original se pedía por el puerto (launcher-data/offline-hosts.json). Los esquemas
https:// y wss:// de la metadata pasan a http:// y ws://: UnityTls no confía en
un certificado local y Unity solo permite HTTP sin TLS contra 127.0.0.1.

Archivos que se cambian, cada uno con el método que admite su formato:
  * global-metadata.dat   literales de C#: se acortan y se ajusta su longitud.
  * globalgamemanagers    URLs de Unity Cloud en cadenas serializadas: misma
                          longitud, rellenando la ruta con '/'.
  * Firebase*.dll         cadenas de C: misma longitud, rellenando con NUL.
  * JSON de StreamingAssets  texto: sustitución directa.
  * steam_api64.dll       se sustituye por el stub de steam_stub/ (sin Steam).

Antes de tocar nada guarda los originales en launcher-data/originals/, indexados
por hash, y comprueba ese hash al restaurar. Se niega a trabajar con el juego
abierto o si los archivos no coinciden con la build registrada por el launcher.
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import struct
import subprocess
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
GAME = BASE.parent
DATA = BASE / "launcher-data"
ORIGINALS = DATA / "originals"
STATE = DATA / "offline-state.json"
HOSTS_FILE = DATA / "offline-hosts.json"
BASELINE = DATA / "baseline.json"

GAME_DATA = "Pixel Gun 3D_Data"
PLUGINS = f"{GAME_DATA}/Plugins/x86_64"
METADATA = f"{GAME_DATA}/il2cpp_data/Metadata/global-metadata.dat"
STEAM_API = f"{PLUGINS}/steam_api64.dll"
STUB = BASE / "steam_stub" / "steam_api64.dll"
STUB_INI = BASE / "steam_stub" / "steam_stub.ini"
FIRST_PORT = 8001  # el host n del mapa escucha en 127.0.0.1:FIRST_PORT+n

# (ruta relativa al juego, método). Los métodos están en PATCHERS.
FILES = [
    (METADATA, "metadata"),
    (f"{GAME_DATA}/globalgamemanagers", "serialized"),
    (f"{PLUGINS}/FirebaseCppApp-12_10_1.dll", "cstring"),
    (f"{PLUGINS}/FirebaseCppRemoteConfig.dll", "cstring"),
    (f"{GAME_DATA}/StreamingAssets/aa/settings.json", "text"),
    (f"{GAME_DATA}/StreamingAssets/aa/catalog.json", "text"),
    (f"{GAME_DATA}/StreamingAssets/google-services-desktop.json", "text"),
]

# Dominios que el juego o sus bibliotecas contactan por su cuenta. Los enlaces
# que solo se abren en el navegador (web, redes sociales, documentación) se
# quedan como están.
BACKEND_DOMAINS = [
    # Pixel Gun Team
    "pixelgun3dserver.com", "pixelgunserver.com", "cubicgames.com", "cginfra.org",
    "bloxelarena.com", "lightmap.com", "script.google.com",
    # terceros: telemetría, pagos, anuncios, multijugador
    "appsflyer.com", "xsolla.com", "exitgames.com", "exitgamescloud.com",
    "revenueuniverse.com", "connect.facebook.net",
    # Unity Cloud
    "cloud.unity3d.com", "engine-data.unity3d.com", "services.api.unity.com",
    "collect.analytics.unity3d.com",
    # Google / Firebase
    "googleapis.com", "firebaseio.com", "app-measurement.com", "mtalk.google.com",
    "android.clients.google.com",
]
# Subdominios de pixelgun3d.com que son servicios (no páginas web).
PIXELGUN3D_SERVICES = ["cdn.pixelgun3d.com", "cfg.pixelgun3d.com", "shop.pixelgun3d.com"]
# Nombres con forma de host que no se contactan (identificadores de tipos protobuf).
NOT_HOSTS = ["type.googleapis.com"]

HOST_RE = re.compile(rb"(?<![A-Za-z0-9.-])((?:[a-z0-9-]+\.)+[a-z]{2,})(?![A-Za-z0-9-])", re.I)
# Una URL o un host suelto dentro de un binario: hasta el primer byte no imprimible.
TOKEN_RE = re.compile(rb"(?:https?://|wss?://)?(?<![A-Za-z0-9.-])((?:[a-z0-9-]+\.)+[a-z]{2,})"
                      rb"(?![A-Za-z0-9-])[!-~]*", re.I)


def is_backend(host: str) -> bool:
    host = host.lower()
    if host in NOT_HOSTS:
        return False
    if host in PIXELGUN3D_SERVICES:
        return True
    return any(host == d or host.endswith("." + d) for d in BACKEND_DOMAINS)


def hosts_in(data: bytes) -> set[str]:
    return {h for h in (m.decode("ascii", "replace").lower() for m in HOST_RE.findall(data))
            if is_backend(h)}


# ------------------------------------------------------------------ metadata

class Metadata:
    """Tabla de literales de global-metadata.dat (versiones 29 y 31)."""

    def __init__(self, data: bytearray):
        sanity, version, self.lit_off, lit_size, self.data_off, self.data_size = \
            struct.unpack_from("<IiIiIi", data, 0)
        if sanity != 0xFAB11BAF:
            raise ValueError("global-metadata.dat no reconocido (¿cifrado?)")
        if version not in (29, 31):
            raise ValueError(f"versión de metadata {version} no probada")
        self.data = data
        self.count = lit_size // 8

    def literal(self, i: int) -> tuple[int, int]:
        """Devuelve (longitud, posición absoluta) del literal i."""
        length, index = struct.unpack_from("<Ii", self.data, self.lit_off + 8 * i)
        return length, self.data_off + index

    def get(self, i: int) -> bytes:
        length, pos = self.literal(i)
        return bytes(self.data[pos:pos + length])

    def set(self, i: int, value: bytes) -> None:
        length, pos = self.literal(i)
        if len(value) > length:
            raise ValueError("solo se pueden acortar literales")
        self.data[pos:pos + length] = value + b"\0" * (length - len(value))
        struct.pack_into("<I", self.data, self.lit_off + 8 * i, len(value))

    def literals(self):
        return (self.get(i) for i in range(self.count))


# ------------------------------------------------------------- sustituciones

def _sub_hosts(data: bytes, hosts: dict[str, str]) -> bytes:
    def sub(m: re.Match) -> bytes:
        ip = hosts.get(m.group(1).decode("ascii", "replace").lower())
        return ip.encode() if ip else m.group(1)
    return HOST_RE.sub(sub, data)


# El servidor local no puede presentar un certificado en el que confíe UnityTls
# (haría falta instalar una CA en Windows), así que el juego le habla en claro.
# Todo lo que usaba TLS apunta ya a loopback, de modo que nada sale sin cifrar.
SCHEME_LITERALS = {b"https": b"http", b"https://": b"http://", b"wss": b"ws", b"wss://": b"ws://",
                   b"wss://{0}:{1}": b"ws://{0}:{1}"}


def _plain_schemes(lit: bytes) -> bytes:
    if lit in SCHEME_LITERALS:
        return SCHEME_LITERALS[lit]
    return lit.replace(b"https://127.0.0.1", b"http://127.0.0.1").replace(b"wss://127.0.0.1", b"ws://127.0.0.1")


def patch_metadata(data: bytes, hosts: dict[str, str], log: list) -> bytes:
    meta = Metadata(bytearray(data))
    for i in range(meta.count):
        old = meta.get(i)
        new = _plain_schemes(_sub_hosts(old, hosts))
        if new != old:
            meta.set(i, new)
            log.append((old, new))
    return bytes(meta.data)


def _replace_same_length(old: bytes, hosts: dict[str, str], pad: bytes, log: list) -> bytes:
    new = _sub_hosts(old, hosts)
    if new == old:
        return old
    if len(new) > len(old):
        raise ValueError(f"la IP no cabe en {old!r}")
    new += pad * (len(old) - len(new))
    log.append((old, new))
    return new


def patch_cstring(data: bytes, hosts: dict[str, str], log: list) -> bytes:
    """Cadenas de C: el token llega hasta el NUL, y se rellena con NUL."""
    return TOKEN_RE.sub(lambda m: _replace_same_length(m.group(0), hosts, b"\0", log), data)


def patch_serialized(data: bytes, hosts: dict[str, str], log: list) -> bytes:
    """Cadenas serializadas de Unity: int32 de longitud + texto. Se respeta esa
    longitud exacta y se rellena con '/', que solo alarga la ruta de la URL."""
    out = bytearray(data)
    for m in HOST_RE.finditer(data):
        if not is_backend(m.group(1).decode("ascii", "replace")):
            continue
        start = m.start()
        while start > 4 and 0x20 <= data[start - 1] < 0x7F:
            start -= 1
        # el prefijo de longitud puede tener bytes imprimibles: probar hacia delante
        for s in range(start, m.start() + 1):
            length = struct.unpack_from("<I", data, s - 4)[0]
            if s + length >= m.end() and length < 4096 and \
                    all(0x20 <= b < 0x7F for b in data[s:s + length]):
                break
        else:
            raise ValueError(f"no se encuentra la cadena serializada de {m.group(1)!r}")
        out[s:s + length] = _replace_same_length(bytes(out[s:s + length]), hosts, b"/", log)
    return bytes(out)


def patch_text(data: bytes, hosts: dict[str, str], log: list) -> bytes:
    new = _sub_hosts(data, hosts)
    if new != data:
        log.append((b"(texto)", f"{len(hosts_in(data))} hosts".encode()))
    return new


PATCHERS = {
    "metadata": patch_metadata,
    "serialized": patch_serialized,
    "cstring": patch_cstring,
    "text": patch_text,
}


def plan_hosts() -> dict[str, str]:
    """Asigna a cada host externo una IP de loopback fija (orden alfabético).

    Se calcula siempre sobre los archivos originales, así que el reparto es
    estable entre aplicaciones mientras no cambie la build.
    """
    hosts: set[str] = set()
    for rel, method in FILES:
        data = original_bytes(rel)
        if method == "metadata":
            for lit in Metadata(bytearray(data)).literals():
                hosts |= hosts_in(lit)
        else:
            hosts |= hosts_in(data)
    # Todo a 127.0.0.1, un puerto por host: Unity solo deja usar http:// sin TLS
    # contra localhost/127.0.0.1 ("Insecure connection not allowed" con otras IPs).
    return {h: f"127.0.0.1:{FIRST_PORT + n}" for n, h in enumerate(sorted(hosts))}


# ------------------------------------------------------------------ archivos

def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _write_file(rel: str, data: bytes) -> None:
    tmp = GAME / (rel + ".tmp")
    tmp.write_bytes(data)
    tmp.replace(GAME / rel)


def game_running() -> bool:
    if sys.platform != "win32":
        return False
    out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq Pixel Gun 3D.exe", "/NH"],
                         capture_output=True, text=True, errors="replace").stdout
    return "Pixel Gun 3D.exe" in out


def status() -> dict:
    return _read_json(STATE, {"mode": "official", "files": []})


def original_bytes(rel: str) -> bytes:
    """Contenido original de un archivo, aunque la copia esté en modo offline."""
    for f in status()["files"]:
        if f["path"] == rel:
            return (ORIGINALS / f["sha256"]).read_bytes()
    return (GAME / rel).read_bytes()


def check_unmodified(rels: list[str]) -> str | None:
    """Evita guardar como "original" un archivo ya parcheado."""
    base = _read_json(BASELINE, {}).get("files", {})
    for rel in rels:
        if rel in base and base[rel] and sha256(GAME / rel) != base[rel]:
            return (f"{rel} no coincide con la build registrada. Si el juego se ha actualizado, "
                    "acepta la build nueva en el launcher antes de pasar a offline.")
    return None


def apply() -> str:
    if game_running():
        return "Cierra el juego antes de cambiar de modo."
    if status()["mode"] == "offline":
        return "La copia ya está en modo offline."
    if not STUB.is_file():
        return "Falta steam_stub/steam_api64.dll: ejecuta py steam_stub/build.py."
    rels = [rel for rel, _ in FILES if (GAME / rel).is_file()] + [STEAM_API]
    err = check_unmodified(rels)
    if err:
        return err

    hosts = plan_hosts()
    patched, files, log = {}, [], {}
    for rel, method in FILES:
        if not (GAME / rel).is_file():
            continue
        data = (GAME / rel).read_bytes()
        changes: list = []
        new = PATCHERS[method](data, hosts, changes)
        if new != data:
            patched[rel] = new
            log[rel] = [(o.decode("utf-8", "replace"), n.decode("utf-8", "replace").rstrip("\0"))
                        for o, n in changes]
    patched[STEAM_API] = STUB.read_bytes()

    # Primero se guardan todos los originales; después se escribe.
    ORIGINALS.mkdir(parents=True, exist_ok=True)
    for rel, new in patched.items():
        data = (GAME / rel).read_bytes()
        digest = sha256_bytes(data)
        if not (ORIGINALS / digest).exists():
            (ORIGINALS / digest).write_bytes(data)
        files.append({"path": rel, "sha256": digest, "patched_sha256": sha256_bytes(new)})
    _write_json(STATE, {"mode": "applying", "files": files})
    for rel, new in patched.items():
        _write_file(rel, new)
    ini = STUB_INI if STUB_INI.is_file() else BASE / "steam_stub" / "steam_stub.ini.example"
    shutil.copy2(ini, GAME / PLUGINS / "steam_stub.ini")

    _write_json(HOSTS_FILE, hosts)
    _write_json(DATA / "offline-changes.json", log)
    _write_json(STATE, {"mode": "offline", "files": files})
    n = sum(len(v) for v in log.values())
    return (f"Modo offline activado: {len(hosts)} hosts redirigidos ({n} cambios en "
            f"{len(log)} archivos) y steam_api64.dll sustituida por el stub.")


def restore() -> str:
    if game_running():
        return "Cierra el juego antes de cambiar de modo."
    st = status()
    if st["mode"] == "official":
        return "La copia ya está en modo oficial."
    for f in st["files"]:
        src = ORIGINALS / f["sha256"]
        if not src.is_file() or sha256(src) != f["sha256"]:
            return f"Falta o está dañada la copia original de {f['path']}. No se ha restaurado nada."
    for f in st["files"]:
        _write_file(f["path"], (ORIGINALS / f["sha256"]).read_bytes())
    (GAME / PLUGINS / "steam_stub.ini").unlink(missing_ok=True)
    _write_json(STATE, {"mode": "official", "files": []})
    return "Archivos originales restaurados: la copia vuelve al modo oficial."


def main(argv: list[str]) -> int:
    cmd = argv[0] if argv else "status"
    if cmd == "apply":
        print(apply())
    elif cmd == "restore":
        print(restore())
    elif cmd == "status":
        print(json.dumps(status(), indent=2, ensure_ascii=False))
    elif cmd == "plan":
        for h, ip in plan_hosts().items():
            print(f"{ip:12} {h}")
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
