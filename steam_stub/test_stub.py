"""Prueba la steam_api64.dll falsa imitando lo que hace Steamworks.NET al arrancar.

    py test_stub.py
"""
import ctypes as C
import struct
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


class CallbackMsg(C.Structure):
    _fields_ = [("hUser", C.c_int32), ("id", C.c_int32), ("param", C.c_void_p), ("size", C.c_int32)]


def main() -> int:
    real = HERE.parent.parent / "Pixel Gun 3D_Data/Plugins/x86_64/steam_api64.dll"
    dll = C.CDLL(str(HERE / "steam_api64.dll"))
    ok = True

    def check(cond, what):
        nonlocal ok
        print(("ok   " if cond else "FAIL ") + what)
        ok &= bool(cond)

    exports = (HERE / "exports.txt").read_text().split()
    missing = [n for n in exports if not hasattr(dll, n)]
    check(not missing, f"las {len(exports)} exportaciones existen {missing[:3]}")

    f = dll
    for name in ["SteamInternal_CreateInterface", "SteamAPI_ISteamClient_GetISteamUser",
                 "SteamAPI_ISteamFriends_GetPersonaName", "SteamAPI_ISteamApps_GetCurrentGameLanguage"]:
        getattr(f, name).restype = C.c_void_p
    f.SteamAPI_ISteamUser_GetSteamID.restype = C.c_uint64
    f.SteamAPI_ISteamUser_RequestEncryptedAppTicket.restype = C.c_uint64
    f.SteamAPI_ISteamMusic_GetVolume.restype = C.c_float

    # SteamAPI.Init() de Steamworks.NET
    check(f.SteamAPI_RestartAppIfNecessary(2524890) == 0, "RestartAppIfNecessary -> false")
    check(f.SteamAPI_Init() & 0xFF == 1, "SteamAPI_Init -> true")
    pipe, user = f.SteamAPI_GetHSteamPipe(), f.SteamAPI_GetHSteamUser()
    check(pipe and user, "pipe y usuario no nulos")
    client = f.SteamInternal_CreateInterface(b"SteamClient020")
    check(client, "CreateInterface(SteamClient020) no nulo")
    iuser = f.SteamAPI_ISteamClient_GetISteamUser(C.c_void_p(client), user, pipe, b"SteamUser023")
    check(iuser, "GetISteamUser no nulo")
    f.SteamAPI_ManualDispatch_Init()

    name = C.string_at(f.SteamAPI_ISteamFriends_GetPersonaName(C.c_void_p(client)))
    check(name, f"GetPersonaName = {name!r}")
    check(C.string_at(f.SteamAPI_ISteamApps_GetCurrentGameLanguage(None)), "idioma no vacío")
    sid = f.SteamAPI_ISteamUser_GetSteamID(C.c_void_p(iuser))
    check(sid >> 52 == 0x011, f"SteamID individual {sid}")
    check(f.SteamAPI_ISteamMusic_GetVolume(None) == 0.0, "float por defecto = 0.0")

    # Ticket para la web API y llamada asíncrona.
    handle = f.SteamAPI_ISteamUser_GetAuthTicketForWebApi(C.c_void_p(iuser), b"pixelgun")
    check(handle, f"GetAuthTicketForWebApi -> {handle}")
    call = f.SteamAPI_ISteamUser_RequestEncryptedAppTicket(C.c_void_p(iuser), None, 0)

    msg, got = CallbackMsg(), {}
    f.SteamAPI_ManualDispatch_RunFrame(pipe)
    while f.SteamAPI_ManualDispatch_GetNextCallback(pipe, C.byref(msg)) & 0xFF:
        got[msg.id] = C.string_at(msg.param, msg.size)
        f.SteamAPI_ManualDispatch_FreeLastCallback(pipe)

    t = got.get(168, b"")
    h, res, n = struct.unpack_from("<Iii", t)
    check(len(t) == 2572 and h == handle and res == 1, "callback 168 con resultado OK")
    check(t[12:12 + n].startswith(b"PG3DOFFLINE:"), f"ticket = {t[12:12 + n]!r}")

    done = got.get(703, b"")
    acall, cid, size = struct.unpack_from("<QiI", done)
    check(acall == call and cid == 154, "SteamAPICallCompleted_t para el ticket cifrado")
    buf, failed = C.create_string_buffer(size), C.c_bool()
    r = f.SteamAPI_ManualDispatch_GetAPICallResult(pipe, C.c_uint64(call), buf, size, 154, C.byref(failed))
    check(r & 0xFF and not failed.value and struct.unpack("<i", buf.raw[:4])[0] == 1,
          "GetAPICallResult devuelve OK")

    print("\nsteam_stub.log:\n" + (HERE / "steam_stub.log").read_text())
    print("TODO BIEN" if ok else "HAY FALLOS")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
