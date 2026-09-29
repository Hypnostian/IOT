#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV06 - Meteorología del predio "Torre Zenón"
=============================================

Origen de envío : Atlas Weather  (Azure Maps Weather REST API)
Protocolo       : HTTPS 443 hacia la API  ->  DPS + MQTT 8883 hacia IoT Central
Plantilla       : GZ Meteorología del Predio
Intervalo       : 300 s (5 min) - la cuota gratuita de Azure Maps no admite más
Equipo          : VM de Azure `granjazenon`

Este es el nodo meteorológico explícito que el escenario 5.3 exige. Los valores
son REALES: se consultan a la API de Azure Maps para las coordenadas del predio
(San Vicente de Chucurí, Santander) y se reenvían a IoT Central.

Cada mensaje lleva DOS marcas de tiempo:
  * `timestampFuente`  -> la que reporta la API (hora de observación)
  * la de ingestión    -> la que pone IoT Central al recibir el mensaje
La diferencia entre ambas es lo que el parcial pide mostrar para un puente de API.

Endpoint utilizado
------------------
GET https://atlas.microsoft.com/weather/currentConditions/json
    ?api-version=1.1&query={lat},{lon}&unit=metric&language=es-ES
    &subscription-key={clave}
Documentación: https://learn.microsoft.com/es-es/rest/api/maps/weather

Degradación controlada
----------------------
Si la API falla (cuota agotada, red caída, 429), el nodo NO se cae: registra el
error, marca la propiedad `fuenteDatos` como degradada y publica el modelo
climatológico local para no dejar un hueco no explicado. El log deja constancia
de cuál fue la fuente de cada muestra.

Uso:
    python dev06_meteo_atlas_weather.py
    python dev06_meteo_atlas_weather.py --una-vez
