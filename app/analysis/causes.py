"""Ranked probable causes, straight from the manufacturer's tables.

The ranking follows MBP-4 §6.2 (signature matrix: what each code looks like in the
sensors and in the recorrida) and §7.x (differential tables: what distinguishes one
candidate from another). Every cause carries the citation of the section it comes from,
because the reviewer refuses an order whose citation cannot be backed.

Deterministic by design: the same evidence always produces the same order. The language
model is never asked to choose a cause — the rules of the plant do that.
"""

from __future__ import annotations

from app.analysis.models import Cause, Symptom
from app.domain.materials import Materials
from app.domain.vocabulary import normalise

# Fault code -> the task that resolves it (MBP-4 §6.1) and the manual section.
TASK_OF: dict[str, str | None] = {
    "F01": "T-B-EMP", "F02": "T-B-VAL", "F03": "T-B-ROD", "F04": "T-B-ACE",
    "F05": "T-B-COR", "F06": "T-B-ALI", "F07": "T-F-CAR", "F08": "T-F-CAR",
    "F09": None,            # the root cause is in the filter or the tank, not the pump
    "F10": None,            # a drifting sensor does not need a work order
}
CITATION_OF: dict[str, str] = {
    "F01": "MBP-4 §6.3", "F02": "MBP-4 §6.4", "F03": "MBP-4 §6.5", "F04": "MBP-4 §6.6",
    "F05": "MBP-4 §6.7", "F06": "MBP-4 §6.8", "F07": "MBP-4 §6.9", "F08": "MBP-4 §6.10",
    "F09": "MBP-4 §6.11", "F10": "MBP-4 §6.12",
}
TITLE_OF: dict[str, str] = {
    "F01": "Pérdida por empaquetadura",
    "F02": "Válvulas de succión/descarga gastadas",
    "F03": "Rodamiento de cigüeñal dañado",
    "F04": "Bajo nivel de aceite del cárter",
    "F05": "Correas flojas o gastadas",
    "F06": "Acople desalineado o elastómero gastado",
    "F07": "Cartuchos colmatados",
    "F08": "Cartucho roto (agua sin filtrar)",
    "F09": "Cavitación por baja succión",
    "F10": "Sensor congelado o con deriva",
}
DIFFERENTIAL_CITATION = {
    "vibracion_alta": "MBP-4 §7.1",
    "diferencial_alto": "MBP-4 §7.5",
    "diferencial_bajo": "MBP-4 §7.6",
    "goteo": "MBP-4 §7.7",
    "presion_succion_baja": "MBP-4 §7.4",
}
STOPPING = {"F01", "F02", "F03", "F05", "F06"}


def _has(symptoms: list[Symptom], *names: str) -> bool:
    return any(symptom.name in names for symptom in symptoms)


def _details(symptoms: list[Symptom], *names: str) -> list[str]:
    return [symptom.detail for symptom in symptoms if symptom.name in names and symptom.detail]


# F02 pulsation: the discharge gauge swings a few kg/cm2 at every sample. The plant's own
# noise is ±0,15, so a mean step of 1 kg/cm2 between consecutive samples is the fault. The
# window range is deliberately NOT used: a slow level change looks exactly the same.
PULSATION_STEP = 1.0
PULSATION_MIN_SAMPLES = 5
# F03/F04: the oil temperature rising inside the window is a signature even under the alarm.
OIL_TEMPERATURE_RISE = 8.0


def _pulsating(symptoms: list[Symptom], trend: dict[str, dict] | None) -> bool:
    """F02's signature: the discharge gauge oscillates (§6.2, §7.1).

    The oscillation is not a level, it is a spread, so it is read from the samples the
    historian returned; when the part says "golpeteo" or the needle oscillates, that is
    the same signature in words.
    """
    text = " ".join(normalise(s.detail) for s in symptoms
                    if s.name in ("vibracion_alta", "caudal_bajo"))
    if any(word in text for word in ("pulsacion", "pulsación", "oscila", "golpeteo", "golpea")):
        return True
    stats = (trend or {}).get("presion_descarga") or {}
    if int(stats.get("n") or 0) < PULSATION_MIN_SAMPLES:
        return False
    return float(stats.get("osc") or 0.0) >= PULSATION_STEP


