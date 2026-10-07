"""Genera y compila la steam_api64.dll falsa.

    py build.py            -> steam_api64.dll en esta carpeta

Necesita Zig como compilador de C (py -m pip install --user ziglang).

exports.txt   nombres que exporta la steam_api64.dll real (SDK de Steamworks).
signatures.tsv  nombre nativo y tipo de retorno según Steamworks.NET, la capa
              que usa el juego. Sirve para devolver lo correcto por defecto.
stub_core.c   funciones con comportamiento propio (arranque, ticket, callbacks).
stub_gen.c    se genera aquí: el resto de exportaciones, que devuelven 0.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

# Structs devueltos por valor que no caben en un registro: el llamador pasa un
# puntero oculto y hay que devolverlo relleno. Tamaño en bytes según el SDK.
BIG_STRUCTS = {"SteamIPAddress_t": 20, "InputAnalogActionData_t": 16, "InputMotionData_t": 40}


def generate() -> Path:
    exports = [l.strip() for l in (HERE / "exports.txt").read_text().splitlines() if l.strip()]
    sigs = dict(l.split("\t") for l in (HERE / "signatures.tsv").read_text().splitlines() if l.strip())
    core = (HERE / "stub_core.c").read_text(encoding="utf-8")
    done = set(re.findall(r"STUB_EXPORT[^(]*?\b(\w+)\(", core))

    out = ["/* Generado por build.py. No editar a mano. */", '#include "stub.h"', ""]
    for size in sorted(set(BIG_STRUCTS.values())):
        out.append(f"typedef struct {{ uint8_t b[{size}]; }} Ret{size};")
    out.append("")
    for name in exports:
        if name in done:
            continue
        ret = sigs.get(name, "")
        seen = f'static volatile LONG f; stub_seen(&f, "{name}");'
        if ret == "IntPtr":
            out.append(f"STUB_EXPORT void *{name}(void) {{ {seen} return g_zero; }}")
        elif ret in ("float", "double"):
            out.append(f"STUB_EXPORT {ret} {name}(void) {{ {seen} return 0; }}")
        elif ret in BIG_STRUCTS:
            n = BIG_STRUCTS[ret]
            out.append(f"STUB_EXPORT Ret{n} {name}(void) {{ {seen} Ret{n} r = {{0}}; return r; }}")
        else:
            out.append(f"STUB_EXPORT uint64_t {name}(void) {{ {seen} return 0; }}")
    path = HERE / "stub_gen.c"
    path.write_text("\n".join(out) + "\n", encoding="utf-8")
    print(f"{len(exports)} exportaciones: {len(done)} propias, {len(exports) - len(done)} generadas")
    return path


def compile_dll() -> int:
    cmd = [sys.executable, "-m", "ziglang", "cc", "-shared", "-O2", "-target", "x86_64-windows-gnu",
           "-Wall", "-Wno-unused-parameter", "-o", str(HERE / "steam_api64.dll"),
           str(HERE / "stub_core.c"), str(HERE / "stub_gen.c")]
    return subprocess.call(cmd, cwd=HERE)


if __name__ == "__main__":
    generate()
    sys.exit(compile_dll())
