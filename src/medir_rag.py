"""Medición del RAG de la PE3.

Uso:
    python src/medir_rag.py               # top-k con las dos configuraciones + híbrida vs vectorial (gratis)
    python src/medir_rag.py --con-claude  # además responde las 10 preguntas con Claude (~0,2 USD)

Escribe resultados/medicion_rag.md y, con --con-claude, resultados/respuestas_rag.md y .json.
"""

import argparse
import json
import logging
import os
import sys

from motor import RAIZ, Categoria, Entrada
from rag import (CONFIG_ELEGIDA, CONFIGURACIONES, K_RESPUESTA, buscar, consulta_de_busqueda,
                 ingestar, responder)

logging.getLogger("motor").setLevel(logging.WARNING)

K = 3   # top-k que se mide

# Consultas con códigos exactos para comparar híbrida vs solo vectorial.
# "acierta" = el fragmento que contiene la respuesta queda en el primer lugar.
EVIDENCIA_HIBRIDA = [
    ("¿Qué le falta a la operación VF102?", "controller", "estado_operaciones_noviembre#04"),
    ("QF1007", "controller", "estado_operaciones_noviembre#02"),
    ("¿Cuánto es el margen de L203?", "controller", "reporte_margenes_octubre_2026#03"),
    ("¿Qué le falta a la operación A104?", "controller", "estado_operaciones_noviembre#03"),
    ("¿Qué pasó con la debit note DN-7781?", "controller", "reporte_margenes_octubre_2026#01"),
]


def posicion(fragmentos, documento):
    """Primer lugar (1, 2, 3...) en que aparece el documento, o None."""
    for i, f in enumerate(fragmentos, start=1):
        if f.documento == documento:
            return i
    return None


def texto_pos(p):
    return f"{p}°" if p else "—"


