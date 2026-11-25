# Verificación del Anexo — Entrega 2

Cada fila corresponde a un requisito del **Anexo de Entregas, Entrega 2** (orquestación,
análisis, reglas, durabilidad, multimodal, cierre) y al enunciado general que aplica
(seguridad, registro, repo). La columna *Evidencia* apunta al código, al test, al comando
o al artefacto que lo demuestra; *Estado* usa **MET**, **PARCIAL** o **NO**.

Método: lectura del anexo, auditoría independiente del árbol con cuatro revisores
(requisito por requisito, contra `HEAD`), inspección del código y de los tests, corrida
oficial del corrector sobre los cuatro escenarios, y demostraciones controladas de lo que
la rúbrica no mide automáticamente (G2/G3 y durabilidad).

## 1. Orquestación (3.1, 3.2)

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 1 | Workflow explícito con escalado → análisis → borrador → reglas → Aprobada/Pendiente | MET | `app/workflow/pipeline.py` (`OrderPipeline.run`): evidencia → análisis → revisor → borrador → reglas → publicación; el escalado es el evento que dispara el pipeline (`app/domain/events.py`, `app/processing/workflow.py`). |
| 2 | Diagrama en el README que muestre workflow fijo y parte de agente | MET | `README.md` §"Orquestación de la entrega 2": diagrama con leyenda `◎` para los dos pasos donde decide un modelo (lectura de respuestas libres y visión) y prosa que dice qué decide el agente y qué no. |
| 3 | Ruteo por tipo: seguridad, parte, sensor, respuesta del operador, cierre | MET | `app/workflow/router.py` (`route_topic`, `route_note`, `classify`); `app/main.py::_dispatch_loop` rutea los tópicos y `app/processing/workflow.py::_process` usa `route_note` para la ruta de seguridad, antes de cualquier modelo o red. |
| 4 | Paso revisor: cita existe y está vigente; repuesto en la lista de materiales | MET | `app/analysis/review.py::review`; cita ausente/vencida o análisis vacío bloquean la publicación (`Analysis.blocked`), repuesto fuera de BOM queda como hallazgo y la orden nace pendiente. Tests: `tests/test_analysis_review.py`, `tests/test_pipeline.py`. |
| 5 | El texto libre no puede aprobar una orden | MET | `app/domain/rules.py::evaluate` (función pura sobre la propuesta y el estado de planta) y `app/workflow/decisions.py` (solo una acción humana sale de `PendienteAprobacion`). Tests: `tests/test_rules_orders.py`, `tests/test_decisions.py`. |

## 2. Análisis y borrador de orden (C)

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 6 | Evidencia: parte confirmado, fotos y tendencia del historian | MET | `app/rag/context.py::build_event_context` arma filas, fotos, tendencia de 6 h (`sensor_trend`), secciones y repuestos; `pipeline.evidence` lo ejecuta con deadline (`ORDER_DEADLINE_S`). |
| 7 | Manuales: tabla de fallas y límites, con cita de cada conclusión | MET | `app/analysis/causes.py` (`TASK_OF`, `CITATION_OF`, `TITLE_OF`, `DIFFERENTIAL_CITATION`); toda causa lleva `citation` y el revisor la valida contra el corpus. |
| 8 | Historial libre con abreviaturas; una falla repetida cambia la causa | MET | `app/analysis/history.py` (cinco patrones, texto normalizado, repetición en el tiempo) + `app/rag/context.py` (historial sin filtrar por equipo, 250 órdenes más recientes) + `app/analysis/analyzer.py::apply_history` (promueve/agrega la causa con su cita y cambia la acción: `T-B-ALI`, `NO-ESTANDAR`). Tests con el archivo real: `tests/test_analysis_history.py` (`ordenes.json`, 243 órdenes; los cinco casos aparecen en B-101/B-102/B-103). |
| 9 | Causas en orden, cada una con evidencia y lo que falta | MET | `app/analysis/models.py::Cause` (`evidence`, `missing`, `confidence`) y `rank_causes`; sin evidencia suficiente la acción es una inspección (`I-VIB`/`I-VAL`). |
| 10 | F09 (cavitación) con la causa raíz en otro equipo; F10 no exige orden | MET | `app/analysis/causes.py::rank_causes` (F09 con `root_equipment`, F10 sin tarea), `tasks_for` devuelve `[]` para F10; tests `test_low_suction_puts_the_root_cause_in_another_equipment`, `test_a_drifting_sensor_does_not_produce_a_work_order`, `test_cavitation_names_the_primary_filter_as_the_root`. |
| 11 | OrdenSistema completa: tareas del catálogo o `NO-ESTANDAR`, `detiene_equipo`, `reduce_inyeccion` con la reserva real, ejecutor, repuestos con disponibilidad/costo, `evento_ids` | MET | `app/domain/orders.py::order_payload`, `app/domain/rules.py::build_proposal` (estado de bombas desde `/api/estado` en el momento de decidir), `app/analysis/analyzer.py::parts_for` (stock y costo unitario). La disponibilidad y el costo viajan en `order_analysis.review.parts` (el contrato `OrdenSistema.repuestos` solo admite código y cantidad; está documentado en el README). |
| 12 | Fotos con un modelo de visión de NVIDIA (empaquetadura, correas, acoples, manómetros, filtros), detecta daño estructural | PARCIAL | `app/vision/nvidia.py` (modelo `meta/llama-3.2-11b-vision-instruct`, JSON estricto, tipo de foto y `structural_damage`), `app/vision/queue.py` (cola), `docker-compose.yml` (variables `VISION_*`/`NVIDIA_API_KEY`), tests `tests/test_vision.py`. **Parcial acotado**: sin `NVIDIA_API_KEY` en el entorno de corrección no se ejecuta contra el servicio real; se valida con dobles HTTP y el modelo queda configurable. |
| 13 | Sin enlace, el análisis de la foto queda en cola; la alerta no depende de él | MET | `PhotoAnalyser.submit`/`drain` (cola en Postgres, `photo_analysis`), `handle_closure`/nota no esperan visión; tests `test_submit_queues_what_cannot_be_analysed`, `test_an_offline_photo_is_not_read_as_no_damage`. |

