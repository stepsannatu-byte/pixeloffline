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


_names: dict | None = None


def names(dump: Path) -> dict[int, str]:
    """RVA -> nombre legible: métodos, literales, tipos y métodos referenciados por metadata."""
    global _names
    if _names is None:
        script = json.loads((dump / "script.json").read_text(encoding="utf-8"))
        _names = {}
        for m in script["ScriptMethod"]:
            _names.setdefault(m["Address"], m["Name"])
        for s in script["ScriptString"]:
            _names[s["Address"]] = "str " + repr(s["Value"])[:80]
        for m in script.get("ScriptMetadata", []):
            _names[m["Address"]] = "meta " + m["Name"]
        for m in script.get("ScriptMetadataMethod", []):
            _names[m["Address"]] = "metamethod " + m["Name"]
    return _names


def disasm(dump: Path, idx: dict, rva: int, limit: int = 4000) -> None:
    import capstone

    data = DLL.read_bytes()
    addrs = [a for a, _ in idx["methods"]]
    i = bisect.bisect_right(addrs, rva)
    end = addrs[i] if i < len(addrs) else rva + 0x2000
    for name, va, vsize, raw, rsize, execu in sections(data):
        if va <= rva < va + vsize:
            code = data[raw + rva - va: raw + end - va]
            break
    else:
        raise SystemExit("RVA fuera de las secciones")
    md = capstone.Cs(capstone.CS_ARCH_X86, capstone.CS_MODE_64)
    nm = names(dump)
    for n, ins in enumerate(md.disasm(code, rva)):
        if n >= limit:
            break
        note = ""
        for op in ins.operands if False else []:
            pass
        if ins.mnemonic in ("call", "jmp") and ins.op_str.startswith("0x"):
            t = int(ins.op_str, 16)
            note = nm.get(t, "")
        elif "rip +" in ins.op_str or "rip -" in ins.op_str:
            m = re.search(r"rip ([+-]) (0x[0-9a-f]+)", ins.op_str)
            t = ins.address + ins.size + (int(m.group(2), 16) * (1 if m.group(1) == "+" else -1))
            note = nm.get(t, f"[0x{t:X}]")
        print(f"{ins.address:08X}  {ins.mnemonic:6} {ins.op_str:45} {('; ' + note) if note else ''}")


def main(argv: list[str]) -> int:
    if len(argv) < 3:
        print(__doc__)
        return 2
    sys.stdout.reconfigure(encoding="utf-8")
    dump = Path(argv[0])
    idx = build_index(dump)
    if argv[1] == "str":
        for rva, name in users_of(idx, argv[2]):
            print(f"0x{rva:X}  {name}")
    elif argv[1] == "method":
        for s in strings_of(idx, int(argv[2], 16)):
            print(repr(s))
    elif argv[1] == "dis":
        disasm(dump, idx, int(argv[2], 16))
    elif argv[1] == "callers":
        target = int(argv[2], 16)
        data = DLL.read_bytes()
        for name, va, vsize, raw, rsize, execu in sections(data):
            if not execu:
                continue
            blob = data[raw:raw + rsize]
            for m in re.finditer(rb"[\xe8\xe9]", blob):
                off = m.start()
                if va + off + 5 + struct.unpack_from("<i", blob, off + 1)[0] == target:
                    print(f"0x{va + off:X}  {method_at(idx, va + off)[1]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
