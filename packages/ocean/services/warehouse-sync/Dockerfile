FROM python:3.13-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends g++ && rm -rf /var/lib/apt/lists/*

# Copy pyproject.toml and install deps
COPY services/warehouse-sync/pyproject.toml .
# pip, not uv: uv segfaults (SIGSEGV, exit 139) under qemu amd64 emulation on the
# arm64 dev machines this image is built from; versions are fully pinned so pip is equivalent.
RUN pip install --no-cache-dir \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "aioboto3>=13.0.0" \
    "snowflake-connector-python==3.12.3" \
    "cryptography>=43.0.0" \
    "pyopenssl==24.3.0" \
    "structlog==25.5.0"

# Copy source code
COPY services/warehouse-sync/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8008"]
