from __future__ import annotations

from pathlib import Path

from clutchreel.core.export import builder as b
from clutchreel.core.export.ffmpeg import escape_drawtext, escape_filter_path


def enc() -> b.EncodeSettings:
    return b.EncodeSettings(width=1920, height=1080, fps=60, encoder="libx264", bitrate_kbps=8000)


def test_clip_command_basic(tmp_path: Path) -> None:
    spec = b.ClipRenderSpec(source=tmp_path / "in.mkv", output=tmp_path / "out.mp4", trim_start=10.0, trim_end=18.5)
    args = b.clip_command(spec, enc())
    assert args[:4] == ["-ss", "10.000", "-t", "8.500"]
    fc = args[args.index("-filter_complex") + 1]
    assert "scale=1920:1080" in fc and "fps=60" in fc
    assert "-c:v" in args and args[args.index("-c:v") + 1] == "libx264"
    assert args[-1].endswith("out.mp4")


def test_clip_command_slow_motion_extends_duration(tmp_path: Path) -> None:
    spec = b.ClipRenderSpec(source=tmp_path / "in.mkv", output=tmp_path / "o.mp4", trim_start=0.0, trim_end=10.0, slow_motion_at=5.0, slow_motion_factor=0.5, slow_motion_seconds=2.0)
    assert spec.output_duration() == 12.0
    fc = b.clip_command(spec, enc())[b.clip_command(spec, enc()).index("-filter_complex") + 1]
    assert "setpts=(PTS-STARTPTS)/0.5" in fc and "atempo=0.5" in fc and "concat=n=3" in fc


def test_clip_command_no_audio_adds_silence(tmp_path: Path) -> None:
    spec = b.ClipRenderSpec(source=tmp_path / "in.mkv", output=tmp_path / "o.mp4", trim_start=0.0, trim_end=4.0, has_audio=False)
    args = b.clip_command(spec, enc())
    assert "anullsrc=channel_layout=stereo:sample_rate=48000" in args


def test_vertical_crop(tmp_path: Path) -> None:
    e = b.encode_settings_for("shorts_1080x1920", "libx264", "media")
    assert (e.width, e.height, e.aspect) == (1080, 1920, "9:16")
    spec = b.ClipRenderSpec(source=tmp_path / "in.mkv", output=tmp_path / "o.mp4", trim_start=0.0, trim_end=4.0)
    fc = b.clip_command(spec, e)[b.clip_command(spec, e).index("-filter_complex") + 1]
    assert "crop='min(iw,ih*9/16)':ih" in fc


def test_overlays_and_counter(tmp_path: Path) -> None:
    spec = b.ClipRenderSpec(source=tmp_path / "in.mkv", output=tmp_path / "o.mp4", trim_start=0.0, trim_end=6.0, overlays=[b.TextOverlay("ACE: ronda 5, 100%", 0, 3)], kill_times=[1.0, 2.0], kill_counter=True)
    fc = b.clip_command(spec, enc())[b.clip_command(spec, enc()).index("-filter_complex") + 1]
    assert fc.count("drawtext=") == 3
    assert "ACE\\: ronda 5\\, 100\\%" in fc
    assert "between(t,1.00,2.00)" in fc


def test_escape_helpers() -> None:
    assert escape_drawtext("a:b'c%d") == "a\\:b\\'c\\%d"
    assert escape_filter_path(Path("C:/Windows/Fonts/x.ttf")) == "C\\:/Windows/Fonts/x.ttf"


def test_xfade_offsets(tmp_path: Path) -> None:
    args = b.xfade_command([tmp_path / "a.mp4", tmp_path / "b.mp4", tmp_path / "c.mp4"], [5.0, 4.0, 3.0], tmp_path / "o.mp4", enc(), "fade", 0.5)
    fc = args[args.index("-filter_complex") + 1]
    assert "offset=4.500" in fc and "offset=8.000" in fc
    assert fc.count("acrossfade") == 2


def test_concat_list_quotes(tmp_path: Path) -> None:
    lst = tmp_path / "l.txt"
    b.write_concat_list([Path("C:/Vídeos/clip 1.mp4"), Path("C:/x/it's.mp4")], lst)
    text = lst.read_text(encoding="utf-8")
    assert "file 'C:/Vídeos/clip 1.mp4'" in text
    assert "file 'C:/x/it'\\''s.mp4'" in text


def test_music_mix_with_and_without_music(tmp_path: Path) -> None:
    with_music = b.music_mix_command(tmp_path / "v.mp4", tmp_path / "m.mp3", tmp_path / "o.mp4", 30.0)
    assert "-stream_loop" not in with_music  # la pista no existe → sin música
    (tmp_path / "m.mp3").write_bytes(b"x")
    with_music = b.music_mix_command(tmp_path / "v.mp4", tmp_path / "m.mp3", tmp_path / "o.mp4", 30.0, ducking=True)
    fc = with_music[with_music.index("-filter_complex") + 1]
    assert "sidechaincompress" in fc and "loudnorm" in fc and "afade=t=out:st=28.50" in fc
    no_duck = b.music_mix_command(tmp_path / "v.mp4", tmp_path / "m.mp3", tmp_path / "o.mp4", 30.0, ducking=False, loudnorm=False)
    fc2 = no_duck[no_duck.index("-filter_complex") + 1]
    assert "sidechaincompress" not in fc2 and "loudnorm" not in fc2


