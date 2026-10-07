"""PG3D Launcher v0 — capa de legado + capa de contenido sobre PGAssetTool.

Qué hace:
  * Registra la build del juego (hashes de los archivos clave) y avisa si una
    actualización la cambia.
  * Instala, activa, desactiva y quita packs .pgmod usando PGAssetTool
    (https://github.com/mof-22/PGAssetTool), que guarda copia de cada bundle
    antes de tocarlo.
  * Tras una actualización, reaplica los mods activos.
  * Lanza el juego.

  * Modo offline: desconecta la copia de todos los servidores externos y de
    Steam (offline/patch.py), y la devuelve intacta al pasar a modo oficial.

Qué NO hace (todavía): servidor local. Sin él, el modo offline arranca el
juego pero se queda "sin conexión".

Uso: coloca este archivo junto a pgassettool.exe y ejecuta
    py pg3d_launcher.py
Los packs .pgmod se dejan en la carpeta "packs" junto al launcher.
Sin dependencias: solo la biblioteca estándar de Python 3.10+.
"""
from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import subprocess
import sys
import threading
from pathlib import Path

from offline import patch as offline

APP_ID = "2524890"  # Pixel Gun 3D: PC Edition en Steam
BASE = Path(__file__).resolve().parent
DATA = BASE / "launcher-data"
PACKS = BASE / "packs"
CONFIG = DATA / "config.json"
BASELINE = DATA / "baseline.json"
HISTORY = DATA / "builds-history.json"

# Archivos que definen "qué build es esta". Si cambian, el juego se ha actualizado.
KEY_FILES = [
    "Pixel Gun 3D.exe",
    "GameAssembly.dll",
    "UnityPlayer.dll",
    "Pixel Gun 3D_Data/il2cpp_data/Metadata/global-metadata.dat",
    "Pixel Gun 3D_Data/StreamingAssets/aa/catalog.json",
    "Pixel Gun 3D_Data/StreamingAssets/build_info",
]


# ----------------------------------------------------------------- utilidades

def _now() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def _write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, path)  # escritura atómica


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ------------------------------------------------------------- configuración

def load_config() -> dict:
    return _read_json(CONFIG, {})


def save_config(cfg: dict) -> None:
    _write_json(CONFIG, cfg)


def is_game_dir(path: Path) -> bool:
    return (path / "Pixel Gun 3D.exe").is_file() and (path / "Pixel Gun 3D_Data").is_dir()


def join_parts() -> str | None:
    """Une pgassettool.exe.part1/.part2/... si el exe llegó troceado. Devuelve un error o None."""
    exe = BASE / "pgassettool.exe"
    parts = sorted(BASE.glob("pgassettool.exe.part*"), key=lambda p: int(p.suffix[5:] or 0))
    if exe.is_file() or not parts:
        return None
    expected_file = BASE / "pgassettool.exe.sha256"
    expected = expected_file.read_text().split()[0].lower() if expected_file.is_file() else None
    tmp = exe.with_suffix(".tmp")
    with tmp.open("wb") as out:
        for p in parts:
            out.write(p.read_bytes())
    if expected and sha256(tmp) != expected:
        tmp.unlink()
        return "Los trozos de pgassettool.exe no coinciden con su hash: vuelve a descargarlos."
    os.replace(tmp, exe)
    for p in parts:
        p.unlink()
    return None


def find_tool(cfg: dict) -> Path | None:
    candidates = [cfg.get("tool_path"), BASE / "pgassettool.exe",
                  BASE / "PGAssetTool" / "pgassettool.exe", BASE / "pgassettool"]
    for c in candidates:
        if c and Path(c).is_file():
            return Path(c)
    return None


# ------------------------------------------------------------ capa de legado

def snapshot(game: Path) -> dict:
    files = {}
    for rel in KEY_FILES:
        p = game / rel
        files[rel] = sha256(p) if p.is_file() else None
    build_info = game / "Pixel Gun 3D_Data/StreamingAssets/build_info"
    info = build_info.read_text(errors="replace").strip() if build_info.is_file() else ""
    return {"taken": _now(), "build_info": info, "files": files}


