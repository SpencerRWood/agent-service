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

RUN chmod +x /app/deploy/start.sh

EXPOSE 8000

CMD ["/app/deploy/start.sh"]
