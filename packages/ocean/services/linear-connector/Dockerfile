FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Copy shared libraries first (build context = repo root)
COPY libs/ocean-events /libs/ocean-events
COPY libs/ocean-broker /libs/ocean-broker

# Install them editable so they're available to linear-connector
RUN uv pip install --system --no-cache -e /libs/ocean-events
RUN uv pip install --system --no-cache -e /libs/ocean-broker

# Copy linear-connector pyproject.toml and install deps
COPY services/linear-connector/pyproject.toml .

# Install dependencies
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "structlog==25.5.0" \
    "asyncpg>=0.29" \
    "sqlalchemy[asyncio]>=2.0"

# Copy source code
COPY services/linear-connector/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
