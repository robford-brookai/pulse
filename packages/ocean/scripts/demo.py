#!/usr/bin/env python3
"""Ocean demo orchestrator: boot stack, run scenario, print summary banner.

Usage:
    uv run python scripts/demo.py
    uv run python scripts/demo.py --warehouse
    uv run python scripts/demo.py --scenario pilot_demo --warehouse
"""
from __future__ import annotations

import argparse
import asyncio
import os
import time

import httpx

CORE_SERVICES = {
    "event-store": "http://localhost:8001/health",
    "graph-projection": "http://localhost:8003/health",
    "control-plane": "http://localhost:8004/health",
    "slack-bot": "http://localhost:8005/health",
}

SIM_SERVICES = {
    "sim-driver": "http://localhost:8060/health",
    "agent-worker": "http://localhost:8061/health",
    "call-simulator": "http://localhost:8062/health",
}

SIM_DRIVER_URL = "http://localhost:8060"
HASURA_CONSOLE_URL = "http://localhost:8090"
DOWNSTREAM_BUFFER_SECONDS = 15


async def wait_for_health(services: dict[str, str], timeout: int = 120) -> None:
    """Poll service health endpoints until all respond 200.

    Raises TimeoutError with list of unhealthy services if timeout exceeded.
    """
    deadline = time.monotonic() + timeout
    healthy: set[str] = set()

    while time.monotonic() < deadline:
        async with httpx.AsyncClient(timeout=3.0) as client:
            for name, url in services.items():
                if name in healthy:
                    continue
                try:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        healthy.add(name)
                except (httpx.ConnectError, httpx.TimeoutException, httpx.ReadError):
                    pass

        if len(healthy) == len(services):
            print(f"All {len(services)} services healthy.")
            return

        pending = sorted(set(services.keys()) - healthy)
        print(f"Waiting for services... ({len(healthy)}/{len(services)} healthy, pending: {', '.join(pending)})")
        await asyncio.sleep(2)

    unhealthy = sorted(set(services.keys()) - healthy)
    raise TimeoutError(f"Services not healthy after {timeout}s: {', '.join(unhealthy)}")


async def trigger_scenario(scenario: str = "pilot_demo") -> dict:
    """POST to sim-driver /simulate and return response metadata."""
    async with httpx.AsyncClient(timeout=30.0) as client:
        url = f"{SIM_DRIVER_URL}/simulate"  # http://localhost:8060/simulate
        resp = await client.post(url, json={"scenario": scenario})
        resp.raise_for_status()
        return resp.json()


async def wait_for_completion(timeout: int = 180) -> None:
    """Poll sim-driver /health until active_scenarios is empty.

    After scenarios finish publishing, waits DOWNSTREAM_BUFFER_SECONDS for
    the pipeline to drain (graph projection, control-plane, agent-worker).
    """
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            async with httpx.AsyncClient(timeout=3.0) as client:
                resp = await client.get(f"{SIM_DRIVER_URL}/health")
                data = resp.json()
                if not data.get("active_scenarios"):
                    print("Scenario publishing complete.")
                    print(f"Waiting {DOWNSTREAM_BUFFER_SECONDS}s for downstream processing...")
                    await asyncio.sleep(DOWNSTREAM_BUFFER_SECONDS)
                    return
        except (httpx.ConnectError, httpx.TimeoutException):
            pass

        print("Waiting for scenario to complete...")
        await asyncio.sleep(3)

    raise TimeoutError(f"Scenario not complete after {timeout}s")


async def sync_embeddings_all() -> None:
    """POST to stacte-bridge /sync for each entity type."""
    entity_types = ["alerts", "tasks", "interactions", "outcomes"]
    async with httpx.AsyncClient(timeout=30.0) as client:
        for entity_type in entity_types:
            try:
                resp = await client.post(
                    "http://stacte-bridge:8000/sync",
                    params={"entity_type": entity_type},
                )
                resp.raise_for_status()
                print(f"  ✓ Synced {entity_type} embeddings")
            except Exception as e:
                print(f"  ⚠ Embedding sync failed for {entity_type}: {e}")


