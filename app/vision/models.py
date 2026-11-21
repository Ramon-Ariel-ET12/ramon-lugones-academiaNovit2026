"""Verdict of the photo analysis (Entrega 2).

The vision model looks at one archived photo and answers with this shape. It is
deliberately small: the pipeline only needs to know whether there is visible damage and
what it looks like, never a free-form opinion that could reach an order.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from app.domain.models import StrictModel

PhotoKind = Literal[
    "empaquetadura",
    "correas",
    "acople",
    "manometro",
    "filtro",
    "estructura",
    "desconocida",
]


class PhotoVerdict(StrictModel):
    """What the vision model saw in one photo."""

    photo: str
    kind: PhotoKind = "desconocida"
    structural_damage: bool = False
    severity: Literal["ninguna", "leve", "grave"] = "ninguna"
    observations: list[str] = Field(default_factory=list)
    model: str = ""
    # True when the photo could not be analysed (link down, no model, unreadable file):
    # the pipeline must never read "no damage" out of a failed analysis.
    deferred: bool = False
