FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

RUN pip install uv --quiet

# Copy pyproject.toml and install deps
COPY services/warehouse-sync/pyproject.toml .
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "confluent-kafka==2.13.2" \
    "snowflake-connector-python==3.12.3" \
    "cryptography>=43.0.0" \
    "pyopenssl==24.3.0" \
    "structlog==25.5.0"

# Copy source code
COPY services/warehouse-sync/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8008"]
