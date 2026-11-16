"""RAG con permisos y búsqueda híbrida del Asistente de control de márgenes (PE3).

Tres piezas:
    ingestar()   lee los documentos, los limpia, los divide en fragmentos y los guarda en ChromaDB
    buscar()     búsqueda híbrida (vectorial + BM25) con el filtro de rol aplicado en la base
    responder()  recibe la Entrada de la PE2 y devuelve la Salida más la lista de fuentes

Uso:
    python src/rag.py ingestar
    python src/rag.py buscar "¿Qué le falta a la operación L207?" --rol vendedor
    python src/rag.py buscar "TAR-SZX-SAI-40HC" --rol controller --modo vectorial
    python src/rag.py responder "¿Qué le falta para cerrar?" --operacion L207 --rol comex
    python src/rag.py responder "..." --operacion QF1004 --rol vendedor --simulado
"""

import argparse
import copy
import json
import os
import re
import sys
import time
import unicodedata
from pathlib import Path
from typing import Optional

import anthropic
import chromadb
from chromadb.config import Settings
from pydantic import BaseModel, ValidationError
from rank_bm25 import BM25Okapi

from motor import (ESQUEMA_SALIDA, MODELO, RAIZ, Categoria, Entrada, ErrorEstructurado, Metricas,
                   Rol, Salida, calcular_costo, describir_errores, log)

CARPETA_DOCUMENTOS = RAIZ / "documentos"
CARPETA_BASE = RAIZ / "chroma_db"           # base local (no se sube a GitHub)

# Configuraciones de fragmentado medidas en la PE3:
# (tamaño máximo en caracteres, solape, ¿respeta las secciones del documento?)
CONFIGURACIONES = {
    "chico": (300, 40, True),       # estructural: corta por sección y luego por tamaño
    "grande": (1500, 150, False),   # fijo: corta todo el documento por tamaño, mezclando secciones
}
CONFIG_ELEGIDA = "chico"                    # la que ganó la medición top-k (resultados/medicion_rag.md)

K_RRF = 60              # constante de Reciprocal Rank Fusion
CANDIDATOS = 20         # cuántos resultados trae cada buscador antes de fusionar
K_RESPUESTA = 4         # cuántos fragmentos recibe Claude
MAX_INTENTOS = 2

PROMPT_SISTEMA_RAG = (RAIZ / "prompts" / "sistema_rag.md").read_text(encoding="utf-8")
PLANTILLA_CONSULTA_RAG = (RAIZ / "prompts" / "consulta_rag.md").read_text(encoding="utf-8")

# La Salida de la PE2 más la lista de fragmentos que Claude usó
ESQUEMA_SALIDA_RAG = copy.deepcopy(ESQUEMA_SALIDA)
ESQUEMA_SALIDA_RAG["properties"]["fuentes"] = {"type": "array", "items": {"type": "string"}}
ESQUEMA_SALIDA_RAG["required"].append("fuentes")


# =====================================================================
# 1. INGESTA
# =====================================================================

def leer_documento(ruta: Path) -> tuple[str, list[str], str]:
    """Lee un .md y separa su encabezado (título y roles que pueden leerlo) del contenido."""
    texto = ruta.read_text(encoding="utf-8").replace("\r\n", "\n")
    encabezado = re.match(r"^---\n(.*?)\n---\n", texto, re.S)
    if not encabezado:
        raise ValueError(f"{ruta.name}: falta el encabezado con 'titulo' y 'roles'")
    datos = dict(linea.split(":", 1) for linea in encabezado.group(1).splitlines())
    roles = [Rol(r.strip()).value for r in datos["roles"].split(",")]   # Rol() rechaza roles inventados
    return datos["titulo"].strip(), roles, texto[encabezado.end():]


def limpiar(texto: str) -> str:
    """Quita espacios sobrantes, líneas vacías repetidas y el título principal (ya va en los metadatos)."""
    lineas = [linea.strip() for linea in texto.split("\n") if not linea.startswith("# ")]
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lineas)).strip()


