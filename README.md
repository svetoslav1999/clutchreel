# ClutchReel

Convierte demos de **Counter-Strike 2** (partidas Premier/Competitivo) en vídeos de mejores jugadas listos para YouTube o Shorts. Arrastras la demo, respondes cinco preguntas (o pulsas «Usar recomendado») y ClutchReel analiza la partida, elige las mejores jugadas por puntuación, graba cada una con OBS desde el visor oficial de demos y monta el vídeo con intro, música, cámara lenta, marcador de kills y miniatura.

> **Seguridad**: ClutchReel **solo lee** los ficheros `.dem`, usa el **visor oficial de demos del juego** y **comandos de consola normales** (`playdemo`, `demo_gototick`, `demo_pause`, `demo_resume`, `spec_player`…). **Nunca inyecta código, no toca la memoria del juego ni modifica archivos del juego.** CS2 se lanza siempre con `-insecure` (sin VAC) para ver demos. Lo único que puede escribir en la carpeta del juego, y solo si activas el modo de respaldo por teclado, es un fichero de configuración `cfg/clutchreel.cfg` con esos mismos comandos.

---

## Avisos

**Proyecto independiente.** ClutchReel no está afiliado, patrocinado ni aprobado por Valve Corporation ni por el proyecto OBS Studio. Counter-Strike, Counter-Strike 2 y Steam son marcas de Valve Corporation; OBS y OBS Studio pertenecen a sus respectivos titulares. Los nombres se usan solo para indicar con qué programas funciona.

**Sin garantías.** El software se ofrece «tal cual», sin garantía de ningún tipo, expresa o implícita. Úsalo bajo tu responsabilidad; los autores no responden de daños, pérdidas de datos ni de las consecuencias de su uso (ver `LICENSE`).

**Qué hace ClutchReel con el juego**

- Lee los ficheros `.dem` del disco (solo lectura) con la librería demoparser2.
- Abre CS2 a través de Steam con `-insecure` (sin VAC; el juego no puede entrar en partidas oficiales mientras está así) y `-netconport`, y reproduce la demo en el **visor oficial de demos** del juego.
- Le envía **comandos de consola normales** del visor (`playdemo`, `demo_gototick`, `demo_step_tick`, `demo_pause`, `spec_player`, `spec_mode`, `getpos`…) por el puerto de consola local o, como respaldo, tecleándolos.
- Cambia temporalmente algunas variables de interfaz para grabar limpio (FPS en pantalla, aviso de TrueView, sonido sin foco…) y las **restaura** al terminar.
- Graba la pantalla con OBS a través de obs-websocket.

**Qué NO hace**

- No inyecta código, no lee ni escribe la memoria del juego, no usa DLL, hooks ni overlays propios.
- No modifica ni parchea ficheros del juego. Lo único que puede escribir en la carpeta de CS2 es `cfg/clutchreel.cfg` (con esos mismos comandos de consola) si activas el modo de respaldo por teclado, y una copia de la demo en `replays` si activas esa opción.
- No se conecta a servidores de partidas ni funciona en partidas online: solo con demos ya descargadas.
- No envía datos a ningún sitio salvo, si tú la activas, la subida a YouTube con tus credenciales.

---

## Requisitos

| Qué | Para qué | Dónde |
|---|---|---|
| Windows 10/11 64 bits | — | — |
| Python 3.11 o superior | ejecutar la app | `Iniciar.bat` lo comprueba y te explica cómo instalarlo (`winget install Python.Python.3.12`) |
| FFmpeg | cortar, unir y exportar | `Iniciar.bat` lo descarga solo en `tools\ffmpeg` si no está instalado |
| Steam + Counter-Strike 2 | reproducir las demos para grabarlas | se detectan por el registro de Windows y `libraryfolders.vdf` |
| OBS Studio 28 o superior | grabar la pantalla del juego (incluye obs-websocket) | https://obsproject.com |
| GPU NVIDIA / AMD / Intel | codificación por hardware (opcional, si no, CPU) | se detecta automáticamente |

Sin OBS ni CS2 puedes usar igualmente el modo **«Ya tengo la grabación»**: le das el vídeo de la partida completa y ClutchReel corta las jugadas de ahí.

---

## Instalación y arranque

1. Copia la carpeta `ClutchReel` donde quieras (vale una ruta con espacios o tildes, y OneDrive).
2. Haz **doble clic en `Iniciar.bat`**. La primera vez:
   - comprueba Python 3.11+ (si falta, te ofrece instalarlo con winget);
   - crea el entorno virtual `.venv` e instala las dependencias;
   - comprueba FFmpeg y, si falta, lo descarga (build oficial de gyan.dev, ~90 MB);
   - abre ClutchReel.
3. Las siguientes veces arranca directamente.

