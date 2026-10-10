import pytest

import numpy as np

from trimscript.transcribe import check_language, chunks, whisper_model, widen_fillers


def test_language_must_be_named():
    assert check_language("EN") == "en"
    assert check_language("de") == "de"
    for bad in ("auto", "", None, "english", "e1"):
        with pytest.raises(ValueError):
            check_language(bad)


def test_chunks_fit_a_window_and_end_in_quiet():
    sr = 1000
    rng = np.random.default_rng(0)
    x = rng.normal(0, 0.3, 95 * sr).astype(np.float32)
    for k in range(0, 95_000, 3000):
        x[k + 2600 : k + 3000] = 0.0001  # short gaps between phrases
    x[24_000:24_600] = 0.0001  # the longest quiet stretch in 20..28 s
    parts = chunks(x, sr)
    assert parts[0][0] == 0 and parts[-1][1] == len(x)
    assert all(b - a <= 28 * sr for a, b in parts)
    assert all(p[1] == q[0] for p, q in zip(parts, parts[1:]))
    assert 24_000 <= parts[0][1] <= 24_600



def test_short_fillers_take_time_from_the_word_before():
    words = [(0.0, 1.0, "talk,"), (1.0, 1.06, "uh,"), (1.1, 1.8, "building")]
    assert widen_fillers(words, 0.55) == [(0.0, 0.51, "talk,"), (0.51, 1.06, "uh,"), (1.1, 1.8, "building")]
    # the word before keeps 0.1 s; long fillers are left alone
    assert widen_fillers([(0.0, 0.3, "so"), (0.3, 0.4, "um")], 0.55) == [(0.0, 0.1, "so"), (0.1, 0.4, "um")]
    assert widen_fillers([(0.0, 1.0, "so"), (1.0, 1.7, "um")], 0.55) == [(0.0, 1.0, "so"), (1.0, 1.7, "um")]


def test_english_only(monkeypatch):
    monkeypatch.delenv("TRIMSCRIPT_WHISPER_MODEL", raising=False)
    assert whisper_model("en") == "small.en"
    with pytest.raises(ValueError, match="English only"):
        whisper_model("de")
