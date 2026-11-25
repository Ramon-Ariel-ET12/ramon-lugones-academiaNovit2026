"""Recurring-fault history over the plant's own free-text orders (Entrega 2)."""

from __future__ import annotations

from app.analysis.analyzer import apply_history
from app.analysis.causes import rank_causes, tasks_for
from app.analysis.history import recurring_findings
from app.analysis.models import Symptom


def order(order_id: str, equipment: str, tasks: list[str], aviso: str = "", trabajo: str = "",
          fecha: str = "2026-01-10T08:00:00-03:00") -> dict:
    return {"id": order_id, "equipo": equipment, "tareas": tasks, "aviso": aviso,
            "trabajo_realizado": trabajo, "fecha_aviso": fecha}


def patterns(findings) -> list[str]:
    return [finding.pattern for finding in findings]


# ------------------------------------------------------------------ the five cases


def test_vibration_that_survived_the_valves_points_at_the_coupling():
    orders = [
        order("OT-1", "B-101", ["T-B-VAL"], aviso="B1 vib 6,3 en aumento, cambiar valvulas",
              trabajo="CBIO DE VALVULAS KIT COMPLETO. VIBRACION BAJO UN POCO (6,0) PERO NO SE FUE",
              fecha="2025-06-01T08:00:00-03:00"),
        order("OT-2", "B-101", ["T-B-ALI"], aviso="otra vez vibra la uno 5,9 sin golpeteo, acople caliente",
              trabajo="otra vez el acople de la 1. desalineado 0,28", fecha="2025-09-01T08:00:00-03:00"),
    ]
    findings = recurring_findings("B-101", orders)
    assert "valvulas_repetidas" in patterns(findings)
    finding = next(f for f in findings if f.pattern == "valvulas_repetidas")
    assert finding.suggested_cause.startswith("acople")
    assert finding.suggested_task == "T-B-ALI"
    assert set(finding.order_ids) == {"OT-1", "OT-2"}


def test_packing_that_lasts_weeks_points_at_a_scored_plunger():
    orders = [
        order("OT-3", "B-103", ["T-B-EMP"], aviso="la tres gotea mucho de nuevo",
              trabajo="cbio de empaquetadura B3. embolo 2 con rayitas finas, se pulio con tela",
              fecha="2025-05-01T08:00:00-03:00"),
        order("OT-4", "B-103", ["T-B-EMP"], aviso="b3 pierde x empaquetadura, 70 gotas",
              trabajo="se cambio empaq. b3 x 4ta vez. sigue sin llegar el embolo. dura 5 semanas",
              fecha="2025-06-05T08:00:00-03:00"),
    ]
    findings = recurring_findings("B-103", orders)
    finding = next(f for f in findings if f.pattern == "empaquetadura_repetida")
    assert "émbolo rayado" in finding.suggested_cause
    assert finding.suggested_task == "NO-ESTANDAR"  # §6.3: revisar el émbolo no es tarea estándar
    assert finding.order_ids


def test_one_old_packing_job_is_not_a_pattern():
    orders = [order("OT-5", "B-103", ["T-B-EMP"], aviso="b3 gotea", trabajo="cambio empaquetadura",
                    fecha="2025-01-01T08:00:00-03:00")]
    assert recurring_findings("B-103", orders) == []


def test_valves_worn_in_two_pumps_in_days_blame_the_filter():
    orders = [
        order("OT-6", "B-101", ["T-B-VAL"], aviso="golpeteo en cabezal", trabajo="valvulas gastadas",
              fecha="2026-01-10T08:00:00-03:00"),
        order("OT-7", "B-102", ["T-B-VAL"], aviso="la tres golpea",
              trabajo="valvulas gastadas c/ arena. 2da bomba en 10 dias", fecha="2026-01-18T08:00:00-03:00"),
    ]
    findings = recurring_findings("B-101", orders)
    finding = next(f for f in findings if f.pattern == "valvulas_en_dos_bombas")
    assert "cartucho roto" in finding.suggested_cause
    assert finding.suggested_task == "T-F-CAR"
    assert "OT-7" in finding.order_ids


def test_a_pump_that_cavitated_before_blames_the_suction():
    orders = [
        order("OT-8", "B-102", ["I-VAL"], aviso="la dos hace ruido a piedras, succion 0,8",
              trabajo="valvulas ok. el problema era el fa tapado (dif 2,3)", fecha="2025-11-01T08:00:00-03:00"),
        order("OT-9", "F-201A", ["T-F-CAR"], aviso="B2 cavita (ruido piedras) succ 0,9",
              trabajo="no tocar la bomba: es el FA de nuevo", fecha="2026-02-01T08:00:00-03:00"),
    ]
    findings = recurring_findings("B-102", orders)
    finding = next(f for f in findings if f.pattern == "cavitacion_filtro")
    assert "filtro" in finding.suggested_cause
    assert "OT-9" in finding.order_ids


def test_oil_that_keeps_going_missing_points_at_the_pinion_seal():
    orders = [
        order("OT-10", "B-102", ["T-B-ACE"], aviso="B2 aceite bajo otra vez",
              trabajo="se repusieron 9 lts. pierde x el reten del piñon, mancha en el piso",
              fecha="2025-10-01T08:00:00-03:00"),
        order("OT-11", "B-102", ["T-B-ACE"], aviso="B2 aceite bajo otra vez",
              trabajo="8 lts otra vez en 3 semanas. pedir reten tx-ret-pin", fecha="2025-10-20T08:00:00-03:00"),
    ]
    findings = recurring_findings("B-102", orders)
    finding = next(f for f in findings if f.pattern == "consumo_aceite")
    assert "retén" in finding.suggested_cause
    assert finding.suggested_task == "NO-ESTANDAR"


