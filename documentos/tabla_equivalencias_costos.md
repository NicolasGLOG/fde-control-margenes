---
titulo: Tabla de equivalencias de conceptos de costo
roles: controller, gerencia, comex
---
# Tabla de equivalencias de conceptos de costo

Los agentes, navieras y aerolíneas usan nombres distintos para el mismo costo. Esta tabla dice a qué concepto interno de Green Logistics corresponde cada nombre, para comparar facturas con la cotización.

## Cargos en origen
- "Origin charges", "Gastos en origen", "FOB charges" y "Local charges at POL" corresponden al concepto interno GASTOS_ORIGEN.
- "Pick up", "Inland haulage" y "Trucking origin" corresponden al concepto interno TRANSPORTE_ORIGEN.
- "Customs clearance export" y "Export declaration" corresponden al concepto interno ADUANA_ORIGEN.

## Flete
- "Ocean freight", "O/F", "Flete marítimo" y "Basic freight" corresponden al concepto interno FLETE.
- "BAF", "Bunker surcharge" y "Recargo de combustible" corresponden al concepto interno RECARGO_COMBUSTIBLE y se compara junto con el FLETE.
- "Air freight", "AF" y "Flete aéreo" corresponden al concepto interno FLETE_AEREO.

## Cargos en destino
- "THC", "Terminal handling charge" y "Destination THC" corresponden al concepto interno THC_DESTINO.
- "ISPS", "Port security fee" y "Recargo de seguridad portuaria" corresponden al concepto interno SEGURIDAD_PORTUARIA.
- "BL fee", "Documentation fee" y "Emisión de BL" corresponden al concepto interno DOCUMENTACION.
- "Desconsolidación", "CFS charges" y "Unstuffing" corresponden al concepto interno DESCONSOLIDACION.

## Cómo usar la tabla
Antes de comparar una debit note con lo acordado, se agrupan sus líneas por concepto interno. Una línea con un nombre que no aparece en esta tabla se marca para revisión del Controller.
