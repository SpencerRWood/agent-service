FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim

WORKDIR /app

COPY backend/pyproject.toml backend/uv.lock /app/backend/
COPY backend/app /app/backend/app
COPY backend/alembic.ini /app/backend/alembic.ini
COPY backend/migrations /app/backend/migrations
COPY scripts /app/scripts

WORKDIR /app/backend

RUN uv sync --frozen --no-dev

ENV PATH="/app/backend/.venv/bin:$PATH"
ENV PYTHONPATH="/app/backend"

EXPOSE 8000

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
