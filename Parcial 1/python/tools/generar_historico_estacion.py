#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Genera el archivo histórico que reproduce DEV05 (replay de CSV).

El origen "replay de CSV o histórico" del catálogo necesita un archivo previo:
esto simula el caso real de una estación de campo que estuvo registrando en una
tarjeta SD sin cobertura y cuyos datos se suben después al sistema.

El histórico se construye con el mismo modelo agronómico que usa el resto de
la flota (gzcommon.sim), pero fechado en la campaña ANTERIOR, para que quede
claro que son datos grabados y no generados en vivo.

Uso:
    python tools/generar_historico_estacion.py
    python tools/generar_historico_estacion.py --dias 6 --paso 60
"""

import argparse
import csv
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gzcommon import sim  # noqa: E402

SALIDA = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "data", "estacion_campo_historico.csv")

CAMPOS = ["timestampFuente", "lluviaLote", "humedadFoliar",
          "horasHumectacion", "tempFoliar", "riesgoMonilia", "bateria"]


def generar(dias=6, paso_s=60, desplazamiento_dias=30):
    """
    dias                -- duración del histórico
    paso_s              -- resolución del registro (la SD grababa cada 60 s)
    desplazamiento_dias -- cuántos días atrás empieza la campaña grabada
    """
    ahora = datetime.datetime.now(datetime.timezone.utc)
    inicio = ahora - datetime.timedelta(days=desplazamiento_dias)
    inicio = inicio.replace(hour=0, minute=0, second=0, microsecond=0)
    ts0 = inicio.timestamp()

    filas = []
    horas_humectacion = 0.0
    dia_actual = None

    total = int((dias * 86400) / paso_s)
    for i in range(total):
        ts = ts0 + i * paso_s
        dia = sim.dia_juliano(ts)
        if dia != dia_actual:
            # El acumulado de humectación se reinicia cada día.
            horas_humectacion = 0.0
            dia_actual = dia

        muestra = sim.estacion_campo("estacion", ts, horas_humectacion)
        if muestra["humedadFoliar"] > 50.0:
            horas_humectacion += paso_s / 3600.0
            muestra["horasHumectacion"] = round(horas_humectacion, 2)

        fila = {"timestampFuente": datetime.datetime.fromtimestamp(
            ts, datetime.timezone.utc).isoformat()}
        fila.update(muestra)
        filas.append(fila)

    os.makedirs(os.path.dirname(SALIDA), exist_ok=True)
    with open(SALIDA, "w", encoding="utf-8", newline="") as fh:
        escritor = csv.DictWriter(fh, fieldnames=CAMPOS)
        escritor.writeheader()
        escritor.writerows(filas)

    lluvia_total = sum(f["lluviaLote"] for f in filas) * (paso_s / 3600.0)
    print("Archivo     : {}".format(SALIDA))
    print("Filas       : {}".format(len(filas)))
    print("Desde       : {}".format(filas[0]["timestampFuente"]))
    print("Hasta       : {}".format(filas[-1]["timestampFuente"]))
    print("Resolución  : {} s".format(paso_s))
    print("Lluvia acum.: {:.1f} mm".format(lluvia_total))
    return SALIDA


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dias", type=int, default=6)
    p.add_argument("--paso", type=int, default=60,
                   help="Resolución del registro en segundos.")
    p.add_argument("--desplazamiento", type=int, default=30,
                   help="Días hacia atrás en que empieza la campaña grabada.")
    args = p.parse_args()
    generar(args.dias, args.paso, args.desplazamiento)
    return 0


if __name__ == "__main__":
    sys.exit(main())
