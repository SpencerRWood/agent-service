FROM node:22-alpine AS frontend-build

WORKDIR /app/frontend

COPY frontend/package.json ./
COPY frontend/package-lock.json ./
COPY frontend/tsconfig.json ./
COPY frontend/tsconfig.app.json ./
COPY frontend/vite.config.ts ./
COPY frontend/index.html ./
COPY frontend/src ./src

ARG VITE_API_BASE_URL=/api
ENV VITE_API_BASE_URL=$VITE_API_BASE_URL

RUN npm ci
RUN npm run build

FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

ENV PYTHONUNBUFFERED=1
ENV PATH="/app/backend/.venv/bin:${PATH}"
ENV PYTHONPATH="/app/backend"
ENV APP_HOST=0.0.0.0
ENV APP_PORT=8000

WORKDIR /app/backend

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev

WORKDIR /app

COPY backend/app /app/backend/app
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY scripts /app/scripts
COPY deploy/start.sh /app/deploy/start.sh
COPY --from=frontend-build /app/frontend/dist /app/frontend/dist

RUN chmod +x /app/deploy/start.sh

EXPOSE 8000

CMD ["/app/deploy/start.sh"]
