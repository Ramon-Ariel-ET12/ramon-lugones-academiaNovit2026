"""What the plant's own history says about a fault that keeps coming back.

The archived work orders are free text written by field staff, with abbreviations and
typos ("descraga", "valvulas gastad", "prensaestopas", "x", "dif 2,3"). A fault that
repeats changes the probable cause, and the Anexo lists the five cases this plant has
actually seen. The matcher is tolerant on purpose and conservative: it only reports a
pattern it can point at, with the order ids that support it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from itertools import pairwise

from app.domain.numbers import normalize_text

# How close two jobs have to be to count as "the same fault coming back".
PACKING_REPEAT_DAYS = 60
VALVES_ACROSS_PUMPS_DAYS = 10
OIL_REPEAT_DAYS = 90

VALVE_TASK = "T-B-VAL"
PACKING_TASK = "T-B-EMP"
OIL_TASK = "T-B-ACE"
ALIGNMENT_TASK = "T-B-ALI"
CARTRIDGE_TASK = "T-F-CAR"


@dataclass(frozen=True)
class HistoryFinding:
    equipment: str
    pattern: str
    detail: str
    order_ids: list[str]
    suggested_cause: str | None
    suggested_task: str | None
    suggested_code: str | None = None
    suggested_citation: str | None = None
    root_equipment: str | None = None


def _text(order: dict) -> str:
    parts = [order.get("aviso"), order.get("trabajo_realizado"), order.get("descripcion")]
    return normalize_text(" ".join(str(part) for part in parts if part))


def _tasks(order: dict) -> set[str]:
    return {str(task) for task in (order.get("tareas") or [])}


def _when(order: dict) -> datetime | None:
    for key in ("fecha_aviso", "fecha", "fecha_inicio"):
        value = order.get(key)
        if not value:
            continue
        try:
            return datetime.fromisoformat(str(value))
        except ValueError:
            continue
    return None


def _ids(orders: list[dict]) -> list[str]:
    return [str(order.get("id")) for order in orders if order.get("id")]


def _within(orders: list[dict], days: int) -> bool:
    """Whether two of these jobs happened within ``days`` of each other.

    Not whether the whole span fits: a fault that repeats for two years repeats in pairs
    weeks apart, and each pair is what changes the probable cause.
    """
    stamps = sorted(stamp for stamp in (_when(order) for order in orders) if stamp is not None)
    return any(later - earlier <= timedelta(days=days) for earlier, later in pairwise(stamps))


def _close_in_time(left: datetime | None, right: datetime | None, days: int) -> bool:
    if left is None or right is None:
        return False
    return abs((left - right).days) <= days


def _has_word(text: str, *words: str) -> bool:
    return any(word in text for word in words)


def _pump_of(equipment: str | None) -> str | None:
    return equipment if equipment and equipment.startswith("B-") else None


def _filter_for(orders: list[dict], *, default: str = "F-201B") -> str:
    """The filter that catches what wears the valves: the secondary one when it exists.

    The Anexo names F-201B (10 µm, the last barrier before the pumps); the history is
    only used to confirm that the plant has that filter.
    """
    tags = {str(order.get("equipo")) for order in orders if CARTRIDGE_TASK in _tasks(order)}
    if default in tags:
        return default
    return next((tag for tag in sorted(tags) if tag.startswith("F-201")), default)


def recurring_findings(equipment: str, orders: list[dict]) -> list[HistoryFinding]:
    """The recurring-fault findings for one equipment, most specific first.

    ``orders`` may include other equipment: two pumps with worn valves in the same few
    days point at the filter upstream, and that cannot be seen from one pump alone.
    """
    findings: list[HistoryFinding] = []
    own = [order for order in orders if str(order.get("equipo") or "") == equipment]
    valves = [order for order in own if VALVE_TASK in _tasks(order)]
    packing = [order for order in own if PACKING_TASK in _tasks(order)]
    oil = [order for order in own if OIL_TASK in _tasks(order)]
    labels = [order for order in own if ALIGNMENT_TASK in _tasks(order)]

    # 1. Vibration that survived the valves: the coupling, not the valves (§7.1 F06).
    survived = [order for order in valves
                if _has_word(_text(order), "no se fue", "no se van", "sigue igual", "sin pulsacion",
                             "no golpea pero vibra")]
    if valves and (survived or labels) and _pump_of(equipment):
        supporting = survived + labels
        findings.append(HistoryFinding(
            equipment=equipment,
            pattern="valvulas_repetidas",
            detail=(f"la vibración no se fue cambiando válvulas ({len(valves)} trabajos de válvulas): "
                    f"el historial apunta al acople"),
            order_ids=_ids(supporting or valves),
            suggested_cause="acople desalineado o elastómero gastado",
            suggested_task=ALIGNMENT_TASK,
            suggested_code="F06",
            suggested_citation="MBP-4 §7.1",
        ))

    # 2. Packing that lasts weeks: the plunger is scored, a new kit will not fix it.
    if len(packing) >= 2 and _within(packing, PACKING_REPEAT_DAYS) and _pump_of(equipment):
        scored = [order for order in packing
                  if _has_word(_text(order), "rayad", "rayitas", "surcos", "de nuevo", "otra vez",
                               "3ra", "4ta", "dur(", "dura ", "semanas")]
        if scored:
            findings.append(HistoryFinding(
                equipment=equipment,
                pattern="empaquetadura_repetida",
                detail=(f"la empaquetadura volvió a fallar {len(packing)} veces en "
                        f"{PACKING_REPEAT_DAYS} días: el historial apunta al émbolo rayado"),
                order_ids=_ids(scored),
                suggested_cause="émbolo rayado",
                suggested_task="NO-ESTANDAR",
                suggested_code="F01",
                suggested_citation="MBP-4 §6.3",
            ))

    # 3. The same valve fault in two pumps within days: the cartridge upstream is broken.
    if _pump_of(equipment) and valves:
        other_pumps = {str(order.get("equipo")): order for order in orders
                       if VALVE_TASK in _tasks(order) and str(order.get("equipo")) != equipment}
        near = [order for order in other_pumps.values()
                if any(_close_in_time(_when(order), _when(mine), VALVES_ACROSS_PUMPS_DAYS)
                       for mine in valves)]
        if near:
            findings.append(HistoryFinding(
                equipment=equipment,
                pattern="valvulas_en_dos_bombas",
                detail=("dos bombas con válvulas gastadas en pocos días: sospechar un cartucho roto "
                        "aguas arriba, en el filtro"),
                order_ids=_ids(near + valves[:1]),
                suggested_cause="cartucho roto aguas arriba (F-201)",
                suggested_task=CARTRIDGE_TASK,
                suggested_code="F08",
                suggested_citation="MBP-4 §6.10",
                root_equipment=_filter_for(orders),
            ))

    # 4. A pump that cavitates and a filter that was changed for it: the suction is the cause.
    if _pump_of(equipment):
        cavitation = [order for order in own
                      if _has_word(_text(order), "cavita", "piedras", "succion 0", "succion baja",
                                   "baja succion")]
        filters = [order for order in orders
                   if CARTRIDGE_TASK in _tasks(order) and _has_word(_text(order), "cavita", "piedras")]

        if cavitation and filters:
            findings.append(HistoryFinding(
                equipment=equipment,
                pattern="cavitacion_filtro",
                detail=("la bomba ya cavitó antes y el filtro se cambió por eso: la causa raíz está "
                        "en la succión, no en la bomba"),
                order_ids=_ids(filters + cavitation[:1]),
                suggested_cause="filtro primario colmatado",
                suggested_task=CARTRIDGE_TASK,
                suggested_code="F07",
                suggested_citation="MBP-4 §6.9",
                root_equipment=str(filters[-1].get("equipo") or "F-201A"),
            ))

    # 5. Oil that keeps disappearing without a visible leak: the pinion seal.
    if len(oil) >= 2 and _within(oil, OIL_REPEAT_DAYS) and _pump_of(equipment):
        leaking = [order for order in oil
                   if _has_word(_text(order), "otra vez", "de nuevo", "reten", "pinon", "pierde")]
        if leaking:
            findings.append(HistoryFinding(
                equipment=equipment,
                pattern="consumo_aceite",
                detail=(f"el aceite se repuso {len(oil)} veces en {OIL_REPEAT_DAYS} días: el historial "
                        f"apunta al retén del piñón, no a una pérdida visible"),
                order_ids=_ids(leaking),
                suggested_cause="retén del piñón",
                suggested_task="NO-ESTANDAR",
                suggested_citation="MBP-4 §6.6",
            ))
    return findings
