FROM python:3.14.8-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.23 /uv /usr/local/bin/uv

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PATH="/app/.venv/bin:$PATH"

WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev

RUN groupadd --gid 10001 querylens \
    && useradd --uid 10001 --gid querylens --no-create-home querylens

COPY --chown=querylens:querylens app ./app
COPY --chown=querylens:querylens migrations ./migrations
COPY --chown=querylens:querylens scripts ./scripts
COPY --chown=querylens:querylens knowledge ./knowledge
COPY --chown=querylens:querylens alembic.ini ./

USER querylens
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
