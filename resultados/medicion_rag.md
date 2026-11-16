# Medición del RAG (PE3)

Configuraciones de fragmentado: **chico** = hasta 300 caracteres, solape 40, respetando secciones; **grande** = hasta 1500 caracteres, solape 150, corte fijo sin secciones
Se mide si el documento correcto aparece en el 1er lugar y entre los primeros 3 resultados.

## Resumen

| Configuración | Búsqueda | Top-1 (de 6 normales) | Top-3 (de 6 normales) | Fugas de documentos restringidos (de 2) |
|---|---|---|---|---|
| chico | hibrida | 4/6 | 6/6 | 0/2 |
| chico | vectorial | 3/6 | 5/6 | 0/2 |
| grande | hibrida | 3/6 | 6/6 | 0/2 |
| grande | vectorial | 3/6 | 4/6 | 0/2 |

## Detalle por pregunta (posición del documento esperado)

| # | Tipo | Rol | Consulta | Documento esperado | chico híbrida | grande híbrida | chico vectorial |
|---|---|---|---|---|---|---|---|
| N1 | normal | controller | ¿Qué documentos se necesitan para cerrar una operación LCL? | procedimiento_cierre_operaciones | 1° | 1° | 1° |
| N2 | normal | comex | ¿Qué certificados necesita una exportación de cerezas a China? | guia_exportacion_fresh | 2° | 2° | — |
| N3 | normal | vendedor | ¿Qué le falta a la operación VF102 para cerrar? | estado_operaciones_noviembre | 1° | 1° | 1° |
| N4 | normal | controller | ¿Cuál es la tarifa acordada TAR-SZX-SAI-40HC? | tarifario_agentes_origen_2026 | 1° | 2° | 3° |
| N5 | normal | vendedor | ¿Qué plazo de pago tiene el cliente Textiles Andes? | condiciones_comerciales_clientes | 2° | 1° | 2° |
| N6 | normal | gerencia | ¿Cuánto fue el margen de la operación A101 en octubre? | reporte_margenes_octubre_2026 | 1° | 3° | 1° |
| S1 | sin_respuesta | controller | ¿Qué tipo de cambio del dólar usamos hoy para facturar? | (ninguno) | — | — | — |
| S2 | sin_respuesta | gerencia | ¿En qué buque viajó la carga y cuándo llegó a San Antonio? | (ninguno) | — | — | — |
| R1 | restringida | vendedor | ¿Cuál fue el margen de la operación QF1004? | reporte_margenes_octubre_2026 | — | — | — |
| R2 | restringida | comex | ¿Cuál es la tarifa acordada con el agente de Ningbo para un contenedor 40HC? | tarifario_agentes_origen_2026 | — | — | — |

En las restringidas, "—" es lo correcto: el rol no puede recibir ese documento.

## Texto enviado a Claude (4 fragmentos por consulta, preguntas normales)

| Configuración | Fragmentos en la base | Caracteres promedio enviados |
|---|---|---|
| chico | 47 | 1158 |
| grande | 10 | 4953 |

## Híbrida vs. solo vectorial (configuración chico, rol controller)

Posición del fragmento que contiene la respuesta dentro del top-3 (— = no aparece).

| Consulta | Fragmento con la respuesta | Vectorial | Híbrida | Resultado |
|---|---|---|---|---|
| ¿Qué le falta a la operación VF102? | estado_operaciones_noviembre#04 | 2° | 1° | **gana la híbrida** |
| QF1007 | estado_operaciones_noviembre#02 | 2° | 1° | **gana la híbrida** |
| ¿Cuánto es el margen de L203? | reporte_margenes_octubre_2026#03 | — | 2° | **gana la híbrida** |
| ¿Qué le falta a la operación A104? | estado_operaciones_noviembre#03 | — | 2° | **gana la híbrida** |
| ¿Qué pasó con la debit note DN-7781? | reporte_margenes_octubre_2026#01 | — | 3° | **gana la híbrida** |