def compare(old: dict, new: dict) -> list[str]:
    return [rel for rel in KEY_FILES if old.get("files", {}).get(rel) != new["files"].get(rel)]


def unpatched(snap: dict) -> dict:
    """En modo offline, cuenta los archivos parcheados por el launcher como su original."""
    files = dict(snap["files"])
    for f in offline.status()["files"]:
        if files.get(f["path"]) == f.get("patched_sha256"):
            files[f["path"]] = f["sha256"]
    return {**snap, "files": files}


def accept_baseline(snap: dict) -> None:
    hist = _read_json(HISTORY, [])
    hist.append(snap)
    _write_json(HISTORY, hist)
    _write_json(BASELINE, snap)


def build_status(game: Path) -> tuple[str, list[str], dict]:
    """Devuelve (estado, archivos_cambiados, snapshot_actual)."""
    snap = unpatched(snapshot(game))
    base = _read_json(BASELINE, None)
    if base is None:
        accept_baseline(snap)
        return "registrada", [], snap
    changed = compare(base, snap)
    return ("cambiada" if changed else "igual"), changed, snap


# ---------------------------------------------------------- capa de contenido

class Tool:
    """Envoltorio de la CLI de PGAssetTool."""

    def __init__(self, exe: Path, game: Path):
        self.exe, self.game = exe, game

    def run(self, *args: str) -> tuple[int, str]:
        cmd = [str(self.exe), *args, "--game", str(self.game)]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=flags)
        except OSError as e:
            return 1, f"No se pudo ejecutar PGAssetTool: {e}"
        return p.returncode, (p.stdout + p.stderr).strip()

    def mods(self) -> list[dict]:
        code, out = self.run("mods")
        result = []
        if code != 0:
            return result
        for line in out.splitlines():
            line = line.strip()
            if line.startswith("[on ]") or line.startswith("[off]"):
                rest = line[5:].split()
                if rest:
                    result.append({"enabled": line.startswith("[on ]"), "id": rest[0],
                                   "line": line[5:].strip()})
        return result

    def reapply(self) -> tuple[int, str]:
        """Restaura y reaplica todo lo activo. Cualquier toggle hace un reconcile completo."""
        active = [m for m in self.mods() if m["enabled"]]
        if not active:
            return 0, "No hay mods activos que reaplicar."
        return self.run("enable", active[0]["id"])


def list_packs() -> list[Path]:
    PACKS.mkdir(exist_ok=True)
    return sorted(PACKS.glob("*.pgmod"))


def in_steam_library(game: Path) -> bool:
    parts = [p.lower() for p in game.resolve().parts]
    return "steamapps" in parts and "common" in parts


def launch_game(game: Path) -> str:
    """Lanza el juego y devuelve cómo. steam:// solo abre la copia de la biblioteca de Steam,
    así que una copia fuera de ella (con sus mods) se lanza directamente por su exe."""
    if sys.platform == "win32" and in_steam_library(game):
        try:
            os.startfile(f"steam://rungameid/{APP_ID}")  # type: ignore[attr-defined]
            return "vía Steam"
        except OSError:
            pass
    subprocess.Popen([str(game / "Pixel Gun 3D.exe")], cwd=str(game))
    return "por su exe"


# --------------------------------------------------------------------- GUI

