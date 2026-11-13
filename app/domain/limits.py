"""Sensor limit evaluation, in one place.

The same limit decides three different things: the wording of an observation in the
part ("presión de descarga alta"), whether the part escalates, and whether a reading
asks the operator for confirmation against the historian.  Keeping the comparison in
one module is what makes those three agree.

Values arrive in whatever unit the operator dictated, so pressures are normalised to
kg/cm2 (the plant's local gauge unit) before the comparison; the raw boundary check
takes an already-normalised value and is used by the sensor detector, which receives
its samples in the unit declared by the limit.
"""

from __future__ import annotations

from app.domain.models import SensorLimit
from app.domain.units import PRESSURE_UNITS, to_kg

HIGH = "high"
LOW = "low"

Violation = str | None


def to_pressure_unit(value: float, unit: str | None) -> float:
    """Express a pressure reading in kg/cm2; other variables pass through untouched."""
    return to_kg(value, unit) if unit in PRESSURE_UNITS else value


def boundary(value: float, limit: SensorLimit | None) -> Violation:
    """Compare a normalised value against ``limit``: ``"high"``, ``"low"`` or ``None``.

    A limit without bounds is always satisfied, and the comparison is inclusive on both
    ends, as the plant's own alarm thresholds are.
    """
    if limit is None:
        return None
    if limit.high is not None and value >= limit.high:
        return HIGH
    if limit.low is not None and value <= limit.low:
        return LOW
    return None


def violation(value: float, unit: str | None, limit: SensorLimit | None) -> Violation:
    """``boundary`` for a reading dictated in a field unit."""
    return boundary(to_pressure_unit(value, unit), limit)


def within(value: float, unit: str | None, limit: SensorLimit | None) -> bool:
    return violation(value, unit, limit) is None
