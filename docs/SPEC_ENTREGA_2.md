# Mini spec · Entrega 2: análisis, orden, aprobación humana y cierre

Especificación de trabajo del camino que va del evento escalado a la orden cerrada. El
contrato de mensajes es `planta_contrato` (instalado con pip); acá se describe el
comportamiento del sistema, no se duplican los modelos. La Entrega 1 está en
[`SPEC_PARTE.md`](SPEC_PARTE.md).

## 1. Entradas

| Entrada | Origen | Qué se hace |
|---|---|---|
| Evento `Escalado` | nuestro propio detector (parte o sensor) | Se analiza y puede generar una orden |
| Parte confirmado | workflow de la Entrega 1 | Filas del parte (TAG, variable, valor, unidad, observación) |
| Fotos | `/media/fotos/...` del simulador | Se archivan y se encolan para visión; nunca bloquean |
| Tendencia | `GET /api/historian/{tag}/{variable}` (6 h) | Síntomas con número (no con adjetivos) |
| Historial | `GET /api/historial-ordenes?equipo=` (2 años, texto libre) | Falla que se repite cambia la causa probable |
| Manuales | corpus indexado (`rag_chunks`) | Cada causa cita su sección (MBP-4 §6.x/§7.x) |
| Contrato | `CT-SVP-2025` §2.1 (indexado) | Precio del habilita |
| Cierre | `planta/cierres` (`NotaCierre`) | Transcripción, parte de cierre y comparación |

## 2. Pasos del pipeline (`app/workflow/pipeline.py`)

```
evento ─▶ evidencia ─▶ síntomas ─▶ causas + historial ─▶ revisor ─▶ borrador ─▶ reglas ─▶ publicación
```

1. **Evidencia** (`build_event_context`): filas, fotos, tendencia de las últimas 6 h,
   secciones citadas del manual, últimas órdenes del equipo y repuestos disponibles.
   Tiene deadline propio (`ORDER_DEADLINE_S`, 120 s); si se pasa, se sigue con el parte.
2. **Síntomas** (`analysis/signatures.py`): un `Symptom` por hecho anómalo, con el número
   que lo sostiene. La oscilación de la descarga (F02) se detecta como dispersión
   (máx−mín ≥ 2 kg/cm²), no como nivel.
3. **Causas** (`analysis/causes.py`): ordenadas por confianza, cada una con `citation`,
   `evidence`, `missing` y `task_code`. Reglas tomadas de la matriz de firmas (§6.2) y de
   las tablas diferenciales (§7.1 vibración, §7.4 succión, §7.5/§7.6 diferencial,
   §7.7 goteo). F09 pone la causa raíz fuera de la bomba; F10 no requiere orden.
4. **Historial** (`analysis/history.py`): los cinco casos recurrentes del anexo, buscados
   sobre el texto libre con tolerancia a abreviaturas y errores, exigiendo repetición en
   el tiempo (no un antecedente viejo suelto). Un hallazgo refuerza una causa que la
   evidencia ya sostiene; nunca inventa una causa nueva.
5. **Revisor** (`analysis/review.py`): toda cita debe existir y estar vigente en el índice;
   todo repuesto debe estar en la lista de materiales del equipo. Cita ausente o vencida
   ⇒ la orden **no se publica**. Stock faltante ⇒ se informa y la orden nace pendiente.
6. **Borrador y reglas**: `make_proposal` + `evaluate` (cinco reglas, ver §3). Se publica
   `Borrador` y enseguida `Aprobada` o `PendienteAprobacion` con `motivo`.
7. **Persistencia**: `order_analysis` guarda causas, citas, hallazgos del revisor, partes
   con stock/costo y `correlation_id` (= id del evento). La orden guarda `evento_ids`.

## 3. Reglas de aprobación (función pura, `app/domain/rules.py`)

