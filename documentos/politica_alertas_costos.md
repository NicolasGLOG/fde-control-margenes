---
titulo: Política de alertas de costo
roles: controller, gerencia
---
# Política de alertas de costo

Esta política define cuándo una diferencia entre el costo facturado y el costo acordado se convierte en una alerta.

## Umbral de alerta
Se genera una alerta cuando el costo facturado supera al acordado en más de 50 USD o en más de 2% del valor acordado, lo que ocurra primero. La comparación se hace por concepto interno, usando la tabla de equivalencias.

## Qué hace el asistente y qué hace una persona
- El asistente detecta la diferencia, calcula el monto y el porcentaje y marca la operación para revisión humana.
- El asistente no aprueba ni rechaza costos, no escribe a los agentes y no carga costos en el sistema operativo.

## Escalamiento
Cuando la diferencia supera el umbral, el Controller revisa la cotización junto con el área de Pricing. Si la diferencia supera 500 USD o 10%, se informa además a Gerencia antes de aceptar la factura del agente.

## Errores documentados
1 de cada 30 documentos de costo llega con errores. El caso de referencia es una debit note de un agente de origen que, sin la revisión del Controller, habría convertido un margen de +16.000 USD en una pérdida de 3.000 USD.
