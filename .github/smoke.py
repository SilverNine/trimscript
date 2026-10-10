"""End-to-end smoke check through the installed CLI: transcribe a spoken clip, remove its fillers,
tighten pauses, export WAV and SRT. Uses the small tiny.en model so CI stays fast.

Usage: python .github/smoke.py <speech.wav> <trimscript command...>
"""
import json
import os
import subprocess
import sys
import wave
from pathlib import Path

clip = Path(sys.argv[1]).resolve()
trimscript = sys.argv[2:]
env = {**os.environ, "TRIMSCRIPT_WHISPER_MODEL": "tiny.en"}


def run(*args: str) -> str:
    print("$ trimscript", *args, flush=True)
    out = subprocess.run([*trimscript, *args], env=env, check=True, capture_output=True, text=True)
    sys.stderr.write(out.stderr[-2000:])
    return out.stdout


def seconds(p: Path) -> float:
    with wave.open(str(p)) as f:
        return f.getnframes() / f.getframerate()


print(f"clip: {seconds(clip):.2f} s", flush=True)
assert seconds(clip) > 1, "the speech synthesizer produced no audio"
run("transcribe", str(clip))
proj = json.loads(run("show", str(clip), "--json"))
words = [it["text"] for it in proj["items"] if it["kind"] in ("word", "filler")]
print("heard:", " ".join(words))
assert len(words) >= 5, f"expected a sentence, got {words}"

run("fillers", str(clip))
run("pauses", str(clip))
out = clip.with_name("smoke-out.wav")
run("export", str(clip), "-o", str(out))
srt = clip.with_name("smoke-out.srt")
run("export", str(clip), "-o", str(srt))

assert out.exists() and srt.read_text(encoding="utf-8").strip(), "export missing"
print(f"source {seconds(clip):.2f}s, export {seconds(out):.2f}s")
assert 1.0 < seconds(out) <= seconds(clip) + 0.05
print("smoke ok")
