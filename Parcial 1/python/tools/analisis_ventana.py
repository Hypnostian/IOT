#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Análisis de la ventana de 4 días de la flota "Granja Zenón - Cacao".

Calcula, por dispositivo / variable / día: MÁXIMO, MÍNIMO, PROMEDIO, RECUENTO
y SUMATORIA (esta última solo donde tiene sentido físico: lluvia, volúmenes,
horas acumuladas y contadores de eventos). Es exactamente la tabla que pide la
sección 6 del enunciado.

Entrada
-------
Los CSV que exporta IoT Central desde  Data explorer -> (consulta) -> Export.
Se admiten varios archivos a la vez; se detectan automáticamente la columna de
tiempo y la de dispositivo.

Uso:
    python tools/analisis_ventana.py docs/evidencias/*.csv
    python tools/analisis_ventana.py export.csv --salida docs/evidencias/resumen
    python tools/analisis_ventana.py export.csv --dias 2026-09-21 2026-09-22 \\
                                                       2026-09-23 2026-09-24
"""

import argparse
import glob
import os
import sys

import pandas as pd

# Variables cuya SUMATORIA tiene sentido fisico. Para el resto, sumar no
# significa nada (no se puede sumar una temperatura) y la tabla lo deja vacio.
SUMABLES = {
    "lluviaLote", "lluviaAcumulada", "horasHumectacion", "volumenAcumulado",
    "eventosAcceso",
}

# Nombres habituales de las columnas de IoT Central segun el idioma del export.
COLS_TIEMPO = ["timestamp", "$timestamp", "time", "Timestamp", "enqueuedTime",
               "marca de tiempo", "Marca de tiempo"]
COLS_DISPOSITIVO = ["deviceId", "$id", "device", "Device ID", "id",
                    "Id. de dispositivo"]


def _detectar(columnas, candidatas):
    minus = {c.lower(): c for c in columnas}
    for cand in candidatas:
        if cand.lower() in minus:
            return minus[cand.lower()]
    return None


def cargar(rutas):
    marcos = []
    for ruta in rutas:
        for archivo in sorted(glob.glob(ruta)):
            df = pd.read_csv(archivo)
            df["__archivo"] = os.path.basename(archivo)
            marcos.append(df)
            print("  leido  {:50s} {:6d} filas".format(
                os.path.basename(archivo), len(df)))
    if not marcos:
        raise SystemExit("No se encontro ningun CSV con esos patrones.")
    return pd.concat(marcos, ignore_index=True)


def analizar(df, dias=None, zona="America/Bogota"):
    col_t = _detectar(df.columns, COLS_TIEMPO)
    col_d = _detectar(df.columns, COLS_DISPOSITIVO)
    if col_t is None:
        raise SystemExit(
            "No encuentro la columna de tiempo. Columnas: {}".format(
                list(df.columns)))

    df[col_t] = pd.to_datetime(df[col_t], errors="coerce", utc=True)
    df = df.dropna(subset=[col_t])
    df["__dia"] = df[col_t].dt.tz_convert(zona).dt.date.astype(str)

    if dias:
        df = df[df["__dia"].isin(dias)]
        if df.empty:
            raise SystemExit("Ninguna fila cae en los dias {}".format(dias))

    ignorar = {col_t, col_d, "__archivo", "__dia"}
    numericas = [c for c in df.columns
                 if c not in ignorar and pd.api.types.is_numeric_dtype(df[c])]
    if not numericas:
        raise SystemExit("El export no trae columnas numericas de telemetria.")

    claves = ["__dia"] + ([col_d] if col_d else [])
    filas = []
    for llaves, grupo in df.groupby(claves, dropna=False):
        if not isinstance(llaves, tuple):
            llaves = (llaves,)
        dia = llaves[0]
        dispositivo = llaves[1] if len(llaves) > 1 else "(unico)"
        for var in numericas:
            serie = grupo[var].dropna()
            if serie.empty:
                continue
            filas.append({
                "dia": dia,
                "dispositivo": dispositivo,
                "variable": var,
                "recuento": int(serie.count()),
                "minimo": round(float(serie.min()), 3),
                "maximo": round(float(serie.max()), 3),
                "promedio": round(float(serie.mean()), 3),
                "desviacion": round(float(serie.std()), 3) if len(serie) > 1 else 0.0,
                "sumatoria": (round(float(serie.sum()), 3)
                              if var in SUMABLES else None),
            })

    resumen = pd.DataFrame(filas)
    if resumen.empty:
        raise SystemExit("No se pudo calcular nada: revisa el export.")
    return resumen.sort_values(["dispositivo", "variable", "dia"])


def a_markdown(resumen):
    """Genera la tabla lista para pegar en el documento del proyecto."""
    lineas = ["| Día | Dispositivo | Variable | Recuento | Mínimo | Máximo | "
              "Promedio | Sumatoria |",
              "|---|---|---|---:|---:|---:|---:|---:|"]
    for _, f in resumen.iterrows():
        suma = "—" if pd.isna(f["sumatoria"]) else "{:g}".format(f["sumatoria"])
        lineas.append("| {} | {} | {} | {} | {:g} | {:g} | {:g} | {} |".format(
            f["dia"], f["dispositivo"], f["variable"], f["recuento"],
            f["minimo"], f["maximo"], f["promedio"], suma))
    return "\n".join(lineas)


def huecos(df, umbral_factor=3.0, zona="America/Bogota"):
    """
    Detecta huecos en la serie: intervalos entre muestras consecutivas mucho
    mayores que la mediana de ese dispositivo. Es la evidencia objetiva de las
    desconexiones que pide el parcial.
    """
    col_t = _detectar(df.columns, COLS_TIEMPO)
    col_d = _detectar(df.columns, COLS_DISPOSITIVO)
    if col_t is None or col_d is None:
        return pd.DataFrame()

    df = df.copy()
    df[col_t] = pd.to_datetime(df[col_t], errors="coerce", utc=True)
    df = df.dropna(subset=[col_t]).sort_values([col_d, col_t])

    filas = []
    for dispositivo, grupo in df.groupby(col_d):
        deltas = grupo[col_t].diff().dt.total_seconds().dropna()
        if deltas.empty:
            continue
        mediana = deltas.median()
        if mediana <= 0:
            continue
        for idx, delta in deltas.items():
            if delta > mediana * umbral_factor and delta > 120:
                fin = grupo.loc[idx, col_t]
                filas.append({
                    "dispositivo": dispositivo,
                    "inicio_hueco": (fin - pd.Timedelta(seconds=delta))
                        .tz_convert(zona).strftime("%Y-%m-%d %H:%M:%S"),
                    "fin_hueco": fin.tz_convert(zona).strftime("%Y-%m-%d %H:%M:%S"),
                    "duracion_min": round(delta / 60.0, 1),
                    "cadencia_normal_s": round(mediana, 1),
                })
    return pd.DataFrame(filas).sort_values(
        ["dispositivo", "inicio_hueco"]) if filas else pd.DataFrame()


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("csv", nargs="+", help="CSV exportados de IoT Central.")
    p.add_argument("--dias", nargs="*", default=None,
                   help="Las 4 fechas de la ventana (AAAA-MM-DD).")
    p.add_argument("--salida", default="docs/evidencias/resumen_ventana",
                   help="Prefijo de los archivos de salida.")
    p.add_argument("--zona", default="America/Bogota")
    args = p.parse_args()

    print("Cargando exportaciones...")
    df = cargar(args.csv)
    print("Total: {} filas\n".format(len(df)))

    resumen = analizar(df, args.dias, args.zona)

    os.makedirs(os.path.dirname(args.salida) or ".", exist_ok=True)
    resumen.to_csv(args.salida + ".csv", index=False, encoding="utf-8")
    with open(args.salida + ".md", "w", encoding="utf-8") as fh:
        fh.write("# Comparativa de la ventana de 4 dias\n\n")
        fh.write(a_markdown(resumen))
        fh.write("\n")

    print(a_markdown(resumen))
    print()

    tabla_huecos = huecos(df, zona=args.zona)
    if not tabla_huecos.empty:
        tabla_huecos.to_csv(args.salida + "_huecos.csv", index=False,
                            encoding="utf-8")
        print("Huecos detectados en la serie (desconexiones):")
        print(tabla_huecos.to_string(index=False))
    else:
        print("No se detectaron huecos por encima del umbral.")

    print("\nArchivos generados:")
    print("  {}.csv".format(args.salida))
    print("  {}.md   <- tabla lista para el documento".format(args.salida))
    return 0


if __name__ == "__main__":
    sys.exit(main())
