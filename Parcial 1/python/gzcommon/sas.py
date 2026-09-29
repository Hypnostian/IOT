# -*- coding: utf-8 -*-
"""
Generación de tokens SAS (Shared Access Signature) para Azure IoT.

Se usa en los dos orígenes que NO utilizan el SDK azure-iot-device y por lo
tanto tienen que construir su propia credencial:

  * dev09 - puente HTTP/REST  (Authorization: SharedAccessSignature ...)
  * dev10 - cliente MQTT explícito con paho-mqtt (password del CONNECT)

Formato del token (documentación de Microsoft):

    SharedAccessSignature sr=<recurso>&sig=<firma>&se=<expiracion>[&skn=<politica>]

donde firma = Base64( HMAC-SHA256( Base64Decode(clave), <recurso>\n<expiracion> ) )
"""

import base64
import hashlib
import hmac
import time
import urllib.parse


def generar_token_sas(uri, clave, nombre_politica=None, vigencia_s=3600):
    """
    Construye un token SAS para el recurso `uri`.

    uri    -- recurso sin esquema, p. ej. "mi-hub.azure-devices.net/devices/gz-09"
              o "0ne00FE0A26/registrations/gz-09-riego-http" para DPS.
    clave  -- clave simétrica en Base64.
    nombre_politica -- 'registration' para DPS; None para un dispositivo de IoT Hub.
    """
    recurso = urllib.parse.quote_plus(uri)
    expiracion = int(time.time()) + int(vigencia_s)

    a_firmar = "{}\n{}".format(recurso, expiracion).encode("utf-8")
    secreto = base64.b64decode(clave)
    firma = base64.b64encode(
        hmac.new(secreto, a_firmar, hashlib.sha256).digest())

    token = "SharedAccessSignature sr={}&sig={}&se={}".format(
        recurso, urllib.parse.quote(firma, safe=""), expiracion)
    if nombre_politica:
        token += "&skn={}".format(nombre_politica)
    return token


def expiracion_token(token):
    """Devuelve el epoch de expiración declarado dentro de un token SAS."""
    for parte in token.split("&"):
        if parte.startswith("se="):
            return int(parte[3:])
    return 0


def token_vencido(token, margen_s=300):
    """True si al token le quedan menos de `margen_s` segundos de vida."""
    return time.time() > (expiracion_token(token) - margen_s)
