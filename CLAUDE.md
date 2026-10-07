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

**Hecho:** `steam_stub\` — `steam_api64.dll` propia (ver su README). Probada con `test_stub.py` simulando Steamworks.NET; **no probada aún dentro del juego**.

**Siguiente:**
1. Redirigir las URLs: parchear los literales de `global-metadata.dat` en la copia offline (con copia del original y restauración antes del modo oficial). Problema por resolver: son `https://`/`wss://`; mirar qué cliente HTTP usa el juego y si acepta `http://` o certificados propios. Sin administrador no se puede tocar `hosts` ni instalar una CA.
2. Instalar el stub y el parche juntos (nunca el stub solo) y leer `steam_stub.log` y `Player.log`.
3. Servidor local en Python: `/auth_v2/`, websocket y configuración, hasta el menú principal.
4. Photon local para el multijugador en LAN.

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
