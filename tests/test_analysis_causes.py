"""Symptoms and ranked causes (Entrega 2).

The citations asserted here are the real ones from the course corpus, so a renamed
section breaks the test instead of the reviewer.
"""

from __future__ import annotations

import json

from app.analysis.causes import rank_causes, tasks_for
from app.analysis.models import Symptom
from app.analysis.signatures import detect_symptoms, part_is_normal
from app.domain.models import ExtractedRow


def citations_in_corpus(corpus_path) -> set[str]:
    rows = [json.loads(line) for line in corpus_path.read_text(encoding="utf-8").splitlines() if line.strip()]
    return {row["id"] for row in rows}


def row(variable: str, value: float | None = None, unit: str | None = None, tag: str = "B-101",
        observation: str | None = None) -> ExtractedRow:
    return ExtractedRow(tag=tag, variable=variable, value=value, unit=unit, observation=observation)


def codes(causes) -> list[str | None]:
    return [cause.code for cause in causes]


# ------------------------------------------------------------------ symptoms


def test_a_photographed_leak_is_a_symptom(snapshot):
    symptoms = detect_symptoms("B-101", [row("goteo_empaquetadura", observation="pérdida importante")],
                               None, None, snapshot)
    assert [s.name for s in symptoms] == ["goteo"]
    assert symptoms[0].source == "parte"


def test_bearing_temperature_uses_the_plant_threshold(snapshot):
    hot = detect_symptoms("B-101", [row("temperatura_rodamiento_ir", 81.0, "degC")], None, None, snapshot)
    cool = detect_symptoms("B-101", [row("temperatura_rodamiento_ir", 60.0, "degC")], None, None, snapshot)
    assert [s.name for s in hot] == ["temperatura_aceite_alta"]
    assert cool == []


def test_a_differential_out_of_band_in_either_direction(snapshot):
    high = detect_symptoms("F-201A", [row("presion_diferencial", 3.5, "kg/cm2", tag="F-201A")], None, None, snapshot)
    low = detect_symptoms("F-201A", [row("presion_diferencial", 0.1, "kg/cm2", tag="F-201A")], None, None, snapshot)
    assert [s.name for s in high] == ["diferencial_alto"]
    assert [s.name for s in low] == ["diferencial_bajo"]


def test_the_historian_adds_the_number_the_part_does_not_have(snapshot):
    trend = {"vibracion": {"n": 30, "min": 3.0, "max": 9.4, "last": 8.8, "unit": "mm/s"}}
    symptoms = detect_symptoms("B-101", [], "vibracion", trend, snapshot)
    assert [s.name for s in symptoms] == ["vibracion_alta"]
    assert "9.4" in symptoms[0].detail and symptoms[0].source == "sensor"


def test_a_sensor_deviation_without_a_trend_is_still_evidence(snapshot):
    symptoms = detect_symptoms("B-102", [], "vibracion", None, snapshot)
    assert [s.name for s in symptoms] == ["vibracion_alta"]
    assert symptoms[0].value is None


def test_a_normal_part_observation_is_the_f10_signal():
    assert part_is_normal([row("estado", observation="sin novedad")]) is True
    assert part_is_normal([row("estado", observation="parada")]) is False


# ------------------------------------------------------------------ causes


def test_a_leak_ranks_f01_first_with_its_citation(materials):
    causes = rank_causes("B-101", [Symptom(name="goteo", tag="B-101", detail="goteo en el prensaestopas")])
    assert causes[0].code == "F01"
    assert causes[0].citation == "MBP-4 §6.3"
    assert causes[0].task_code == "T-B-EMP"
    assert tasks_for(causes, "B-101", materials) == ["T-B-EMP"]


def test_pulsating_vibration_points_at_the_valves(materials):
    causes = rank_causes("B-102", [
        Symptom(name="vibracion_alta", detail="golpeteo metálico, la aguja oscila"),
        Symptom(name="caudal_bajo", detail="caudal en baja")])
    assert causes[0].code == "F02"
    assert causes[0].citation == "MBP-4 §6.4"
    assert tasks_for(causes, "B-102", materials) == ["T-B-VAL"]


def test_vibration_with_rising_oil_temperature_points_at_the_bearing(materials):
    causes = rank_causes("B-101", [
        Symptom(name="vibracion_alta", detail="vibración 8,4 mm/s"),
        Symptom(name="temperatura_aceite_alta", detail="aceite a 78 °C")])
    assert causes[0].code == "F03"
    assert causes[0].task_code == "T-B-ROD"
    assert causes[0].stops_equipment is True
    assert tasks_for(causes, "B-101", materials) == ["T-B-ROD"]


def test_low_suction_puts_the_root_cause_in_another_equipment(materials):
    causes = rank_causes("B-103", [
        Symptom(name="vibracion_alta", detail="ruido a piedras"),
        Symptom(name="presion_succion_baja", detail="succión 0,4 kg/cm2")])
    cavitation = next(cause for cause in causes if cause.code == "F09")
    assert cavitation.root_equipment == "F-201A"
    assert cavitation.citation == "MBP-4 §6.11"
    assert "T-B-ROD" not in tasks_for(causes, "B-103", materials)


