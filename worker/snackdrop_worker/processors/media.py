"""Operaciones de video y audio (ffmpeg) y transcripción (Whisper)."""

from __future__ import annotations

import re
import shutil
import subprocess
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from .common import Cancelled, Context, Output, ProcessingError, choice, clamp_float, clamp_int, ffmpeg_path, fmt_size, models_dir, ratio, run, unique
from .registry import register

HW_TEST_TIMEOUT = 20


def ffmpeg_available() -> bool:
    return ffmpeg_path() is not None


@dataclass
class Probe:
    duration: float
    video: str | None
    audio: str | None
    width: int
    height: int


def probe(src: Path, name: str) -> Probe:
    ff = ffmpeg_path()
    if not ff:
        raise ProcessingError("Este nodo no tiene ffmpeg")
    proc = subprocess.run([ff, "-hide_banner", "-nostdin", "-i", str(src)], capture_output=True, text=True,
                          errors="replace", timeout=120, check=False)
    info = proc.stderr
    if "Invalid data found" in info or "Stream #" not in info:
        raise ProcessingError(f"{name}: no es un archivo de audio o video válido")
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    duration = int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0
    vm = re.search(r"Stream #\S+.*?: Video: (\w+)(?!.*attached pic).*?(\d{2,5})x(\d{2,5})", info)
    am = re.search(r"Stream #\S+.*?: Audio: (\w+)", info)
    return Probe(
        duration=duration,
        video=vm.group(1) if vm else None,
        audio=am.group(1) if am else None,
        width=int(vm.group(2)) if vm else 0,
        height=int(vm.group(3)) if vm else 0,
    )


def ffmpeg(args: list[str], ctx: Context, duration: float, timeout: float = 6 * 3600) -> None:
    ff = ffmpeg_path()
    if not ff:
        raise ProcessingError("Este nodo no tiene ffmpeg")

    def on_line(line: str) -> None:
        if duration > 0 and line.startswith(("out_time_us=", "out_time_ms=")):
            try:
                ctx.progress(int(line.split("=", 1)[1]) / 1_000_000 / duration)
            except ValueError:
                pass

    run([ff, "-hide_banner", "-nostdin", "-y", "-loglevel", "error", "-progress", "pipe:1", "-nostats", *args],
        ctx, timeout=timeout, on_stdout=on_line)


