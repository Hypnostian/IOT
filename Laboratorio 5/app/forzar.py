"""Ordena al publicador forzar una variable durante unos minutos (prueba de la alerta).

Uso dentro del contenedor del publicador:
    docker compose exec publicador python forzar.py temperature 36 --minutos 6
"""

import argparse
import json
import os

import paho.mqtt.publish as publicar

parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
parser.add_argument("variable", choices=["temperature", "humidity", "illuminance"])
parser.add_argument("valor", type=float)
parser.add_argument("--minutos", type=float, default=6)
args = parser.parse_args()

dispositivo = os.getenv("DISPOSITIVO_ID", "estacion-01")
topico = f"lab5/{dispositivo}/control"
orden = {"variable": args.variable, "valor": args.valor, "duracion_s": args.minutos * 60}

publicar.single(
    topico,
    json.dumps(orden),
    qos=1,
    hostname=os.getenv("MQTT_HOST", "mosquitto"),
    port=int(os.getenv("MQTT_PUERTO", "1883")),
    client_id=f"forzar-{dispositivo}",
    auth={"username": os.environ["MQTT_USUARIO"], "password": os.environ["MQTT_CLAVE"]},
)
print(f"orden enviada a {topico}: {orden}")
