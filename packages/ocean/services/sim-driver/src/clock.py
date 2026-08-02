"""Time compression helper — maps simulated hours to wall-clock sleep durations."""
from __future__ import annotations

import asyncio


async def sim_sleep(sim_hours: float, compression_ratio: float) -> None:
    """Sleep for sim_hours of simulated time, compressed to wall-clock seconds.

    Example: sim_hours=1.0, compression_ratio=960 → sleep(3.75 seconds).
    """
    wall_seconds = (sim_hours * 3600) / compression_ratio
    await asyncio.sleep(wall_seconds)
