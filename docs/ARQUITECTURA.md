# Arquitectura de ClutchReel

```
Iniciar.bat ──► scripts/obtener_ffmpeg.py ──► python -m clutchreel
                                                    │
                                              clutchreel/app.py (QApplication, tema, excepthook)
                                                    │
                                        ui/main_window.py (navegación + orquestación)
          ┌──────────────┬──────────────┬───────────┴───────────┬─────────────────┐
     pages/home     pages/wizard   pages/review          pages/export        pages/settings
     (dropzone,     (5 pasos,      (tarjetas, edición,   (cola de trabajos,  (tabs + diagnóstico,
      recientes,     recomendado)   vista previa, undo)   resultado, YouTube) calibración, registro)
      historial)
                                   ui/jobs.py (JobQueue secuencial) ── ui/workers.py (QThread)
                                                    │
        ┌───────────────────────┬───────────────────┼─────────────────────┬──────────────────┐
   core/demo              core/recorder         core/editor           core/export         services
   parser.py (demoparser2) obs_client.py        project.py (Clip,     ffmpeg.py (run,     config.py (JSON %APPDATA%)
   detectors.py (jugadas)  cs2_control.py       Project, UndoStack)   probe, HW)          history.py
   selector.py (duración)  recorder.py          music.py (beats)      builder.py (cmds)   watcher.py (carpeta demos)
   stats.py (K/D, ADR…)    win_input.py                               exporter.py         youtube.py (OAuth)
   models.py                                                          video_check.py      diagnostics.py
                                                                      metadata.py
```

## Flujo de datos

1. **Análisis** (`core/demo/parser.py`): `parse_demo()` → `MatchData` (mapa, tickrate real medido con `game_time`, rondas con alineaciones por ronda, kills con todos los flags, jugadores con `user_id`).
2. **Detección** (`detectors.py`): cada detector produce `Highlight`s (ticks, puntuación, descripción). `merge_highlights()` fusiona solapes de la misma ronda. `selector.py` elige por duración objetivo y ordena.
3. **Proyecto** (`core/editor/project.py`): `Project` = `MatchData` + lista de `Clip` (jugada + recorte + estilo + grabación asociada) + `StyleSettings`. Se serializa a JSON; `UndoStack` guarda instantáneas.
4. **Grabación** (`core/recorder/recorder.py`): por clip → `demo_pause` + `demo_gototick(inicio − 1 s)` → `spec_player` + verificación de cámara → OBS `StartRecord` → 0,6 s → `demo_step_tick N` (t_resume; N = ticks del clip + 0,8 s) → CS2 reproduce exactamente N ticks y pausa solo («Demo paused at engine time X, demo tick Y») → `StopRecord` (ruta). CS2 reproduce las demos a ~57 ticks/s (no 64; medido en 1.41.9), así que la velocidad real se mide por clip (`Clip.recording_tickrate`) y el exportador convierte ticks→segundos con ella. Desfase del clip en el fichero = `(t_resume − t_rec) + latencia_calibrada + margen_previo/velocidad + ajuste_manual`. `video_check.check_clip()` descarta clips vacíos/negros/estáticos; reintento por clip; autoguardado tras cada clip (reanudable).
5. **Exportación** (`core/export/exporter.py`): cada clip → intermedio MP4 normalizado (`clip_command`: recorte, cámara lenta por `setpts`/`atempo`, textos `drawtext`, contador de kills, zoom, 9:16, fundidos) → intro/outro (`card_command`) → unión (`concat` sin recodificar, o `xfade`/`acrossfade`) → música con `sidechaincompress` (ducking), fundidos y `loudnorm` → miniatura.
6. **Publicación** (`services/youtube.py`): subida reanudable por chunks, privada, con miniatura.

## Decisiones

- **Hilos**: todo lo pesado corre en `Worker(QThread)`; la UI solo recibe señales. El grabador pide diálogos al hilo principal mediante `_Bridge` + `threading.Event`.
- **CS2 en Windows**: con CS2 1.41.9 (2026-10) `-netconport` abre sin `-tools` (con `-tools` el juego se cerraba al saltar en la demo). Cadena de respaldo: puerto → teclado (`SendInput` con scancodes + `exec clutchreel`) → semiautomático; sin puerto no se puede leer la consola y los clips se marcan como fallidos (no verificados).
- **Seguir al jugador** (`core/recorder/spectate.py`, verificado en CS2 1.41.9): `spec_player N` sigue al **slot N−1** (`user_id` de demoparser2, resuelto en el tick del clip porque puede cambiar); `spec_player "nombre exacto"` también funciona; `spec_player_by_accountid`, `spec_lock_to_accountid` y `spec_player_by_name` no existen. Verificación doble por la consola: `getpos` = ojo del jugador (Z+64 de pie / +46 agachado) comparado con `parse_ticks` de la demo, y el anuncio «Added TrueView prediction for player slot N (nombre)». Durante la grabación se muestrea `getpos` cada 0,7 s y se vigilan los anuncios; si la cámara cambia con el jugador vivo, el clip se descarta y se reintenta. Al morir el jugador, CS2 muestra 0,8 s la animación y a los ~3 s pasa al asesino: el clip termina 0,8 s tras la muerte.
- **Sincronización**: en vez de confiar en el tiempo exacto de cada comando, se graba con margen y se recorta en la exportación con el desfase calibrado (medido con la detección de movimiento del clip de prueba).
- **Configuración**: dataclasses anidadas → JSON tolerante (claves desconocidas ignoradas, tipos inválidos → valor por defecto). Perfiles = instantáneas de estilo/exportación/detección.
- **Sin tocar el juego**: no hay inyección, ni lectura de memoria, ni plugins; solo el visor oficial y comandos de consola.
