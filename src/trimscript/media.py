"""ffprobe / ffmpeg helpers. ffmpeg is never bundled; we call the one on the user's PATH."""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

CACHE = Path.home() / ".cache" / "trimscript"


class MissingFFmpeg(RuntimeError):
    pass


def ffmpeg_bin(name: str = "ffmpeg") -> str:
    path = shutil.which(name)
    if not path:
        hint = {"darwin": "brew install ffmpeg", "win32": "winget install ffmpeg"}.get(sys.platform, "install ffmpeg with your package manager")
        raise MissingFFmpeg(f"{name} not found on PATH ({hint})")
    return path


@dataclass
class MediaInfo:
    duration: float
    has_video: bool
    has_audio: bool
    width: int = 0
    height: int = 0
    vcodec: str = ""
    fps: float = 0.0
    rate: str = ""  # exact frame rate as a fraction, e.g. 30000/1001
    sample_rate: int = 0
    channels: int = 0
    acodec: str = ""
    container: str = ""


def probe(path: Path) -> MediaInfo:
    out = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "error", "-show_entries",
         "format=duration,format_name:stream=codec_type,codec_name,width,height,avg_frame_rate,r_frame_rate,sample_rate,channels", "-of", "json", str(path)],
        check=True, capture_output=True, text=True,
    ).stdout
    d = json.loads(out)
    streams = d.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video" and s.get("codec_name") not in ("mjpeg", "png")), None)
    a = next((s for s in streams if s.get("codec_type") == "audio"), None)
    return MediaInfo(
        duration=float(d["format"]["duration"]),
        has_video=v is not None,
        has_audio=a is not None,
        width=int(v.get("width", 0)) if v else 0,
        height=int(v.get("height", 0)) if v else 0,
        vcodec=v.get("codec_name", "") if v else "",
        fps=_rate(v.get("avg_frame_rate", "0/1")) if v else 0.0,
        rate=v.get("r_frame_rate", "") if v else "",
        sample_rate=int(a.get("sample_rate", 0)) if a else 0,
        channels=int(a.get("channels", 0)) if a else 0,
        acodec=a.get("codec_name", "") if a else "",
        container=d["format"].get("format_name", ""),
    )


def _rate(r: str) -> float:
    num, _, den = r.partition("/")
    return float(num) / float(den) if den and float(den) else 0.0


def workdir(media: Path) -> Path:
    """Per-media cache folder, keyed by path, size and mtime so an edited file gets a fresh one."""
    media = Path(media).resolve()
    st = media.stat()
    key = hashlib.sha256(f"{media}|{st.st_size}|{st.st_mtime_ns}".encode()).hexdigest()[:16]
    d = CACHE / key
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_ffmpeg(args: list[str]) -> None:
    proc = subprocess.run([ffmpeg_bin(), "-hide_banner", "-loglevel", "error", "-y", *args], capture_output=True, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"ffmpeg failed: {proc.stderr.strip()[-2000:]}")


def filter_script_option() -> str:
    """ffmpeg 7 reads an option value from a file with "-/option"; 6 and older need the old name."""
    out = subprocess.run([ffmpeg_bin(), "-hide_banner", "-version"], capture_output=True, text=True).stdout
    major = re.match(r"ffmpeg version n?(\d+)\.", out)
    return "-/filter_complex" if major is None or int(major.group(1)) >= 7 else "-filter_complex_script"


def h264_encoder() -> list[str]:
    """Hardware H.264 on macOS, libx264 elsewhere."""
    encoders = subprocess.run([ffmpeg_bin(), "-hide_banner", "-encoders"], capture_output=True, text=True).stdout
    if "h264_videotoolbox" in encoders:
        return ["-c:v", "h264_videotoolbox", "-b:v", "6M", "-allow_sw", "1"]
    return ["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"]


def speech_wav(media: Path) -> Path:
    """16 kHz mono WAV for speech recognition."""
    out = workdir(media) / "speech16k.wav"
    if not out.exists():
        run_ffmpeg(["-i", str(media), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(out)])
    return out


BROWSER_AUDIO = {"aac", "mp3", "pcm_s16le", "opus", "flac"}


def browser_ready(info: MediaInfo, path: Path) -> bool:
    """Chrome / Safari can play and seek this file as is, so no proxy needs to be made first."""
    if info.acodec and info.acodec not in BROWSER_AUDIO:
        return False
    if not info.has_video:
        return path.suffix.lower() in (".m4a", ".mp3", ".wav", ".aac", ".flac", ".mp4")
    if not (info.vcodec == "h264" and info.height <= 1080 and "mp4" in info.container):
        return False
    # the editor jumps over every cut while playing; a long keyframe interval makes each jump stall
    return keyframe_interval(path) <= 1.0


def keyframe_interval(path: Path, probe_seconds: int = 30) -> float:
    out = subprocess.run(
        [ffmpeg_bin("ffprobe"), "-v", "error", "-select_streams", "v:0", "-skip_frame", "nokey",
         "-read_intervals", f"%+{probe_seconds}", "-show_entries", "frame=pts_time", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    ).stdout.split()
    times = sorted(float(t) for t in out if t.replace(".", "", 1).isdigit())
    if len(times) < 2:
        return float("inf")
    return (times[-1] - times[0]) / (len(times) - 1)


def proxy(media: Path, info: MediaInfo | None = None) -> Path:
    """What the editor plays. The source itself when the browser can handle it; otherwise a copy
    with a keyframe every second, so seeking is instant."""
    info = info or probe(media)
    if browser_ready(info, Path(media)):
        return Path(media)
    wd = workdir(media)
    if not info.has_video:
        out = wd / "proxy.m4a"
        if not out.exists():
            run_ffmpeg(["-i", str(media), "-vn", "-c:a", "aac", "-b:a", "160k", str(out)])
        return out
    out = wd / "proxy.mp4"
    if not out.exists():
        scale = ["-vf", "scale=-2:720"] if info.height > 720 else []
        run_ffmpeg([
            "-i", str(media), *scale, *h264_encoder(), "-g", "30", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart", str(out),
        ])
    return out
