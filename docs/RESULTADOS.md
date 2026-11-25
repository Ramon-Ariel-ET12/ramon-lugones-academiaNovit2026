# Resultados de la evaluación oficial

## Entrega 2 · los cuatro escenarios del Anexo 2

Corrida oficial de cierre del **2026-11-25 00:08** (commit `21bcef8`) con los cuatro
escenarios del anexo, sobre el `docker-compose.yml` del repo:

```bash
ESCENARIOS="tormenta-perfecta sin-luz contratista fuga-sin-enlace" ./scripts/verificar.sh
# equivale a
uv run --with httpx --with pyyaml python academia2026-tp/correccion/corregir.py \
  --repo . --alumno "Ramón Ariel" \
  --escenarios tormenta-perfecta sin-luz contratista fuga-sin-enlace
```

Los artefactos quedan en `academia2026-tp/correccion/corridas/academiaNovit2026/`
(`informe.md`, `resultado.json`, un JSON por escenario, los logs y `meta.json`).

**89,4 / 100 · APRUEBA** (mínimo 60). **Sin faltas eliminatorias.**

| Criterio | Peso | Valor | Puntos |
|---|---:|---:|---:|
| A1 Cobertura | 5 | 93 % | 4,63 |
| A2 Borrador al primer intento | 10 | 69 % | 6,91 |
| A3 Parte final correcto | 8 | 73 % | 5,86 |
| A4a Pregunta cuando hace falta | 4 | 100 % | 4,00 |
| A4b No pregunta de más | 3 | 97 % | 2,91 |
| B1 Sin novedad / Escalado | 10 | 93 % | 9,28 |
| B2 Alerta de seguridad | 10 | 100 % | 10,00 |
| D1 Reglas de aprobación | 15 | 100 % | 15,00 |
| D2 Orden adecuada a la falla | 10 | 100 % | 10,00 |
| E1 Sigue andando sin enlace | 3 | 50 % | 1,50 |
| E2 Pendientes visibles | 3 | 100 % | 3,00 |
| E3 Sin duplicados | 4 | 100 % | 4,00 |
| F1 Mensajes válidos | 2 | 100 % | 2,00 |
| F2 Latido | 1 | 100 % | 1,00 |
| F3 Sobrevive al corte de luz | 2 | **0 %** | 0,00 |
| G1 Orden ejecutada | 3 | 100 % | 3,00 |
| G2 Cierre propio | 2 | inactivo | – |
| G3 Certificación de la contratista | 5 | inactivo | – |

Detalle por escenario (de `resultado.json`):

- **D1**: tormenta-perfecta 3 órdenes decididas, sin-luz 3, contratista 3; todas
  Aprobada o Pendiente según las cinco reglas, con motivo en las pendientes.
  `fuga-sin-enlace` no decidió órdenes.
- **D2**: una falla por escenario, con orden sobre el equipo correcto — F02-B-102 en
  tormenta, F07-F-201B en sin-luz, F03-B-101 en contratista.
- **G1**: un cierre en tormenta y otro en sin-luz (F-201A, `T-F-CAR`, trabajo propio);
  las dos órdenes pasaron a `Ejecutada`. La corrida de contratista no recibió cierres.
- **E2** dio 100 %: el sistema avisó los pendientes durante los dos cortes y los dejó en
  cero cuando volvió el enlace.
- **F3**: el apagón de `sin-luz` cae cuando no había ninguna orden pendiente antes del
  corte, así que el criterio mide 0 por el guion, no por el sistema. La durabilidad se
  demuestra aparte con un corte controlado del contenedor (misma id y estado, sin
  duplicado) — ver [`VERIFICACION_ENTREGA_2.md`](VERIFICACION_ENTREGA_2.md).
- **E1**: en tormenta-perfecta el reloj de la planta corre a 1800× durante el corte y
  las notas caen en segundos reales: la tablet no llega a responder dentro de la ventana.
  En `fuga-sin-enlace` la nota del corte sí se respondió (1/1).

**Variación entre corridas.** La misma suite dio **91,2** el 2026-11-21 (commit `bdd2976`)
y **85,8** el 2026-11-25 antes del commit final, con los mismos D1/D2/G1 al 100 %. La
diferencia está en A1/A2/A3/B1, que dependen de la voz que elige el simulador, del ASR
local y de si el operador virtual alcanza a contestar antes del corte; los criterios
deterministas (reglas, orden, cierre y mensajes) se mantuvieron estables.

