"""MCP server: lets a coding agent read the transcript and propose edits.

Edits arrive in the open editor as suggestions with a reason; the person accepts or rejects them.
Run with `trimscript mcp` (stdio). Register in Claude Code with:
    claude mcp add trimscript -- uvx trimscript mcp
"""
from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from trimscript import render
from trimscript.cli import ensure_project, resolve, show
from trimscript.project import Project, editing

INSTRUCTIONS = """\
trimscript edits video by editing its transcript. Every tool takes `media`, the path to the video or
audio file. Start with get_transcript. Item ids look like w12 (word) or p13 (pause); a removal spans
FIRST..LAST inclusive. Your removals are suggestions with a reason: the person reviews them in the
editor. Only pass apply=true when the person explicitly asked you to remove without review.
Suggest removals that include words. Fillers, pauses and stray sounds are not yours to suggest:
the person handles them with one button each in the editor.
In get_transcript output, ~~x~~ is already removed and [-x-] is a pending suggestion."""

mcp = MCPServer(name="trimscript", instructions=INSTRUCTIONS)


def _project(media: str) -> tuple[Path, Path]:
    ppath, src = resolve(media)
    if not ppath.exists():
        raise ToolError(f"no transcript yet for {media}; call transcribe first")
    return ppath, src


@contextlib.contextmanager
def _agent_errors():
    """Bad ids and the like go back to the agent as readable errors it can fix."""
    try:
        yield
    except (KeyError, ValueError) as e:
        raise ToolError(str(e).strip("'\"")) from e


@mcp.tool()
def transcribe(media: str, language: str = "en") -> str:
    """Transcribe a media file locally (minutes for long files). Safe to call again: reuses an existing transcript.
    language is the spoken language code, such as en or de; there is no automatic detection."""
    with contextlib.redirect_stdout(sys.stderr):  # stdout belongs to the MCP protocol
        ppath, _ = ensure_project(media, language)
    p = Project.load(ppath)
    return f"{len([i for i in p.items if i.kind in ('word', 'filler')])} words, {p.duration:.1f}s. Call get_transcript next."


@mcp.tool()
def get_transcript(media: str, with_ids: bool = True) -> str:
    """The transcript, one sentence per line, prefixed by its item id range and start time.

    with_ids=true prefixes every item with its id so you can remove part of a sentence.
    """
    ppath, _ = _project(media)
    return show(Project.load(ppath), with_ids)


@mcp.tool()
def suggest_removal(media: str, first: str, last: str, reason: str, apply: bool = False) -> str:
    """Propose removing items FIRST..LAST (inclusive). Give a short reason the person will see."""
    ppath, _ = _project(media)
    with _agent_errors(), editing(ppath) as p:
        cut = p.add_cut(first, last, "accepted" if apply else "suggested", "agent", reason)
        now, then = p.kept_duration(), p.kept_duration(with_suggestions=True)
    return f"{'removed' if apply else 'suggested'} {cut.id}; edit runs {now:.1f}s now, {then:.1f}s if every suggestion is accepted"


@mcp.tool()
def correct_text(media: str, first: str, last: str, text: str) -> str:
    """Fix misheard words in items FIRST..LAST (e.g. a product name). Changes captions, not the media.

    Use it when you are confident: names, jargon, obvious mishearings.
    """
    ppath, _ = _project(media)
    with _agent_errors(), editing(ppath) as p:
        old = p.correct(first, last, text)
    return f"corrected {' '.join(old.values())!r} -> {text!r}"


@mcp.tool()
def list_edits(media: str) -> str:
    """Every removal and suggestion with its id, status, author and reason."""
    ppath, _ = _project(media)
    p = Project.load(ppath)
    if not p.cuts:
        return "no edits"
    rows = [f"{c.id} {c.status:9} {c.first}..{c.last} by {c.by}: {c.reason}" for c in p.cuts]
    return "\n".join(rows + [
        f"edited length {p.kept_duration():.1f}s of {p.duration:.1f}s; "
        f"{p.kept_duration(with_suggestions=True):.1f}s if every suggestion is accepted"
    ])


@mcp.tool()
def withdraw(media: str, cut_id: str) -> str:
    """Take back one of your suggestions (or a removal) by id."""
    ppath, _ = _project(media)
    with editing(ppath) as p:
        if all(c.id != cut_id for c in p.cuts):
            raise ToolError(f"no edit {cut_id}; see list_edits")
        p.restore(cut_id)
    return f"withdrew {cut_id}"


@mcp.tool()
def enhance_voice(media: str, on: bool = True) -> str:
    """Turn voice enhancement (noise, level, loudness to -14 LUFS) on or off for previews and exports."""
    ppath, _ = _project(media)
    with editing(ppath) as p:
        p.settings["enhance"] = on
    return f"voice enhancement {'on' if on else 'off'}"


@mcp.tool()
def export(media: str, format: str = "mp4") -> str:
    """Render the accepted edit next to the source: mp4, wav, srt, vtt or fcpxml. Suggestions are not applied."""
    ppath, src = _project(media)
    out = src.with_name(f"{src.stem}.trimscript.{format}")
    with contextlib.redirect_stdout(sys.stderr):
        render.export(Project.load(ppath), src, out)
    return str(out)


def main() -> None:
    mcp.run("stdio")
