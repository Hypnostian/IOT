#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV02 - Lote de cultivo 2 "Zenón Bajo"
======================================

Origen de envío : Python con el SDK oficial `azure-iot-device`
Protocolo       : DPS (aprovisionamiento) + MQTT sobre TLS, puerto 8883
Plantilla       : GZ Nodo de Suelo (dtmi:granjazenon:cacao:NodoSuelo;1)
Intervalo       : 15 s  (la cadencia más rápida de la flota)
Equipo          : VM de Azure `granjazenon` (Ubuntu 24.04, Mexico Central)

Este es el nodo de referencia del catálogo: aprovisiona por DPS con una clave
derivada del grupo de inscripción, anuncia su Model ID, publica telemetría,
reporta propiedades, acepta una propiedad escribible (umbral de riego) y
responde dos comandos.

Uso:
    python dev02_lote2_dps_mqtt.py
    python dev02_lote2_dps_mqtt.py --una-vez            # prueba de humo
    python dev02_lote2_dps_mqtt.py --ventanas 03:10-03:35
"""

import sys

from gzcommon import runner, sim

CLAVE = "dev02"

# Estado local del nodo, modificable por comandos y propiedades escribibles.
ESTADO = {
    "riego_activo": False,
    "umbral_riego_vwc": 24.0,
    "ultima_calibracion": None,
}


def telemetria():
    datos = sim.nodo_suelo("lote2")
    # Si el riego está abierto, el suelo responde: sube la humedad y baja la CE.
    if ESTADO["riego_activo"]:
        datos["humedadSuelo"] = round(min(48.0, datos["humedadSuelo"] + 6.5), 1)
        datos["ceSuelo"] = round(max(0.15, datos["ceSuelo"] - 0.22), 2)
    return datos


def cmd_calibrar(payload):
    ESTADO["ultima_calibracion"] = runner.marca_tiempo()
    return {"resultado": "calibrado", "en": ESTADO["ultima_calibracion"]}


def cmd_riego(payload):
    encender = payload if isinstance(payload, bool) else bool(
        (payload or {}).get("encender", False))
    ESTADO["riego_activo"] = encender
    return {"resultado": "riego {}".format("abierto" if encender else "cerrado")}


def main():
    args = runner.argumentos(__doc__).parse_args()

    nodo = runner.Nodo(
        CLAVE,
        generar_telemetria=telemetria,
        propiedades_iniciales={
            "lote": "Lote 2 - Zenón Bajo",
            "variedadCacao": "ICS-95",
            "areaHa": 2.4,
            "profundidadSensorCm": 20,
            "umbralRiegoVWC": ESTADO["umbral_riego_vwc"],
            "intervaloTelemetriaSeg": 15,
        },
        comandos={
            "CalibrarSensorSuelo": cmd_calibrar,
            "ActivarRiegoLote": cmd_riego,
        },
        websockets=False,
        intervalo_s=args.intervalo,
        ventanas=args.ventanas,
        una_vez=args.una_vez,
    )
    nodo.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