## 3. Reglas de aprobación y decisión humana (D, 3.3, 3.5)

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 14 | Función pura con las 5 reglas | MET | `app/domain/rules.py::evaluate` (`MAX_PART_COST_USD=2500`, almacén `yacimiento`, ejecutor, inyección, tarea estándar). |
| 15 | Daño estructural grave → revisión humana | MET | `rules.py` (`structural_damage` fuerza pendiente) + `processing/workflow.py::_check_structural_damage` (veredicto de visión o S1 con foto) + `pipeline.run(structural_damage=…)`. La semántica de "análisis fallido" nunca es "sin daño". |
| 16 | Cada pendiente lleva su motivo; única escritura sobre órdenes | MET | `app/domain/orders.py` (payload `motivo`), `app/workflow/decisions.py` (matriz de transiciones y registro en `decisions`), `app/processing/workflow.py::handle_closure` (un cierre no saltea al planificador). |
| 17 | Tests de los bordes: 2.499/2.500, `T-B-VAL`, `TX-ROD-CIG` sin stock, reserva no disponible | MET | `tests/test_rules_orders.py`: `test_the_cost_limit_is_strictly_less_than_2500`, `test_the_valve_kit_is_under_the_limit…`, `test_the_crankshaft_bearing_kit_has_no_stock…`, `test_a_part_with_stock_only_in_central…`, `test_the_annex_bearing_kit_is_pending…`, `test_pump_stop_without_reserve_reduces_injection`. |
| 18 | Checkpoint en Postgres; correlation ID evento ↔ orden ↔ cierre | MET | `app/persistence/schema.sql` (`orders`, `order_analysis.correlation_id`, `closures.correlation_id`), `pipeline.run` guarda `correlation_id=event.id`, `handle_closure` lo copia del análisis; `GET /api/orders/{id}` devuelve orden, análisis, cierre y decisiones. |
| 19 | Sobrevive al corte con el mismo ID y estado, sin duplicarse | MET | `app/main.py::_resume_orders` (re-publica con el estado persistido; borra un `Borrador` huérfano), id determinista `order_id(equipo, tareas, evento_id)` y `open_order` (dedup por tareas). Demostración controlada en §6. |
| 20 | Interfaz por rol: planificador aprueba/rechaza, supervisor cierra, inspector certifica/observa | MET | `app/api/decisions.py`, `app/workflow/decisions.py`, `scripts/orden.py`, consola. El rol está atado al ejecutor y al estado (§4). |
| 21 | Reintentos, deadlines y detección de loops | MET | `NOTE_TIMEOUT_S`, `ORDER_DEADLINE_S`, `MAX_ATTEMPTS`, `MAX_NOTE_STEPS`, `TOKEN_BUDGET` en `app/config.py`; reintentos en tools/ASR/visión; `_review_loop` corta el diálogo y `_within` aplica el presupuesto. Documentado en la mini spec §8. |

