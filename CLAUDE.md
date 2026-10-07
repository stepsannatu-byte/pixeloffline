# PG3D Launcher — handoff

Proyecto de Stephan: un launcher para Pixel Gun 3D PC Edition que sobreviva aunque los desarrolladores abandonen el juego. Tiene tres capas:

1. **Offline-primero.** Un servidor local en `127.0.0.1` que imita el backend: perfil, inventario, economía, configuración remota y rankings locales. Tres modos: offline, autoalojado (homelab/LAN) y oficial sin mods.
2. **Contenido por packs.** Packs `.pgmod` versionados y firmados en lugar de actualizaciones fijas: armas, skins, mascotas, sombreros, mapas…
3. **Legado.** Hash de la build congelado, backend documentado, índice de packs descentralizado y herramientas para que la comunidad siga sin los desarrolladores.

Responde en español, breve, sin exclamaciones. Si dudas de un dato, verifícalo en lugar de suponerlo.

## Entorno

- Windows, usuario `ciclo1` (probablemente un PC de clase: puede haber restricciones para instalar o ejecutar).
- Juego en `C:\Users\ciclo1\Downloads\Pixel Gun 3D PC Edition`. Es la build de Steam, AppID `2524890`. Unity con IL2CPP: `GameAssembly.dll` y `Pixel Gun 3D_Data\il2cpp_data\Metadata\global-metadata.dat` (28 MB).
- Este launcher vive en `...\Pixel Gun 3D PC Edition\PG3D Launcher\` y detecta el juego en la carpeta padre.
- La copia del juego estaba contaminada con un cheat inyectado ("Asteroid": `config.asteroid` cifrado e `imgui.ini` con ventanas `emberlogin` y `asteroidv2`). Stephan lo quitó. **No reintroducir nada parecido.**

## Lo que se sabe de la build

- **Addressables:** `StreamingAssets\aa\catalog.json`, `settings.json` y bundles en `aa\StandaloneWindows64`. Hay también `StreamingAssets\Cache\bundles\` (bundles descargados) y `EmbeddedConfigs\`.
- **Plugins:** Firebase (App, Analytics, Messaging, RemoteConfig, Installations), `steam_api64.dll`, Unity Services. Remote Config es la dependencia de servidor más evidente.
- **Peso:** el grueso está en `resources.assets.resS` (827 MB) y `resources.assets` (229 MB), además de `sharedassetsN` y `levelN`.
- **Registro de objetos:** el MonoBehaviour `ItemsDataStorage` del bundle `it_d`. `itemDatas` tiene `index` e `id` (slug); `itemRecords` tiene `_index`, `_weaponNumber`, `_prefabName`, `_tag` y `localizeWeaponKey`. Hay unas 1517 armas. El número que se ve en el juego no es el mismo que el número del prefab.
- **Tipos de objeto** (según PGAssetTool): Weapon, Hat, Cape, Mask, Boots, Pet (`Pets/Content`), Glider, Avatar y Transport. Todos comparten el mismo mecanismo de prefab, skins y assets relacionados.

## Herramientas

**PGAssetTool** — https://github.com/mof-22/PGAssetTool (MIT, v1.0.6, último commit `4b70c44` del 2026-09-27). `SrJea/PGAssetTool` es un espejo idéntico. Es la base de la capa 2.

- Solo sustituye apariencia: `replaceTexture` (png), `replaceMesh` (glb) y `replaceAudio` (wav/mp3/ogg).
- **Se niega a propósito** a escribir componentes o scripts (comportamiento) y a añadir assets a bundles. Ver `DESIGN.md`, secciones "What can be written back" y "The one thing that is neither".
- CLI `pgassettool`: `info`, `weapons`, `items [kind]`, `show <item>`, `extract <item> [--workspace]`, `pack`, `apply <pgmod>`, `verify`, `mods`, `enable|disable|remove <id>`. Opción `--game <dir>`.
- Escribe los bundles en el sitio, pero antes guarda una copia de cada uno, indexada por hash, en `PGAssetTool-data\` junto al exe. Vuelve a aplicar los mods tras una actualización del juego y se niega a escribir con el juego abierto.
- No tiene código de red; solo lee el registro de Windows para encontrar Steam y lanza el juego.
- No publica el exe en las releases. Se ha compilado así, desde Linux con el SDK de .NET 10.0.401:
  ```
  dotnet publish src/PGAssetTool.Cli -c Release -p:EnableWindowsTargeting=true -p:EnableCompressionInSingleFile=true
  ```
  Sale autocontenido y en un solo archivo, de unos 37 MB. SHA-256: `b7350f554c3623560b5469c2d5e65f9af33f13b6dd7b300c41b98fc3eea9b5df`. Se entregó partido en `pgassettool.exe.part1` y `.part2`; el launcher los une y verifica el hash.

**pg3d-tools** (YeetDisDude) — **descartada.** Trae spam a los contactos de la desarrolladora, envío de mensajes al websocket oficial, registros falsos de moneda y comprobación de baneos, con código de 2024 y ejecutables de origen dudoso. Si hacen falta Il2CppDumper o Cpp2IL, se descargan de sus repos originales.

## Estado del launcher (`pg3d_launcher.py`, v0)

Python 3.10+ con la biblioteca estándar y tkinter.

- Al arrancar, hace hash de los archivos clave (exe, `GameAssembly.dll`, `UnityPlayer.dll`, `global-metadata.dat`, `catalog.json`, `build_info`) y los compara con `launcher-data\baseline.json`. Si cambian, el juego se ha actualizado. El historial queda en `builds-history.json`.
- Envuelve la CLI de PGAssetTool: instalar packs de `packs\`, activar/desactivar, quitar, reaplicar (un `enable` lanza una reconciliación completa), verificar e info.
- "Jugar" lanza el exe de la copia gestionada. Solo usa `steam://rungameid/2524890` si la copia está dentro de `steamapps\common` (antes abría siempre la instalación de Steam en `C:\Program Files (x86)\Steam\steamapps\common\`, que también existe en este PC).
- `join_parts()` une los trozos del exe y comprueba el hash.
- **Pruebas:** probado en Windows el 2026-10-07: la interfaz arranca, registra la build (`build_info`: "Build from DESKTOP-KPFUUJA at 9/30/2026 10:31:26 PM") y `pgassettool info/show 1/items pet/verify` funcionan con la versión 26.12.0 (2326 bundles, 112 mascotas, 0 bundles alterados).
- Se arranca con `py pg3d_launcher.py` desde esta carpeta.

