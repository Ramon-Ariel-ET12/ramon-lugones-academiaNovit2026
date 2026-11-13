"""Historical range validation against the plant historian."""

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta

from app.domain.limits import to_pressure_unit, within
from app.domain.models import ExtractedRow, PlantSnapshot
from app.domain.vocabulary import SENSOR_MAP
from app.integrations.plant_api import PlantClient

log = logging.getLogger(__name__)

CACHE_SECONDS = 600.0
MARGIN = 0.05
MIN_RANGE_SAMPLES = 20       # below this a min/max says nothing about the operation
MIN_HISTORY_SAMPLES = 1440   # one day at one sample per minute: enough to ask the operator


def range_from_values(values: list[float | None],
                      minimum: int = MIN_RANGE_SAMPLES) -> tuple[float, float] | None:
    """Observed operating range, or None when the historian has too little history."""

    clean = [value for value in values if value is not None]
    if len(clean) < minimum:
        return None
    # Observed operating range. A normal field reading is inside it; only a gross
    # outlier asks for confirmation.
    return min(clean), max(clean)


def outside_range(value: float, unit: str | None, bounds: tuple[float, float]) -> bool:
    low, high = bounds
    span = max(high - low, abs(high) * 0.02, 0.1)
    measured = to_pressure_unit(value, unit)
    return measured < low - span * MARGIN or measured > high + span * MARGIN


class HistoricalValidator:
    def __init__(self, plant: PlantClient, snapshot: PlantSnapshot):
        self.plant = plant
        self.snapshot = snapshot
        self._cache: dict[tuple[str, str], tuple[float, tuple[float, float] | None]] = {}

    async def _bounds(self, tag: str, variable: str, reference: datetime):
        key = (tag, variable)
        cached = self._cache.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < CACHE_SECONDS:
            return cached[1]
        try:
            samples = await self.plant.historian(tag, variable,
                                                 desde=(reference - timedelta(days=45)).isoformat(),
                                                 hasta=reference.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("historian unavailable for %s/%s: %s", tag, variable, exc)
            self._cache[key] = (now, None)
            return None
        # A scenario that starts from scratch has minutes of data; asking the operator
        # to confirm a reading "outside the historical range" from that is only noise.
        bounds = range_from_values([item.get("valor") for item in samples], MIN_HISTORY_SAMPLES)
        self._cache[key] = (now, bounds)
        return bounds

    async def check(self, rows: list[ExtractedRow], reference: datetime) -> list[ExtractedRow]:
        flagged: list[ExtractedRow] = []
        for row in rows:
            if row.value is None:
                continue
            sensor = SENSOR_MAP.get(row.variable)
            if sensor is None:
                continue
            limit = self.snapshot.limit(row.tag, sensor)
            if limit is None:
                continue
            # A value inside the datasheet band is a normal operating reading even if it
            # is new in the observed history. Only an out-of-band value that is also new
            # asks the operator to confirm.
            if within(row.value, row.unit, limit):
                continue
            bounds = await self._bounds(row.tag, sensor, reference)
            if bounds and outside_range(row.value, row.unit, bounds):
                flagged.append(row)
        return flagged
