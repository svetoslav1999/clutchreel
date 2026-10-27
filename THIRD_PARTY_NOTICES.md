# Avisos de software de terceros

ClutchReel se distribuye bajo la licencia MIT (ver `LICENSE`). Usa las bibliotecas y programas
que se listan aquí, cada uno con su propia licencia. Los textos completos están en la distribución
de cada paquete (carpeta `*.dist-info/licenses` dentro de `.venv` o de `dist\ClutchReel`) y en los
enlaces indicados. Inventario revisado el 2026-10-27 con las versiones fijadas en `requirements.txt`
(auditoría de metadatos de `pip`, SBOM CycloneDX de demoparser2 y repositorios de origen).

**No hay dependencias con copyleft fuerte (GPL/AGPL) en el programa distribuido.** PyInstaller
(GPLv2 con excepción expresa para los ejecutables que genera) se usa solo para construir.

## Bibliotecas incluidas en la aplicación

| Paquete | Versión | Licencia | Notas |
|---|---|---|---|
| PySide6 / PySide6_Essentials / PySide6_Addons / shiboken6 | 6.12.0 | LGPL-3.0-only (también GPL-2.0 o comercial) | Enlace dinámico. Ver la sección «Qt / PySide6 (LGPL)». https://www.qt.io/licensing |
| demoparser2 | 0.42.1 | MIT | Repositorio https://github.com/LaihoE/demoparser (fichero `LICENSE`). El wheel no declara licencia en sus metadatos; incluye un SBOM CycloneDX con sus 192 crates de Rust, todos bajo licencias permisivas (MIT, Apache-2.0, BSD, Zlib, Unlicense, BSL-1.0, Unicode-3.0) salvo `smartstring` 1.0.1 (MPL-2.0, sin modificar) y `polars-arrow-format` 0.1.0 (Apache-2.0 por su fichero `LICENSE`; crates.io lo muestra como «non-standard» porque usa `license-file`). `csgoproto` y `parser` son crates del propio demoparser2. |
| websocket-client | 1.9.2 | Apache-2.0 | Transporte del cliente propio de obs-websocket (`clutchreel/core/recorder/obsws.py`). https://github.com/websocket-client/websocket-client |
| pandas | 3.1.0 | BSD-3-Clause | Incluye componentes con licencias BSD/MIT propias (ver `pandas/LICENSES`). |
| numpy | 2.5.4 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 | |
| polars, polars-runtime-32 | 2.1.0 | MIT | Dependencia de demoparser2. |
| pyarrow | 26.0.0 | Apache-2.0 | Dependencia de demoparser2. Incluye `NOTICE.txt`. |
| tqdm | 4.70.1 | MPL-2.0 AND MIT | Dependencia de demoparser2, sin modificar. |
| colorama | 0.4.6 | BSD-3-Clause | |
| psutil | 7.2.2 | BSD-3-Clause | |
| google-api-python-client, google-auth, google-auth-oauthlib, google-auth-httplib2, google-api-core, googleapis-common-protos, proto-plus | ver `requirements.txt` | Apache-2.0 | Subida opcional a YouTube. |
| opentelemetry-api | 1.45.1 | Apache-2.0 | |
| protobuf | 7.36.2 | BSD-3-Clause | |
| requests | 2.34.2 | Apache-2.0 | Incluye `NOTICE`. |
| requests-oauthlib | 2.0.0 | ISC | |
| oauthlib | 4.0.0 | BSD-3-Clause | |
| httplib2 | 0.32.0 | MIT | |
| urllib3 | 2.8.0 | MIT | |
| certifi | 2026.10.23 | MPL-2.0 | Sin modificar. |
| charset-normalizer | 3.5.2 | MIT | |
| idna | 3.20 | BSD-3-Clause | |
| cryptography | 50.0.2 | Apache-2.0 OR BSD-3-Clause | |
| cffi | 2.1.1 | MIT-0 | |
| pycparser | 3.12 | BSD-3-Clause | |
| pyasn1, pyasn1_modules | 0.6.4 / 0.4.2 | BSD-2-Clause | |
| uritemplate | 4.2.0 | BSD-3-Clause OR Apache-2.0 | |
| pyparsing | 3.3.3 | MIT | |
| python-dateutil | 3.0.0 | BSD-3-Clause / Apache-2.0 (doble) | |
| six | 1.17.0 | MIT | |
| typing_extensions | 4.16.0 | PSF-2.0 | |
| tzdata | 2026.5 | Apache-2.0 | |

## Qt / PySide6 (LGPL-3.0)

Qt y PySide6 se usan bajo la LGPL-3.0. Para que puedas ejercer los derechos que da esa licencia:

- ClutchReel no modifica Qt ni PySide6 y los enlaza **dinámicamente** (ficheros `Qt6*.dll`,
  `PySide6/*.pyd`, `shiboken6/*.pyd`).
- El ejecutable se construye como **carpeta** (`dist\ClutchReel\`), no como un único fichero, de modo
  que puedes sustituir las bibliotecas de Qt/PySide6 por otras versiones compatibles.
- PySide6 incluye el plugin multimedia de Qt basado en FFmpeg (`PySide6/plugins/multimedia/ffmpegmediaplugin.dll`,
  compilación LGPL de Qt) para la vista previa en la interfaz; no es el FFmpeg que ClutchReel usa para exportar.
- El código fuente de Qt está en https://code.qt.io y el de PySide6 en
  https://code.qt.io/cgit/pyside/pyside-setup.git ; el texto de la LGPL-3.0 en
  https://www.gnu.org/licenses/lgpl-3.0.html

## Programas externos (no se distribuyen con ClutchReel)

- **FFmpeg** (https://ffmpeg.org): ClutchReel lo ejecuta como proceso aparte. No se incluye en el
  repositorio ni en `dist\ClutchReel`; `Iniciar.bat` lo descarga en `tools\ffmpeg` desde la
  compilación indicada en `scripts\obtener_ffmpeg.py` (las compilaciones habituales para Windows son
  GPL por los códecs que incorporan). Puedes usar en su lugar cualquier FFmpeg que tengas instalado
  (Ajustes → Rutas).
- **OBS Studio** (GPL-2.0, https://obsproject.com) y **Counter-Strike 2 / Steam** (Valve
  Corporation): programas del usuario, controlados por sus interfaces públicas (obs-websocket y el
  puerto de consola). ClutchReel no los incluye ni los modifica.

## Herramientas de construcción (no se incluyen en la aplicación)

| Paquete | Versión | Licencia |
|---|---|---|
| PyInstaller | 6.22.3 | GPLv2-or-later con excepción para los programas empaquetados (`COPYING.txt`) |
| pyinstaller-hooks-contrib | 2026.9 | Apache-2.0 / GPLv2 |
| setuptools | 84.2.1 | MIT |
| packaging | 26.3 | Apache-2.0 OR BSD-2-Clause |
| pefile | 2024.8.26 | MIT |
| altgraph | 0.17.5 | MIT |
| pywin32-ctypes | 0.2.3 | BSD-3-Clause |
| pytest, ruff, mypy | ver `requirements-dev.txt` | MIT |

## Recursos

- Las fuentes, iconos y música incluidos en `assets/` son propios o de dominio público; la música del
  usuario (`assets/music`) no se distribuye.
