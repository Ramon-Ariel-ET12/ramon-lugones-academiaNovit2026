"""The reviewer step: nothing is published on the strength of a citation we cannot back.

Delivery 2 asks for an explicit reviewer: every citation must exist and be current, and
every spare part must be in the equipment's bill of materials. The analysis is not
published as an order when the reviewer finds a problem it cannot justify; a stock
shortage is reported but does not block, because a pending order is exactly how the
plant handles "we have the part, just not here".
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from app.analysis.models import Cause, ReviewFinding
from app.domain.materials import Materials
from app.rag.corpus import bundled_path, canonical, load_fragments

# A part without an explicit quantity is one unit, as in the approval rules.
DEFAULT_QUANTITY = 1.0


class CitationIndex(Protocol):
    def knows(self, citation: str) -> bool: ...

    def is_current(self, citation: str) -> bool: ...


def _normalise(citation: str | None) -> str:
    return " ".join((citation or "").split())


class CorpusCitations:
    """Citations known to the manual index, as ``citation -> current``.

    Rows may come from the ``rag_chunks`` table (``citation``/``current``) or from the
    course corpus file (``id``/``vigente``); both are accepted so the reviewer works
    against the indexed database in production and against the bundled file in tests.
    """

    def __init__(self, chunks: list[dict]):
        self._current: dict[str, bool] = {}
        for chunk in chunks:
            row = chunk if "text" in chunk else canonical(chunk)
            citation = _normalise(row.get("citation"))
            if citation:
                self._current[citation] = row.get("current") is not False

    @classmethod
    def bundled(cls, path: Path | str) -> CorpusCitations:
        return cls(load_fragments(path))

    @classmethod
    def from_settings(cls, settings) -> CorpusCitations:
        return cls.bundled(bundled_path(settings))

    def knows(self, citation: str) -> bool:
        return _normalise(citation) in self._current

    def is_current(self, citation: str) -> bool:
        return self._current.get(_normalise(citation), False)


def review(equipment: str, causes: list[Cause], parts: list[dict], materials: Materials,
           citations: CitationIndex, warehouse: str = "yacimiento") -> list[ReviewFinding]:
    """Findings that stop (or qualify) an order. An empty list is the only pass."""
    findings: list[ReviewFinding] = []
    if not causes:
        findings.append(ReviewFinding(kind="empty_causes",
                                      detail="el análisis no llegó a ninguna causa probable"))
    for cause in causes:
        citation = _normalise(cause.citation)
        if not citation:
            findings.append(ReviewFinding(kind="citation_missing",
                                          detail=f"la causa '{cause.title}' no cita el manual"))
        elif not citations.knows(citation):
            findings.append(ReviewFinding(kind="citation_missing",
                                          detail=f"la cita '{citation}' no existe en el corpus"))
        elif not citations.is_current(citation):
            findings.append(ReviewFinding(kind="citation_expired",
                                          detail=f"la cita '{citation}' es de una revisión vencida"))
    bom = set(materials.bom.get(equipment, []))
    for part in parts:
        code = str(part.get("codigo") or "")
        quantity = float(part.get("cantidad") or DEFAULT_QUANTITY)
        if not code:
            findings.append(ReviewFinding(kind="part_not_in_bom",
                                          detail=f"la orden de {equipment} trae un repuesto sin código"))
            continue
        if code not in bom:
            findings.append(ReviewFinding(kind="part_not_in_bom",
                                          detail=f"el repuesto {code} no está en la lista de materiales de "
                                                 f"{equipment}"))
            continue
        if not materials.in_stock(code, quantity, warehouse):
            findings.append(ReviewFinding(kind="part_no_stock",
                                          detail=f"no hay stock de {code} ({quantity:g}) en el almacén "
                                                 f"{warehouse}"))
    return findings


def citations_of(causes: list[Cause]) -> list[str]:
    """The citations an order carries, deduplicated in cause order."""
    seen: list[str] = []
    for cause in causes:
        citation = _normalise(cause.citation)
        if citation and citation not in seen:
            seen.append(citation)
    return seen
