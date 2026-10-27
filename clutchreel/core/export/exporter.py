"""Exportador: proyecto + grabaciones → vídeo final (con progreso y cancelación)."""

from __future__ import annotations

import logging
import shutil
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from clutchreel.core.demo.models import KIND_LABELS, Highlight
from clutchreel.core.editor.music import detect_beats, pick_track
from clutchreel.core.editor.project import Clip, Project
from clutchreel.core.export import builder as b
from clutchreel.core.export.ffmpeg import FFmpeg, FFmpegError
from clutchreel.core.export.metadata import pretty_map
from clutchreel.services.config import AppConfig
from clutchreel.utils.paths import cache_dir, safe_filename
from clutchreel.utils.timeutil import ticks_to_seconds
from clutchreel.utils.winutil import free_disk_bytes

log = logging.getLogger(__name__)

ProgressFn = Callable[[float, str], None]


class ExportError(Exception):
    pass


@dataclass
class ExportResult:
    video: Path
    thumbnail: Path | None
    duration: float
    elapsed: float


def _remove_stale_exports(cache: Path, older_than: float = 6 * 3600) -> None:
    """Borra intermedios de exportaciones que no terminaron (la app se cerró o se colgó a mitad)."""
    now = time.time()
    for d in cache.glob("export_*"):
        try:
            if d.is_dir() and now - d.stat().st_mtime > older_than:
                shutil.rmtree(d, ignore_errors=True)
                log.info("Intermedios antiguos borrados: %s", d.name)
        except OSError:
            continue


def _clip_source(project: Project, clip: Clip) -> tuple[Path, float] | None:
    """Fichero de vídeo y segundo donde empieza la jugada dentro de él."""
    if project.recording_mode == "existing" and project.existing_recording:
        src = Path(project.existing_recording)
        if src.exists():
            start = project.existing_recording_offset + clip.highlight.start_seconds(project.tickrate)
            return src, start
        return None
    if clip.is_recorded:
        return Path(clip.recording_path), clip.recording_offset
    return None


def thumbnail_title(hl: Highlight) -> str:
    """Título corto para la miniatura: solo la jugada principal (la lista de tipos fusionados no cabe)."""
    kinds = hl.merged_kinds or [hl.kind]
    return KIND_LABELS.get(kinds[0], kinds[0])


def _overlay_for(clip: Clip, hl: Highlight, project: Project) -> list[b.TextOverlay]:
    overlays: list[b.TextOverlay] = []
    text = clip.overlay_text.strip() or f"{hl.label} · Ronda {hl.round}"
    overlays.append(b.TextOverlay(text=text, start=0.3, end=3.5, position="top", size=44))
    return overlays