# ------------------------------------------------------------------ real corpus


def real_orders(plant_dir) -> list[dict]:
    import json

    return json.loads((plant_dir / "datos/documentos/historial/ordenes.json").read_text(encoding="utf-8"))


def test_the_real_archive_produces_the_five_documented_cases(plant_dir):
    """The archive shipped with the plant is the best fixture there is."""
    orders = real_orders(plant_dir)
    assert len(orders) > 200
    by_equipment = {equipment: recurring_findings(equipment, orders) for equipment in ("B-101", "B-102", "B-103")}
    assert all(by_equipment.values()), "el archivo real tiene patrones y ninguno se detectó"
    detected = {(equipment, pattern) for equipment, findings in by_equipment.items()
                for pattern in patterns(findings)}
    assert {("B-101", "valvulas_repetidas"), ("B-103", "empaquetadura_repetida"),
            ("B-102", "valvulas_en_dos_bombas"), ("B-102", "cavitacion_filtro"),
            ("B-102", "consumo_aceite")} <= detected
    for findings in by_equipment.values():
        for finding in findings:
            assert finding.order_ids, "un hallazgo sin órdenes de respaldo no es un hallazgo"
            assert all(isinstance(order_id, str) and order_id for order_id in finding.order_ids)


# ------------------------------------------------- the history changes cause and action


def vibration() -> list[Symptom]:
    return [Symptom(name="vibracion_alta", detail="la bomba vibra 6,3 en aumento")]


def test_the_coupling_history_promotes_the_coupling_and_changes_the_action(plant_dir, materials):
    findings = recurring_findings("B-101", real_orders(plant_dir))
    causes = rank_causes("B-101", vibration())
    assert tasks_for(causes, "B-101", materials) == ["I-VIB"]
    causes = apply_history(causes, findings)
    assert causes[0].code == "F06" and causes[0].confidence == "alta"
    assert causes[0].citation == "MBP-4 §7.1"
    assert tasks_for(causes, "B-101", materials) == ["T-B-ALI"]


def test_the_history_does_not_displace_a_bearing_that_the_evidence_supports(plant_dir, materials):
    findings = recurring_findings("B-101", real_orders(plant_dir))
    symptoms = [*vibration(), Symptom(name="temperatura_aceite_alta", detail="aceite a 84 °C y subiendo")]
    causes = rank_causes("B-101", symptoms)
    causes = apply_history(causes, findings)
    assert causes[0].code == "F03"
    assert "F06" not in {cause.code for cause in causes}
    assert tasks_for(causes, "B-101", materials) == ["T-B-ROD"]


def test_repeated_packing_turns_the_action_into_the_non_standard_plunger_check(plant_dir, materials):
    findings = recurring_findings("B-103", real_orders(plant_dir))
    symptoms = [Symptom(name="goteo", detail="pierde agua por la empaquetadura, 70 gotas/min")]
    causes = apply_history(rank_causes("B-103", symptoms), findings)
    assert causes[0].citation == "MBP-4 §6.3"
    assert tasks_for(causes, "B-103", materials) == ["NO-ESTANDAR"]


def test_valves_in_two_pumps_add_the_upstream_cause_without_losing_the_pump_repair(plant_dir, materials):
    findings = recurring_findings("B-102", real_orders(plant_dir))
    trend = {"presion_descarga": {"osc": 1.8, "n": 12, "min": 108, "max": 114, "last": 110, "mean": 111}}
    causes = apply_history(rank_causes("B-102", vibration(), trend), findings)
    assert [cause.code for cause in causes[:2]] == ["F02", "F08"]
    assert causes[1].root_equipment == "F-201B"
    assert tasks_for(causes, "B-102", materials) == ["T-B-VAL"]


def test_cavitation_names_the_primary_filter_as_the_root(plant_dir, materials):
    findings = recurring_findings("B-102", real_orders(plant_dir))
    symptoms = [*vibration(), Symptom(name="presion_succion_baja", detail="succión 0,8 kg/cm2")]
    causes = apply_history(rank_causes("B-102", symptoms), findings)
    assert causes[0].code == "F09"
    upstream = next(cause for cause in causes if cause.code == "F07")
    assert upstream.root_equipment == "F-201A"
    assert tasks_for(causes, "B-102", materials) == ["I-VIB"]


def test_repeated_oil_loss_blames_the_pinion_seal(plant_dir, materials):
    findings = recurring_findings("B-102", real_orders(plant_dir))
    causes = apply_history(rank_causes("B-102", [Symptom(name="aceite_bajo", detail="visor bajo")]), findings)
    assert causes[0].title.startswith("Retén del piñón")
    assert causes[0].citation == "MBP-4 §6.6"
    assert tasks_for(causes, "B-102", materials) == ["NO-ESTANDAR"]


def test_every_citation_the_history_adds_exists_and_is_current(plant_dir):
    from app.analysis.review import CorpusCitations

    citations = CorpusCitations.bundled(plant_dir / "datos" / "documentos" / "fragmentos.jsonl")
    findings = [finding for equipment in ("B-101", "B-102", "B-103")
                for finding in recurring_findings(equipment, real_orders(plant_dir))]
    assert findings
    for finding in findings:
        if finding.suggested_citation:
            assert citations.knows(finding.suggested_citation), finding.suggested_citation
            assert citations.is_current(finding.suggested_citation), finding.suggested_citation
