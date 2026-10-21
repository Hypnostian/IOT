"""Consulta de la toma guardada en InfluxDB: inicio, fin, puntos, cobertura y huecos.

Uso dentro del contenedor de la ingesta:
    docker compose exec ingesta python consultar.py
    docker compose exec ingesta python consultar.py --desde 2026-10-10T19:00:00Z --hasta 2026-10-14T19:00:00Z
"""

import argparse
import os
from datetime import datetime, timedelta, timezone

from influxdb_client import InfluxDBClient

HORA_COLOMBIA = timezone(timedelta(hours=-5))
BUCKET = os.environ["INFLUX_BUCKET"]

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("--desde", default="0", help="inicio en RFC3339 (por defecto, todo el bucket)")
parser.add_argument("--hasta", default="now()", help="fin en RFC3339 (por defecto, ahora)")
parser.add_argument("--hueco-s", type=float, default=30, help="separacion minima para contar un hueco")
args = parser.parse_args()

desde = args.desde if args.desde in ("0", "now()") or args.desde.startswith("-") else f"time(v: \"{args.desde}\")"
hasta = args.hasta if args.hasta in ("now()",) or args.hasta.startswith("-") else f"time(v: \"{args.hasta}\")"
intervalo = float(os.getenv("INTERVALO_S", "10"))


def local(instante):
    return instante.astimezone(HORA_COLOMBIA).strftime("%Y-%m-%d %H:%M:%S")


with InfluxDBClient(url=os.getenv("INFLUX_URL", "http://influxdb:8086"),
                    token=os.environ["INFLUX_TOKEN"], org=os.environ["INFLUX_ORG"]) as cliente:
    consulta = cliente.query_api()
    tiempos = [r.get_time() for r in consulta.query_stream(f'''
from(bucket: "{BUCKET}")
  |> range(start: {desde}, stop: {hasta})
  |> filter(fn: (r) => r._measurement == "ambiente" and r._field == "seq")
  |> group()
  |> sort(columns: ["_time"])
  |> keep(columns: ["_time"])''')]

    if not tiempos:
        print("No hay puntos guardados en ese rango.")
        raise SystemExit(1)

    inicio, fin = tiempos[0], tiempos[-1]
    duracion = fin - inicio
    esperados = int(duracion.total_seconds() // intervalo) + 1
    huecos = [(a, b) for a, b in zip(tiempos, tiempos[1:]) if (b - a).total_seconds() > args.hueco_s]
    forzados = sum(1 for r in consulta.query_stream(f'''
from(bucket: "{BUCKET}")
  |> range(start: {desde}, stop: {hasta})
  |> filter(fn: (r) => r._measurement == "ambiente" and r._field == "forzado" and r._value == 1)'''))

    print(f"Bucket: {BUCKET}   medicion: ambiente   hora: Colombia (UTC-5)")
    print(f"Inicio de la toma : {local(inicio)}")
    print(f"Ultimo punto      : {local(fin)}")
    print(f"Duracion          : {duracion.days} d {duracion.seconds // 3600} h {duracion.seconds % 3600 // 60} min")
    print(f"Puntos guardados  : {len(tiempos)} de {esperados} esperados a {intervalo:g} s "
          f"({100 * len(tiempos) / esperados:.2f} %)")
    print(f"Puntos forzados   : {forzados} (prueba de la alerta)")
    print(f"Huecos > {args.hueco_s:g} s    : {len(huecos)}")
    for a, b in huecos:
        print(f"  {local(a)} -> {local(b)}  ({(b - a).total_seconds():.0f} s sin datos)")

    print("\nUltimas 5 lecturas:")
    print(f"  {'hora Colombia':19}  {'dispositivo':12} {'temp C':>7} {'hum %':>6} {'lux':>9} {'retardo ms':>10}")
    for r in consulta.query_stream(f'''
from(bucket: "{BUCKET}")
  |> range(start: {desde}, stop: {hasta})
  |> filter(fn: (r) => r._measurement == "ambiente")
  |> pivot(rowKey: ["_time"], columnKey: ["_field"], valueColumn: "_value")
  |> group()
  |> sort(columns: ["_time"])
  |> tail(n: 5)'''):
        print(f"  {local(r.get_time()):19}  {r['dispositivo']:12} {r['temperature']:7.2f} {r['humidity']:6.1f} "
              f"{r['illuminance']:9.1f} {r['retardo_ms']:10.1f}")
