# -*- coding: utf-8 -*-
"""
Configuración central de la flota "Granja Zenón - Cacao".

Ningún secreto vive en el código: todo se lee del archivo .env (que está en
.gitignore) o de variables de entorno reales del sistema. Esto cumple el
requisito del parcial: "Credenciales solo por variable de entorno o DPS
attested".

Variables esperadas (ver .env.example):

    GZ_ID_SCOPE            Ámbito de ID de la aplicación IoT Central
    GZ_GROUP_SAS_KEY       Clave SAS primaria del grupo de conexión
                           (Permissions -> Device connection groups ->
                            SAS-IoT-Devices -> Shared access signature)
    GZ_MAPS_SUBSCRIPTION_KEY   API key de Azure Maps (Atlas Weather)
    GZ_MAPS_CLIENT_ID          Client ID de la cuenta de Azure Maps
    GZ_LAT / GZ_LON        Coordenadas del predio
"""

import base64
import hashlib
import hmac
import os

# --------------------------------------------------------------------------
# Carga del archivo .env (sin dependencias externas)
# --------------------------------------------------------------------------
_RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_ENV = os.path.join(_RAIZ, ".env")


def _cargar_env(ruta=_ENV):
    if not os.path.exists(ruta):
        return
    with open(ruta, "r", encoding="utf-8") as fh:
        for linea in fh:
            linea = linea.strip()
            if not linea or linea.startswith("#") or "=" not in linea:
                continue
            clave, _, valor = linea.partition("=")
            clave = clave.strip()
            valor = valor.strip().strip('"').strip("'")
            # Las variables de entorno reales tienen prioridad sobre .env
            os.environ.setdefault(clave, valor)


_cargar_env()


def env(nombre, defecto=None, obligatorio=False):
    valor = os.environ.get(nombre, defecto)
    if obligatorio and not valor:
        raise SystemExit(
            "Falta la variable de entorno {}. Copia .env.example a .env y "
            "complétalo.".format(nombre))
    return valor


# --------------------------------------------------------------------------
# Identidad de la aplicación y del predio
# --------------------------------------------------------------------------
ID_SCOPE = env("GZ_ID_SCOPE", obligatorio=True)
GROUP_SAS_KEY = env("GZ_GROUP_SAS_KEY", obligatorio=True)

DPS_ENDPOINT = env("GZ_DPS_ENDPOINT", "global.azure-devices-provisioning.net")

MAPS_KEY = env("GZ_MAPS_SUBSCRIPTION_KEY", "")
MAPS_CLIENT_ID = env("GZ_MAPS_CLIENT_ID", "")

# Predio: vereda La Colorada, San Vicente de Chucurí, Santander (Colombia).
# Zona cacaotera real, a ~90 km de Bucaramanga.
LAT = float(env("GZ_LAT", "6.88060"))
LON = float(env("GZ_LON", "-73.41030"))
ALTITUD_M = float(env("GZ_ALTITUD_M", "692"))
ZONA_HORARIA = env("GZ_TZ", "America/Bogota")

PREDIO = "Granja Zenón - Cacao"


# --------------------------------------------------------------------------
# Derivación de claves por dispositivo a partir de la clave de grupo
# --------------------------------------------------------------------------
def derivar_clave_dispositivo(device_id, group_key=None):
    """
    Deriva la clave simétrica de un dispositivo a partir de la clave SAS del
    grupo de inscripción, exactamente como lo hace `az iot central device
    compute-device-key`:

        device_key = Base64( HMAC-SHA256( Base64Decode(group_key), device_id ) )

    Así ningún dispositivo lleva la clave maestra del grupo.
    """
    clave = group_key or GROUP_SAS_KEY
    secreto = base64.b64decode(clave)
    firma = hmac.new(secreto, msg=device_id.encode("utf-8"),
                     digestmod=hashlib.sha256).digest()
    return base64.b64encode(firma).decode("utf-8")


# --------------------------------------------------------------------------
# Catálogo de los 10 dispositivos de la flota
# --------------------------------------------------------------------------
# Cada fila declara: id en IoT Central, nombre visible, zona, plantilla
# (model id DTDL), origen de envío, protocolo e intervalo de muestreo.
# La asincronía exigida por el parcial sale de la columna "intervalo":
# 15 s, 20 s, 30 s, 60 s, 120 s, 300 s y 600 s -> 7 cadencias distintas.

