"""Motor LLM base del Asistente de control de márgenes (Green Logistics).

Recibe una consulta sobre una operación, se la pasa a Claude y devuelve una
respuesta validada con Pydantic, junto con tokens, costo y latencia.

Uso:
    python src/motor.py                 # consulta de ejemplo contra Claude
    python src/motor.py --simulado      # sin API key: respuesta simulada
    python src/motor.py --demo-error    # muestra el reintento y el error estructurado
"""

import argparse
import json
import logging
import os
import sys
import time
from enum import Enum
from pathlib import Path
from typing import Optional

import anthropic
from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError, model_validator

load_dotenv()

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")
log = logging.getLogger("motor")
logging.getLogger("httpx").setLevel(logging.WARNING)   # oculta el detalle de cada petición HTTP

RAIZ = Path(__file__).resolve().parent.parent

MODELO = os.getenv("MODELO") or "claude-opus-5-5"

# Precios publicados en USD por 1.000.000 de tokens (entrada, salida)
PRECIOS = {
    "claude-opus-5-5": (4.00, 20.00),
    "claude-haiku-5-5": (0.10, 0.50),
}

# Umbral de alerta definido por el Controller: lo que se cumpla primero
UMBRAL_USD = 50.0
UMBRAL_PORCENTAJE = 2.0

MAX_INTENTOS = 2          # el primero + un reintento

# Prompts como plantillas separadas (no escritas dentro de las funciones)
PROMPT_SISTEMA = (RAIZ / "prompts" / "sistema.md").read_text(encoding="utf-8")
PLANTILLA_CONSULTA = (RAIZ / "prompts" / "consulta.md").read_text(encoding="utf-8")


# =====================================================================
# 1. CONTRATO DE DATOS
# =====================================================================

class Rol(str, Enum):
    CONTROLLER = "controller"
    GERENCIA = "gerencia"
    VENDEDOR = "vendedor"
    COMEX = "comex"


class Categoria(str, Enum):
    FACTURAS_FALTANTES = "facturas_faltantes"
    ALERTA_COSTO = "alerta_costo"
    ESTADO_OPERACION = "estado_operacion"
    FUERA_DE_ALCANCE = "fuera_de_alcance"


class Entrada(BaseModel):
    """Lo que recibe el motor (sale de la Historia 1 y 2 de la PE1)."""

    operacion_id: str = Field(
        pattern=r"^(QF|L|A|VF|VFA)\d{2,6}$",
        description="Código de la operación: QF, L, A, VF o VFA seguido de números (ej. QF1000)",
    )
    rol: Rol
    consulta: str = Field(min_length=10, max_length=1000)
    documentos: str = Field(default="", max_length=20000,
                            description="Texto con los documentos disponibles de la operación")


class Salida(BaseModel):
    """Lo que el motor devuelve. Claude tiene que llenar este formulario."""

    categoria: Categoria
    documentos_recibidos: list[str]
    documentos_faltantes: list[str]
    costo_acordado_usd: Optional[float] = Field(default=None, ge=0)
    costo_facturado_usd: Optional[float] = Field(default=None, ge=0)
    requiere_humano: bool
    confianza: float = Field(ge=0, le=1)
    respuesta: str = Field(min_length=10, max_length=600)

    @model_validator(mode="after")
    def reglas_de_negocio(self) -> "Salida":
        # Regla del umbral: una diferencia sobre 50 USD o 2% obliga a revisión humana
        if self.costo_acordado_usd is not None and self.costo_facturado_usd is not None:
            diferencia = abs(self.costo_facturado_usd - self.costo_acordado_usd)
            porcentaje = (diferencia / self.costo_acordado_usd * 100
                          if self.costo_acordado_usd > 0 else float("inf"))
            if (diferencia > UMBRAL_USD or porcentaje > UMBRAL_PORCENTAJE) and not self.requiere_humano:
                raise ValueError(
                    f"requiere_humano debe ser true: la diferencia de costo es {diferencia:.2f} USD "
                    f"({porcentaje:.1f}%), sobre el umbral de {UMBRAL_USD:.0f} USD o {UMBRAL_PORCENTAJE:.0f}%"
                )
        # Si faltan documentos o la consulta está fuera de alcance, decide una persona
        if self.documentos_faltantes and not self.requiere_humano:
            raise ValueError("requiere_humano debe ser true cuando faltan documentos")
        if self.categoria == Categoria.FUERA_DE_ALCANCE and not self.requiere_humano:
            raise ValueError("requiere_humano debe ser true cuando la consulta está fuera de alcance")
        return self


