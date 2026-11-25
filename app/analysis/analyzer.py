"""The analysis step: evidence in, ranked causes and a reviewed task list out.

This is the seam between the workflow and the analysis modules. It decides nothing by
itself: it asks the signatures what is wrong, the history what has happened before, the
cause table what that means, and the reviewer whether the result can be published.
"""

from __future__ import annotations

from app.analysis.causes import STOPPING, TITLE_OF, rank_causes, tasks_for
from app.analysis.history import HistoryFinding, recurring_findings
from app.analysis.models import Analysis, Cause
from app.analysis.review import CitationIndex, citations_of, review
from app.analysis.signatures import detect_symptoms, part_is_normal
from app.domain.materials import DEFAULT_PART_QUANTITY, Materials
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
                needed[code] = needed.get(code, 0.0) + float(part.get("cantidad") or DEFAULT_PART_QUANTITY)
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


def _history_cause(finding: HistoryFinding, *, title: str, citation: str, task: str | None,
                   code: str | None = None, root: str | None = None) -> Cause:
    return Cause(code=code, title=title, confidence="alta", evidence=[finding.detail],
                 citation=citation, task_code=task,
                 stops_equipment=bool(code and code in STOPPING), root_equipment=root)


def _merge(causes: list[Cause], cause: Cause, position: str) -> None:
    """Add the history cause, or strengthen the one already there. Never duplicates it."""
    existing = next((item for item in causes if cause.code and item.code == cause.code), None)
    if existing is None and cause.code is None:
        existing = next((item for item in causes if item.title == cause.title), None)
    if existing is not None:
        if existing.confidence != "alta":
            existing.confidence = "alta"
        if cause.citation:
            # The history brings its own differential section (§7.1, §7.2 …).
            existing.citation = cause.citation
        if cause.task_code:
            existing.task_code = cause.task_code
        for detail in cause.evidence:
            if detail not in existing.evidence:
                existing.evidence.append(detail)
        return
    causes.insert(0 if position == "top" else min(1, len(causes)), cause)


def apply_history(causes: list[Cause], findings: list[HistoryFinding]) -> list[Cause]:
    """Let a recurring fault change the probable cause and, where the manual says so, the action.

    The five cases of the Anexo are gated on the evidence of the current event: the
    history only promotes the coupling when the vibration is the fault at hand (not when
    a bearing already explains it), only turns the packing into the plunger when there is
    a leak, only blames the filter when the suction or the valves are the symptom, and
    only blames the pinion seal when the oil level is low. A history cause that would
    displace the repair of the equipment itself goes second, with the upstream equipment
    named in ``root_equipment``.
    """
    codes = {cause.code for cause in causes if cause.code}
    for finding in findings:
        if finding.pattern == "valvulas_repetidas" and codes & {"F02", "F06"}:
            _merge(causes, _history_cause(
                finding, code="F06", title=TITLE_OF["F06"], citation="MBP-4 §7.1",
                task="T-B-ALI"), "top")
        elif finding.pattern == "empaquetadura_repetida" and "F01" in codes:
            # §6.3: a leak that comes back in weeks is the plunger, and that is not the
            # standard packing task. The order asks for the non-standard check.
            _merge(causes, _history_cause(
                finding, title="Émbolo rayado (la empaquetadura no dura)",
                citation="MBP-4 §6.3", task="NO-ESTANDAR"), "top")
        elif finding.pattern == "valvulas_en_dos_bombas" and "F02" in codes:
            # §7.2: the repair of the pump stands, but the probable root cause is upstream.
            _merge(causes, _history_cause(
                finding, code="F08", title=TITLE_OF["F08"], citation="MBP-4 §6.10",
                task=None, root=finding.root_equipment), "second")
        elif finding.pattern == "cavitacion_filtro" and codes & {"F09", "F07"}:
            _merge(causes, _history_cause(
                finding, code="F07", title=TITLE_OF["F07"], citation="MBP-4 §6.9",
                task=None, root=finding.root_equipment), "second")
        elif finding.pattern == "consumo_aceite" and "F04" in codes:
            _merge(causes, _history_cause(
                finding, title="Retén del piñón gastado (consumo de aceite)",
                citation="MBP-4 §6.6", task="NO-ESTANDAR"), "top")
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