def main() -> None:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk

    DATA.mkdir(exist_ok=True)
    PACKS.mkdir(exist_ok=True)
    cfg = load_config()

    root = tk.Tk()
    root.title("PG3D Launcher v0")
    root.geometry("860x600")
    root.minsize(700, 480)

    # --- localizar juego y herramienta
    game = Path(cfg["game_dir"]) if cfg.get("game_dir") else None
    if not game or not is_game_dir(game):
        if is_game_dir(BASE.parent):
            game = BASE.parent
        else:
            messagebox.showinfo("PG3D Launcher", "Selecciona la carpeta de Pixel Gun 3D PC Edition.")
            sel = filedialog.askdirectory(title="Carpeta del juego")
            if not sel or not is_game_dir(Path(sel)):
                messagebox.showerror("PG3D Launcher", "Esa carpeta no contiene 'Pixel Gun 3D.exe'.")
                return
            game = Path(sel)
        cfg["game_dir"] = str(game)
        save_config(cfg)

    err = join_parts()
    if err:
        messagebox.showerror("PG3D Launcher", err)
        return
    tool_exe = find_tool(cfg)
    if not tool_exe:
        messagebox.showinfo("PG3D Launcher", "Selecciona pgassettool.exe (la CLI de PGAssetTool).")
        sel = filedialog.askopenfilename(title="pgassettool.exe",
                                         filetypes=[("pgassettool", "pgassettool*.exe"), ("Todos", "*")])
        if not sel:
            return
        tool_exe = Path(sel)
        cfg["tool_path"] = sel
        save_config(cfg)
    tool = Tool(tool_exe, game)

    # --- layout
    top = ttk.Frame(root, padding=10)
    top.pack(fill="x")
    status_var = tk.StringVar(value="Comprobando build…")
    ttk.Label(top, textvariable=status_var, wraplength=820).pack(side="left", fill="x", expand=True)

    body = ttk.Panedwindow(root, orient="horizontal")
    body.pack(fill="both", expand=True, padx=10)

    left = ttk.Labelframe(body, text="Mods instalados", padding=6)
    right = ttk.Labelframe(body, text="Packs disponibles (carpeta packs)", padding=6)
    body.add(left, weight=1)
    body.add(right, weight=1)

    mods_list = tk.Listbox(left, activestyle="none")
    mods_list.pack(fill="both", expand=True)
    packs_list = tk.Listbox(right, activestyle="none")
    packs_list.pack(fill="both", expand=True)

    log = tk.Text(root, height=10, wrap="word", state="disabled")
    log.pack(fill="x", padx=10, pady=(6, 0))

    bar = ttk.Frame(root, padding=10)
    bar.pack(fill="x")

    buttons: list[ttk.Button] = []
    mods_cache: list[dict] = []

    def write(text: str) -> None:
        log.configure(state="normal")
        log.insert("end", text.rstrip() + "\n\n")
        log.see("end")
        log.configure(state="disabled")

    def busy(flag: bool) -> None:
        for b in buttons:
            b.configure(state="disabled" if flag else "normal")

    def in_background(label: str, fn, then=None) -> None:
        busy(True)
        write(f"> {label}")

        def worker():
            try:
                code, out = fn()
            except Exception as e:  # nunca dejar la GUI bloqueada
                code, out = 1, f"Error: {e}"

            def done():
                write(out or ("Hecho." if code == 0 else f"Terminó con código {code}."))
                busy(False)
                refresh()
                if then:
                    then(code)
            root.after(0, done)

        threading.Thread(target=worker, daemon=True).start()

    def refresh() -> None:
        nonlocal mods_cache
        mods_cache = tool.mods()
        mods_list.delete(0, "end")
        for m in mods_cache:
            mods_list.insert("end", ("● " if m["enabled"] else "○ ") + m["line"])
        if not mods_cache:
            mods_list.insert("end", "(ninguno)")
        packs_list.delete(0, "end")
        for p in list_packs():
            packs_list.insert("end", p.name)

    def selected_mod() -> dict | None:
        sel = mods_list.curselection()
        if not sel or sel[0] >= len(mods_cache):
            messagebox.showinfo("PG3D Launcher", "Selecciona un mod de la lista.")
            return None
        return mods_cache[sel[0]]

    def check_build() -> None:
        state, changed, snap = build_status(game)
        label = snap["build_info"] or "build sin build_info"
        if state == "registrada":
            status_var.set(f"Build registrada como base: {label}")
        elif state == "igual":
            status_var.set(f"Build sin cambios: {label}")
        else:
            status_var.set(f"El juego se ha actualizado ({len(changed)} archivo(s) clave distintos). "
                           "Pulsa 'Reaplicar mods' y luego 'Aceptar build'.")
            write("Archivos cambiados:\n  " + "\n  ".join(changed))

    # --- acciones
    def act_install():
        sel = packs_list.curselection()
        packs = list_packs()
        if not sel or sel[0] >= len(packs):
            messagebox.showinfo("PG3D Launcher", "Selecciona un pack de la lista de la derecha.")
            return
        pack = packs[sel[0]]
        in_background(f"Instalar {pack.name}", lambda: tool.run("apply", str(pack)))

    def act_toggle():
        m = selected_mod()
        if m:
            cmd = "disable" if m["enabled"] else "enable"
            in_background(f"{cmd} {m['id']}", lambda: tool.run(cmd, m["id"]))

    def act_remove():
        m = selected_mod()
        if m and messagebox.askyesno("PG3D Launcher", f"¿Desinstalar {m['id']}?"):
            in_background(f"Quitar {m['id']}", lambda: tool.run("remove", m["id"]))

    def act_reapply():
        in_background("Reaplicar mods activos", tool.reapply)

    def act_accept():
        accept_baseline(unpatched(snapshot(game)))
        check_build()
        write("Build actual aceptada como base.")

    def act_verify():
        in_background("Verificar bundles", lambda: tool.run("verify"))

    def act_info():
        in_background("Info de la instalación", lambda: tool.run("info"))

    def act_open_packs():
        if sys.platform == "win32":
            os.startfile(PACKS)  # type: ignore[attr-defined]

    def act_mode():
        if offline.status()["mode"] == "official":
            in_background("Pasar a modo offline", lambda: (0, offline.apply()), lambda _: show_mode())
            return
        # Al volver a oficial no puede quedar contenido modificado en los bundles.
        def to_official():
            msgs = []
            for m in tool.mods():
                if m["enabled"]:
                    code, out = tool.run("disable", m["id"])
                    msgs.append(out)
                    if code != 0:
                        return code, "\n".join(msgs + ["No se ha restaurado: falló al desactivar mods."])
            msgs.append(offline.restore())
            return 0, "\n".join(msgs)
        in_background("Pasar a modo oficial", to_official, lambda _: show_mode())

    def show_mode():
        mode = offline.status()["mode"]
        mode_var.set("Modo: OFFLINE (sin Steam ni servidores)" if mode == "offline" else "Modo: oficial")
        mode_btn.configure(text="Pasar a oficial" if mode == "offline" else "Pasar a offline")

    def act_play():
        try:
            write(f"Juego lanzado {launch_game(game)}.")
        except OSError as e:
            write(f"No se pudo lanzar el juego: {e}")

    mode_var = tk.StringVar()
    ttk.Label(top, textvariable=mode_var).pack(side="right")
    mode_btn = ttk.Button(bar, command=act_mode)
    mode_btn.pack(side="left", padx=(0, 6))
    buttons.append(mode_btn)
    show_mode()

    for text, fn in [("Instalar pack", act_install), ("Activar/Desactivar", act_toggle),
                     ("Quitar", act_remove), ("Reaplicar mods", act_reapply),
                     ("Aceptar build", act_accept), ("Verificar", act_verify),
                     ("Info", act_info), ("Abrir carpeta packs", act_open_packs),
                     ("Jugar", act_play)]:
        b = ttk.Button(bar, text=text, command=fn)
        b.pack(side="left", padx=(0, 6))
        buttons.append(b)

    write(f"Juego: {game}\nPGAssetTool: {tool_exe}")
    root.after(50, check_build)
    root.after(100, refresh)
    root.mainloop()


if __name__ == "__main__":
    main()