def separar_secciones(texto: str) -> list[tuple[str, str]]:
    """Divide el documento en sus secciones '## ...' (chunking estructural)."""
    secciones, nombre, actual = [], "Introducción", []
    for linea in texto.split("\n"):
        if linea.startswith("## "):
            if "".join(actual).strip():
                secciones.append((nombre, "\n".join(actual).strip()))
            nombre, actual = linea[3:].strip(), []
        else:
            actual.append(linea)
    if "".join(actual).strip():
        secciones.append((nombre, "\n".join(actual).strip()))
    return secciones


def dividir(texto: str, tamano: int, solape: int) -> list[str]:
    """Corta una sección en fragmentos de hasta `tamano` caracteres sin partir líneas,
    repitiendo al inicio de cada fragmento el final del anterior (`solape` caracteres)."""
    unidades = []
    for linea in texto.split("\n"):
        linea = linea.strip()
        if not linea:
            continue
        if len(linea) <= tamano:
            unidades.append(linea)
            continue
        actual = ""                                   # línea muy larga: se corta por palabras
        for palabra in linea.split(" "):
            if actual and len(actual) + 1 + len(palabra) > tamano:
                unidades.append(actual)
                actual = palabra
            else:
                actual = f"{actual} {palabra}".strip()
        if actual:
            unidades.append(actual)

    fragmentos, actual = [], ""
    for unidad in unidades:
        if actual and len(actual) + 1 + len(unidad) > tamano:
            fragmentos.append(actual)
            cola = actual[-solape:] if solape else ""
            cola = cola[cola.find(" ") + 1:] if " " in cola else ""   # el solape parte en una palabra entera
            actual = f"…{cola}\n{unidad}" if cola else unidad
        else:
            actual = f"{actual}\n{unidad}" if actual else unidad
    if actual:
        fragmentos.append(actual)
    return fragmentos


def _cliente_chroma(ruta_base: Path):
    return chromadb.PersistentClient(path=str(ruta_base), settings=Settings(anonymized_telemetry=False))


def ingestar(carpeta: Path = CARPETA_DOCUMENTOS, config: str = CONFIG_ELEGIDA,
             ruta_base: Path = CARPETA_BASE, mostrar: bool = False):
    """Procesa todos los documentos de la carpeta y devuelve la colección de ChromaDB."""
    tamano, solape, por_seccion = CONFIGURACIONES[config]
    cliente = _cliente_chroma(ruta_base)
    nombre = f"documentos_{config}"
    try:
        cliente.delete_collection(nombre)          # se rehace completa: ingestar dos veces da lo mismo
    except Exception:
        pass
    coleccion = cliente.create_collection(nombre, metadata={"hnsw:space": "cosine"})

    ids, textos, metadatos = [], [], []
    for ruta in sorted(Path(carpeta).glob("*.md")):
        titulo, roles, contenido = leer_documento(ruta)
        numero = 0
        limpio = limpiar(contenido)
        secciones = separar_secciones(limpio) if por_seccion else [("(varias secciones)", limpio)]
        for seccion, texto_seccion in secciones:
            for pedazo in dividir(texto_seccion, tamano, solape):
                fragmento_id = f"{ruta.stem}#{numero:02d}"
                ids.append(fragmento_id)
                # Prefijo de contexto: el fragmento "sabe" de qué documento y sección viene
                textos.append(f"Documento: {titulo} | Sección: {seccion}\n{pedazo}")
                metadatos.append({
                    "documento": ruta.stem,
                    "titulo": titulo,
                    "seccion": seccion,
                    "fragmento": numero,
                    "roles": roles,
                    "caracteres": len(pedazo),
                })
                numero += 1
        if mostrar:
            print(f"  {ruta.name:<40} {numero:>3} fragmentos  roles: {', '.join(roles)}")

    coleccion.add(ids=ids, documents=textos, metadatas=metadatos)
    if mostrar:
        print(f"Total: {len(ids)} fragmentos en la colección '{nombre}' "
              f"(tamaño {tamano}, solape {solape}, {'por sección' if por_seccion else 'corte fijo'}) "
              f"-> {ruta_base}")
    return coleccion


