"""Exports: MP4 / WAV from the kept ranges, SRT / VTT captions on the edited timeline."""
from __future__ import annotations

import tempfile
from fractions import Fraction
from pathlib import Path
from xml.sax.saxutils import escape

from trimscript import media
from trimscript.project import Project


def snapped_kept(proj: Project, fps: float) -> list[tuple[float, float]]:
    """Kept ranges on the frame grid, so every cut drops whole frames and audio never drifts from video."""
    kept = proj.kept()
    if fps <= 0:
        return kept
    out = []
    for a, b in kept:
        fa, fb = round(a * fps), round(b * fps)
        if fb > fa:
            out.append((fa / fps, fb / fps))
    return out


def _select_expr(ranges: list[tuple[float, float]], frame: float) -> str:
    # half a frame of slack keeps boundary frames from flickering in and out
    eps = frame / 2 if frame else 0.0005
    terms = [f"between(t\\,{a - eps:.4f}\\,{b - eps:.4f})" for a, b in ranges]

    # a balanced sum: ffmpeg 9 refuses expressions nested more than about a hundred deep, which a
    # flat a+b+c... chain of a long talk's few hundred kept ranges is
    def tree(lo: int, hi: int) -> str:
        if hi - lo == 1:
            return terms[lo]
        mid = (lo + hi) // 2
        return f"({tree(lo, mid)}+{tree(mid, hi)})"

    return tree(0, len(terms)) if terms else "0"


def export_media(proj: Project, source: Path, out: Path) -> Path:
    info = media.probe(source)
    want_video = info.has_video and out.suffix.lower() in (".mp4", ".mov", ".m4v")
    fps = info.fps if want_video else 0.0
    ranges = snapped_kept(proj, fps)
    if not ranges:
        raise ValueError("nothing left to export: every part is removed")

    enhance = info.has_audio and proj.settings.get("enhance")
    extra = ["-i", str(_enhanced(source))] if enhance else []
    audio_in = "[1:a]" if enhance else "[0:a]"
    parts = []
    if want_video:
        parts.append(f"[0:v]select='{_select_expr(ranges, 1 / fps)}',setpts=N/FRAME_RATE/TB[v]")
    if info.has_audio:
        # aselect keeps or drops whole audio frames, so first slice audio into ~1 ms frames
        # sources often carry slightly less audio than video; pad so the streams end together
        pad = f",apad=whole_dur={sum(b - a for a, b in ranges):.4f}" if want_video else ""
        parts.append(f"{audio_in}asetnsamples=n=64:p=0,aselect='{_select_expr(ranges, 0)}',asetpts=N/SR/TB{pad}[a]")
    graph = ";\n".join(parts)

    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False) as f:
        f.write(graph)
        script = f.name
    maps = (["-map", "[v]"] if want_video else []) + (["-map", "[a]"] if info.has_audio else [])
    if want_video:
        codec = [*media.h264_encoder(), "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-movflags", "+faststart"]
    elif out.suffix.lower() == ".wav":
        codec = ["-c:a", "pcm_s16le"]
    else:
        codec = ["-c:a", "aac", "-b:a", "192k"]
    try:
        media.run_ffmpeg(["-i", str(source), *extra, media.filter_script_option(), script, *maps, *codec, str(out)])
    finally:
        Path(script).unlink(missing_ok=True)
    return out


def _enhanced(source: Path) -> Path:
    from trimscript.enhance import enhanced_audio

    return enhanced_audio(source)


def _timeline(proj: Project):
    """Map source time to edited time."""
    removed = proj.removed()

    def at(t: float) -> float:
        shift = 0.0
        for lo, hi in removed:
            if hi <= t:
                shift += hi - lo
            elif lo < t:
                shift += t - lo
        return t - shift

    return at


def captions(proj: Project, max_chars: int = 42, max_gap: float = 0.6) -> list[tuple[float, float, str]]:
    """Group kept words into caption lines on the edited timeline."""
    at = _timeline(proj)
    removed_ids = set()
    for a, b, _ in proj.cut_runs():
        removed_ids.update(it.id for it in proj.items[a : b + 1])
    words = [it for it in proj.items if it.text and it.id not in removed_ids]

    lines, cur = [], []
    for w in words:
        if cur:
            text = " ".join(x.text for x in cur + [w])
            gap = w.start - cur[-1].end
            if len(text) > max_chars or gap > max_gap or cur[-1].text.endswith((".", "?", "!")):
                lines.append(cur)
                cur = []
        cur.append(w)
    if cur:
        lines.append(cur)
    return [(at(ln[0].start), at(ln[-1].end), " ".join(x.text for x in ln)) for ln in lines]


