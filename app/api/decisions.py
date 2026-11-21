"""HTTP interface for the human decisions (Entrega 2).

The plant contract has no channel for the planner, the supervisor or the inspector, so
this router is our own interface. It is mounted on the same app as the console, which
is only reachable from the plant network (and through the panel proxy).
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from fastapi import APIRouter, HTTPException
from pydantic import Field

from app.domain.models import StrictModel
from app.workflow.decisions import DecisionError, OrderDecisionService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/api/orders", tags=["orders"])

# The console and the CLI both come through here; the service owns the role matrix.
_service: OrderDecisionService | None = None


def configure(service: OrderDecisionService) -> None:
    """Wire the service once, at startup (the app owns the repository and the publisher)."""
    global _service
    _service = service


def service() -> OrderDecisionService:
    if _service is None:
        raise HTTPException(status_code=503, detail="la interfaz de órdenes todavía no está lista")
    return _service


class DecisionRequest(StrictModel):
    role: Literal["planificador", "supervisor", "inspector"]
    action: Literal["approve", "reject", "close", "certify", "observe"]
    actor: str = Field(min_length=2, max_length=80)
    motive: str | None = Field(default=None, max_length=500)
    habilita: str | None = Field(default=None, max_length=40)


@router.get("")
async def list_orders(state: str | None = None, limit: int = 20) -> dict[str, Any]:
    repo = service().repo
    orders = await repo.open_orders() if state is None else await repo.orders_by_state(state, limit)
    return {"ordenes": orders[:limit]}


@router.get("/{order_id}")
async def order_detail(order_id: str) -> dict[str, Any]:
    repo = service().repo
    row = await repo.orders_by_id(order_id)
    if row is None:
        raise HTTPException(status_code=404, detail=f"no existe la orden {order_id}")
    return {
        "orden": row,
        "analisis": await repo.get_analysis(order_id),
        "cierre": await repo.get_closure(order_id),
        "decisiones": await repo.human_decisions(order_id),
    }


@router.post("/{order_id}/decision")
async def decide(order_id: str, body: DecisionRequest) -> dict[str, Any]:
    try:
        result = await service().decide(
            order_id, role=body.role, action=body.action, actor=body.actor,
            motive=body.motive, habilita=body.habilita,
        )
    except DecisionError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"orden_id": result.order_id, "estado": result.state, "rol": result.role,
            "accion": result.action}
