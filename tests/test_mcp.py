import asyncio

import pytest
from mcp.server.mcpserver.exceptions import ToolError

from trimscript import mcp_server
from trimscript.project import Project

WORDS = [(0.5, 0.8, "Hello"), (0.9, 1.2, "um,"), (1.3, 1.6, "world."), (3.0, 3.4, "Bye.")]


def call(name, **args):
    out = asyncio.run(mcp_server.mcp.call_tool(name, args))
    return "\n".join(b.text for b in out.content)


def test_agent_flow(tmp_path):
    media = tmp_path / "clip.mp4"
    media.write_bytes(b"")
    path = tmp_path / "clip.mp4.trimscript.json"
    Project.from_words("clip.mp4", 4.0, WORDS).save(path)

    text = call("get_transcript", media=str(media))
    assert "w0:Hello" in text and "w1:um," in text

    bye = next(i.id for i in Project.load(path).items if i.text == "Bye.")
    out = call("suggest_removal", media=str(media), first=bye, last=bye, reason="drop the outro")
    assert out.startswith("suggested")
    um = next(i.id for i in Project.load(path).items if i.text == "um,")
    with pytest.raises(ToolError, match="include words"):
        call("suggest_removal", media=str(media), first=um, last=um, reason="filler")

    p = Project.load(path)
    assert {c.status for c in p.cuts} == {"suggested"} and p.removed() == []
    listing = call("list_edits", media=str(media))
    assert "drop the outro" in listing

    cid = next(c.id for c in p.cuts if c.by == "agent")
    call("withdraw", media=str(media), cut_id=cid)
    assert all(c.by != "agent" for c in Project.load(path).cuts)


def test_tools_are_listed():
    names = {t.name for t in asyncio.run(mcp_server.mcp.list_tools())}
    assert {"transcribe", "get_transcript", "suggest_removal", "export"} <= names


def test_bad_id_is_a_readable_error(tmp_path):
    import pytest
    from mcp.server.mcpserver.exceptions import ToolError

    media = tmp_path / "clip.mp4"
    media.write_bytes(b"")
    Project.from_words("clip.mp4", 4.0, WORDS).save(tmp_path / "clip.mp4.trimscript.json")
    with pytest.raises(ToolError, match="unknown item id: w99"):
        call("suggest_removal", media=str(media), first="w99", last="w99", reason="x")
