"""Exports against real (tiny, generated) media. Skipped when ffmpeg is missing."""
import shutil
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction

import pytest

from trimscript import media, render
from trimscript.project import Project

pytestmark = pytest.mark.skipif(not shutil.which("ffmpeg"), reason="ffmpeg not installed")

WORDS = [(0.5, 1.0, "one"), (1.5, 2.0, "two"), (2.5, 3.0, "three"), (3.5, 4.0, "four")]


@pytest.fixture
def clip(tmp_path):
    path = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc2=s=320x240:r=30000/1001:d=5",
         "-f", "lavfi", "-i", "sine=f=440:d=5", "-shortest", "-c:v", "libx264", "-c:a", "aac", str(path)],
        check=True,
    )
    proj = Project.from_words("clip.mp4", media.probe(path).duration, WORDS)
    proj.add_cut("w1", "w1")  # "two"
    return path, proj


def test_mp4_has_matching_streams(clip, tmp_path):
    path, proj = clip
    out = render.export(proj, path, tmp_path / "out.mp4")
    info = media.probe(out)
    assert info.has_video and info.has_audio
    assert info.duration == pytest.approx(proj.kept_duration(), abs=0.1)


def test_fcpxml_cuts_on_frames(clip, tmp_path):
    path, proj = clip
    out = render.export(proj, path, tmp_path / "out.fcpxml")
    root = ET.parse(out).getroot()
    assert root.get("version") == "1.9"
    fd = Fraction(root.find("resources/format").get("frameDuration")[:-1])
    assert fd == Fraction(1001, 30000)
    clips = root.findall(".//spine/asset-clip")
    assert len(clips) == 2
    for c in clips:
        for attr in ("offset", "start", "duration"):
            v = c.get(attr)
            if v != "0s":
                assert (Fraction(v[:-1]) / fd).denominator == 1, f"{attr}={v} is off the frame grid"
    # second clip starts where the first one ends on the timeline
    assert Fraction(clips[1].get("offset")[:-1]) == Fraction(clips[0].get("duration")[:-1])


def test_enhance_keeps_length_and_hits_loudness(tmp_path, monkeypatch):
    import json

    from trimscript import enhance

    monkeypatch.setattr(media, "CACHE", tmp_path / "cache")
    src = tmp_path / "voice.wav"
    # a tone that comes and goes (speech-like level changes) over steady noise
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i",
         "sine=f=220:d=8,volume='0.3*gt(mod(t,2),0.6)':eval=frame",
         "-f", "lavfi", "-i", "anoisesrc=d=8:c=pink:a=0.01", "-filter_complex", "amix=inputs=2:normalize=0",
         "-ar", "48000", str(src)],
        check=True,
    )
    out = enhance.enhanced_audio(src)
    assert media.probe(out).duration == pytest.approx(media.probe(src).duration, abs=0.05)
    err = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(out), "-af", "loudnorm=print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    ).stderr
    loud = float(json.loads(err[err.rindex("{") : err.rindex("}") + 1])["input_i"])
    assert loud == pytest.approx(enhance.LOUDNESS, abs=1.0)


def test_sounds_finds_voice_between_words_only(tmp_path):
    from trimscript import transcribe

    path = tmp_path / "talk.wav"
    on = "between(t,0.5,1.0)+between(t,1.15,1.35)+between(t,1.5,2.0)+between(t,2.5,3.0)"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=4",
         "-af", f"volume='{on}':eval=frame", str(path)],
        check=True,
    )
    words = [(0.5, 1.0, "a"), (1.5, 2.0, "b"), (2.5, 3.0, "c")]
    assert transcribe.sounds(words, path) == [(1.0, 1.5)]


def test_tighten_pulls_a_stretched_word_end_back_to_the_voice(tmp_path):
    from trimscript import transcribe

    path = tmp_path / "talk.wav"
    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=f=220:d=3",
         "-af", "volume='between(t,0.5,1.0)':eval=frame", "-ar", "16000", str(path)],
        check=True,
    )
    [(a, b, _)] = transcribe.tighten([(0.5, 2.5, "word")], path)
    assert a == 0.5 and b == pytest.approx(1.04, abs=0.05)  # volume switches per audio frame


def test_select_expression_with_many_ranges(tmp_path):
    """A long talk keeps hundreds of ranges; ffmpeg must still parse the select expression."""
    ranges = [(i * 0.2, i * 0.2 + 0.1) for i in range(600)]
    script = tmp_path / "graph.txt"
    script.write_text(f"[0:v]select='{render._select_expr(ranges, 1 / 5)}',setpts=N/FRAME_RATE/TB[v]")
    proc = subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "testsrc=d=120:r=5:s=64x36",
         media.filter_script_option(), str(script), "-map", "[v]", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stderr[-300:]
