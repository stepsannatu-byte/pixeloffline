# steam_stub

`steam_api64.dll` propia para la copia offline del juego. Sustituye a la de Valve para que el juego arranque sin Steam: responde a Steamworks.NET con valores locales y entrega un ticket falso (`PG3DOFFLINE:<steamid>:<nombre>`) que solo acepta el servidor local.

No contiene código de Valve. `exports.txt` es la lista de nombres de la API pública de Steamworks y `signatures.tsv` el tipo de retorno de cada función según Steamworks.NET.

## Compilar y probar

```
py -m pip install --user ziglang
py build.py
py test_stub.py
```

## Uso

**No la instales sin redirigir antes las URLs del juego al servidor local.** Si no, el juego enviaría el ticket falso a los servidores oficiales.

Se copia en `Pixel Gun 3D_Data\Plugins\x86_64\` en lugar de la original, que debe guardarse antes, junto con `steam_stub.ini` (ver `steam_stub.ini.example`). Deja en `steam_stub.log` la primera llamada a cada función, lo que sirve para ver qué más pide el juego.

## Qué hace

- `SteamAPI_Init` y `SteamInternal_CreateInterface` devuelven éxito e interfaces no nulas; `RestartAppIfNecessary` devuelve false.
- Cola de callbacks para el despacho manual de Steamworks.NET (`ManualDispatch_*`) y resultados de llamadas asíncronas (`SteamAPICallCompleted_t` + `GetAPICallResult`).
- `GetAuthTicketForWebApi` (callback 168), `GetAuthSessionTicket` (163), `RequestEncryptedAppTicket` (154).
- Nombre, SteamID, idioma y país salen del `.ini`. AppID 2524890.
- El resto de funciones devuelve 0, o un puntero a memoria a cero si la función devuelve un puntero (vale como interfaz y como cadena vacía).
