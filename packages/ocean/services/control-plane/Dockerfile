FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Copy shared libraries first (build context = repo root)
COPY libs/ocean-events /libs/ocean-events
COPY libs/ocean-broker /libs/ocean-broker

# Install them editable so they're available to control-plane. ocean-broker is the
# transport: it brings boto3 and the EventBridge publisher the consumer depends on.
RUN uv pip install --system --no-cache -e /libs/ocean-events -e /libs/ocean-broker

# Copy control-plane pyproject.toml and install deps
COPY services/control-plane/pyproject.toml .

# Install dependencies (ocean-events already installed above)
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "sqlalchemy==2.0.48" \
    asyncpg==0.31.0 \
    "structlog==25.5.0" \
    httpx

# Copy source code
COPY services/control-plane/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
