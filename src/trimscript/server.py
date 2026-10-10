"""Local editor server. Serves the web UI, the media proxy, and edits to the project file.

The project file stays the source of truth: the CLI or an agent can edit it while the editor is
open, and /api/events tells the browser to reload.
"""
from __future__ import annotations

import asyncio
import json
import threading
import time
from dataclasses import asdict
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from trimscript import media, render
from trimscript.project import Cut, Project, dumps, editing, is_filler

STATIC = Path(__file__).parent / "static"


class Op(BaseModel):
    op: str  # cut | restore | restore_items | accept | reject | fillers | pauses | nudge | correct | undo | redo | enhance
    first: str | None = None
    last: str | None = None
    cut_id: str | None = None
    cut_ids: list[str] | None = None
    status: str = "accepted"
    by: str = "user"
    reason: str = ""
    on: bool = True
    edge: str = "start"
    delta: float = 0.0
    text: str = ""


class ExportReq(BaseModel):
    format: str = "mp4"


def create_app(project_path: Path, source: Path, proxy: Path | None = None) -> FastAPI:
    """`proxy` may be None: the editor opens right away and the preview is prepared in the background."""
    app = FastAPI(title="trimscript")
    preview: dict = {"status": "ready", "path": proxy} if proxy else {"status": "running"}

    if proxy is None:

        def make_preview():
            try:
                preview.update(path=media.proxy(source), status="ready")
            except Exception as e:
                preview.update(status="error", error=str(e))

        threading.Thread(target=make_preview, daemon=True).start()
    # Each entry is (before, after) for one editor op: cuts keyed by id plus the texts of corrected
    # items. Undo reverts only that op's difference, so edits made meanwhile by the CLI or an
    # agent survive.
    history: list[tuple[dict, dict]] = []
    future: list[tuple[dict, dict]] = []
    export_state: dict = {"status": "idle"}
    enhance_state: dict = {"status": "idle"}

    def build_enhanced() -> None:
        if enhance_state.get("status") in ("running", "ready"):
            return
        enhance_state.update(status="running")

        def run():
            try:
                from trimscript.enhance import enhanced_proxy

                while preview["status"] == "running":
                    time.sleep(0.5)
                enhanced_proxy(source, preview["path"])
                enhance_state.update(status="ready")
            except Exception as e:
                enhance_state.update(status="error", error=str(e))

        threading.Thread(target=run, daemon=True).start()

    def state_of(p: Project, text_ids=()) -> dict:
        items = {it.id: it for it in p.items}
        return {"cuts": {c.id: asdict(c) for c in p.cuts}, "texts": {i: items[i].text for i in text_ids}}

    def apply_diff(src: dict, dst: dict) -> None:
        """Move the project from state `src` towards `dst`, touching only what differs."""
        with editing(project_path) as p:
            cur = {c.id: c for c in p.cuts}
            for cid in src["cuts"].keys() - dst["cuts"].keys():
                cur.pop(cid, None)
            for cid, d in dst["cuts"].items():
                if src["cuts"].get(cid) != d:
                    cur[cid] = Cut(**d)
            order = list(dst["cuts"]) + [cid for cid in cur if cid not in dst["cuts"]]
            p.cuts = [cur[cid] for cid in order if cid in cur]
            if dst["texts"]:
                ids = set(dst["texts"])
                for it in p.items:
                    if it.id in ids:
                        it.text = dst["texts"][it.id]
                        it.kind = "filler" if is_filler(it.text) else "word"

    def project_json(p: Project | None = None) -> Response:
        # serialized by hand: FastAPI's generic encoder is slow on a 2-hour transcript
        p = p or Project.load(project_path)
        d = p.to_dict()
        d["name"] = source.name
        d["can_undo"], d["can_redo"] = bool(history), bool(future)
        if p.settings.get("enhance"):
            build_enhanced()
        d["enhance_state"] = enhance_state
        d["preview_state"] = {k: v for k, v in preview.items() if k != "path"}
        d["mtime"] = str(project_path.stat().st_mtime_ns)
        return Response(dumps(d), media_type="application/json")

    @app.get("/api/project")
    def get_project():
        return project_json()

    @app.post("/api/ops")
    def apply_op(op: Op):
        if op.op == "undo":
            if not history:
                raise HTTPException(409, "nothing to undo")
            before, after = history.pop()
            apply_diff(after, before)
            future.append((before, after))
            return project_json()
        if op.op == "redo":
            if not future:
                raise HTTPException(409, "nothing to redo")
            before, after = future.pop()
            apply_diff(before, after)
            history.append((before, after))
            return project_json()

        before = state_of(Project.load(project_path))
        result: dict = {"ok": True}
        corrected: list[str] = []
        try:
            with editing(project_path) as p:
                if op.op == "cut":
                    result["cut"] = p.add_cut(op.first, op.last, op.status, op.by, op.reason).id
                elif op.op == "restore":
                    p.restore(op.cut_id)
                elif op.op == "restore_items":
                    result["dropped"] = p.restore_items(op.first, op.last)
                elif op.op in ("accept", "reject"):
                    result["changed"] = p.set_status(op.cut_ids, "accepted" if op.op == "accept" else "rejected")
                elif op.op == "fillers":
                    result["changed"] = len(p.trim_fillers())
                elif op.op == "pauses":
                    result["changed"] = len(p.tighten_pauses())
                elif op.op == "correct":
                    old = p.correct(op.first, op.last, op.text)
                    corrected = list(old)
                    before["texts"] = old
                elif op.op == "nudge":
                    result["nudge"] = p.nudge(op.cut_id, op.edge, op.delta)
                elif op.op == "enhance":
                    p.settings["enhance"] = op.on
                else:
                    raise HTTPException(400, f"unknown op {op.op}")
        except (KeyError, ValueError) as e:
            raise HTTPException(400, str(e).strip("'\"")) from e
        if op.op == "enhance":
            if op.on:
                build_enhanced()
        else:  # settings stay out of undo
            history.append((before, state_of(p, corrected)))
            future.clear()
        resp = project_json(p)
        resp.headers["X-TrimScript-Result"] = json.dumps(result)
        return resp

    @app.get("/api/events")
    async def events():
        async def stream():
            last = None
            while True:
                try:
                    m = project_path.stat().st_mtime_ns
                except FileNotFoundError:
                    m = None
                if m != last:
                    last = m
                    yield f"data: {m}\n\n"  # the browser skips mtimes it already has
                await asyncio.sleep(0.4)

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/media/proxy")
    def get_proxy(enhanced: int = 0):
        if preview["status"] != "ready":
            raise HTTPException(409, "the preview is still being prepared")
        if enhanced:
            from trimscript.enhance import enhanced_proxy

            if enhance_state.get("status") != "ready":
                raise HTTPException(409, "enhanced audio is still being prepared")
            return FileResponse(enhanced_proxy(source, preview["path"]))
        return FileResponse(preview["path"])

    @app.post("/api/export")
    def start_export(req: ExportReq):
        if export_state.get("status") == "running":
            raise HTTPException(409, "an export is already running")
        out = _next_free(source.with_name(f"{source.stem}.trimscript.{req.format}"))

        def run():
            try:
                render.export(Project.load(project_path), source, out)
                export_state.update(status="done", path=str(out))
            except Exception as e:  # surfaced to the editor
                export_state.update(status="error", error=str(e))

        export_state.clear()
        export_state.update(status="running", path=str(out))
        threading.Thread(target=run, daemon=True).start()
        return export_state

    @app.get("/api/export")
    def export_status():
        return export_state

    if STATIC.exists():
        app.mount("/", _Static(directory=STATIC, html=True), name="static")
    return app


class _Static(StaticFiles):
    """index.html must never be cached, or an upgraded trimscript keeps showing the old editor.
    Built assets carry a content hash in their name, so they can be cached forever."""

    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if path.startswith("assets/"):
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        else:
            resp.headers["Cache-Control"] = "no-cache"
        return resp


def _next_free(path: Path) -> Path:
    if not path.exists():
        return path
    n = 2
    while True:
        cand = path.with_name(f"{path.stem}-{n}{path.suffix}")
        if not cand.exists():
            return cand
        n += 1
