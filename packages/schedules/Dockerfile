# Build context is the REPO ROOT (same rule as packages/pulse-ledger/Dockerfile): every
# dependency here is a workspace sibling never published to an index. Build with:
#   docker buildx build --platform linux/amd64 -f packages/schedules/Dockerfile .
# --platform linux/amd64 is required on an arm64 dev machine: the target nodes are x86.
#
# One image, every schedules job — the CMD picks the subcommand:
#   docker run <image> python -m schedules.cli month-open | consent-sweep | verdict-relay-poll
#
# Plain `pip` throughout (not `uv pip`) for the same two reasons the ledger Dockerfile documents:
# `tool.uv.sources` workspace pins refuse to resolve outside a real uv workspace, and uv
# segfaults under qemu amd64 emulation (warehouse-sync revival, 2026-08-26).
FROM python:3.13-slim

WORKDIR /app

# Dependency order matters: each local path must be installed before a later package names it.
COPY packages/pulse-core /libs/pulse-core
RUN pip install --no-cache-dir /libs/pulse-core

# pulse-ledger's own hard deps, installed first by the same rule.
COPY packages/twenty-projection /libs/twenty-projection
RUN pip install --no-cache-dir /libs/twenty-projection

COPY packages/pulse-ledger /libs/pulse-ledger
RUN pip install --no-cache-dir /libs/pulse-ledger

COPY packages/verdict-relay /libs/verdict-relay
RUN pip install --no-cache-dir /libs/verdict-relay

COPY packages/schedules /app/schedules
RUN pip install --no-cache-dir /app/schedules

CMD ["python", "-m", "schedules.cli", "month-open"]
