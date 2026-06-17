# FastAPI backend image.
FROM python:3.11-slim

WORKDIR /app

# Build tooling for native deps (asyncpg / psycopg2 wheels usually exist, but
# libpq headers keep source builds working across platforms).
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies first for better layer caching.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

EXPOSE 8000

# --reload picks up changes mounted from the host via docker-compose.
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