## 4. Cierre y certificación (G)

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 22 | `planta/cierres`: transcribe y arma el parte (tareas, repuestos, horas, prueba); la orden pasa a `Ejecutada` | MET | `app/processing/closure.py::parse_closure`, `app/processing/workflow.py::handle_closure`; el parte queda en `closures.parte` y se ve en `GET /api/orders/{id}`/consola. |
| 23 | Comparación con la orden y cada diferencia marcada | MET | `closure.py::compare` (`tarea_faltante`, `tarea_extra`, `repuesto_faltante`, `repuesto_extra`, `cantidad`, `horas`, `prueba`, `precio`); tests `tests/test_closure.py` con `cierres_ejemplo.json` (12 cierres) y los tipos que faltaban. |
| 24 | Propio → `Cerrada`; contratista → `Certificada` con habilita o `Observada` con motivo | MET | `app/workflow/decisions.py` (`TRANSITIONS`, control de ejecutor), tests `tests/test_decisions.py`; demostración §5. |
| 25 | Monto del habilita sale de la orden y `CT-SVP-2025`, no del cierre; validado contra `cierres_ejemplo.json` | MET | `app/domain/billing.py::PriceList.amount_for`, `app/workflow/decisions.py::_certification_amount`; el monto declarado solo se usa para marcar la diferencia (`--monto` / `monto_declarado`). Tests `tests/test_billing.py`, `tests/test_closure.py`. |
| 26 | G2/G3 reproducibles a mano (inactivos en la rúbrica) | MET | Procedimiento y transcripción de la corrida controlada en §5. |

## 5. Demostración manual de G2/G3 (2026-11-25)

Con el stack de desarrollo arriba y órdenes sembradas en la base (el corrector no produce
cierres en `contratista`), se ejecutó:

```bash
# G2: trabajo propio, cerrado por el supervisor después del cierre del técnico
curl -s -X POST localhost:8200/api/orders/OT-DEMO-PROPIO/decision \
  -H 'content-type: application/json' \
  -d '{"role":"supervisor","action":"close","actor":"Luis Soto"}'
# {"orden_id":"OT-DEMO-PROPIO","estado":"Cerrada","rol":"supervisor","accion":"close"}

# G3: contratista observada y después certificada con el monto del contrato
curl -s -X POST localhost:8200/api/orders/OT-DEMO-OBS/decision \
  -H 'content-type: application/json' \
  -d '{"role":"inspector","action":"observe","actor":"Inés Ríos","motive":"declara horas de más"}'
# {"orden_id":"OT-DEMO-OBS","estado":"Observada", ...}

curl -s -X POST localhost:8200/api/orders/OT-DEMO-CONTRATISTA/decision \
  -H 'content-type: application/json' \
  -d '{"role":"inspector","action":"certify","actor":"Inés Ríos","habilita":"HAB-2026-0001","monto_declarado":1300}'
# {"orden_id":"OT-DEMO-CONTRATISTA","estado":"Certificada", ...}

curl -s localhost:8200/api/orders/OT-DEMO-CONTRATISTA
# estado Certificada · habilita HAB-2026-0001 · monto_habilita_usd 780.0 (contrato)
# diferencias: prueba ("el cierre no declara la prueba final"),
#              precio ("declara USD 1300 y el contrato CT-SVP-2025 da USD 780 ...")
```

Controles negativos (devuelven 409 y no cambian la orden):

```text
inspector certifica trabajo propio:
  {"detail":"la certificación es para trabajo de la contratista; esta orden es propia"}
supervisor cierra trabajo de la contratista (Ejecutada):
  {"detail":"el cierre propio lo firma el supervisor; esta orden es de la contratista"}
```

El monto de la habilita es el del contrato (USD 780), no el declarado (USD 1300), y la
diferencia queda registrada en el cierre. La transcripción completa de la corrida está
en `var/audit/entrega2/g2-g3.txt` (local).

## 6. Durabilidad: corte controlado (2026-11-25)

Con una orden `PendienteAprobacion` con su motivo y un `Borrador` huérfano en la base:

```text
antes:    OT-DEMO-PENDING = PendienteAprobacion · motivo "sin stock de TX-ROD-CIG …"
          abiertas = [OT-DEMO-CONTRATISTA-2, OT-DEMO-DRAFT, OT-DEMO-GUARD, OT-DEMO-OBS, OT-DEMO-PENDING]
corte:    docker kill pia-asistente-cerebro-1   (SIGKILL, como el apagón de sin-luz)
después:  OT-DEMO-PENDING = PendienteAprobacion · mismo id y motivo
          abiertas = [OT-DEMO-CONTRATISTA-2, OT-DEMO-GUARD, OT-DEMO-OBS, OT-DEMO-PENDING]
          duplicados = 0 · el Borrador huérfano ya no está
log:      "removed 1 order(s) left in Borrador"
          "resumed order OT-DEMO-PENDING in state PendienteAprobacion"
```

