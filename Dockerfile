# syntax=docker/dockerfile:1.6
# Multi-stage build using uv. Final image runs the combined ASGI app
# (auth server + MCP) on $PORT (Cloud Run convention, default 8080).

FROM python:3.12-slim AS builder

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# Install uv (pinned).
COPY --from=ghcr.io/astral-sh/uv:0.8.3 /uv /uvx /usr/local/bin/

WORKDIR /app

# Lock-only dependency layer (cached when only source changes).
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# App source.
COPY auth_server ./auth_server
COPY mcp_server ./mcp_server
COPY tablycja_client ./tablycja_client
COPY server.py ./

# ---- runtime stage --------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PATH="/app/.venv/bin:$PATH" \
    PORT=8080

# Non-root user.
RUN useradd --create-home --shell /usr/sbin/nologin app
WORKDIR /app

COPY --from=builder --chown=app:app /app /app

USER app

EXPOSE 8080

# Cloud Run sets $PORT. Listen on 0.0.0.0:$PORT.
CMD ["sh", "-c", "exec uvicorn server:app --host 0.0.0.0 --port ${PORT:-8080} --proxy-headers --forwarded-allow-ips=*"]
