#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
DEV09 - Reservorio y riego "Pozo de Lucas"
==========================================

Origen de envío : puente HTTP/REST contra la Device REST API de IoT Hub
Protocolo       : HTTPS 443, sin MQTT y SIN el SDK azure-iot-device
Plantilla       : GZ Reservorio y Riego
Intervalo       : 120 s
Equipo          : VM de Azure `granjazenon`

Qué hace distinto a este origen
-------------------------------
Todo lo que los demás nodos delegan en el SDK, aquí se hace a mano:

  1. Aprovisionamiento: se llama a la API REST de DPS (PUT .../register) para
     averiguar a qué IoT Hub asignó IoT Central al dispositivo.
  2. Credencial: se construye el token SAS a mano
     (HMAC-SHA256 sobre "<recurso>\\n<expiración>") y se renueva solo.
  3. Publicación: POST https://{hub}/devices/{id}/messages/events

Limitación real que este nodo demuestra (y que se sustenta en la exposición)
---------------------------------------------------------------------------
HTTPS no mantiene sesión. IoT Central marca el estado de conexión a partir de
la sesión MQTT/AMQP viva, así que este dispositivo ingiere telemetría
correctamente pero NO aparece como "Connected" de forma continua. Es un
comportamiento esperado de la plataforma, no un error del puente, y está
documentado en la sección de evidencias.

Uso:
    python dev09_riego_http_rest.py
    python dev09_riego_http_rest.py --una-vez
"""

import json
import logging
import sys
import time

import requests

from gzcommon import config, dps, runner, sas, sim

CLAVE = "dev09"
API_VERSION_HUB = "2020-09-30"

ESTADO = {"bomba_forzada": None, "volumen_acumulado_m3": 0.0,
          "nivel_minimo_pct": 20.0, "ultimo_dia": None}


class PuenteHttp(object):
    """Cliente D2C mínimo sobre la API REST de dispositivo de IoT Hub."""

    def __init__(self, device_id, device_key, model_id, log):
        self.device_id = device_id
        self.device_key = device_key
        self.model_id = model_id
        self.log = log
        self.hub = None
        self.token = None
        self.sesion = requests.Session()

    def provisionar(self):
        resultado = dps.registrar(
            config.ID_SCOPE, self.device_id, self.device_key,
            self.model_id, config.DPS_ENDPOINT, log=self.log.info)
        self.hub = resultado["assignedHub"]

    def _asegurar_token(self):
        if self.token is None or sas.token_vencido(self.token, 300):
            recurso = "{}/devices/{}".format(self.hub, self.device_id)
            self.token = sas.generar_token_sas(recurso, self.device_key,
                                               vigencia_s=3600)
            self.log.info("Token SAS renovado (vigencia 60 min).")

    def publicar(self, datos):
        self._asegurar_token()
        url = "https://{}/devices/{}/messages/events?api-version={}".format(
            self.hub, self.device_id, API_VERSION_HUB)
        cabeceras = {
            "Authorization": self.token,
            "Content-Type": "application/json; charset=utf-8",
            # Propiedades de aplicación: viajan como cabeceras iothub-app-*
            "iothub-app-origen": "puente-http-rest",
            "iothub-app-predio": "granja-zenon",
        }
        respuesta = self.sesion.post(url, headers=cabeceras,
                                     data=json.dumps(datos).encode("utf-8"),
                                     timeout=25)
        if respuesta.status_code not in (200, 204):
            raise RuntimeError("HTTP {} - {}".format(
                respuesta.status_code, respuesta.text[:200]))
        return respuesta.status_code


def telemetria(intervalo_s):
    datos = sim.reservorio("riego")

    # Un comando remoto puede forzar el estado de la bomba.
    if ESTADO["bomba_forzada"] is not None:
        datos["bombaOn"] = ESTADO["bomba_forzada"]
        if not datos["bombaOn"]:
            datos["caudal"] = 0.0
            datos["presionLinea"] = round(max(0.3, datos["presionLinea"] * 0.2), 2)

    # Volumen acumulado del día: sumatoria del caudal, se reinicia a medianoche.
    dia = sim.dia_juliano()
    if ESTADO["ultimo_dia"] != dia:
        ESTADO["ultimo_dia"] = dia
        ESTADO["volumen_acumulado_m3"] = 0.0
    ESTADO["volumen_acumulado_m3"] += (datos["caudal"] * (intervalo_s / 60.0)) / 1000.0
    datos["volumenAcumulado"] = round(ESTADO["volumen_acumulado_m3"], 3)
    return datos


def main():
    args = runner.argumentos(__doc__).parse_args()
    dev = config.dispositivo(CLAVE)
    log = runner.configurar_log(dev["device_id"])
    intervalo = args.intervalo or dev["intervalo_s"]
    ventanas = runner.parsear_ventanas(args.ventanas)

    puente = PuenteHttp(dev["device_id"], dev["device_key"],
                        dev["model_id"], log)
    puente.provisionar()
    log.info("Puente HTTP/REST listo contra %s (intervalo %d s)",
             puente.hub, intervalo)

    enviados = 0
    while not runner._PARAR:
        if runner.en_ventana_desconexion(ventanas):
            log.warning("VENTANA DE DESCONEXIÓN: el puente no publica.")
            time.sleep(min(30, intervalo))
            continue
        try:
            datos = telemetria(intervalo)
            codigo = puente.publicar(datos)
            enviados += 1
            log.info("TX #%d (HTTP %d) -> %s", enviados, codigo,
                     json.dumps(datos, ensure_ascii=False))
        except Exception as exc:  # noqa: BLE001
            log.error("Fallo publicando por HTTP: %s", exc)
            time.sleep(15)
            continue

        if args.una_vez:
            log.info("Modo --una-vez: prueba de humo correcta.")
            break

        restante = intervalo
        while restante > 0 and not runner._PARAR:
            time.sleep(min(1.0, restante))
            restante -= 1.0

    log.info("Cierre del puente. Mensajes enviados: %d", enviados)
    return 0


if __name__ == "__main__":
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    sys.exit(main())