def test_a_high_differential_is_a_filter_cartridge(materials):
    causes = rank_causes("F-201B", [Symptom(name="diferencial_alto", tag="F-201B", detail="ΔP 3,4")])
    assert causes[0].code == "F07"
    assert tasks_for(causes, "F-201B", materials) == ["T-F-CAR"]


def test_a_broken_cartridge_shows_a_collapsing_differential(materials):
    causes = rank_causes("F-201A", [Symptom(name="diferencial_bajo", tag="F-201A", detail="ΔP 0,1")])
    assert causes[0].code == "F08"
    assert tasks_for(causes, "F-201A", materials) == ["T-F-CAR"]


def test_thin_evidence_asks_for_an_inspection(materials):
    causes = rank_causes("B-101", [Symptom(name="vibracion_alta", detail="vibración moderada")])
    assert tasks_for(causes, "B-101", materials) == ["I-VIB"]
    assert all(cause.citation for cause in causes)


def test_an_oscillating_discharge_gauge_is_the_f02_signature(materials):
    """The plant's own F02: vibration high and the discharge pressure swings."""
    symptoms = [Symptom(name="vibracion_alta", detail="vibración 8,1 mm/s")]
    trend = {"vibracion": {"n": 40, "min": 3.0, "max": 8.4, "last": 8.1, "osc": 0.2, "unit": "mm/s"},
             # The gauge swings ~2,7 psi at every sample: that is a pulsation.
             "presion_descarga": {"n": 40, "min": 156.0, "max": 163.0, "last": 159.0, "osc": 2.7,
                                  "unit": "psi"}}
    causes = rank_causes("B-102", symptoms, trend)
    assert causes[0].code == "F02"
    assert tasks_for(causes, "B-102", materials) == ["T-B-VAL"]


def test_a_steady_discharge_with_vibration_is_not_f02(materials):
    symptoms = [Symptom(name="vibracion_alta", detail="vibración 8,1 mm/s")]
    # A slow level change moves the range but not the step between samples.
    trend = {"presion_descarga": {"n": 40, "min": 156.0, "max": 163.0, "last": 159.4, "osc": 0.18,
                                  "unit": "psi"}}
    causes = rank_causes("B-102", symptoms, trend)
    assert causes[0].code != "F02"


def test_a_drifting_sensor_does_not_produce_a_work_order(materials):
    causes = [cause for cause in rank_causes(
        "B-101", [Symptom(name="vibracion_alta", detail="sensor plano")]) if cause.code == "F10"]
    assert causes == [] or tasks_for(causes, "B-101", materials) == []


def test_every_citation_the_engine_uses_exists_in_the_corpus(corpus_path):
    known = citations_in_corpus(corpus_path)
    from app.analysis.causes import CITATION_OF, DIFFERENTIAL_CITATION

    for citation in list(CITATION_OF.values()) + list(DIFFERENTIAL_CITATION.values()):
        assert citation in known, f"{citation} no existe en el corpus"


def test_rising_oil_temperature_is_a_symptom_even_below_the_alarm(snapshot):
    """§6.2: F03 shows up as an oil temperature that climbs, alarm or not."""
    trend = {"temperatura_aceite": {"n": 40, "min": 58.0, "max": 70.0, "last": 69.0, "osc": 0.2,
                                    "unit": "degC"}}
    symptoms = detect_symptoms("B-101", [], "vibracion", trend, snapshot)
    assert "temperatura_aceite_alta" in [symptom.name for symptom in symptoms]


def test_a_flat_oil_temperature_is_not_a_symptom(snapshot):
    trend = {"temperatura_aceite": {"n": 40, "min": 60.0, "max": 61.0, "last": 60.5, "osc": 0.1,
                                    "unit": "degC"}}
    assert detect_symptoms("B-101", [], None, trend, snapshot) == []


def test_vibration_with_rising_oil_ranks_the_bearing_first(materials):
    symptoms = [Symptom(name="vibracion_alta", detail="vibración 7,8 mm/s"),
                Symptom(name="temperatura_aceite_alta", detail="el aceite subió 12 °C")]
    causes = rank_causes("B-101", symptoms, {"presion_descarga": {"n": 40, "osc": 0.2}})
    assert causes[0].code == "F03"
    assert tasks_for(causes, "B-101", materials) == ["T-B-ROD"]


def test_a_escalation_outside_the_window_still_produces_evidence(snapshot):
    """The detector escalated: the deviation existed even if the 6h window no longer shows it."""
    cool_trend = {"presion_diferencial": {"n": 40, "min": 0.2, "max": 0.4, "last": 0.3, "osc": 0.01,
                                          "unit": "kg/cm2"}}
    symptoms = detect_symptoms("F-201B", [], "presion_diferencial", cool_trend, snapshot)
    assert [symptom.name for symptom in symptoms] == ["diferencial_alto"]
    assert symptoms[0].source == "sensor"
    causes = rank_causes("F-201B", symptoms, cool_trend)
    assert causes[0].code == "F07"