def _cause(code: str, *, confidence: str, evidence: list[str], missing: list[str],
           equipment: str, task: str | None = None, needs_inspection: bool = False,
           root_equipment: str | None = None) -> Cause:
    return Cause(
        code=code,
        title=TITLE_OF[code],
        confidence=confidence,  # type: ignore[arg-type]
        evidence=[text for text in evidence if text],
        missing=missing,
        citation=CITATION_OF[code],
        task_code=task if task is not None else TASK_OF.get(code),
        stops_equipment=code in STOPPING,
        needs_inspection=needs_inspection,
        root_equipment=root_equipment,
    )


def _inspection(symptom_text: str, missing: list[str], citation: str, task: str = "I-VIB") -> Cause:
    return Cause(
        title=f"Causa no determinada con la evidencia disponible ({symptom_text})",
        confidence="baja",
        evidence=[symptom_text],
        missing=missing,
        citation=citation,
        task_code=task,
        stops_equipment=False,
        needs_inspection=True,
    )


def rank_causes(equipment: str, symptoms: list[Symptom], trend: dict[str, dict] | None = None,
                part_normal: bool = False) -> list[Cause]:
    """Order the probable causes. Existing citations only: the reviewer checks them."""
    causes: list[Cause] = []
    vibration = _has(symptoms, "vibracion_alta")
    hot_oil = _has(symptoms, "temperatura_aceite_alta")
    suction = _has(symptoms, "presion_succion_baja")
    drip = _has(symptoms, "goteo")
    belts = _has(symptoms, "correas")
    low_oil = _has(symptoms, "aceite_bajo")
    diff_high = _has(symptoms, "diferencial_alto")
    diff_low = _has(symptoms, "diferencial_bajo")
    low_flow = _has(symptoms, "caudal_bajo")
    state = _has(symptoms, "estado")

    # The recorrida is the strongest evidence: a photographed leak or a visible belt is
    # not a hypothesis.
    if drip:
        causes.append(_cause("F01", confidence="alta",
                             evidence=[*_details(symptoms, "goteo"), "goteo informado en la recorrida"],
                             missing=[], equipment=equipment))
    if belts:
        causes.append(_cause("F05", confidence="alta",
                             evidence=[*_details(symptoms, "correas"), "correas en mal estado en la recorrida"],
                             missing=[], equipment=equipment))
    if low_oil:
        causes.append(_cause("F04", confidence="alta",
                             evidence=[*_details(symptoms, "aceite_bajo"), "nivel bajo en el visor"],
                             missing=[], equipment=equipment))
    if hot_oil and not vibration:
        causes.append(_cause("F04", confidence="media",
                             evidence=_details(symptoms, "temperatura_aceite_alta"),
                             missing=["confirmar el nivel del visor de aceite"],
                             equipment=equipment))

    # Filters: the differential is the measurement, and §7.5/§7.6 separate high from low.
    if diff_high:
        causes.append(_cause("F07", confidence="alta",
                             evidence=_details(symptoms, "diferencial_alto"),
                             missing=[], equipment=equipment))
    if diff_low:
        causes.append(_cause("F08", confidence="alta",
                             evidence=_details(symptoms, "diferencial_bajo"),
                             missing=["verificar el manómetro local antes de cambiar cartuchos"],
                             equipment=equipment))

    # Vibration: §7.1 is the differential table. The order depends on what else is there.
    if vibration and part_normal and not (drip or belts or low_oil or hot_oil or suction):
        # The operator walked the machine and saw nothing: the sensor is the suspect (F10).
        causes.append(_cause("F10", confidence="alta",
                             evidence=[*_details(symptoms, "vibracion_alta"), "la recorrida no encontró la vibración"],
                             missing=["cruzar la lectura del sensor con el colector"],
                             equipment=equipment))
    elif vibration:
        if suction:
            causes.append(_cause("F09", confidence="media",
                                 evidence=_details(symptoms, "vibracion_alta", "presion_succion_baja"),
                                 missing=["confirmar la presión de succión en el resto de las bombas",
                                          "verificar el nivel del TK-301"],
                                 equipment=equipment, root_equipment="F-201A"))
        if hot_oil:
            causes.append(_cause("F03", confidence="alta",
                                 evidence=_details(symptoms, "vibracion_alta", "temperatura_aceite_alta"),
                                 missing=["medir la temperatura del rodamiento con la pistola"],
                                 equipment=equipment))
        elif _pulsating(symptoms, trend):
            causes.append(_cause("F02", confidence="alta",
                                 evidence=[*_details(symptoms, "vibracion_alta", "caudal_bajo"), "la presión de descarga oscila"],
                                 missing=["confirmar la pulsación con el manómetro local"],
                                 equipment=equipment))
        else:
            causes.append(_cause("F06", confidence="baja",
                                 evidence=_details(symptoms, "vibracion_alta"),
                                 missing=["verificar el acople y el elastómero con la guarda abierta"],
                                 equipment=equipment))
            causes.append(_cause("F03", confidence="baja",
                                 evidence=_details(symptoms, "vibracion_alta"),
                                 missing=["seguir la tendencia de vibración y la temperatura de aceite"],
                                 equipment=equipment))

    # Low suction with no vibration: §7.4. All pumps low points at the filter, one pump
    # at its suction valve; without the rest of the plant, it is an inspection.
    if suction and not vibration:
        causes.append(_cause("F07", confidence="media",
                             evidence=_details(symptoms, "presion_succion_baja"),
                             missing=["comparar la succión de las tres bombas y el ΔP del filtro"],
                             equipment=equipment))

    if state:
        causes.append(_inspection("equipo parado o disparado",
                                  ["revisar la protección y las válvulas antes de arrancar"],
                                  citation="MBP-4 §6.2", task="I-VAL"))
    if low_flow and not (vibration or drip or belts):
        causes.append(_inspection("caudal bajo sin otra firma",
                                  ["medir caudal, succión y descarga con el colector"],
                                  citation="MBP-4 §7.3"))

    # A part that says "normal" against a sensor that says otherwise is the F10 signature
    # (§6.12). It never justifies a work order, but it must be said out loud.
    if vibration and not causes:
        causes.append(_cause("F10", confidence="baja",
                             evidence=_details(symptoms, "vibracion_alta"),
                             missing=["cruzar la lectura del sensor con la recorrida"],
                             equipment=equipment))

    if not causes and symptoms:
        cited = DIFFERENTIAL_CITATION.get(symptoms[0].name, "MBP-4 §6.2")
        causes.append(_inspection(symptoms[0].detail or symptoms[0].name,
                                  ["volver a recorrer el equipo y medir con el colector"], cited))
    return causes


def tasks_for(causes: list[Cause], equipment: str, materials: Materials) -> list[str]:
    """The task of the leading cause, or an inspection when the evidence is thin.

    One order asks for one thing: a repair only when the top cause is identified with
    high confidence, an inspection otherwise (the Anexo: if the evidence does not reach
    a cause, the recommended action is an inspection). A drifting sensor does not demand
    a work order at all.
    """
    if not causes:
        return []
    top = causes[0]
    if top.code == "F10" and not top.needs_inspection:
        return []
    repair = top.task_code if top.confidence == "alta" else None
    task = repair or (top.task_code if top.needs_inspection else None) or "I-VIB"
    # Only codes the catalogue actually has: an invented code would make the order lie.
    return [task] if materials.task(task, equipment) is not None else []
