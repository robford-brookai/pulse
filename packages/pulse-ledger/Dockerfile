# Build context is the REPO ROOT, not this directory: pulse-core is a workspace sibling
# (`packages/pulse-ledger/pyproject.toml`'s `[tool.uv.sources]`), so both packages must be in the
# build context for a local-path install to see either. Build with:
#   docker buildx build --platform linux/amd64 -f packages/pulse-ledger/Dockerfile .
# --platform linux/amd64 is required on an arm64 dev machine: the target nodes are x86.
#
# One image, two commands — the API and the outbox relay (task 4.5) — never two images. The
# default CMD runs the API; a relay deployment overrides the command:
#   docker run <image> python -m pulse_ledger.relay_worker
FROM python:3.13-slim

WORKDIR /app

RUN pip install uv --quiet

# pulse-core first, pulse-ledger second: `uv pip install` resolving two local paths in one call
# does not reliably see one as the other's dependency, so this installs pulse-core as a real
# package before pulse-ledger ever asks for it by name (the pyproject.toml fallback the task
# describes, applied directly rather than as a later fix).
COPY packages/pulse-core /libs/pulse-core
RUN uv pip install --system --no-cache /libs/pulse-core

# twenty-projection next, before pulse-ledger asks for it by name: the heal-back leg imports its
# REST writer (`twenty_projection.apply`), so `pulse-ledger`'s `[project.dependencies]` names it,
# and it is a workspace sibling never published to an index — without this the build fails at
# `No matching distribution found for twenty-projection`.
#
# Plain `pip` here, not `uv pip`, for the same reason the pulse-ledger install below uses it:
# this package's `[tool.uv.sources]` points `pulse-core` at `{ workspace = true }`, which uv
# refuses outside a real uv workspace even though pulse-core is already on the path above.
COPY packages/twenty-projection /libs/twenty-projection
RUN pip install --no-cache-dir /libs/twenty-projection

# ocean-broker the same way: the relay process's EventBridge publisher, imported lazily inside
# `pulse_ledger.relay.default_publisher()`. A lazy import is still a runtime dependency — without
# this the relay container starts and then dies on `ModuleNotFoundError: No module named
# 'ocean_broker'` the first time it publishes, which is how it failed on dev 2026-08-21. It lives
# under packages/ocean/libs/, not packages/, so the path differs from its siblings above.
COPY packages/ocean/libs/ocean-broker /libs/ocean-broker
RUN pip install --no-cache-dir /libs/ocean-broker

# The [serve] extra brings uvicorn — the API process's ASGI server, not a hard dependency of the
# library (identity/verdict-relay/schedules import pulse-ledger without it).
#
# Plain `pip`, not `uv pip`, for this one: pulse-ledger's `[tool.uv.sources]` points `pulse-core`
# at `{ workspace = true }`, and `uv` refuses to build any package declaring that outside an actual
# uv workspace — even though pulse-core is already installed above and satisfies the plain
# `pulse-core` dependency in `[project.dependencies]` by name. Stock pip has no opinion on
# `tool.uv.sources` and installs against what is already on the system path.
COPY packages/pulse-ledger /app/pulse-ledger
RUN pip install --no-cache-dir "/app/pulse-ledger[serve,relay]"

CMD ["python", "-m", "pulse_ledger.api_server"]
