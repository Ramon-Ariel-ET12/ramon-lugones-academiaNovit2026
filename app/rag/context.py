"""Evidence context for an escalated event.

The full maintenance analysis belongs to the second deliverable; this builder is the
contract for it: source rows, photos, sensor trend, cited manual sections, historical
orders and available parts, with no LLM in the loop.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from itertools import pairwise
from statistics import mean

from app.domain.materials import Materials
from app.domain.models import ExtractedRow, PlantSnapshot
from app.integrations.plant_api import PlantClient
from app.rag.search import ManualSearch

log = logging.getLogger(__name__)

# How many jobs of the plant's history one event looks at. The recurring patterns need
# the other pumps and both filters, so the query is not filtered by equipment; the cap is
# only a bound for the context, and it keeps the most recent jobs.
ORDER_HISTORY_LIMIT = 250

# How many samples the oscillation estimate looks at: enough to see a pulsation, short
# enough that a slow level change in the window does not look like one.
OSCILLATION_SAMPLES = 40


def _query_for(equipment: str, rows: list[ExtractedRow], snapshot: PlantSnapshot) -> str:
    description = snapshot.equipment.get(equipment)
    parts = [description.description if description else equipment]
    for row in rows:
        parts.append(row.variable.replace("_", " "))
        if row.observation:
            parts.append(row.observation)
    parts.append("falla causa probable accion recomendada")
    return " ".join(parts)


def _recent_orders(orders: list[dict], limit: int = ORDER_HISTORY_LIMIT) -> list[dict]:
    """The most recent jobs, bounded. The ISO text sorts lexicographically (same offset)."""
    dated = sorted(orders, key=lambda order: str(order.get("fecha_aviso") or order.get("fecha") or ""))
    return dated[-limit:] if limit > 0 else dated


async def sensor_trend(plant: PlantClient, snapshot: PlantSnapshot, equipment: str | None,
                       hours: int = 6) -> dict:
    """Recent trend per sensor of one equipment (last hours), for the escalated event."""
    if not equipment:
        return {}
    try:
        state = await plant.state()
        now = datetime.fromisoformat(state["ts"])
    except Exception:
        log.warning("plant state unavailable: using the host clock for the trend", exc_info=True)
        now = datetime.now().astimezone()
    trend: dict[str, dict] = {}
    for key in snapshot.limits:
        tag, variable = key.split("|", 1)
        if tag != equipment:
            continue
        try:
            samples = await plant.historian(tag, variable, desde=(now - timedelta(hours=hours)).isoformat(),
                                            hasta=now.isoformat())
        except Exception as exc:  # noqa: BLE001
            log.warning("historian %s/%s unavailable: %s", tag, variable, exc)
            continue
        values = [item["valor"] for item in samples if item.get("valor") is not None]
        if not values:
            continue
        limit = snapshot.limit(tag, variable)
        window = values[-OSCILLATION_SAMPLES:]
        steps = [abs(later - earlier) for earlier, later in pairwise(window)]
        trend[variable] = {
            "n": len(values),
            "min": round(min(values), 2),
            "max": round(max(values), 2),
            "last": round(values[-1], 2),
            # Mean step between consecutive samples: a pulsating gauge moves a lot every
            # sample, a drifting level barely moves. The range alone cannot tell them apart.
            "osc": round(mean(steps), 3) if steps else 0.0,
            "unit": limit.unit if limit else "",
        }
    return trend


async def build_event_context(event: dict, rows: list[ExtractedRow], photos: list[str],
                              plant: PlantClient, search: ManualSearch | None, snapshot: PlantSnapshot,
                              materials: Materials | None, *, include_history: bool = True) -> dict:
    equipment = event.get("equipo")
    context: dict = {"event": event, "rows": [row.model_dump() for row in rows], "photos": photos}
    if not equipment:
        return context
    context["sensor_trend"] = await sensor_trend(plant, snapshot, equipment)
    if search is not None:
        try:
            context["sections"] = await search.search(_query_for(equipment, rows, snapshot), 6)
        except Exception:  # noqa: BLE001
            context["sections"] = []
    if include_history:
        try:
            # One unfiltered call: the five recurring cases need the other pumps and the two
            # filters, not only this equipment's last five jobs.
            history = await plant.order_history()
            context["order_history"] = _recent_orders(history)
        except Exception:  # noqa: BLE001
            context["order_history"] = []
    else:
        # Storing the whole archive in the event row would add ~90 KB per escalation and
        # the console never shows it; the conclusions live in order_analysis.
        context["order_history"] = []
    if materials is not None:
        context["available_parts"] = [
            {"codigo": code, "stock": materials.parts[code].stock.get("yacimiento", 0),
             "costo_usd": materials.parts[code].cost_usd}
            for code in materials.bom.get(equipment, []) if code in materials.parts
        ]
    return context
