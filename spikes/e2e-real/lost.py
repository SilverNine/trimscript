"""Which kept words went missing in the export, and were they next to a cut?

Usage: python lost.py <source video>   (after run.py produced <stem>.trimscript.mp4)
"""
import difflib
import re
import sys
from pathlib import Path

from trimscript import transcribe
from trimscript.project import Project, project_path_for

src = Path(sys.argv[1])
proj = Project.load(project_path_for(src))
out = src.with_name(src.stem + ".trimscript.mp4")
removed_idx = set()
for a, b, _ in proj.cut_runs():
    removed_idx.update(range(a, b + 1))
spans = proj.removed()
kept = [it for i, it in enumerate(proj.items) if i not in removed_idx and it.kind != "pause" and it.text]
norm = lambda s: re.sub(r"[^a-z0-9']", "", s.lower())
expected = [norm(it.text) for it in kept]
heard_raw, _ = transcribe.transcribe(out, "en", progress=lambda m: None)
heard = [norm(w) for _, _, w in heard_raw]

def near_cut(t, tol=0.35):
    return any(abs(t - lo) < tol or abs(t - hi) < tol for lo, hi in spans)

lost = at_cut = 0
rows = []
for op, i1, i2, j1, j2 in difflib.SequenceMatcher(None, expected, heard, autojunk=False).get_opcodes():
    if op in ("delete", "replace"):
        for k in range(i1, i2):
            it = kept[k]
            c = near_cut(it.start) or near_cut(it.end)
            lost += 1
            at_cut += c
        rows.append(f"{op:7} @{kept[i1].start:7.1f}s cut={'Y' if any(near_cut(kept[k].start) or near_cut(kept[k].end) for k in range(i1, i2)) else 'n'} "
                    f"expected={' '.join(expected[i1:i2])!r} heard={' '.join(heard[j1:j2])!r}")
print(f"lost {lost} of {len(expected)} kept words; {at_cut} sit within 0.35 s of a cut edge ({len(spans)} cuts)")
print("\n".join(rows[:40]))