@lru_cache
def _encoders() -> str:
    ff = ffmpeg_path()
    if not ff:
        return ""
    try:
        return subprocess.run([ff, "-hide_banner", "-encoders"], capture_output=True, text=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


def has_encoder(name: str) -> bool:
    return re.search(rf"\s{re.escape(name)}\s", _encoders()) is not None


@lru_cache
def hw_encoder_works(name: str) -> bool:
    """Que ffmpeg liste el codificador no significa que haya GPU: se prueba con un cuadro."""
    ff = ffmpeg_path()
    if not ff or not has_encoder(name):
        return False
    try:
        proc = subprocess.run(
            [ff, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "color=black:s=256x256:d=0.1",
             "-frames:v", "1", "-c:v", name, "-f", "null", "-"],
            capture_output=True, timeout=HW_TEST_TIMEOUT, check=False,
        )
        return proc.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def hw_encoders() -> list[str]:
    return [e for e in ("h264_nvenc", "hevc_nvenc", "h264_videotoolbox", "hevc_videotoolbox") if hw_encoder_works(e)]


def _video_encoder(codec: str, crf: int, preset: str, hardware: bool) -> tuple[list[str], str]:
    hevc = codec == "h265"
    if hardware:
        nv = "hevc_nvenc" if hevc else "h264_nvenc"
        if hw_encoder_works(nv):
            return ["-c:v", nv, "-preset", "p5", "-rc", "vbr", "-cq", str(crf), "-b:v", "0"] + (["-tag:v", "hvc1"] if hevc else []), "NVENC (GPU Nvidia)"
        vt = "hevc_videotoolbox" if hevc else "h264_videotoolbox"
        if hw_encoder_works(vt):
            q = max(30, min(90, int(100 - (crf - 18) * 3.5)))
            return ["-c:v", vt, "-q:v", str(q)] + (["-tag:v", "hvc1"] if hevc else []), "VideoToolbox (GPU Apple)"
    if hevc and has_encoder("libx265"):
        return ["-c:v", "libx265", "-crf", str(crf), "-preset", preset, "-tag:v", "hvc1", "-x265-params", "log-level=error"], "x265 (CPU)"
    return ["-c:v", "libx264", "-crf", str(crf), "-preset", preset], "x264 (CPU)"


VIDEO_PRESETS = ("ultrafast", "veryfast", "fast", "medium", "slow", "veryslow")


def _scale_filter(p: Probe, max_height: int | None) -> list[str]:
    if max_height and p.height > max_height:
        return ["-vf", f"scale=-2:{max_height}:flags=lanczos"]
    return []


def _require_video(p: Probe, name: str) -> None:
    if not p.video:
        raise ProcessingError(f"{name}: no contiene video")


@register("video.compress", available=ffmpeg_available)
def video_compress(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    _require_video(p, name)
    codec = choice(params.get("codec"), ("h264", "h265"), "h264")
    crf = clamp_int(params.get("crf"), 16, 40, 26)
    preset = choice(params.get("preset"), VIDEO_PRESETS, "medium")
    max_height = clamp_int(params.get("max_height"), 144, 4320, None)
    audio_kbps = clamp_int(params.get("audio_bitrate"), 32, 512, 128)
    hardware = params.get("hardware", "auto") != "off"
    enc, engine = _video_encoder(codec, crf, preset, hardware)
    out = unique(out_dir, Path(name).stem, ".mp4")
    args = ["-i", str(src), "-map", "0:v:0", "-map", "0:a?", *_scale_filter(p, max_height), *enc, "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", f"{audio_kbps}k", "-movflags", "+faststart", str(out)]
    ctx.log(f"Codificando {name} con {engine}, CRF {crf}…")
    try:
        ffmpeg(args, ctx, p.duration)
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    before, after = src.stat().st_size, out.stat().st_size
    if params.get("never_larger", True) is not False and after >= before:
        out.unlink()
        out = unique(out_dir, Path(name).stem, Path(name).suffix.lower() or ".mp4")
        shutil.copyfile(src, out)
        return out, f"{name}: ya estaba bien comprimido ({fmt_size(before)}), se conserva el original"
    return out, f"{name} → {out.name} ({fmt_size(before)} → {fmt_size(after)}{ratio(before, after)}, {engine})"


REMUX_OK = {
    ".mp4": ({"h264", "hevc", "av1", "mpeg4"}, {"aac", "mp3", "ac3", "eac3", "alac", None}),
    ".mov": ({"h264", "hevc", "prores", "mpeg4"}, {"aac", "mp3", "alac", "pcm_s16le", None}),
    ".webm": ({"vp8", "vp9", "av1"}, {"opus", "vorbis", None}),
}


@register("video.convert", available=ffmpeg_available)
def video_convert(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    _require_video(p, name)
    container = choice(params.get("container"), ("mp4", "mkv", "webm", "mov"), "mp4")
    mode = choice(params.get("mode"), ("auto", "reencode"), "auto")
    ext = f".{container}"
    out = unique(out_dir, Path(name).stem, ext)
    remux_ok = ext == ".mkv" or (p.video in REMUX_OK[ext][0] and p.audio in REMUX_OK[ext][1])
    if mode == "auto" and remux_ok:
        maps = ["-map", "0"] if ext == ".mkv" else ["-map", "0:v:0", "-map", "0:a?"]
        extra = ["-movflags", "+faststart"] if ext in (".mp4", ".mov") else []
        try:
            ffmpeg(["-i", str(src), *maps, "-c", "copy", *extra, str(out)], ctx, p.duration)
            return out, f"{name} → {out.name} (sin recodificar, {fmt_size(out.stat().st_size)})"
        except ProcessingError:
            out.unlink(missing_ok=True)
            ctx.log(f"{name}: no se pudo copiar sin recodificar; se recodifica")
    if ext == ".webm":
        enc = ["-c:v", "libvpx-vp9", "-crf", "32", "-b:v", "0", "-row-mt", "1", "-deadline", "good", "-cpu-used", "4",
               "-c:a", "libopus", "-b:a", "128k"]
        engine = "VP9/Opus"
    else:
        venc, engine = _video_encoder("h264", 22, "medium", params.get("hardware", "auto") != "off")
        enc = [*venc, "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "160k"]
        if ext in (".mp4", ".mov"):
            enc += ["-movflags", "+faststart"]
    try:
        ffmpeg(["-i", str(src), "-map", "0:v:0", "-map", "0:a?", *enc, str(out)], ctx, p.duration)
    except BaseException:
        out.unlink(missing_ok=True)
        raise
    return out, f"{name} → {out.name} (recodificado {engine}, {fmt_size(out.stat().st_size)})"


@register("video.resize", available=ffmpeg_available)
def video_resize(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    _require_video(p, name)
    height = choice(clamp_int(params.get("height"), 144, 4320, 1080), (2160, 1440, 1080, 720, 480, 360), 1080)
    crf = clamp_int(params.get("crf"), 16, 40, 23)
    ext = Path(name).suffix.lower() if Path(name).suffix.lower() in (".mp4", ".mov", ".mkv") else ".mp4"
    if p.height <= height:
        out = unique(out_dir, Path(name).stem, Path(name).suffix.lower() or ".mp4")
        shutil.copyfile(src, out)
        return out, f"{name}: ya mide {p.height}p o menos, se conserva el original"
    venc, engine = _video_encoder("h264", crf, "medium", params.get("hardware", "auto") != "off")
    out = unique(out_dir, f"{Path(name).stem}_{height}p", ext)
    base = ["-i", str(src), "-map", "0:v:0", "-map", "0:a?", "-vf", f"scale=-2:{height}:flags=lanczos", *venc, "-pix_fmt", "yuv420p"]
    tail = (["-movflags", "+faststart"] if ext != ".mkv" else []) + [str(out)]
    try:
        ffmpeg([*base, "-c:a", "copy", *tail], ctx, p.duration)
    except ProcessingError:
        out.unlink(missing_ok=True)
        ffmpeg([*base, "-c:a", "aac", "-b:a", "160k", *tail], ctx, p.duration)
    return out, f"{name} → {out.name} ({p.width}x{p.height} → {height}p, {engine}, {fmt_size(out.stat().st_size)})"


AUDIO_FORMATS = {
    "mp3": (".mp3", ["-c:a", "libmp3lame"], True),
    "aac": (".m4a", ["-c:a", "aac"], True),
    "opus": (".opus", ["-c:a", "libopus"], True),
    "ogg": (".ogg", ["-c:a", "libvorbis"], True),
    "flac": (".flac", ["-c:a", "flac"], False),
    "wav": (".wav", ["-c:a", "pcm_s16le"], False),
}
EXT_AUDIO_FORMAT = {".mp3": "mp3", ".m4a": "aac", ".aac": "aac", ".opus": "opus", ".ogg": "ogg", ".flac": "flac", ".wav": "wav"}


def _audio_args(fmt: str, kbps: int, mono: bool = False, rate: str | None = None) -> tuple[str, list[str]]:
    ext, codec, lossy = AUDIO_FORMATS[fmt]
    args = [*codec]
    if lossy:
        args += ["-b:a", f"{kbps}k"]
    if mono:
        args += ["-ac", "1"]
    if rate and rate != "keep":
        args += ["-ar", rate]
    return ext, args


@register("video.extract_audio", available=ffmpeg_available)
def extract_audio(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    if not p.audio:
        raise ProcessingError(f"{name}: no tiene pista de audio")
    fmt = choice(params.get("format"), tuple(AUDIO_FORMATS), "mp3")
    ext, args = _audio_args(fmt, clamp_int(params.get("bitrate"), 32, 512, 192))
    out = unique(out_dir, Path(name).stem, ext)
    ffmpeg(["-i", str(src), "-vn", "-map", "0:a:0", *args, str(out)], ctx, p.duration)
    return out, f"{name} → {out.name} ({fmt_size(out.stat().st_size)})"


@register("audio.convert", available=ffmpeg_available)
def audio_convert(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    if not p.audio:
        raise ProcessingError(f"{name}: no tiene audio")
    fmt = choice(params.get("format"), tuple(AUDIO_FORMATS), "mp3")
    rate = choice(params.get("sample_rate"), ("keep", "44100", "48000", "22050", "16000"), "keep")
    ext, args = _audio_args(fmt, clamp_int(params.get("bitrate"), 32, 512, 192), bool(params.get("mono")), rate)
    out = unique(out_dir, Path(name).stem, ext)
    ffmpeg(["-i", str(src), "-vn", "-map", "0:a:0", *args, str(out)], ctx, p.duration)
    before, after = src.stat().st_size, out.stat().st_size
    return out, f"{name} → {out.name} ({fmt_size(before)} → {fmt_size(after)})"


@register("audio.normalize", available=ffmpeg_available)
def audio_normalize(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    if not p.audio:
        raise ProcessingError(f"{name}: no tiene audio")
    target = clamp_int(params.get("target_lufs"), -30, -9, -16)
    fmt = EXT_AUDIO_FORMAT.get(Path(name).suffix.lower(), "mp3")
    ext, args = _audio_args(fmt, clamp_int(params.get("bitrate"), 32, 512, 192))
    out = unique(out_dir, Path(name).stem, ext)
    ffmpeg(["-i", str(src), "-vn", "-map", "0:a:0", "-af", f"loudnorm=I={target}:TP=-1.5:LRA=11", *args, str(out)], ctx, p.duration)
    return out, f"{name} → {out.name} (volumen normalizado a {target} LUFS)"


@register("video.gif", available=ffmpeg_available)
def video_gif(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> Output:
    p = probe(src, name)
    _require_video(p, name)
    start = clamp_float(params.get("start"), 0, max(0.0, p.duration - 0.1) if p.duration else 1e9, 0)
    duration = clamp_float(params.get("duration"), 0.5, 60, 5)
    fps = clamp_int(params.get("fps"), 5, 30, 12)
    width = clamp_int(params.get("width"), 120, 1280, 480)
    fmt = choice(params.get("format"), ("gif", "webp"), "gif")
    out = unique(out_dir, Path(name).stem, f".{fmt}")
    base = ["-ss", f"{start:.2f}", "-t", f"{duration:.2f}", "-i", str(src), "-an"]
    if fmt == "gif":
        vf = f"fps={fps},scale={width}:-1:flags=lanczos,split[a][b];[a]palettegen=stats_mode=diff[p];[b][p]paletteuse=dither=bayer:bayer_scale=5"
        args = [*base, "-vf", vf, "-loop", "0", str(out)]
    else:
        args = [*base, "-vf", f"fps={fps},scale={width}:-1:flags=lanczos", "-c:v", "libwebp", "-q:v", "70", "-loop", "0", str(out)]
    ffmpeg(args, ctx, duration)
    return out, f"{name} → {out.name} ({duration:.1f} s desde {start:.1f} s, {width}px, {fps} fps, {fmt_size(out.stat().st_size)})"


@register("video.thumbnails", available=ffmpeg_available)
def thumbnails(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> list[Output]:
    p = probe(src, name)
    _require_video(p, name)
    if p.duration <= 0:
        raise ProcessingError(f"{name}: no se pudo leer la duración")
    mode = choice(params.get("mode"), ("frames", "sheet"), "sheet")
    width = clamp_int(params.get("width"), 120, 1920, 320 if mode == "sheet" else 1280)
    fmt = choice(params.get("format"), ("jpg", "png", "webp"), "jpg")
    stem = Path(name).stem
    if mode == "sheet":
        cols = clamp_int(params.get("columns"), 2, 10, 4)
        rows = clamp_int(params.get("rows"), 2, 10, 4)
        n = cols * rows
        out = unique(out_dir, f"{stem}_miniaturas", f".{fmt}")
        vf = f"fps={n}/{p.duration:.3f},scale={width}:-2,tile={cols}x{rows}:padding=4:margin=4"
        ffmpeg(["-i", str(src), "-an", "-vf", vf, "-frames:v", "1", "-update", "1", str(out)], ctx, p.duration)
        return [(out, f"{name} → {out.name} (hoja de {cols}x{rows})")]
    count = clamp_int(params.get("count"), 1, 50, 6)
    outputs: list[Output] = []
    for i in range(count):
        ctx.check()
        t = p.duration * (i + 0.5) / count
        out = unique(out_dir, f"{stem}_{i + 1:02d}", f".{fmt}")
        ffmpeg(["-ss", f"{t:.2f}", "-i", str(src), "-an", "-frames:v", "1", "-vf", f"scale={width}:-2", "-update", "1", str(out)], ctx, 0)
        outputs.append((out, f"{name} @ {t:.1f}s → {out.name}"))
        ctx.progress((i + 1) / count)
    return outputs


# --- Transcripción -------------------------------------------------------------------


def whisper_available() -> bool:
    try:
        import faster_whisper  # noqa: F401
    except Exception:  # noqa: BLE001
        return False
    return True


@lru_cache(maxsize=2)
def _whisper(size: str):
    from faster_whisper import WhisperModel

    return WhisperModel(size, device="auto", compute_type="default", download_root=str(models_dir() / "whisper"))


def _decode_16k(src: Path, name: str, ctx: Context):
    """Audio mono 16 kHz en float32 decodificado con ffmpeg (evita depender de la versión de PyAV)."""
    import numpy as np

    ff = ffmpeg_path()
    if not ff:
        return str(src)
    proc = subprocess.run([ff, "-hide_banner", "-nostdin", "-loglevel", "error", "-i", str(src), "-vn", "-ac", "1",
                           "-ar", "16000", "-f", "f32le", "-"], capture_output=True, timeout=3600, check=False)
    ctx.check()
    if proc.returncode != 0 or not proc.stdout:
        raise ProcessingError(f"{name}: no es un archivo de audio o video válido")
    return np.frombuffer(proc.stdout, dtype=np.float32)


def _ts(seconds: float, sep: str) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


@register("audio.transcribe", available=whisper_available)
def transcribe(src: Path, out_dir: Path, name: str, params: dict, ctx: Context) -> list[Output]:
    size = choice(params.get("model"), ("tiny", "base", "small", "medium"), "base")
    language = choice(params.get("language"), ("auto", "es", "en", "pt", "fr", "de", "it"), "auto")
    output = choice(params.get("output"), ("txt", "srt", "vtt", "all"), "srt")
    ctx.log(f"Cargando modelo Whisper «{size}» (la primera vez se descarga)…")
    try:
        model = _whisper(size)
        segments, info = model.transcribe(_decode_16k(src, name, ctx), language=None if language == "auto" else language,
                                          vad_filter=True, beam_size=5)
        collected = []
        for seg in segments:
            ctx.check()
            collected.append(seg)
            if info.duration:
                ctx.progress(seg.end / info.duration)
    except (ProcessingError, Cancelled):
        raise
    except Exception as exc:  # noqa: BLE001
        raise ProcessingError(f"{name}: no se pudo transcribir ({exc})") from exc
    stem = Path(name).stem
    formats = ("txt", "srt", "vtt") if output == "all" else (output,)
    outputs: list[Output] = []
    for fmt in formats:
        out = unique(out_dir, stem, f".{fmt}")
        if fmt == "txt":
            body = "\n".join(s.text.strip() for s in collected) + "\n"
        elif fmt == "srt":
            body = "".join(f"{i}\n{_ts(s.start, ',')} --> {_ts(s.end, ',')}\n{s.text.strip()}\n\n" for i, s in enumerate(collected, 1))
        else:
            body = "WEBVTT\n\n" + "".join(f"{_ts(s.start, '.')} --> {_ts(s.end, '.')}\n{s.text.strip()}\n\n" for s in collected)
        out.write_text(body, encoding="utf-8")
        outputs.append((out, f"{name} → {out.name} ({len(collected)} segmentos, idioma {info.language})"))
    return outputs
