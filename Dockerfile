# syntax=docker/dockerfile:1

# ---------------------------------------------------------------------------
# Stage 1 - build the single-page application.
# ---------------------------------------------------------------------------
FROM node:22-alpine AS frontend

WORKDIR /build
# Dependencies are copied first so a source-only change reuses the npm layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund

COPY frontend/ ./
# The build writes into the Python package, which is where the server serves
# it from; keeping that path identical in Docker and on a laptop means one
# code path instead of two.
RUN mkdir -p /out && npx vite build --outDir /out --emptyOutDir

# ---------------------------------------------------------------------------
# Stage 2 - the application image.
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PORT=8000

WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY src/ ./src/
COPY examples/ ./examples/

RUN pip install --no-cache-dir ".[studio]"

COPY --from=frontend /out /app/src/bpmn_architect/server/static

# An unprivileged user: nothing here needs root at runtime.
RUN useradd --create-home --uid 10001 studio && chown -R studio:studio /app
USER studio

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=3s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2).status==200 else 1)"

CMD ["python", "-m", "uvicorn", "bpmn_architect.server.app:app", "--host", "0.0.0.0", "--port", "8000"]
