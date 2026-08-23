FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends tesseract-ocr \
    && rm -rf /var/lib/apt/lists/*

RUN groupadd --system metro && useradd --system --gid metro --home-dir /app metro

COPY pyproject.toml README.md ./
COPY src ./src
RUN pip install --upgrade pip && pip install .

COPY alembic.ini ./
COPY migrations ./migrations

RUN mkdir -p /app/data/raw /app/data/staging && chown -R metro:metro /app
USER metro

EXPOSE 8000
CMD ["uvicorn", "metro_collector.api.app:app", "--host", "0.0.0.0", "--port", "8000"]