**Nota sobre el puntuador.** La copia local del corrector lleva un parche sin commitear en
`correccion/puntuar.py`: cuando una orden `PendienteAprobacion` trae `motivo`, la expresión
original `bien += ok` recibe un string y aborta con `TypeError`. El parche envuelve el
resultado en `bool(...)`; sin él, esta corrida (que sí publica pendientes con motivo) no se
puede puntuar. La copia pública del corrector todavía no lo corrige.

**Pruebas y verificación.** 302 pruebas (301 sin la integración contra Postgres), `ruff` y
`mypy` limpios; presupuesto de recursos, RAG y punta a punta del `scripts/verificar.sh`.
La matriz requisito por requisito de esta entrega, la demostración manual de G2/G3 y el
corte controlado de durabilidad están en
[`VERIFICACION_ENTREGA_2.md`](VERIFICACION_ENTREGA_2.md).

## Entrega 1 · escenarios obligatorios

Corrida ejecutada con la planta en modo corrección y el sistema levantado desde el
`docker-compose.yml` del repo:

```bash
uv run --with httpx --with pyyaml python academia2026-tp/correccion/corregir.py \
  --repo . --alumno "Ramón Ariel" \
  --escenarios martes-tranquilo fuga-sin-enlace
```

Es el comando canónico del corrector, sin `--sin-construir` y **sin variables de
entorno**: el build del sistema resuelve `planta_contrato` por sí mismo. La corrida del
**2026-11-10 17:39** (commit `b9fa0ff`) queda en `academia2026-tp/correccion/corridas/academiaNovit2026/`
(`informe.md`, `resultado.json`, un JSON por escenario y los logs).

## Nota

**91,3 / 100 · APRUEBA** (mínimo 60). **Sin faltas eliminatorias.** 57,5 puntos sobre
63 medidos; D1/D2/F3/G1 no aplican porque estos dos escenarios no tienen fallas de equipo
ni cierres, y la nota se reescala.

| Criterio | Peso | Valor | Puntos |
|---|---:|---:|---:|
| A1 Cobertura | 5 | 100 % | 5,00 |
| A2 Borrador al primer intento | 10 | 69 % | 6,94 |
| A3 Parte final correcto | 8 | 69 % | 5,56 |
| A4a Pregunta cuando hace falta | 4 | 100 % | 4,00 |
| A4b No pregunta de más | 3 | 100 % | 3,00 |
| B1 Sin novedad / Escalado | 10 | 100 % | 10,00 |
| B2 Alerta de seguridad | 10 | 100 % | 10,00 |
| E1 Sigue andando sin enlace | 3 | 100 % | 3,00 |
| E2 Pendientes visibles | 3 | 100 % | 3,00 |
| E3 Sin duplicados | 4 | 100 % | 4,00 |
| F1 Mensajes válidos | 2 | 100 % | 2,00 |
| F2 Latido | 1 | 100 % | 1,00 |

La corrida guardada da **91,3**. Una verificación posterior sobre el mismo árbol
(`scripts/verificar.sh`, commit `5cdbbd9`) dio **88,8 · APRUEBA**, también sin
eliminatorias: A2 64 %, A3 69 % y A4a 75 %. En esa corrida el ASR perdió la cláusula de
la B-102 en `NOTA-00011`, así que el borrador salió sin esa lectura y sin la ambigüedad
"la bomba"; el operador la corrigió por voz ("Te faltó la dos") y el segundo borrador
quedó completo y confirmado. La variación viene del simulador: elige una voz de operador
distinta cada vez y el ASR local transcribe distinto. Corridas anteriores al arreglo:
88,8 / 89,2 / 82,4 / 73,5.

## Lectura de los resultados

### Parte por voz (A)

- **A1 100 %**: las 13 notas del operador tuvieron pantalla de tablet. Incluye las notas
  que solo traen observaciones (borrador informativo con filas sin valor) y las ambiguas.
- **A2 69 % / A3 69 %**: en `martes-tranquilo` se confirmaron 8 de 9 notas al primer
  borrador y 8 de 9 al final; en `fuga-sin-enlace`, 2 de 4. Las notas no confirmables son
  del mecanismo del operador virtual, no del flujo:
  - `NOTA-00008` y `NOTA-00006` dicen solo “la bomba está parada, en reserva”: el sistema
    pregunta el equipo y manda un borrador con una fila **sin valor**; el operador virtual
    solo confirma cuando puede comparar valores.
  - `NOTA-00001` es la condición insegura S1: la respuesta correcta es la alerta, no un
    borrador que se confirma.
