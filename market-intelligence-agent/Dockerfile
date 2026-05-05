FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:0.6.14 /uv /usr/local/bin/uv

WORKDIR /app

COPY . .

RUN uv sync --frozen --no-dev

EXPOSE 8000 8080

CMD ["uv", "run", "uvicorn", "app.api.server:app", "--host", "0.0.0.0", "--port", "8000"]
