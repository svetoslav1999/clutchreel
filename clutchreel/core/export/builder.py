"""Generación de comandos FFmpeg (funciones puras, testeables sin ejecutar nada).

Pipeline de exportación:

1. ``clip_command``: cada clip se recorta y normaliza (resolución, fps, audio,
   cámara lenta, textos, zoom, recorte 9:16) a un intermedio MP4.
2. ``card_command``: intro/outro generados con ``drawtext``.
3. ``concat_command`` o ``xfade_command``: unión (con o sin transiciones).
4. ``music_mix_command``: mezcla música con ducking, fundidos y ``loudnorm``.
5. ``thumbnail_command``: fotograma del mejor momento con título.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from clutchreel.core.export.ffmpeg import escape_drawtext, escape_filter_path, font_file_for

PRESETS: dict[str, dict[str, object]] = {
    "youtube_1080p60": {"label": "YouTube 1080p60", "width": 1920, "height": 1080, "fps": 60, "aspect": "16:9"},
    "youtube_1440p60": {"label": "YouTube 1440p60", "width": 2560, "height": 1440, "fps": 60, "aspect": "16:9"},
    "youtube_4k60": {"label": "YouTube 4K60", "width": 3840, "height": 2160, "fps": 60, "aspect": "16:9"},
    "shorts_1080x1920": {"label": "Shorts / TikTok 1080×1920", "width": 1080, "height": 1920, "fps": 60, "aspect": "9:16"},
}

QUALITY_BITRATE: dict[str, dict[int, int]] = {
    # kbps por calidad y altura
    "alta": {1080: 16000, 1440: 28000, 2160: 50000, 1920: 16000},
    "media": {1080: 10000, 1440: 18000, 2160: 32000, 1920: 10000},
    "baja": {1080: 6000, 1440: 10000, 2160: 18000, 1920: 6000},
}


@dataclass
class EncodeSettings:
    width: int = 1920
    height: int = 1080
    fps: int = 60
    encoder: str = "libx264"
    bitrate_kbps: int = 16000
    aspect: str = "16:9"
    audio_bitrate: str = "192k"

    def video_args(self) -> list[str]:
        args = ["-c:v", self.encoder]
        if self.encoder.endswith("_nvenc"):
            args += ["-preset", "p5", "-rc", "vbr", "-cq", "19", "-b:v", f"{self.bitrate_kbps}k", "-maxrate", f"{int(self.bitrate_kbps * 1.5)}k", "-bufsize", f"{self.bitrate_kbps * 2}k"]
        elif self.encoder.endswith("_amf"):
            args += ["-quality", "quality", "-rc", "vbr_peak", "-b:v", f"{self.bitrate_kbps}k", "-maxrate", f"{int(self.bitrate_kbps * 1.5)}k"]
        elif self.encoder.endswith("_qsv"):
            args += ["-preset", "slower", "-b:v", f"{self.bitrate_kbps}k", "-maxrate", f"{int(self.bitrate_kbps * 1.5)}k"]
        elif self.encoder == "libx265":
            args += ["-preset", "medium", "-crf", "22", "-tag:v", "hvc1"]
        else:
            args += ["-preset", "medium", "-crf", "19", "-maxrate", f"{self.bitrate_kbps}k", "-bufsize", f"{self.bitrate_kbps * 2}k"]
        args += ["-pix_fmt", "yuv420p", "-r", str(self.fps), "-movflags", "+faststart"]
        return args

    def audio_args(self) -> list[str]:
        return ["-c:a", "aac", "-b:a", self.audio_bitrate, "-ar", "48000", "-ac", "2"]


@dataclass
class TextOverlay:
    text: str
    start: float = 0.0
    end: float = 0.0  # 0 = hasta el final
    position: str = "top"  # top | bottom | center
    size: int = 48
    color: str = "white"


@dataclass
class ClipRenderSpec:
    source: Path
    output: Path
    trim_start: float
    trim_end: float
    has_audio: bool = True
    game_volume: float = 1.0
    slow_motion_at: float | None = None  # segundos relativos al inicio recortado
    slow_motion_factor: float = 0.5
    slow_motion_seconds: float = 1.2
    zoom: float = 1.0
    overlays: list[TextOverlay] = field(default_factory=list)
    kill_times: list[float] = field(default_factory=list)  # relativas al clip, para el marcador
    kill_counter: bool = False
    fade_in: float = 0.0
    fade_out: float = 0.0
    font_family: str = "Segoe UI"
    crop_focus_x: float = 0.5  # 0..1 centro horizontal del recorte 9:16

    @property
    def duration(self) -> float:
        return max(0.1, self.trim_end - self.trim_start)

    def output_duration(self) -> float:
        """Duración tras aplicar cámara lenta."""
        if self.slow_motion_at is None:
            return self.duration
        seg = self._slow_segment()
        if not seg:
            return self.duration
        a, b = seg
        return self.duration + (b - a) * (1.0 / self.slow_motion_factor - 1.0)

    def _slow_segment(self) -> tuple[float, float] | None:
        if self.slow_motion_at is None or self.slow_motion_factor >= 1.0:
            return None
        half = self.slow_motion_seconds / 2.0
        a = max(0.0, self.slow_motion_at - half)
        b = min(self.duration, self.slow_motion_at + half)
        if b - a < 0.2:
            return None
        return (round(a, 3), round(b, 3))


def _drawtext(text: str, font: Path | None, size: int, color: str, x: str, y: str, enable: str | None = None, box: bool = True) -> str:
    parts = [f"text='{escape_drawtext(text)}'", f"fontsize={size}", f"fontcolor={color}", f"x={x}", f"y={y}"]
    if font:
        parts.append(f"fontfile='{escape_filter_path(font)}'")
    if box:
        parts += ["box=1", "boxcolor=black@0.45", "boxborderw=14"]
    parts += ["shadowcolor=black@0.6", "shadowx=2", "shadowy=2"]
    if enable:
        parts.append(f"enable='{enable}'")
    return "drawtext=" + ":".join(parts)


def _scale_chain(enc: EncodeSettings, zoom: float, crop_focus_x: float) -> list[str]:
    chain: list[str] = []
    if zoom > 1.01:
        chain.append(f"crop=iw/{zoom:.3f}:ih/{zoom:.3f}")
    if enc.aspect == "9:16":
        # Recorte vertical centrado en la acción (mira ≈ centro de la pantalla).
        fx = min(max(crop_focus_x, 0.0), 1.0)
        chain.append(f"crop='min(iw,ih*9/16)':ih:'(iw-ow)*{fx:.3f}':0")
    chain.append(f"scale={enc.width}:{enc.height}:force_original_aspect_ratio=decrease:flags=lanczos")
    chain.append(f"pad={enc.width}:{enc.height}:(ow-iw)/2:(oh-ih)/2:color=black")
    chain.append("setsar=1")
    chain.append(f"fps={enc.fps}")
    chain.append("format=yuv420p")
    return chain


def clip_command(spec: ClipRenderSpec, enc: EncodeSettings) -> list[str]:
    """Argumentos FFmpeg (sin el ejecutable ni ``-y``) para renderizar un clip."""
    font = font_file_for(spec.font_family)
    args: list[str] = ["-ss", f"{spec.trim_start:.3f}", "-t", f"{spec.duration:.3f}", "-i", str(spec.source)]
    if not spec.has_audio:
        args += ["-f", "lavfi", "-t", f"{spec.duration:.3f}", "-i", "anullsrc=channel_layout=stereo:sample_rate=48000"]
    vf = _scale_chain(enc, spec.zoom, spec.crop_focus_x)
    filters: list[str] = []
    video_in = "[0:v]"
    audio_in = "[0:a]" if spec.has_audio else "[1:a]"

    seg = spec._slow_segment()
    if seg:
        a, b = seg
        f = spec.slow_motion_factor
        filters.append(f"{video_in}split=3[v0][v1][v2]")
        filters.append(f"[v0]trim=0:{a},setpts=PTS-STARTPTS[va]")
        filters.append(f"[v1]trim={a}:{b},setpts=(PTS-STARTPTS)/{f}[vb]")
        filters.append(f"[v2]trim=start={b},setpts=PTS-STARTPTS[vc]")
        filters.append("[va][vb][vc]concat=n=3:v=1:a=0[vcat]")
        filters.append(f"{audio_in}asplit=3[a0][a1][a2]")
        filters.append(f"[a0]atrim=0:{a},asetpts=PTS-STARTPTS[aa]")
        filters.append(f"[a1]atrim={a}:{b},asetpts=PTS-STARTPTS,atempo={max(0.5, f)}[ab]")
        filters.append(f"[a2]atrim=start={b},asetpts=PTS-STARTPTS[ac]")
        filters.append("[aa][ab][ac]concat=n=3:v=0:a=1[acat]")
        video_in = "[vcat]"
        audio_in = "[acat]"

    out_dur = spec.output_duration()
    overlays: list[str] = []
    for ov in spec.overlays:
        y = {"top": "60", "bottom": "h-th-80", "center": "(h-th)/2"}.get(ov.position, "60")
        enable = None
        if ov.start > 0 or ov.end > 0:
            end = ov.end if ov.end > 0 else out_dur + 1
            enable = f"between(t,{ov.start:.2f},{end:.2f})"
        overlays.append(_drawtext(ov.text, font, ov.size, ov.color, "(w-tw)/2", y, enable))
    if spec.kill_counter and spec.kill_times:
        times = sorted(t for t in spec.kill_times if 0 <= t <= out_dur + 0.5)
        for idx, t in enumerate(times):
            nxt = times[idx + 1] if idx + 1 < len(times) else out_dur + 1
            label = f"KILLS  {idx + 1}"
            overlays.append(_drawtext(label, font, 40, "white", "w-tw-40", "40", f"between(t,{t:.2f},{nxt:.2f})"))
    fades: list[str] = []
    if spec.fade_in > 0:
        fades.append(f"fade=t=in:st=0:d={spec.fade_in:.2f}")
    if spec.fade_out > 0:
        fades.append(f"fade=t=out:st={max(0.0, out_dur - spec.fade_out):.2f}:d={spec.fade_out:.2f}")
    vchain = ",".join(vf + overlays + fades)
    filters.append(f"{video_in}{vchain}[vout]")
    achain = [f"volume={spec.game_volume:.2f}", "aresample=48000", "aformat=channel_layouts=stereo"]
    if spec.fade_in > 0:
        achain.append(f"afade=t=in:st=0:d={spec.fade_in:.2f}")
    if spec.fade_out > 0:
        achain.append(f"afade=t=out:st={max(0.0, out_dur - spec.fade_out):.2f}:d={spec.fade_out:.2f}")
    filters.append(f"{audio_in}{','.join(achain)}[aout]")
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]
    args += enc.video_args() + enc.audio_args()
    args += ["-t", f"{out_dur + 0.05:.3f}", str(spec.output)]
    return args


def card_command(
    output: Path,
    enc: EncodeSettings,
    title: str,
    subtitle: str = "",
    duration: float = 3.0,
    font_family: str = "Segoe UI",
    background: str = "#101418",
    logo: Path | None = None,
) -> list[str]:
    """Tarjeta de intro/outro: fondo liso, título, subtítulo y logo opcional con fundidos."""
    font = font_file_for(font_family)
    args: list[str] = [
        "-f",
        "lavfi",
        "-i",
        f"color=c={background}:s={enc.width}x{enc.height}:r={enc.fps}:d={duration:.2f}",
        "-f",
        "lavfi",
        "-t",
        f"{duration:.2f}",
        "-i",
        "anullsrc=channel_layout=stereo:sample_rate=48000",
    ]
    title_size = int(enc.height * 0.085)
    sub_size = int(enc.height * 0.04)
    chain: list[str] = []
    if logo and logo.exists():
        args += ["-i", str(logo)]
    chain.append(_drawtext(title, font, title_size, "white", "(w-tw)/2", "(h-th)/2-40" if subtitle else "(h-th)/2", box=False))
    if subtitle:
        chain.append(_drawtext(subtitle, font, sub_size, "#9fb3c8", "(w-tw)/2", "(h+th)/2+30", box=False))
    chain.append(f"fade=t=in:st=0:d=0.5,fade=t=out:st={max(0.0, duration - 0.6):.2f}:d=0.6,format=yuv420p")
    filters = [f"[0:v]{','.join(chain)}[vt]"]
    if logo and logo.exists():
        logo_h = int(enc.height * 0.12)
        filters.append(f"[2:v]scale=-1:{logo_h}[lg]")
        filters.append("[vt][lg]overlay=W-w-40:H-h-40[vout]")
    else:
        filters[-1] = filters[-1].replace("[vt]", "[vout]")
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "1:a"]
    args += enc.video_args() + enc.audio_args() + ["-t", f"{duration:.2f}", str(output)]
    return args


def write_concat_list(paths: list[Path], list_file: Path) -> None:
    lines = []
    for p in paths:
        text = str(p).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{text}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


def concat_command(list_file: Path, output: Path) -> list[str]:
    """Unión sin recodificar (todos los intermedios comparten formato)."""
    return ["-f", "concat", "-safe", "0", "-i", str(list_file), "-c", "copy", "-movflags", "+faststart", str(output)]


def xfade_command(inputs: list[Path], durations: list[float], output: Path, enc: EncodeSettings, transition: str = "fade", t_dur: float = 0.4) -> list[str]:
    """Unión con transiciones ``xfade``/``acrossfade`` (recodifica)."""
    if len(inputs) != len(durations) or not inputs:
        raise ValueError("inputs y durations deben tener la misma longitud (>0)")
    args: list[str] = []
    for p in inputs:
        args += ["-i", str(p)]
    if len(inputs) == 1:
        return [*args, "-c", "copy", str(output)]
    filters: list[str] = []
    t_dur = max(0.1, min(t_dur, min(durations) / 2 - 0.05))
    prev_v, prev_a = "[0:v]", "[0:a]"
    offset = 0.0
    for i in range(1, len(inputs)):
        offset += durations[i - 1] - t_dur
        vout = f"[v{i}]" if i < len(inputs) - 1 else "[vout]"
        aout = f"[a{i}]" if i < len(inputs) - 1 else "[aout]"
        filters.append(f"{prev_v}[{i}:v]xfade=transition={transition}:duration={t_dur:.2f}:offset={offset:.3f}{vout}")
        filters.append(f"{prev_a}[{i}:a]acrossfade=d={t_dur:.2f}:c1=tri:c2=tri{aout}")
        prev_v, prev_a = vout, aout
    args += ["-filter_complex", ";".join(filters), "-map", "[vout]", "-map", "[aout]"]
    args += enc.video_args() + enc.audio_args() + [str(output)]
    return args


def music_mix_command(
    video: Path,
    music: Path | None,
    output: Path,
    total_duration: float,
    music_volume: float = 0.35,
    ducking: bool = True,
    fade: float = 1.5,
    loudnorm: bool = True,
    game_volume: float = 1.0,
) -> list[str]:
    """Mezcla música (en bucle) con el audio del juego, ducking, fundidos y loudnorm."""
    args: list[str] = ["-i", str(video)]
    filters: list[str] = []
    if music and music.exists():
        args += ["-stream_loop", "-1", "-i", str(music)]
        mchain = [f"volume={music_volume:.2f}", "aresample=48000", "aformat=channel_layouts=stereo"]
        if fade > 0:
            mchain.append(f"afade=t=in:st=0:d={fade:.2f}")
            mchain.append(f"afade=t=out:st={max(0.0, total_duration - fade):.2f}:d={fade:.2f}")
        filters.append(f"[1:a]atrim=0:{total_duration:.3f},asetpts=PTS-STARTPTS,{','.join(mchain)}[m]")
        filters.append(f"[0:a]volume={game_volume:.2f},aformat=channel_layouts=stereo,asplit=2[g1][g2]")
        if ducking:
            filters.append("[m][g2]sidechaincompress=threshold=0.03:ratio=5:attack=40:release=700:makeup=1[md]")
            filters.append("[g1][md]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        else:
            filters.append("[g2]anullsink")
            filters.append("[g1][m]amix=inputs=2:duration=first:dropout_transition=2:normalize=0[mix]")
        last = "[mix]"
    else:
        filters.append(f"[0:a]volume={game_volume:.2f},aformat=channel_layouts=stereo[mix]")
        last = "[mix]"
    if loudnorm:
        filters.append(f"{last}loudnorm=I=-14:TP=-1.5:LRA=11[aout]")
    else:
        filters.append(f"{last}anull[aout]")
    args += ["-filter_complex", ";".join(filters), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-shortest", "-movflags", "+faststart", str(output)]
    return args


def thumbnail_command(video: Path, at_seconds: float, output: Path, title: str = "", font_family: str = "Segoe UI", width: int = 1280, height: int = 720) -> list[str]:
    font = font_file_for(font_family)
    chain = [f"scale={width}:{height}:force_original_aspect_ratio=increase", f"crop={width}:{height}", "eq=contrast=1.1:saturation=1.25"]
    if title:
        chain.append(_drawtext(title.upper(), font, int(height * 0.12), "yellow", "(w-tw)/2", "h-th-60"))
    return ["-ss", f"{max(0.0, at_seconds):.3f}", "-i", str(video), "-frames:v", "1", "-vf", ",".join(chain), "-q:v", "2", str(output)]


def bitrate_for(quality: str, height: int, override: int = 0) -> int:
    if override > 0:
        return override
    table = QUALITY_BITRATE.get(quality, QUALITY_BITRATE["alta"])
    return table.get(height, table[1080])


def encode_settings_for(preset: str, encoder: str, quality: str, bitrate_override: int = 0) -> EncodeSettings:
    p = PRESETS.get(preset, PRESETS["youtube_1080p60"])
    width = int(p["width"])  # type: ignore[call-overload]
    height = int(p["height"])  # type: ignore[call-overload]
    return EncodeSettings(
        width=width,
        height=height,
        fps=int(p["fps"]),  # type: ignore[call-overload]
        encoder=encoder,
        bitrate_kbps=bitrate_for(quality, height, bitrate_override),
        aspect=str(p["aspect"]),
    )
