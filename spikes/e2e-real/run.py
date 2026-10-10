"""End-to-end check on real talks: transcribe, accept every filler / long-pause suggestion,
export, then transcribe the export again and compare.

Usage: python run.py [--judge MODEL] <video>...   (run from the repo with `uv run`)
--judge transcribes the export with a fixed whisper model, so runs with different models are heard
by the same ear.
Prints one JSON line per video. The video folder gets the usual trimscript outputs.
"""
import difflib
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

from trimscript import enhance, media, render, transcribe
from trimscript.project import Project, is_filler, project_path_for


JUDGE = ""


def words_of(items):
    return [re.sub(r"[^a-z0-9']", "", it.text.lower()) for it in items if it.kind != "pause" and it.text]


def loudness(path: Path) -> float:
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    return float(json.loads(err[err.rindex("{") : err.rindex("}") + 1])["input_i"])


def check(src: Path) -> dict:
    r: dict = {"file": src.name}
    info = media.probe(src)
    r["minutes"] = round(info.duration / 60, 1)
    r["video"] = f"{info.width}x{info.height}@{info.fps:.2f}"

    t = time.time()
    words, engine = transcribe.transcribe(src, "en", progress=lambda m: None)
    r["transcribe_s"] = round(time.time() - t, 1)
    proj = Project.from_words(src.name, info.duration, words, has_video=info.has_video, engine=engine)
    r["words"] = len(words)
    r["fillers_found"] = sum(1 for it in proj.items if it.kind == "filler")
    r["pauses_over_1s"] = sum(1 for it in proj.items if it.kind == "pause" and it.end - it.start > 1)

    t = time.time()
    r["browser_ready"] = media.browser_ready(info, src)
    media.proxy(src, info)
    r["preview_s"] = round(time.time() - t, 1)

    proj.trim_fillers()
    proj.tighten_pauses()
    proj.set_status(None, "accepted")
    proj.settings["enhance"] = True
    proj.save(project_path_for(src))
    r["cut_s"] = round(info.duration - proj.kept_duration(), 1)

    t = time.time()
    enhance.enhanced_audio(src)
    r["enhance_s"] = round(time.time() - t, 1)

    out = src.with_name(src.stem + ".trimscript.mp4")
    t = time.time()
    render.export(proj, src, out)
    r["export_s"] = round(time.time() - t, 1)
    oi = media.probe(out)
    r["duration_error_s"] = round(oi.duration - proj.kept_duration(), 2)
    r["loudness_lufs"] = round(loudness(out), 1)

    # the export, heard again: which fillers survived, and did any kept words get clipped?
    saved = os.environ.get("TRIMSCRIPT_WHISPER_MODEL")
    if JUDGE:
        os.environ["TRIMSCRIPT_WHISPER_MODEL"] = JUDGE
    try:
        again, _ = transcribe.transcribe(out, "en", progress=lambda m: None)
    finally:
        os.environ.pop("TRIMSCRIPT_WHISPER_MODEL", None)
        if saved:
            os.environ["TRIMSCRIPT_WHISPER_MODEL"] = saved
    removed = set()
    for a, b, _c in proj.cut_runs():
        removed.update(range(a, b + 1))
    expected = [w for w in words_of([it for i, it in enumerate(proj.items) if i not in removed]) if w]
    heard = [re.sub(r"[^a-z0-9']", "", w.lower()) for _, _, w in again]
    heard = [w for w in heard if w]
    r["fillers_left"] = sum(1 for w in heard if is_filler(w))
    sm = difflib.SequenceMatcher(None, expected, heard, autojunk=False)
    r["kept_words_match"] = round(sm.ratio(), 3)
    lost = sum(i2 - i1 for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace"))
    r["kept_words_lost_pct"] = round(100 * lost / max(len(expected), 1), 1)
    # lost words next to a cut edge are the ones a cut may have clipped; the rest is recognizer noise
    spans = proj.removed()
    kept_items = [it for i, it in enumerate(proj.items) if i not in removed and it.kind in ("word", "filler") and words_of([it])[0]]
    near = lambda t: any(abs(t - lo) < 0.35 or abs(t - hi) < 0.35 for lo, hi in spans)
    r["lost_at_cut_edge"] = sum(near(kept_items[k].start) or near(kept_items[k].end)
                                for op, i1, i2, _, _ in sm.get_opcodes() if op in ("delete", "replace") for k in range(i1, i2))
    r["cuts"] = len(spans)
    return r


if __name__ == "__main__":
    if not shutil.which("ffmpeg"):
        sys.exit("ffmpeg needed")
    args = sys.argv[1:]
    if args[:1] == ["--judge"]:
        JUDGE, args = args[1], args[2:]
    for arg in args:
        print(json.dumps(check(Path(arg))), flush=True)