## Repositorio

https://github.com/stepsannatu-byte/pixeloffline (público, MIT). El repo es la carpeta `PG3D Launcher`. Stephan quiere un push cada vez que se termina un bloque de trabajo. No subir binarios del juego ni de PGAssetTool (ver `.gitignore`).

## Objetivo prioritario: offline / LAN sin Steam

Stephan quiere jugar offline o en un servidor local, **sin Steam en absoluto**. Los packs son secundarios.

**Arranque observado** (`%USERPROFILE%\AppData\LocalLow\Pixel Gun Team\Pixel Gun 3D\Player.log` y volcado de Il2CppDumper):
1. Steamworks.NET (`SteamAPI_Init`, despacho manual de callbacks, `SteamClient020`/`SteamUser023`).
2. `GetAuthTicketForWebApi` → callback 168 → "Authorization SteamTicketCallbackFunc steamTicketReceived True".
3. `[ReserveUrls] http auth request sent: url='https://server-v2.pixelgun3dserver.com/auth_v2/'`. La respuesta puede traer `meta_urls` alternativas (solo en "grayzone").
4. Websocket `wss://{0}:{1}`. Multijugador por Photon (`ns.exitgamescloud.com`).
5. Configuración: `secure.pixelgun3dserver.com/pixelgun3d-config/...`, `secure.pixelgun3dserver.com/pg3d-config-system/{0}/{1}.json`, `cfg.pixelgun3d.com/config.json`. Contenido: `cdn.pixelgun3d.com/addressables/standalone/26.12/` (con `m_IgnoreFailures`, así que sin red usa el catálogo local).
6. Telemetría: AppsFlyer, lightmap.com, Firebase, Unity Analytics. Pagos: Xsolla.

Los nombres de clases del juego están ofuscados (caracteres CJK). Steamworks.NET no lo está. Los textos de log sirven para localizar el código.

