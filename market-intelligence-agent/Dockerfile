FROM python:3.12-slim

# Install Node.js + npm (provides npx) for MCP servers that ship as Node packages
# (e.g. @modelcontextprotocol/server-filesystem).
RUN apt-get update \
    && apt-get install -y --no-install-recommends curl ca-certificates gnupg \
    && curl -fsSL https://deb.nodesource.com/setup_20.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

# Pre-pull the filesystem MCP server so the first request doesn't pay an npm install.
RUN npx -y @modelcontextprotocol/server-filesystem --help >/dev/null 2>&1 || true

# Install Chromium for @playwright/mcp. `--with-deps` brings in the shared libraries
# (libnss, libatk, fonts, etc.) that headless Chrome needs on Debian-slim.
RUN npx -y playwright@latest install --with-deps chromium

# Pre-pull the Playwright MCP server so the first request doesn't pay an npm install.
RUN npx -y @playwright/mcp@latest --help >/dev/null 2>&1 || true

EXPOSE 8000 8080

CMD ["uv", "run", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
