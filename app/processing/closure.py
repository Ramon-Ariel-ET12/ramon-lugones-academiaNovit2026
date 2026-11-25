"""The closure note, read back and compared with the order (Entrega 2).

The technician closes the order by voice: what was done, with what, how long and how it
was proven. The transcript is free field speech, so this reader is deterministic and
tolerant (accents, spoken numbers, part names truncated), and the comparison marks every
difference instead of "fixing" it: the human decides.
"""

from __future__ import annotations

import re

from app.domain.billing import PriceList
from app.domain.closure import ClosureComparison, ClosurePart, Difference
from app.domain.materials import DEFAULT_PART_QUANTITY, Materials
from app.domain.numbers import normalize_text, parse_numbers, tokenize

# A gross overrun of the included hours is the documented "extra horas" difference; a
# couple of tenths over is normal field rounding and would only add noise.
HOURS_OVERRUN = 0.50
# Cents of rounding in a declared amount are not a difference.
AMOUNT_TOLERANCE_USD = 1.0


def _tasks_from(text: str, materials: Materials) -> list[str]:
    """Task codes whose catalogue name the technician said."""
    found: list[str] = []
    for code, task in {**{c: t for tasks in materials.standard.values() for c, t in tasks.items()},
                       **materials.nonstandard}.items():
        name = normalize_text(task.name)
        if name and name in text and code not in found:
            found.append(code)
    return found


def _quantity_before(text: str, position: int) -> float:
    """The quantity said before a part name: "un juego", "2 elastómeros", "el doble de"."""
    window = text[max(0, position - 40):position]
    if "doble" in window:
        return 2.0
    numbers = parse_numbers(tokenize(window))
    if numbers:
        return float(numbers[-1].value)
    return 1.0


def _parts_from(text: str, materials: Materials) -> list[dict]:
    """Parts said in the closure, by code or by the (possibly truncated) catalogue name."""
    used: dict[str, float] = {}
    for code, part in materials.parts.items():
        name = normalize_text(part.name.split(" (")[0])
        position = text.find(name) if name else -1
        by_code = text.find(code.lower())
        if position < 0 and by_code < 0:
            continue
        where = position if position >= 0 else by_code
        quantity = _quantity_before(text, where) if position >= 0 else 1.0
        used[code] = used.get(code, 0.0) + quantity
    return [{"codigo": code, "cantidad": quantity} for code, quantity in used.items()]


def _hours_from(text: str) -> float | None:
    sentence = re.search(r"fueron ([^.]*)", text)
    if sentence is None:
        return None
    numbers = parse_numbers(tokenize(sentence.group(1)))
    return float(numbers[0].value) if numbers else None


def _proof_from(text: str) -> str:
    for sentence in re.split(r"(?<=[.;])\s+", text):
        folded = normalize_text(sentence)
        if any(word in folded for word in ("probe", "medi", "quedo en servicio", "sin perdida")):
            return sentence.strip().rstrip(".")
    return ""


def parse_closure(text: str, *, orden_id: str, tecnico: str = "", empresa: str = "",
                  materials: Materials) -> ClosurePart:
    """Read the technician's closure note. Unknown wording simply produces fewer facts."""
    folded = normalize_text(text)
    return ClosurePart(
        orden_id=orden_id,
        tecnico=tecnico,
        empresa=empresa,
        tasks_done=_tasks_from(folded, materials),
        parts_used=_parts_from(folded, materials),
        hours=_hours_from(folded),
        test_result=_proof_from(text),
        transcript=text,
    )


def _part_key(part: dict) -> str:
    return str(part.get("codigo") or "")


def _quantities(parts: list[dict]) -> dict[str, float]:
    quantities: dict[str, float] = {}
    for part in parts:
        code = _part_key(part)
        if code:
            quantities[code] = quantities.get(code, 0.0) + float(part.get("cantidad") or DEFAULT_PART_QUANTITY)
    return quantities


def compare(order: dict, closure: ClosurePart, materials: Materials, prices: PriceList,
            *, equipment_count: int = 1, started_at: str | None = None,
            declared_amount: float | None = None) -> ClosureComparison:
    """Mark every difference between what was asked and what the technician said."""
    differences: list[Difference] = []
    ordered_tasks = [str(task) for task in (order.get("tareas") or [])]
    if ordered_tasks and "NO-ESTANDAR" not in ordered_tasks:
        done = set(closure.tasks_done)
        differences.extend(
            Difference(kind="tarea_faltante", detail=f"la orden pedía {task} y el cierre no lo menciona")
            for task in ordered_tasks if task not in done
        )
        differences.extend(
            Difference(kind="tarea_extra", detail=f"el cierre declara {task}, que no estaba en la orden")
            for task in closure.tasks_done if task not in ordered_tasks
        )

    ordered_parts = _quantities(order.get("repuestos") or [])
    used_parts = _quantities(closure.parts_used)
    for code, quantity in ordered_parts.items():
        if code not in used_parts:
            differences.append(Difference(kind="repuesto_faltante",
                                          detail=f"la orden reservó {code} ({quantity:g}) y no se usó"))
        elif used_parts[code] > quantity:
            differences.append(Difference(kind="cantidad",
                                          detail=f"declara {used_parts[code]:g} de {code} y la orden autorizaba "
                                                 f"{quantity:g}"))
    differences.extend(
        Difference(kind="repuesto_extra", detail=f"declara {code} ({quantity:g}), que no estaba en la orden")
        for code, quantity in used_parts.items() if code not in ordered_parts
    )

    included = prices.hours_included(ordered_tasks, equipment_count)
    if closure.hours is not None and included and closure.hours > included * (1 + HOURS_OVERRUN):
        differences.append(Difference(kind="horas",
                                      detail=f"declara {closure.hours:g} h y el precio cerrado incluye "
                                             f"{included:g} h; las horas de más no estaban autorizadas"))
    if not closure.test_result:
        differences.append(Difference(kind="prueba", detail="el cierre no declara la prueba final"))

    amount = prices.amount_for(ordered_tasks, equipment_count=equipment_count,
                               started_at=started_at or order.get("ts"))
    if amount is None:
        differences.append(Difference(
            kind="precio",
            detail="el trabajo se inició antes de 2025-01-01: se certifica con CT-SVP-2022, que no está "
                   "disponible en el corpus, así que el monto no se puede calcular con el contrato vigente"))
    elif declared_amount is not None and abs(float(declared_amount) - amount) > AMOUNT_TOLERANCE_USD:
        differences.append(Difference(
            kind="precio",
            detail=f"declara USD {float(declared_amount):.0f} y el contrato CT-SVP-2025 da USD {amount:.0f} "
                   f"para lo que pidió la orden (la movilización solo corresponde a trabajos por hora)"))
    return ClosureComparison(closure=closure, differences=differences, monto_habilita_usd=amount)
