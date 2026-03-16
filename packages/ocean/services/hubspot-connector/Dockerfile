FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

COPY libs/ocean-events /libs/ocean-events

RUN uv pip install --system --no-cache -e /libs/ocean-events

COPY services/hubspot-connector/pyproject.toml .

RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "confluent-kafka==2.13.2" \
    "structlog==25.5.0"

COPY services/hubspot-connector/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
