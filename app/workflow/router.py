"""Message routing: one place that decides what a plant message is for.

Delivery 2 asks for routing by message type (seguridad, parte, sensor, respuesta del
operador, cierre). The plant has no separate safety topic — safety is detected locally
from the transcript of a part — so the router exposes the six routes and keeps the
"a part that turns out to be unsafe" decision in one documented place instead of
scattered through the dispatch loop.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Topic = Literal["parte", "sensor", "respuesta", "cierre", "energia", "desconocido"]
Route = Literal["seguridad", "parte", "sensor", "respuesta", "cierre", "energia"]

NOTE_TOPIC = "planta/recorridas"
SENSOR_PREFIX = "planta/sensores/"
TOPIC_ROUTES: dict[str, Topic] = {
    NOTE_TOPIC: "parte",
    "planta/respuestas": "respuesta",
    "planta/cierres": "cierre",
    "planta/energia": "energia",
}


@dataclass(frozen=True)
class Routed:
    """A plant message with the route the pipeline must take."""

    route: Route
    topic: str
    payload: dict


def route_topic(topic: str) -> Topic:
    if topic.startswith(SENSOR_PREFIX):
        return "sensor"
    return TOPIC_ROUTES.get(topic, "desconocido")


def route_note(*, safety: str | None) -> Route:
    """A part goes to the safety path when the local detector found a condition.

    The detector runs on the transcript before any model or network call, so the safety
    route is decided on the same text the plant will hear, not on a payload flag.
    """
    return "seguridad" if safety else "parte"


def sensor_parts(payload: dict) -> tuple[str, str] | None:
    """The (tag, variable) a sensor message is about, or None when it is malformed."""
    tag, variable = payload.get("tag"), payload.get("variable")
    if not tag or not variable:
        return None
    return str(tag), str(variable)


def classify(topic: str, payload: dict) -> Routed:
    """Route a message by its topic. Parts stay ``parte`` until the transcript says otherwise."""
    return Routed(route=route_topic(topic), topic=topic, payload=payload)  # type: ignore[arg-type]
