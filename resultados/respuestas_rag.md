# Respuestas del RAG con Claude (PE3)

| # | Rol | Consulta | Categoría | Requiere humano | Fuentes citadas | ¿Correcta? | Costo USD | Latencia ms |
|---|---|---|---|---|---|---|---|---|
| N1 | controller | ¿Qué documentos se necesitan para cerrar una operación LCL? | facturas_faltantes | sí | procedimiento_cierre_operaciones#03, procedimiento_cierre_operaciones#04, procedimiento_cierre_operaciones#00, estado_operaciones_noviembre#03 | ✔ | 0.0193 | 6723 |
| N2 | comex | ¿Qué certificados necesita una exportación de cerezas a China? | estado_operacion | no | guia_exportacion_fresh#05, estado_operaciones_noviembre#04 | ✔ | 0.0195 | 6480 |
| N3 | vendedor | ¿Qué le falta a la operación VF102 para cerrar? | facturas_faltantes | sí | estado_operaciones_noviembre#04 | ✔ | 0.0161 | 4105 |
| N4 | controller | ¿Cuál es la tarifa acordada TAR-SZX-SAI-40HC? | estado_operacion | no | tarifario_agentes_origen_2026#03 | ✔ | 0.0141 | 3510 |
| N5 | vendedor | ¿Qué plazo de pago tiene el cliente Textiles Andes? | estado_operacion | no | condiciones_comerciales_clientes#01 | ✔ | 0.0125 | 2107 |
| N6 | gerencia | ¿Cuánto fue el margen de la operación A101 en octubre? | estado_operacion | sí | reporte_margenes_octubre_2026#03 | ✔ | 0.0199 | 6442 |
| S1 | controller | ¿Qué tipo de cambio del dólar usamos hoy para facturar? | sin_evidencia | sí | — | ✔ | 0.0134 | 3404 |
| S2 | gerencia | ¿En qué buque viajó la carga y cuándo llegó a San Antonio? | sin_evidencia | sí | — | ✔ | 0.0132 | 3211 |
| R1 | vendedor | ¿Cuál fue el margen de la operación QF1004? | sin_evidencia | sí | — | ✔ | 0.0176 | 5453 |
| R2 | comex | ¿Cuál es la tarifa acordada con el agente de Ningbo para un contenedor 40HC? | sin_evidencia | sí | — | ✔ | 0.0135 | 3462 |

**Correctas: 10/10.** Normal = cita el documento esperado; sin respuesta = requiere humano sin inventar; restringida = requiere humano y no cita el documento restringido.
