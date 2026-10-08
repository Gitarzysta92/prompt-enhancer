# syntax=docker/dockerfile:1
FROM node:24.21.0-bookworm-slim AS frontend
WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json frontend/.npmrc ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM ghcr.io/astral-sh/uv:0.11.26 AS uv
FROM caddy:2.11.7 AS gateway
FROM python:3.12-slim-bookworm AS python-build
COPY --from=uv /uv /usr/local/bin/uv
WORKDIR /app
COPY pyproject.toml uv.lock README.md ./
COPY src/ src/
COPY --from=frontend /build/src/prompt_enhancer/_resources/dashboard/ src/prompt_enhancer/_resources/dashboard/
RUN uv sync --frozen --no-dev --no-editable --no-cache

FROM python:3.12-slim-bookworm AS runtime
ARG APP_REVISION=development
ENV PATH="/app/.venv/bin:/usr/local/bin:/usr/bin:/bin" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PROMPT_ENHANCER_REVISION=${APP_REVISION}
LABEL org.opencontainers.image.title="Prompt Enhancer" \
      org.opencontainers.image.revision=${APP_REVISION}
RUN /usr/sbin/groupadd --gid 10001 app && /usr/sbin/useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /data/prompt-enhancer && chown -R app:app /data
COPY --from=python-build /app/.venv /app/.venv
COPY --from=gateway /usr/bin/caddy /usr/local/bin/caddy
# Port 8080 needs no file capability; retaining it prevents cap-drop execution.
RUN python -c "import os; p='/usr/local/bin/caddy'; os.removexattr(p, 'security.capability') if 'security.capability' in os.listxattr(p) else None"
COPY --chmod=0444 deploy/coolify/Caddyfile deploy/coolify/entrypoint.py /app/deploy/
RUN chmod 0755 /app/deploy
WORKDIR /app
USER 10001:10001
# Only the authenticated gateway is reachable on the container network.
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.build_opener(urllib.request.ProxyHandler({})).open('http://127.0.0.1:8080/health', timeout=3).close()"
ENTRYPOINT ["python", "/app/deploy/entrypoint.py"]
