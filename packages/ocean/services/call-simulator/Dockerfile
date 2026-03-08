FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Install dependencies
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "confluent-kafka==2.13.2" \
    "pydantic>=2.0" \
    "structlog==25.5.0"

# Install ocean-events shared library
COPY libs/ocean-events /app/ocean-events
RUN uv pip install --system /app/ocean-events

# Copy source code
COPY services/call-simulator/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