def abrir_coleccion(config: str = CONFIG_ELEGIDA, ruta_base: Path = CARPETA_BASE):
    try:
        return _cliente_chroma(ruta_base).get_collection(f"documentos_{config}")
    except Exception:
        sys.exit("No existe la base de documentos. Corre primero: python src/rag.py ingestar")


# =====================================================================
# 2. BÚSQUEDA HÍBRIDA CON PERMISOS
# =====================================================================

class Fragmento(BaseModel):
    documento: str
    fragmento_id: str
    seccion: str
    texto: str
    puntaje: float


PALABRAS_VACIAS = {
    "a", "al", "con", "cual", "de", "del", "el", "en", "es", "esta", "fue", "la", "las", "le", "lo",
    "los", "me", "para", "por", "que", "se", "su", "un", "una", "y", "o", "hay", "tiene", "nuestra",
}


def tokenizar(texto: str) -> list[str]:
    """Minúsculas, sin tildes, sin palabras vacías. Los códigos como TAR-NGB-SAI-40HC
    quedan enteros y además por partes."""
    texto = unicodedata.normalize("NFKD", texto.lower())
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    tokens = []
    for token in re.findall(r"[a-z0-9]+(?:[-/][a-z0-9]+)*", texto):
        if token in PALABRAS_VACIAS:
            continue
        tokens.append(token)
        if "-" in token or "/" in token:
            tokens.extend(parte for parte in re.split(r"[-/]", token) if parte not in PALABRAS_VACIAS)
    return tokens


def filtro_de_rol(rol: Rol) -> dict:
    """La cláusula WHERE de seguridad: solo fragmentos cuyo metadato 'roles' incluye el rol."""
    return {"roles": {"$contains": rol.value}}


def buscar(consulta: str, usuario, k: int = K_RESPUESTA, modo: str = "hibrida",
           coleccion=None) -> list[Fragmento]:
    """Devuelve los k fragmentos más relevantes que el usuario puede leer.

    usuario: el rol (Rol o texto). El filtro de permisos se aplica DENTRO de las
    consultas a ChromaDB, así que un fragmento restringido nunca sale de la base.
    modo: "hibrida" (vectorial + BM25 fusionados con RRF), "vectorial" o "bm25".
    """
    rol = Rol(usuario)                         # un rol que no existe lanza ValueError
    coleccion = coleccion or abrir_coleccion()
    filtro = filtro_de_rol(rol)

    # Búsqueda vectorial, filtrada por rol en la base (pre-filtering)
    vectorial = coleccion.query(query_texts=[consulta], n_results=CANDIDATOS, where=filtro,
                                include=["documents", "metadatas", "distances"])
    datos = {}
    ranking_vectorial = []
    for fid, texto, meta, distancia in zip(vectorial["ids"][0], vectorial["documents"][0],
                                           vectorial["metadatas"][0], vectorial["distances"][0]):
        datos[fid] = (texto, meta)
        ranking_vectorial.append((fid, 1 - distancia))

    # BM25 sobre los fragmentos que la base entrega para este rol (mismo filtro)
    permitidos = coleccion.get(where=filtro, include=["documents", "metadatas"])
    ranking_bm25 = []
    if permitidos["ids"]:
        bm25 = BM25Okapi([tokenizar(t) for t in permitidos["documents"]])
        puntajes = bm25.get_scores(tokenizar(consulta))
        orden = sorted(range(len(puntajes)), key=lambda i: puntajes[i], reverse=True)
        for i in orden[:CANDIDATOS]:
            if puntajes[i] <= 0:
                break
            fid = permitidos["ids"][i]
            datos[fid] = (permitidos["documents"][i], permitidos["metadatas"][i])
            ranking_bm25.append((fid, float(puntajes[i])))

    if modo == "vectorial":
        ranking = ranking_vectorial
    elif modo == "bm25":
        ranking = ranking_bm25
    else:
        # Reciprocal Rank Fusion: suma 1 / (60 + posición) de cada lista
        rrf = {}
        for lista in (ranking_vectorial, ranking_bm25):
            for posicion, (fid, _) in enumerate(lista, start=1):
                rrf[fid] = rrf.get(fid, 0) + 1 / (K_RRF + posicion)
        ranking = sorted(rrf.items(), key=lambda par: par[1], reverse=True)

    resultado = []
    for fid, puntaje in ranking[:k]:
        texto, meta = datos[fid]
        resultado.append(Fragmento(documento=meta["documento"], fragmento_id=fid,
                                   seccion=meta["seccion"], texto=texto, puntaje=round(puntaje, 4)))
    return resultado


