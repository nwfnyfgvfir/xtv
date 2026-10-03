# syntax=docker/dockerfile:1

# --- frontend build ---
FROM node:22-alpine AS frontend
# App version baked into the SPA; CI passes the git tag (e.g. v0.9.8).
ARG APP_VERSION=dev
ENV APP_VERSION=$APP_VERSION
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

# --- backend runtime ---
FROM python:3.12-slim AS runtime
# Same tag as the frontend stage; exposed via FastAPI version + /api/health.
ARG APP_VERSION=
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MEDIA_ROOT=/media \
    DATABASE_URL=sqlite:////data/app.db \
    APP_VERSION=${APP_VERSION}

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

COPY backend/app /app/app
COPY --from=frontend /src/frontend/dist /app/app/static

RUN mkdir -p /data /media/local /media/strm

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
