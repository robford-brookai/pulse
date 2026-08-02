#!/usr/bin/env bash
set -e

echo "Checking uv sync with retries"
tries=0
until [ $tries -ge 3 ]; do
  uv sync --all-packages --frozen && break
  tries=$((tries+1))
  echo "uv sync failed, retrying ($tries/3)..."
  sleep $((tries * 5))
done
if [ $tries -ge 3 ]; then
  echo "uv sync failed after 3 attempts" >&2
  exit 1
fi

echo "Verifying critical imports"
python .github/scripts/check_imports.py pydantic uvicorn
