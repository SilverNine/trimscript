# Contributing

Thanks for taking a look. Bug reports with a short recording that shows the problem are the most
useful thing you can send.

## Set up

```sh
uv sync                      # Python 3.11+, installs the dev tools too
uv run pytest -q             # needs ffmpeg on PATH for the media tests
uv run trimscript open some-video.mp4
```

The editor UI lives in `web/` (React, Tailwind, shadcn/ui). The built files are committed in
`src/trimscript/static/`, so Python users never need Node.

```sh
cd web
pnpm install
pnpm dev                     # Vite on :5173, proxying to `trimscript open` on :4747
pnpm build                   # writes src/trimscript/static/ and the third-party license file
```

Commit the rebuilt `static/` together with your `web/` change; CI checks that they match.

## What fits

TrimScript is a small, local editor for spoken-word recordings. Good changes keep it that way:
fewer steps, clearer feedback while listening, better word timing, more robust exports.

Some things are deliberately out of scope, so please open an issue before working on them:

- reordering, copying or pasting parts of the transcript
- speaker labels and speaker-based layouts
- cloud transcription or any upload of the media
- automatic removal of breaths or other sounds by classification
- built-in language model calls (agents connect from outside through MCP)
- writing to the source file; every export is a new file

## Pull requests

- One topic per pull request, with a test when the change is in `src/`.
- `uv run pytest -q` and `pnpm build` in `web/` pass locally.
- Describe how you checked it by ear if it changes cuts, timing or audio.
