"""Cliente simulado: imita la respuesta de la API de Claude sin gastar ni necesitar API key.

Sirve para probar el motor y para mostrar el manejo de errores:
con invalido=True devuelve siempre una salida que no pasa la validación.
"""

import json
import re
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


# ---------------------------------------------------------------------
# PE3: cliente simulado para el RAG
# ---------------------------------------------------------------------

class _MensajesRAG:
    """Guarda cada petición (para revisar qué vio el modelo) y cita el primer fragmento recibido.
    Con fuentes_fijas se puede forzar qué fragmentos cita (por ejemplo, uno inventado)."""

    def __init__(self, fuentes_fijas=None):
        self.peticiones = []
        self.fuentes_fijas = fuentes_fijas

    def create(self, **kwargs):
        self.peticiones.append(kwargs)
        prompt = kwargs["messages"][0]["content"]
        ids = re.findall(r"^\[([^\]]+#\d+)\]$", prompt, re.M)
        fuentes = self.fuentes_fijas if self.fuentes_fijas is not None else ids[:1]
        if fuentes:
            salida = {
                "categoria": "estado_operacion", "documentos_recibidos": [], "documentos_faltantes": [],
                "costo_acordado_usd": None, "costo_facturado_usd": None, "requiere_humano": True,
                "confianza": 0.5, "respuesta": f"Respuesta simulada a partir de {fuentes[0]}.",
                "fuentes": fuentes,
            }
        else:
            salida = {
                "categoria": "sin_evidencia", "documentos_recibidos": [], "documentos_faltantes": [],
                "costo_acordado_usd": None, "costo_facturado_usd": None, "requiere_humano": True,
                "confianza": 0.0, "respuesta": "Los documentos no contienen la respuesta.", "fuentes": [],
            }
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=json.dumps(salida, ensure_ascii=False))],
            usage=SimpleNamespace(input_tokens=0, output_tokens=0),
            stop_reason="end_turn",
        )


class ClienteSimuladoRAG:
    def __init__(self, fuentes_fijas=None):
        self.mensajes = _MensajesRAG(fuentes_fijas)
        self.beta = SimpleNamespace(messages=self.mensajes)

    def prompts_enviados(self) -> str:
        """Todo el texto que se le habría enviado al modelo (sistema + mensajes)."""
        partes = []
        for p in self.mensajes.peticiones:
            partes.append(p["system"])
            partes.extend(str(m["content"]) for m in p["messages"])
        return "\n".join(partes)