def medir_recuperacion(preguntas):
    colecciones = {nombre: ingestar(config=nombre) for nombre in CONFIGURACIONES}
    filas, resumen = [], {}
    for nombre in CONFIGURACIONES:
        for modo in ("hibrida", "vectorial"):
            resumen[(nombre, modo)] = {"top1": 0, "topk": 0, "fugas": 0}

    for p in preguntas:
        entrada = Entrada(operacion_id=p["operacion_id"], rol=p["rol"], consulta=p["consulta"])
        fila = {"p": p, "pos": {}}
        for nombre, coleccion in colecciones.items():
            for modo in ("hibrida", "vectorial"):
                frags = buscar(consulta_de_busqueda(entrada), p["rol"], k=K, modo=modo, coleccion=coleccion)
                pos = posicion(frags, p["documento_esperado"]) if p["documento_esperado"] else None
                fila["pos"][(nombre, modo)] = pos
                r = resumen[(nombre, modo)]
                if p["tipo"] == "normal":
                    r["top1"] += pos == 1
                    r["topk"] += pos is not None
                elif p["tipo"] == "restringida":
                    r["fugas"] += pos is not None
        filas.append(fila)
    return filas, resumen, colecciones


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--con-claude", action="store_true")
    args = parser.parse_args()

    preguntas = json.loads((RAIZ / "datos" / "preguntas_prueba.json").read_text(encoding="utf-8"))
    normales = sum(1 for p in preguntas if p["tipo"] == "normal")
    restringidas = sum(1 for p in preguntas if p["tipo"] == "restringida")
    filas, resumen, colecciones = medir_recuperacion(preguntas)

    configs = list(CONFIGURACIONES)
    lineas = [
        "# Medición del RAG (PE3)", "",
        "Configuraciones de fragmentado: " + "; ".join(
            f"**{n}** = hasta {t} caracteres, solape {s}, {'respetando secciones' if sec else 'corte fijo sin secciones'}"
            for n, (t, s, sec) in CONFIGURACIONES.items()),
        f"Se mide si el documento correcto aparece en el 1er lugar y entre los primeros {K} resultados.", "",
        "## Resumen", "",
        f"| Configuración | Búsqueda | Top-1 (de {normales} normales) | Top-{K} (de {normales} normales) | "
        f"Fugas de documentos restringidos (de {restringidas}) |",
        "|---|---|---|---|---|",
    ]
    for (nombre, modo), r in resumen.items():
        lineas.append(f"| {nombre} | {modo} | {r['top1']}/{normales} | {r['topk']}/{normales} | {r['fugas']}/{restringidas} |")

    lineas += ["", "## Detalle por pregunta (posición del documento esperado)", "",
               "| # | Tipo | Rol | Consulta | Documento esperado | " +
               " | ".join(f"{n} híbrida" for n in configs) + f" | {CONFIG_ELEGIDA} vectorial |",
               "|---|---|---|---|---|" + "---|" * (len(configs) + 1)]
    for f in filas:
        p = f["p"]
        celdas = [texto_pos(f["pos"][(n, "hibrida")]) for n in configs]
        celdas.append(texto_pos(f["pos"][(CONFIG_ELEGIDA, "vectorial")]))
        lineas.append(f"| {p['id']} | {p['tipo']} | {p['rol']} | {p['consulta']} | "
                      f"{p['documento_esperado'] or '(ninguno)'} | " + " | ".join(celdas) + " |")
    lineas += ["", "En las restringidas, \"—\" es lo correcto: el rol no puede recibir ese documento."]

    # Desempate: cuánto texto recibe Claude por consulta (lo que se paga en tokens)
    lineas += ["", f"## Texto enviado a Claude ({K_RESPUESTA} fragmentos por consulta, preguntas normales)", "",
               "| Configuración | Fragmentos en la base | Caracteres promedio enviados |", "|---|---|---|"]
    for nombre, coleccion in colecciones.items():
        largos = []
        for p in preguntas:
            if p["tipo"] != "normal":
                continue
            entrada = Entrada(operacion_id=p["operacion_id"], rol=p["rol"], consulta=p["consulta"])
            frags = buscar(consulta_de_busqueda(entrada), p["rol"], k=K_RESPUESTA, coleccion=coleccion)
            largos.append(sum(len(f.texto) for f in frags))
        lineas.append(f"| {nombre} | {coleccion.count()} | {sum(largos) / len(largos):.0f} |")

    lineas += ["", f"## Híbrida vs. solo vectorial (configuración {CONFIG_ELEGIDA}, rol controller)", "",
               "Posición del fragmento que contiene la respuesta dentro del top-3 (— = no aparece).", "",
               "| Consulta | Fragmento con la respuesta | Vectorial | Híbrida | Resultado |",
               "|---|---|---|---|---|"]
    coleccion = colecciones[CONFIG_ELEGIDA]
    for consulta, rol, esperado in EVIDENCIA_HIBRIDA:
        pos = {}
        for modo in ("vectorial", "hibrida"):
            ids = [f.fragmento_id for f in buscar(consulta, rol, k=3, modo=modo, coleccion=coleccion)]
            pos[modo] = ids.index(esperado) + 1 if esperado in ids else None
        v, h = pos["vectorial"] or 99, pos["hibrida"] or 99
        resultado = ("**gana la híbrida**" if h < v else "gana la vectorial" if v < h
                     else "empate" if h < 99 else "ninguna lo encuentra")
        lineas.append(f"| {consulta} | {esperado} | {texto_pos(pos['vectorial'])} | "
                      f"{texto_pos(pos['hibrida'])} | {resultado} |")

    tabla = "\n".join(lineas)
    (RAIZ / "resultados").mkdir(exist_ok=True)
    (RAIZ / "resultados" / "medicion_rag.md").write_text(tabla + "\n", encoding="utf-8")
    print(tabla)

    if not args.con_claude:
        return
    if not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Falta ANTHROPIC_API_KEY en .env")

    print("\n=== Respuestas con Claude ===")
    salidas, filas_r, aciertos = [], [], 0
    for p in preguntas:
        r = responder({"operacion_id": p["operacion_id"], "rol": p["rol"], "consulta": p["consulta"]},
                      coleccion=coleccion)
        docs_citados = sorted({f.documento for f in r.fuentes})
        if not r.ok:
            correcto = False
        elif p["tipo"] == "normal":
            correcto = r.salida.categoria != Categoria.SIN_EVIDENCIA and p["documento_esperado"] in docs_citados
        elif p["tipo"] == "sin_respuesta":
            correcto = r.salida.requiere_humano and r.salida.categoria in (Categoria.SIN_EVIDENCIA, Categoria.FUERA_DE_ALCANCE)
        else:
            correcto = r.salida.requiere_humano and p["documento_esperado"] not in docs_citados
        aciertos += correcto
        salidas.append({"pregunta": p, "respuesta": json.loads(r.model_dump_json())})
        filas_r.append(
            f"| {p['id']} | {p['rol']} | {p['consulta']} | "
            f"{r.salida.categoria.value if r.ok else 'error: ' + r.error.tipo} | "
            f"{'sí' if r.ok and r.salida.requiere_humano else 'no'} | {', '.join(f.fragmento_id for f in r.fuentes) or '—'} | "
            f"{'✔' if correcto else '✘'} | {r.metricas.costo_usd:.4f} | {r.metricas.latencia_ms:.0f} |")
        print(f"{p['id']}: {'OK' if correcto else 'FALLA'}")

    md = ["# Respuestas del RAG con Claude (PE3)", "",
          "| # | Rol | Consulta | Categoría | Requiere humano | Fuentes citadas | ¿Correcta? | Costo USD | Latencia ms |",
          "|---|---|---|---|---|---|---|---|---|", *filas_r, "",
          f"**Correctas: {aciertos}/{len(preguntas)}.** Normal = cita el documento esperado; "
          "sin respuesta = requiere humano sin inventar; restringida = requiere humano y no cita el documento restringido."]
    (RAIZ / "resultados" / "respuestas_rag.md").write_text("\n".join(md) + "\n", encoding="utf-8")
    (RAIZ / "resultados" / "respuestas_rag.json").write_text(
        json.dumps(salidas, ensure_ascii=False, indent=2), encoding="utf-8")
    print("\n".join(md))


if __name__ == "__main__":
    main()