class Exporter:
    def __init__(self, config: AppConfig, ffmpeg: FFmpeg | None = None) -> None:
        self.config = config
        self.ffmpeg = ffmpeg or FFmpeg(config.paths.ffmpeg_path)
        self.cancel = threading.Event()

    def export(self, project: Project, progress: ProgressFn | None = None) -> ExportResult:
        t0 = time.time()
        cfg = self.config

        def report(frac: float, msg: str) -> None:
            if progress:
                progress(max(0.0, min(1.0, frac)), msg)

        if not self.ffmpeg.available:
            raise ExportError("FFmpeg no está disponible. Ejecuta Iniciar.bat o configura la ruta en Ajustes.")
        clips = [c for c in project.enabled_clips() if _clip_source(project, c) is not None]
        if not clips:
            raise ExportError("No hay clips con grabación. Graba primero las jugadas o selecciona un vídeo existente.")

        out_dir = Path(cfg.paths.output_folder or ".")
        out_dir.mkdir(parents=True, exist_ok=True)
        if free_disk_bytes(out_dir) < 2_000_000_000:
            raise ExportError("Quedan menos de 2 GB libres en la carpeta de salida. Libera espacio antes de exportar.")
        _remove_stale_exports(cache_dir())
        work = Path(tempfile.mkdtemp(prefix="export_", dir=str(cache_dir())))
        try:
            return self._export(project, clips, out_dir, work, report, t0)
        finally:
            shutil.rmtree(work, ignore_errors=True)  # también si falla o se cancela: son GB de intermedios

    def _export(self, project: Project, clips: list[Clip], out_dir: Path, work: Path, report: Callable[[float, str], None], t0: float) -> ExportResult:
        cfg = self.config
        preset = project.export_preset or cfg.export.preset
        encoder = self.ffmpeg.pick_video_encoder(cfg.export.codec, cfg.export.hw_accel)
        enc = b.encode_settings_for(preset, encoder, cfg.export.quality, cfg.export.bitrate_kbps)
        enc.aspect = "9:16" if preset.startswith("shorts") else enc.aspect
        style = project.style
        report(0.02, f"Codificador: {encoder}")

        # 1) Clips intermedios ----------------------------------------------
        intermediates: list[Path] = []
        durations: list[float] = []
        rendered: list[Clip] = []
        beats: list[float] = []
        music = pick_track(cfg.paths.music_folder, style.music_track) if style.music_enabled else None
        if style.beat_sync and music:
            beats = detect_beats(music)
        total_clips = len(clips)
        for idx, clip in enumerate(clips):
            if self.cancel.is_set():
                raise ExportError("Exportación cancelada.")
            src_info = _clip_source(project, clip)
            assert src_info is not None
            src, start = src_info
            info = self.ffmpeg.probe(src)
            hl = clip.highlight
            # En las grabaciones propias los ticks avanzan al ritmo real medido al grabar (no al nominal).
            rate = clip.effective_tickrate(project.tickrate) if project.recording_mode != "existing" else project.tickrate
            base_dur = hl.duration_seconds(rate)
            trim_start = start + clip.trim_start
            trim_end = start + base_dur - clip.trim_end
            if info.duration > 0:
                trim_end = min(trim_end, info.duration)
            if trim_end - trim_start < 0.5:
                log.warning("Clip %s demasiado corto tras recortar; se omite", clip.id)
                continue
            key_rel = ticks_to_seconds(hl.key_tick - hl.start_tick, rate) - clip.trim_start
            slow_at = key_rel if (style.slow_motion and clip.slow_motion and 0 < key_rel < trim_end - trim_start) else None
            kill_times = [ticks_to_seconds(k.tick - hl.start_tick, rate) - clip.trim_start for k in hl.kills]
            fade = style.transition_duration if (style.transitions and style.transition_type == "fade") else 0.0
            spec = b.ClipRenderSpec(
                source=src,
                output=work / f"clip_{idx:03d}.mp4",
                trim_start=trim_start,
                trim_end=trim_end,
                has_audio=info.has_audio,
                game_volume=style.game_volume * clip.game_volume,
                slow_motion_at=slow_at,
                slow_motion_factor=style.slow_motion_factor,
                slow_motion_seconds=style.slow_motion_seconds,
                zoom=clip.zoom,
                overlays=_overlay_for(clip, hl, project),
                kill_times=kill_times,
                kill_counter=style.kill_counter,
                fade_in=fade if clip.transition_in != "none" else 0.0,
                fade_out=fade if clip.transition_out != "none" else 0.0,
                font_family=style.font_family,
            )
            # Ajuste de duración al ritmo (si procede) acortando el final.
            if beats:
                desired = b.ClipRenderSpec.output_duration(spec)
                snapped = self._snap_to_beats(desired, beats, sum(durations))
                if snapped < desired - 0.05:
                    spec.trim_end -= desired - snapped
            frac_base = 0.05 + 0.6 * idx / total_clips
            report(frac_base, f"Renderizando clip {idx + 1}/{total_clips}: {hl.label}")
            def clip_progress(f: float, _m: str, fb: float = frac_base) -> None:
                report(fb + 0.6 * f / total_clips, "")

            self.ffmpeg.run(b.clip_command(spec, enc), total_duration=spec.output_duration(), progress=clip_progress, cancel=self.cancel)
            intermediates.append(spec.output)
            rendered.append(clip)
            durations.append(self.ffmpeg.probe(spec.output).duration or spec.output_duration())
        if not intermediates:
            raise ExportError("Ningún clip pudo renderizarse.")

        # 2) Intro / outro ----------------------------------------------------
        map_label = pretty_map(project.match.map_name)
        title = style.intro_title.strip() or f"{project.player_name} · {map_label}"
        logo = Path(style.watermark_path) if style.watermark_path else None
        parts: list[Path] = []
        part_durs: list[float] = []
        if style.intro_enabled:
            report(0.67, "Creando intro…")
            intro = work / "intro.mp4"
            subtitle = f"Highlights Premier · {project.match.score_label()}" + (f" · {style.channel_name}" if style.channel_name else "")
            self.ffmpeg.run(b.card_command(intro, enc, title, subtitle, 3.0, style.font_family, logo=logo), cancel=self.cancel)
            parts.append(intro)
            part_durs.append(3.0)
        parts += intermediates
        part_durs += durations
        if style.outro_enabled:
            report(0.7, "Creando cierre…")
            outro = work / "outro.mp4"
            sub = style.channel_name or "Gracias por ver"
            self.ffmpeg.run(b.card_command(outro, enc, "GG", sub, 3.0, style.font_family, logo=logo), cancel=self.cancel)
            parts.append(outro)
            part_durs.append(3.0)

        # 3) Unión -------------------------------------------------------------
        report(0.72, "Uniendo clips…")
        joined = work / "joined.mp4"
        use_xfade = style.transitions and style.transition_type not in ("fade", "none") and len(parts) <= 40
        overlap = b.xfade_duration(part_durs, style.transition_duration) if use_xfade and len(parts) > 1 else 0.0
        if use_xfade:
            self.ffmpeg.run(
                b.xfade_command(parts, part_durs, joined, enc, style.transition_type, style.transition_duration),
                total_duration=sum(part_durs),
                progress=lambda f, _m: report(0.72 + 0.12 * f, ""),
                cancel=self.cancel,
            )
        else:
            lst = work / "concat.txt"
            b.write_concat_list(parts, lst)
            self.ffmpeg.run(b.concat_command(lst, joined), cancel=self.cancel)
        total = self.ffmpeg.probe(joined).duration or sum(part_durs)

        # 4) Música + loudnorm --------------------------------------------------
        report(0.85, "Mezclando audio…")
        stamp = time.strftime("%Y-%m-%d_%H-%M")
        base_name = safe_filename(f"{project.player_name} {map_label} {stamp}")
        final = out_dir / f"{base_name}.mp4"
        counter = 1
        while final.exists():
            counter += 1
            final = out_dir / f"{base_name} ({counter}).mp4"
        self.ffmpeg.run(
            b.music_mix_command(joined, music, final, total, style.music_volume, style.ducking, style.fade_seconds, cfg.export.loudnorm, 1.0),
            total_duration=total,
            progress=lambda f, _m: report(0.85 + 0.12 * f, ""),
            cancel=self.cancel,
        )

        # 5) Miniatura ---------------------------------------------------------------
        thumb: Path | None = None
        if cfg.export.thumbnail:
            report(0.98, "Creando miniatura…")
            best = max(rendered, key=lambda c: c.highlight.score)
            offset = 0.0
            if style.intro_enabled:
                offset += 3.0 - overlap  # con xfade cada transición solapa las dos partes
            for c, d in zip(rendered, durations, strict=True):
                if c is best:
                    break
                offset += d - overlap
            key = ticks_to_seconds(best.highlight.key_tick - best.highlight.start_tick, best.effective_tickrate(project.tickrate) if project.recording_mode != "existing" else project.tickrate)
            # Medio segundo después de la última kill: ya se ve la baja (y el marcador con la cuenta final).
            at = min(total - 0.5, offset + max(0.0, key - best.trim_start) + 0.5)
            thumb = final.with_suffix(".jpg")
            try:
                self.ffmpeg.run(b.thumbnail_command(final, at, thumb, thumbnail_title(best.highlight), style.font_family))
            except FFmpegError as exc:
                log.warning("Miniatura no generada: %s", exc)
                thumb = None
        project.output_video = str(final)
        project.thumbnail = str(thumb) if thumb else ""
        report(1.0, "Exportación terminada")
        return ExportResult(video=final, thumbnail=thumb, duration=total, elapsed=time.time() - t0)

    @staticmethod
    def _snap_to_beats(desired: float, beats: list[float], elapsed: float) -> float:
        target = elapsed + desired
        nearest = min(beats, key=lambda x: abs(x - target))
        if abs(nearest - target) <= 0.6 and nearest - elapsed > 1.0:
            return nearest - elapsed
        return desired
