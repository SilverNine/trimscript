import pytest

from trimscript import render
from trimscript.project import Project

WORDS = [
    (0.50, 0.80, "Hello"),
    (0.85, 1.20, "there."),
    (1.30, 1.60, "Um,"),
    (1.70, 2.00, "this"),
    (2.05, 2.30, "is"),
    (2.35, 2.80, "trimscript."),
    # 1.2 s gap -> pause item
    (4.00, 4.40, "Bye."),
]


def make() -> Project:
    return Project.from_words("clip.mp4", 5.5, WORDS)


def ids(p: Project) -> list[str]:
    return [f"{it.kind[0]}:{it.text}" for it in p.items]


def test_items_include_pauses_and_fillers():
    p = make()
    assert ids(p) == ["w:Hello", "w:there.", "f:Um,", "w:this", "w:is", "w:trimscript.", "p:", "w:Bye.", "p:"]
    assert p.items[0].start == 0.5  # leading 0.5 s is below PAUSE_MIN, no pause item


def test_cut_one_word_uses_gap_midpoints():
    p = make()
    p.add_cut("w2", "w2")
    assert p.removed() == [[1.25, 1.65]]
    assert p.kept_duration() == pytest.approx(5.5 - 0.4)


def test_cut_first_word_starts_at_zero():
    p = make()
    p.add_cut("w0", "w0")
    assert p.removed() == [[0.0, 0.825]]


def test_pause_keeps_a_little_silence():
    p = make()
    pause = next(it for it in p.items if it.kind == "pause")
    p.add_cut(pause.id, pause.id)
    lo, hi = p.removed()[0]
    assert lo == pytest.approx(2.8 + 0.12)
    assert hi == pytest.approx(4.0 - 0.12)


def test_word_next_to_pause_keeps_edge_pad():
    p = make()
    p.add_cut("w5", "w5")  # "trimscript." is followed by a pause
    lo, hi = p.removed()[0]
    assert hi == pytest.approx(2.8 + 0.08)


def test_fillers_are_removed_right_away():
    p = make()
    made = p.trim_fillers()
    assert [(c.first, c.status, c.by) for c in made] == [("w2", "accepted", "fillers")]
    assert p.removed() == [[1.25, 1.65]]
    assert p.trim_fillers() == []  # already covered


def test_suggestions_do_not_change_media_until_accepted():
    p = make()
    c = p.add_cut("w3", "w4", "suggested", "agent", "filler phrase")
    assert p.removed() == []
    assert p.set_status([c.id], "accepted") == 1
    assert p.removed() != []


def test_reject_removes_suggestion():
    p = make()
    p.add_cut("w3", "w4", "suggested", "agent", "x")
    p.set_status(None, "rejected")
    assert p.cuts == []


def test_restore_items_drops_overlapping_cuts():
    p = make()
    p.add_cut("w0", "w1")
    p.add_cut("w4", "w4")
    assert p.restore_items("w1", "w1") == 1
    assert len(p.cuts) == 1


def test_adjacent_cuts_merge():
    p = make()
    p.add_cut("w0", "w0")
    p.add_cut("w1", "w1")
    assert p.removed() == [[0.0, 1.25]]


def test_roundtrip(tmp_path):
    p = make()
    p.add_cut("w3", "w4", "suggested", "agent", "tighten")
    path = tmp_path / "clip.mp4.trimscript.json"
    p.save(path)
    q = Project.load(path)
    assert q.cuts[0].reason == "tighten" and q.rev == 1


def test_captions_follow_edited_timeline():
    p = make()
    p.add_cut("w0", "w1")  # remove "Hello there." (0 .. 1.25)
    caps = render.captions(p)
    assert caps[0][2] == "Um, this is trimscript."
    assert caps[0][0] == pytest.approx(1.30 - 1.25)


def test_snapped_kept_is_on_frame_grid():
    p = make()
    p.add_cut("w2", "w2")
    for a, b in render.snapped_kept(p, 30):
        assert round(a * 30, 6).is_integer() and round(b * 30, 6).is_integer()