# =====================================================================
# 3. RESPUESTA CON FUENTES
# =====================================================================

class Fuente(BaseModel):
    documento: str
    seccion: str
    fragmento_id: str


class RespuestaRAG(BaseModel):
    ok: bool
    salida: Optional[Salida] = None
    fuentes: list[Fuente] = []
    error: Optional[ErrorEstructurado] = None
    metricas: Metricas


def consulta_de_busqueda(entrada: Entrada) -> str:
    """El texto que se busca: la consulta más el código de la operación, si no lo trae."""
    if entrada.operacion_id in entrada.consulta:
        return entrada.consulta
    return f"{entrada.operacion_id} {entrada.consulta}"


def _llamar_claude(cliente, mensajes: list):
    return cliente.beta.messages.create(
        model=MODELO,
        max_tokens=16000,
        system=PROMPT_SISTEMA_RAG,
        messages=mensajes,
        output_config={"effort": "medium",
                       "format": {"type": "json_schema", "schema": ESQUEMA_SALIDA_RAG}},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )


def responder(entrada, coleccion=None, cliente=None, k: int = K_RESPUESTA) -> RespuestaRAG:
    """Recibe la Entrada de la PE2 (objeto o diccionario) y responde solo con lo recuperado."""
    metricas = Metricas(modelo=MODELO)
    inicio = time.perf_counter()

    def terminar(ok, salida=None, fuentes=None, error=None) -> RespuestaRAG:
        metricas.latencia_ms = round((time.perf_counter() - inicio) * 1000, 1)
        metricas.costo_usd = calcular_costo(MODELO, metricas.tokens_entrada, metricas.tokens_salida)
        return RespuestaRAG(ok=ok, salida=salida, fuentes=fuentes or [], error=error, metricas=metricas)

    try:
        entrada = entrada if isinstance(entrada, Entrada) else Entrada.model_validate(entrada)
    except ValidationError as e:
        return terminar(False, error=ErrorEstructurado(
            tipo="entrada_invalida", mensaje="La consulta no cumple el contrato de Entrada",
            campos=describir_errores(e)))

    fragmentos = buscar(consulta_de_busqueda(entrada), entrada.rol, k=k, coleccion=coleccion)

    # Sin fragmentos para este rol: no se llama al modelo y decide una persona
    if not fragmentos:
        log.info("No hay fragmentos que este rol pueda leer: requiere revisión humana")
        return terminar(True, salida=Salida(
            categoria=Categoria.SIN_EVIDENCIA, documentos_recibidos=[], documentos_faltantes=[],
            requiere_humano=True, confianza=0.0,
            respuesta="No encontré documentos que pueda consultar para responder esto. Lo debe revisar una persona."))

    por_id = {f.fragmento_id: f for f in fragmentos}
    texto_fragmentos = "\n\n".join(f"[{f.fragmento_id}]\n{f.texto}" for f in fragmentos)
    mensajes = [{"role": "user", "content": PLANTILLA_CONSULTA_RAG.format(
        rol=entrada.rol.value, operacion_id=entrada.operacion_id,
        consulta=entrada.consulta, fragmentos=texto_fragmentos)}]

    cliente = cliente or anthropic.Anthropic()
    errores = []
    for intento in range(1, MAX_INTENTOS + 1):
        metricas.intentos = intento
        try:
            respuesta = _llamar_claude(cliente, mensajes)
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
        errores = []
        try:
            datos = json.loads(texto)
            citadas = list(dict.fromkeys(datos.pop("fuentes", [])))      # sin repetidas
            salida = Salida.model_validate(datos)
            inventadas = [c for c in citadas if c not in por_id]
            if inventadas:
                errores.append({"campo": "fuentes", "problema": "cita fragmentos que no se entregaron",
                                "valor": ", ".join(inventadas)})
            if salida.categoria != Categoria.SIN_EVIDENCIA and not citadas:
                errores.append({"campo": "fuentes", "problema": "una respuesta con evidencia debe citar al menos un fragmento",
                                "valor": "[]"})
        except json.JSONDecodeError as e:
            errores.append({"campo": "(json)", "problema": str(e), "valor": texto[:80]})
        except ValidationError as e:
            errores = describir_errores(e)

        if not errores:
            log.info(f"Salida válida en el intento {intento}")
            fuentes = [Fuente(documento=por_id[c].documento, seccion=por_id[c].seccion, fragmento_id=c)
                       for c in citadas]
            return terminar(True, salida=salida, fuentes=fuentes)

        for c in errores:
            log.warning(f"Intento {intento}/{MAX_INTENTOS}: falló '{c['campo']}' -> {c['problema']}")
        mensajes.append({"role": "assistant", "content": respuesta.content})
        mensajes.append({"role": "user", "content": "Tu respuesta no pasó la validación. Corrige estos "
                         "problemas y responde de nuevo:\n" + json.dumps(errores, ensure_ascii=False)})

    return terminar(False, error=ErrorEstructurado(
        tipo="salida_invalida", mensaje=f"La salida no se pudo validar después de {MAX_INTENTOS} intentos",
        campos=errores))


