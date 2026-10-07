# PG3D Launcher

Launcher para Pixel Gun 3D PC Edition pensado para seguir funcionando aunque el juego deje de mantenerse: registro de la build, packs de contenido `.pgmod` sobre [PGAssetTool](https://github.com/mof-22/PGAssetTool) y, más adelante, modo offline con servidor local.

No incluye binarios ni assets del juego.

## Uso

1. Coloca esta carpeta dentro de la carpeta del juego (`...\Pixel Gun 3D PC Edition\PG3D Launcher\`).
2. Añade `pgassettool.exe` (o sus trozos `.part1`/`.part2`) y `classdata.tpk`. El launcher une los trozos y comprueba el hash de `pgassettool.exe.sha256`.
3. Ejecuta `py pg3d_launcher.py` (Python 3.10+, solo biblioteca estándar).
4. Deja los packs `.pgmod` en `packs\`.

Si la copia del juego no está en una biblioteca de Steam, "Jugar" lanza su exe directamente; si lo está, usa `steam://rungameid/2524890`.

## Modo offline

El botón "Pasar a offline" desconecta la copia del juego de todos los servidores externos y de Steam: redirige cada host a una IP de loopback y sustituye `steam_api64.dll` por `steam_stub` (hay que compilarlo antes con `py steam_stub/build.py`). Guarda los originales y "Pasar a oficial" los devuelve. Desde la línea de comandos: `py -m offline.patch plan|apply|restore|status`.

Sin el servidor local (en desarrollo), el juego arranca pero se queda sin conexión.

Detalles del proyecto, reglas y siguientes pasos en [CLAUDE.md](CLAUDE.md).
