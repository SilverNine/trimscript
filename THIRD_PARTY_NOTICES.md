# Third-party notices

TrimScript is MIT licensed (see [LICENSE](LICENSE)). It includes or uses the following.

## Bundled in the package

The editor in `src/trimscript/static/` is a build of `web/` and bundles React, Radix UI, floating-ui,
shadcn/ui components, Tailwind CSS, Lucide icons (ISC, some derived from Feather, MIT), Sonner,
class-variance-authority (Apache-2.0), clsx, tailwind-merge and their dependencies. The full list
with every license text is generated at build time into
[`src/trimscript/static/THIRD_PARTY_LICENSES.txt`](src/trimscript/static/THIRD_PARTY_LICENSES.txt),
which ships inside the Python package.

## Installed separately

Python dependencies (FastAPI, Uvicorn, NumPy, SciPy, noisereduce, the MCP SDK, pywhispercpp and,
optionally, parakeet-mlx) are installed by your package manager under their own licenses; TrimScript
does not redistribute them.

FFmpeg is called as a separate program that you install yourself. TrimScript does not include or
distribute FFmpeg.

## Downloaded at first use

- Whisper small.en in ggml format, from the whisper.cpp model repository. Whisper weights by
  OpenAI, MIT.
- With `trimscript[parakeet]` and `--engine parakeet`: Parakeet TDT 0.6B v2 by NVIDIA, CC BY 4.0, in the
  MLX conversion by mlx-community (huggingface.co/mlx-community/parakeet-tdt-0.6b-v2).

Model files are downloaded from their publishers' repositories to your machine; TrimScript does not
redistribute them.

Licenses cover copyright only as far as they say. The MIT license on the Whisper weights contains no
express patent grant, and CC BY 4.0 on Parakeet expressly does not license patent rights. Neither the
model publishers nor TrimScript grant any patent license for the models.
