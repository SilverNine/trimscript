"""Cut the recorded take into the demo video.

Usage: python compose.py <take dir> <terminal mp4> <cards dir> <out.mp4>
Editor frames carry wall-clock times; each segment is a window of them, optionally sped up.
The terminal recording is aligned to the editor by a fixed offset measured from the take.
"""
import json
import subprocess
import sys
from pathlib import Path

take, term, cards, out = map(Path, sys.argv[1:5])
TERM_OFFSET = 10.1  # terminal t = (editor t - agent mark) - offset
FPS = 30
BG = "0x111111"
work = out.parent / "segs"
work.mkdir(exist_ok=True)

frames = json.loads((take / "frames.json").read_text())
marks = {m["name"]: m["t"] / 1000 for m in json.loads((take / "marks.json").read_text())}


def ff(*args):
    subprocess.run(["ffmpeg", "-v", "error", "-y", *args], check=True)


def editor_clip(a: float, b: float, speed: float, name: str) -> Path:
    """Editor frames between wall-clock a and b (seconds), as a constant-rate clip."""
    sel = [f for f in frames if a <= f["t"] / 1000 <= b]
    before = [f for f in frames if f["t"] / 1000 < a]
    if before:
        sel = [before[-1]] + sel  # the picture on screen at time a
    lines = []
    for i, f in enumerate(sel):
        t0 = max(f["t"] / 1000, a)
        t1 = sel[i + 1]["t"] / 1000 if i + 1 < len(sel) else b
        d = max(t1 - t0, 0) / speed
        if d <= 0:
            continue
        lines.append(f"file '{(take / 'frames' / f['f']).resolve()}'\nduration {d:.4f}\n")
    lines.append(f"file '{(take / 'frames' / sel[-1]['f']).resolve()}'\n")
    lst = work / f"{name}.txt"
    lst.write_text("".join(lines))
    clip = work / f"{name}-raw.mp4"
    ff("-f", "concat", "-safe", "0", "-i", str(lst), "-vf", f"fps={FPS},scale=1920:1080,format=yuv420p",
       "-c:v", "libx264", "-crf", "16", "-preset", "medium", str(clip))
    return clip


def card(png: str, seconds: float, name: str) -> Path:
    clip = work / f"{name}.mp4"
    ff("-loop", "1", "-t", f"{seconds}", "-i", str(cards / png), "-vf", f"fps={FPS},format=yuv420p",
       "-c:v", "libx264", "-crf", "16", str(clip))
    return clip


def framed(raw: Path, caps: list[tuple[str, float, float]], name: str) -> Path:
    """Editor at 90% on a dark background, captions in the band below."""
    inputs = ["-i", str(raw)]
    for c, _, _ in caps:
        inputs += ["-i", str(cards / c)]
    g = f"color={BG}:s=1920x1080:r={FPS}[bg];[0]scale=1728:972[ed];[bg][ed]overlay=96:10:shortest=1[v0]"
    for k, (_, a, b) in enumerate(caps):
        g += f";[v{k}][{k + 1}]overlay=0:988:enable='between(t,{a},{b})'[v{k + 1}]"
    clip = work / f"{name}.mp4"
    ff(*inputs, "-filter_complex", g, "-map", f"[v{len(caps)}]", "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(clip))
    return clip


def agent_part(rel_a: float, rel_b: float, speed: float, name: str) -> Path:
    """Editor on the left, the terminal with Claude Code on the right, the same window of time."""
    ag = marks["agent"]
    raw = editor_clip(ag + rel_a, ag + rel_b, speed, name)
    ta, tb = rel_a - TERM_OFFSET, rel_b - TERM_OFFSET
    g = (f"color={BG}:s=1920x1080:r={FPS}[bg];"
         f"[0]scale=1200:675[ed];"
         f"[1]trim={max(ta, 0)}:{tb},setpts=(PTS-STARTPTS)/{speed},fps={FPS},crop=640:900:0:100[tm];"
         f"[bg][ed]overlay=40:150:shortest=1[a];[a][tm]overlay=1250:44[b];[b][2]overlay=0:988[v]")
    clip = work / f"{name}.mp4"
    ff("-i", str(raw), "-i", str(term), "-i", str(cards / "c4.png"), "-filter_complex", g, "-map", "[v]",
       "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p", str(clip))
    return clip


m = marks
parts = [card("title.png", 2.5, "title")]
a_len = m["agent"] - m["open"]
parts.append(framed(editor_clip(m["open"], m["agent"], 1, "A"),
                    [("c1.png", 0, m["delete"] - m["open"]),
                     ("c2.png", m["delete"] - m["open"], m["fillers"] - m["open"]),
                     ("c3.png", m["fillers"] - m["open"], a_len)], "A"))
parts.append(agent_part(10.5, 16.5, 2, "B1"))
parts.append(agent_part(16.5, 56.0, 6, "B2"))
parts.append(agent_part(56.0, 60.0, 1, "B3"))
c_len = m["end"] - m["review"]
parts.append(framed(editor_clip(m["review"], m["end"], 1, "C"),
                    [("c5.png", 0, 6.9), ("c6.png", 6.9, c_len)], "C"))
parts.append(card("end.png", 4, "end"))

lst = work / "all.txt"
lst.write_text("".join(f"file '{p.resolve()}'\n" for p in parts))
ff("-f", "concat", "-safe", "0", "-i", str(lst), "-c:v", "libx264", "-crf", "18", "-preset", "slow",
   "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(out))
print(out, subprocess.check_output(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(out)]).decode().strip())
