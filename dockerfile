FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    POETRY_VERSION=2.4.1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        libexpat1 \
        gcc && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir "poetry==$POETRY_VERSION"

COPY pyproject.toml poetry.lock README.md ./

RUN poetry install --only main --no-interaction --no-ansi --no-root

# Force a completely clean charset-normalizer installation
RUN pip uninstall -y charset-normalizer && \
    pip install --no-cache-dir "charset-normalizer==3.4.1"

COPY neurocom_backend ./neurocom_backend

CMD ["sh", "-c", "poetry run uvicorn neurocom_backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]