def _ts(t: float, sep: str) -> str:
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d}{sep}{ms:03d}"


def export_captions(proj: Project, out: Path) -> Path:
    vtt = out.suffix.lower() == ".vtt"
    sep = "." if vtt else ","
    rows = ["WEBVTT", ""] if vtt else []
    for i, (a, b, text) in enumerate(captions(proj), 1):
        if not vtt:
            rows.append(str(i))
        rows += [f"{_ts(a, sep)} --> {_ts(b, sep)}", text, ""]
    out.write_text("\n".join(rows))
    return out


def export(proj: Project, source: Path, out: Path) -> Path:
    """Write a new file. The source is never modified, so writing over it is refused."""
    if Path(out).resolve() == Path(source).resolve():
        raise ValueError("refusing to overwrite the source file: choose another output path")
    if out.suffix.lower() in (".srt", ".vtt"):
        return export_captions(proj, out)
    if out.suffix.lower() == ".fcpxml":
        return export_fcpxml(proj, source, out)
    return export_media(proj, source, out)


def _fraction(rate: str, fps: float) -> Fraction:
    try:
        f = Fraction(rate)
        if f > 0:
            return f
    except (ValueError, ZeroDivisionError):
        pass
    return Fraction(round(fps * 1000), 1000) if fps > 0 else Fraction(30)


def export_fcpxml(proj: Project, source: Path, out: Path) -> Path:
    """One asset-clip per kept range on the spine, cut on frame boundaries.

    Opens in Final Cut Pro and DaVinci Resolve, where every cut stays adjustable.
    """
    info = media.probe(source)
    rate = _fraction(info.rate, info.fps)
    frame = 1 / rate  # seconds per frame, exact

    def t(frames: int) -> str:
        # keep the frame duration's denominator (82/30s, not 41/15s): NLEs read these as frame counts
        return f"{frames * frame.numerator}/{frame.denominator}s" if frames else "0s"

    total = round(info.duration * rate)
    clips, offset = [], 0
    for a, b in proj.kept():
        fa, fb = round(a * rate), round(b * rate)
        if fb <= fa:
            continue
        clips.append((offset, fa, fb - fa))
        offset += fb - fa
    if not clips:
        raise ValueError("nothing left to export: every part is removed")

    name = escape(source.stem, {'"': "&quot;"})
    fmt_attrs = f'frameDuration="{t(1)}"'
    if info.has_video:
        fmt_attrs += f' width="{info.width}" height="{info.height}"'
    audio = ""
    if info.has_audio:
        audio = f' hasAudio="1" audioSources="1" audioChannels="{info.channels or 2}" audioRate="{info.sample_rate or 48000}"'
    rows = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!DOCTYPE fcpxml>",
        '<fcpxml version="1.9">',
        "  <resources>",
        f'    <format id="r1" {fmt_attrs}/>',
        f'    <asset id="r2" name="{name}" start="0s" duration="{t(total)}" hasVideo="{int(info.has_video)}" format="r1"{audio}>',
        f'      <media-rep kind="original-media" src="{escape(source.resolve().as_uri(), {chr(34): "&quot;"})}"/>',
        "    </asset>",
        "  </resources>",
        "  <library>",
        '    <event name="trimscript">',
        f'      <project name="{name} (trimscript)">',
        f'        <sequence format="r1" duration="{t(offset)}" tcStart="0s" tcFormat="NDF" audioLayout="stereo" audioRate="48k">',
        "          <spine>",
    ]
    for off, start, dur in clips:
        rows.append(f'            <asset-clip ref="r2" name="{name}" offset="{t(off)}" start="{t(start)}" duration="{t(dur)}" tcFormat="NDF"/>')
    rows += ["          </spine>", "        </sequence>", "      </project>", "    </event>", "  </library>", "</fcpxml>", ""]
    out.write_text("\n".join(rows))
    return out