class ErrorEstructurado(BaseModel):
    tipo: str                      # "entrada_invalida", "salida_invalida", "api", "rechazo"
    mensaje: str
    campos: list[dict] = []        # qué campo falló y por qué


class Metricas(BaseModel):
    modelo: str
    intentos: int = 0
    tokens_entrada: int = 0
    tokens_salida: int = 0
    costo_usd: float = 0.0
    latencia_ms: float = 0.0


class Resultado(BaseModel):
    ok: bool
    salida: Optional[Salida] = None
    error: Optional[ErrorEstructurado] = None
    metricas: Metricas


# Esquema JSON que se le entrega a Claude para que responda con esta forma exacta.
# Los rangos y reglas de negocio los revisa Pydantic después (Salida).
ESQUEMA_SALIDA = {
    "type": "object",
    "properties": {
        "categoria": {"type": "string", "enum": [c.value for c in Categoria]},
        "documentos_recibidos": {"type": "array", "items": {"type": "string"}},
        "documentos_faltantes": {"type": "array", "items": {"type": "string"}},
        "costo_acordado_usd": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "costo_facturado_usd": {"anyOf": [{"type": "number"}, {"type": "null"}]},
        "requiere_humano": {"type": "boolean"},
        "confianza": {"type": "number"},
        "respuesta": {"type": "string"},
    },
    "required": ["categoria", "documentos_recibidos", "documentos_faltantes",
                 "costo_acordado_usd", "costo_facturado_usd", "requiere_humano",
                 "confianza", "respuesta"],
    "additionalProperties": False,
}


# =====================================================================
# 2. MOTOR
# =====================================================================

def calcular_costo(modelo: str, tokens_entrada: int, tokens_salida: int) -> float:
    precio_entrada, precio_salida = PRECIOS[modelo]
    return round((tokens_entrada * precio_entrada + tokens_salida * precio_salida) / 1_000_000, 6)


def describir_errores(error: ValidationError) -> list[dict]:
    """Convierte un ValidationError en una lista de {campo, problema, valor}."""
    campos = []
    for e in error.errors():
        campo = " -> ".join(str(parte) for parte in e["loc"]) or "(regla de negocio)"
        campos.append({"campo": campo, "problema": e["msg"], "valor": str(e.get("input"))[:80]})
    return campos


