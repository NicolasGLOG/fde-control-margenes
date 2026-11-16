"""Tests de permisos del RAG (PE3). No usan la API: el modelo se reemplaza por un cliente
simulado que guarda todo lo que se le habría enviado.

Uso:
    python -m pytest -v
"""

import pytest

from motor import Categoria, Rol
from rag import RAIZ, buscar, filtro_de_rol, ingestar, responder
from simulado import ClienteSimuladoRAG

# Documentos que cada rol NO puede leer (según el encabezado 'roles' de cada documento)
PROHIBIDOS = {
    Rol.CONTROLLER: set(),
    Rol.GERENCIA: set(),
    Rol.COMEX: {"reporte_margenes_octubre_2026", "tarifario_agentes_origen_2026",
                "politica_alertas_costos", "condiciones_comerciales_clientes"},
    Rol.VENDEDOR: {"reporte_margenes_octubre_2026", "tarifario_agentes_origen_2026",
                   "politica_alertas_costos", "tabla_equivalencias_costos"},
}

# Consultas pensadas para atraer justo los documentos restringidos
CONSULTAS_TENTADORAS = [
    "¿Cuál fue el margen de la operación QF1004 en octubre?",
    "¿Cuál es la tarifa TAR-NGB-SAI-40HC del agente de Ningbo?",
    "Muéstrame el reporte de márgenes y los costos internos",
    "¿Qué plazo de pago y línea de crédito tiene Importadora Sur?",
    "¿Cuándo una diferencia de costo genera una alerta?",
]


@pytest.fixture(scope="module")
def coleccion(tmp_path_factory):
    """Base de ChromaDB nueva, solo para los tests."""
    return ingestar(ruta_base=tmp_path_factory.mktemp("chroma"))


# ---------------------------------------------------------------------
# 1. Un test por rol: nunca recibe fragmentos de documentos que no puede leer
# ---------------------------------------------------------------------

@pytest.mark.parametrize("rol", list(Rol), ids=[r.value for r in Rol])
def test_rol_solo_recibe_documentos_permitidos(coleccion, rol):
    for consulta in CONSULTAS_TENTADORAS:
        for modo in ("hibrida", "vectorial", "bm25"):
            fragmentos = buscar(consulta, rol, k=50, modo=modo, coleccion=coleccion)
            documentos = {f.documento for f in fragmentos}
            assert not documentos & PROHIBIDOS[rol], f"{rol.value} recibió {documentos & PROHIBIDOS[rol]}"


@pytest.mark.parametrize("rol", list(Rol), ids=[r.value for r in Rol])
def test_filtro_se_aplica_en_la_base(coleccion, rol):
    """La base misma entrega solo fragmentos cuyo metadato 'roles' incluye el rol."""
    permitidos = coleccion.get(where=filtro_de_rol(rol), include=["metadatas"])
    assert permitidos["ids"], "cada rol debe poder leer al menos un documento"
    for meta in permitidos["metadatas"]:
        assert rol.value in meta["roles"]
        assert meta["documento"] not in PROHIBIDOS[rol]


def test_controller_y_gerencia_si_ven_documentos_restringidos(coleccion):
    for rol in (Rol.CONTROLLER, Rol.GERENCIA):
        fragmentos = buscar("¿Cuál es la tarifa TAR-NGB-SAI-40HC?", rol, k=3, coleccion=coleccion)
        assert fragmentos[0].documento == "tarifario_agentes_origen_2026"


# ---------------------------------------------------------------------
# 2. El documento restringido tampoco llega al prompt del modelo
# ---------------------------------------------------------------------

@pytest.mark.parametrize("rol, consulta, operacion, secreto", [
    (Rol.VENDEDOR, "¿Cuál fue el margen de la operación QF1004?", "QF1004", "820 USD"),
    (Rol.VENDEDOR, "¿Cuál es la tarifa acordada con Ningbo Star Logistics?", "QF1004", "2.800 USD"),
    (Rol.COMEX, "¿Cuál fue el margen de la operación QF1004?", "QF1004", "820 USD"),
    (Rol.COMEX, "¿Qué línea de crédito tiene Importadora Sur?", "QF1004", "25.000 USD"),
], ids=["vendedor-margen", "vendedor-tarifa", "comex-margen", "comex-credito"])
def test_documento_restringido_no_llega_al_prompt(coleccion, rol, consulta, operacion, secreto):
    cliente = ClienteSimuladoRAG()
    r = responder({"operacion_id": operacion, "rol": rol.value, "consulta": consulta},
                  coleccion=coleccion, cliente=cliente)
    enviado = cliente.prompts_enviados()
    assert enviado, "el modelo debió recibir al menos los documentos permitidos"
    assert secreto not in enviado
    for documento in PROHIBIDOS[rol]:
        assert documento not in enviado
        assert all(f.documento != documento for f in r.fuentes)


# ---------------------------------------------------------------------
# 3. Sin evidencia -> requiere_humano = true, sin inventar
# ---------------------------------------------------------------------

def test_sin_fragmentos_no_llama_al_modelo_y_pide_humano(tmp_path):
    # Una base que solo tiene un documento restringido: el vendedor no puede leer nada
    carpeta = tmp_path / "docs"
    carpeta.mkdir()
    origen = RAIZ / "documentos" / "reporte_margenes_octubre_2026.md"
    (carpeta / origen.name).write_text(origen.read_text(encoding="utf-8"), encoding="utf-8")
    coleccion = ingestar(carpeta=carpeta, ruta_base=tmp_path / "chroma")

    cliente = ClienteSimuladoRAG()
    r = responder({"operacion_id": "QF1004", "rol": "vendedor",
                   "consulta": "¿Cuál fue el margen de la operación QF1004?"},
                  coleccion=coleccion, cliente=cliente)
    assert r.ok and r.salida.requiere_humano
    assert r.salida.categoria == Categoria.SIN_EVIDENCIA
    assert r.fuentes == []
    assert cliente.mensajes.peticiones == []          # no se gastó en el modelo


def test_fuente_inventada_se_rechaza(coleccion):
    cliente = ClienteSimuladoRAG(fuentes_fijas=["reporte_margenes_octubre_2026#99"])
    r = responder({"operacion_id": "VF102", "rol": "comex",
                   "consulta": "¿Qué le falta a la operación VF102 para cerrar?"},
                  coleccion=coleccion, cliente=cliente)
    assert not r.ok
    assert r.error.tipo == "salida_invalida"
    assert len(cliente.mensajes.peticiones) == 2       # el primer intento y el reintento


def test_rol_inexistente_no_recibe_nada(coleccion):
    with pytest.raises(ValueError):
        buscar("margen QF1004", "jefe", coleccion=coleccion)
    r = responder({"operacion_id": "QF1004", "rol": "jefe", "consulta": "¿Cuál fue el margen?"},
                  coleccion=coleccion, cliente=ClienteSimuladoRAG())
    assert not r.ok and r.error.tipo == "entrada_invalida"
