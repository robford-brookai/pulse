FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Install dependencies
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "pydantic>=2.0" \
    "structlog==25.5.0" \
    "sqlalchemy[asyncio]>=2.0" \
    "asyncpg>=0.29"

# Install ocean shared libraries: the event envelope and the EventBridge publisher/catalog
COPY libs/ocean-events /app/ocean-events
COPY libs/ocean-broker /app/ocean-broker
RUN uv pip install --system /app/ocean-events /app/ocean-broker

# Copy source code
COPY services/call-simulator/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
