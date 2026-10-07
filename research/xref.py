"""Referencias cruzadas en GameAssembly.dll sin desensamblador.

    py research/xref.py <dump_dir> str "<literal exacto>"   -> métodos que usan ese texto
    py research/xref.py <dump_dir> method <rva hex>         -> textos que usa ese método

<dump_dir> es la salida de Il2CppDumper (script.json). Busca cargas relativas a
RIP (mov/lea reg, [rip+disp32]) hacia las ranuras de literales de IL2CPP.
La primera vez indexa el binario y guarda la caché junto a script.json.
"""
from __future__ import annotations

import bisect
import json
import pickle
import re
import struct
import sys
from pathlib import Path

GAME = Path(__file__).resolve().parent.parent.parent
DLL = GAME / "GameAssembly.dll"
LOAD_RE = re.compile(rb"[\x48\x4c][\x8b\x8d][\x05\x0d\x15\x1d\x25\x2d\x35\x3d]", re.S)


def sections(data: bytes):
    pe = struct.unpack_from("<I", data, 0x3C)[0]
    n = struct.unpack_from("<H", data, pe + 6)[0]
    opt = pe + 24
    so = struct.unpack_from("<H", data, pe + 20)[0]
    for i in range(n):
        name, vsize, va, rsize, raw = struct.unpack_from("<8sIIII", data, opt + so + 40 * i)
        chars = struct.unpack_from("<I", data, opt + so + 40 * i + 36)[0]
        yield name.rstrip(b"\0").decode(), va, vsize, raw, rsize, bool(chars & 0x20000000)


def build_index(dump: Path) -> dict:
    cache = dump / "xref-cache.pickle"
    if cache.is_file():
        return pickle.loads(cache.read_bytes())
    data = DLL.read_bytes()
    refs: dict[int, list[int]] = {}
    for name, va, vsize, raw, rsize, execu in sections(data):
        if not execu:
            continue
        blob = data[raw:raw + rsize]
        for m in LOAD_RE.finditer(blob):
            off = m.start()
            disp = struct.unpack_from("<i", blob, off + 3)[0]
            rva = va + off
            refs.setdefault(rva + 7 + disp, []).append(rva)
    script = json.loads((dump / "script.json").read_text(encoding="utf-8"))
    methods = sorted((m["Address"], m["Name"]) for m in script["ScriptMethod"])
    strings = {}
    for s in script["ScriptString"]:
        strings.setdefault(s["Value"], []).append(s["Address"])
    slot_to_str = {a: v for v, addrs in strings.items() for a in addrs}
    idx = {"refs": refs, "methods": methods, "strings": strings, "slot_to_str": slot_to_str}
    cache.write_bytes(pickle.dumps(idx))
    return idx


def method_at(idx: dict, rva: int) -> tuple[int, str]:
    addrs = [a for a, _ in idx["methods"]]
    i = bisect.bisect_right(addrs, rva) - 1
    return idx["methods"][i] if i >= 0 else (0, "?")


def users_of(idx: dict, literal: str) -> list[tuple[int, str]]:
    out = set()
    for slot in idx["strings"].get(literal, []):
        for rva in idx["refs"].get(slot, []):
            out.add(method_at(idx, rva))
    return sorted(out)


def strings_of(idx: dict, method_rva: int) -> list[str]:
    addrs = [a for a, _ in idx["methods"]]
    i = bisect.bisect_left(addrs, method_rva)
    end = addrs[i + 1] if i + 1 < len(addrs) else method_rva + 0x10000
    found = []
    for slot, value in idx["slot_to_str"].items():
        for rva in idx["refs"].get(slot, []):
            if method_rva <= rva < end:
                found.append((rva, value))
    return [v for _, v in sorted(found)]


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    idx = build_index(Path(argv[0]))
    if argv[1] == "str":
        for rva, name in users_of(idx, argv[2]):
            print(f"0x{rva:X}  {name}")
    elif argv[1] == "method":
        for s in strings_of(idx, int(argv[2], 16)):
            print(repr(s))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
