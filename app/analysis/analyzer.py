"""The analysis step: evidence in, ranked causes and a reviewed task list out.

This is the seam between the workflow and the analysis modules. It decides nothing by
itself: it asks the signatures what is wrong, the history what has happened before, the
cause table what that means, and the reviewer whether the result can be published.
"""

from __future__ import annotations

from app.analysis.causes import rank_causes, tasks_for
from app.analysis.history import HistoryFinding, recurring_findings
from app.analysis.models import Analysis, Cause
from app.analysis.review import CitationIndex, citations_of, review
from app.analysis.signatures import detect_symptoms, part_is_normal
from app.domain.materials import Materials
from app.domain.models import ExtractedRow, PlantSnapshot


def parts_for(tasks: list[str], equipment: str, materials: Materials) -> list[dict]:
    """The spare parts the ordered tasks need, with availability and unit cost.

    The order itself only carries ``codigo``/``cantidad`` (the contract's model); the
    availability and the cost belong to the analysis, where the planner reads them.
    """
    needed: dict[str, float] = {}
    for task_code in tasks:
        task = materials.task(task_code, equipment)
        if task is None:
            continue
        for part in task.parts:
            code = str(part.get("codigo") or "")
            if code:
                needed[code] = needed.get(code, 0.0) + float(part.get("cantidad") or 1)
    parts: list[dict] = []
    for code, quantity in needed.items():
        spare = materials.parts.get(code)
        parts.append({
            "codigo": code,
            "cantidad": quantity,
            "nombre": spare.name if spare else "",
            "costo_usd": spare.cost_usd if spare else 0.0,
            "stock": spare.stock if spare else {},
            "en_yacimiento": materials.in_stock(code, quantity, "yacimiento"),
            "en_central": materials.in_stock(code, quantity, "central"),
        })
    return parts


def apply_history(causes: list[Cause], findings: list[HistoryFinding]) -> list[Cause]:
    """Let a recurring fault change the probable cause, without inventing a new one.

    A finding only strengthens a cause the evidence already supports (it says "the
    coupling" when the coupling is already a candidate); it never adds a cause of its own,
    because a cause without evidence would need a citation we cannot back.
    """
    for finding in findings:
        if not finding.suggested_cause:
            continue
        words = {word for word in finding.suggested_cause.lower().split() if len(word) > 4}
        for cause in causes:
            if words & set(cause.title.lower().split()) or (finding.suggested_task and
                                                            finding.suggested_task == cause.task_code):
                if cause.confidence != "alta":
                    cause.confidence = "alta"
                detail = f"el historial lo respalda: {finding.detail}"
                if detail not in cause.evidence:
                    cause.evidence.append(detail)
                break
    return causes


def analyse(equipment: str, rows: list[ExtractedRow], sensor_variable: str | None, context: dict,
            snapshot: PlantSnapshot, materials: Materials, citations: CitationIndex,
            correlation_id: str) -> Analysis:
    """Everything the order will be based on, reviewer findings included."""
    trend = context.get("sensor_trend") or {}
    history = context.get("order_history") or []
    symptoms = detect_symptoms(equipment, rows, sensor_variable, trend, snapshot)
    findings = recurring_findings(equipment, history)
    causes = apply_history(rank_causes(equipment, symptoms, trend, part_is_normal(rows)), findings)
    tasks = tasks_for(causes, equipment, materials)
    parts = parts_for(tasks, equipment, materials)
    return Analysis(
        correlation_id=correlation_id,
        equipment=equipment,
        symptoms=symptoms,
        causes=causes,
        citations=citations_of(causes),
        findings=review(equipment, causes, parts, materials, citations),
        tasks=tasks,
        parts=parts,
        history=[finding.detail for finding in findings],
    )
