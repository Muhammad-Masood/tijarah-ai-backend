FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        gcc \
        libexpat1 && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir poetry==2.4.1

COPY pyproject.toml poetry.lock README.md ./

RUN poetry export -f requirements.txt --output requirements.txt --without-hashes

RUN pip install --no-cache-dir -r requirements.txt

COPY neurocom_backend ./neurocom_backend

CMD ["sh", "-c", "uvicorn neurocom_backend.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
