"""trimscript command line. Every edit command writes the project file the editor is watching.

Agent edits are suggestions by default; pass --apply to remove right away.
"""
from __future__ import annotations

import argparse
import json
import sys
import webbrowser
from pathlib import Path

from trimscript import __version__, media, render, transcribe
from trimscript.project import Project, editing, project_path_for


def resolve(target: str) -> tuple[Path, Path]:
    """Accept either the media file or its .trimscript.json; return (project path, media path)."""
    t = Path(target).expanduser().resolve()
    if t.name.endswith(".trimscript.json"):
        proj = Project.load(t)
        return t, (t.parent / proj.source).resolve()
    return project_path_for(t), t


def ensure_project(target: str, language: str = "en", engine: str | None = None, force: bool = False) -> tuple[Path, Path]:
    ppath, src = resolve(target)
    if ppath.exists() and not force:
        return ppath, src
    if not src.exists():
        sys.exit(f"trimscript: no such file: {src}")
    info = media.probe(src)
    if not info.has_audio:
        sys.exit("trimscript: this file has no audio track")
    words, engine_name = transcribe.transcribe(src, language, engine, progress=lambda m: print(f"trimscript: {m}", file=sys.stderr))
    proj = Project.from_words(src.name, info.duration, words, transcribe.sounds(words, src),
                              has_video=info.has_video, language=language, engine=engine_name)
    proj.save(ppath)
    print(f"trimscript: {len(words)} words -> {ppath.name}", file=sys.stderr)
    return ppath, src


def fmt_time(t: float) -> str:
    m, s = divmod(t, 60)
    return f"{int(m)}:{s:04.1f}"


