# INFORME técnico · modelos y costos

## 1. Decisión de arquitectura de modelos

La primera entrega exige que el parte por voz, la detección y la alerta de condición
insegura funcionen **sin enlace y sin GPU**, en una PC de planta de 4 núcleos y 8 GB. La
segunda agrega el análisis de la anomalía, el borrador de orden, las reglas de
aprobación, la decisión humana y el cierre, y una foto que se analiza en la **nube de
NVIDIA** cuando hay enlace. Por eso:

- La transcripción y la extracción corren **en la planta**.
- La detección de seguridad y las reglas de aprobación son **código determinista**, no
  un modelo: una alerta falsa cuesta más que una detección perdida y el resultado debe
  ser idéntico con los mismos datos.
- El único modelo de lenguaje es **opcional** y secundario: interpreta respuestas
  libres que el lector determinista no entiende. Nunca decide una regla ni una alerta.

> **Nota de alcance.** El enunciado menciona una "lista cerrada" de modelos, pero esa
> lista no fue provista en el repositorio, en los anexos ni en el sitio público. Se
> eligen modelos locales de uso libre que entran en el hardware exigido, más un modelo de
> visión de NVIDIA para las fotos, y todos los identificadores son configurables por
> variable de entorno para poder sustituirlos si la cátedra publica la lista.

## 2. Modelos usados

### 2.1 Transcripción (local, CPU)

| Campo | Valor |
|---|---|
| Nombre | `Systran/faster-whisper-small` |
| Arquitectura | Whisper small (encoder-decoder Transformer) |
| Proveedor | Systran / comunidad OpenAI Whisper; runtime CTranslate2 |
| Versión del runtime | `faster-whisper 1.2.1`, `ctranslate2 4.8.5` |
| Parámetros | 244 M |
| Licencia | MIT |
| Página | <https://huggingface.co/Systran/faster-whisper-small> |
| Ejecución | contenedor `cerebro`, CPU, `compute_type=int8`, 4 hilos, VAD, `beam_size=5`, `language=es` |
| Memoria aproximada | 0,8–1,2 GB |
| Descarga | horneada en build; `local_files_only=True` en runtime |

Entrada: WAV 16 kHz mono servido por `sim:8100`. Prompt de dominio con TAGs, variables
y unidades para mejorar números y nombres de equipo. La latencia se mide en
`scripts/benchmark_asr.py`; el resultado está en la sección 3.

### 2.2 Embeddings del RAG (local, CPU)

| Campo | Valor |
|---|---|
| Nombre | `sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2` |
| Proveedor | Sentence-Transformers / UKPLab |
| Versión del runtime | `fastembed 0.9.1` (ONNX Runtime, sin PyTorch) |
| Parámetros | 118 M |
| Dimensión | 384 |
| Licencia | Apache-2.0 |
| Página | <https://huggingface.co/sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2> |
| Ejecución | CPU, ONNX, 701 fragmentos indexados en pgvector (HNSW) |
| Memoria aproximada | 0,2–0,4 GB |

Se combina con BM25 en español y re-ranking por metadata (vigencia, fabricante,
equipo, modelo). La evaluación está en la sección 4.

### 2.3 Modelo de lenguaje local opcional

| Campo | Valor |
|---|---|
| Nombre | `Qwen/Qwen2.5-0.5B-Instruct` |
| Proveedor | Alibaba Qwen |
| Versión | Qwen2.5, 0,49 B parámetros |
| Licencia | Apache-2.0 |
| Página | <https://huggingface.co/Qwen/Qwen2.5-0.5B-Instruct> |
| Runtime | `transformers 5.22.2` + `torch 2.15.0+cpu`, `langchain-huggingface`, CPU |
| Uso | interpretar respuestas libres del operador cuando el lector determinista no encuentra una acción; salida JSON validada con Pydantic `extra="forbid"` |
| Activación | `LLM_ENABLED=true` y build con `--build-arg DOWNLOAD_LLM=1`; por defecto `false` y no horneado en el camino evaluado |
| Memoria aproximada | 1,5–2,5 GB en float32 |

No se usa para: detectar seguridad, decidir la tarea, aprobar órdenes, calcular
límites ni interpretar valores del parte. Esas decisiones son código.

### 2.4 Modelo de visión en la nube

