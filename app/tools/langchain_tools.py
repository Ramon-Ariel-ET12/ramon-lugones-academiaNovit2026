"""LangChain tool wrappers over the same read-only functions.

An agent calls these; a human calls the methods of ``Tools`` directly. Both go through
the same contract models, so a tool cannot be reachable in one surface and not the
other. ``StructuredTool`` calls ``coroutine`` with keyword arguments, so the wrapper
builds the query model from them instead of expecting it positionally.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from langchain_core.tools import StructuredTool
from pydantic import BaseModel

from app.tools.contracts import (
    BomQuery,
    EquipmentQuery,
    InventoryQuery,
    ManualSearchQuery,
    OrderHistoryQuery,
    SensorHistoryQuery,
    StockQuery,
    TaskCatalogQuery,
)
from app.tools.queries import Tools

ToolCall = Callable[..., Awaitable[BaseModel]]


def _tool(method: ToolCall, schema: type[BaseModel], name: str, description: str) -> StructuredTool:
    async def call(**kwargs: Any) -> dict:
        return (await method(schema(**kwargs))).model_dump()

    return StructuredTool.from_function(coroutine=call, name=name, description=description,
                                       args_schema=schema)


def build_langchain_tools(tools: Tools) -> list[StructuredTool]:
    return [
        _tool(tools.equipos, EquipmentQuery, "equipos",
              "Equipos de la planta con TAG y nombres informales."),
        _tool(tools.historial_sensores, SensorHistoryQuery, "historial_sensores",
              "Historial de sensores de un equipo en las últimas horas o días."),
        _tool(tools.historial_ordenes, OrderHistoryQuery, "historial_ordenes",
              "Historial de órdenes de trabajo por equipo."),
        _tool(tools.inventario, InventoryQuery, "inventario",
              "Inventario de repuestos con stock por almacén."),
        _tool(tools.stock, StockQuery, "stock", "Stock de un repuesto en un almacén."),
        _tool(tools.lista_materiales, BomQuery, "lista_materiales",
              "Lista de materiales de un equipo."),
        _tool(tools.catalogo_tareas, TaskCatalogQuery, "catalogo_tareas",
              "Catálogo de tareas estándar y no estándar de mantenimiento."),
        _tool(tools.buscar_manuales, ManualSearchQuery, "buscar_manuales",
              "Búsqueda en manuales con cita de sección y vigencia."),
    ]
