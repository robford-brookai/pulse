#!/usr/bin/env python3
"""Gate 2: Configuration & Secrets
Usage: cd /path/to/ocean && python test/cat2_config.py
Loads .env if present; validates all env vars required by OCEAN services.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Parse .env file if present (no python-dotenv required)
env_file = Path(".env")
if env_file.exists():
    for line in env_file.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            os.environ.setdefault(k.strip(), v.strip())

failures: list[str] = []


def check(name: str, condition: bool, hint: str = "") -> None:
    if condition:
        print(f"PASS: {name}")
    else:
        msg = f"FAIL: {name}"
        if hint:
            msg += f" — {hint}"
        failures.append(msg)


# --- Core infrastructure (required by most services) ---
check("DATABASE_URL",     bool(os.getenv("DATABASE_URL")),     "postgresql+asyncpg://... required")
check("REDPANDA_BROKERS", bool(os.getenv("REDPANDA_BROKERS")), "host:port required")

# DATABASE_URL shape: must start with postgresql
db_url = os.getenv("DATABASE_URL", "")
check("DATABASE_URL format", db_url.startswith("postgresql"), "must start with 'postgresql'")

# --- Slack-bot required vars ---
check("SLACK_BOT_TOKEN",    bool(os.getenv("SLACK_BOT_TOKEN")),    "xoxb-... token required")
check("SLACK_SIGNING_SECRET", bool(os.getenv("SLACK_SIGNING_SECRET")), "signing secret required")

slack_token = os.getenv("SLACK_BOT_TOKEN", "")
check("SLACK_BOT_TOKEN format", slack_token.startswith("xoxb-"), "must start with 'xoxb-'")

check("HASURA_URL", bool(os.getenv("HASURA_URL")), "http://... required")
hasura_url = os.getenv("HASURA_URL", "")
check("HASURA_URL format", hasura_url.startswith("http"), "must start with 'http'")

check("HASURA_GRAPHQL_ADMIN_SECRET", bool(os.getenv("HASURA_GRAPHQL_ADMIN_SECRET")), "admin secret required")
check("OPS_SLACK_CHANNEL", bool(os.getenv("OPS_SLACK_CHANNEL")), "e.g. #care-alerts-ops")
ops_channel = os.getenv("OPS_SLACK_CHANNEL", "")
check("OPS_SLACK_CHANNEL format", ops_channel.startswith("#"), "must start with '#'")

# --- ZCC dispatch vars (slack-bot outreach) ---
check("ZCC_ACCOUNT_ID",      bool(os.getenv("ZCC_ACCOUNT_ID")),      "Zoom account ID required")
check("ZCC_CLIENT_ID",       bool(os.getenv("ZCC_CLIENT_ID")),       "Zoom OAuth client ID required")
check("ZCC_CLIENT_SECRET",   bool(os.getenv("ZCC_CLIENT_SECRET")),   "Zoom OAuth client secret required")
check("ZCC_DEFAULT_QUEUE_ID", bool(os.getenv("ZCC_DEFAULT_QUEUE_ID")), "Zoom queue ID required")
check("PHI_STORE_URL",       bool(os.getenv("PHI_STORE_URL")),       "PHI store URL required for outreach")

# --- Webhook secrets (HMAC auth) ---
check("POCAR_WEBHOOK_SECRET", bool(os.getenv("POCAR_WEBHOOK_SECRET")), "HMAC secret for POCAR webhooks")
check("ZCC_WEBHOOK_SECRET",   bool(os.getenv("ZCC_WEBHOOK_SECRET")),   "HMAC secret for ZCC webhooks")

pocar_secret = os.getenv("POCAR_WEBHOOK_SECRET", "")
check("POCAR_WEBHOOK_SECRET length", len(pocar_secret) >= 8, "must be at least 8 chars")

zcc_secret = os.getenv("ZCC_WEBHOOK_SECRET", "")
check("ZCC_WEBHOOK_SECRET length", len(zcc_secret) >= 8, "must be at least 8 chars")

# --- stacte-bridge ---
check("VOYAGE_API_KEY", bool(os.getenv("VOYAGE_API_KEY")), "VoyageAI API key required for embeddings")

# --- sim-driver ---
check("ANTHROPIC_API_KEY",   bool(os.getenv("ANTHROPIC_API_KEY")),   "Claude API key required for sim agents")
anthropic_key = os.getenv("ANTHROPIC_API_KEY", "")
check("ANTHROPIC_API_KEY format", anthropic_key.startswith("sk-ant-"), "must start with 'sk-ant-'")

check("SLACK_BOT_TOKEN_SIM", bool(os.getenv("SLACK_BOT_TOKEN_SIM")), "Separate Slack token for sim workspace")

# --- Print summary ---
print()
if failures:
    for f in failures:
        print(f, file=sys.stderr)
    print(f"\nGate 2: {len(failures)} failed", file=sys.stderr)
    sys.exit(1)
else:
    total = 21  # count of check() calls above
    print(f"Gate 2: all {total} checks passed")