| Campo | Valor |
|---|---|
| Nombre | `meta/llama-3.2-11b-vision-instruct` |
| Proveedor | Meta (modelo) servido por **NVIDIA NIM** |
| Versión | Llama 3.2 Vision 11B, instruction-tuned; 11 000 M de parámetros; entrada texto + imagen, salida texto; contexto 128K, salida máxima 4K |
| Licencia | Llama 3.2 Community License |
| Página de referencia | <https://build.nvidia.com/meta/llama-3.2-11b-vision-instruct> |
| API | OpenAI-compatible (`POST /chat/completions`), `https://integrate.api.nvidia.com/v1` |
| Ejecución | contenedor `cerebro`, solo a través del proxy del enlace; `VISION_ENABLED=true` y `NVIDIA_API_KEY`; sin clave o sin enlace la foto queda en cola |
| Entrada | una foto de campo (JPEG/PNG/WebP) + un prompt cerrado que pide un JSON de cuatro campos |
| Salida | `{"kind", "structural_damage", "severity", "observations"}`, validada con Pydantic `extra="forbid"` |
| Uso | tipo de foto (empaquetadura, correas, acople, manómetro, filtro), daño estructural y severidad; el veredicto marca la orden para revisión humana |
| No se usa para | la alerta de seguridad, las reglas de aprobación, la tarea ni el monto del habilita |

**Tokens por foto.** El modelo factura la imagen troceada en *tiles* de 560 px (hasta 4,
≈1 601 tokens cada uno según la arquitectura Mllama) más el prompt (≈250 tokens) y la
salida acotada a 300 tokens: una foto típica queda en el orden de **≈6 800–7 100 tokens
de entrada** y menos de 100 de salida. El número exacto no se estima: el cliente lee
`usage.prompt_tokens`/`usage.completion_tokens` de cada respuesta y lo registra en
`usage_log` con `task='vision'`, junto con la latencia del intento que respondió. En las
pruebas con dobles (sin clave) se fijan 812/47 y 6 400/52 tokens para verificar el camino.

**Costo.** NVIDIA NIM publica este modelo con nivel gratuito (USD 0) en
<https://build.nvidia.com/meta/llama-3.2-11b-vision-instruct>; la misma página lista una
ruta paga de referencia a USD 0,35 por millón de tokens de entrada y de salida. A ese
precio, una foto de ≈7 100 tokens cuesta **≈USD 0,0025**; con el nivel gratuito, USD 0.
El costo se registra por llamada en `usage_log` (hoy 0) para que el número sea auditable
si cambia el proveedor.

> `nube-sync` sigue siendo un servicio de archivo, no un modelo. La única llamada a un
> modelo en la nube es la visión, y es opcional: la planta opera y alerta sin ella.

## 3. Consumo y latencia del ASR

Se ejecuta:

```bash
uv run python scripts/benchmark_asr.py --dir academia2026-tp/datos/voces \
  --model var/models/faster-whisper-small
```

| Métrica | Resultado medido |
|---|---|
| Notas medidas | 102 (todas las voces del banco provisto) |
| WER medio (palabras) | 0,252 (incluye dígitos vs. palabras: "112" contra "ciento doce") |
| Latencia media / máxima en el host | 1,65 s / 2,35 s |
| Latencia en la corrida oficial (contenedor, 3 CPU) | mediana 2,8 s; máx. 15,1 s en la primera nota (caché fría) |
| Hardware | Desktop, CPU sin GPU, 12 hilos disponibles; contenedor limitado a 3 CPU |
| RAM del proceso | ~1 GB |
| Extracción en la corrida oficial archivada | 22/22 campos con TAG, valor y unidad correctos (`scripts/audit_escenario.py`) |
| Extracción en la corrida `libre` de desarrollo (medida el 2026-11-10) | 11/15 campos (73,3 %) — `evaluacion/evaluar_parte.py` |

## 4. Consumo y latencia del RAG

```bash
uv run python evaluacion/retrieval_eval.py
```

La métrica se calcula con `corpus.evaluar.evaluar(buscar, suite)` del repo de la planta
cuando está disponible (`PLANTA_REPO_DIR` o `academia2026-tp/planta`); si no, con la copia
local, que da exactamente los mismos valores (hay una prueba que compara ambas).

| Métrica | BM25 base (curso) | Este sistema |
|---|---|---|
| hit@5 | 0,85 | **0,873** |
| recall@5 | 0,66 | **0,718** |
| MRR | — | **0,678** |
| Distractor@5 (Rev. C antes que D) | ~6 de 71 | **0** |
| Preguntas | 71 | 71 |

