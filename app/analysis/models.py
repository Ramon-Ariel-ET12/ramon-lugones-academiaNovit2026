"""Domain models of the maintenance analysis (Entrega 2).

These are the contract between the detector, the cause ranking, the reviewer and the
order drafter. They are pure data: no I/O, no database, no model calls.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.models import StrictModel

SymptomName = Literal[
    "vibracion_alta",
    "temperatura_aceite_alta",
    "caudal_bajo",
    "presion_succion_baja",
    "diferencial_alto",
    "diferencial_bajo",
    "goteo",
    "aceite_bajo",
    "correas",
    "estado",
]


class Symptom(StrictModel):
    """One abnormal fact read from the evidence, with the number that supports it."""

    name: SymptomName
    tag: str | None = None
    detail: str = ""
    value: float | None = None
    unit: str | None = None
    source: Literal["parte", "sensor", "historial"] = "parte"


class Cause(StrictModel):
    """A probable cause, in the order the evidence supports.

    ``evidence`` is what is already known; ``missing`` is what would confirm it. A cause
    whose evidence is thin still comes back, with ``needs_inspection`` set, so the order
    asks for an inspection instead of inventing a repair.
    """

    code: str | None = None       # plant fault code (F01..F10) when it is identified
    title: str
    confidence: Literal["alta", "media", "baja"] = "media"
    evidence: list[str] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    citation: str | None = None   # manual section the cause comes from
    task_code: str | None = None  # task that resolves it, when known
    stops_equipment: bool = False
    needs_inspection: bool = False
    root_equipment: str | None = None  # F09: the root cause lives in another equipment


class ReviewFinding(StrictModel):
    """One problem found by the reviewer step before an order can be published."""

    kind: Literal["citation_missing", "citation_expired", "part_not_in_bom", "part_no_stock", "empty_causes"]
    detail: str


class Analysis(StrictModel):
    """Everything the analysis decided for one escalated event."""

    correlation_id: str
    equipment: str
    symptoms: list[Symptom] = Field(default_factory=list)
    causes: list[Cause] = Field(default_factory=list)
    citations: list[str] = Field(default_factory=list)
    findings: list[ReviewFinding] = Field(default_factory=list)
    tasks: list[str] = Field(default_factory=list)
    parts: list[dict] = Field(default_factory=list)
    history: list[str] = Field(default_factory=list)

    @property
    def blocked(self) -> bool:
        """The reviewer refused to publish: no order may be derived from this analysis."""
        return bool(self.findings)