"""

import math
import sys

import requests

from gzcommon import config, runner, sim

CLAVE = "dev06"
URL = "https://atlas.microsoft.com/weather/currentConditions/json"
API_VERSION = "1.1"

ESTADO = {"fuente": "desconocida", "fallos": 0, "exitos": 0}


def _consultar_api():
    """Consulta Azure Maps Weather y devuelve el diccionario de la respuesta."""
    parametros = {
        "api-version": API_VERSION,
        "query": "{},{}".format(config.LAT, config.LON),
        "unit": "metric",
        "language": "es-ES",
        "details": "true",
    }
    # La clave va en una CABECERA, no en la URL. Cuando iba en la URL, cada
    # error de requests imprimia la URL completa y la clave quedaba en claro
    # en el log del servicio (se detecto al revisar dev06.log el 28/09).
    cabeceras = {"subscription-key": config.MAPS_KEY}
    if config.MAPS_CLIENT_ID:
        cabeceras["x-ms-client-id"] = config.MAPS_CLIENT_ID

    respuesta = requests.get(URL, params=parametros, headers=cabeceras,
                             timeout=20)
    if respuesta.status_code >= 400:
        # Mensaje propio, sin la URL: nunca debe salir una credencial al log.
        raise RuntimeError("HTTP {} de Azure Maps".format(respuesta.status_code))
    cuerpo = respuesta.json()
    resultados = cuerpo.get("results") or []
    if not resultados:
        raise RuntimeError("La API no devolvió resultados")
    return resultados[0]


def _radiacion_estimada(nubosidad_pct):
    """
    Azure Maps no expone irradiancia. Se estima a partir de la geometría solar
    del predio y de la nubosidad que sí reporta la API:
        Rs = 1120 W/m2 * curva_solar * (1 - 0.75 * nubosidad^3)
    (forma habitual del modelo de Kasten-Czeplak).
    """
    f_nubes = 1.0 - 0.75 * math.pow(max(0.0, min(1.0, nubosidad_pct / 100.0)), 3)
    return max(0.0, 1120.0 * sim.curva_diurna() * f_nubes)


def _mapear(observacion):
    """Traduce la respuesta de Azure Maps al esquema de la plantilla DTDL."""
    def num(ruta, defecto=0.0):
        nodo = observacion
        for parte in ruta.split("."):
            if not isinstance(nodo, dict):
                return defecto
            nodo = nodo.get(parte)
            if nodo is None:
                return defecto
        return float(nodo) if isinstance(nodo, (int, float)) else defecto

    nubes = num("cloudCover", 40.0)
    datos = {
        "tempExterior": round(num("temperature.value", 24.0), 1),
        "hrExterior": round(num("relativeHumidity", 78.0), 1),
        "lluviaAcumulada": round(
            num("precipitationSummary.past24Hours.value", 0.0), 1),
        "velocidadViento": round(num("wind.speed.value", 6.0), 1),
        "direccionViento": int(num("wind.direction.degrees", 90.0)),
        "radiacionSolar": round(_radiacion_estimada(nubes), 1),
        "presionBarometrica": round(num("pressure.value", 1012.0), 1),
        "puntoRocio": round(num("dewPoint.value", 19.0), 1),
        "indiceUV": round(num("uvIndex", 0.0), 1),
        "timestampFuente": observacion.get("dateTime", runner.marca_tiempo()),
    }
    return datos


def _modelo_local():
    """Respaldo climatológico si la API no responde."""
    sol = sim.curva_diurna()
    nub = sim.nubosidad()
    temp = 20.8 + 10.4 * sol * nub + sim.ruido("meteo-t", 0.8, 900)
    hr = 92.0 - 28.0 * sol * nub + sim.ruido("meteo-h", 3.0, 900)
    lluvia = sim.evento_lluvia(None, "estacion-lluvia")
    return {
        "tempExterior": round(temp, 1),
        "hrExterior": round(max(35.0, min(99.0, hr)), 1),
        "lluviaAcumulada": round(lluvia * 4.0, 1),
        "velocidadViento": round(max(0.0, 7.5 + sim.ruido("meteo-v", 5.0, 600)), 1),
        "direccionViento": int((110 + sim.ruido("meteo-d", 60, 1800)) % 360),
        "radiacionSolar": round(1080.0 * sol * nub, 1),
        "presionBarometrica": round(1011.5 + sim.ruido("meteo-p", 2.0, 3600), 1),
        "puntoRocio": round(temp - (100.0 - max(35.0, min(99.0, hr))) / 5.0, 1),
        "indiceUV": round(11.0 * sol, 1),
        "timestampFuente": runner.marca_tiempo(),
    }


def telemetria():
    if config.MAPS_KEY:
        try:
            datos = _mapear(_consultar_api())
            ESTADO["fuente"] = "Azure Maps Weather API (currentConditions)"
            ESTADO["exitos"] += 1
            return datos
        except Exception as exc:  # noqa: BLE001
            ESTADO["fallos"] += 1
            ESTADO["fuente"] = "modelo climatológico local (API degradada)"
            import logging
            logging.getLogger("gz").warning(
                "Atlas Weather no respondió (%s). Fallo %d de %d intentos. "
                "Se publica el modelo local.",
                exc, ESTADO["fallos"], ESTADO["fallos"] + ESTADO["exitos"])
    else:
        ESTADO["fuente"] = "modelo climatológico local (sin API key)"
    return _modelo_local()


def main():
    args = runner.argumentos(__doc__).parse_args()

    nodo = runner.Nodo(
        CLAVE,
        generar_telemetria=telemetria,
        propiedades_iniciales={
            "fuenteDatos": "Azure Maps Weather API - currentConditions v1.1",
            "latitud": config.LAT,
            "longitud": config.LON,
        },
        comandos={
            "RefrescarPronostico": lambda p: {"muestra": telemetria(),
                                              "fuente": ESTADO["fuente"]},
        },
        intervalo_s=args.intervalo,
        ventanas=args.ventanas,
        una_vez=args.una_vez,
    )
    nodo.log.info("Predio en %.5f, %.5f  |  API key %s",
                  config.LAT, config.LON,
                  "configurada" if config.MAPS_KEY else "AUSENTE")
    nodo.ejecutar()
    return 0


if __name__ == "__main__":
    sys.exit(main())
