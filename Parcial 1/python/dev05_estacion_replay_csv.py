#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV05 - Estación de campo "Casa de Zenón"
=========================================

Origen de envío : replay de un CSV histórico (no hay generación en vivo)
Protocolo       : DPS + MQTT sobre TLS 8883
Plantilla       : GZ Estación de Campo (dtmi:granjazenon:cacao:EstacionCampo;1)
Intervalo       : 60 s
Equipo          : VM de Azure `granjazenon`

Caso real que representa
------------------------
La estación de lote graba en una tarjeta SD porque está en un punto sin
cobertura. Cada cierto tiempo se recoge la tarjeta y se vuelca el histórico al
sistema. Por eso este nodo es el que MEJOR muestra la asincronía y la
desconexión de la flota: reproduce datos fechados en la campaña anterior, y
tiene ventanas de silencio programadas que dejan huecos visibles en la serie
de IoT Central.

Diferencia importante frente a los demás orígenes: cada mensaje lleva
`timestampFuente`, la marca de tiempo en que el dato fue REGISTRADO, distinta
de la marca de ingestión que pone IoT Central al recibirlo. Esa diferencia es
lo que se analiza en el documento.

Uso:
    python dev05_estacion_replay_csv.py
    python dev05_estacion_replay_csv.py --ventanas 01:00-02:30,13:00-13:40
"""

import csv
import os
import sys

from gzcommon import runner

CLAVE = "dev05"
CSV_HISTORICO = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                             "data", "estacion_campo_historico.csv")

NUMERICOS = {"lluviaLote": float, "humedadFoliar": float,
             "horasHumectacion": float, "tempFoliar": float,
             "riesgoMonilia": int, "bateria": int}


class Reproductor(object):
    """Recorre el CSV en bucle y entrega una fila por cada muestra."""

    def __init__(self, ruta):
        if not os.path.exists(ruta):
            raise SystemExit(
                "No existe {}. Genéralo con:\n"
                "    python tools/generar_historico_estacion.py".format(ruta))
        with open(ruta, "r", encoding="utf-8") as fh:
            self.filas = list(csv.DictReader(fh))
        if not self.filas:
            raise SystemExit("El histórico está vacío: {}".format(ruta))
        self.i = 0
        self.vueltas = 0

    def siguiente(self):
        fila = self.filas[self.i]
        self.i += 1
        if self.i >= len(self.filas):
            self.i = 0
            self.vueltas += 1
        datos = {}
        for clave, valor in fila.items():
            if clave in NUMERICOS:
                try:
                    datos[clave] = NUMERICOS[clave](float(valor))
                except (TypeError, ValueError):
                    continue
            elif clave == "timestampFuente":
                # Se reenvía tal cual: es la marca de tiempo de la FUENTE.
                datos[clave] = valor
        return datos


def main():
    parser = runner.argumentos(__doc__)
    parser.add_argument("--csv", default=CSV_HISTORICO,
                        help="Ruta del histórico a reproducir.")
    args = parser.parse_args()

    reproductor = Reproductor(args.csv)

    nodo = runner.Nodo(
        CLAVE,
        generar_telemetria=reproductor.siguiente,
        propiedades_iniciales={
            "lote": "Lote 1 - Zenón Alto (estación de referencia)",
            "alturaInstalacionM": 1.8,
        },
        comandos={
            "ReiniciarPluviometro": lambda p: {"resultado": "acumulado en cero"},
        },
        intervalo_s=args.intervalo,
        # Por defecto este nodo tiene dos ventanas de silencio al día: es el
        # dispositivo elegido para evidenciar el "hueco documentado" del parcial.
        ventanas=args.ventanas or "01:00-02:30,13:00-13:40",
        una_vez=args.una_vez,
    )
    nodo.log.info("Histórico cargado: %d filas desde %s",
                  len(reproductor.filas), os.path.basename(args.csv))
    nodo.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