def print_banner(scenario_meta: dict, warehouse: bool) -> None:
    """Print summary banner with exploration pointers."""
    scenario = scenario_meta.get("scenario", "unknown")
    patients = scenario_meta.get("patients", 0)

    print()
    print("=" * 70)
    print(f"  OCEAN DEMO COMPLETE -- {scenario}")
    print("=" * 70)
    print()
    print(f"  Scenario: {scenario}")
    print(f"  Patients: {patients}")
    print()
    print("  Check Slack channel for alert cards with claims, resolves,")
    print("  escalations, and call outcomes.")
    print()
    print(f"  Hasura Console: {HASURA_CONSOLE_URL}")
    print()
    print("  Ready-to-paste GraphQL query:")
    print("  ---")
    print("  query DemoPatientTimeline($pid: String!) {")
    print("    patients(where: {patient_id: {_eq: $pid}}) {")
    print("      patient_id enrollment_status")
    print("    }")
    print("    patient_timeline(")
    print("      where: {patient_id: {_eq: $pid}}")
    print("      order_by: {created_at: desc}")
    print("    ) {")
    print("      event_type event_id status summary created_at")
    print("    }")
    print("  }")
    print('  Variable: {"pid": "sim-pt-demo-001"}')
    print("  ---")
    print()

    # AI summary status — check both env and .env file
    has_key = bool(os.environ.get("ANTHROPIC_API_KEY"))
    if not has_key:
        env_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".env")
        try:
            with open(env_path) as f:
                for line in f:
                    if line.strip().startswith("ANTHROPIC_API_KEY=") and len(line.strip().split("=", 1)[1]) > 5:
                        has_key = True
                        break
        except FileNotFoundError:
            pass
    if has_key:
        print("  AI summaries: ENABLED (Haiku)")
    else:
        print("  AI summaries: UNAVAILABLE")
        print("  export ANTHROPIC_API_KEY=sk-... in .env to enable")
    print()

    # Warehouse status
    if warehouse:
        print("  Warehouse sync: ENABLED -- events streaming to Snowflake")
        print("  Run dbt: cd .repos/streamline && dbt run --select ocean")
    else:
        print("  Warehouse sync: DISABLED -- run with WAREHOUSE=true to enable")
    print()

    print("  Stack is running. Explore Slack threads, run GraphQL queries,")
    print("  check logs. Use 'task down' to stop.")
    print("=" * 70)
    print()


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(description="Ocean demo orchestrator")
    parser.add_argument(
        "--warehouse",
        action="store_true",
        default=False,
        help="Include warehouse-sync profile",
    )
    parser.add_argument(
        "--scenario",
        default="pilot_demo",
        help="Scenario name (default: pilot_demo)",
    )
    return parser.parse_args(argv)


async def main() -> None:
    """Run the full demo sequence: health check, trigger, wait, banner."""
    args = parse_args()

    print("Ocean Demo")
    print("-" * 40)

    # Core services must be healthy before proceeding
    await wait_for_health(CORE_SERVICES)
    # Sim services get a shorter timeout — agent-worker can be slow to start
    try:
        await wait_for_health(SIM_SERVICES, timeout=30)
    except TimeoutError as e:
        print(f"WARNING: {e}")
        print("Continuing — some sim services may still be starting.")

    print(f"\nTriggering scenario: {args.scenario}")
    meta = await trigger_scenario(args.scenario)
    print(f"Scenario started: {meta.get('patients', '?')} patients, "
          f"~{meta.get('estimated_duration_seconds', '?')}s estimated")

    await wait_for_completion()

    print("\n🔍 Syncing embeddings...")
    await sync_embeddings_all()

    print_banner(meta, warehouse=args.warehouse)


if __name__ == "__main__":
    asyncio.run(main())
