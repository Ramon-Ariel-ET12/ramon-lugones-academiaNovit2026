"""Human decisions on a work order (Entrega 2).

The contract has no channel for these decisions, so it is our own interface. Three
roles, and each one can only do its own transition:

| role        | actions            | from                                  | to                     |
|-------------|--------------------|---------------------------------------|------------------------|
| planificador| approve, reject    | PendienteAprobacion                    | Aprobada / Rechazada   |
| supervisor  | close              | Ejecutada (own work)                   | Cerrada                |
| inspector   | certify, observe   | Ejecutada (contractor work)            | Certificada / Observada|

Nothing else writes an order state. ``approve`` is the only way a pending order moves,
and it is a human action by definition: the automatic path already happened in the
approval rules, so the planner's approval is the documented human override.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Literal

from app.domain.closure import ClosureComparison
from app.domain.materials import Materials
from app.persistence.repository import Repository
from app.processing.closure import compare, parse_closure
from app.publisher import Publisher

log = logging.getLogger(__name__)

Role = Literal["planificador", "supervisor", "inspector"]
Action = Literal["approve", "reject", "close", "certify", "observe"]

# role -> action -> (allowed source states, resulting state)
TRANSITIONS: dict[str, dict[str, tuple[frozenset[str], str]]] = {
    "planificador": {
        "approve": (frozenset({"PendienteAprobacion"}), "Aprobada"),
        "reject": (frozenset({"PendienteAprobacion"}), "Rechazada"),
    },
    "supervisor": {
        "close": (frozenset({"Ejecutada", "Aprobada", "Cerrada"}), "Cerrada"),
    },
    "inspector": {
        "certify": (frozenset({"Ejecutada", "Observada"}), "Certificada"),
        "observe": (frozenset({"Ejecutada", "Observada"}), "Observada"),
    },
}


class DecisionError(RuntimeError):
    """The decision is not allowed: wrong role, wrong action or wrong current state."""


@dataclass
class DecisionResult:
    order_id: str
    state: str
    role: str
    action: str


class OrderDecisionService:
    def __init__(self, repo: Repository, publisher: Publisher, *, prices=None,
                 materials: Materials | None = None):
        self.repo = repo
        self.publisher = publisher
        self.materials = materials
        # A ``PriceList`` (app.domain.billing) used to compute the habilita amount. It is
        # injected so the service stays testable and so the contract table can come from
        # the indexed document instead of a constant in the code.
        self.prices = prices

    async def decide(self, order_id: str, *, role: str, action: str, actor: str,
                     motive: str | None = None, habilita: str | None = None,
                     declared_amount: float | None = None,
                     comparison: ClosureComparison | None = None) -> DecisionResult:
        if role not in TRANSITIONS:
            raise DecisionError(f"rol desconocido: {role}")
        if action not in TRANSITIONS[role]:
            raise DecisionError(f"el rol {role} no puede {action}")
        if not actor.strip():
            raise DecisionError("la decisión necesita un responsable")

        row = await self.repo.orders_by_id(order_id)
        if row is None:
            raise DecisionError(f"no existe la orden {order_id}")
        payload = dict(row["payload"])
        current = payload.get("estado") or row["state"]
        allowed_from, target = TRANSITIONS[role][action]
        if current not in allowed_from:
            raise DecisionError(f"{action} no aplica a una orden en estado {current}")

        if action == "observe" and not (motive or "").strip():
            raise DecisionError("observar una orden exige el motivo")
        if action == "reject" and not (motive or "").strip():
            raise DecisionError("rechazar una orden exige el motivo")
        if action == "certify":
            amount, habilita, comparison = await self._certification_amount(
                row, payload, habilita, comparison, declared_amount,
            )

        payload["estado"] = target
        payload["ts"] = datetime.now(UTC).isoformat()
        payload["motivo"] = motive if target in ("Rechazada", "Observada") else None
        if target == "Certificada":
            payload["habilita"] = habilita
            payload["monto_habilita_usd"] = amount
        elif target == "Observada":
            payload["habilita"] = None
            payload["monto_habilita_usd"] = None

        if comparison is not None:
            await self.repo.save_closure(
                order_id, None, comparison.closure.transcript, list(comparison.closure.parts_used),
                [difference.model_dump() for difference in comparison.differences],
                monto=comparison.monto_habilita_usd,
            )
        published = await self.publisher.publish("sistema/ordenes", payload, sync=True)
        if not published:
            raise DecisionError(f"la orden {order_id} no valida contra el contrato")
        await self.repo.upsert_order(order_id, row["equipment"], row["tasks"], target, payload)
        analysis = await self.repo.get_analysis(order_id) or {}
        await self.repo.record_human_decision(
            order_id, target, [motive] if motive else [f"{role} {action}"], actor, role,
            correlation_id=analysis.get("correlation_id"),
        )
        log.info("order %s: %s %s by %s (%s)", order_id, role, action, actor, target)
        return DecisionResult(order_id=order_id, state=target, role=role, action=action)

    async def _certification_amount(self, row: dict, payload: dict, habilita: str | None,
                                    comparison: ClosureComparison | None,
                                    declared_amount: float | None) -> tuple[float | None, str | None,
                                                                          ClosureComparison | None]:
        """The amount comes from the order and the contract, never from the declaration.

        An order is always about one equipment, so ``I-VIB`` (priced per measured
        equipment) certifies one measurement. When the inspector states what the
        contractor invoiced, the comparison is recomputed here so the difference is
        recorded with the decision.
        """
        if self.prices is None:
            raise DecisionError("no hay lista de precios del contrato configurada")
        started = str(payload.get("ts") or "")[:10]
        if declared_amount is not None and self.materials is not None:
            closure = await self.repo.get_closure(row["id"])
            if closure is not None:
                parts = parse_closure(str(closure.get("transcripcion") or ""), orden_id=row["id"],
                                      materials=self.materials)
                comparison = compare(payload, parts, self.materials, self.prices,
                                     started_at=started, declared_amount=declared_amount)
        amount = comparison.monto_habilita_usd if comparison is not None else None
        if amount is None:
            amount = self.prices.amount_for(list(payload.get("tareas") or []), started_at=started,
                                           equipment_count=1)
        habilita = habilita or (comparison.habilita if comparison is not None else None)
        if amount is None or not habilita:
            raise DecisionError("para certificar hacen falta la habilitación y el monto del contrato")
        return float(amount), habilita, comparison
