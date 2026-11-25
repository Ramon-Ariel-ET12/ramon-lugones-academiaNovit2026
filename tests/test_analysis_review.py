"""The reviewer step: citations and spare parts (Entrega 2)."""

from __future__ import annotations

import pytest

from app.analysis.models import Cause
from app.analysis.review import CorpusCitations, citations_of, review


@pytest.fixture(scope="module")
def citations(corpus_path):
    return CorpusCitations.bundled(corpus_path)


def cause(title: str = "Válvulas gastadas", citation: str | None = "MBP-4 §6.4") -> Cause:
    return Cause(code="F02", title=title, citation=citation, task_code="T-B-VAL", stops_equipment=True)


def test_a_clean_analysis_passes(materials, citations):
    findings = review("B-101", [cause()], [{"codigo": "TX-VAL-KIT", "cantidad": 1}],
                      materials, citations)
    assert findings == []


def test_an_invented_citation_blocks(materials, citations):
    findings = review("B-101", [cause(citation="MBP-9 §1.1")], [], materials,
                      citations)
    assert [f.kind for f in findings] == ["citation_missing"]
    assert "MBP-9 §1.1" in findings[0].detail


def test_a_superseded_manual_blocks(materials, citations):
    """TX350-C is the expired revision; TX350-D is the current one, same section."""
    citations = citations
    assert citations.knows("TX350-C §3.2") and not citations.is_current("TX350-C §3.2")
    assert citations.is_current("TX350-D §3.2")
    findings = review("B-101", [cause(citation="TX350-C §3.2")], [], materials, citations)
    assert [f.kind for f in findings] == ["citation_expired"]


def test_a_cause_without_a_citation_blocks(materials, citations):
    findings = review("B-101", [cause(citation=None)], [], materials,
                      citations)
    assert [f.kind for f in findings] == ["citation_missing"]


def test_a_part_outside_the_bill_of_materials_blocks(materials, citations):
    # A pump seal kit has no place in a filter's bill of materials.
    findings = review("F-201B", [cause()], [{"codigo": "TX-SELLO-CAR", "cantidad": 1}],
                      materials, citations)
    assert [f.kind for f in findings] == ["part_not_in_bom"]


def test_no_stock_in_the_yacimiento_is_reported_but_not_hidden(materials, citations):
    # The rodamiento set is in the pump's BOM but the yacimiento has none: the order can
    # exist, it just cannot be approved without a human (that is the sin-luz case).
    findings = review("B-102", [cause()], [{"codigo": "TX-ROD-CIG", "cantidad": 1}], materials,
                      citations)
    assert [f.kind for f in findings] == ["part_no_stock"]
    assert materials.parts["TX-ROD-CIG"].stock == {"yacimiento": 0.0, "central": 2.0}


def test_an_analysis_without_causes_blocks(materials, citations):
    findings = review("B-101", [], [], materials, citations)
    assert [f.kind for f in findings] == ["empty_causes"]


def test_citations_are_deduplicated_in_order(citations):
    causes = [cause(citation="MBP-4 §6.4"), cause(citation="MBP-4 §7.1"),
              cause(citation="MBP-4 §6.4")]
    assert citations_of(causes) == ["MBP-4 §6.4", "MBP-4 §7.1"]


def test_the_index_accepts_the_rows_the_database_returns(citations):
    """rag_citations() returns {"citation", "current"}: the reviewer must read them."""
    index = CorpusCitations([{"citation": "MBP-4 §7.1", "current": True},
                             {"citation": "TX350-C §3.2", "current": False}])
    assert index.knows("MBP-4 §7.1") and index.is_current("MBP-4 §7.1")
    assert index.knows("TX350-C §3.2") and not index.is_current("TX350-C §3.2")
    assert not index.knows("MBP-9 §1.1")
