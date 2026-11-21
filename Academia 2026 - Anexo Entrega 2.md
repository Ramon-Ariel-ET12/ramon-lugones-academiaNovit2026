# ACADEMIA NOVIT 2026 · ANEXO DE TP

# Anexo Entregas

## TP Planta de inyección: contenido de cada entrega

---

## 01. CRONOGRAMA

| ENTREGA | FECHA | MÓDULOS YA DADOS | FOCO                                                                                                       | ESCENARIOS QUE TIENE QUE PASAR                |
| ------- | ----- | ---------------- | ---------------------------------------------------------------------------------------------------------- | --------------------------------------------- |
| 2       | 20/11 | 3.1 a 3.4        | Del evento a la orden: workflow, reglas en código, aprobación humana con proceso persistido, fotos, cierre | `tormenta-perfecta`, `sin-luz`, `contratista` |

---

## 02. ENTREGA 2

**Análisis, orden de trabajo, aprobación humana y cierre.**

### Orquestación (3.1, 3.2)

- Workflow explícito con LLM usado en la entrega anterior:
  - Escalado.
  - Análisis.
  - Borrador de orden.
  - Reglas.
  - Aprobada o Pendiente.
- Diagrama en el README que muestre qué parte es workflow fijo y qué parte es agente.
- Ruteo por tipo de mensaje:
  - Seguridad.
  - Parte.
  - Sensor.
  - Respuesta del operador.
  - Cierre.
- Un paso revisor:
  - Verifica que cada cita exista y esté vigente.
  - Verifica que cada repuesto esté en la lista de materiales.

### C · Análisis y borrador de orden

**Evidencia:** parte confirmado, fotos y tendencia del historian.

**Manuales:** tabla de fallas y límites, con la cita de cada conclusión.

**Historial (`/api/historial-ordenes?equipo=`):**

Es texto libre de campo, con abreviaturas. Una falla que se repite cambia la causa probable:

- B-101 con vibración que no se fue cambiando válvulas: era el acople.
- B-103 con empaquetadura que dura semanas: émbolo rayado.
- Válvulas gastadas en dos bombas en pocos días: cartucho roto en el F-201B.
- B-102 que cavita: filtro primario colmatado.
- Consumo de aceite de la B-102: retén del piñón.

**Causas en orden:**

Cada causa debe incluir:

- Su evidencia.
- Lo que falta para confirmarla.

Si la evidencia no alcanza, la acción es una inspección (`I-VIB` o `I-VAL`).

**Casos especiales:**

- **F09 (cavitación):** la causa raíz está en otro equipo (filtro o tanque).
- **F10 (sensor con deriva):** no exige orden.

**OrdenSistema completa:**

- Tareas con códigos del catálogo o `NO-ESTANDAR`.
- `detiene_equipo`.
- `reduce_inyeccion`, según la disponibilidad real de la reserva en ese momento.
- Ejecutor.
- Repuestos con disponibilidad (yacimiento o central) y costo unitario.
- `evento_ids`.

---

### D · Reglas de aprobación en código

Una función pura con las 5 reglas:

1. Tarea estándar.
2. Se mantiene la inyección.
3. Stock en el almacén del yacimiento.
4. Costo menor a USD 2.500.
5. Personal propio.

**Revisión humana obligatoria:**

Si las fotos muestran daño estructural grave, va siempre a revisión humana (B-101 en `fuga-sin-enlace`).

- Cada orden `Pendiente` lleva su motivo.
- Es la única escritura sobre órdenes.

**Tests de cada regla con casos límite:**

- USD 2.499 y 2.500.
- `T-B-VAL` (USD 1.900).
- `TX-ROD-CIG`, sin stock en el yacimiento.
- Reserva no disponible.

---

### Durabilidad y aprobación humana (3.3, 3.5)

- La orden pendiente queda suspendida con un checkpoint en Postgres.
- Un correlation ID une evento, orden y cierre.
- Sobrevive a que el contenedor se apague de golpe (el corte de luz de `sin-luz` mata los contenedores con label `pc`):
  - Vuelve con el mismo ID.
  - Vuelve con el mismo estado.
  - Sin duplicarse.

**Interfaz propia (CLI, API o web) para:**

| Rol          | Acción                |
| ------------ | --------------------- |
| Planificador | Aprobar o rechazar    |
| Supervisor   | Cerrar                |
| Inspector    | Certificar u observar |

El contrato no trae canal para estas decisiones.

**Otros requisitos:**

- Reintentos.
- Deadlines.
- Detección de loops.

---

### Multimodal

- Fotos con un modelo de visión de NVIDIA de la lista:
  - Empaquetadura.
  - Correas.
  - Acoples.
  - Manómetros.
  - Filtros.
- Detecta daño estructural.
- Sin enlace, el análisis de la foto queda en cola.
- La alerta no depende de él.

---

### G · Cierre y certificación

**`planta/cierres`:**

Transcribe y arma el parte de cierre con:

- Tareas hechas.
- Repuestos usados.
- Horas.
- Resultado de la prueba (ejemplo: "probé a ciento diez kilos, sin pérdida").

La orden pasa a `Ejecutada`.

**Comparación del cierre con la orden:**

- Tareas pedidas contra tareas hechas.
- Repuestos reservados contra repuestos usados.
- Marca cada diferencia.

**Según el tipo de trabajo:**

- **Trabajo propio:** el supervisor lo deja `Cerrado`.
- **Trabajo de la contratista:** el inspector lo deja:
  - `Certificado`, con habilita (número y monto).
  - `Observado`, con motivo.

**Cálculo del monto de la habilita:**

- Sale de la orden y de la lista de precios de `CT-SVP-2025`.
- No sale de lo que declara el cierre.
- Se valida contra `cierres_ejemplo.json`, que trae:
  - Movilización mal cobrada.
  - Horas extra.
  - Lista de precios vieja.

---

## Cómo se verifica

**Escenarios:**

- `tormenta-perfecta`
- `sin-luz`
- `contratista`
- `fuga-sin-enlace` (para el caso de daño estructural).

**Métricas:** D1, D2, F3 y G1.

**Eliminatoria que aplica:** `aprobacion_indebida`.

**Revisión manual:**

G2 y G3 (cierre propio y certificación) se revisan a mano: están desactivados en la rúbrica.

---

# ACADEMIA NOVIT 2026

_Enseñamos lo que sabemos._

**Desarrollo de Agentes IA y Software Agéntico.**

Formación anual, gratuita, abierta y 100% online.
