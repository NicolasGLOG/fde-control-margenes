# fde-control-margenes

Asistente de control de márgenes para **Green Logistics** (curso Forward Deployed Engineer, Coderhouse).

Recibe una consulta sobre una operación (por ejemplo `QF1001`), revisa sus documentos con Claude y devuelve una respuesta **validada con Pydantic**: qué facturas llegaron, cuáles faltan, si un costo supera el umbral de alerta (más de 50 USD o 2% sobre lo acordado) y si la operación requiere revisión del Controller. También informa tokens, costo en USD y latencia.

> Todos los datos de este repositorio son **ficticios**.

## Cómo ejecutarlo desde un clon limpio

Requiere Python 3.10 o superior.

```bash
git clone https://github.com/NicolasGLOG/fde-control-margenes.git
cd fde-control-margenes
python -m venv .venv
.venv\Scripts\activate          # en macOS / Linux: source .venv/bin/activate
pip install -r requirements.txt
```

Copia `.env.example` como `.env` y completa tu clave de Anthropic (`ANTHROPIC_API_KEY`). Después:

```bash
python src/motor.py              # una consulta de ejemplo contra Claude
python src/pruebas.py            # las 5 consultas de prueba + tabla de medición (resultados/medicion.md)
```

Sin API key se puede probar todo el flujo con respuestas simuladas:

```bash
python src/motor.py --simulado
python src/motor.py --demo-error   # muestra el campo que falló, el reintento y el error estructurado
python src/pruebas.py --simulado
```

## Estructura

```
fde-control-margenes/
├── src/
│   ├── motor.py        # contrato de datos (Entrada / Salida), llamada a Claude, validación y reintento
│   ├── pruebas.py      # corre las 5 consultas y calcula promedios
│   ├── simulado.py     # cliente simulado para probar sin API key
│   ├── rag.py          # PE3: ingesta, búsqueda híbrida con permisos y respuesta con fuentes
│   └── medir_rag.py    # PE3: medición top-k y respuestas con Claude
├── documentos/         # PE3: 8 documentos ficticios con los roles que pueden leerlos
├── tests/
│   └── test_permisos.py        # PE3: un test de permisos por rol + prompt sin fugas
├── prompts/
│   ├── sistema.md      # prompt de sistema (plantilla separada)
│   ├── consulta.md     # plantilla del mensaje de cada consulta
│   ├── sistema_rag.md  # PE3: prompt de sistema del RAG
│   └── consulta_rag.md # PE3: plantilla con los fragmentos recuperados
├── datos/
│   ├── consultas_prueba.json   # 5 consultas ficticias con su resultado esperado
│   └── preguntas_prueba.json   # PE3: 10 preguntas (6 normales, 2 sin respuesta, 2 restringidas)
├── requirements.txt
├── .env.example        # nombres de las variables, sin valores
└── .gitignore          # excluye .env y .venv
```

## Contrato de datos

**Entrada**
| Campo | Tipo | Regla |
|---|---|---|
| `operacion_id` | texto | Patrón `QF`, `L`, `A`, `VF` o `VFA` + números (ej. `QF1001`) |
| `rol` | Enum | `controller`, `gerencia`, `vendedor` o `comex` |
| `consulta` | texto | Entre 10 y 1.000 caracteres |
| `documentos` | texto | Opcional, hasta 20.000 caracteres |

**Salida**
| Campo | Tipo | Regla |
|---|---|---|
| `categoria` | Enum | `facturas_faltantes`, `alerta_costo`, `estado_operacion` o `fuera_de_alcance` |
| `documentos_recibidos` / `documentos_faltantes` | lista de textos | |
| `costo_acordado_usd` / `costo_facturado_usd` | número o vacío | Mayor o igual a 0 |
| `requiere_humano` | sí / no | **Obligatorio en sí** si la diferencia de costo supera 50 USD o 2%, si faltan documentos o si la consulta está fuera de alcance |
| `confianza` | número | Entre 0 y 1 |
| `respuesta` | texto | Entre 10 y 600 caracteres |

## Qué pasa cuando la salida no es válida

El motor registra **qué campo falló y por qué**, le devuelve el error a Claude y **reintenta una vez**. Si vuelve a fallar, entrega un error estructurado (`tipo`, `mensaje` y la lista de `campos` con su problema) en vez de una respuesta. Los errores de la API (clave inválida, límite de uso, sin conexión) también se devuelven como error estructurado.

## PE3: RAG con permisos y búsqueda híbrida

El asistente ahora responde con los documentos de Green Logistics (carpeta `documentos/`, 8 documentos ficticios) y cada rol solo recibe lo que puede leer.

```bash
python src/rag.py ingestar                     # un solo comando: limpia, fragmenta y guarda en ChromaDB
python src/rag.py buscar "¿Qué le falta a la operación VF102?" --rol vendedor
python src/rag.py buscar "QF1007" --rol controller --modo vectorial
python src/rag.py responder "¿Cuál fue el margen de la operación QF1004?" --operacion QF1004 --rol vendedor
python -m pytest -v                            # tests de permisos (no usan la API)
python src/medir_rag.py                        # medición top-k con 2 configuraciones de fragmentado
python src/medir_rag.py --con-claude           # además responde las 10 preguntas con Claude (~0,16 USD)
```

| Pieza | Qué hace |
|---|---|
| `ingestar()` | Lee cada `.md`, toma del encabezado su `titulo` y los `roles` que pueden leerlo, lo divide por sección y por tamaño (300 caracteres, solape 40) y guarda cada fragmento con sus metadatos: `documento`, `seccion`, `roles`, `fragmento`. |
| `buscar(consulta, usuario, k)` | Búsqueda vectorial y BM25 fusionadas con Reciprocal Rank Fusion. El filtro por rol va **dentro** de la consulta a ChromaDB (`where={"roles": {"$contains": rol}}`), así que un fragmento restringido nunca sale de la base. Devuelve `documento`, `fragmento_id`, `texto` y `puntaje`. |
| `responder(entrada)` | Recibe la `Entrada` de la PE2 y devuelve la `Salida` más la lista de `fuentes`. Claude solo ve los fragmentos recuperados. Si no hay evidencia, la categoría es `sin_evidencia` con `requiere_humano = true`. Si Claude cita un fragmento que no se le entregó, la respuesta se rechaza y se reintenta. |

**Permisos por rol** (encabezado de cada documento):

| Documento | controller | gerencia | comex | vendedor |
|---|---|---|---|---|
| Procedimiento de cierre, guía de exportación, estado de operaciones | ✔ | ✔ | ✔ | ✔ |
| Tabla de equivalencias de costos | ✔ | ✔ | ✔ | |
| Condiciones comerciales de clientes | ✔ | ✔ | | ✔ |
| Política de alertas, tarifario de agentes, reporte de márgenes | ✔ | ✔ | | |

Las 10 preguntas de prueba están en `datos/preguntas_prueba.json`, y los resultados, en `resultados/medicion_rag.md` y `resultados/respuestas_rag.md`. La base `chroma_db/` se genera con `ingestar` y no se sube a GitHub. La primera vez, ChromaDB descarga su modelo de embeddings (unos 80 MB), que después corre en tu computador.