def test_bitrate_table() -> None:
    assert b.bitrate_for("alta", 1080) == 16000
    assert b.bitrate_for("baja", 2160) == 18000
    assert b.bitrate_for("alta", 1080, override=5000) == 5000
    assert b.encode_settings_for("inexistente", "libx264", "alta").height == 1080


def test_encoder_args() -> None:
    e = b.EncodeSettings(encoder="h264_nvenc", bitrate_kbps=10000)
    args = e.video_args()
    assert "-rc" in args and "-cq" in args and "-b:v" in args
    e2 = b.EncodeSettings(encoder="libx265")
    assert "-tag:v" in e2.video_args()


def test_thumbnail_title_is_only_the_main_play() -> None:
    from clutchreel.core.demo.models import Highlight
    from clutchreel.core.export.exporter import thumbnail_title

    merged = Highlight("ace", 6, 0, 100, 1.0, "x", merged_kinds=["ace", "entry", "smoke", "noscope"])
    assert thumbnail_title(merged) == "ACE"  # «ACE + PRIMERA BAJA + A TRAVÉS DE HUMO + NO-SCOPE» no cabe en 1280 px
    assert thumbnail_title(Highlight("clutch", 2, 0, 100, 1.0, "x")) == "Clutch"


def test_vertical_texts_fit_and_counter_goes_below_title(tmp_path: Path) -> None:
    """En 9:16 (1080 px de ancho) el título largo se salía y el marcador de kills se montaba encima."""
    import re

    from clutchreel.core.export.builder import ClipRenderSpec, TextOverlay, clip_command, encode_settings_for

    enc = encode_settings_for("shorts_1080x1920", "libx264", "alta")
    title = "ACE + Primera baja + A través de humo + No-scope · Ronda 6"
    spec = ClipRenderSpec(tmp_path / "a.mkv", tmp_path / "o.mp4", 0.0, 10.0, overlays=[TextOverlay(title, 0.3, 3.5, "top", 44)], kill_times=[1.0], kill_counter=True)
    fc = clip_command(spec, enc)[clip_command(spec, enc).index("-filter_complex") + 1]
    sizes = [int(s) for s in re.findall(r"fontsize=(\d+)", fc)]
    title_size, counter_size = sizes[0], sizes[1]
    assert title_size * 0.56 * len(title) <= 1080 * 0.9 + 1
    counter_y = int(re.search(r"KILLS  1':fontsize=\d+:fontcolor=white:x=w-tw-40:y=(\d+)", fc).group(1))  # type: ignore[union-attr]
    assert counter_y >= 60 + title_size  # debajo del título
    # En 16:9 el título cabe tal cual y el marcador sigue arriba a la derecha.
    enc169 = encode_settings_for("youtube_1080p60", "libx264", "alta")
    fc169 = clip_command(spec, enc169)[clip_command(spec, enc169).index("-filter_complex") + 1]
    assert "fontsize=44" in fc169 and "x=w-tw-40:y=40:" in fc169
    assert counter_size == 40


def test_card_title_fits_vertical_and_drops_missing_glyphs(tmp_path: Path) -> None:
    import re

    from clutchreel.core.export.builder import card_command, encode_settings_for
    from clutchreel.core.export.ffmpeg import font_file_for

    enc = encode_settings_for("shorts_1080x1920", "libx264", "alta")
    args = card_command(tmp_path / "i.mp4", enc, "♛JUGADOR CON NOMBRE LARGO♛ · Mirage", "Highlights Premier · CT 13 – 10 T")
    fc = args[args.index("-filter_complex") + 1]
    size = int(re.findall(r"fontsize=(\d+)", fc)[0])
    assert size * 0.56 * len("JUGADOR CON NOMBRE LARGO · Mirage") <= 1080 * 0.9 + 1
    if font_file_for("Segoe UI") is not None:  # Segoe UI no tiene «♛»: saldría un cuadro vacío
        assert "♛" not in fc and "JUGADOR CON NOMBRE LARGO" in fc


def test_font_codepoints_reads_real_font() -> None:
    from clutchreel.core.export.ffmpeg import font_codepoints, font_file_for, text_for_font

    font = font_file_for("Segoe UI")
    if font is None:
        return
    cps = font_codepoints(str(font))
    assert cps is not None and ord("ñ") in cps and ord("A") in cps
    assert text_for_font("♛Niño ñandú♛", font) == "Niño ñandú"
    assert text_for_font("sin fuente", None) == "sin fuente"
