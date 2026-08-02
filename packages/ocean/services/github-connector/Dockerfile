FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY libs/ocean-events /libs/ocean-events
COPY libs/ocean-broker /libs/ocean-broker

# ocean-broker is the publisher: it brings boto3, sqlalchemy[asyncio], and the
# EventBridge transport, which is why no bus client is pinned below.
RUN uv pip install --system --no-cache -e /libs/ocean-events -e /libs/ocean-broker

COPY services/github-connector/pyproject.toml .

RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "structlog==25.5.0"

COPY services/github-connector/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
