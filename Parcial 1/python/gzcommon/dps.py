# -*- coding: utf-8 -*-
"""
Registro contra el Device Provisioning Service (DPS) usando la API REST.

Los orígenes que usan el SDK `azure-iot-device` no necesitan este módulo: el
SDK hace el aprovisionamiento internamente. Aquí se implementa el flujo a mano
porque dos dispositivos de la flota no usan el SDK:

  * dev09 - puente HTTP/REST
  * dev10 - cliente MQTT explícito (paho-mqtt)

Ambos necesitan saber a QUÉ IoT Hub los asignó IoT Central antes de poder
publicar, y ese dato solo lo entrega DPS.

Flujo (api-version 2021-06-01):
  1. PUT  /{idScope}/registrations/{regId}/register
  2. Si devuelve 202 -> sondear GET .../operations/{operationId}
  3. La respuesta 'assigned' trae assignedHub y deviceId.

El resultado se guarda en caché en disco para no reprovisionar en cada
arranque (DPS tiene cuota) y para que un reinicio del servicio sea inmediato.
"""

import json
import os
import time

import requests

from . import sas

API_VERSION = "2021-06-01"
_CACHE_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".dps-cache")


def _ruta_cache(device_id):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    return os.path.join(_CACHE_DIR, "{}.json".format(device_id))


def _leer_cache(device_id):
    ruta = _ruta_cache(device_id)
    if not os.path.exists(ruta):
        return None
    try:
        with open(ruta, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def _escribir_cache(device_id, datos):
    with open(_ruta_cache(device_id), "w", encoding="utf-8") as fh:
        json.dump(datos, fh, indent=2)


def registrar(id_scope, device_id, device_key, model_id=None,
              endpoint="global.azure-devices-provisioning.net",
              usar_cache=True, log=print):
    """
    Registra el dispositivo y devuelve {'assignedHub': ..., 'deviceId': ...}.
    """
    if usar_cache:
        cache = _leer_cache(device_id)
        if cache and cache.get("assignedHub"):
            log("DPS: hub en caché -> {}".format(cache["assignedHub"]))
            return cache

    recurso = "{}/registrations/{}".format(id_scope, device_id)
    token = sas.generar_token_sas(recurso, device_key, "registration", 3600)

    url = "https://{}/{}/registrations/{}/register?api-version={}".format(
        endpoint, id_scope, device_id, API_VERSION)
    cabeceras = {
        "Content-Type": "application/json; charset=utf-8",
        "Authorization": token,
        "Accept": "application/json",
    }
    cuerpo = {"registrationId": device_id}
    if model_id:
        # IoT Central usa el payload para asignar la plantilla correcta.
        cuerpo["payload"] = {"modelId": model_id}

    log("DPS: registrando {} (modelo {})".format(device_id, model_id))
    resp = requests.put(url, headers=cabeceras, json=cuerpo, timeout=30)
    resp.raise_for_status()
    datos = resp.json()

    operation_id = datos.get("operationId")
    estado = datos.get("status")

    # Sondeo de la operación hasta que DPS asigne el hub.
    intentos = 0
    while estado in ("assigning", "unassigned") and intentos < 30:
        espera = float(resp.headers.get("Retry-After", 3))
        time.sleep(espera)
        intentos += 1
        url_op = ("https://{}/{}/registrations/{}/operations/{}"
                  "?api-version={}").format(endpoint, id_scope, device_id,
                                            operation_id, API_VERSION)
        resp = requests.get(url_op, headers=cabeceras, timeout=30)
        resp.raise_for_status()
        datos = resp.json()
        estado = datos.get("status")
        log("DPS: intento {} -> estado {}".format(intentos, estado))

    if estado != "assigned":
        raise RuntimeError(
            "DPS no asignó el dispositivo {}: {}".format(device_id, datos))

    estado_registro = datos["registrationState"]
    resultado = {
        "assignedHub": estado_registro["assignedHub"],
        "deviceId": estado_registro["deviceId"],
        "registradoEn": estado_registro.get("createdDateTimeUtc"),
    }
    log("DPS: asignado a {}".format(resultado["assignedHub"]))
    _escribir_cache(device_id, resultado)
    return resultado
