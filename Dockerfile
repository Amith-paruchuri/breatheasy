# Single production image: built frontend + FastAPI backend, one origin.
# Build from the repo root:  docker build -t breatheasy .

# ---- 1. frontend ----
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---- 2. runtime ----
FROM python:3.12-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app
COPY backend/requirements.lock ./
RUN pip install -r requirements.lock
COPY backend/alembic.ini ./
COPY backend/migrations ./migrations
COPY backend/app ./app
COPY --from=web /web/dist ./static
RUN useradd --create-home --uid 10001 appuser && chown -R appuser /app
USER appuser

ENV ENV=production \
    STATIC_DIR=/app/static \
    PORT=8080
EXPOSE 8080
# Cloud Run sends SIGTERM and allows ~10 s; finish in-flight requests within that.
CMD exec uvicorn app.main:app --host 0.0.0.0 --port "${PORT}" \
    --proxy-headers --forwarded-allow-ips="*" --timeout-graceful-shutdown 8 --no-server-header
