# Build context is the REPO ROOT, not this directory: pulse-core and billing are workspace
# siblings (`packages/billing-connector/pyproject.toml`'s `[tool.uv.sources]`), so both must be in
# the build context for a local-path install to see either — same posture pulse-ledger's
# Dockerfile documents for its own siblings. Build with:
#   docker buildx build --platform linux/amd64 -f packages/billing-connector/Dockerfile .
# --platform linux/amd64 is required on an arm64 dev machine: the target nodes are x86.
#
# One process, one command: `python -m billing_connector.service` (task 2.3's consume loop). No
# HTTP server — the connector serves nothing, it consumes its own SQS queue and declares through
# the command API.
FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# pulse-core first: `uv pip install` resolving two local paths in one call does not reliably see
# one as the other's dependency, so this installs pulse-core as a real package before billing or
# billing-connector ever ask for it by name (the same fallback pulse-ledger's Dockerfile applies).
COPY packages/pulse-core /libs/pulse-core
RUN uv pip install --system --no-cache /libs/pulse-core

# billing next: the engine's fact store and rules registry this connector reads and declares
# against (`billing.store.PostgresFactStore`, `billing.rules.registry`, `billing.consumer`'s
# engine-credential name). A workspace sibling never published to an index.
COPY packages/billing /libs/billing
RUN pip install --no-cache-dir /libs/billing

# billing-connector itself.
#
# Plain `pip`, not `uv pip`, for this one: its `[tool.uv.sources]` points `pulse-core` and
# `billing` at `{ workspace = true }`, which `uv` refuses to build outside a real uv workspace even
# though both are already installed above and satisfy the plain dependency names in
# `[project.dependencies]`. Stock pip has no opinion on `tool.uv.sources` and installs against
# what is already on the system path.
COPY packages/billing-connector /app/billing-connector
RUN pip install --no-cache-dir /app/billing-connector

CMD ["python", "-m", "billing_connector.service"]