- **A4a 100 %**: se preguntó en las tres notas ambiguas (`NOTA-00008` y `NOTA-00011` en
  `martes-tranquilo`, `NOTA-00006` en `fuga-sin-enlace`). El caso `NOTA-00011` se recuperó
  con dos correcciones del parser: el punto de la abreviatura (`1600 p.c.`) y la “y”
  espuria entre la lectura y la variable (`1600 p.c. y de descarga`) ya no cortan la
  cláusula, así que la lectura sobrevive y “la bomba” vuelve como pregunta.
- **A4b 100 %**: ninguna nota clara recibió preguntas de más.
- **Aciertos por campo**: 22 de 22 lecturas con TAG, valor y unidad correctos
  (`scripts/audit_escenario.py`), incluidas las notas que necesitaron corrección.

### Detección (B)

- **B1 100 %**: una decisión por equipo y nota, `SinNovedad` en todos los casos de estos
  escenarios; el pico aislado y “parada, en reserva” no escalaron.
- **B2 100 %**: la alerta S1 salió **20,4 s** después de la nota y el aviso de emergencia
  en la tablet a los **18,2 s**, con `espera_respuesta: false` y **sin falsas alarmas**.
  La alerta se publica desde la transcripción parcial: el primer segmento que nombra un
  disparador no espera al audio completo.

### Sin enlace (E)

- **E1 100 %**: las notas durante el corte tuvieron respuesta en la tablet dentro de la
  ventana del corte.
- **E2 100 %**: durante el corte el latido informó `enlace_ok=false` con pendientes > 0 y
  volvió a cero con el enlace restablecido.
- **E3 100 %**: sin eventos ni órdenes duplicadas.

### Robustez (F)

- **F1 100 %**: 76 mensajes publicados en `martes-tranquilo` y 41 en `fuga-sin-enlace`,
  todos válidos contra `planta_contrato`.
- **F2 100 %**: latido regular cada 30 s, sin huecos (28 y 23 latidos).

### Lo que estos escenarios no ejercitan

`martes-tranquilo` y `fuga-sin-enlace` no tienen fallas de equipo, cortes de luz ni
cierres. Por eso D1, D2, F3 y G1 quedan “sin datos” en la corrida. Están implementados y
cubiertos por pruebas unitarias (`tests/test_rules_orders.py`, `tests/test_sync_history.py`,
`tests/test_events_sensors.py`); una corrida con `tormenta-perfecta`, `sin-luz` o
`contratista` los ejercita de punta a punta.

## Evaluaciones complementarias

- **Verificación independiente de la corrida**: `scripts/audit_escenario.py` recalcula los
  criterios desde el registro MQTT y la verdad de campo, sin usar el puntuador oficial.
  Resultado: A1 13/13 notas con borrador, A2 10/13, A3 10/13, A3b 22/22 campos con
  TAG+valor+unidad, A4a 3/3, A4b 9/9, B1 22/22, alerta S1 en 20,4 s reales,
  0 alertas falsas, 0 duplicados, 0 mensajes inválidos.
- **ASR local**: mediana 3,3 s por nota en esta corrida; máximo 17,6 s en la primera nota
  de `fuga-sin-enlace`, con el índice RAG construyéndose en paralelo sobre las mismas
  3 CPU. Ese máximo es el que fija la latencia de la alerta S1.
- **RAG**: hit@5 0,873 / recall@5 0,718 / MRR 0,678 contra BM25 0,859 / 0,674 / 0,581;
  distractor@5 (Rev. C antes que D) 0 contra 6 de 71. Medido con
  `corpus.evaluar.evaluar(buscar, suite)`; los dos evaluadores coinciden al milésimo.
  Informe: `evaluacion/informe_retrieval.json`.
- **Pruebas**: 169 pruebas, 0 fallos con `TEST_DATABASE_URL` apuntando a la base del
  compose (168 sin la de integración, que se saltea si la variable no está); `ruff check .`
  limpio.
- **Punta a punta con el operador virtual**: 9 flujos (inspección normal, ambigüedad,
  unidades, corrección por voz, pico vs. desvío sostenido, S1–S4 incluyendo sin enlace,
  operación sin enlace, reinicio y notas `VIVO-`). Detalle en
  [`END_TO_END_TEST_REPORT.md`](END_TO_END_TEST_REPORT.md).