Esto cubre F3 (mismo ID, mismo estado, sin duplicado) con independencia de que el guion de
`sin-luz` tenga o no una orden pendiente antes del apagón. Transcripción en
`var/audit/entrega2/durabilidad.txt` (local).

## 7. Cómo se verifica

| # | Requisito | Estado | Evidencia |
|---|---|---|---|
| 27 | Escenarios `tormenta-perfecta`, `sin-luz`, `contratista`, `fuga-sin-enlace`; métricas D1, D2, F3, G1; eliminatoria `aprobacion_indebida` | MET | Corrida oficial de los cuatro escenarios: **91,2 / 100 · APRUEBA**, sin eliminatorias; D1/D2/G1 100 %. Detalle en `docs/RESULTADOS.md`. |
| 28 | Revisión manual G2/G3 | MET | §5 de este documento. |
| 29 | `docker compose up` levanta el sistema; presupuesto 4 CPU / 8 GB | MET | `scripts/check_compose_budget.py`: 4/4 CPU y 7,375/8 GiB, red, label y proxies en regla; `docker compose config` válido. |
| 30 | Repo público `nombre-apellido`, con `README.md`, `docker-compose.yml` y `tests/` | MET | `https://github.com/Ramon-Ariel-ET12/ramon-lugones-academiaNovit2026` (renombrado desde `ramon-ariel`); `master` con la Entrega 2 publicada. Nota: el enunciado pide `nombre-apellido` y el repo se llama `ramon-lugones-academiaNovit2026`; se documenta la desviación. |
| 31 | Tests automatizados y suite de evaluación | MET | 302 pruebas (301 sin la de integración de Postgres), `ruff` y `mypy` limpios; `evaluacion/retrieval_eval.py` (71 preguntas) y el corrector oficial. |
| 32 | Registro de cada paso: modelo, herramientas, tokens, costo y tiempo | MET | `usage_log` (`app/persistence/queue.py::record_usage`): ASR, parser, LLM opcional y visión (`task='vision'`, tokens de la API y latencia); `decisions`/`human_decisions` registran actor, rol y `correlation_id`. |

## 8. Brechas y techos documentados

- **Visión sin clave**: el análisis real contra NVIDIA no se ejecuta en la corrección
  (no hay `NVIDIA_API_KEY` en el entorno). El cliente, la cola y el veredicto están
  cubiertos con dobles; el modelo y el costo están en `INFORME.md` §2.4. Sin clave o sin
  enlace la foto queda en cola y la alerta no depende de ella.
- **F3 = 0 en `sin-luz`**: el apagón del escenario cae cuando no hay una orden pendiente
  antes del corte. La durabilidad se demuestra con el corte controlado de §6.
- **E1/E2**: el reloj de la planta corre a 1800× durante el corte; el ASR tarda segundos
  reales y la tablet no llega a responder dentro de la ventana. En `fuga-sin-enlace` la
  nota del corte sí se respondió (1/1). Es un techo de guion, no del flujo.
- **Una orden por equipo**: cuando el historial señala un filtro o el tanque como causa
  raíz, la orden sigue siendo del equipo del evento (el análisis nombra el equipo aguas
  arriba en `root_equipment` y en la evidencia). No se abren órdenes sobre otros equipos.
- **Puntuador del curso**: `correccion/puntuar.py` revienta con `bien += ok` cuando una
  orden pendiente trae `motivo`. La corrida local usa una copia parcheada (`bool(...)`);
  sin ese parche, un sistema que publique pendientes con motivo no se puede puntuar. La
  copia pública del corrector todavía no lo corrige.

## 9. Reproducir

```bash
# suite y estáticos
TEST_DATABASE_URL="postgresql://pia:pia-local-dev@<db>:5432/pia" uv run pytest -q
uv run ruff check . && uv run mypy app

# presupuesto, RAG y punta a punta
uv run python scripts/check_compose_budget.py
uv run python evaluacion/retrieval_eval.py
uv run python scripts/e2e_probe.py --reiniciar

# corrección oficial de los cuatro escenarios (para el stack de desarrollo antes)
ESCENARIOS="tormenta-perfecta sin-luz contratista fuga-sin-enlace" ./scripts/verificar.sh

# decisiones humanas
uv run python scripts/orden.py pendientes
uv run python scripts/orden.py ver <OT>
uv run python scripts/orden.py certificar <OT> --actor "Inés Ríos" --habilita HAB-2026-0001 --monto 1300
```
