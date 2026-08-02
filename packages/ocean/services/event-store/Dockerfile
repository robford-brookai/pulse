FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Copy ocean-events library first (build context = repo root)
COPY libs/ocean-events /libs/ocean-events

# Install ocean-events editable so it's available to event-store
RUN uv pip install --system --no-cache -e /libs/ocean-events

# Copy event-store pyproject.toml and install deps
COPY services/event-store/pyproject.toml .

# Install dependencies (ocean-events already installed above)
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "sqlalchemy==2.0.48" \
    asyncpg==0.31.0 \
    "confluent-kafka==2.13.2" \
    "structlog==25.5.0"

# Copy source code
COPY services/event-store/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
