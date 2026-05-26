# syntax=docker/dockerfile:1.7

# ─── Stage 1 : build frontend assets ──────────────────────────────
FROM node:22-slim AS frontend-builder
WORKDIR /build/frontend
COPY frontend/package*.json ./
RUN npm ci
COPY frontend ./
RUN npm run build

# ─── Stage 2 : build wheel ────────────────────────────────────────
FROM python:3.12-slim AS builder
WORKDIR /build
RUN pip install --no-cache-dir --upgrade pip build
COPY pyproject.toml README.md ./
COPY jobmail ./jobmail
COPY --from=frontend-builder /build/jobmail/web/static/assets ./jobmail/web/static/assets
RUN python -m build --wheel --outdir /dist

# ─── Stage 3 : runtime ────────────────────────────────────────────
FROM python:3.12-slim
WORKDIR /app

# Non-root user for runtime
RUN groupadd -r app && useradd -r -g app -d /app -s /sbin/nologin app \
 && mkdir -p /app/data && chown -R app:app /app

# Install the wheel + claude extras (Anthropic SDK) so all 3 providers work.
COPY --from=builder /dist/*.whl /tmp/
RUN pip install --no-cache-dir /tmp/*.whl "anthropic>=0.40" \
 && rm -rf /tmp/*.whl /root/.cache/pip

USER app
ENV PYTHONUNBUFFERED=1 \
    DB_PATH=/app/data/jobmail.db \
    WEB_HOST=0.0.0.0 \
    WEB_PORT=8765
EXPOSE 8765

# Healthcheck via the dashboard root.
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request,sys; \
    sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8765/', timeout=3).status==200 else 1)"

# Default cmd : web dashboard. Override with `jobmail fetch` for one-shot runs.
CMD ["python", "-m", "jobmail", "serve"]
