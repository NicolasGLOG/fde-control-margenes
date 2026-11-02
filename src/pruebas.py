"""Corre las 5 consultas de prueba y arma la tabla de medición de la PE2.

Uso:
    python src/pruebas.py              # contra Claude (gasta saldo, ~0,1 USD en total)
    python src/pruebas.py --simulado   # sin API key, para probar el flujo

Escribe la tabla en resultados/medicion.md.
"""

import argparse
import json
import os
import sys

from motor import RAIZ, Motor

# Meta del KPI técnico de la PE1: precisión del checklist >= 95%
META_PRECISION = 95.0


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--simulado", action="store_true")
    args = parser.parse_args()

    cliente = None
    if args.simulado:
        from simulado import ClienteSimulado
        cliente = ClienteSimulado()
    elif not os.getenv("ANTHROPIC_API_KEY"):
        sys.exit("Falta ANTHROPIC_API_KEY en .env (o ejecuta con --simulado)")

    casos = json.loads((RAIZ / "datos" / "consultas_prueba.json").read_text(encoding="utf-8"))
    motor = Motor(cliente=cliente)

    filas = []
    for i, caso in enumerate(casos, start=1):
        print(f"\n=== Consulta {i}: {caso['nombre']} ===")
        r = motor.procesar(caso["entrada"])
        esperado = caso["esperado"]
        acierto = (r.ok and r.salida.categoria.value == esperado["categoria"]
                   and r.salida.requiere_humano == esperado["requiere_humano"])
        print(r.model_dump_json(indent=2))
        filas.append({
            "n": i,
            "consulta": caso["entrada"]["consulta"],
            "valido": "Sí" if r.ok else f"No ({r.error.tipo})",
            "acierto": acierto,
            "tokens_entrada": r.metricas.tokens_entrada,
            "tokens_salida": r.metricas.tokens_salida,
            "costo": r.metricas.costo_usd,
            "latencia": r.metricas.latencia_ms,
            "intentos": r.metricas.intentos,
        })

    n = len(filas)
    prom_entrada = sum(f["tokens_entrada"] for f in filas) / n
    prom_salida = sum(f["tokens_salida"] for f in filas) / n
    prom_costo = sum(f["costo"] for f in filas) / n
    prom_latencia = sum(f["latencia"] for f in filas) / n
    validas = sum(1 for f in filas if f["valido"] == "Sí")
    precision = sum(1 for f in filas if f["acierto"]) / n * 100

    lineas = [
        f"# Medición PE2 · modelo {motor.modelo}" + (" (SIMULADO)" if args.simulado else ""),
        "",
        "| # | Consulta | ¿Validó? | ¿Acertó? | Tokens (entrada / salida) | Costo USD | Latencia ms | Intentos |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for f in filas:
        lineas.append(
            f"| {f['n']} | {f['consulta']} | {f['valido']} | {'Sí' if f['acierto'] else 'No'} | "
            f"{f['tokens_entrada']} / {f['tokens_salida']} | {f['costo']:.6f} | {f['latencia']:.0f} | {f['intentos']} |"
        )
    lineas += [
        f"| **Promedio** | | {validas}/{n} | {precision:.0f}% | {prom_entrada:.0f} / {prom_salida:.0f} | "
        f"{prom_costo:.6f} | {prom_latencia:.0f} | |",
        "",
        f"**KPI técnico (meta PE1: precisión ≥ {META_PRECISION:.0f}%):** {precision:.0f}% "
        f"→ {'cumple' if precision >= META_PRECISION else 'no cumple'} la meta en este set de {n} consultas.",
        "",
        "Precisión = consultas donde la categoría y la decisión de revisión humana coinciden con lo esperado.",
    ]

    tabla = "\n".join(lineas)
    carpeta = RAIZ / "resultados"
    carpeta.mkdir(exist_ok=True)
    (carpeta / "medicion.md").write_text(tabla + "\n", encoding="utf-8")
    print("\n" + tabla)


if __name__ == "__main__":
    main()