def show(proj: Project, words: bool) -> str:
    """A transcript an agent can read and point at. Removed items are wrapped in ~~ ~~ (accepted) or [- -] (suggested)."""
    state = {}
    for a, b, c in proj.cut_runs(("accepted", "suggested")):
        for i in range(a, b + 1):
            state.setdefault(i, c)
    lines, cur, first = [], [], None
    for i, it in enumerate(proj.items):
        c = state.get(i)
        text = {"pause": f"<{it.end - it.start:.1f}s>", "sound": "<?>"}.get(it.kind, it.text)
        if words:
            text = f"{it.id}:{text}"
        if c is not None:
            text = f"~~{text}~~" if c.status == "accepted" else f"[-{text}-]"
        if first is None:
            first = it
        cur.append(text)
        if it.text.endswith((".", "?", "!")) or (it.kind == "pause" and it.end - it.start > 1.5):
            lines.append(f"{first.id}-{it.id} {fmt_time(first.start)} | {' '.join(cur)}")
            cur, first = [], None
    if cur:
        lines.append(f"{first.id}-{proj.items[-1].id} {fmt_time(first.start)} | {' '.join(cur)}")
    head = f"# {proj.source}  {fmt_time(proj.duration)} -> {fmt_time(proj.kept_duration())}"
    sugg = [c for c in proj.cuts if c.status == "suggested"]
    if sugg:
        head += f"  ({len(sugg)} suggestions pending; {fmt_time(proj.kept_duration(with_suggestions=True))} if all accepted)"
    return "\n".join([head, *lines])


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="trimscript", description="Edit video by editing the transcript.")
    ap.add_argument("--version", action="version", version=f"trimscript {__version__}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    o = sub.add_parser("open", help="transcribe if needed and open the editor")
    o.add_argument("target")
    o.add_argument("--lang", default="en", help="spoken language code, e.g. en or de (default en)")
    o.add_argument("--port", type=int, default=4747)
    o.add_argument("--no-browser", action="store_true")

    t = sub.add_parser("transcribe", help="(re)build the transcript")
    t.add_argument("target")
    t.add_argument("--lang", default="en", help="spoken language code, e.g. en or de (default en)")
    t.add_argument("--engine", choices=["whisper", "parakeet"], help="parakeet: faster on Apple Silicon, but drops most fillers")
    t.add_argument("--force", action="store_true")

    s = sub.add_parser("show", help="print the transcript with item ids")
    s.add_argument("target")
    s.add_argument("--words", action="store_true", help="prefix every item with its id")
    s.add_argument("--json", action="store_true")

    c = sub.add_parser("remove", help="remove items FIRST..LAST (a suggestion unless --apply)")
    c.add_argument("target")
    c.add_argument("first")
    c.add_argument("last", nargs="?")
    c.add_argument("--reason", default="")
    c.add_argument("--apply", action="store_true")

    fl = sub.add_parser("fillers", help="remove every um and uh now (restore or undo brings them back)")
    fl.add_argument("target")
    tp = sub.add_parser("pauses", help="tighten pauses over a second now (restore or undo brings them back)")
    tp.add_argument("target")

    fx = sub.add_parser("fix", help="correct the transcript text of FIRST..LAST (the media is untouched)")
    fx.add_argument("target")
    fx.add_argument("first")
    fx.add_argument("last")
    fx.add_argument("text")

    r = sub.add_parser("restore", help="bring back a removed part by id, or every one touching FIRST..LAST")
    r.add_argument("target")
    r.add_argument("ids", nargs="+")

    for name in ("accept", "reject"):
        a = sub.add_parser(name, help=f"{name} suggestions (all when no ids are given)")
        a.add_argument("target")
        a.add_argument("ids", nargs="*")

    sub.add_parser("mcp", help="run the MCP server on stdio (for coding agents)")

    en = sub.add_parser("enhance", help="turn voice enhancement on (or --off) for previews and exports")
    en.add_argument("target")
    en.add_argument("--off", action="store_true")

    e = sub.add_parser("export", help="write MP4, WAV, SRT, VTT or FCPXML")
    e.add_argument("target")
    e.add_argument("-o", "--out")

    args = ap.parse_args(argv)

    if args.cmd == "open":
        ppath, src = ensure_project(args.target, args.lang)
        serve(ppath, src, args.port, not args.no_browser)
        return
    if args.cmd == "mcp":
        from trimscript.mcp_server import main as mcp_main

        mcp_main()
        return
    if args.cmd == "transcribe":
        ensure_project(args.target, args.lang, args.engine, force=args.force)
        return

    ppath, src = resolve(args.target)
    if not ppath.exists():
        sys.exit(f"trimscript: no project yet, run: trimscript transcribe {args.target}")

    if args.cmd == "show":
        proj = Project.load(ppath)
        print(json.dumps(proj.to_dict(), ensure_ascii=False) if args.json else show(proj, args.words))
    elif args.cmd == "remove":
        with editing(ppath) as p:
            cut = p.add_cut(args.first, args.last or args.first, "accepted" if args.apply else "suggested", "agent", args.reason)
        print(cut.id)
    elif args.cmd == "pauses":
        with editing(ppath) as p:
            made = p.tighten_pauses()
        print(f"{len(made)} pauses tightened")
    elif args.cmd == "fillers":
        with editing(ppath) as p:
            made = p.trim_fillers()
        print(f"{len(made)} fillers removed")
    elif args.cmd == "fix":
        with editing(ppath) as p:
            p.correct(args.first, args.last, args.text)
    elif args.cmd == "restore":
        with editing(ppath) as p:
            if len(args.ids) == 2 and not args.ids[0].startswith("c"):
                p.restore_items(*args.ids)
            else:
                for i in args.ids:
                    p.restore(i)
    elif args.cmd in ("accept", "reject"):
        with editing(ppath) as p:
            n = p.set_status(args.ids or None, "accepted" if args.cmd == "accept" else "rejected")
        print(f"{n} {args.cmd}ed")
    elif args.cmd == "enhance":
        with editing(ppath) as p:
            p.settings["enhance"] = not args.off
        if not args.off:
            from trimscript.enhance import enhanced_audio

            print(enhanced_audio(src, progress=lambda m: print(f"trimscript: {m}", file=sys.stderr)))
    elif args.cmd == "export":
        out = Path(args.out) if args.out else src.with_name(f"{src.stem}.trimscript.mp4")
        render.export(Project.load(ppath), src, out)
        print(out)


def serve(ppath: Path, src: Path, port: int, browser: bool) -> None:
    import uvicorn

    from trimscript.server import create_app

    app = create_app(ppath, src)
    url = f"http://127.0.0.1:{port}/"
    print(f"trimscript: editor at {url}  (Ctrl+C to stop)", file=sys.stderr)
    if browser:
        webbrowser.open(url)
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


if __name__ == "__main__":
    main()
