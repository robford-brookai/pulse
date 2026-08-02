"""sim-driver FastAPI app -- lifespan + /simulate endpoint.

Publishes source-only events (signal.received, alert.created) via PatientSimulator.
The /simulate response includes enriched metadata and an agent_hook advertising
the consumer contract for Phase 11's agent-worker.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, ValidationError

from src.publisher import RedpandaPublisher
from src.scenario_engine import ScenarioEngine

__version__ = "2.0.0"

log = structlog.get_logger()

# Track running scenarios to prevent duplicate runs
_active_scenarios: dict[str, asyncio.Task] = {}
_publisher: RedpandaPublisher | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    global _publisher
    brokers = os.environ.get("REDPANDA_BROKERS", "redpanda:29092")
    _publisher = RedpandaPublisher(bootstrap_servers=brokers)
    log.info("sim_driver_started", brokers=brokers)

    yield

    # Cancel any running scenarios on shutdown
    for task in list(_active_scenarios.values()):
        task.cancel()
    _active_scenarios.clear()
    log.info("sim_driver_stopped")


app = FastAPI(title="sim-driver", version="2.0.0", lifespan=lifespan)


class SimulateRequest(BaseModel):
    scenario: str = "smoke_test"


@app.get("/health")
async def health() -> dict:
    return {
        "status": "ok",
        "service": "sim-driver",
        "active_scenarios": list(_active_scenarios.keys()),
    }


@app.post("/simulate")
async def simulate(req: SimulateRequest) -> dict:
    """Start a named scenario in the background.

    Returns immediately with enriched metadata including patient count,
    expected events, estimated duration, and agent_hook consumer contract.
    """
    if _publisher is None:
        raise HTTPException(status_code=503, detail="Publisher not initialized")

    if req.scenario in _active_scenarios and not _active_scenarios[req.scenario].done():
        return {"status": "already_running", "scenario": req.scenario}

    try:
        engine = ScenarioEngine(scenario_name=req.scenario, publisher=_publisher)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors())

    task = asyncio.create_task(_run_scenario(engine, req.scenario))
    _active_scenarios[req.scenario] = task

    log.info("scenario_started", scenario=req.scenario)
    return {
        "status": "started",
        "scenario": req.scenario,
        "patients": engine.patient_count,
        "expected_events": engine.expected_event_count,
        "estimated_duration_seconds": round(engine.estimated_duration_seconds, 1),
        "agent_hook": {
            "description": "Source events will trigger control-plane task creation. Agent-worker (Phase 11) consumes from ocean.tasks.",
            "consumer_topics": ["ocean.tasks"],
            "source_filter": "control-plane",
            "personas_available": 3,
        },
    }


async def _run_scenario(engine: ScenarioEngine, name: str) -> None:
    try:
        # Reset agent-worker claimed_tasks before each scenario run
        try:
            async with httpx.AsyncClient(timeout=2.0) as client:
                resp = await client.post("http://agent-worker:8061/reset")
                log.info("agent_worker_reset", status=resp.status_code)
        except Exception as exc:
            log.warning("agent_worker_reset_failed", error=str(exc))

        await engine.run()
        log.info("scenario_finished", scenario=name)
    except asyncio.CancelledError:
        log.info("scenario_cancelled", scenario=name)
    except Exception:
        log.exception("scenario_error", scenario=name)
    finally:
        _active_scenarios.pop(name, None)
