FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# Build context is the repo root, not packages/ocean: this service installs pulse-core, which
# lives outside the ocean tree (packages/pulse-core). Every other ocean service builds from
# packages/ocean; the compose entry for this one names the wider context to match.
# Copy the local libraries first (build context = repo root)
COPY packages/ocean/libs/ocean-events /libs/ocean-events

# pulse-core is the kit `src/rebuild_patients.py` reads the ledger's replay route through
# (m1-retire-patient-state design decision 12). A workspace package exists on no index, so it can
# only be installed from a path in the context. The consumer path imports nothing from it.
COPY packages/pulse-core /libs/pulse-core

# Install the local libraries editable so they are available to graph-projection
RUN uv pip install --system --no-cache -e /libs/ocean-events -e /libs/pulse-core

# Copy graph-projection pyproject.toml and install deps
COPY packages/ocean/services/graph-projection/pyproject.toml .

# Install dependencies (ocean-events and pulse-core already installed above)
RUN uv pip install --system --no-cache \
    fastapi==0.135.1 \
    uvicorn==0.41.0 \
    "sqlalchemy==2.0.48" \
    asyncpg==0.31.0 \
    "aioboto3>=13.0.0" \
    "structlog==25.5.0"

# Copy source code
COPY packages/ocean/services/graph-projection/src ./src

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
