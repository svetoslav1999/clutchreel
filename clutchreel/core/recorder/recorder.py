"""Orquestador de grabación: por cada jugada, posiciona la demo, sigue al jugador,
comprueba que la cámara está en él, graba con OBS y verifica el clip.
Reanudable y con reintentos."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from clutchreel.core.demo.models import PlayerInfo
from clutchreel.core.editor.project import Clip, Project
from clutchreel.core.export.ffmpeg import FFmpeg
from clutchreel.core.export.video_check import ClipCheck, check_clip
from clutchreel.core.recorder.cs2_control import Cs2Controller, Cs2Error
from clutchreel.core.recorder.obs_client import ObsClient, ObsError
from clutchreel.core.recorder.spectate import DemoTimeline, PlaybackCheck, SpectateError, camera_on_target
from clutchreel.services.config import AppConfig
from clutchreel.utils.paths import safe_filename
from clutchreel.utils.timeutil import seconds_to_ticks, ticks_to_seconds
from clutchreel.utils.winutil import free_disk_bytes

log = logging.getLogger(__name__)

StatusFn = Callable[[str, float], None]  # mensaje, fracción 0..1
AskFn = Callable[[str], bool]

PRE_PAD = 1.0  # segundo extra antes de la jugada (se recorta en la exportación)
POST_PAD = 0.8
# Tras morir el jugador, CS2 muestra 0,8 s la animación de muerte, viaja hasta el asesino y a los ~3 s
# cambia la cámara a él (spec_freeze_deathanim_time / spec_freeze_time; medido en CS2 1.41.9).
DEATH_PAD = 0.8
SAMPLE_PERIOD = 0.7  # cada cuánto se pregunta la posición de la cámara durante la grabación
MIN_FREE_BYTES = 2_000_000_000  # una jugada a 1080p60 ocupa ~25 MB/s en OBS; sin margen el clip sale cortado


class RecorderError(Exception):
    pass


def explain_failure(exc: Exception, channel: str = "") -> str:
    """Motivo del fallo de un clip en lenguaje claro y con la acción sugerida."""
    text = str(exc)
    low = text.lower()
    if isinstance(exc, SpectateError):
        hint = f"Cámara en el jugador equivocado: {text}"
    elif "negra" in low:
        hint = "OBS grabó imagen negra: revisa la captura de juego (Game Capture no engancha CS2; abre CS2 con -insecure o usa Window/Display Capture)."
    elif "estática" in low:
        hint = "La demo no avanzó durante la grabación: CS2 no recibió los comandos de reproducción."
        if channel == "keyboard":
            hint += " Se enviaron por teclado simulado; reinicia CS2 desde ClutchReel para usar el puerto de consola."
    elif "sonido" in low:
        hint = f"{text} Revisa en OBS que la fuente «Audio del escritorio» está activa y no silenciada."
    elif isinstance(exc, Cs2Error):
        hint = f"CS2 no respondió por la consola: {text}"
    elif "no existe" in low or "vacía" in low or "no contiene vídeo" in low:
        hint = f"OBS no generó un vídeo válido: {text}"
    else:
        hint = text
    return hint


@dataclass
class ClipPlan:
    """Ticks reales que se graban para un clip."""

    start_tick: int  # donde se coloca la demo (con margen previo)
    play_tick: int  # inicio de la jugada (lo que se exporta)
    end_tick: int  # fin de la grabación útil
    death_tick: int | None = None  # muerte del jugador dentro de la jugada

    @property
    def pre_pad_ticks(self) -> int:
        return self.play_tick - self.start_tick


def plan_clip(project: Project, clip: Clip, tickrate: float) -> ClipPlan:
    """Calcula inicio/fin: margen previo sin salirse de la ronda y fin justo tras la muerte del jugador."""
    hl = clip.highlight
    rnd = project.match.round_by_number(hl.round)
    floor = rnd.start_tick if rnd else 0
    start = max(0, floor, hl.start_tick - seconds_to_ticks(PRE_PAD, tickrate))
    start = min(start, hl.start_tick)
    end = hl.end_tick
    death = next(
        (k.tick for k in project.match.kills if k.victim_steamid == project.player_steamid and hl.start_tick <= k.tick <= hl.end_tick),
        None,
    )
    if death is not None:
        end = min(end, death + seconds_to_ticks(DEATH_PAD, tickrate))
    end = max(end, hl.start_tick + seconds_to_ticks(1.0, tickrate))
    return ClipPlan(start_tick=start, play_tick=hl.start_tick, end_tick=end, death_tick=death)


@dataclass
class RecordJob:
    clip: Clip
    attempts: int = 0
    result: Path | None = None
    check: ClipCheck | None = None
    error: str = ""


@dataclass
class RecordSession:
    project: Project
    jobs: list[RecordJob] = field(default_factory=list)
    channel: str = ""
    capture_mode: str = ""
    started_at: float = field(default_factory=time.time)

    @property
    def done(self) -> int:
        return sum(1 for j in self.jobs if j.result is not None)

    def failed_jobs(self) -> list[RecordJob]:
        return [j for j in self.jobs if j.result is None]

    def job_outcome(self) -> tuple[str, str]:
        """Estado para la cola de trabajos: ``hecho`` / ``parcial`` / ``error`` y el motivo."""
        failed = self.failed_jobs()
        if not failed:
            return "hecho", ""
        reasons = "; ".join(f"ronda {j.clip.highlight.round} ({j.clip.highlight.label}): {j.error or 'motivo desconocido'}" for j in failed)
        status = "error" if self.done == 0 else "parcial"
        return status, f"{self.done}/{len(self.jobs)} clips correctos. {reasons}"


class Recorder:
    """Graba todos los clips pendientes de un proyecto."""

    def __init__(self, config: AppConfig, ask_user: AskFn | None = None, max_attempts: int = 2, ask_yes_no: AskFn | None = None) -> None:
        self.config = config
        self.obs = ObsClient(config.obs, config.paths.obs_path)
        self.cs2 = Cs2Controller(config.cs2, config.paths.cs2_path)
        self.cs2.ask_user = ask_user  # paso manual: muestra comandos para teclear
        self.ask_yes_no = ask_yes_no or ask_user  # pregunta Sí/No (reiniciar o reabrir CS2)
        self.ffmpeg = FFmpeg(config.paths.ffmpeg_path)
        self.cancel = threading.Event()
        self.max_attempts = max_attempts
        self.on_clip_done: Callable[[Clip], None] | None = None
        self.timeline_factory: Callable[[str], DemoTimeline] = DemoTimeline
        self.timeline: DemoTimeline | None = None
        self._relaunches = 0

    # ------------------------------------------------------------- setup ----

    def prepare(self, status: StatusFn) -> tuple[str, str]:
        """Conecta OBS (lanzándolo si procede), prepara escena, lanza CS2 y conecta consola."""
        # ``cancel`` puede haberse sustituido tras construir el grabador (lo hace la cola de trabajos).
        self.cs2.cancel = self.cancel
        self.obs.cancel = self.cancel
        status("Conectando con OBS…", 0.02)
        try:
            self.obs.ensure_connected(allow_launch=self.config.obs.auto_launch)
        except ObsError as exc:
            raise RecorderError(str(exc)) from exc
        capture_mode = ""
        if self.config.obs.manage_scene:
            try:
                capture_mode = self.obs.ensure_scene()
            except ObsError as exc:
                raise RecorderError(str(exc)) from exc
            except Exception as exc:
                raise RecorderError(f"No se pudo preparar la escena de OBS: {exc}") from exc
        rec_dir = Path(self.config.paths.output_folder) / "grabaciones"
        if free_disk_bytes(rec_dir) < MIN_FREE_BYTES:
            raise RecorderError(
                f"Quedan menos de {MIN_FREE_BYTES // 1_000_000_000} GB libres en {rec_dir.anchor or rec_dir}. "
                "Libera espacio o cambia la carpeta de salida en Ajustes → Rutas antes de grabar."
            )
        try:
            self.obs.apply_recording_settings(rec_dir)
        except Exception as exc:  # noqa: BLE001
            log.warning("Ajustes de grabación de OBS no aplicados: %s", exc)

        status("Abriendo Counter-Strike 2…", 0.05)
        if self.cancel.is_set():
            raise RecorderError("Cancelado.")
        try:
            if self.cs2.is_running():
                self._offer_restart(status)
            else:
                self.cs2.launch()
        except Cs2Error as exc:
            raise RecorderError(str(exc)) from exc
        status("Conectando con la consola de CS2…", 0.08)
        try:
            channel = self.cs2.connect_channel()
        except Cs2Error as exc:
            raise RecorderError(str(exc)) from exc
        if channel != "netcon" or not self.cs2.can_read_console:
            log.warning("Sin lectura de la consola de CS2 (canal %s): no se podrá comprobar la cámara", channel)
        return channel, capture_mode

    def _offer_restart(self, status: StatusFn) -> None:
        """CS2 ya está abierto: si le faltan opciones, pide permiso para reiniciarlo (nunca lo cierra sin preguntar)."""
        missing = self.cs2.missing_launch_options()
        if not missing:
            log.info("CS2 ya está en ejecución con las opciones necesarias")
            return
        ask = self.ask_yes_no
        if ask is None:
            log.warning("CS2 abierto sin %s y no hay forma de pedir permiso; se sigue con teclado simulado", ", ".join(missing))
            return
        text = (
            f"CS2 está abierto sin las opciones {', '.join(missing)}, necesarias para controlarlo por consola y comprobar a quién sigue la cámara.\n\n"
            "¿Cerrar CS2 y volver a abrirlo desde ClutchReel?\n\n"
            "Sí: se cierra CS2 (se pierde lo que tengas abierto en el juego) y se reabre con las opciones correctas.\n"
            "No: se intenta con teclado simulado, menos fiable; los clips sin cámara comprobada se marcarán como fallidos."
        )
        if ask(text):
            status("Reiniciando CS2 con las opciones de ClutchReel…", 0.06)
            self.cs2.restart_game()
        else:
            log.warning("El usuario no quiso reiniciar CS2; se sigue con teclado simulado")

    def _load_timeline(self, project: Project, plans: list[ClipPlan], status: StatusFn) -> None:
        """Lee de la demo dónde está cada jugador en los ticks a grabar (para verificar la cámara)."""
        status("Leyendo posiciones de los jugadores en la demo…", 0.09)
        try:
            timeline = self.timeline_factory(project.match.demo_path)
            timeline.load_ranges([(p.start_tick - 32, p.end_tick + 32) for p in plans])
            self.timeline = timeline
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudieron leer las posiciones de la demo: %s", exc)
            self.timeline = None

    # --------------------------------------------------------------- run ----

    def record_project(self, project: Project, status: StatusFn) -> RecordSession:
        session = RecordSession(project=project)
        pending = [c for c in project.enabled_clips() if not c.is_recorded]
        session.jobs = [RecordJob(clip=c) for c in pending]
        if not pending:
            status("Todos los clips ya están grabados.", 1.0)
            return session
        player = project.match.player_by_steamid(project.player_steamid)
        if player is None:
            raise RecorderError("El jugador elegido no aparece en la demo.")
        plans = {job.clip.id: plan_clip(project, job.clip, project.tickrate) for job in session.jobs}

        channel, capture_mode = self.prepare(status)
        session.channel = channel
        session.capture_mode = capture_mode
        try:
            self._load_timeline(project, list(plans.values()), status)
            status("Cargando la demo en CS2…", 0.1)
            try:
                self.cs2.play_demo(Path(project.match.demo_path))
                self.cs2.setup_hud()
            except Cs2Error as exc:
                raise RecorderError(str(exc)) from exc
            self._verify_capture(status)
            total = len(session.jobs)
            for idx, job in enumerate(session.jobs):
                if self.cancel.is_set():
                    raise RecorderError("Grabación cancelada.")
                base = 0.12 + 0.86 * idx / total
                while job.attempts < self.max_attempts:
                    job.attempts += 1
                    label = f"Clip {idx + 1}/{total}: {job.clip.highlight.label} (ronda {job.clip.highlight.round})"
                    status(f"{label} · intento {job.attempts}", base)
                    try:
                        self._record_clip(project, job, player, plans[job.clip.id], status, base, 0.86 / total)
                        break
                    except (Cs2Error, ObsError, RecorderError, SpectateError) as exc:
                        if self.cancel.is_set():
                            # Cancelado por el usuario: el clip no ha fallado (su tarjeta no debe quedar en rojo).
                            log.info("Grabación cancelada durante el clip %s", job.clip.id)
                            raise RecorderError("Grabación cancelada.") from exc
                        job.error = explain_failure(exc, channel)
                        job.clip.recording_ok = False
                        job.clip.camera_note = job.error
                        log.warning("Clip %s falló (intento %d): %s", job.clip.id, job.attempts, exc)
                        if self.cs2.is_running() and not self.cs2.responsive(timeout=5.0):
                            # Colgado: reintentar los demás clips solo alargaría la espera. No se cierra sin permiso.
                            raise RecorderError(
                                "CS2 ha dejado de responder. Ciérralo (o espera a que se recupere) y vuelve a pulsar «Crear vídeo»: "
                                "los clips ya grabados se conservan."
                            ) from exc
                        if not self.cs2.is_running():
                            if not self._may_relaunch():
                                raise RecorderError("CS2 se cerró y no se reabrió; grabación detenida (los clips ya grabados se conservan).") from exc
                            status("CS2 se cerró; reabriendo…", base)
                            try:
                                self._recover_game(project)
                            except Cs2Error as rexc:
                                job.error = explain_failure(rexc, channel)
                                break
                if self.on_clip_done:
                    self.on_clip_done(job.clip)
                try:
                    project.save()
                except OSError as exc:
                    log.warning("No se pudo autoguardar el proyecto: %s", exc)
        finally:
            self._finish()
        ok = sum(1 for j in session.jobs if j.result is not None)
        status(f"Grabación terminada: {ok}/{len(session.jobs)} clips correctos.", 1.0)
        return session

    def _finish(self) -> None:
        """Deja OBS sin grabar y CS2 como estaba (variables restauradas, demo en pausa o juego cerrado)."""
        try:
            if self.obs.connected and self.obs.is_recording():
                self.obs.stop_record()
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.cs2.is_running():
                self.cs2.pause()
                self.cs2.restore_cvars()
        except Exception as exc:  # noqa: BLE001
            log.debug("No se pudo dejar CS2 en pausa: %s", exc)
        if self.config.cs2.close_game_when_done:
            self.cs2.close_game()


    def _may_relaunch(self) -> bool:
        """CS2 se cerró a mitad: se pregunta antes de reabrirlo (puede haberlo cerrado el usuario).

        Sin forma de preguntar (modo automático) se reabre una sola vez por sesión.
        """
        ask = self.ask_yes_no
        if ask is None:
            self._relaunches += 1
            return self._relaunches <= 1
        return ask("CS2 se ha cerrado durante la grabación.\n\n¿Reabrirlo y seguir grabando las jugadas que faltan?")

    def _recover_game(self, project: Project) -> None:
        self.cs2.netcon.close()
        self.cs2.launch()
        self.cs2.connect_channel()
        self.cs2.play_demo(Path(project.match.demo_path))
        self.cs2.setup_hud()

    def _verify_capture(self, status: StatusFn) -> None:
        """Si la fuente de OBS está negra, prueba otros modos de captura."""
        if not self.config.obs.manage_scene:
            return
        settle = 2.0
        for attempt, mode in enumerate(("game", "window", "display")):
            if attempt == 0 and self.config.obs.capture_mode != "game":
                mode = self.config.obs.capture_mode
            # Se mira la imagen cada 0,25 s hasta el plazo (antes se esperaba el plazo entero aunque
            # la captura ya funcionara): el resultado es el mismo, pero sin esperas de sobra.
            deadline = time.monotonic() + settle
            settle = 5.0  # tras cambiar de fuente, OBS tarda en enganchar y renderizar
            brightness = self.obs.source_brightness()
            while brightness is not None and brightness <= 6.0 and time.monotonic() < deadline:
                time.sleep(0.25)
                brightness = self.obs.source_brightness()
            if brightness is None or brightness > 6.0:
                return
            log.warning("La fuente de OBS parece negra (%.1f) con modo %s; probando otro modo", brightness, mode)
            nxt = {"game": "window", "window": "display", "display": "display"}[mode]
            status(f"OBS no captura el juego con «{mode}»; probando «{nxt}»…", 0.1)
            try:
                self.obs.switch_capture_mode(nxt)
            except Exception as exc:  # noqa: BLE001
                log.warning("No se pudo cambiar el modo de captura: %s", exc)
                return

    # ------------------------------------------------------------ camera ----

    def _follow(self, project: Project, player: PlayerInfo, tick: int) -> tuple[str, str]:
        """Pone la cámara sobre el jugador y la verifica. Devuelve ``(método, nombre visto)``."""
        tl = self.timeline
        slot = tl.slot_of(player.steamid64, tick) if tl else None
        if slot is None:
            slot = player.user_id if player.user_id >= 0 else None
        if tl is not None and tl.samples(tick) and not tl.is_alive(player.steamid64, tick):
            raise SpectateError(f"{player.name} está muerto en el tick {tick}; no se le puede seguir.")
        method, match = self.cs2.follow_player(player.steamid64, player.name, slot, tl, tick)
        if method == "sin verificar":
            raise SpectateError(
                "no se pudo comprobar a quién sigue la cámara porque no se puede leer la consola de CS2 "
                "(hace falta el puerto de consola: reinicia CS2 desde ClutchReel)."
            )
        log.info("Cámara en %s (método %s, slot %s, distancia %.1f)", player.name, method, slot, match.target_distance if match else -1)
        return method, (match.name if match else player.name)

    def _check_playback(
        self,
        player: PlayerInfo,
        plan: ClipPlan,
        samples: list[tuple[float, tuple[float, float, float]]],
        t_resume: float,
        tickrate: float,
        changes: list[tuple[float, int, str]] | None = None,
    ) -> PlaybackCheck:
        """Comprueba que la cámara siguió al jugador mientras estaba vivo.

        Dos fuentes: las posiciones muestreadas con ``getpos`` y los cambios de cámara que
        anuncia CS2 en la consola («Added TrueView prediction for player slot N (nombre)»).
        """
        result = PlaybackCheck()
        tl = self.timeline
        latency = float(self.config.cs2.command_latency)
        last_alive = (plan.death_tick - seconds_to_ticks(0.3, tickrate)) if plan.death_tick is not None else plan.end_tick
        alive_seconds = ticks_to_seconds(min(last_alive, plan.end_tick) - plan.start_tick, tickrate) + latency
        if changes is not None:
            result.min_ratio = 0.6  # los anuncios de CS2 cubren los cambios de jugador; getpos solo confirma
        for t, _slot, name in changes or []:
            rel = t - t_resume
            if 0.0 <= rel <= alive_seconds and name and name != player.name:
                result.switches.append((rel, name))
        if tl is None:
            return result
        # El tick estimado por reloj se desvía (la demo no avanza exactamente en tiempo real), así que
        # se busca al jugador en una ventana de ±1,5 s alrededor de la estimación.
        window = seconds_to_ticks(1.5, tickrate)
        for t, pos in samples:
            est = plan.start_tick + int((t - t_resume - latency) * tickrate)
            if est < plan.start_tick + 8 or est > min(last_alive, plan.end_tick):
                continue
            match = tl.identify(pos, est, window=window, target=player.steamid64)
            result.samples += 1
            if camera_on_target(match, player.steamid64, tolerance=64.0):
                result.on_target += 1
            else:
                result.off_target.append((t - t_resume, match.name if match and match.distance < 64 else ""))
        return result

    # -------------------------------------------------------------- clip ----

    def _record_clip(self, project: Project, job: RecordJob, player: PlayerInfo, plan: ClipPlan, status: StatusFn, base: float, span: float) -> None:
        clip = job.clip
        hl = clip.highlight
        tickrate = project.tickrate
        if plan.end_tick < hl.end_tick:
            log.info("El jugador muere en el tick %s: el clip termina en %s en vez de %s", plan.death_tick, plan.end_tick, hl.end_tick)
            hl.end_tick = plan.end_tick
        cs2 = self.cs2.settings

        status(f"Buscando tick {plan.start_tick}…", base + span * 0.1)
        reached = self.cs2.goto_tick(plan.start_tick)
        status(f"Siguiendo a {player.name}…", base + span * 0.18)
        method, seen = self._follow(project, player, reached if reached is not None else plan.start_tick)
        if self.cancel.is_set():
            raise RecorderError("Grabación cancelada.")

        status("Grabando…", base + span * 0.25)
        self.obs.start_record()
        try:
            t_rec = time.perf_counter()
            time.sleep(0.6)
            n_changes_before = len(self.cs2.camera_changes)
            # Se reproducen exactamente los ticks del clip (+ margen final): CS2 pausa solo al llegar y lo
            # anuncia por la consola. Así el final no depende de la velocidad real de reproducción.
            play_ticks = (plan.end_tick - plan.start_tick) + seconds_to_ticks(POST_PAD, tickrate)
            self.cs2.play_ticks(play_ticks)
            t_resume = time.perf_counter()
            nominal_wait = ticks_to_seconds(play_ticks, tickrate)
            deadline = t_resume + nominal_wait * 1.6 + 6.0  # por si CS2 no anuncia la pausa
            samples: list[tuple[float, tuple[float, float, float]]] = []
            next_sample = t_resume + 0.4
            paused: tuple[float, int | None] | None = None
            last_status = -1
            while time.perf_counter() < deadline:
                if self.cancel.is_set():
                    raise RecorderError("Grabación cancelada.")
                if not self.cs2.is_running():
                    raise Cs2Error("CS2 se cerró durante la grabación.")
                now = time.perf_counter()
                if self.cs2.can_read_console and now >= next_sample:
                    pos = self.cs2.camera_position()
                    if pos is not None:
                        samples.append(((now + time.perf_counter()) / 2.0, pos))  # getpos tarda: se usa el instante medio
                    next_sample = now + SAMPLE_PERIOD
                paused = self.cs2.pause_after(t_resume + 0.2)
                if paused is not None:
                    break
                elapsed = time.perf_counter() - t_resume
                if int(elapsed) != last_status:  # un aviso por segundo basta (antes, 20 por segundo)
                    last_status = int(elapsed)
                    status(f"Grabando… {elapsed:.0f}/{nominal_wait:.0f} s", base + span * (0.25 + 0.6 * min(1.0, elapsed / nominal_wait)))
                time.sleep(0.05)
            latency = float(cs2.command_latency)
            if paused is None:
                self.cs2.pause()
                rate = tickrate
                log.warning("CS2 no anunció la pausa al final del clip; se usa el tickrate nominal (%.0f)", tickrate)
            else:
                t_pause, demo_tick = paused
                rate = play_ticks / max(0.5, t_pause - t_resume - latency)
                if not (0.5 * tickrate <= rate <= 1.5 * tickrate):
                    log.warning("Velocidad de reproducción medida fuera de rango (%.1f ticks/s); se usa %.0f", rate, tickrate)
                    rate = tickrate
                log.info("Clip reproducido a %.1f ticks/s (nominal %.0f); CS2 pausó en el tick de demo %s", rate, tickrate, demo_tick)
            time.sleep(0.3)
            path = self.obs.stop_record()
        except BaseException:
            self._abort_recording()
            raise
        if path is None:
            raise ObsError("OBS no devolvió la ruta de la grabación.")
        pre_pad = ticks_to_seconds(plan.pre_pad_ticks, rate)
        offset = (t_resume - t_rec) + latency + pre_pad + float(cs2.start_offset)

        status("Comprobando la cámara…", base + span * 0.88)
        if self.cs2.can_read_console:
            self.cs2.netcon.read(0.05, 0.3)  # recoge los últimos anuncios de cámara
        changes = self.cs2.camera_changes[n_changes_before:] if self.cs2.can_read_console else None
        playback = self._check_playback(player, plan, samples, t_resume, rate, changes)
        if not playback.ok():
            self._discard(path)
            raise SpectateError(f"durante la grabación {playback.describe()}.")
        status("Comprobando el clip…", base + span * 0.9)
        check = check_clip(self.ffmpeg, path, expected_duration=ticks_to_seconds(play_ticks, rate) + (t_resume - t_rec))
        job.check = check
        if not check.ok:
            self._discard(path)
            raise RecorderError(check.reason)
        final_path = self._rename_recording(path, project, clip)
        clip.recording_path = str(final_path)
        clip.recording_offset = max(0.0, offset)
        clip.recording_tickrate = rate
        clip.recording_ok = True
        clip.recorded_player_steamid = player.steamid64
        clip.recorded_player_name = seen or player.name
        clip.camera_verified = True
        clip.camera_note = f"{method}; {playback.on_target}/{playback.samples} muestras en el jugador" if playback.samples else method
        job.result = final_path
        job.error = ""
        log.info("Clip %s grabado en %s (offset %.2f s, %.1f ticks/s, cámara: %s)", clip.id, final_path, offset, rate, clip.camera_note)

    def _abort_recording(self) -> None:
        """Para la grabación que quedó a medias (fallo o cancelación) y borra su fichero incompleto."""
        try:
            if self.obs.connected and self.obs.is_recording():
                partial = self.obs.stop_record()
                if partial is not None:
                    self._discard(partial)
        except Exception as exc:  # noqa: BLE001
            log.warning("No se pudo parar la grabación interrumpida: %s", exc)

    @staticmethod
    def _discard(path: Path) -> None:
        """Borra una grabación descartada para no llenar el disco de clips inválidos."""
        try:
            path.unlink()
        except OSError:
            pass

    @staticmethod
    def _rename_recording(path: Path, project: Project, clip: Clip) -> Path:
        name = safe_filename(f"{project.player_name} R{clip.highlight.round:02d} {clip.highlight.kind} {clip.id[:6]}")
        target = path.with_name(f"{name}{path.suffix}")
        try:
            if target.exists():
                target.unlink()
            path.rename(target)
            return target
        except OSError:
            return path

    # ------------------------------------------------------- calibration ----

    def calibrate(self, project: Project, status: StatusFn) -> tuple[float, Path]:
        """Graba un clip de prueba y mide la latencia entre ``demo_resume`` y el primer movimiento."""
        player = project.match.player_by_steamid(project.player_steamid)
        if player is None:
            raise RecorderError("El jugador elegido no aparece en la demo.")
        clips = project.enabled_clips() or project.clips
        if not clips:
            raise RecorderError("No hay jugadas para probar.")
        clip = max(clips, key=lambda c: c.highlight.score)
        plan = plan_clip(project, clip, project.tickrate)
        self.prepare(status)
        try:
            self._load_timeline(project, [plan], status)
            status("Cargando la demo…", 0.2)
            try:
                self.cs2.play_demo(Path(project.match.demo_path))
                self.cs2.setup_hud()
            except Cs2Error as exc:
                raise RecorderError(str(exc)) from exc
            self._verify_capture(status)
            status("Posicionando la demo…", 0.4)
            reached = self.cs2.goto_tick(plan.start_tick)
            try:
                _method, seen = self._follow(project, player, reached if reached is not None else plan.start_tick)
            except SpectateError as exc:
                raise RecorderError(f"Cámara en el jugador equivocado: {exc}") from exc
            time.sleep(1.0)
            status("Grabando clip de prueba (6 s)…", 0.6)
            self.obs.start_record()
            try:
                t_rec = time.perf_counter()
                time.sleep(1.5)
                self.cs2.resume()
                t_resume = time.perf_counter()
                time.sleep(6.0)
                self.cs2.pause()
                path = self.obs.stop_record()
            except BaseException:
                self._abort_recording()
                raise
            if path is None:
                raise RecorderError("OBS no devolvió la ruta del clip de prueba.")
            status("Analizando el clip…", 0.85)
            check = check_clip(self.ffmpeg, path, expected_duration=6.0 + (t_resume - t_rec))
            if not check.ok:
                raise RecorderError(f"El clip de prueba no es válido: {check.reason}")
            if check.motion_start is None:
                raise RecorderError("No se detectó movimiento en el clip de prueba; revisa que la demo avanza.")
            latency = check.motion_start - (t_resume - t_rec)
            latency = max(0.0, min(3.0, latency))
            self.config.cs2.command_latency = round(latency, 2)
            status(f"Latencia medida: {latency:.2f} s · cámara en {seen}", 1.0)
            return latency, path
        finally:
            self._finish()
