"""The project file: one JSON document next to the media, shared by the editor, the CLI and agents.

Nothing here touches the media. Every edit is a cut over a run of transcript items, and the
times to remove are derived from the words, so the editor preview and the export always agree.
"""
from __future__ import annotations

import contextlib
import json
import os
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass, field
from pathlib import Path

VERSION = 1
PAUSE_MIN = 0.6  # gaps at least this long become pause items you can delete
PAUSE_KEEP = 0.12  # silence kept on each side when a pause is shortened
EDGE_PAD = 0.08  # breathing room kept between a word and a neighbouring pause

FILLER_WORDS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "hm", "mm", "mhm"}


def normalize(text: str) -> str:
    return re.sub(r"[^a-z]", "", text.lower())


def is_filler(text: str) -> bool:
    return normalize(text) in FILLER_WORDS


@dataclass
class Item:
    id: str
    text: str
    start: float
    end: float
    kind: str = "word"  # word | filler | sound | pause


@dataclass
class Cut:
    id: str
    first: str  # item id, inclusive
    last: str  # item id, inclusive
    status: str = "accepted"  # accepted | suggested
    by: str = "user"  # user | fillers | pauses | agent
    reason: str = ""
    nudge: list[float] = field(default_factory=lambda: [0.0, 0.0])  # seconds added to start / end edge


