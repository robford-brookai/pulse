FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Install dependencies
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "sqlalchemy==2.0.48" \
    asyncpg==0.31.0 \
    "voyageai>=0.3.0" \
    "pgvector>=0.3.0" \
    "structlog==25.5.0" \
    "httpx>=0.28.1"

# Copy source code
COPY services/stacte-bridge/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
