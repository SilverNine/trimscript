"""Speech to timed words. All local.

whisper.cpp (small.en, English only) through pywhispercpp, with a prompt full of fillers carried into every
chunk so "um" and "uh" stay in the transcript, and DTW token timestamps for word edges.

The language is always named, never detected, and the decoder runs without timestamp tokens: the
audio is split into chunks shorter than one 30 s window at quiet moments, each chunk is decoded
whole, and word times come only from DTW.
Parakeet TDT 0.6B v2 is an option (`trimscript[parakeet]`, Apple Silicon): faster, but it drops most
fillers once a recording is longer than a few seconds (see spikes/e2e-real/RESULTS.md).
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from trimscript import media

Word = tuple[float, float, str]

PARAKEET_MODEL = "mlx-community/parakeet-tdt-0.6b-v2"
WHISPER_MODEL = "small.en"
MODEL_SIZES = {WHISPER_MODEL: "~470 MB", "large-v3-turbo": "~1.6 GB"}
# small.en squeezes an "um" into the last few hundredths of a second and stretches the word before
# it over the sound, so a cut would leave most of the "um" in. A filler shorter than this starts
# this long before its end instead (three talks, heard back by large-v3-turbo: 224 fillers left
# after export without it, 51 with it, kept words unchanged).
FILLER_SPAN = {"small.en": 0.55}
# whisper.cpp DTW times run late: against Parakeet's word edges the median lag was 0.14 s for both
# starts and ends, on a synthetic demo and three conference talks. Left in, cuts eat the next word.
DTW_LAG = 0.14
CHUNK_MIN, CHUNK_MAX = 20.0, 28.0  # seconds; one chunk must fit in a 30 s window
# each chunk is prompted with the fillers plus the end of the previous chunk's text: without that
# context whisper writes fewer fillers (373 against 460 on a 36 min talk)
CONTEXT_WORDS = 60
FILLER_PROMPT = "Umm, so, uh, I was like, hmm, er, you know, um, I mean, uh-huh, mm-hmm. Uh, okay."


def check_language(language: str | None) -> str:
    """The spoken language must be named (en, de, ko...). There is no automatic detection."""
    code = (language or "").strip().lower()
    if not code.isalpha() or not 2 <= len(code) <= 3 or code == "auto":
        raise ValueError(f"name the spoken language as a code such as en or de, not {language!r}: "
                         "automatic language detection is not supported")
    return code


def transcribe(media_path: Path, language: str = "en", engine: str | None = None, progress=print) -> tuple[list[Word], str]:
    language = check_language(language)
    wav = media.speech_wav(media_path)
    if engine == "parakeet":
        progress("transcribing with Parakeet (first run downloads the model, ~1.2 GB)")
        words, name = _parakeet(wav), f"parakeet:{PARAKEET_MODEL}"
    else:
        model = whisper_model(language)
        size = f" (first run downloads the model, {MODEL_SIZES[model]})" if model in MODEL_SIZES else ""
        progress(f"transcribing with whisper.cpp {model}{size}")
        words, name = _whisper(wav, language, model), f"whisper.cpp:{model}"
        return widen_fillers(tighten(words, wav), FILLER_SPAN.get(model, 0.0)), name
    return tighten(words, wav), name


def widen_fillers(words: list[Word], span: float) -> list[Word]:
    """A filler shorter than `span` starts `span` before its end, taking the time from the word before
    (which keeps at least 0.1 s)."""
    from trimscript.project import is_filler

    if not span:
        return words
    out = [list(w) for w in words]
    for i, (a, b, text) in enumerate(out):
        if i and is_filler(text) and b - a < span:
            start = max(b - span, out[i - 1][0] + 0.1)
            if start < a:
                out[i][0] = round(start, 3)
                out[i - 1][1] = min(out[i - 1][1], out[i][0])
    return [(a, b, t) for a, b, t in out]


def _parakeet(wav: Path) -> list[Word]:
    try:
        from parakeet_mlx import from_pretrained
    except ImportError as e:
        raise RuntimeError("Parakeet needs Apple Silicon and `trimscript[parakeet]`") from e

    model = from_pretrained(PARAKEET_MODEL)
    result = model.transcribe(str(wav), chunk_duration=120.0, overlap_duration=15.0)
    words: list[list] = []
    for sent in result.sentences:
        for tok in sent.tokens:
            if not words or tok.text.startswith(" "):
                words.append([tok.start, tok.end, tok.text])
            else:
                words[-1][1] = tok.end
                words[-1][2] += tok.text
    return [(round(a, 3), round(b, 3), t.strip()) for a, b, t in words if t.strip()]


def whisper_model(language: str = "en") -> str:
    """TRIMSCRIPT_WHISPER_MODEL picks another ggml model, e.g. tiny.en for a quick check."""
    model = os.environ.get("TRIMSCRIPT_WHISPER_MODEL", WHISPER_MODEL)
    if model.endswith(".en") and language != "en":
        raise ValueError("TrimScript transcribes English only for now")
    return model


def _aheads(w, model: str):
    """DTW alignment heads for a model name such as large-v3-turbo or tiny.en."""
    key = "WHISPER_AHEADS_" + model.removesuffix("-q5_0").removesuffix("-q8_0").upper().replace("-", "_").replace(".", "_")
    if not hasattr(w.whisper_alignment_heads_preset, key):
        raise RuntimeError(f"no word timing heads for whisper model {model!r}")
    return getattr(w.whisper_alignment_heads_preset, key)


def chunks(x, sr: int, lo: float = CHUNK_MIN, hi: float = CHUNK_MAX, hop: float = 0.01) -> list[tuple[int, int]]:
    """Split samples into runs of lo..hi seconds, each ending in the middle of the longest quiet
    stretch in that range (or the quietest 10 ms when there is no quiet)."""
    import numpy as np

    n = int(sr * hop)
    db = _db(x, n)
    out, start = [], 0
    while len(x) - start > hi * sr:
        f0, f1 = (start + int(lo * sr)) // n, (start + int(hi * sr)) // n
        win = db[f0:f1]
        quiet = win < max(np.percentile(db, 10), -90.0) + 15
        best, run, best_mid = 0, 0, int(np.argmin(win))
        for k, q in enumerate(quiet):
            run = run + 1 if q else 0
            if run > best:
                best, best_mid = run, k - run + 1 + run // 2
        end = int((f0 + best_mid) * n)
        out.append((start, end))
        start = end
    out.append((start, len(x)))
    return out


def _whisper(wav: Path, language: str, model_name: str = WHISPER_MODEL) -> list[Word]:
    import wave

    import _pywhispercpp as w
    import numpy as np
    from pywhispercpp.model import Model

    model = Model(
        model_name,
        redirect_whispercpp_logs_to=None,
        # DTW needs flash attention off; the heads preset must match the model
        context_params={"flash_attn": False, "dtw_token_timestamps": True,
                        "dtw_aheads_preset": _aheads(w, model_name)},
        language=language, initial_prompt=FILLER_PROMPT, carry_initial_prompt=True,
        token_timestamps=True, no_timestamps=True, print_progress=False, print_realtime=False,
    )
    with wave.open(str(wav)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    toks, prev = [], ""
    for a, b in chunks(x, sr):
        prompt = " ".join([FILLER_PROMPT, *prev.split()[-CONTEXT_WORDS:]])
        stdout, sys.stdout = sys.stdout, sys.stderr  # pywhispercpp prints; stdout may belong to MCP
        try:
            model.transcribe(x[a:b], initial_prompt=prompt)
        finally:
            sys.stdout = stdout
        ctx = model._ctx
        offset = a / sr * 100  # t_dtw is in centiseconds from the chunk start
        text = []
        for s in range(w.whisper_full_n_segments(ctx)):
            for k in range(w.whisper_full_n_tokens(ctx, s)):
                t = w.whisper_full_get_token_data(ctx, s, k).t_dtw
                tok = w.whisper_full_get_token_text(ctx, s, k)
                toks.append({"text": tok, "t_dtw": t + offset if t >= 0 else t})
                if not tok.startswith(("[_", "<|")):
                    text.append(tok)
        prev = "".join(text)
    return _dtw_words([{"tokens": toks}])


def _dtw_words(segs: list[dict]) -> list[Word]:
    toks = [x for s in segs for x in s.get("tokens", [])
            if not x["text"].startswith(("[_", "<|")) and x.get("t_dtw", -1) >= 0]
    words: list[list] = []
    for x in toks:
        at = max(0.0, x["t_dtw"] / 100 - DTW_LAG)
        if not words or x["text"].startswith(" "):
            words.append([at, at, x["text"]])
        else:
            words[-1][2] += x["text"]
            words[-1][1] = at
    out = []
    for i, (a, b, text) in enumerate(words):
        nxt = words[i + 1][0] if i + 1 < len(words) else b + 0.3
        end = max(b, min(nxt, a + 0.6))
        if text.strip():
            out.append((round(a, 3), round(end, 3), text.strip()))
    return out


def _db(x, n: int):
    """Level of each n-sample frame in dB."""
    import numpy as np

    frames = x[: len(x) // n * n].reshape(-1, n)
    return 20 * np.log10(np.sqrt((frames**2).mean(1)) + 1e-9)


def _voiced(wav: Path, hop: float):
    import wave

    import numpy as np

    with wave.open(str(wav)) as f:
        sr = f.getframerate()
        x = np.frombuffer(f.readframes(f.getnframes()), dtype=np.int16).astype(np.float32) / 32768
    n = int(sr * hop)
    if len(x) < n:
        return np.zeros(0, dtype=bool)
    db = _db(x, n)
    floor = max(np.percentile(db, 10), -90.0)
    return db > max(floor + 15, db.max() - 50)


def sounds(words: list[Word], media_path: Path, hop: float = 0.01) -> list[tuple[float, float]]:
    """Voice between two words that the recognizer did not write down.

    Recognizers tidy away many fillers, more so on long recordings (Parakeet keeps an "um" in a
    four-second clip and drops it once the clip is part of a longer one). The sound is still in
    the audio, sitting in a small gap between words. These spans are offered for review as
    "unclear sound"; nothing classifies them, the person listens and decides.
    """
    voiced = _voiced(media.speech_wav(media_path), hop)
    out = []
    for (_, a1, _), (b0, _, _) in zip(words, words[1:]):
        gap = b0 - a1
        if not (0.12 <= gap < 0.6):  # longer gaps become pause items
            continue
        seg = voiced[int(a1 / hop) : int(b0 / hop)]
        if seg.sum() * hop >= 0.1:
            out.append((round(a1, 3), round(b0, 3)))
    return out


def tighten(words: list[Word], wav: Path, hop: float = 0.01) -> list[Word]:
    """Pull word edges in to where the voice actually is.

    Recognizers stretch a word over the silence after it (Parakeet's last token in a sentence can
    swallow a second or more). Cuts and pause detection need the real edges.
    """
    import numpy as np

    voiced = _voiced(wav, hop)
    if not len(voiced):
        return words

    out = []
    for a, b, text in words:
        i0, i1 = int(a / hop), min(int(np.ceil(b / hop)), len(voiced))
        idx = np.flatnonzero(voiced[i0:i1])
        if len(idx):
            na = a if idx[0] * hop < 0.3 else a + idx[0] * hop
            nb = min(b, a + (idx[-1] + 1) * hop + 0.04)
            if nb - na >= 0.05:
                a, b = na, nb
        out.append((round(a, 3), round(b, 3), text))
    return out
