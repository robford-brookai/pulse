FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY libs/ocean-events /libs/ocean-events
COPY libs/ocean-broker /libs/ocean-broker

RUN uv pip install --system --no-cache -e /libs/ocean-events
RUN uv pip install --system --no-cache -e /libs/ocean-broker

COPY services/mongodb-connector/pyproject.toml .

RUN uv pip install --system --no-cache \
    "motor>=3.3" \
    "pymongo>=4.6" \
    "asyncpg>=0.29" \
    "sqlalchemy[asyncio]>=2.0" \
    "confluent-kafka>=2.3" \
    "structlog>=24.0" \
    "fastapi>=0.110" \
    "uvicorn>=0.27"

COPY services/mongodb-connector/src ./src

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/healthz')"]

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