def test_nudge_moves_one_edge_and_is_clamped():
    p = make()
    c = p.add_cut("w2", "w2")  # removed [1.25, 1.65]
    p.nudge(c.id, "start", 0.05)
    p.nudge(c.id, "end", -0.02)
    assert p.removed() == [[1.3, 1.63]]
    for _ in range(100):
        p.nudge(c.id, "end", 0.01)
    assert c.nudge[1] == 0.5


def test_dumps_one_record_per_line_and_roundtrips():
    import json

    from trimscript.project import dumps

    p = make()
    p.items[0].text = 'He said "},{"id": x'  # hostile text must not break the layout
    p.add_cut("w0", "w1")
    s = dumps(p.to_dict())
    assert json.loads(s)["items"][0]["text"] == 'He said "},{"id": x'
    assert s.count("\n  {") == len(p.items) + len(p.cuts)  # one line per record, no extra splits


def test_correct_maps_words_and_keeps_timing():
    p = make()
    before = p.removed()
    old = p.correct("w3", "w5", "this is TrimScript.")
    assert old == {"w3": "this", "w4": "is", "w5": "trimscript."}
    assert [p.items[i].text for i in (3, 4, 5)] == ["this", "is", "TrimScript."]
    assert p.removed() == before


def test_correct_with_fewer_words_fills_the_first_item():
    p = make()
    p.correct("w0", "w1", "Hi.")
    assert (p.items[0].text, p.items[1].text) == ("Hi.", "")
    p.correct("w2", "w2", "So,")
    assert p.items[2].kind == "word"  # no longer a filler


def test_sound_items_are_removed_by_hand_and_never_captioned():
    p = Project.from_words("clip.mp4", 5.5, WORDS, sounds=[(1.20, 1.30)])
    assert ids(p)[:4] == ["w:Hello", "w:there.", "s:", "f:Um,"]
    assert [c.first for c in p.trim_fillers()] == ["w3"]  # sounds are not fillers
    with pytest.raises(ValueError):
        p.add_cut("s2", "s2", "suggested", "agent", "a sound")
    q = Project.from_words("clip.mp4", 5.5, WORDS, sounds=[(1.20, 1.30)])
    q.add_cut("s2", "s2")  # the person removes it
    assert q.removed() == [[1.2, 1.3]]  # the whole gap, word edges untouched
    assert all(t for _, _, t in render.captions(p))
    p.correct("w1", "w3", "there, um")  # the sound takes no text
    assert [it.text for it in p.items[1:4]] == ["there,", "", "um"]


def test_dtw_tokens_become_words():
    from trimscript.transcribe import _dtw_words

    toks = [{"text": "[_BEG_]", "t_dtw": -1}, {"text": " Hey", "t_dtw": 100}, {"text": ",", "t_dtw": 118},
            {"text": " um", "t_dtw": 148}, {"text": ",", "t_dtw": 164}, {"text": " welcome", "t_dtw": 178}]
    # a word runs to the next one (at most 0.6 s); tighten() later pulls the end back to the voice
    assert _dtw_words([{"tokens": toks}]) == [(0.86, 1.34, "Hey,"), (1.34, 1.64, "um,"), (1.64, 1.94, "welcome")]


def test_export_never_overwrites_the_source(tmp_path):
    src = tmp_path / "talk.mp4"
    src.write_bytes(b"original")
    proj = Project.from_words("talk.mp4", 1.0, [(0.0, 0.5, "hello")])
    with pytest.raises(ValueError, match="overwrite the source"):
        render.export(proj, src, tmp_path / "." / "talk.mp4")
    assert src.read_bytes() == b"original"


def test_pauses_are_tightened_not_suggested():
    p = make()
    made = p.tighten_pauses()
    assert [(c.first, c.status) for c in made] == [("p6", "accepted"), ("p8", "accepted")]
    assert p.tighten_pauses() == []  # already covered


def test_a_suggestion_without_words_is_refused():
    p = make()
    for first, last in (("p6", "p6"), ("w2", "w2")):  # a pause, a filler
        with pytest.raises(ValueError):
            p.add_cut(first, last, "suggested", "agent", "x")
    p.add_cut("w5", "p6", "suggested", "agent", "a word and its pause")  # with words it is fine
