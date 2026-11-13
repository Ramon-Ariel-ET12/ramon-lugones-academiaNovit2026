"""Wire contract models, re-exported from the provided package.

The models are installed with pip from ``planta_contrato``; they are never copied into
this repository.
"""

from __future__ import annotations

try:
    from planta_contrato import (  # noqa: F401
        Calidad,
        EstadoEnergia,
        EstadoOrden,
        EstadoSistema,
        EventoSistema,
        FilaParte,
        LecturaSensor,
        MensajeTablet,
        NotaCierre,
        NotaRecorrida,
        OrdenSistema,
        Pantalla,
        Repuesto,
        RespuestaOperador,
        TipoEvento,
        Topicos,
    )
except ImportError as exc:  # pragma: no cover - installation problem
    raise RuntimeError(
        "planta_contrato is not installed. Install the provided package with pip "
        "(see README: PLANTA_CONTRATO_DIR or the documented git source)."
    ) from exc

from pydantic import BaseModel

TOPIC_MODELS: dict[str, type[BaseModel]] = {
    "sistema/eventos": EventoSistema,
    "sistema/ordenes": OrdenSistema,
    "sistema/estado": EstadoSistema,
    "sistema/tablet": MensajeTablet,
}

