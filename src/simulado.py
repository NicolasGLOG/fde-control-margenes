"""Cliente simulado: imita la respuesta de la API de Claude sin gastar ni necesitar API key.

Sirve para probar el motor y para mostrar el manejo de errores:
con invalido=True devuelve siempre una salida que no pasa la validación.
"""

import json
from types import SimpleNamespace

SALIDA_VALIDA = {
    "categoria": "facturas_faltantes",
    "documentos_recibidos": ["Factura de venta al cliente", "Factura de la naviera"],
    "documentos_faltantes": ["Debit note o factura del agente de origen"],
    "costo_acordado_usd": None,
    "costo_facturado_usd": None,
    "requiere_humano": True,
    "confianza": 0.9,
    "respuesta": "Falta la debit note del agente de origen; sin ella no se puede cerrar el margen.",
}

# Dos errores a propósito: confianza fuera de rango y requiere_humano en false con documentos faltantes
SALIDA_INVALIDA = dict(SALIDA_VALIDA, confianza=1.4, requiere_humano=False)


class _Mensajes:
    def __init__(self, invalido: bool):
        self.invalido = invalido

    def create(self, **kwargs):
        salida = SALIDA_INVALIDA if self.invalido else SALIDA_VALIDA
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(salida, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
            stop_reason="end_turn",
        )


class ClienteSimulado:
    def __init__(self, invalido: bool = False):
        self.beta = SimpleNamespace(messages=_Mensajes(invalido))
