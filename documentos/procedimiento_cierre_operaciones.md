---
titulo: Procedimiento de cierre de operaciones
roles: controller, gerencia, comex, vendedor
---
# Procedimiento de cierre de operaciones

Este procedimiento define qué documentos necesita cada tipo de operación para que el Controller pueda cerrar el margen. Una operación solo se cierra cuando están todos los documentos y el Controller aprueba el cierre.

## Importación marítima FCL (QF)
Documentos obligatorios para cerrar una operación QF:
- Factura de venta al cliente (puede haber 2 o 3 por operación).
- Factura de la naviera por flete y/o gastos locales.
- Debit note o factura del agente de origen.
- Factura de gastos locales en destino, solo si hubo servicios locales (desconsolidación, almacenaje o transporte).

## Importación marítima LCL (L)
Documentos obligatorios para cerrar una operación L (carga consolidada):
- Factura de venta al cliente.
- Factura del consolidador o coloader por el flete marítimo.
- Factura de desconsolidación del almacén extraportuario en destino.
- Debit note del agente de origen, si el agente cobró servicios en origen.

## Importación aérea (A)
Documentos obligatorios para cerrar una operación A:
- Factura de venta al cliente.
- Factura de la aerolínea o del agente de carga aérea (incluye el flete aéreo).
- Debit note del agente de origen por gastos en origen.
- Factura de manejo de terminal aérea en destino (handling).

## Exportaciones (VF y VFA)
Las exportaciones marítimas (VF) y aéreas (VFA) siguen la guía de documentos de exportación de la vertical Fresh. El cierre requiere la factura de venta al cliente, la factura de la naviera o aerolínea y la factura del agente de destino.

## Quién aprueba el cierre
El asistente puede proponer el cierre de una operación cuando no faltan documentos y no hay alertas de costo abiertas. El cierre siempre lo aprueba el Controller. Cargar los costos en el sistema operativo y escribir a los agentes también lo hace una persona, no el asistente.
