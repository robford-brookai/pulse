FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Install dependencies
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "confluent-kafka==2.13.2" \
    "pydantic>=2.0" \
    "pyyaml>=6.0" \
    "structlog==25.5.0" \
    "anthropic>=0.49.0" \
    "asyncpg>=0.31.0"

# Install ocean-events shared library
COPY libs/ocean-events /app/ocean-events
RUN uv pip install --system /app/ocean-events

# Install ocean-broker: the shared EventBridge publisher and event catalog
COPY libs/ocean-broker /app/ocean-broker
RUN uv pip install --system /app/ocean-broker

# Copy source code
COPY services/agent-worker/src ./src

# Copy AGENTS.md for persona loading
COPY AGENTS.md /app/AGENTS.md

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--no-access-log"]
