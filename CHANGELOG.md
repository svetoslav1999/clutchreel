# Cambios

Formato: versión, fecha y cambios agrupados. Cómo actualizar: sección «Actualizar» del `README.md`.

## 1.1.1 — 2026-10-29

- **Python 3.12 o superior.** Las dependencias fijadas (numpy 2.5) no existen para Python 3.11 y la
  instalación fallaba; `Iniciar.bat`, el README y `pyproject.toml` lo exigen ahora.
- README para el repositorio público: instalación con Git o descargando el ZIP, aviso de que FFmpeg
  es un programa aparte (GPL-3.0) que se descarga de gyan.dev, y una ruta mal escrita corregida.
- `pyproject.toml` declara la licencia MIT y el autor.
- README nuevo para el repositorio público: qué es y para qué sirve, capturas, recorrido animado,
  diagrama del proceso, tipos de jugada con su color, guía paso a paso y preguntas frecuentes.
  Guías `CONTRIBUTING.md` y `SECURITY.md`, y plantillas de issue que piden tachar datos personales.
- Inicio: al refrescar, el historial ya no muestra un instante las líneas antiguas encima de las nuevas.
- Cola: la tabla de trabajos ya no se aplasta cuando se muestra el último vídeo creado.
- README: apartado «En desarrollo activo» con lo próximo y cómo seguir el proyecto; aviso de que
  la descarga de FFmpeg puede tardar varios minutos.

## 1.1.0 — 2026-10-27

Probado en Windows 11 con CS2 1.41.9, OBS 33.0.0 (obs-websocket 5.7.6) y una GPU RTX 4060 Ti:
dos pasadas completas con «Crear vídeo» y 5 jugadas, 5/5 clips con la cámara verificada en el
jugador, con audio, sin negro, y el vídeo final decodificado sin errores.

### Errores corregidos (de más a menos grave)

1. **La contraseña de OBS acababa en el registro.** La librería anterior la escribía en INFO al
   conectar. Ahora un filtro tacha cualquier secreto en registro, consola e informe de errores, y el
   cliente nuevo no la registra nunca (tampoco va por línea de comandos).
2. **Grabaciones a medias y procesos huérfanos.** Si algo fallaba o se cancelaba con OBS grabando, la
   grabación seguía y quedaba un fichero incompleto; FFmpeg podía quedarse abierto. Ahora se para
   la grabación, se borra el fichero incompleto y FFmpeg nunca queda huérfano.
3. **Cancelar no llegaba a todas las esperas** (arranque de CS2 y OBS, carga de la demo, saltos). Al
   cerrar la app con un trabajo en marcha se espera a que OBS pare y CS2 quede restaurado. Cancelar ya
   no marca el clip como fallido.
4. **Salto sin confirmación:** `goto_tick` no esperaba nunca al salto cuando no podía leer la consola.
5. **Barra del reproductor en todos los clips** con CS2 recién abierto (la lectura de
   `demo_ui_mode` caducaba). Ahora se reintenta, se aplica igualmente y, si no se pudo leer, al
   terminar se restaura su valor por defecto.
6. **«Ya tengo la grabación»** omitía en silencio las jugadas que caían fuera del vídeo; ahora avisa
   de cuáles y exige un vídeo que exista.
7. **Textos del vídeo:** los caracteres sin glifo (p. ej. «♛») salían como cuadros; en Shorts 9:16 el
   título y los textos se salían del encuadre.
8. **5 kills con ACE desactivado:** la etiqueta decía «4K» y la descripción «5K»; ahora «5K» en todo.
9. **Asistente:** ya no preselecciona a otro jugador si no reconoce tu cuenta.
10. **Interfaz:** tarjetas que no se reajustaban al encoger la ventana, panel de edición y pista de
    Revisión cortados a tamaño mínimo, texto del clip seleccionado solapado, nombres con «<» en el
    historial, reabrir un proyecto ya no salta a la Cola.
11. **Robustez:** historial y proyectos dañados no bloquean la app, historial guardado de forma
    atómica, intermedios de exportaciones abortadas se limpian, una sola entrada de deshacer por gesto.

### Optimización

Misma demo (Premier, 220 MB, de_mirage) y mismas 5 jugadas, de soltar la demo a vídeo exportado:

| Etapa | 1.0.0 | 1.1.0 |
|---|---|---|
| Análisis de la demo (trabajo completo) | 6,7 s | 1,2 s; 0,01 s si ya estaba en caché |
| Análisis puro (lectura de eventos) | 2,07 s | 1,08 s |
| Grabación de los 5 clips | 145,8 s | 134,9 s |
| Exportación | 232,3 s | 27,9 s |
| **Total** | **387,7 s** | **165–167 s** |

La medida de la 1.0.0 lanzó CS2 desde cero (22 s hasta la consola, 2,8 s de carga de la demo); las de
la 1.1.0 reutilizaron el CS2 abierto (menos de 1 s hasta la consola, 13–15 s de carga de la demo).

- Exportación: con CS2 en primer plano y la demo en pausa la GPU iba al 100 % y cada clip se exportaba
  15 veces más lento (98,6 s frente a 6,5 s). Al terminar de grabar ClutchReel se trae al frente y CS2
  se frena solo. (Minimizar CS2 lo congelaba: se descartó.)
- Análisis en una sola pasada de eventos con resultado idéntico, caché por huella de la demo, numpy
  cargado solo cuando hace falta, huella de las demos memorizada en Inicio.
- Comprobación de la captura de OBS por sondeo en vez de una espera fija de 2 s; progreso limitado a
  10 avisos por segundo.
- La carga de la demo dentro de CS2 tarda unos 3 s con el juego recién abierto y 10–14 s si lleva
  horas abierto: depende de CS2, no de ClutchReel.

### Diseño

- Identidad visual propia: tema oscuro y claro con contraste comprobado, Bahnschrift para títulos y
  cifras, color por tipo de jugada en tarjetas y miniaturas.
- Tarjetas con miniatura 16:9 real de la grabación, textos recortados con el completo al pasar el
  ratón, iconos de línea en vez de emojis, monograma propio como icono.
- Zona de arrastre tipo claqueta, barra de pasos en el asistente, cola con iconos de estado.

### Cliente OBS propio

- Sustituye a `obsws-python` (GPL-3.0) por un cliente del protocolo obs-websocket 5 escrito según la
  especificación oficial, sobre `websocket-client` (Apache-2.0). La app no cambia por fuera.
- Al actualizar, `Iniciar.bat` y `Actualizar.bat` instalan `websocket-client` y desinstalan
  `obsws-python`.

### Licencia

- ClutchReel pasa a ser software libre bajo la licencia **MIT** (`LICENSE`). Inventario de
  dependencias y sus licencias en `THIRD_PARTY_NOTICES.md`; ninguna con copyleft fuerte.
- El ejecutable opcional se genera como carpeta (Qt/PySide6 bajo LGPL-3.0) y ya no incluye FFmpeg.

### Actualización

- `Actualizar.bat` nuevo: descarga la última versión sin descartar cambios locales y actualiza las
  dependencias.
- `Iniciar.bat` reinstala las dependencias cuando cambia el contenido de `requirements.txt` (antes
  dependía de la fecha del fichero) y quita las que ya no se usan.
- La configuración de la 1.0.0 (`%APPDATA%\ClutchReel`) se conserva tal cual.

## 1.0.0 — 2026-10-26

Primera versión: demos de CS2 a vídeos de mejores jugadas con OBS.
