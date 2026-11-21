"""Sensor and field signatures: what the evidence actually says.

The plant gives us two kinds of evidence for the same failure: what the operator said in
the part and what the historian recorded. A symptom only exists when one of the two shows
a number or an explicit observation, because the cause ranking must be able to point at
it ("vibración 8.4 mm/s" is evidence; "vibra" alone is not).
"""

from __future__ import annotations

from app.analysis.models import Symptom, SymptomName
from app.domain.limits import violation
from app.domain.models import ExtractedRow, PlantSnapshot
from app.domain.vocabulary import HOT_BEARING_DEGC, normalise

# Sensor variable -> the symptom it produces when it leaves its band.
SENSOR_SYMPTOMS: dict[str, SymptomName] = {
    "vibracion": "vibracion_alta",
    "temperatura_aceite": "temperatura_aceite_alta",
    "presion_succion": "presion_succion_baja",
}

NORMAL_WORDS = ("sin novedad", "normal", "no vibra", "no hay ruido", "estable")
# Degrees the oil must climb inside the window to be F03/F04 evidence (§6.2 "en aumento").
OIL_TEMPERATURE_RISE = 8.0


def _row_symptoms(row: ExtractedRow, snapshot: PlantSnapshot) -> list[Symptom]:
    tag, text = row.tag, normalise(row.observation)
    symptoms: list[Symptom] = []
    if row.variable == "goteo_empaquetadura":
        symptoms.append(Symptom(name="goteo", tag=tag, source="parte", value=row.value, unit=row.unit,
                                detail=row.observation or "pérdida por empaquetadura informada"))
    elif row.variable == "nivel_aceite_visor":
        symptoms.append(Symptom(name="aceite_bajo", tag=tag, source="parte",
                                detail=row.observation or "nivel de aceite bajo en el visor"))
    elif row.variable == "estado_correas":
        symptoms.append(Symptom(name="correas", tag=tag, source="parte",
                                detail=row.observation or "correas en mal estado"))
    elif row.variable == "temperatura_rodamiento_ir" and row.value is not None:
        if row.value > HOT_BEARING_DEGC:
            symptoms.append(Symptom(name="temperatura_aceite_alta", tag=tag, source="parte",
                                    value=row.value, unit=row.unit or "degC",
                                    detail=f"rodamiento a {row.value:g} °C con la pistola"))
    elif row.variable == "presion_diferencial" and row.value is not None:
        side = violation(row.value, row.unit, snapshot.limit(tag, "presion_diferencial"))
        if side == "high":
            symptoms.append(Symptom(name="diferencial_alto", tag=tag, source="parte",
                                    value=row.value, unit=row.unit, detail="diferencial por encima del límite"))
        elif side == "low":
            symptoms.append(Symptom(name="diferencial_bajo", tag=tag, source="parte",
                                    value=row.value, unit=row.unit, detail="diferencial por debajo del límite"))
    elif row.variable == "presion_descarga_local" and row.value is not None:
        side = violation(row.value, row.unit, snapshot.limit(tag, "presion_descarga"))
        if side == "low":
            symptoms.append(Symptom(name="caudal_bajo", tag=tag, source="parte",
                                    value=row.value, unit=row.unit,
                                    detail="presión de descarga por debajo del límite"))
    elif row.variable == "ruido":
        symptoms.append(Symptom(name="vibracion_alta", tag=tag, source="parte",
                                detail=f"ruido informado: {row.observation or 'anormal'}"))
    elif row.variable == "estado" and text and text not in ("parada, en reserva", "parada por mantenimiento"):
        symptoms.append(Symptom(name="estado", tag=tag, source="parte", detail=row.observation or "parada"))
    return symptoms


def _trend_value(stats: dict) -> float | None:
    value = stats.get("last")
    return float(value) if value is not None else None


def _trend_symptoms(equipment: str, trend: dict[str, dict], snapshot: PlantSnapshot) -> list[Symptom]:
    symptoms: list[Symptom] = []
    for variable, stats in sorted(trend.items()):
        limit = snapshot.limit(equipment, variable)
        if limit is None:
            continue
        peak = max([v for v in (stats.get("max"), stats.get("last")) if v is not None], default=None)
        floor = min([v for v in (stats.get("min"), stats.get("last")) if v is not None], default=None)
        last = _trend_value(stats)
        unit = stats.get("unit") or limit.unit or None
        if variable == "presion_diferencial":
            if peak is not None and limit.high is not None and peak >= limit.high:
                symptoms.append(Symptom(name="diferencial_alto", tag=equipment, source="sensor",
                                        value=last, unit=unit, detail=f"diferencial máximo {peak:g} {unit or ''}".strip()))
            elif floor is not None and limit.low is not None and floor <= limit.low:
                symptoms.append(Symptom(name="diferencial_bajo", tag=equipment, source="sensor",
                                        value=last, unit=unit, detail=f"diferencial mínimo {floor:g} {unit or ''}".strip()))
            continue
        name = SENSOR_SYMPTOMS.get(variable)
        if name is None:
            continue
        high_side = limit.high is not None and peak is not None and peak >= limit.high
        low_side = limit.low is not None and floor is not None and floor <= limit.low
        if variable == "temperatura_aceite" and not (high_side or low_side):
            # §6.2: F03 and F04 show up as an oil temperature that climbs, alarm or not.
            rise = (last or 0.0) - (floor or last or 0.0)
            if rise >= OIL_TEMPERATURE_RISE:
                symptoms.append(Symptom(name="temperatura_aceite_alta", tag=equipment, source="sensor",
                                        value=last, unit=unit,
                                        detail=f"el aceite subió {rise:.1f} °C en la ventana"))
            continue
        if not (high_side or low_side):
            continue
        extreme = peak if high_side else floor
        limit_value = limit.high if high_side else limit.low
        symptoms.append(Symptom(name=name, tag=equipment, source="sensor", value=last, unit=unit,
                                detail=f"{variable} llegó a {extreme:g} {unit or ''} (límite {limit_value:g})".strip()))
    return symptoms


def detect_symptoms(equipment: str, rows: list[ExtractedRow], sensor_variable: str | None,
                    trend: dict[str, dict] | None, snapshot: PlantSnapshot) -> list[Symptom]:
    """Every abnormal fact the evidence supports, part first and historian second."""
    symptoms: list[Symptom] = []
    for row in rows:
        symptoms.extend(_row_symptoms(row, snapshot))
    if trend:
        symptoms.extend(_trend_symptoms(equipment, trend, snapshot))
    if sensor_variable and not any(symptom.source == "sensor" for symptom in symptoms):
        # The detector escalated on this sensor, so the deviation was sustained: the
        # historian window may already have moved past it (or be unavailable after a
        # restart). Trusting only the window would leave the escalation with no evidence.
        name = SENSOR_SYMPTOMS.get(sensor_variable)
        if name is not None:
            symptoms.append(Symptom(name=name, tag=equipment, source="sensor",
                                    detail=f"desvío sostenido informado por el sensor {sensor_variable}"))
        elif sensor_variable == "presion_diferencial":
            symptoms.append(Symptom(name="diferencial_alto", tag=equipment, source="sensor",
                                    detail="desvío sostenido del diferencial informado por el sensor"))
    return symptoms


def part_is_normal(rows: list[ExtractedRow]) -> bool:
    """The operator looked at the machine and saw nothing wrong (the F10 signal)."""
    if not rows:
        return False
    return any(any(word in normalise(row.observation) for word in NORMAL_WORDS) for row in rows)
