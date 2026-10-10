# Demo video

The ~50 s demo: delete a sentence, trim fillers and listen across the edits, then ask Claude Code
(through the TrimScript MCP server) to suggest removing a side note and the sign-off, and review
its suggestions. Everything on screen is
real: the editor runs on the synthetic demo talk, the agent is a live Claude Code session.

- `record.mjs` drives the editor in headless Chrome and saves screencast frames with wall-clock
  times. Headless Chrome draws no cursor, so the script injects one, plus keycaps for key presses.
  Mid-way it starts `agent.tape` in VHS, which types the request into Claude Code.
- `cards.mjs` renders the captions, title and end card.
- `compose.py` cuts the take into the video. The agent part shows the editor and the terminal side
  by side and is sped up; `TERM_OFFSET` aligns the two recordings (measured per take: the terminal
  frame where the prompt is sent against the editor frame where suggestions appear).

VHS runs Claude Code with a clean environment, so nothing from the calling shell leaks into it,
and `compose.py` crops the top of the terminal, where Claude Code prints the account plan.
The first run in a new folder shows Claude Code's trust prompt; answer it once beforehand.

```sh
./run.sh <folder with home-server-demo.mp4 and its project> <out dir>
```