# =====================================================================
# 4. EJECUCIÓN DESDE LA TERMINAL
# =====================================================================

def main():
    parser = argparse.ArgumentParser(description="RAG con permisos del asistente de control de márgenes")
    sub = parser.add_subparsers(dest="comando", required=True)

    p_ing = sub.add_parser("ingestar", help="procesa la carpeta documentos/ y la guarda en ChromaDB")
    p_ing.add_argument("--config", choices=CONFIGURACIONES, default=CONFIG_ELEGIDA)

    p_bus = sub.add_parser("buscar", help="muestra los fragmentos que recupera un rol")
    p_bus.add_argument("consulta")
    p_bus.add_argument("--rol", required=True)
    p_bus.add_argument("--modo", choices=["hibrida", "vectorial", "bm25"], default="hibrida")
    p_bus.add_argument("-k", type=int, default=K_RESPUESTA)

    p_res = sub.add_parser("responder", help="responde una consulta con fuentes")
    p_res.add_argument("consulta")
    p_res.add_argument("--rol", required=True)
    p_res.add_argument("--operacion", required=True)
    p_res.add_argument("--simulado", action="store_true", help="sin API key: respuesta simulada")

    args = parser.parse_args()

    if args.comando == "ingestar":
        print(f"Ingestando {CARPETA_DOCUMENTOS} ...")
        coleccion = ingestar(config=args.config, mostrar=True)
        ejemplo = coleccion.get(ids=["tarifario_agentes_origen_2026#03"], include=["documents", "metadatas"])
        print("\nEjemplo de fragmento y sus metadatos:")
        print(json.dumps({"id": ejemplo["ids"][0], "metadatos": ejemplo["metadatas"][0],
                          "texto": ejemplo["documents"][0]}, ensure_ascii=False, indent=2))

    elif args.comando == "buscar":
        for f in buscar(args.consulta, args.rol, k=args.k, modo=args.modo):
            print(f"{f.puntaje:>8}  {f.fragmento_id:<38} {f.seccion}")

    else:
        cliente = None
        if args.simulado:
            from simulado import ClienteSimuladoRAG
            cliente = ClienteSimuladoRAG()
        elif not os.getenv("ANTHROPIC_API_KEY"):
            sys.exit("Falta ANTHROPIC_API_KEY en .env (o ejecuta con --simulado)")
        r = responder({"operacion_id": args.operacion, "rol": args.rol, "consulta": args.consulta},
                      cliente=cliente)
        print(r.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