La línea de base medida en este repo es hit@5 0,859 / recall@5 0,674 / MRR 0,581, consistente
con la referencia del curso. La combinación BM25 + vector (peso 0,1) + re-ranking por metadata
mejora la recuperación y elimina las trampas de versión: ninguna sección de la Rev. C queda
antes que la vigente en el top 5.

Costo: USD 0 (modelo local, sin API).

## 5. Tokens y costo del LLM local

El camino evaluado no consume tokens de un LLM: la extracción es determinista y cada paso
del pipeline se registra en `usage_log` (modelo, tokens, costo y latencia). En la corrida
oficial quedó, por nota, `faster-whisper-small` con la latencia real del ASR y
`deterministic/parse` con la del parser; tokens y costo son 0.

La visión de la Entrega 2 es la única llamada a un modelo en la nube. Cada foto analizada
agrega una fila `task='vision'` con el modelo, los tokens de entrada y salida que reporta
la API, la latencia y el costo (0 con el nivel gratuito de NIM). Las fotos que quedan en
cola no registran consumo porque no hubo llamada. En las pruebas con dobles se verifica
que el registro no puede convertir un análisis válido en fallo.

El modelo opcional no se ejecutó en esta entrega y por eso **no se informan** sus tokens
ni su latencia: no se inventan mediciones. Se activa con `LLM_ENABLED=true` y
`docker compose build --build-arg DOWNLOAD_LLM=1 cerebro`; su salida JSON se valida con
`extra="forbid"` y solo propone acciones de corrección (`set/add/remove/move/unit`), nunca
una regla de aprobación ni la alerta de seguridad.

En la nube el costo es 0: la visión usa el nivel gratuito de NVIDIA NIM y la réplica
`nube-sync` no es un modelo.

## 6. Conclusión

La corrida oficial de cierre de la **Entrega 2** (commit `21bcef8`, 2026-11-25) sobre los
cuatro escenarios del anexo —`tormenta-perfecta`, `sin-luz`, `contratista`,
`fuga-sin-enlace`— obtuvo **89,4 / 100 (APRUEBA)**, sin faltas eliminatorias. La misma
suite había dado 91,2 el 2026-11-21; la diferencia está en A1/A2/B1, que dependen del ASR
y de la voz del simulador, con D1/D2/G1 siempre al 100 %. D1 (reglas de aprobación),
D2 (orden adecuada a la falla) y G1 (orden ejecutada) dieron 100 %; F3 (sobrevive al
corte de luz) dio 0 % porque el apagón del escenario cae cuando no había ninguna orden
pendiente que sobrevivir, y E1/E2 pierden la ventana del corte porque el reloj de la
planta corre a 1800× mientras el ASR local tarda segundos. Los dos techos están
explicados en [`RESULTADOS.md`](docs/RESULTADOS.md) y el requisito de durabilidad se
demuestra además con un corte controlado del contenedor.

La corrida oficial de la primera entrega, con los dos escenarios obligatorios, había
dado **91,3 / 100**. Las corridas anteriores archivadas dieron 88,8 / 89,2 / 82,4 / 73,5.
La variación está en A2 y A3, porque el simulador elige una voz de operador distinta cada
vez, el ASR local a veces pierde una cláusula y el operador virtual no confirma
borradores sin valores. La auditoría completa con la verificación independiente está en
[`DELIVERY_1_AUDIT.md`](docs/DELIVERY_1_AUDIT.md).

La combinación elegida prioriza **disponibilidad local** y **determinismo**.
`faster-whisper small` en int8 entra en la PC de planta (WER 0,252 y 1,65 s de latencia
media en CPU) y da texto suficiente para un vocabulario de campo acotado; el parser
determinista convierte ese texto en filas verificables sin depender de la latencia ni de
la variabilidad de un LLM. El modelo de lenguaje queda como una ayuda acotada y auditable
para el lenguaje libre, no como el núcleo de las decisiones. El RAG usa un embedding
multilingüe pequeño (384 dimensiones) que cabe en el presupuesto y permite comparar
contra la línea de base BM25 con las mismas citas y metadatos. La visión también queda
fuera del camino crítico: se consulta cuando hay enlace, su veredicto puede forzar
revisión humana, y ni la alerta ni las reglas dependen de ella.

Si la cátedra publica la lista cerrada de modelos, el reemplazo es directo:
`ASR_MODEL`, `EMBEDDING_MODEL`, `LLM_MODEL`, `VISION_MODEL` y `VISION_BASE_URL` son
variables de entorno y el contrato de mensajes no cambia.