También puedes abrir una demo directamente: `Iniciar.bat "C:\ruta\partida.dem"`.

### Ejecutable opcional (.exe)

`scripts\construir_exe.bat` genera `dist\ClutchReel\ClutchReel.exe` con PyInstaller (necesita haber ejecutado antes `Iniciar.bat`).

---

## Instalar en otro PC

ClutchReel se instala clonando el repositorio privado; no hace falta copiar nada más de este PC.

**Requisitos**

| Qué | Notas |
|---|---|
| Windows 10/11 64 bits | — |
| [Git](https://git-scm.com/download/win) | para clonar (`winget install Git.Git`) |
| Python 3.11 o 3.12 | `winget install Python.Python.3.12` (Iniciar.bat avisa si falta) |
| OBS Studio 28 o superior | incluye obs-websocket |
| Steam + Counter-Strike 2 | con sesión iniciada |

FFmpeg no hace falta instalarlo: `Iniciar.bat` lo descarga solo en `toolsfmpeg`.

**Pasos**

1. Clona el repositorio (pedirá iniciar sesión en GitHub la primera vez, porque es privado):
   ```
   git clone https://github.com/svetoslav1999/clutchreel.git
   ```
   Vale cualquier carpeta, también con espacios, tildes u OneDrive.
2. Haz **doble clic en `Iniciar.bat`**. La primera vez crea `.venv`, instala las dependencias (versiones fijadas en `requirements.txt`) y descarga FFmpeg; tarda unos minutos.
3. Se abre la **primera configuración**: muestra lo detectado (Steam, CS2, OBS, FFmpeg, demos) y toma tu cuenta de Steam como jugador. Tu configuración se guarda solo en ese PC, en `%APPDATA%\ClutchReel\config.json`; el repositorio no contiene contraseñas, SteamIDs ni rutas.
4. En **Ajustes → OBS** pulsa **«Configurar OBS automáticamente»**: activa el servidor WebSocket de OBS con una contraseña nueva, la guarda en ClutchReel y reabre OBS (avisa antes de cerrarlo).
5. Con un proyecto abierto, **Ajustes → 🎥 Probar grabación (calibrar)** para medir la latencia de ese PC.

Para actualizar más adelante: `git pull` en la carpeta y vuelve a abrir `Iniciar.bat` (reinstala dependencias si `requirements.txt` cambió).

---

## Uso en cinco pasos

1. **Inicio**: arrastra una o varias demos a la zona grande (o elige de la lista «Demos en tu carpeta de CS2»). Se analizan con barra de progreso: mapa, fecha, marcador, jugadores y estadísticas.
2. **Asistente** (5 pasos, botón «✨ Usar recomendado y terminar»):
   1. jugador (se detecta tu cuenta de Steam; se recuerda para la próxima vez). Si tu cuenta no aparece en la demo no se preselecciona a nadie: elige tu jugador en la lista;
   2. qué sacar: multikills (2K/3K/4K/ACE), clutches 1vX, rachas de headshots, primeras bajas, AWP/no-scope, wallbangs, kills a través de humo, cegado, en el aire, cuchillo, rondas decisivas, mejor ronda o todas las kills;
   3. duración objetivo (1-3, 3-5, 5-10 min o sin límite): se eligen las mejores por puntuación;
   4. estilo: formato (YouTube 1080p/1440p/4K o Shorts 9:16), música, transiciones, intro/outro, marcador de kills, cámara lenta, nombre del canal;
   5. grabación: automática con OBS o vídeo ya grabado (hay que elegir el vídeo; si alguna jugada cae fuera de él, al exportar se avisa de cuáles se omitieron).
3. **Revisión**: tarjetas de las jugadas (tipo, ronda, puntuación, duración). Arrastra para reordenar, casilla para incluir/excluir, recorta inicio/fin, cámara lenta, texto, zoom, transición y volumen por clip; música con ducking, intro/outro, logo; «Ordenar por: cronológico / mejor puntuación / crescendo»; deshacer/rehacer (Ctrl+Z / Ctrl+Y); guardar perfil. Todo se autoguarda en un proyecto `.clutchreel.json`.
4. **🎬 Crear vídeo**: si faltan grabaciones, ClutchReel abre OBS y CS2, reproduce la demo y graba cada jugada; después monta y exporta. En «Cola y resultado» ves el progreso, la estimación de tiempo, y al terminar: abrir carpeta, previsualizar, título/descripción/etiquetas sugeridos (editables) y «Subir a YouTube (privado)».
5. **Modo TODO AUTOMÁTICO** (casilla en Inicio o icono de la bandeja): vigila la carpeta de demos de CS2 y, cuando aparece una nueva, la procesa con el perfil guardado y avisa con una notificación de Windows.

---

## La primera grabación con OBS: calibración

La grabación automática depende de tu PC, de OBS y de la versión de CS2, así que **la primera vez pulsa `Ajustes → 🎥 Probar grabación (calibrar)`** con un proyecto abierto. ClutchReel:

1. conecta con OBS (o lo abre con el WebSocket activado), crea la escena «ClutchReel» con una fuente *Game Capture* de `cs2.exe` (si sale negra prueba *Window Capture* y luego *Display Capture*);
2. lanza CS2 por Steam con `-insecure -novid -console -netconport 2121`;
3. carga la demo, salta a la mejor jugada, sigue a tu jugador, **comprueba por la consola que la cámara está en él** y graba 6 s;
4. mide la latencia entre `demo_resume` y el primer fotograma con movimiento, y la guarda en `Ajustes → CS2 → Latencia medida`.

Revisa el clip en la vista previa. Cada clip grabado lleva en su tarjeta de Revisión el jugador al que siguió la cámara de verdad; si la cámara no se pudo poner en tu jugador, el clip se marca como fallido con el motivo (nunca se da por bueno sin comprobar).

### Cómo envía ClutchReel los comandos a CS2

1. **Puerto de consola** (`-netconport`): socket TCP local. Con CS2 1.41.9 (octubre 2026) el puerto abre en Windows sin `-tools` (y con `-tools` el juego se cerraba al saltar en la demo), así que la casilla «Añadir -tools» está desactivada. Es el único canal que permite **leer** la consola, y por tanto comprobar a quién sigue la cámara: ClutchReel compara la posición de la cámara (`getpos`) con la posición del jugador en la demo en ese tick y, además, lee el anuncio de CS2 «Added TrueView prediction for player slot N (nombre)». Un clip solo se da por bueno si ambas pruebas coinciden con tu jugador, antes y durante la grabación.
2. **Teclado**: si el puerto no responde, ClutchReel pone CS2 en primer plano, abre la consola, teclea `exec clutchreel` (los comandos van en `cfg\clutchreel.cfg`) y la cierra.
3. **Semiautomático**: si tampoco funciona, aparece una ventana con los comandos para que los teclees tú y pulses «Hecho».

---

## Ajustes

- **Jugador**: SteamID64 y nombre (se rellena desde las cuentas de Steam del PC).
- **Rutas**: demos, salida, FFmpeg, OBS, CS2, música. Vacío = detección automática.
- **OBS**: host/puerto/contraseña (se leen de la configuración de obs-websocket; nunca se pasan por línea de comandos y el registro tacha cualquier contraseña, también la que imprime la librería obs-websocket al conectar), modo de captura, formato (solo se cambia si el de OBS no sirve), resolución y FPS. ClutchReel toca en OBS únicamente: la escena/fuente «ClutchReel», la carpeta de grabación y, si está marcado «Fijar resolución y FPS», el lienzo.
- **CS2**: opciones de lanzamiento, puerto de consola, `-tools` (desactivado), comandos de HUD, esperas, latencia, ventana forzada, respaldos.
- **Calidad y detección**: preset, códec H.264/HEVC, NVENC/AMF/QSV/CPU, bitrate, loudnorm, miniatura, abrir carpeta/notificar/apagar al terminar, márgenes antes/después de cada jugada, ventana de multikill, fusión de jugadas cercanas.
- **YouTube**, **Modo automático**, **Apariencia** (tema oscuro/claro, bandeja).
- Botones **Diagnóstico** (Python, FFmpeg, codificador, Steam, CS2, demos, OBS, WebSocket, jugador, disco, vista previa, con solución para cada fallo) y **Ver registro** → «Copiar informe de errores».

Rendimiento: el análisis lee la demo en una sola pasada y guarda el resultado en `%APPDATA%\ClutchReel\cachenalisis` (volver a analizar la misma demo, aunque esté copiada en otra carpeta, es instantáneo). Al terminar de grabar, ClutchReel se pone delante de CS2: con CS2 en primer plano y la demo en pausa, el juego ocupa toda la GPU y la exportación iba hasta 15 veces más lenta.

La configuración está en `%APPDATA%\ClutchReel\config.json`; los proyectos en `%APPDATA%\ClutchReel\proyectos`; el registro rotativo en `%APPDATA%\ClutchReel\logs\clutchreel.log`. Los vídeos salen en `Vídeos\ClutchReel` (grabaciones en bruto en `Vídeos\ClutchReel\grabaciones`).

---

## Subida a YouTube (opcional)

Sin credenciales la app funciona igual; el botón explica qué falta. Para activarla:

1. Entra en https://console.cloud.google.com, crea un proyecto y activa **YouTube Data API v3**.
2. Pantalla de consentimiento OAuth: tipo *Externo*, añade tu cuenta como usuario de prueba.
3. Credenciales → *Crear credenciales* → *ID de cliente de OAuth* → tipo **Aplicación de escritorio** → descarga el JSON.
4. En ClutchReel: `Ajustes → YouTube`, activa la casilla y elige ese JSON (`client_secrets.json`).
5. La primera subida abre el navegador para autorizar; el token se guarda en `%APPDATA%\ClutchReel\youtube_token.json`.

Los vídeos se suben como **privados** (borrador) con título, descripción, etiquetas y miniatura.

---

## Música

Pon pistas en una carpeta y elígela en `Ajustes → Rutas → Música` (o en `assets\music`). El volumen baja automáticamente cuando suena el juego (ducking) y hay fundidos de entrada/salida. «Sincronizar cortes al ritmo» requiere instalar `librosa` en el entorno (`.venv\Scripts\pip install librosa`); si no está, se ignora.

---

## Solución de problemas

| Síntoma | Causa probable | Qué hacer |
|---|---|---|
| «OBS está abierto pero el servidor WebSocket no responde» | el servidor WebSocket está desactivado en OBS | OBS → Herramientas → Ajustes del servidor WebSocket → Activar (puerto 4455) y copia la contraseña en Ajustes → OBS. O cierra OBS: ClutchReel lo abre con el servidor activado. |
| La grabación sale negra | Game Capture no engancha a CS2 | ClutchReel cambia solo a Window/Display Capture. Si persiste, en Ajustes → OBS elige «Display Capture» y ejecuta OBS como administrador. |
| «El puerto de consola 2121 no respondió» | CS2 estaba abierto sin `-netconport` (ClutchReel pide permiso para reiniciarlo) o un cortafuegos bloquea el puerto local | acepta el reinicio de CS2 desde ClutchReel, o ciérralo antes de pulsar «Crear vídeo». Sin puerto se usa el teclado, pero los clips no se pueden comprobar y se marcan como fallidos. |
| Un clip aparece como «✗ falló: la cámara no sigue a…» | CS2 cambió la cámara a otro jugador (p. ej. tu jugador murió) o el comando `spec_player` no llegó | vuelve a pulsar «Crear vídeo»: solo se reintentan los clips fallidos. Si se repite, copia el registro (Ajustes → Ver registro). |
| Las grabaciones tienen extensión `.mkv` pero son MP4 | OBS cambia la extensión al vuelo pero sigue con el formato anterior hasta reiniciarse | ClutchReel renombra cada grabación según su contenido real; no hace falta hacer nada. |
| Se ve la barra del reproductor de demos en el vídeo | versiones anteriores de ClutchReel no siempre aplicaban `demo_ui_mode 0` cuando abrían CS2 ellas mismas | ya está corregido; si la ves, cierra CS2 y vuelve a pulsar «Crear vídeo». |
| He pulsado «Cancelar» o he cerrado la app grabando | — | ClutchReel para la grabación de OBS, borra el clip a medias y devuelve las variables de CS2 a su valor. Los clips ya grabados se conservan. |
| El clip empieza tarde/pronto | latencia distinta de la calibrada | repite «Probar grabación» o ajusta «Ajuste manual de inicio (s)». |
| «playdemo» no encuentra la demo | CS2 no acepta la ruta absoluta | activa «Copiar la demo a la carpeta replays del juego». |
| «No hay espacio suficiente» | menos de 2 GB libres | libera espacio o cambia la carpeta de salida. |
| La demo «no tiene cabecera de demo de CS2» | es de CS:GO o está corrupta/incompleta | solo se admiten demos de CS2 completas. |
| Vista previa sin imagen | códecs de QtMultimedia | el vídeo final se abre igual con el botón «Abrir carpeta». |
| Python no encontrado | no está instalado o no está en PATH | `winget install Python.Python.3.12` y vuelve a ejecutar `Iniciar.bat`. |

Para cualquier error: `Ajustes → Ver registro → Copiar informe de errores`.

---

## Desarrollo

```
.venv\Scripts\pip install -r requirements-dev.txt
.venv\Scripts\python -m pytest          # tests (detectores, ticks, FFmpeg, configuración, grabador con dobles)
.venv\Scripts\python -m ruff check .    # linter
.venv\Scripts\python -m mypy clutchreel # tipos
```

Estructura: `clutchreel/ui` (PySide6), `core/demo` (demoparser2, detectores, puntuación, selección), `core/recorder` (OBS + CS2), `core/editor` (proyecto, deshacer, música), `core/export` (FFmpeg, miniatura, metadatos), `services` (configuración, historial, vigilante, YouTube, diagnóstico), `utils`. Más detalle en `docs/ARQUITECTURA.md`.
