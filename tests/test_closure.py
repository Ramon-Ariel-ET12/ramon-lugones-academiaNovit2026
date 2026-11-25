"""Closure comparison and certification amount, checked against the course examples.

`cierres_ejemplo.json` is the acceptance fixture: twelve real closures of the
contractor, some with differences and some clean. It is the only honest way to know
whether the amount comes from the order and the contract instead of from what the
technician declared.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.domain.billing import PriceList
from app.domain.materials import load_materials
from app.processing.closure import compare, parse_closure

CONTRACT_DOC = "datos/documentos/contrato/CT-SVP-2025.md"
EXAMPLES_DOC = "datos/documentos/contrato/cierres_ejemplo.json"


@pytest.fixture(scope="module")
def materials():
    return load_materials(Path(__file__).resolve().parent.parent / "datos" / "materiales.yaml")


@pytest.fixture(scope="module")
def prices(plant_dir):
    return PriceList.from_markdown((plant_dir / CONTRACT_DOC).read_text(encoding="utf-8"))


@pytest.fixture(scope="module")
def examples(plant_dir):
    return json.loads((plant_dir / EXAMPLES_DOC).read_text(encoding="utf-8"))


def order_of(example: dict) -> dict:
    return {"id": example["orden_id"], "equipo": example["equipo"], "tareas": example["tareas"],
            "repuestos": example["repuestos_orden"], "ts": example["fecha_inicio"]}


def equipment_count(example: dict) -> int:
    return 3 if example["tareas"] == ["I-VIB"] else 1


def run(example: dict, materials, prices):
    closure = parse_closure(example["cierre_texto"], orden_id=example["orden_id"],
                            tecnico=example["tecnico"], empresa="Servipat", materials=materials)
    return compare(order_of(example), closure, materials, prices,
                   equipment_count=equipment_count(example), started_at=example["fecha_inicio"],
                   declared_amount=example["monto_declarado_usd"])


def compare_order(order: dict, example: dict, materials, prices, *, text: str | None = None,
                  declared_amount: float | None = None):
    """The closure of the example against an order that may have been modified."""
    closure = parse_closure(text or example["cierre_texto"], orden_id=example["orden_id"],
                            tecnico=example["tecnico"], empresa="Servipat", materials=materials)
    return compare(order, closure, materials, prices, equipment_count=equipment_count(example),
                   started_at=example["fecha_inicio"], declared_amount=declared_amount)


def test_the_examples_are_the_real_fixture(examples):
    assert len(examples) == 12
    assert {"Observada", "Certificada"} <= {example["estado"] for example in examples}


def test_every_closure_parses_the_three_facts(materials, examples):
    for example in examples:
        closure = parse_closure(example["cierre_texto"], orden_id=example["orden_id"], materials=materials)
        assert closure.tasks_done == example["tareas"], example["orden_id"]
        assert closure.hours == pytest.approx(example["horas_declaradas"]), example["orden_id"]
        assert closure.test_result, example["orden_id"]
        assert [part["codigo"] for part in closure.parts_used] == [part["codigo"]
                                                                  for part in example["repuestos_declarados"]]


def test_a_clean_closure_has_no_differences(materials, prices, examples):
    for example in examples:
        result = run(example, materials, prices)
        if example["estado"] == "Certificada":
            assert result.differences == [], (example["orden_id"], [d.detail for d in result.differences])


def expected_kind(example: dict) -> str:
    """Which difference the fixture documents, derived from its own data (not its prose)."""
    ordered = {part["codigo"]: part["cantidad"] for part in example["repuestos_orden"]}
    declared = {part["codigo"]: part["cantidad"] for part in example["repuestos_declarados"]}
    if set(declared) - set(ordered):
        return "repuesto_extra"
    if any(declared[code] > ordered[code] for code in declared):
        return "cantidad"
    if example["horas_declaradas"] > example["horas_registro_ingreso"]:
        return "horas"
    return "precio"


def test_every_observed_closure_reports_its_difference(materials, prices, examples):
    for example in examples:
        result = run(example, materials, prices)
        if example["estado"] != "Observada":
            continue
        kinds = {difference.kind for difference in result.differences}
        assert kinds, example["orden_id"]
        assert expected_kind(example) in kinds, (example["orden_id"], kinds, example["diferencias"])


def test_the_certified_amount_comes_from_the_contract(materials, prices, examples):
    for example in examples:
        result = run(example, materials, prices)
        if example["lista_aplicada"] == "CT-SVP-2025":
            assert result.monto_habilita_usd == pytest.approx(example["monto_habilita_usd"]), example["orden_id"]


def test_a_work_started_before_2025_cannot_be_priced_with_the_current_contract(materials, prices, examples):
    old = next(example for example in examples if example["lista_aplicada"] == "CT-SVP-2022")
    result = run(old, materials, prices)
    assert result.monto_habilita_usd is None
    assert any("CT-SVP-2022" in difference.detail for difference in result.differences)


def test_a_clean_closure_from_2024_still_flags_the_old_list(materials, prices, examples):
    """OT-24-0010 is 2024 and its declared amount is the ONLY reason it is observed."""
    example = next(item for item in examples if item["orden_id"] == "OT-24-0010")
    result = run(example, materials, prices)
    assert [difference.kind for difference in result.differences] == ["precio"]


def test_the_extra_part_is_not_paid(materials, prices, examples):
    example = next(item for item in examples if item["orden_id"] == "OT-25-0004")
    result = run(example, materials, prices)
    assert "repuesto_extra" in {difference.kind for difference in result.differences}
    assert result.monto_habilita_usd == pytest.approx(960.0)


def test_double_the_authorised_part_is_a_quantity_difference(materials, prices, examples):
    example = next(item for item in examples if item["orden_id"] == "OT-25-0026")
    result = run(example, materials, prices)
    assert "cantidad" in {difference.kind for difference in result.differences}
    assert result.monto_habilita_usd == pytest.approx(780.0)


def test_more_hours_than_the_closed_price_includes(materials, prices, examples):
    example = next(item for item in examples if item["orden_id"] == "OT-26-0032")
    result = run(example, materials, prices)
    assert "horas" in {difference.kind for difference in result.differences}


def test_a_missing_proof_is_a_difference(materials, prices):
    closure = parse_closure("Cierro la orden OT 25 0001. Hice análisis de vibraciones con colector.",
                            orden_id="OT-1", materials=materials)
    result = compare({"tareas": ["I-VIB"], "repuestos": [], "ts": "2026-01-01"}, closure, materials, prices,
                     equipment_count=3)
    assert "prueba" in {difference.kind for difference in result.differences}


def test_the_price_list_comes_from_the_repository_texts(materials, prices, plant_dir):
    """The production path: rag_texts rows -> PriceList (the query must carry `doc`)."""
    rows = [{"doc": "CT-SVP-2025", "citation": "CT-SVP-2025 §2.1", "section_key": "precios",
             "text": (plant_dir / CONTRACT_DOC).read_text(encoding="utf-8")}]
    from_rows = PriceList.from_chunks(rows)
    assert len(from_rows) == len(prices)
    assert from_rows.amount_for(["I-VIB"], equipment_count=3) == 960.0
    # A row without `doc` is accepted too (a caller that already filtered the document).
    assert len(PriceList.from_chunks([{"text": rows[0]["text"]}])) == len(prices)


# ------------------------------------------------- los tres tipos que faltaban


def test_a_closure_without_declared_hours_has_no_hours_difference(materials, prices, examples):
    """Current behaviour: without declared hours there is no hours difference to mark."""
    example = next(item for item in examples if item["orden_id"] == "OT-25-0046")
    text = example["cierre_texto"].split("Fueron")[0].strip()
    closure = parse_closure(text, orden_id=example["orden_id"], materials=materials)
    result = compare_order(order_of(example), example, materials, prices, text=text,
                           declared_amount=example["monto_declarado_usd"])
    assert closure.hours is None
    assert result.differences == []
    assert result.monto_habilita_usd == pytest.approx(960.0)


def test_a_task_the_order_asked_and_the_closure_forgot_is_missing(materials, prices, examples):
    example = next(item for item in examples if item["orden_id"] == "OT-25-0046")
    order = {**order_of(example), "tareas": ["I-VIB", "T-B-EMP"]}
    result = compare_order(order, example, materials, prices,
                           declared_amount=example["monto_declarado_usd"])
    assert [difference.kind for difference in result.differences] == ["tarea_faltante"]
    assert "T-B-EMP" in result.differences[0].detail
    assert result.monto_habilita_usd == pytest.approx(960.0)  # T-B-EMP has no contract item


def test_a_task_the_order_did_not_ask_is_extra(materials, prices, examples):
    """OT-25-0119 closes a laser alignment (T-B-ALI) with its elastomer."""
    example = next(item for item in examples if item["orden_id"] == "OT-25-0119")
    order = {"id": example["orden_id"], "equipo": example["equipo"], "tareas": ["T-B-ROD"],
             "repuestos": [{"codigo": "ACO-ELAST-90", "cantidad": 1}], "ts": example["fecha_inicio"]}
    result = compare_order(order, example, materials, prices)
    kinds = {difference.kind for difference in result.differences}
    assert kinds == {"tarea_faltante", "tarea_extra"}
    extra = next(difference for difference in result.differences if difference.kind == "tarea_extra")
    assert "T-B-ALI" in extra.detail


def test_a_reserved_part_the_closure_does_not_use_is_missing(materials, prices, examples):
    example = next(item for item in examples if item["orden_id"] == "OT-25-0046")
    order = {**order_of(example), "repuestos": [{"codigo": "TX-SELLO-CAR", "cantidad": 1}]}
    result = compare_order(order, example, materials, prices,
                           declared_amount=example["monto_declarado_usd"])
    assert [difference.kind for difference in result.differences] == ["repuesto_faltante"]
    assert "TX-SELLO-CAR" in result.differences[0].detail
    assert result.monto_habilita_usd == pytest.approx(960.0)
