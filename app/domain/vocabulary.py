"""Plant vocabulary shared by the parser, the event builder and the tools.

Everything here is plant knowledge, not implementation detail: the phrases an operator
uses for a normal state, which sensor backs which field variable, and the tolerance the
field uses to call two readings the same one.  Keeping it in a single module stops the
parser from accepting a phrase as "normal" that the event builder then escalates.
"""

from __future__ import annotations

# Observations that describe a healthy machine ("la tres está parada, en reserva").
NORMAL_STATES = frozenset({"parada, en reserva", "parada por mantenimiento"})

# Field variable -> plant sensor that carries the same magnitude.
SENSOR_MAP = {
    "presion_descarga_local": "presion_descarga",
    "presion_diferencial": "presion_diferencial",
    "temperatura_rodamiento_ir": "temperatura_aceite",
}

# Sensors that are monitored continuously (the ones the detector keeps a window for).
MONITORED_SENSORS = frozenset({
    "presion_descarga", "presion_succion", "presion_diferencial", "temperatura_aceite", "vibracion",
})

# Variables reported as an observation with no number attached.
QUALITATIVE_VARIABLES = frozenset({"goteo_empaquetadura", "estado_correas", "ruido", "nivel_aceite_visor"})

# A bearing read with the IR gun above this temperature is reported as hot, whatever the
# datasheet says (the plant's own rule of thumb, used by the parser and the event builder).
HOT_BEARING_DEGC = 75.0

# Two readings are the same one within 2 %, or 0.6 units on small values, as the field
# itself compares them ("ciento doce" vs "ciento doce y medio").
TOLERANCE_RATIO = 0.02
TOLERANCE_FLOOR = 0.6


def normalise(text: str | None) -> str:
    """Lowercase and collapse whitespace: the form observations are compared in."""
    return " ".join((text or "").lower().split())


def values_close(left: float | None, right: float | None, *, ratio: float = TOLERANCE_RATIO,
                 floor: float = TOLERANCE_FLOOR) -> bool:
    """Whether two readings are the same one, field tolerance included.

    ``floor`` is the absolute slack in the variable's unit: 0.6 for a pressure or a
    temperature, 1.0 when matching an anonymous correction against every row.
    """
    if left is None or right is None:
        return left == right
    return abs(float(left) - float(right)) <= max(floor, abs(float(right)) * ratio)
