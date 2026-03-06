"""sim-driver FastAPI app — lifespan + /simulate endpoint."""
from __future__ import annotations

import asyncio
import os
from contextlib import asynccontextmanager

import structlog
from fastapi import BackgroundTasks, FastAPI, HTTPException
from pydantic import BaseModel

from src.publisher import RedpandaPublisher
from src.scenario_engine import ScenarioEngine

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


app = FastAPI(title="sim-driver", version="0.1.0", lifespan=lifespan)


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

    Returns immediately. The scenario runs asynchronously.
    POST /simulate {"scenario": "smoke_test"}
    """
    if _publisher is None:
        raise HTTPException(status_code=503, detail="Publisher not initialized")

    if req.scenario in _active_scenarios and not _active_scenarios[req.scenario].done():
        return {"status": "already_running", "scenario": req.scenario}

    engine = ScenarioEngine(scenario_name=req.scenario, publisher=_publisher)

    task = asyncio.create_task(_run_scenario(engine, req.scenario))
    _active_scenarios[req.scenario] = task

    log.info("scenario_started", scenario=req.scenario)
    return {"status": "started", "scenario": req.scenario}


async def _run_scenario(engine: ScenarioEngine, name: str) -> None:
    try:
        await engine.run()
        log.info("scenario_finished", scenario=name)
    except asyncio.CancelledError:
        log.info("scenario_cancelled", scenario=name)
    except Exception:
        log.exception("scenario_error", scenario=name)
    finally:
        _active_scenarios.pop(name, None)
