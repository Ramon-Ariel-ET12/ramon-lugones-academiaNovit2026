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
<p><a href="/api/state">JSON</a> · <a href="/health">salud</a></p></body></html>"""


STARTING = "<h1>PIA-3 assistant</h1><p>starting...</p>"
