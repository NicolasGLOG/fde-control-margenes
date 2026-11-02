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
│   └── simulado.py     # cliente simulado para probar sin API key
├── prompts/
│   ├── sistema.md      # prompt de sistema (plantilla separada)
│   └── consulta.md     # plantilla del mensaje de cada consulta
├── datos/
│   └── consultas_prueba.json   # 5 consultas ficticias con su resultado esperado
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
