# Runs the MCP server on stdio, for directories that start it to list its tools.
# For editing your own videos, install with uv instead (see README).
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends ffmpeg \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY . .
RUN pip install --no-cache-dir .

ENTRYPOINT ["trimscript", "mcp"]