CATALOGO = {
    "dev01": {
        "device_id": "gz-01-lote1-wokwi",
        "nombre": "Lote de cultivo 1 - Zenón Alto",
        "zona": "Lote de cultivo 1",
        "model_id": "dtmi:granjazenon:cacao:NodoSuelo;1",
        "origen": "Wokwi ESP32 #1 (Arduino + Azure SDK for C)",
        "protocolo": "MQTT 8883 / DPS",
        "intervalo_s": 15,
    },
    "dev02": {
        "device_id": "gz-02-lote2-python",
        "nombre": "Lote de cultivo 2 - Zenón Bajo",
        "zona": "Lote de cultivo 2",
        "model_id": "dtmi:granjazenon:cacao:NodoSuelo;1",
        "origen": "Python azure-iot-device (DPS + MQTT)",
        "protocolo": "MQTT 8883 / DPS",
        "intervalo_s": 15,
    },
    "dev03": {
        "device_id": "gz-03-lote3-twin",
        "nombre": "Lote de cultivo 3 - La Vega",
        "zona": "Lote de cultivo 3",
        "model_id": "dtmi:granjazenon:cacao:NodoSuelo;1",
        "origen": "Digital Twin / simulador nativo de IoT Central",
        "protocolo": "interno de la plataforma",
        "intervalo_s": 30,
    },
    "dev04": {
        "device_id": "gz-04-dosel-ws",
        "nombre": "Dosel y sombrío - Bosque de Bartolito",
        "zona": "Dosel / sombra",
        "model_id": "dtmi:granjazenon:cacao:NodoDosel;1",
        "origen": "Python #2 con transporte distinto (MQTT sobre WebSocket)",
        "protocolo": "MQTT over WebSocket 443",
        "intervalo_s": 60,
    },
    "dev05": {
        "device_id": "gz-05-estacion-replay",
        "nombre": "Estación de campo - Casa de Zenón",
        "zona": "Estación de campo",
        "model_id": "dtmi:granjazenon:cacao:EstacionCampo;1",
        "origen": "Replay de CSV histórico",
        "protocolo": "MQTT 8883 / DPS",
        "intervalo_s": 60,
    },
    "dev06": {
        "device_id": "gz-06-meteo-atlas",
        "nombre": "Meteorología del predio - Torre Zenón",
        "zona": "Meteorología del predio",
        "model_id": "dtmi:granjazenon:cacao:MeteorologiaPredio;1",
        "origen": "Atlas Weather (Azure Maps Weather REST API)",
        "protocolo": "HTTPS 443 -> MQTT 8883",
        "intervalo_s": 300,
    },
    "dev07": {
        "device_id": "gz-07-aire-openmeteo",
        "nombre": "Calidad de aire rural - Camino Real",
        "zona": "Calidad de aire rural",
        "model_id": "dtmi:granjazenon:cacao:CalidadAireRural;1",
        "origen": "API pública Open-Meteo Air Quality",
        "protocolo": "HTTPS 443 -> MQTT 8883",
        "intervalo_s": 600,
    },
    "dev08": {
        "device_id": "gz-08-secado-wokwi",
        "nombre": "Secado y fermentación - Marinela",
        "zona": "Secado / fermentación",
        "model_id": "dtmi:granjazenon:cacao:SecadoFermentacion;1",
        "origen": "Wokwi ESP32 #2 (segunda instancia, firmware distinto)",
        "protocolo": "MQTT 8883 / DPS",
        "intervalo_s": 20,
    },
    "dev09": {
        "device_id": "gz-09-riego-http",
        "nombre": "Reservorio y riego - Pozo de Lucas",
        "zona": "Reservorio / riego",
        "model_id": "dtmi:granjazenon:cacao:ReservorioRiego;1",
        "origen": "Puente HTTP/REST (IoT Hub Device REST API)",
        "protocolo": "HTTPS 443",
        "intervalo_s": 120,
    },
    "dev10": {
        "device_id": "gz-10-perimetro-paho",
        "nombre": "Perímetro y bodega - Bodega Zenón",
        "zona": "Perímetro / bodega",
        "model_id": "dtmi:granjazenon:cacao:PerimetroBodega;1",
        "origen": "Cliente MQTT explícito (paho-mqtt) con SAS propio",
        "protocolo": "MQTT 8883 (crudo)",
        "intervalo_s": 30,
    },
}


def dispositivo(clave):
    """Devuelve la fila del catálogo y le agrega la clave derivada."""
    fila = dict(CATALOGO[clave])
    fila["device_key"] = derivar_clave_dispositivo(fila["device_id"])
    return fila


if __name__ == "__main__":
    print("Ambito de ID : {}".format(ID_SCOPE))
    print("Predio       : {} ({}, {})".format(PREDIO, LAT, LON))
    print("")
    print("{:8s} {:24s} {:12s} {}".format(
        "Clave", "Device ID", "Intervalo", "Clave derivada del dispositivo"))
    print("-" * 110)
    for clave in sorted(CATALOGO):
        d = dispositivo(clave)
        print("{:8s} {:24s} {:9d} s  {}".format(
            clave, d["device_id"], d["intervalo_s"], d["device_key"]))