**Herramientas externas** (fuera del repo, en `%USERPROFILE%\Downloads\pg3d-tools-ext\`): Il2CppDumper v6.7.46 (Perfare, zip SHA-256 `F5FC60DF…A2DEA2`) y su salida en `dump\` (`dump.cs`, `stringliteral.json`, `script.json`, `il2cpp.h`). Metadata e IL2CPP versión 31. Zig 0.16.0 instalado con `pip --user` como compilador de C.

**Hecho (2026-10-07):**
- `steam_stub\` — `steam_api64.dll` propia (ver su README). Probada dentro del juego: arranca sin Steam, crea las interfaces y entrega el ticket (`GetAuthTicketForWebApi`, identity `pg3d_backend`, callback 168) y las estadísticas (1101).
- `offline\patch.py` — modo offline (`py -m offline.patch plan|apply|restore|status`; también botón en el launcher). Redirige 54 hosts a `127.0.0.1:8001+n` (mapa en `launcher-data\offline-hosts.json`) en `global-metadata.dat` (literales acortados), `globalgamemanagers` (URLs de Unity Cloud, misma longitud con relleno `/`), `FirebaseCppApp`/`FirebaseCppRemoteConfig` (cadenas C, relleno NUL) y los JSON de `StreamingAssets`, y pone el stub de Steam. Originales en `launcher-data\originals\<sha256>`; la restauración se comprobó idéntica byte a byte. Al pasar a oficial, el launcher desactiva antes los mods.
- **Comprobado:** con el juego en offline, 90 s vigilando sus conexiones TCP: 0 externas. El juego muestra "Offline"/"sin conexión", que es lo esperado sin servidor local.
- El validador de certificados propio del juego (`CertificateHandler` en la clase ofuscada TypeDefIndex 12719, RVA 0x46A600) es `mov al,1; ret`: acepta cualquier certificado, así que el servidor local puede usar HTTPS con certificado autofirmado (openssl viene con Git for Windows). Las peticiones HTTP van por UnityWebRequest (errores "Curl error 7" en el log).
- Photon: `ns.exitgames.com` está en literales (redirigido), pero `http://ns.exitgamescloud.com:80/photon/n` es un valor por defecto de campo en la sección 8 de la metadata, con prefijo de longitud comprimido; no se ha tocado. Hay que resolverlo al hacer el multijugador.

**Servidor local (`offline\server.py`, `py -m offline.server`)** — escucha en `127.0.0.1:<puerto>` de cada host del mapa, HTTP y HTTPS en el mismo puerto (mira el primer byte). Registra todo en `launcher-data\server-log.jsonl` (con `body_b64`). Responde 404 salvo las rutas de `ROUTES`.

Por qué 127.0.0.1 con puertos y `http://`: UnityTls no acepta el certificado autofirmado ("not correctly signed by a trusted CA"); esas peticiones no usan el validador permisivo. Con `http://` Unity lanza "Insecure connection not allowed" (`insecureHttpOption` = NotAllowed) salvo hacia 127.0.0.1/localhost. Por eso el parche usa `127.0.0.1:8001+n` y cambia los literales `https`/`https://`/`wss`/`wss://` a sus versiones sin TLS.

**Protocolo `/auth_v2/`** (POST a `server-v2`, método que lo envía: `上与丛丌东一下下上.丙七丝丅丘丒丏丒丘.MoveNext` 0x1E88320; cuerpo armado en `上与丛丌东一下下上$$丁丈丛丑丄丑七丁丒` 0x1E505B0):
- Cuerpo binario UTF-16LE: por campo `[long. clave en bytes][long. valor en bytes][clave][valor]`; las longitudes sin desplazar y cada carácter desplazado `shift`. El último valor termina en un carácter 0. El orden de los campos es aleatorio.
- `shift` cambia en cada petición y sale de `id_seed` (semillas consecutivas → +11 de desplazamiento; probablemente `new System.Random(id_seed)`). El servidor lo averigua probando hasta que aparece la clave `version`.
- Campos: `cpu_frequency, ram, cpu_model, uniq_id` (ID del jugador guardado en local; aquí 355395299), `cpu_cores, device_model, hash` (UUID), `device_id, platform` (9 = Steam), `id_seed, steam_ticket` (hex de los 2560 bytes del ticket), `version` (26.12.0).
- **Respuesta: mismo formato y mismo `shift`.** Comprobado: el juego la acepta ("auth response urls: meta_urls=[null], bundle_urls=[null]") y deja de reintentar. Con JSON da `ArgumentOutOfRangeException` en `UnicodeEncoding.GetString` (decodificador `丞丟三丄不不丟不丂`).
- Claves que lee la respuesta (`万丁丕丄丟世丕东丝` 0x1E51BB0): `url, meta_urls, bundle_urls, token, hash, player_id, server_time, check_version, end_time, create_to, easy, currency, reason_key, err_code, queue_place, polling_timeout`. Ahora se envían `url=ws://127.0.0.1:9001, token, hash, player_id, server_time, check_version=0, end_time`.
- Tras la auth el juego **no** abre aún el websocket (nada llega a 9001). Falta saber el formato que espera `url` (el literal es `wss://{0}:{1}`, quizá quiere host y puerto por separado) o qué otro campo lo activa.
- Otra respuesta, probablemente del websocket (`丝丂丝三一且丕专且` 0x1E57BF0): `id, secret, country, continent, developer, block_value, reg_ver, reg_time, l_online_diff, time, new_player, char_key, progress_status, last_command, err_code, OldPurchased, TableViewKey`. "terceShtuA" = "AuthSecret" al revés.
- Hay también un flujo `auth/cubicid` con `session_token`, `req_id` y `Authorization: Bearer` (cuentas Cubic ID), que no se usa en Steam.

**`research\xref.py`** — referencias cruzadas sin desensamblador: `py research/xref.py <dump> str "<literal>"` da los métodos que usan un texto; `method <rva>` da los textos de un método. Indexa en 2 s las cargas `[rip+disp32]` de `GameAssembly.dll` contra las ranuras de literales de `script.json`.

`xref.py` también tiene `dis <rva>` (desensambla con capstone, `pip install --user capstone`, y anota llamadas, textos y tipos) y `callers <rva>`.

**Socket.IO (`offline\socketio.py`)** — con `token` no vacío en la respuesta de auth, `Rilisoft.WebSocket.WebSocketManager` (BestHTTP.SocketIO antiguo) conecta a la `url` con `?EIO=4&transport=websocket&client_version=26.12.0&c=1&client_ver=v2&platform=9&a=0`. El servidor local hace el handshake websocket, manda el paquete open de Engine.IO y `40` (conexión al namespace raíz, como Socket.IO v2). Entonces el juego conecta al namespace `/sio` y envía su primer evento como binario con dos adjuntos.

**Estado final (2026-10-07): el proyecto se detiene aquí en la parte jugable.** Los eventos del socket van cifrados por el cliente, y descifrarlos o reimplementarlos queda fuera de lo que Claude va a hacer, tanto con capturas del juego oficial como sin ellas. Tampoco se harán trainers, menús de desarrollo inyectados ni parches de código para saltarse el servidor y entrar en modos online o mundos. Sin ese paso el juego no llega al menú principal, y el inventario lo valida el servidor, así que armas o mundos nuevos tampoco serían jugables. `offline\pgcrypto.py` existe solo en el PC de Stephan y está excluido del repo.

Lo que sigue siendo útil: el launcher, el modo offline (desconexión total y reversible), el servidor local hasta la autenticación y esta documentación del legado.

## Reglas del proyecto

- No tocar los servidores oficiales, no hacer trampas y no cambiar el comportamiento en partidas online.
- El contenido creativo nuevo (objetos nuevos, estadísticas) va **solo en modo offline**. Antes de entrar en modo oficial, el launcher debe devolver los bundles originales.
- No redistribuir binarios ni assets del juego. Solo el launcher, las herramientas y el contenido original de la comunidad.

## Siguientes pasos

1. ~~Ejecutar el launcher en Windows~~ y ~~comprobar PGAssetTool con esta versión~~ (hecho).
3. **Fork de PGAssetTool para crear objetos nuevos** (armas, skins, mascotas…), solo offline. El primer hito es un comando `clone`:
   - copiar el prefab de un objeto existente y sus assets a un bundle nuevo registrado en el manifiesto y catálogo;
   - añadir entradas nuevas en `itemDatas` e `itemRecords` de `it_d`;
   - añadir la clave de localización;
   - después, aplicarle el aspecto con las operaciones replace que ya existen.

   Las estadísticas se ajustarían clonando y modificando campos existentes, no escribiendo comportamiento nuevo. Antes hay que inspeccionar `it_d` real y averiguar dónde viven las estadísticas (componentes del prefab o Remote Config).
4. **Contrato del backend (capa 1):** ver "Objetivo prioritario" arriba. El servidor local también tiene que dar la propiedad de los objetos creados con el fork, porque el inventario lo valida el servidor.
5. Mapas procedurales por semilla e índice comunitario de packs.
