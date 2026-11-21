"""Models of the closure comparison (Entrega 2).

What the technician said when closing the order, against what the order asked for.
The comparison never changes the order by itself: it produces the differences and the
state a human has to confirm.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.models import StrictModel

DifferenceKind = Literal["tarea_faltante", "tarea_extra", "repuesto_faltante", "repuesto_extra",
                         "cantidad", "horas", "prueba", "precio"]


class Difference(StrictModel):
    kind: DifferenceKind
    detail: str


class ClosurePart(StrictModel):
    """The closure part: what was done, with what, how long and how it was proven."""

    orden_id: str
    tecnico: str = ""
    empresa: str = ""
    tasks_done: list[str] = Field(default_factory=list)
    parts_used: list[dict] = Field(default_factory=list)
    hours: float | None = None
    test_result: str = ""
    transcript: str = ""


class ClosureComparison(StrictModel):
    closure: ClosurePart
    differences: list[Difference] = Field(default_factory=list)
    monto_habilita_usd: float | None = None
    habilita: str | None = None

    @property
    def clean(self) -> bool:
        return not self.differences