class Motor:
    def __init__(self, cliente=None, modelo: str = MODELO):
        self.modelo = modelo
        self.cliente = cliente or anthropic.Anthropic()

    def _llamar(self, mensajes: list):
        return self.cliente.beta.messages.create(
            model=self.modelo,
            max_tokens=16000,
            system=PROMPT_SISTEMA,
            messages=mensajes,
            output_config={
                "effort": "medium",
                "format": {"type": "json_schema", "schema": ESQUEMA_SALIDA},
            },
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
        )

    def procesar(self, datos: dict) -> Resultado:
        metricas = Metricas(modelo=self.modelo)
        inicio = time.perf_counter()

        def terminar(ok, salida=None, error=None) -> Resultado:
            metricas.latencia_ms = round((time.perf_counter() - inicio) * 1000, 1)
            metricas.costo_usd = calcular_costo(self.modelo, metricas.tokens_entrada, metricas.tokens_salida)
            return Resultado(ok=ok, salida=salida, error=error, metricas=metricas)

        # 1. Validar la entrada antes de gastar en el modelo
        try:
            entrada = Entrada.model_validate(datos)
        except ValidationError as e:
            campos = describir_errores(e)
            for c in campos:
                log.warning(f"Entrada inválida en '{c['campo']}': {c['problema']}")
            return terminar(False, error=ErrorEstructurado(
                tipo="entrada_invalida", mensaje="La consulta no cumple el contrato de Entrada", campos=campos))

        mensajes = [{"role": "user", "content": PLANTILLA_CONSULTA.format(
            rol=entrada.rol.value,
            operacion_id=entrada.operacion_id,
            consulta=entrada.consulta,
            documentos=entrada.documentos or "(sin documentos)",
        )}]

        # 2. Llamar al modelo, validar y reintentar una vez si la salida no cumple
        ultimo_error = None
        for intento in range(1, MAX_INTENTOS + 1):
            metricas.intentos = intento
            try:
                respuesta = self._llamar(mensajes)
            except anthropic.AuthenticationError:
                return terminar(False, error=ErrorEstructurado(tipo="api", mensaje="Clave de API inválida (revisa .env)"))
            except anthropic.RateLimitError:
                return terminar(False, error=ErrorEstructurado(tipo="api", mensaje="Límite de uso alcanzado o sin saldo"))
            except anthropic.APIConnectionError:
                return terminar(False, error=ErrorEstructurado(tipo="api", mensaje="Sin conexión con la API"))
            except anthropic.APIStatusError as e:
                return terminar(False, error=ErrorEstructurado(tipo="api", mensaje=f"Error {e.status_code}: {e.message}"))

            metricas.tokens_entrada += respuesta.usage.input_tokens
            metricas.tokens_salida += respuesta.usage.output_tokens

            if respuesta.stop_reason == "refusal":
                return terminar(False, error=ErrorEstructurado(tipo="rechazo", mensaje="El modelo no respondió la consulta"))

            texto = next((b.text for b in respuesta.content if b.type == "text"), "")
            try:
                salida = Salida.model_validate_json(texto)
                log.info(f"Salida válida en el intento {intento}")
                return terminar(True, salida=salida)
            except ValidationError as e:
                ultimo_error = describir_errores(e)
                for c in ultimo_error:
                    log.warning(f"Intento {intento}/{MAX_INTENTOS}: falló el campo '{c['campo']}' -> {c['problema']}")
                # Para el reintento, se le devuelve a Claude su respuesta y el error
                mensajes.append({"role": "assistant", "content": respuesta.content})
                mensajes.append({"role": "user", "content":
                    "Tu respuesta no pasó la validación. Corrige estos problemas y responde de nuevo:\n"
                    + json.dumps(ultimo_error, ensure_ascii=False)})

        return terminar(False, error=ErrorEstructurado(
            tipo="salida_invalida",
            mensaje=f"La salida no se pudo validar después de {MAX_INTENTOS} intentos",
            campos=ultimo_error or [],
        ))


# =====================================================================
# 3. EJECUCIÓN DESDE LA TERMINAL
# =====================================================================

EJEMPLO = {
    "operacion_id": "QF1001",
    "rol": "controller",
    "consulta": "¿Qué facturas faltan para cerrar el margen de esta operación?",
    "documentos": (
        "- Factura de venta N°5521 a Vinos del Maule: 3.400 USD\n"
        "- Factura CMA CGM N°88231 (flete + gastos locales): 2.650 USD\n"
        "- Correo del agente de origen (Shanghai): 'la debit note sale la próxima semana'"
    ),
}


def main():
    parser = argparse.ArgumentParser(description="Motor LLM del asistente de control de márgenes")
    parser.add_argument("--simulado", action="store_true", help="usar respuestas simuladas (sin API key)")
    parser.add_argument("--demo-error", action="store_true", help="simular dos salidas inválidas seguidas")
    args = parser.parse_args()

    if args.simulado or args.demo_error:
        from simulado import ClienteSimulado
        cliente = ClienteSimulado(invalido=args.demo_error)
    else:
        if not os.getenv("ANTHROPIC_API_KEY"):
            sys.exit("Falta ANTHROPIC_API_KEY en .env (o ejecuta con --simulado)")
        cliente = None

    resultado = Motor(cliente=cliente).procesar(EJEMPLO)
    print(resultado.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
