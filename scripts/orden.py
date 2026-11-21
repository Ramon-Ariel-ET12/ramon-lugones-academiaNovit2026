"""Human decisions on work orders, from the terminal.

The plant contract has no channel for the planner, the supervisor or the inspector, so
this CLI is the operator's interface (the same API the console uses):

    python scripts/orden.py pendientes
    python scripts/orden.py ver OT-3f2a
    python scripts/orden.py aprobar OT-3f2a   --actor "Ana Pérez"
    python scripts/orden.py rechazar OT-3f2a  --actor "Ana Pérez" --motivo "sin reserva"
    python scripts/orden.py cerrar   OT-3f2a  --actor "Luis Soto"
    python scripts/orden.py certificar OT-3f2a --actor "Inés Ríos" --habilita HAB-2025-0003
    python scripts/orden.py observar  OT-3f2a --actor "Inés Ríos" --motivo "declara horas de más"

It talks to the API over HTTP so it can run from the host against the panel port, or
inside the container.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import httpx

BASE = os.environ.get("ASISTENTE_URL", "http://localhost:8200")
ACTIONS = {"aprobar": "approve", "rechazar": "reject", "cerrar": "close",
           "certificar": "certify", "observar": "observe"}
ROLES = {"aprobar": "planificador", "rechazar": "planificador", "cerrar": "supervisor",
         "certificar": "inspector", "observar": "inspector"}


def _print(value) -> None:
    print(json.dumps(value, ensure_ascii=False, indent=2, default=str))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--url", default=BASE, help=f"base del asistente (default {BASE})")
    sub = parser.add_subparsers(dest="comando", required=True)

    pendientes = sub.add_parser("pendientes", help="órdenes esperando una decisión")
    pendientes.add_argument("--estado", default="PendienteAprobacion")

    ver = sub.add_parser("ver", help="orden, análisis, cierre y decisiones")
    ver.add_argument("orden")

    for name in ACTIONS:
        action = sub.add_parser(name, help=f"{name} una orden")
        action.add_argument("orden")
        action.add_argument("--actor", required=True, help="quién decide")
        action.add_argument("--motivo", default=None)
        action.add_argument("--habilita", default=None, help="número de habilitación (certificar)")

    args = parser.parse_args(argv)

    with httpx.Client(base_url=args.url, timeout=20) as client:
        if args.comando == "pendientes":
            response = client.get("/api/orders", params={"state": args.estado})
        elif args.comando == "ver":
            response = client.get(f"/api/orders/{args.orden}")
        else:
            body = {"role": ROLES[args.comando], "action": ACTIONS[args.comando], "actor": args.actor,
                    "motive": args.motivo, "habilita": args.habilita}
            response = client.post(f"/api/orders/{args.orden}/decision", json=body)
        try:
            _print(response.json())
        except ValueError:
            print(response.text, file=sys.stderr)
        return 0 if response.is_success else 1


if __name__ == "__main__":
    raise SystemExit(main())