@dataclass
class Project:
    source: str
    duration: float
    has_video: bool = True
    language: str = "en"
    engine: str = ""
    items: list[Item] = field(default_factory=list)
    cuts: list[Cut] = field(default_factory=list)
    settings: dict = field(default_factory=dict)  # enhance: bool
    version: int = VERSION
    rev: int = 0

    # ---------- construction ----------

    @classmethod
    def from_words(cls, source: str, duration: float, words: list[tuple[float, float, str]],
                   sounds: list[tuple[float, float]] = (), **kw) -> Project:
        """Build items from (start, end, text) words, inserting pause items for long gaps and
        sound items (voice the recognizer left out) where given."""
        items: list[Item] = []
        prev_end = 0.0
        n = 0
        entries = sorted([(s, e, t) for s, e, t in words] + [(s, e, None) for s, e in sounds], key=lambda w: w[0])
        for start, end, text in entries:
            if text is None:
                items.append(Item(f"s{n}", "", start, end, "sound"))
                n += 1
                prev_end = max(prev_end, end)
                continue
            if start - prev_end >= PAUSE_MIN:
                items.append(Item(f"p{n}", "", prev_end, start, "pause"))
                n += 1
            items.append(Item(f"w{n}", text, start, end, "filler" if is_filler(text) else "word"))
            n += 1
            prev_end = max(prev_end, end)
        if duration - prev_end >= PAUSE_MIN:
            items.append(Item(f"p{n}", "", prev_end, duration, "pause"))
        return cls(source=source, duration=duration, items=items, **kw)

    # ---------- persistence ----------

    @classmethod
    def load(cls, path: Path) -> Project:
        return cls.load_dict(json.loads(Path(path).read_text()))

    @classmethod
    def load_dict(cls, d: dict) -> Project:
        d = dict(d)
        d["items"] = [Item(**i) for i in d.get("items", [])]
        d["cuts"] = [Cut(**c) for c in d.get("cuts", [])]
        d.pop("removed", None)
        d.pop("kept_duration", None)
        d.pop("kept_if_accepted", None)
        return cls(**d)

    def to_dict(self, derived: bool = True) -> dict:
        # dataclasses.asdict deep-copies every item, which costs ~25 ms on a 2-hour transcript
        d = {f: getattr(self, f) for f in self.__dataclass_fields__}
        d["items"] = [dict(vars(i)) for i in self.items]
        d["cuts"] = [dict(vars(c)) for c in self.cuts]
        d["settings"] = dict(self.settings)
        if derived:
            d["removed"] = self.removed()
            d["kept_duration"] = round(self.kept_duration(), 3)
            d["kept_if_accepted"] = round(self.kept_duration(with_suggestions=True), 3)
        return d

    def save(self, path: Path) -> None:
        """Atomic write so a crash or a concurrent reader never sees half a file."""
        path = Path(path)
        self.rev += 1
        fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".trimscript-", suffix=".json")
        with os.fdopen(fd, "w") as f:
            f.write(dumps(self.to_dict()))
        os.replace(tmp, path)

    # ---------- queries ----------

    def index(self) -> dict[str, int]:
        # items never change after transcription, so the id -> position map is built once
        cached = self.__dict__.get("_index")
        if cached is None or len(cached) != len(self.items):
            cached = {it.id: i for i, it in enumerate(self.items)}
            self.__dict__["_index"] = cached
        return cached

    def cut_runs(self, statuses=("accepted",)) -> list[tuple[int, int, Cut]]:
        idx = self.index()
        runs = []
        for c in self.cuts:
            if c.status in statuses and c.first in idx and c.last in idx:
                a, b = sorted((idx[c.first], idx[c.last]))
                runs.append((a, b, c))
        return sorted(runs, key=lambda r: r[0])

    def removed(self, statuses=("accepted",)) -> list[list[float]]:
        """Time ranges to drop, merged and sorted. The single source of truth for preview and export."""
        removed_items = [False] * len(self.items)
        for a, b, _ in self.cut_runs(statuses):
            for i in range(a, b + 1):
                removed_items[i] = True

        # hand-tuned edges, keyed by the item where a cut starts / ends
        idx = self.index()
        left_nudge, right_nudge = {}, {}
        for c in self.cuts:
            if c.status in statuses and c.first in idx and c.last in idx:
                a, b = sorted((idx[c.first], idx[c.last]))
                left_nudge[a] = c.nudge[0]
                right_nudge[b] = c.nudge[1]

        spans: list[list[float]] = []
        i = 0
        while i < len(self.items):
            if not removed_items[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(self.items) and removed_items[j + 1]:
                j += 1
            lo = max(0.0, self._left(i) + left_nudge.get(i, 0.0))
            hi = min(self.duration, self._right(j) + right_nudge.get(j, 0.0))
            if hi - lo > 0.01:
                spans.append([round(lo, 3), round(hi, 3)])
            i = j + 1
        return _merge(spans)

    def _left(self, i: int) -> float:
        it = self.items[i]
        if it.kind == "pause":
            return it.start + (PAUSE_KEEP if i > 0 else 0)
        if i == 0:
            return 0.0
        prev = self.items[i - 1]
        if prev.kind == "pause":
            return max(prev.start, it.start - EDGE_PAD)
        return (prev.end + it.start) / 2

    def _right(self, j: int) -> float:
        it = self.items[j]
        last = j == len(self.items) - 1
        if it.kind == "pause":
            return it.end - (PAUSE_KEEP if not last else 0)
        if last:
            return self.duration
        nxt = self.items[j + 1]
        if nxt.kind == "pause":
            return min(nxt.end, it.end + EDGE_PAD)
        return (it.end + nxt.start) / 2

    def kept(self, statuses=("accepted",)) -> list[tuple[float, float]]:
        out, t = [], 0.0
        for lo, hi in self.removed(statuses):
            if lo > t:
                out.append((t, lo))
            t = max(t, hi)
        if t < self.duration:
            out.append((t, self.duration))
        return out

    def kept_duration(self, with_suggestions: bool = False) -> float:
        statuses = ("accepted", "suggested") if with_suggestions else ("accepted",)
        return sum(b - a for a, b in self.kept(statuses))

    # ---------- edits ----------

    def add_cut(self, first: str, last: str, status="accepted", by="user", reason="") -> Cut:
        idx = self.index()
        if first not in idx or last not in idx:
            raise KeyError(f"unknown item id: {first if first not in idx else last}")
        if idx[first] > idx[last]:
            first, last = last, first
        if status == "suggested" and all(it.kind != "word" for it in self.items[idx[first] : idx[last] + 1]):
            raise ValueError("suggest ranges that include words: fillers, pauses and stray sounds "
                             "are handled by the person in the editor")
        cut = Cut(f"c{uuid.uuid4().hex[:8]}", first, last, status, by, reason)
        self.cuts.append(cut)
        return cut

    def find_cut(self, cut_id: str) -> Cut:
        for c in self.cuts:
            if c.id == cut_id:
                return c
        raise KeyError(f"unknown cut id: {cut_id}")

    def nudge(self, cut_id: str, edge: str, delta: float) -> list[float]:
        """Move one edge of a cut by `delta` seconds (negative = earlier). Returns the new offsets."""
        c = self.find_cut(cut_id)
        k = 0 if edge == "start" else 1
        c.nudge = list(c.nudge)
        c.nudge[k] = round(max(-0.5, min(0.5, c.nudge[k] + delta)), 3)
        return c.nudge

    def correct(self, first: str, last: str, text: str) -> dict[str, str]:
        """Fix what the transcript says without touching the media. Returns the old texts by id.

        Words map one to one when the counts match; otherwise the first item takes the whole
        text and the rest go empty (their time still belongs to the sentence).
        """
        idx = self.index()
        a, b = sorted((idx[first], idx[last]))
        targets = [it for it in self.items[a : b + 1] if it.kind not in ("pause", "sound")]
        if not targets:
            raise ValueError("nothing to correct: the range holds no words")
        new = text.split()
        old = {it.id: it.text for it in targets}
        if len(new) == len(targets):
            parts = new
        else:
            parts = [" ".join(new)] + [""] * (len(targets) - 1)
        for it, t in zip(targets, parts):
            it.text = t
            it.kind = "filler" if is_filler(t) else "word"
        return old

    def restore(self, cut_id: str) -> None:
        self.cuts = [c for c in self.cuts if c.id != cut_id]

    def restore_items(self, first: str, last: str) -> int:
        """Drop every cut that overlaps the given item range. Returns how many were dropped."""
        idx = self.index()
        a, b = sorted((idx[first], idx[last]))
        keep, dropped = [], 0
        for c in self.cuts:
            ca, cb = sorted((idx.get(c.first, -1), idx.get(c.last, -1)))
            if ca <= b and a <= cb:
                dropped += 1
            else:
                keep.append(c)
        self.cuts = keep
        return dropped

    def set_status(self, cut_ids: list[str] | None, status: str) -> int:
        """Accept (status='accepted') or reject (status='rejected', removes) suggestions."""
        n = 0
        for c in list(self.cuts):
            if c.status != "suggested" or (cut_ids is not None and c.id not in cut_ids):
                continue
            n += 1
            if status == "rejected":
                self.cuts.remove(c)
            else:
                c.status = status
        return n

    def _uncovered(self, kind: str) -> list[Item]:
        covered = set()
        for a, b, _ in self.cut_runs(("accepted", "suggested")):
            covered.update(range(a, b + 1))
        return [it for i, it in enumerate(self.items) if it.kind == kind and i not in covered]

    def trim_fillers(self) -> list[Cut]:
        """Remove every filler word not already covered by a cut, right away.

        Applied, not suggested: ⌫ on a removed part or undo brings it back.
        """
        return [self.add_cut(it.id, it.id, "accepted", "fillers", f'filler "{it.text.strip()}"')
                for it in self._uncovered("filler")]

    def tighten_pauses(self, longer_than: float = 1.0) -> list[Cut]:
        """Shorten every pause over `longer_than` seconds right away (a little silence is kept).

        Applied, not suggested: undo or restore brings a pause back. Pauses are deliberately never
        offered for review alongside filler suggestions.
        """
        covered = set()
        for a, b, _ in self.cut_runs(("accepted", "suggested")):
            covered.update(range(a, b + 1))
        made = []
        for i, it in enumerate(self.items):
            dur = it.end - it.start
            if it.kind == "pause" and dur > longer_than and i not in covered:
                made.append(self.add_cut(it.id, it.id, "accepted", "pauses", f"{dur:.1f}s pause tightened"))
        return made


_ENC = json.JSONEncoder(ensure_ascii=False, separators=(",", ":"))  # reused: building one per call is the slow part


def dumps(d: dict) -> str:
    """Compact JSON with one item / cut per line: fast for long recordings, readable in a git diff."""
    out = []
    for k, v in d.items():
        if isinstance(v, list) and v and isinstance(v[0], dict):
            # one encoder call for the whole list, then a line break between records. Every record
            # starts with "id", and a quote inside a string is always escaped, so the split is exact.
            body = _ENC.encode(v)[1:-1].replace('},{"id":', '},\n  {"id":')
            out.append(f"{_ENC.encode(k)}: [\n  {body}\n]")
        else:
            out.append(f"{_ENC.encode(k)}: {_ENC.encode(v)}")
    return "{\n" + ",\n".join(out) + "\n}\n"


def _merge(spans: list[list[float]]) -> list[list[float]]:
    out: list[list[float]] = []
    for lo, hi in sorted(spans):
        if out and lo <= out[-1][1] + 1e-6:
            out[-1][1] = max(out[-1][1], hi)
        else:
            out.append([lo, hi])
    return out


def project_path_for(media: Path) -> Path:
    media = Path(media)
    return media.with_name(media.name + ".trimscript.json")


@contextlib.contextmanager
def editing(path: Path):
    """Load, let the caller edit, save. A file lock keeps the editor and the CLI from racing."""
    path = Path(path)
    lock = path.with_name(path.name + ".lock")
    with open(lock, "w") as lf:
        _lock(lf, True)
        try:
            proj = Project.load(path)
            yield proj
            proj.save(path)
        finally:
            _lock(lf, False)


def _lock(f, on: bool) -> None:
    if sys.platform == "win32":
        import msvcrt

        f.seek(0)
        msvcrt.locking(f.fileno(), msvcrt.LK_LOCK if on else msvcrt.LK_UNLCK, 1)
    else:
        import fcntl

        fcntl.flock(f, fcntl.LOCK_EX if on else fcntl.LOCK_UN)