Se aprueba sola solo si: (1) la tarea es estándar para el equipo; (2) la inyección se
mantiene (el equipo sigue en marcha o hay bomba de reserva parada); (3) todo repuesto
tiene stock en el almacén del yacimiento; (4) el costo de repuestos es **menor** a
USD 2.500; (5) el ejecutor es personal propio. Cualquier otra cosa → `PendienteAprobacion`
con motivo. Daño estructural (visión o S1 con foto) y estado de planta desconocido fuerzan
revisión humana. Los tests cubren los bordes: USD 2.499 y 2.500, `T-B-VAL` (USD 1.900),
`TX-ROD-CIG` sin stock en el yacimiento, y reserva no disponible.

## 4. Decisión humana (interfaz propia)

| Rol | Acción | Transición válida |
|---|---|---|
| Planificador | `approve` / `reject` | `PendienteAprobacion` → `Aprobada` / `Rechazada` |
| Supervisor | `close` | `Ejecutada` (trabajo propio) → `Cerrada` |
| Inspector | `certify` / `observe` | `Ejecutada` → `Certificada` (con habilita y monto) / `Observada` (con motivo) |

- `POST /api/orders/{id}/decision` con `{role, action, actor, motive?, habilita?}`;
  rechazar y observar exigen motivo; certificar exige número de habilitación y monto.
- Toda decisión se registra en `decisions` con actor, rol y `correlation_id`, y el nuevo
  estado se publica validado contra `OrdenSistema`.
- Rechazos por estado incorrecto devuelven 409 con el motivo, no un estado inconsistente.

## 5. Durabilidad

- La orden pendiente es una fila en `orders` más su `payload`; al arrancar se re-publican
  las órdenes abiertas con el mismo id y estado (`_resume_orders`), nunca como `Borrador`.
- El corte de luz de `sin-luz` mata los contenedores con `academia.planta=pc`;
  `restart: unless-stopped` los levanta y la orden pendiente sobrevive. No se duplica: el
  id es determinista (`order_id(equipo, tareas, evento_id)`) y `open_order` evita una
  segunda orden abierta con las mismas tareas.
- `correlation_id` une evento, análisis y cierre; `GET /api/orders/{id}` los devuelve juntos.

## 6. Cierre y certificación

1. `planta/cierres` → se descarga el audio y se transcribe con el ASR local (presupuesto
   de tiempo propio).
2. `parse_closure` extrae tareas hechas, repuestos usados (con cantidad), horas y prueba.
3. `compare` marca cada diferencia: `tarea_faltante`, `tarea_extra`, `repuesto_faltante`,
   `repuesto_extra`, `cantidad`, `horas` (solo exceso grave sobre las incluidas),
   `prueba` (sin prueba declarada) y `precio` (monto declarado distinto del contrato o
   lista anterior a 2025). La orden pasa a `Ejecutada`.
4. El monto del habilita sale de las tareas de la orden y de `CT-SVP-2025` §2.1
   (`app/domain/billing.py`): precio cerrado por ítem, `I-VIB` por equipo medido, trabajo
   iniciado antes de 2025 ⇒ lista anterior, que no está en el corpus ⇒ monto desconocido.
5. `cierres_ejemplo.json` es el oráculo: los 12 cierres reproducen sus diferencias y su
   monto (tests `test_closure.py`).

## 7. Fotos y visión

- `app/vision/nvidia.py`: cliente de la API compatible con OpenAI de NVIDIA, con tipo de
  imagen por *magic bytes*, respuesta JSON estricta, reintento solo en errores transitorios
  y sin registrar la clave ni la imagen.
- `app/vision/queue.py`: `submit` analiza lo que puede y encola el resto (`photo_analysis`);
  `drain` corre en su propia tarea y se detiene si el enlace está caído.
- El veredicto (`structural_damage`) marca el equipo para revisión humana; un análisis
  fallido no se interpreta como "sin daño". La alerta de seguridad no depende de esto.

## 8. Presupuestos y bucles

- `ORDER_DEADLINE_S` (120 s) para evidencia y análisis de fotos de una orden.
- `NOTE_TIMEOUT_S` (180 s) para el pipeline de la nota (incluye la transcripción).
- Reintentos: tools (1), ASR/plant (3 con backoff), visión (2 solo en transitorios).
- Bucles: el diálogo de la tablet está acotado por `MAX_ATTEMPTS`/`MAX_NOTE_STEPS` y corta
  cuando dos correcciones seguidas no cambian el borrador.
