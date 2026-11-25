"""The CT-SVP-2025 price list, read from the document (Entrega 2)."""

from __future__ import annotations

import pytest

from app.domain.billing import ITEM_OF_TASK, PriceList

CONTRACT_DOC = "datos/documentos/contrato/CT-SVP-2025.md"
CORPUS_DOC = "datos/documentos/fragmentos.jsonl"


@pytest.fixture(scope="module")
def prices(plant_dir) -> PriceList:
    return PriceList.from_markdown((plant_dir / CONTRACT_DOC).read_text(encoding="utf-8"))


def test_the_seven_items_are_read(prices):
    assert len(prices) == 7
    assert prices.items["SVP-01"].price_usd == 1150.0
    assert prices.items["SVP-03"].price_usd == 320.0
    assert prices.items["SVP-03"].per_equipment is True
    assert prices.items["SVP-01"].hours_included == 16.0


def test_the_corpus_chunks_produce_the_same_table(prices, plant_dir):
    import json

    chunks = [json.loads(line)
              for line in (plant_dir / CORPUS_DOC).read_text(encoding="utf-8").splitlines() if line.strip()]
    from_chunks = PriceList.from_chunks([{"doc": "CT-SVP-2025", "text": chunk["texto"]}
                                        for chunk in chunks if chunk["doc"] == "CT-SVP-2025"])
    assert {code: item.price_usd for code, item in from_chunks.items.items()} == \
           {code: item.price_usd for code, item in prices.items.items()}


def test_closed_prices_are_per_order_and_i_vib_per_equipment(prices):
    assert prices.amount_for(["T-B-ROD"]) == 1150.0
    assert prices.amount_for(["T-B-ALI"]) == 780.0
    assert prices.amount_for(["I-VIB"], equipment_count=3) == 960.0
    assert prices.amount_for(["I-VIB"], equipment_count=1) == 320.0


def test_hours_included_scale_with_the_equipment_count(prices):
    assert prices.hours_included(["T-B-ROD"]) == 16.0
    assert prices.hours_included(["I-VIB"], equipment_count=3) == 3.0


def test_a_work_from_2024_has_no_price_in_the_current_list(prices):
    assert prices.amount_for(["T-B-ROD"], started_at="2024-11-21T16:30-03:00") is None
    assert prices.amount_for(["T-B-ROD"], started_at="2025-01-02T10:00:00-03:00") == 1150.0


def test_an_unknown_task_has_no_contract_price(prices):
    assert prices.amount_for(["T-B-EMP"]) is None
    assert prices.amount_for([]) is None


def test_the_task_to_item_map_is_the_contract_annex(prices):
    assert ITEM_OF_TASK == {"T-B-ROD": "SVP-01", "T-B-ALI": "SVP-02", "I-VIB": "SVP-03"}
    assert set(ITEM_OF_TASK.values()) <= set(prices.items)
