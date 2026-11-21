"""The operator console: the small HTML page served at ``/``.

Presentation only. It receives the dict that ``Repository.console_state`` returns and
never touches the database, MQTT or the workflow.
"""

from __future__ import annotations

import html
import json

CSS = """body{font-family:system-ui;margin:2rem;color:#1b1b1b}table{border-collapse:collapse}
td,th{border-bottom:1px solid #ddd;padding:.35rem .6rem;text-align:left;vertical-align:top}
.badge{background:#0a7;color:#fff;padding:.1rem .5rem;border-radius:6px}"""


def _esc(value) -> str:
    return html.escape("" if value is None else str(value))


def _sources(context) -> str:
    """The manual section each conclusion is based on, rendered next to the event."""
    if isinstance(context, str):
        try:
            context = json.loads(context)
        except ValueError:
            return ""
    sections = (context or {}).get("sections") or []
    citations = [str(item.get("citation")) for item in sections if item.get("citation")]
    if not citations:
        return ""
    return f" <small>· fuentes: {html.escape(', '.join(citations))}</small>"


def _causes(row: dict) -> str:
    causes = row.get("causes") or []
    if not causes:
        return "<small>sin análisis registrado</small>"
    items = "".join(
        f"<li>{html.escape(str(cause.get('title') or ''))} "
        f"<small>({html.escape(str(cause.get('code') or '—'))}, {html.escape(str(cause.get('confidence') or ''))}, "
        f"{html.escape(str(cause.get('citation') or 'sin cita'))})</small></li>"
        for cause in causes[:3]
    )
    return f"<ul>{items}</ul>"


def _differences(row: dict) -> str:
    differences = row.get("diferencias") or []
    if not differences:
        return ""
    items = "".join(f"<li>{html.escape(str(difference.get('kind') or ''))}: "
                    f"{html.escape(str(difference.get('detail') or ''))}</li>" for difference in differences)
    amount = row.get("monto_habilita_usd")
    extra = f" <small>· contrato: USD {amount:.0f}</small>" if amount is not None else ""
    return f"<div><b>Diferencias del cierre</b>{extra}<ul>{items}</ul></div>"


def _next_command(row: dict) -> str:
    order_id = row["id"]
    state = row.get("state")
    if state == "PendienteAprobacion":
        return f'aprobar {order_id} --actor "..."   ·   rechazar {order_id} --actor "..." --motivo "..."'
    if state in ("Aprobada", "Ejecutada", "Observada"):
        return (f'cerrar {order_id} --actor "..."   ·   certificar {order_id} --actor "..." '
                f'--habilita HAB-AAAA-NNNN   ·   observar {order_id} --actor "..." --motivo "..."')
    return ""


def _review_section(data: dict) -> str:
    rows = data.get("review_orders") or []
    if not rows:
        return ""
    cards = []
    for row in rows:
        command = _next_command(row)
        hint = (f'<p><code>python scripts/orden.py {html.escape(command)}</code></p>' if command else "")
        cards.append(
            f"<li><b>{_esc(row['id'])}</b> · {_esc(row['equipment'])} · <b>{_esc(row['state'])}</b> "
            f"{_esc(row['tasks'])}"
            f"{'<br><small>motivo: ' + _esc(row['payload'].get('motivo')) + '</small>' if row['payload'].get('motivo') else ''}"
            f"{_causes(row)}{_differences(row)}{hint}</li>"
        )
    return f"<h2>Órdenes para decidir</h2><ul>{''.join(cards)}</ul>"


def render_console(data: dict, *, system_name: str, link_up: bool) -> str:
    notes = "".join(
        f"<tr><td>{_esc(note['id'])}</td><td>{_esc(note['ts'])}</td>"
        f"<td>{_esc(note['status'])}</td><td>{_esc((note['transcript'] or '')[:120])}</td></tr>"
        for note in data["notes"]
    )
    events = "".join(
        f"<li><b>{_esc(event['type'])}</b> {_esc(event['equipment'])} ({_esc(event['origin'])})"
        f" - {_esc(event['summary'])}{_sources(event.get('context'))}</li>"
        for event in data["events"]
    )
    orders = "".join(
        f"<li><b>{_esc(order['state'])}</b> {_esc(order['equipment'])} {_esc(order['tasks'])} "
        f"<small>{_esc((order['payload'] or {}).get('motivo') or '')}</small></li>"
        for order in data["orders"]
    )
    usage = data["usage"]
    return f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<title>PIA-3 · Central de mantenimiento</title>
<style>{CSS}</style></head><body>
<h1>PIA-3 · Central de mantenimiento</h1>
<p><span class="badge">{_esc(system_name)}</span>
enlace {'arriba' if link_up else 'caído'} · pendientes de sincronizar: {data['pending_sync']} ·
fragmentos RAG: {data['rag_chunks']}</p>
<p>LLM: {usage['calls']} llamadas · tokens entrada {usage['input']} · salida {usage['output']} · \
latencia {usage['latency']} ms</p>
<h2>Partes recientes</h2><table><tr><th>Nota</th><th>Hora</th><th>Estado</th>\
<th>Transcripción</th></tr>{notes}</table>
<h2>Eventos</h2><ul>{events}</ul>
<h2>Órdenes</h2><ul>{orders}</ul>
{_review_section(data)}
<p><a href="/api/state">JSON</a> · <a href="/health">salud</a></p></body></html>"""


STARTING = "<h1>PIA-3 assistant</h1><p>starting...</p>"
