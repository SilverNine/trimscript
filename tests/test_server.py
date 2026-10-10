from fastapi.testclient import TestClient

from trimscript.project import Project, editing
from trimscript.server import create_app

WORDS = [(0.5, 0.8, "Hello"), (0.9, 1.2, "um,"), (1.3, 1.6, "world."), (1.7, 2.0, "Bye.")]


def setup(tmp_path):
    path = tmp_path / "clip.mp4.trimscript.json"
    Project.from_words("clip.mp4", 3.0, WORDS).save(path)
    proxy = tmp_path / "proxy.mp4"
    proxy.write_bytes(b"\0" * 10)
    return path, TestClient(create_app(path, tmp_path / "clip.mp4", proxy))


def cut_ids(path):
    return {(c.first, c.status) for c in Project.load(path).cuts}


def test_cut_and_undo_redo(tmp_path):
    path, client = setup(tmp_path)
    assert client.post("/api/ops", json={"op": "cut", "first": "w0", "last": "w0"}).status_code == 200
    assert client.get("/api/project").json()["removed"] == [[0.0, 0.85]]
    client.post("/api/ops", json={"op": "undo"})
    assert cut_ids(path) == set()
    client.post("/api/ops", json={"op": "redo"})
    assert cut_ids(path) == {("w0", "accepted")}


def test_undo_keeps_edits_made_by_an_agent_meanwhile(tmp_path):
    path, client = setup(tmp_path)
    client.post("/api/ops", json={"op": "fillers"})
    with editing(path) as p:  # the CLI / an agent writes in between
        p.add_cut("w3", "w3", "suggested", "agent", "drop the outro")
    client.post("/api/ops", json={"op": "accept", "cut_ids": None})
    client.post("/api/ops", json={"op": "undo"})  # un-accept
    assert cut_ids(path) == {("w1", "accepted"), ("w3", "suggested")}
    client.post("/api/ops", json={"op": "undo"})  # bring the fillers back
    assert cut_ids(path) == {("w3", "suggested")}


def test_unknown_item_is_a_400(tmp_path):
    _, client = setup(tmp_path)
    assert client.post("/api/ops", json={"op": "cut", "first": "nope", "last": "w0"}).status_code == 400


def test_range_requests_on_proxy(tmp_path):
    _, client = setup(tmp_path)
    r = client.get("/media/proxy", headers={"Range": "bytes=0-3"})
    assert r.status_code == 206 and len(r.content) == 4


def test_editor_page_is_not_cached(tmp_path):
    from trimscript.server import STATIC

    if not (STATIC / "index.html").exists():
        return
    _, client = setup(tmp_path)
    assert client.get("/").headers["cache-control"] == "no-cache"


def test_correct_is_undoable(tmp_path):
    path, client = setup(tmp_path)
    r = client.post("/api/ops", json={"op": "correct", "first": "w2", "last": "w2", "text": "World."})
    assert r.status_code == 200 and r.json()["items"][2]["text"] == "World."
    client.post("/api/ops", json={"op": "undo"})
    assert Project.load(path).items[2].text == "world."
    client.post("/api/ops", json={"op": "redo"})
    assert Project.load(path).items[2].text == "World."
