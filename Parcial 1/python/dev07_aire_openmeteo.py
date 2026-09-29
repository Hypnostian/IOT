#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV07 - Calidad de aire rural "Camino Real"
===========================================

Origen de envío : API pública Open-Meteo Air Quality (sin clave, sin registro)
Protocolo       : HTTPS 443 hacia la API  ->  DPS + MQTT 8883 hacia IoT Central
Plantilla       : GZ Calidad de Aire Rural
Intervalo       : 600 s (10 min) - la fuente publica valores horarios
Equipo          : VM de Azure `granjazenon`

Por qué este origen es distinto del de DEV06
--------------------------------------------
DEV06 consume un servicio comercial autenticado con clave de suscripción de
Azure Maps. DEV07 consume una API pública abierta, de otro dominio (calidad del
aire, no meteorología), sin autenticación y con un contrato de datos distinto.
Son dos puentes REST independientes, con su propio código y su propio feed.

Qué se mide y por qué importa en el escenario
---------------------------------------------
El camino de saca del predio es destapado. En verano, el paso de volquetas y el
secado del cacao al sol levantan material particulado que se deposita sobre el
grano tendido en la marquesina. Vigilar PM2.5 y PM10 permite decidir cuándo
cubrir el secadero. El umbral de la Rule sigue la guía OMS 2021 para PM2.5 en
24 h: 15 µg/m³ como valor guía, 37.5 µg/m³ como meta intermedia 3.

Endpoints utilizados
--------------------
https://air-quality-api.open-meteo.com/v1/air-quality  (PM2.5, PM10, AQI europeo)
https://api.open-meteo.com/v1/forecast                 (temperatura y HR)

Uso:
    python dev07_aire_openmeteo.py
    python dev07_aire_openmeteo.py --una-vez
"""

import collections
import sys

import requests

from gzcommon import config, runner, sim

CLAVE = "dev07"
URL_AIRE = "https://air-quality-api.open-meteo.com/v1/air-quality"
URL_TIEMPO = "https://api.open-meteo.com/v1/forecast"

# Media móvil de PM10 para detectar el evento de polvo por cosecha.
HISTORIAL_PM10 = collections.deque(maxlen=12)
ESTADO = {"fuente": "desconocida", "fallos": 0, "exitos": 0,
          "umbral_pm25": 37.5}


def _consultar_aire():
    parametros = {
        "latitude": config.LAT,
        "longitude": config.LON,
        "current": "pm10,pm2_5,european_aqi",
        "timezone": config.ZONA_HORARIA,
    }
    respuesta = requests.get(URL_AIRE, params=parametros, timeout=20)
    respuesta.raise_for_status()
    return respuesta.json().get("current", {})


def _consultar_tiempo():
    parametros = {
        "latitude": config.LAT,
        "longitude": config.LON,
        "current": "temperature_2m,relative_humidity_2m",
        "timezone": config.ZONA_HORARIA,
    }
    respuesta = requests.get(URL_TIEMPO, params=parametros, timeout=20)
    respuesta.raise_for_status()
    return respuesta.json().get("current", {})


def _detectar_polvo(pm10):
    """Marca evento cuando el PM10 dobla su media móvil reciente."""
    if len(HISTORIAL_PM10) >= 4:
        media = sum(HISTORIAL_PM10) / len(HISTORIAL_PM10)
        evento = pm10 > max(8.0, media * 2.0)
    else:
        evento = False
    HISTORIAL_PM10.append(pm10)
    return evento


def _modelo_local():
    """Respaldo si la API pública no responde."""
    sol = sim.curva_diurna()
    # El polvo del camino sube con la actividad diurna y baja con la lluvia.
    lluvia = sim.evento_lluvia(None, "estacion-lluvia")
    base = 7.5 + 9.0 * sol + sim.ruido("aire-pm", 2.5, 1800)
    if lluvia > 1.0:
        base *= 0.45
    pm25 = max(1.0, base)
    pm10 = max(2.0, pm25 * 2.35 + sim.ruido("aire-pm10", 3.0, 1800))
    return {
        "pm25": round(pm25, 1),
        "pm10": round(pm10, 1),
        "aqi": int(max(1, min(150, pm25 * 2.4))),
        "hrAire": round(max(35.0, min(99.0, 90.0 - 26.0 * sol)), 1),
        "tempAire": round(20.9 + 10.1 * sol, 1),
        "polvoCosecha": _detectar_polvo(pm10),
    }


def telemetria():
    try:
        aire = _consultar_aire()
        tiempo = _consultar_tiempo()
        pm25 = float(aire.get("pm2_5") or 0.0)
        pm10 = float(aire.get("pm10") or 0.0)
        datos = {
            "pm25": round(pm25, 1),
            "pm10": round(pm10, 1),
            "aqi": int(aire.get("european_aqi") or 0),
            "hrAire": round(float(tiempo.get("relative_humidity_2m") or 0.0), 1),
            "tempAire": round(float(tiempo.get("temperature_2m") or 0.0), 1),
            "polvoCosecha": _detectar_polvo(pm10),
        }
        ESTADO["fuente"] = "Open-Meteo Air Quality"
        ESTADO["exitos"] += 1
        return datos
    except Exception as exc:  # noqa: BLE001
        ESTADO["fallos"] += 1
        ESTADO["fuente"] = "modelo local (API degradada)"
        import logging
        logging.getLogger("gz").warning(
            "Open-Meteo no respondió (%s). Se publica el modelo local.", exc)
        return _modelo_local()


def main():
    args = runner.argumentos(__doc__).parse_args()

    nodo = runner.Nodo(
        CLAVE,
        generar_telemetria=telemetria,
        propiedades_iniciales={
            "fuenteDatos": "Open-Meteo Air Quality API (open data, CC-BY 4.0)",
            "latitud": config.LAT,
            "longitud": config.LON,
            "umbralPm25": ESTADO["umbral_pm25"],
        },
        intervalo_s=args.intervalo,
        ventanas=args.ventanas,
        una_vez=args.una_vez,
    )
    nodo.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
